"""The owner's uploads live in R2 (CM-9, m-24957283; `docs/mudanza-subidas-r2.md`).

Until this story every photo, clip, document and voice sample the owner uploaded — and the
pieces made before 2026-10-06 — lived ONLY on the server's local `uploads` volume
(`uploads/{tenant}/…`, `generated/{tenant}/…`), with no backup. Now:

- **New uploads go to R2**, under `t/{tenant}/uploads/…` (`new_upload_key`), written once
  by `put_once`. `t/` is the bucket's locked prefix (no delete, no overwrite): these are
  the owner's originals, nothing ever deletes them, and every key carries a fresh
  `uuid4` so a write never meets an object of its own name.
- **What was on the volume is copied once** (`local_media_move`, by hand) to the same
  place: `uploads/{tenant}/{rest}` → `t/{tenant}/uploads/{rest}` and
  `generated/{tenant}/{rest}` → `t/{tenant}/generated-local/{rest}` (`moved_key_for`).
  Each file has a row in `local_media_moves`, the **key map**.
- **Every reader resolves an old key** that is no longer on disk through that map
  (`resolve_moved_key`): `R2ReadingMediaStore`, the WhatsApp attachment reader, the
  upload route of the app and `read_owner_media`. So a key kept in a JSON field that was
  never rewritten still reads its file.

Nothing here holds a whole file in memory that the caller did not already hold: uploads
stream from the file object, and `materialize` copies an object to a temporary file
range by range.
"""

from __future__ import annotations

import logging
import mimetypes
import re
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

#: Recorded on every `local_media_moves` row (provenance of the copy).
PIPELINE_VERSION = "uploads-to-r2-v1"

#: The local roots that are copied, and the folder each one gets under `t/{tenant}/`.
#: `generated-local/` and not `generated/`: the retention rule of ADR 39 empties
#: `t/{tenant}/generated/{draft}/` (`PURGEABLE_ROOTS`), and these old pieces never had a
#: retention decision — they are copied as they are, nothing more.
R2_FOLDER_OF_ROOT = {"uploads": "uploads", "generated": "generated-local"}
LOCAL_ROOTS = tuple(R2_FOLDER_OF_ROOT)

#: Waiting rooms on the volume: a file there is promoted (or discarded) by its own flow
#: within minutes, so it is never copied (the Galería's `gallery-staging`, CM-1, and the
#: catalog form's `catalog_staging`).
STAGING_DIRS = frozenset({"gallery-staging", "catalog_staging"})

#: A map row resolves only once its R2 copy was verified (same size and SHA-256).
MAPPED_STATUSES = ("verified", "local_deleted")

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
#: What an upload's name keeps in its key — the same rule as `Qualify/upload_names.py`:
#: letters (any script), digits, spaces, dots, dashes and underscores.
_SAFE_SEGMENT = re.compile(r"[^\w .-]+")

#: How many times a PUT is tried before the upload fails, and the wait before the n-th
#: retry (`n * _WAIT_SECONDS`).
_ATTEMPTS = 3
_WAIT_SECONDS = 0.5
#: The size of each ranged read when an object is copied to a temporary file.
_CHUNK = 8 * 1024 * 1024


#: What the owner reads when R2 did not keep an upload — nothing was saved anywhere, so
#: the next step is to upload it again (UX review 2026-11-06). One source for every screen.
UPLOAD_NOT_SAVED = "No pudimos guardar el archivo. Vuelve a subirlo en un momento."


#: An upload over `ObjectGate`'s single-PUT ceiling (300 MB): uploading it again cannot
#: work, so the owner is told to pick a lighter file (a video: the Galería's own wording,
#: `catalog.business_media.VIDEO_TOO_HEAVY_TEXT`).
UPLOAD_TOO_LARGE = "Ese archivo es muy pesado. Prueba con uno más liviano."


class UploadNotKept(RuntimeError):
    """R2 did not keep the upload (down, refused, or the key holds another file). The
    caller tells the owner to try again; nothing was saved locally."""


class UploadTooLarge(UploadNotKept):
    """The upload is over the single-PUT ceiling: no retry will ever keep it."""


def refusal_text(exc: BaseException, name: str = "") -> str:
    """What the owner reads for a refused upload: too large (a video says so in the
    Galería's words) or not saved — upload it again."""
    if isinstance(exc, UploadTooLarge):
        if (mimetypes.guess_type(name)[0] or "").startswith("video/"):
            from qualify_api.catalog.business_media import VIDEO_TOO_HEAVY_TEXT  # noqa: PLC0415

            return VIDEO_TOO_HEAVY_TEXT
        return UPLOAD_TOO_LARGE
    return UPLOAD_NOT_SAVED


# -- keys ----------------------------------------------------------------------------


def _segments_ok(parts: list[str]) -> bool:
    return bool(parts) and all(p not in ("", ".", "..") and "\\" not in p for p in parts)


def owner_upload_key(tenant_id: UUID, rest: str) -> str:
    """`t/{tenant}/uploads/{rest}` — `rest` is a POSIX path of plain segments."""
    if not isinstance(tenant_id, UUID):
        raise ValueError("an upload key is addressed by the tenant's UUID")
    if not _segments_ok(rest.split("/")):
        raise ValueError("upload key segment is not valid")
    return f"t/{tenant_id}/uploads/{rest}"


def safe_segment(name: str, *, fallback: str = "archivo", limit: int = 120) -> str:
    """A file name reduced to one safe key segment: its last path component, without
    separators, control characters or leading dots or spaces."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _SAFE_SEGMENT.sub("_", base).lstrip(". ")[-limit:]
    return cleaned or fallback


def new_upload_key(tenant_id: UUID, name: str, *, folder: str = "") -> str:
    """A fresh key for one upload: `t/{tenant}/uploads/[{folder}/]{uuid4}_{name}`. The
    `uuid4` makes every key new, which is what lets the bucket lock refuse overwrites
    without ever refusing one of ours."""
    leaf = f"{uuid4().hex}_{safe_segment(name)}"
    return owner_upload_key(tenant_id, f"{folder}/{leaf}" if folder else leaf)


def served_upload_tenant(key: str) -> UUID | None:
    """The tenant of a key the upload route may serve straight from R2 — an owner upload
    (`t/{tenant}/uploads/…`) or a copied old piece (`t/{tenant}/generated-local/…`) — or
    None for any other key (the Brand Kit, the pieces, the connections stay behind
    `/r2media` tokens)."""
    parts = key.split("/")
    if len(parts) < 4 or parts[0] != "t" or not _UUID.match(parts[1]):
        return None
    if parts[2] not in R2_FOLDER_OF_ROOT.values() or not _segments_ok(parts[3:]):
        return None
    return UUID(parts[1])


def local_key_tenant(local_key: str) -> UUID | None:
    """The tenant of an old local key (`uploads/{tenant}/…`, `generated/{tenant}/…`), or
    None when the key is not one (its business cannot be determined)."""
    parts = local_key.split("/")
    if len(parts) < 3 or parts[0] not in R2_FOLDER_OF_ROOT or not _UUID.match(parts[1]):
        return None
    if not _segments_ok(parts[2:]):
        return None
    return UUID(parts[1])


def moved_key_for(local_key: str) -> str | None:
    """Where the one-time copy puts an old local file in R2, or None when the key is not
    a tenant's local key."""
    tenant = local_key_tenant(local_key)
    if tenant is None:
        return None
    root, _, rest = local_key.split("/", 2)
    return f"t/{tenant}/{R2_FOLDER_OF_ROOT[root]}/{rest}"


def is_staging(local_key: str) -> bool:
    parts = local_key.split("/")
    return len(parts) >= 4 and parts[0] == "uploads" and parts[2] in STAGING_DIRS


#: `mimetypes` knows no font type on some systems (same table as `Qualify/brand_finish`).
_FONT_TYPES = {".ttf": "font/ttf", ".otf": "font/otf", ".woff": "font/woff", ".woff2": "font/woff2"}


def content_type_for(name: str, default: str = "application/octet-stream") -> str:
    """The content type an upload is stored (and served) with, from its file name."""
    suffix = Path(name).suffix.lower()
    return _FONT_TYPES.get(suffix) or mimetypes.guess_type(name)[0] or default


# -- R2 ------------------------------------------------------------------------------


def default_gate() -> Any:
    """The production `ObjectGate` (R2 from the environment)."""
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    return ObjectGate(R2ObjectStore(R2Settings.from_env()))


def _stream_size(fileobj: IO[bytes]) -> tuple[int, int]:
    origin = fileobj.seek(0, 1)
    end = fileobj.seek(0, 2)
    fileobj.seek(origin, 0)
    return origin, end - origin


def _held_size(gate: Any, tenant_id: UUID, key: str) -> int | None:
    from qualify_shared.objects.gate import ObjectNotFound  # noqa: PLC0415

    try:
        return int(gate.object_size(tenant_id, key))
    except ObjectNotFound:
        return None


def put_once(
    tenant_id: UUID,
    key: str,
    fileobj: IO[bytes],
    content_type: str,
    *,
    gate: Any = None,
) -> None:
    """Write one object to R2 ONCE, streamed from `fileobj` (seekable; read from its
    current position). Never overwrites: a key that already holds an object of this same
    size is taken as this write landed earlier (keys are fresh `uuid4`s or the copy's
    1:1 map, so nothing else writes them) and one of another size raises. A passing
    error is retried (`_ATTEMPTS`); a refusal that cannot change is not. Raises
    `UploadNotKept`."""
    from qualify_shared.objects import gate as gate_module  # noqa: PLC0415
    from qualify_shared.objects.config import R2ConfigurationError  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectSizeExceeded, UnsizedStream  # noqa: PLC0415
    from qualify_shared.objects.keys import TenantPrefixViolation  # noqa: PLC0415

    permanent = (
        R2ConfigurationError,
        UnsizedStream,
        TenantPrefixViolation,
        ValueError,
    )
    try:
        origin, size = _stream_size(fileobj)
    except OSError as exc:
        raise UploadNotKept("the upload stream is not seekable") from exc
    if size > gate_module.MAX_MEDIA_BYTES:  # before any R2 call: no retry changes it
        raise UploadTooLarge(f"{size} bytes, over the single-PUT ceiling")
    try:
        gate = gate if gate is not None else default_gate()
    except permanent as exc:
        raise UploadNotKept(f"{type(exc).__name__}: {exc}") from exc
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            held = _held_size(gate, tenant_id, key)
            if held == size:
                return
            if held is not None:
                raise UploadNotKept("the key already holds another file: never overwritten")
            fileobj.seek(origin, 0)
            gate.put_media(tenant_id, key, fileobj, content_type)
            return
        except UploadNotKept:
            raise
        except ObjectSizeExceeded as exc:
            raise UploadTooLarge(str(exc)) from exc
        except permanent as exc:
            raise UploadNotKept(f"{type(exc).__name__}: {exc}") from exc
        except Exception as exc:  # R2 down or the connection dropped: look, then retry
            if attempt == _ATTEMPTS:
                raise UploadNotKept(f"{type(exc).__name__}: {exc}") from exc
            logger.warning(
                "owner upload to R2 failed, attempt %d of %d: %s",
                attempt,
                _ATTEMPTS,
                type(exc).__name__,
            )
            time.sleep(_WAIT_SECONDS * attempt)


def put_bytes_once(
    tenant_id: UUID, key: str, data: bytes, content_type: str, *, gate: Any = None
) -> None:
    """`put_once` for bytes the caller already holds."""
    import io  # noqa: PLC0415

    put_once(tenant_id, key, io.BytesIO(data), content_type, gate=gate)


@contextmanager
def materialize(tenant_id: UUID, key: str, *, gate: Any = None) -> Iterator[Path]:
    """An R2 object as a temporary file, copied in `_CHUNK` ranged reads (never the whole
    object in memory) — for readers that need a path (FFmpeg, Whisper, a voice sample).
    The file is removed on exit. `gate` may be a factory (built only here)."""
    gate = _gate_of(gate)
    size = int(gate.object_size(tenant_id, key))
    suffix = Path(key).suffix[:10]
    with tempfile.NamedTemporaryFile(prefix="qualify-r2-", suffix=suffix, delete=False) as out:
        path = Path(out.name)
        try:
            start = 0
            while start < size:
                end = min(start + _CHUNK, size) - 1
                stream = gate.open_range(tenant_id, key, start, end)
                try:
                    out.write(stream.read())
                finally:
                    close = getattr(stream, "close", None)
                    if callable(close):
                        close()
                start = end + 1
        except BaseException:
            out.close()
            path.unlink(missing_ok=True)
            raise
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


# -- the key map ---------------------------------------------------------------------

#: Map rows never change once verified, so a hit is kept for the life of the process
#: (bounded); a miss is never kept — the copy may verify that key a minute later.
_CACHE_LIMIT = 4096
_moved_cache: dict[tuple[UUID, str], str] = {}
_cache_lock = threading.Lock()


def resolve_moved_key(tenant_id: UUID, local_key: str) -> str | None:
    """The verified R2 key of an old local key of THIS tenant, or None (not copied yet,
    or not a key of this tenant). Read through `tenant_session`: RLS keeps another
    tenant's map out of reach whatever the key says."""
    if local_key_tenant(local_key) != tenant_id:
        return None
    cached = _moved_cache.get((tenant_id, local_key))
    if cached is not None:
        return cached
    from qualify_shared.db import tenant_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    with tenant_session(tenant_id) as session:
        found = session.scalar(
            text(
                "SELECT r2_key FROM local_media_moves WHERE local_key = :key"
                " AND status IN ('verified', 'local_deleted')"
            ),
            {"key": local_key},
        )
    if found:
        with _cache_lock:
            if len(_moved_cache) >= _CACHE_LIMIT:
                _moved_cache.clear()
            _moved_cache[(tenant_id, local_key)] = found
    return found or None


def clear_moved_cache() -> None:
    with _cache_lock:
        _moved_cache.clear()


Resolver = Callable[[UUID, str], "str | None"]


def moved_or_none(local_key: str, resolver: Resolver | None = None) -> str | None:
    """`resolve_moved_key` for a key whose tenant is taken from the key itself — for a
    reader that already proved the key is the caller's (`owned_by`). A map that cannot
    be read answers None (the caller keeps its own «not found»)."""
    tenant = local_key_tenant(local_key)
    if tenant is None:
        return None
    try:
        return (resolver or resolve_moved_key)(tenant, local_key)
    except Exception as exc:  # the database down must not turn a miss into a crash
        logger.warning("key map unreadable for a local key: %s", type(exc).__name__)
        return None


def read_owner_media(
    tenant_id: UUID,
    key: str,
    *,
    root: Path,
    gate: Any = None,
    resolver: Resolver | None = None,
) -> bytes:
    """The bytes of one of THIS tenant's files, wherever they are: R2 for an R2 key; the
    volume for an old local key still on disk; R2 through the key map for one that was
    copied and removed from disk. Raises `PermissionError` for another tenant's key and
    `FileNotFoundError` when it is nowhere."""
    from qualify_shared.objects.keys import is_object_store_key  # noqa: PLC0415

    from qualify_api.creative.media import LocalMediaStore, owned_by  # noqa: PLC0415

    if not owned_by(tenant_id, key):
        raise PermissionError("media key is not this tenant's")
    if is_object_store_key(key):
        return _read_r2(gate, tenant_id, key)
    try:
        return LocalMediaStore(root).read(key)
    except FileNotFoundError:
        moved = moved_or_none(key, resolver)
        if moved is None:
            raise
        return _read_r2(gate, tenant_id, moved)


def _gate_of(gate: Any) -> Any:
    """`gate` itself, or — None or a factory — the gate it stands for, built only now."""
    if gate is None:
        return default_gate()
    if callable(gate) and not hasattr(gate, "open_object"):
        return gate()
    return gate


def _read_r2(gate: Any, tenant_id: UUID, key: str) -> bytes:
    gate = _gate_of(gate)
    stream = gate.open_object(tenant_id, key)
    try:
        return stream.read()
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()


@contextmanager
def owner_media_path(
    tenant_id: UUID,
    key: str,
    *,
    root: Path,
    gate: Any = None,
    resolver: Resolver | None = None,
) -> Iterator[Path]:
    """A local path to one of THIS tenant's files — the file itself while it is still on
    the volume, else a temporary copy of its R2 object (`materialize`)."""
    from qualify_shared.objects.keys import is_object_store_key  # noqa: PLC0415

    from qualify_api.creative.media import LocalMediaStore, owned_by  # noqa: PLC0415

    if not owned_by(tenant_id, key):
        raise PermissionError("media key is not this tenant's")
    if not is_object_store_key(key):
        path = LocalMediaStore(root)._path(key)
        if path.is_file():
            yield path
            return
        moved = moved_or_none(key, resolver)
        if moved is None:
            raise FileNotFoundError(key)
        key = moved
    with materialize(tenant_id, key, gate=gate) as path:
        yield path

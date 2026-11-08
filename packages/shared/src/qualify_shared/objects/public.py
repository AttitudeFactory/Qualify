"""The public door to the object plane (ADR 44, m-24921056 VE-04a; decision #9 of
`docs/epica-video-por-partes.md` §2).

`ObjectGate` only knows `t/{tenant}/…`: every method routes its key through
`require_tenant_prefix`, and `delete_prefix` only empties folders under `PURGEABLE_ROOTS`
of one tenant. A reel's shared analysis has no tenant — its source video and frames live
under `public/reel-analyses/…`, a key that names no business (0119 docstring) — so it
needs a door of its own instead of a hole in the tenant one. «Public» means «no business
in the key», NOT «served without a session»: nothing here presigns or exposes a URL.

The door is closed by construction, not by discipline:

- `PUBLIC_ROOTS` lists the only roots: `reel-analyses/` (VE-04a) and `reel-covers/` (ADR 42
  R12, m-24854859, a reviewed addition with its own key shape);
- `require_public_key` accepts EXACTLY the two key shapes of an analysis —
  `public/reel-analyses/(instagram|tiktok)/<post_id>/<uuid>/source/source.mp4` and
  `…/frames/NN-N.jpg` — and the one of a reel's cover,
  `public/reel-covers/(instagram|tiktok)/<reel_id>.jpg` (deterministic: two businesses
  whose run keeps the same reel write ONE object), and rejects `..`, `//`, a missing
  segment and anything else;
- a cover is written as `image/jpeg` only, at most `MAX_COVER_BYTES`;
- `delete_public_prefix` empties only `…/<uuid>/source/` or `…/<uuid>/frames/`, never a
  network, a reel or the root (the 30-day purge of VE-12 calls it), and never a cover;
  `delete_public_object` deletes exactly one cover key and nothing else (the 30-day purge
  of the covers);
- only `qualify_api.referentes.reel_analysis*`, the 30-day purges (`reel_retention`,
  `delete_public_prefix` and `delete_public_object` only), «Replicar» (`reel_reference`,
  `open_public` only) and the covers (`reel_covers`, `put_public` and `open_public` only)
  may import this module, and the screen (`Qualify/`) never does (static test in
  `packages/api/tests/test_reel_analysis_door_sanctity.py`).

`ObjectGate` and `PURGEABLE_ROOTS` are unchanged: `delete_prefix` still refuses
`public/…` (test).
"""

from __future__ import annotations

import re
from typing import IO
from uuid import UUID

from qualify_shared.objects.gate import (
    DELETE_BATCH,
    MAX_MEDIA_BYTES,
    ObjectNotFound,
    ObjectSizeExceeded,
    ObjectStore,
    PrefixDeletion,
    StoredObject,
    _stream_length,
)

PUBLIC_PREFIX = "public/"
#: The only roots under `public/`. A new one is a reviewed decision, like the gate's
#: method set — and it brings its own exact key shape below.
PUBLIC_ROOTS: tuple[str, ...] = ("reel-analyses/", "reel-covers/")

NETWORKS = ("instagram", "tiktok")
#: An Instagram shortcode or a TikTok numeric id: never a slash, a dot or a space.
_POST_ID = r"[A-Za-z0-9_-]{1,64}"
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_ANALYSIS = rf"public/reel-analyses/(?:{'|'.join(NETWORKS)})/{_POST_ID}/{_UUID}/"
_KEY = re.compile(rf"{_ANALYSIS}(?:source/source\.mp4|frames/[0-9]{{2}}-[0-9]{{1,2}}\.jpg)")
_DELETABLE = re.compile(rf"{_ANALYSIS}(?:source|frames)/")
#: R12: one cover per reel, named by the reel alone.
_COVER_KEY = re.compile(rf"public/reel-covers/(?:{'|'.join(NETWORKS)})/{_POST_ID}\.jpg")

SOURCE_CONTENT_TYPE = "video/mp4"
FRAME_CONTENT_TYPE = "image/jpeg"
COVER_CONTENT_TYPE = "image/jpeg"
#: A remuxed ≤ 60 s source is at most the 80 MiB download; frames are ~150 KB.
MAX_PUBLIC_BYTES = 80 * 1024 * 1024
#: A cover is re-encoded to a JPEG of at most 720 px at quality 80 (~100 KB): a body ten
#: times that is not a cover.
MAX_COVER_BYTES = 1024 * 1024


class PublicKeyViolation(Exception):
    """The key is not one of the public door's exact shapes. The key is not echoed: a
    rejected key is input, and an exception message is a log line waiting to happen."""


def is_reel_post_id(post_id: str) -> bool:
    """True for an id this door can key: an Instagram shortcode or a TikTok numeric id
    (letters, digits, `_`, `-`; 1–64). Checked at request and enqueue time, so a malformed
    id never reaches a download."""
    return isinstance(post_id, str) and re.fullmatch(_POST_ID, post_id) is not None


def _check_post(network: str, post_id: str) -> None:
    if network not in NETWORKS:
        raise PublicKeyViolation("unknown network for a public reel key")
    if not re.fullmatch(_POST_ID, post_id or ""):
        raise PublicKeyViolation("post_id is not a plain reel identifier")


def reel_analysis_root(network: str, post_id: str, analysis_id: UUID) -> str:
    """`public/reel-analyses/{network}/{post_id}/{analysis_id}/` — one analysis' folder."""
    _check_post(network, post_id)
    return f"{PUBLIC_PREFIX}reel-analyses/{network}/{post_id}/{UUID(str(analysis_id))}/"


def reel_source_key(network: str, post_id: str, analysis_id: UUID) -> str:
    return f"{reel_analysis_root(network, post_id, analysis_id)}source/source.mp4"


def reel_frame_key(network: str, post_id: str, analysis_id: UUID, shot: int, n: int) -> str:
    """`…/frames/{shot:02d}-{n}.jpg` — shot 0–99, frame 0–99 within the shot."""
    if not (0 <= shot <= 99 and 0 <= n <= 99):
        raise PublicKeyViolation("frame position out of range")
    return f"{reel_analysis_root(network, post_id, analysis_id)}frames/{shot:02d}-{n}.jpg"


def reel_cover_key(network: str, reel_id: str) -> str:
    """`public/reel-covers/{network}/{reel_id}.jpg` — the one cover of a reel (R12)."""
    _check_post(network, reel_id)
    return f"{PUBLIC_PREFIX}reel-covers/{network}/{reel_id}.jpg"


def reel_source_prefix(network: str, post_id: str, analysis_id: UUID) -> str:
    return f"{reel_analysis_root(network, post_id, analysis_id)}source/"


def reel_frames_prefix(network: str, post_id: str, analysis_id: UUID) -> str:
    return f"{reel_analysis_root(network, post_id, analysis_id)}frames/"


def _plain(key: object) -> bool:
    return isinstance(key, str) and ".." not in key and "//" not in key


def is_cover_key(key: str) -> bool:
    """True when `key` is exactly a reel's cover (`reel_cover_key`)."""
    return _plain(key) and _COVER_KEY.fullmatch(key) is not None


def require_public_key(key: str) -> str:
    """`key` unchanged if it is exactly a source or a frame of one analysis, or a reel's
    cover; raise otherwise (`..`, another root, a missing segment, a tenant key, anything
    else)."""
    if not _plain(key) or not (_KEY.fullmatch(key) or _COVER_KEY.fullmatch(key)):
        raise PublicKeyViolation("not a public reel object key")
    return key


def require_cover_key(key: str) -> str:
    """`key` unchanged if it is exactly a reel's cover; raise otherwise — an analysis'
    source or frame included."""
    if not is_cover_key(key):
        raise PublicKeyViolation("not a public reel-cover key")
    return key


def require_public_prefix(prefix: str) -> str:
    """`prefix` unchanged if it is one analysis' `source/` or `frames/` folder."""
    if (
        not isinstance(prefix, str)
        or ".." in prefix
        or "//" in prefix
        or not _DELETABLE.fullmatch(prefix)
    ):
        raise PublicKeyViolation("not a deletable public reel-analysis folder")
    return prefix


class PublicObjectGate:
    """Access to `public/reel-analyses/…` and `public/reel-covers/…`. One instance wraps
    one store (the same R2 bucket as `ObjectGate`; isolation lives in the key checks,
    never in the store)."""

    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def put_public(self, object_key: str, fileobj: IO[bytes], content_type: str) -> None:
        """Write a source, a frame or a cover. Single PUT, hard size ceiling, type
        required: a cover is a JPEG, never anything else."""
        key = require_public_key(object_key)
        if is_cover_key(key):
            allowed, ceiling = (COVER_CONTENT_TYPE,), MAX_COVER_BYTES
        else:
            allowed, ceiling = (SOURCE_CONTENT_TYPE, FRAME_CONTENT_TYPE), MAX_PUBLIC_BYTES
        if content_type not in allowed:
            raise ValueError("a public reel object is an MP4 source or a JPEG frame or cover")
        size = _stream_length(fileobj)
        if size > min(ceiling, MAX_MEDIA_BYTES):
            raise ObjectSizeExceeded(f"public object is {size} bytes, over the ceiling")
        self._store.put(key, fileobj, content_type)

    def put_public_if_absent(self, object_key: str, fileobj: IO[bytes], content_type: str) -> bool:
        """`put_public`, unless the key already exists: then nothing is written and False
        is returned. The production bucket's lock policy refuses to overwrite an object
        («ObjectLockedByBucketPolicy», measured live 2026-11-05), so a retried analysis
        must not PUT what an earlier attempt already stored. Safe because these keys are
        per analysis row and their content is deterministic for it (same source, same
        sampling version). A store without HEAD support just writes."""
        key = require_public_key(object_key)
        size = getattr(self._store, "size", None)
        if size is not None:
            try:
                size(key)
            except (ObjectNotFound, NotImplementedError):
                pass
            else:
                return False
        self.put_public(key, fileobj, content_type)
        return True

    def open_public(self, object_key: str) -> IO[bytes]:
        """Open a stored source, frame or cover (re-checked: a key read from a row is
        input)."""
        return self._store.open(require_public_key(object_key))

    def public_size(self, object_key: str) -> int:
        key = require_public_key(object_key)
        return self._store.size(key)  # type: ignore[attr-defined]

    def open_public_range(self, object_key: str, start: int, end: int) -> IO[bytes]:
        key = require_public_key(object_key)
        return self._store.open_range(key, start, end)  # type: ignore[attr-defined]

    def delete_public_prefix(self, prefix: str, *, execute: bool = False) -> PrefixDeletion:
        """List one analysis' `source/` or `frames/` folder and, with `execute=True`,
        delete it. A dry run reports what it WOULD delete; idempotent like
        `ObjectGate.delete_prefix`."""
        key = require_public_prefix(prefix)
        found: list[StoredObject] = list(self._store.list_prefix(key))  # type: ignore[attr-defined]
        if execute:
            keys = [item.key for item in found]
            for start in range(0, len(keys), DELETE_BATCH):
                self._store.delete_keys(keys[start : start + DELETE_BATCH])  # type: ignore[attr-defined]
        return PrefixDeletion(objects=len(found), bytes=sum(item.size for item in found))

    def delete_public_object(self, object_key: str, *, execute: bool = False) -> PrefixDeletion:
        """Find one reel's cover and, with `execute=True`, delete it — that key and no
        other (an analysis' source or frame is refused). A dry run reports what it WOULD
        delete; a cover already gone deletes nothing (idempotent)."""
        key = require_cover_key(object_key)
        found = [
            item
            for item in self._store.list_prefix(key)  # type: ignore[attr-defined]
            if item.key == key
        ]
        if execute and found:
            self._store.delete_keys([key])  # type: ignore[attr-defined]
        return PrefixDeletion(objects=len(found), bytes=sum(item.size for item in found))


__all__ = [
    "COVER_CONTENT_TYPE",
    "FRAME_CONTENT_TYPE",
    "MAX_COVER_BYTES",
    "MAX_PUBLIC_BYTES",
    "PUBLIC_ROOTS",
    "SOURCE_CONTENT_TYPE",
    "is_cover_key",
    "is_reel_post_id",
    "PublicKeyViolation",
    "PublicObjectGate",
    "reel_analysis_root",
    "reel_cover_key",
    "reel_frame_key",
    "reel_frames_prefix",
    "reel_source_key",
    "reel_source_prefix",
    "require_cover_key",
    "require_public_key",
    "require_public_prefix",
]

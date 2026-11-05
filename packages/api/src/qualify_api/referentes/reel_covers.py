"""The covers of «Ideas para tus reels», kept in R2 (ADR 42 R12 / §2.11, m-24854859).

Since R7 the screen only reads what the weekly run stored, and a cover's signed CDN URL
dies in ~4 days on Instagram (~1 on TikTok) while an idea lives 7. So the run copies the
cover of each reel it keeps as an IDEA — never of a mere candidate — while the URL is
alive, and the screen serves that copy (`Qualify/avatar_proxy.reel_cover`, through
`open_cover`).

- `copy_idea_covers(tenant, run, sources)` — called by the `reels-worker`'s production
  hook of an `ok` run (`reel_worker.production_run`), before VE-04a's analysis; never by
  `scoped_run` (a `--tenant` worker writes no public R2 object, FN2). Per idea: a reel
  whose copy exists only moves `cover_r2_used_at` forward; otherwise, while the URL's own
  signature has not expired (`cdn_media.signature_expired`), the cover is downloaded under
  the cover rules (`cdn_media.fetch_cover`: the network's CDN, https on 443, no
  credentials, no redirects, 8 s, at most 3 MB), re-encoded (`cdn_media.reencode_cover`:
  JPEG, at most 720 px, quality 80, no metadata), PUT through the public door and only
  then recorded (`UPDATE … WHERE cover_r2_key IS NULL`, through `tenant_session`, as the
  run writes `public_reels`). A failure is logged with the reel and a reason — never the
  URL — and never changes the run: the run already ended `ok`, and this never raises.
- `open_cover(network, reel_id)` — the copy's bytes for the route, or None. It reads R2
  through its own client, bounded for a request path (`ROUTE_CONNECT_SECONDS`,
  `ROUTE_READ_SECONDS`, one attempt): a slow R2 costs the screen a placeholder, not a
  thread held for minutes.
- `PostgresCoverStore` — those two writes, plus what the 30-day purge reads and clears
  (`reel_retention.purge_reel_covers`, through `global_session`: the copies belong to no
  business). `MemoryCoverStore` is its offline twin over a `MemoryReelRunStore`.

The key is the reel's alone (`public/reel-covers/{network}/{reel_id}.jpg`, 0127 pins it):
two businesses whose runs keep the same reel write ONE object, and the second run only
moves the date. Of the public R2 door this module calls `put_public` and `open_public`
only (static test). It never calls a vendor and charges nobody: a CDN download costs no
credit.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from io import BytesIO
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

import httpx
from qualify_shared.db.session import global_session, tenant_session
from qualify_shared.objects.config import R2ConfigurationError
from qualify_shared.objects.gate import ObjectNotFound
from qualify_shared.objects.public import (
    COVER_CONTENT_TYPE,
    NETWORKS,
    PublicKeyViolation,
    PublicObjectGate,
    is_reel_post_id,
    reel_cover_key,
)
from sqlalchemy import text

from qualify_api.vendors.cdn_media import (
    COVER_TIMEOUT_SECONDS,
    CoverUnavailable,
    fetch_cover,
    reencode_cover,
    signature_expired,
)

if TYPE_CHECKING:
    from qualify_api.referentes.reel_runs import IdeaSource
    from qualify_api.referentes.reel_store import MemoryReelRunStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DueCover:
    """A copy whose last use is old enough to purge."""

    network: str
    reel_id: str
    key: str
    used_at: datetime


class CoverStore(Protocol):
    """Where a copy is recorded (`public_reels.cover_r2_key` / `cover_r2_used_at`, 0127)."""

    def bump_cover(self, tenant_id: UUID, network: str, reel_id: str, now: datetime) -> bool:
        """An idea used the copy again: move its date forward (never back). False when
        the reel has no copy (any more)."""
        ...

    def record_cover(
        self, tenant_id: UUID, network: str, reel_id: str, key: str, now: datetime
    ) -> bool:
        """The copy was just PUT: set the key and its date, only while the reel has none.
        False when it already had one (another business's run copied it meanwhile)."""
        ...

    def due_covers(
        self, cutoff: datetime, *, after: tuple[datetime, str, str] | None, limit: int
    ) -> list[DueCover]:
        """Copies last used at or before `cutoff`, oldest first, after the keyset
        `(used_at, network, reel_id)`."""
        ...

    def purge_cover(
        self, network: str, reel_id: str, cutoff: datetime, delete: Callable[[str], object]
    ) -> bool:
        """While the reel's copy is still due (re-checked under a row lock), `delete(key)`
        and only then clear the key and its date. False when it was used again or cleared
        meanwhile; an exception from `delete` leaves the row as it was."""
        ...


@dataclass
class CoverReport:
    """What `copy_idea_covers` did with one run's ideas."""

    ideas: int = 0
    #: Downloaded, re-encoded and PUT.
    copied: int = 0
    #: The reel already had a copy: only its date moved.
    reused: int = 0
    #: Nothing to copy from: no URL, its signature expired, or not a reel the door keys.
    skipped: int = 0
    #: The download, the re-encode, R2 or the database failed (logged, never raised).
    failed: int = 0


# --------------------------------------------------------------------------------------
# the stores
# --------------------------------------------------------------------------------------

_BUMP = text(
    "UPDATE public_reels SET cover_r2_used_at = GREATEST(cover_r2_used_at, :now) "
    "WHERE network = :network AND reel_id = :reel_id AND cover_r2_key IS NOT NULL"
)
_RECORD = text(
    "UPDATE public_reels SET cover_r2_key = :key, cover_r2_used_at = :now "
    "WHERE network = :network AND reel_id = :reel_id AND cover_r2_key IS NULL"
)


class PostgresCoverStore:
    """`CoverStore` over 0127. The run's two writes go through `tenant_session` (the run's
    business; `public_reels` has no policy to scope them, as in `reel_store`); the purge
    reads and clears through `global_session` — it has no business at hand."""

    def bump_cover(self, tenant_id: UUID, network: str, reel_id: str, now: datetime) -> bool:
        with tenant_session(tenant_id) as session:
            done = session.execute(_BUMP, {"now": now, "network": network, "reel_id": reel_id})
            return bool(done.rowcount)

    def record_cover(
        self, tenant_id: UUID, network: str, reel_id: str, key: str, now: datetime
    ) -> bool:
        with tenant_session(tenant_id) as session:
            done = session.execute(
                _RECORD, {"key": key, "now": now, "network": network, "reel_id": reel_id}
            )
            return bool(done.rowcount)

    def due_covers(
        self, cutoff: datetime, *, after: tuple[datetime, str, str] | None, limit: int
    ) -> list[DueCover]:
        keyset = ""
        params: dict[str, object] = {"cutoff": cutoff, "limit": limit}
        if after is not None:
            keyset = "AND (cover_r2_used_at, network, reel_id) > (:at, :network, :reel_id) "
            params.update(at=after[0], network=after[1], reel_id=after[2])
        with global_session() as session:
            rows = session.execute(
                text(
                    "SELECT network, reel_id, cover_r2_key, cover_r2_used_at FROM public_reels "
                    "WHERE cover_r2_key IS NOT NULL AND cover_r2_used_at <= :cutoff "
                    f"{keyset}ORDER BY cover_r2_used_at, network, reel_id LIMIT :limit"
                ),
                params,
            ).all()
        return [
            DueCover(r.network, r.reel_id, str(r.cover_r2_key), r.cover_r2_used_at) for r in rows
        ]

    def purge_cover(
        self, network: str, reel_id: str, cutoff: datetime, delete: Callable[[str], object]
    ) -> bool:
        params = {"network": network, "reel_id": reel_id, "cutoff": cutoff}
        with global_session() as session:
            # the row lock holds an idea's bump until the copy is gone and the row cleared:
            # that bump then finds no copy, and its run copies the cover again
            key = session.scalar(
                text(
                    "SELECT cover_r2_key FROM public_reels WHERE network = :network "
                    "AND reel_id = :reel_id AND cover_r2_key IS NOT NULL "
                    "AND cover_r2_used_at <= :cutoff FOR UPDATE"
                ),
                params,
            )
            if key is None:
                return False
            delete(str(key))
            session.execute(
                text(
                    "UPDATE public_reels SET cover_r2_key = NULL, cover_r2_used_at = NULL "
                    "WHERE network = :network AND reel_id = :reel_id"
                ),
                params,
            )
            return True


class MemoryCoverStore:
    """The offline twin: the key lives on the run store's own `PublicReel` (so its
    `ideas()` sees it) and the last use here."""

    def __init__(self, runs: MemoryReelRunStore | None = None) -> None:
        if runs is None:
            from qualify_api.referentes.reel_store import MemoryReelRunStore  # noqa: PLC0415

            runs = MemoryReelRunStore()
        self.runs = runs
        self.used: dict[tuple[str, str], datetime] = {}
        self._lock = threading.Lock()

    def bump_cover(self, tenant_id: UUID, network: str, reel_id: str, now: datetime) -> bool:
        with self._lock:
            reel = self.runs.reels.get((network, reel_id))
            if reel is None or reel.cover_r2_key is None:
                return False
            last = self.used.get((network, reel_id))
            self.used[(network, reel_id)] = now if last is None else max(last, now)
            return True

    def record_cover(
        self, tenant_id: UUID, network: str, reel_id: str, key: str, now: datetime
    ) -> bool:
        with self._lock:
            reel = self.runs.reels.get((network, reel_id))
            if reel is None or reel.cover_r2_key is not None:
                return False
            self.runs.reels[(network, reel_id)] = replace(reel, cover_r2_key=key)
            self.used[(network, reel_id)] = now
            return True

    def due_covers(
        self, cutoff: datetime, *, after: tuple[datetime, str, str] | None, limit: int
    ) -> list[DueCover]:
        with self._lock:
            due = sorted(
                (used, network, reel_id)
                for (network, reel_id), used in self.used.items()
                if used <= cutoff and (after is None or (used, network, reel_id) > after)
            )
            return [
                DueCover(
                    network, reel_id, str(self.runs.reels[(network, reel_id)].cover_r2_key), used
                )
                for used, network, reel_id in due[:limit]
            ]

    def purge_cover(
        self, network: str, reel_id: str, cutoff: datetime, delete: Callable[[str], object]
    ) -> bool:
        with self._lock:
            reel = self.runs.reels.get((network, reel_id))
            used = self.used.get((network, reel_id))
            if reel is None or reel.cover_r2_key is None or used is None or used > cutoff:
                return False
            delete(reel.cover_r2_key)
            self.runs.reels[(network, reel_id)] = replace(reel, cover_r2_key=None)
            del self.used[(network, reel_id)]
            return True


_store: CoverStore | None = None
_store_guard = threading.Lock()


def default_store() -> CoverStore:
    global _store
    with _store_guard:
        if _store is None:
            _store = PostgresCoverStore()
        return _store


#: The route's R2 read (an `<img>` request): seconds to connect and to read, one attempt.
ROUTE_CONNECT_SECONDS = 2.0
ROUTE_READ_SECONDS = 5.0

_gate: PublicObjectGate | None = None
_route: PublicObjectGate | None = None
#: boto3's default session is not thread-safe: both doors are built once, under this lock.
_gate_guard = threading.Lock()


def _r2_gate(*, bounded: bool) -> PublicObjectGate:
    """The public door over the real R2 bucket; `bounded`: with the route's short timeouts
    and no retry."""
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    settings = R2Settings.from_env()
    if bounded:
        settings = settings.bounded(
            connect=ROUTE_CONNECT_SECONDS, read=ROUTE_READ_SECONDS, attempts=1
        )
    return PublicObjectGate(R2ObjectStore(settings))


def _route_gate() -> PublicObjectGate:
    """The route's door: built once, bounded (`R2ConfigurationError` without R2)."""
    global _route
    with _gate_guard:
        if _route is None:
            _route = _r2_gate(bounded=True)
        return _route


def _default_gate() -> PublicObjectGate:
    """The public door over the real R2 bucket, built once (`R2ConfigurationError` when the
    environment has no R2: then nothing is copied and the screen shows its placeholder)."""
    global _gate
    if _gate is None:
        _gate = _r2_gate(bounded=False)
    return _gate


# --------------------------------------------------------------------------------------
# the copy
# --------------------------------------------------------------------------------------


class _Lazy:
    """What a copy needs only when one is made: the R2 door and an HTTP client. A run
    whose ideas all have their copy touches neither."""

    def __init__(self, gate: PublicObjectGate | None, client: httpx.Client | None) -> None:
        self._gate = gate
        self._client = client
        self._owned: httpx.Client | None = None

    def gate(self) -> PublicObjectGate:
        if self._gate is None:
            self._gate = _default_gate()
        return self._gate

    def client(self) -> httpx.Client:
        if self._client is None:
            self._owned = self._client = httpx.Client(timeout=COVER_TIMEOUT_SECONDS)
        return self._client

    def close(self) -> None:
        if self._owned is not None:
            self._owned.close()


def copy_idea_covers(
    tenant_id: UUID,
    run_id: UUID,
    sources: Sequence[IdeaSource],
    *,
    gate: PublicObjectGate | None = None,
    store: CoverStore | None = None,
    client: httpx.Client | None = None,
    clock: Callable[[], float] = time.time,
) -> CoverReport:
    """Copy the cover of each idea of an `ok` run to R2, or move the date of the copy it
    already has (see the module docstring). Never raises for a failure of its own: what
    failed is logged and counted, and the run goes on."""
    report = CoverReport()
    lazy = _Lazy(gate, client)
    try:
        active = store or default_store()
        for source in sources:
            report.ideas += 1
            try:
                outcome = _copy_one(tenant_id, source, active, lazy, clock)
            except CoverUnavailable as exc:
                outcome = "failed"
                logger.info(
                    "reels run %s: cover of %s/%s not copied: %s",
                    run_id,
                    source.network,
                    source.post_id,
                    exc.reason,
                )
            except R2ConfigurationError:
                outcome = "failed"
                logger.warning("reels run %s: no R2 configured, covers not copied", run_id)
            except Exception as exc:  # noqa: BLE001 — R2 or the database: the next idea goes on
                outcome = "failed"
                logger.warning(
                    "reels run %s: cover of %s/%s not copied: %s",
                    run_id,
                    source.network,
                    source.post_id,
                    type(exc).__name__,
                )
            setattr(report, outcome, getattr(report, outcome) + 1)
    except Exception:  # noqa: BLE001 — never the run's failure
        logger.exception("reels run %s: the copy of its covers failed", run_id)
    finally:
        lazy.close()
    logger.info(
        "reels run %s covers: ideas=%d copied=%d reused=%d skipped=%d failed=%d",
        run_id,
        report.ideas,
        report.copied,
        report.reused,
        report.skipped,
        report.failed,
    )
    return report


def _copy_one(
    tenant_id: UUID,
    source: IdeaSource,
    store: CoverStore,
    lazy: _Lazy,
    clock: Callable[[], float],
) -> str:
    """`copied`, `reused` or `skipped` for one idea; raises on a failure."""
    network, reel_id = source.network, source.post_id
    if network not in NETWORKS or not is_reel_post_id(reel_id):
        return "skipped"
    moment = clock()
    now = datetime.fromtimestamp(moment, UTC)
    if getattr(source, "cover_r2_key", None):
        if store.bump_cover(tenant_id, network, reel_id, now):
            return "reused"
        # purged since the run read the reel: copied again below, like a new idea
    url = getattr(source, "cover_url", "") or ""
    if not url or signature_expired(url, now=moment):
        return "skipped"
    content, _ = fetch_cover(url, client=lazy.client())
    jpeg = reencode_cover(content)
    key = reel_cover_key(network, reel_id)
    lazy.gate().put_public(key, BytesIO(jpeg), COVER_CONTENT_TYPE)
    if store.record_cover(tenant_id, network, reel_id, key, now):
        return "copied"
    # another business's run recorded the same object meanwhile: this idea used it
    if store.bump_cover(tenant_id, network, reel_id, now):
        return "copied"
    raise LookupError("the reel has no public_reels row to record its cover on")


# --------------------------------------------------------------------------------------
# the route's read
# --------------------------------------------------------------------------------------


def open_cover(network: str, reel_id: str, *, gate: PublicObjectGate | None = None) -> bytes | None:
    """The R2 copy of a reel's cover, or None: no copy (never made, or purged), a reel the
    door cannot key, R2 not configured or unreachable — the screen then shows its
    placeholder. Blocking: the route runs it in a thread."""
    try:
        key = reel_cover_key(network, reel_id)
    except PublicKeyViolation:
        return None
    try:
        with (gate or _route_gate()).open_public(key) as body:
            return body.read()
    except (ObjectNotFound, KeyError):
        return None
    except R2ConfigurationError:
        logger.debug("reel covers: no R2 configured")
        return None
    except Exception as exc:  # noqa: BLE001 — a picture must never break the page
        logger.warning(
            "reel cover %s/%s unreadable from R2: %s", network, reel_id, type(exc).__name__
        )
        return None


__all__ = [
    "COVER_CONTENT_TYPE",
    "CoverReport",
    "CoverStore",
    "DueCover",
    "MemoryCoverStore",
    "PostgresCoverStore",
    "copy_idea_covers",
    "default_store",
    "open_cover",
]

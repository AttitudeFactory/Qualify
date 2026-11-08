"""The window of a reel's public source that an «Igual al original» part sends to Seedance
(ADR 44, m-24921059 VE-04d; design `docs/diseno-video-por-planos.md` §4.2 and §8).

A part in `edit` mode needs 4-10 whole seconds of the original reel. The cut is written once
into the part's own folder of reel cuts,
`reel-windows/{tenant}/{draft_id}/source-window-{analysis_id}-{start}-{end}.mp4`, so that a
second call (a retry, a regenerated part) finds it instead of cutting again: the copy exists
for idempotency, NOT to outlive the source. The analysed source is global and purged 30 days
after the analysis (F9, VE-12), and RA5 of the design reads F9 strictly: the per-business
purge drops `source-window-*.mp4` on the same 30-day clock (VE-12, not this module). The
root is outside `t/` because the production bucket's lock on `t/` refuses deletes
(m-24971181); cuts written under `t/{tenant}/generated/` before 2026-11-06 stay there,
undeletable. A part
regenerated after the source is gone gets `source_purged` and falls back to `reference`.
The analysis id is in the key, so a part whose reference reel changes never reuses the old
reel's cut.

Who reads and writes what — the contract of the backend handoff (VE-04d):

- the analysis row is read as `qualify_app` through `tenant_session` (`AnalysisRequests.get`,
  the column SELECT of 0119); never with `qualify_reels_worker` or `qualify_creative_worker`;
- the draft is proven to be THIS business's through RLS (`content_drafts` under
  `tenant_session`) BEFORE anything is read from R2: a foreign draft would put a reel cut in
  a folder the caller does not own;
- the source is read through the public door (`PublicObjectGate.open_public[_range]`) — read
  only; this module never writes or deletes under `public/`;
- the cut is written through the tenant door (`ObjectGate.put_source_window`), which builds
  the key itself from the UUIDs and the whole seconds.

Two concurrent first calls in different processes both cut and PUT the same bytes to the
same key — harmless. The window is not an output: it is never registered in `image_assets`
and never published (design §7).

Memory: the source goes to a temp file in 8 MiB ranges (never the whole ≤ 80 MiB object in
memory), but the H.264 encode of a 1080x1920 window peaks at ~295 MiB above baseline
(measured 2026-11-05 on a 68 MiB, 60 s source, 8 cores). So at most one cut runs per process
at a time (`_CUT_LOCK`, taken with a timeout), and it only runs in the creative worker: it
refuses with `wrong_process` unless the creative worker's entry point marked this process
(`creative.process.mark_worker_process`). Not an environment switch: every app container
reads the same `.env.prod`, so only the marker keeps it out of the Reflex process (one
512 MiB process in production).
The temp directory is removed on every exit.
"""

from __future__ import annotations

import math
import shutil
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from qualify_creative.video import VideoSourceError
from qualify_creative.video.cut import (
    EDIT_FPS_RANGE,
    MAX_WINDOW_SECONDS,
    MIN_WINDOW_SECONDS,
    cut_window,
)
from qualify_shared.objects.gate import ObjectGate, ObjectNotFound
from qualify_shared.objects.keys import TenantPrefixViolation, source_window_key
from qualify_shared.objects.public import PublicKeyViolation, PublicObjectGate

from qualify_api.creative.process import is_worker_process
from qualify_api.referentes.reel_analysis_store import AnalysisRecord, AnalysisRequests
from qualify_api.referentes.reel_analysis_types import STATUS_OK

WINDOW_CONTENT_TYPE = "video/mp4"
#: Ranged reads from R2 to the temp file (the same size as the worker's).
READ_CHUNK_BYTES = 8 * 1024 * 1024
#: One cut at a time per process: the encode alone peaks at ~295 MiB (module docstring).
_CUT_LOCK = threading.Lock()
#: How long a call waits for another cut in this process before giving up (a 10 s
#: 1080x1920 window takes seconds; a queue of them would rather fall back than hang).
LOCK_TIMEOUT_S = 120.0

# Why a window was refused. The first four send the part to `reference` (like
# `refused_face`); `bad_window` is a caller bug (not whole seconds, or not 4-10 s).
WINDOW_SOURCE_PURGED = "source_purged"
WINDOW_NOT_EDIT_ELIGIBLE = "not_edit_eligible"
WINDOW_ANALYSIS_NOT_READY = "analysis_not_ready"
WINDOW_UNAVAILABLE = "window_unavailable"
WINDOW_BAD = "bad_window"
#: Called outside the creative worker (the process was not marked by its entry point): a
#: deployment bug, not a reason to fall back.
WINDOW_WRONG_PROCESS = "wrong_process"
FALLS_BACK_TO_REFERENCE = frozenset(
    {
        WINDOW_SOURCE_PURGED,
        WINDOW_NOT_EDIT_ELIGIBLE,
        WINDOW_ANALYSIS_NOT_READY,
        WINDOW_UNAVAILABLE,
    }
)


class SourceWindowRefused(Exception):
    """The window cannot be cut. `code` is stable; `falls_back` says whether the part goes
    to `reference` instead (every code but `bad_window`)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code

    @property
    def falls_back(self) -> bool:
        return self.code in FALLS_BACK_TO_REFERENCE


class ForeignDraft(TenantPrefixViolation):
    """`draft_id` is not a piece of this business (RLS sees no such row): its folder is not
    the caller's. A `TenantPrefixViolation`, raised before the source is read. The ids are
    not echoed (an exception message is a log line)."""


class DraftOwnership(Protocol):
    """Whether a draft is visible to this business (RLS on `content_drafts`)."""

    def owns(self, tenant_id: UUID, draft_id: UUID) -> bool: ...


class PostgresDraftOwnership:
    """`DraftOwnership` as `qualify_app`: under `tenant_session`, RLS hides other
    businesses' drafts, so «not found» and «someone else's» are the same answer."""

    def owns(self, tenant_id: UUID, draft_id: UUID) -> bool:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            found = session.execute(
                text("SELECT 1 FROM content_drafts WHERE id = :id"), {"id": draft_id}
            ).first()
        return found is not None


def window_key(tenant_id: UUID, draft_id: UUID, analysis_id: UUID, start_s: int, end_s: int) -> str:
    """`reel-windows/{tenant}/{draft_id}/source-window-{analysis_id}-{start}-{end}.mp4`
    (`qualify_shared.objects.keys.source_window_key`; outside `t/` since VE-12)."""
    return source_window_key(
        UUID(str(tenant_id)), UUID(str(draft_id)), UUID(str(analysis_id)), start_s, end_s
    )


def _whole_seconds(value: object, name: str) -> int:
    """`value` as an int if it is a whole number of seconds (3 or 3.0; never 2.5 or True)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SourceWindowRefused(WINDOW_BAD, f"{name} is not a number of seconds")
    if not math.isfinite(value):
        raise SourceWindowRefused(WINDOW_BAD, f"{name} is not a finite number")
    if float(value) != int(value):
        raise SourceWindowRefused(WINDOW_BAD, f"{name} is not a whole second")
    return int(value)


def check_window(start_s: object, end_s: object) -> tuple[int, int]:
    """`(start, end)` in whole seconds, `0 <= start`, `end - start` in 4-10; raises
    `SourceWindowRefused(bad_window)` otherwise."""
    start = _whole_seconds(start_s, "start_s")
    end = _whole_seconds(end_s, "end_s")
    if start < 0 or not MIN_WINDOW_SECONDS <= end - start <= MAX_WINDOW_SECONDS:
        raise SourceWindowRefused(
            WINDOW_BAD,
            f"a window lasts {MIN_WINDOW_SECONDS}-{MAX_WINDOW_SECONDS} whole seconds "
            f"from 0 on, not {start}..{end}",
        )
    return start, end


def _check_analysis(record: AnalysisRecord | None, end_s: int) -> str:
    """The row's source key, or the refusal that sends the part to `reference`. Never
    touches R2: a purged source is refused from the row alone."""
    if record is None or record.status != STATUS_OK or not record.source_key:
        raise SourceWindowRefused(WINDOW_ANALYSIS_NOT_READY)
    if record.source_purged_at is not None:
        raise SourceWindowRefused(WINDOW_SOURCE_PURGED)
    if not record.edit_eligible:
        raise SourceWindowRefused(WINDOW_NOT_EDIT_ELIGIBLE)
    if record.source_seconds is not None and end_s > record.source_seconds + 1e-3:
        raise SourceWindowRefused(WINDOW_UNAVAILABLE, "the window ends past the source")
    return record.source_key


def _copy_source(public: PublicObjectGate, key: str, dest: Path) -> None:
    """The stored source to `dest` in 8 MiB ranged reads (HEAD, then ranges: the store must
    offer both, as `R2ObjectStore` does). A missing object (purged outside its row's
    knowledge) is `source_purged`."""
    try:
        size = public.public_size(key)
        with dest.open("wb") as out:
            for start in range(0, size, READ_CHUNK_BYTES):
                end = min(size, start + READ_CHUNK_BYTES) - 1
                shutil.copyfileobj(public.open_public_range(key, start, end), out, READ_CHUNK_BYTES)
    except ObjectNotFound as error:
        raise SourceWindowRefused(WINDOW_SOURCE_PURGED, "the source is gone from R2") from error


def _already_cut(gate: ObjectGate, tenant_id: UUID, key: str) -> bool:
    """Whether the window is already stored (a HEAD; the store must offer `size`)."""
    try:
        return gate.object_size(tenant_id, key) > 0
    except ObjectNotFound:
        return False


@dataclass
class SourceWindows:
    """VE-09's entry point. Built with the stores it reads and writes; `default_source_windows`
    wires the real ones. Runs only in the creative worker (`in_worker`, refused with
    `wrong_process` otherwise), and only ever opens `tenant_session` — never the creative
    worker's role."""

    requests: AnalysisRequests
    drafts: DraftOwnership
    gate: ObjectGate
    public: PublicObjectGate
    temp_root: str | None = None
    lock_timeout_s: float = LOCK_TIMEOUT_S
    in_worker: Callable[[], bool] = field(default=is_worker_process)
    cut: Callable[..., Any] = field(default=cut_window)

    def source_window(
        self,
        tenant_id: UUID,
        analysis_id: UUID,
        *,
        draft_id: UUID,
        start_s: int,
        end_s: int,
    ) -> str:
        """The R2 key of `[start_s, end_s)` of the analysed reel, cut into the piece's
        folder (cut once; a later call returns the same key). Raises `SourceWindowRefused`
        (see `falls_back`) or `ForeignDraft`."""
        if not self.in_worker():
            raise SourceWindowRefused(WINDOW_WRONG_PROCESS, "only the creative worker cuts")
        start, end = check_window(start_s, end_s)
        if not self.drafts.owns(tenant_id, draft_id):
            raise ForeignDraft("the draft is not a piece of this business")
        source_key = _check_analysis(self.requests.get(tenant_id, analysis_id), end)
        key = window_key(tenant_id, draft_id, analysis_id, start, end)
        if _already_cut(self.gate, tenant_id, key):
            return key
        if not _CUT_LOCK.acquire(timeout=self.lock_timeout_s):
            raise SourceWindowRefused(WINDOW_UNAVAILABLE, "another cut kept this process busy")
        try:
            if not _already_cut(self.gate, tenant_id, key):  # cut while we waited
                self._cut_into(tenant_id, source_key, draft_id, analysis_id, start, end)
        finally:
            _CUT_LOCK.release()
        return key

    def _cut_into(
        self,
        tenant_id: UUID,
        source_key: str,
        draft_id: UUID,
        analysis_id: UUID,
        start: int,
        end: int,
    ) -> None:
        """Copy the source to a temp folder, cut `[start, end)` and PUT it through
        `ObjectGate.put_source_window`, which builds the `reel-windows/` key itself."""
        work = Path(tempfile.mkdtemp(prefix="qualify-window-", dir=self.temp_root))
        try:
            local = work / "source.mp4"
            try:
                _copy_source(self.public, source_key, local)
            except PublicKeyViolation as error:  # a row key that is not the door's shape
                raise SourceWindowRefused(WINDOW_ANALYSIS_NOT_READY) from error
            try:
                # always at 24-60 fps, as BytePlus's edit takes it (m-24973444)
                window = self.cut(
                    local,
                    float(start),
                    float(end),
                    out=work / "window.mp4",
                    fps_range=EDIT_FPS_RANGE,
                )
            except VideoSourceError as error:
                raise SourceWindowRefused(WINDOW_UNAVAILABLE, error.reason) from error
            with open(window.path, "rb") as body:
                self.gate.put_source_window(
                    UUID(str(tenant_id)),
                    UUID(str(draft_id)),
                    UUID(str(analysis_id)),
                    start,
                    end,
                    body,
                )
        finally:
            shutil.rmtree(work, ignore_errors=True)


def default_source_windows() -> SourceWindows:
    """The real one: Postgres as `qualify_app` and the R2 bucket behind both doors."""
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    from qualify_api.referentes.reel_analysis_store import (  # noqa: PLC0415
        PostgresAnalysisRequests,
    )

    store = R2ObjectStore(R2Settings.from_env())
    return SourceWindows(
        requests=PostgresAnalysisRequests(),
        drafts=PostgresDraftOwnership(),
        gate=ObjectGate(store),
        public=PublicObjectGate(store),
    )


__all__ = [
    "FALLS_BACK_TO_REFERENCE",
    "WINDOW_ANALYSIS_NOT_READY",
    "WINDOW_BAD",
    "WINDOW_CONTENT_TYPE",
    "WINDOW_NOT_EDIT_ELIGIBLE",
    "WINDOW_SOURCE_PURGED",
    "WINDOW_UNAVAILABLE",
    "WINDOW_WRONG_PROCESS",
    "DraftOwnership",
    "ForeignDraft",
    "PostgresDraftOwnership",
    "SourceWindowRefused",
    "SourceWindows",
    "check_window",
    "default_source_windows",
    "window_key",
]

"""The backend reads behind the create flow's wait for a reel's analysis (ADR 44 UI-2,
m-24921076). Blocking: callers run them in `asyncio.to_thread`.

Only database reads through `reel_analysis` (`tenant_session`, the current
`ANALYSIS_VERSION` only): never the vendor, never the model, never a download (F5: the
`reels-worker` does all of that). The tenant only opens the session; the analysis is
global and names no business.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from qualify_api.creative.parts import plan_from_analysis
from qualify_api.referentes import reel_analysis
from qualify_api.referentes.reel_analysis_types import AnalysisStatus, ReelAnalysis

from . import reel_parts_vm
from .avatar_proxy import part_source_path, part_thumbnail_path

#: How long the fleet's 24 h model-call count (`fleet_paused`) is reused across polls:
#: it is the same number for every tab and every business (the fleet is global), and it
#: moves slowly; without this every tab sums the table every 3 s.
FLEET_CACHE_SECONDS = 60.0


class _FleetCache:
    """`model_calls_since` remembered for `FLEET_CACHE_SECONDS`, process-wide. The count
    names no business; only the `since`/`now` of the first read in the window are used."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._value: int | None = None
        self._at = 0.0

    def get(self, read: Callable[[], int]) -> int:
        with self._lock:
            if self._value is not None and self._clock() - self._at < FLEET_CACHE_SECONDS:
                return self._value
        value = read()
        with self._lock:
            self._value, self._at = value, self._clock()
        return value

    def clear(self) -> None:
        with self._lock:
            self._value = None


_fleet = _FleetCache()


class _CachedFleetStore:
    """The analysis store with its fleet count served from `_fleet`; everything else is
    the store's own."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def model_calls_since(self, tenant_id: UUID, since: datetime, now: datetime) -> int:
        return _fleet.get(lambda: self._store.model_calls_since(tenant_id, since, now))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


def analysis_status(tenant_id: UUID, analysis_id: UUID) -> AnalysisStatus | None:
    """What the wait polls every 3 s (None: no such row of the current version)."""
    store = _CachedFleetStore(reel_analysis.default_store())
    return reel_analysis.get_analysis_status(tenant_id, analysis_id, store=store)


def plan_parts(tenant_id: UUID, analysis_id: UUID, products: Sequence[str] = ()) -> int | None:
    """How many parts the reel's plan proposes (`plan_from_analysis`, pure) — the «n» of
    «Encontramos {n} partes», never the shots detected. None when the analysis is not
    `ok` (any more)."""
    analysis = reel_analysis.get_analysis(tenant_id, analysis_id)
    if analysis is None:
        return None
    return len(plan_from_analysis(analysis, products=tuple(p for p in products if p)))


def reel_plan(
    tenant_id: UUID, analysis_id: UUID, products: Sequence[str] = ()
) -> list[dict[str, Any]] | None:
    """The reel's plan as the step's entries (UI-3, m-24921077): each part of
    `plan_from_analysis` with whether someone is seen in it and why it is not «Igual al
    original» (`reel_parts_vm.entries_from_plan`, pure), and its thumbnail's signed path
    (`avatar_proxy.part_thumbnail_path`, "" when no frame is kept). m-24992893: also
    `source` (`avatar_proxy.part_source_path` — the same path on every entry of the
    analysis, "" once the copy is purged or for a part with no cut of the reel) and
    `start_s` / `end_s` (floats, the part's stretch of the original; 0.0 with no
    `source`). None when the analysis is not `ok` (any more). One read; the count of
    «Encontramos {n} partes» is its length."""
    analysis = reel_analysis.get_analysis(tenant_id, analysis_id)
    if analysis is None:
        return None
    plan = plan_from_analysis(analysis, products=tuple(p for p in products if p))
    entries = reel_parts_vm.entries_from_plan(analysis, plan)
    # m-24992893: ONE signed path of the stored original per analysis, shared by every
    # part; each entry says which stretch of it is the part's (pure: no read here)
    source = part_source_path(analysis)
    for entry in entries:
        cuts = entry["plan"].get("shot_indexes") or ()
        # the signed path of a frame of the part's cuts ("" → the row's placeholder);
        # pure: the browser asks the route, which reads R2
        entry["thumb"] = part_thumbnail_path(analysis, cuts)
        stretch = part_stretch(analysis, cuts)
        entry["source"] = source if stretch is not None else ""
        entry["start_s"], entry["end_s"] = stretch or (0.0, 0.0)
    return entries


def part_stretch(analysis: ReelAnalysis, shot_indexes: Sequence[int]) -> tuple[float, float] | None:
    """Where a part made of `shot_indexes` sits in the original reel: the first cut's
    start and the last cut's end, in seconds (rounded to the tenth). None when the part
    names no cut the analysis knows (a part not taken from the reel). Pure."""
    wanted = set(shot_indexes)
    cuts = [shot for shot in analysis.shots if shot.shot_index in wanted]
    if not cuts:
        return None
    start = round(min(shot.start_s for shot in cuts), 1)
    end = round(max(shot.end_s for shot in cuts), 1)
    return (start, end) if end > start else None


__all__ = [
    "FLEET_CACHE_SECONDS",
    "analysis_status",
    "part_stretch",
    "plan_parts",
    "reel_plan",
]

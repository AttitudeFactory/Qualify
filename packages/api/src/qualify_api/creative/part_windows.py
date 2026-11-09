"""The window of the original reel an «Igual al original» part edits (ADR 44, VE-09).

`SourcePartWindows` is the `media.PartWindows` the creative worker wires: it reads the
part's analysed cuts (as `qualify_app`, `tenant_session` — `AnalysisRequests`), picks the
window (`parts.part_window`, pure) and asks `SourceWindows.source_window` (VE-04d) to cut
it into the PART's own folder. Idempotent: a re-run of the same part (the queue runs a
generation's preparation more than once) gets the same key, cut once.

Every refusal becomes `media.PartWindowRefused` with the `SourceWindowRefused` code
(`foreign_draft` for `ForeignDraft`); the part then FAILS with that typed reason and its
vista previa is given back — it is never switched to «Nueva» by itself (signed
2026-11-06). Anything unexpected while cutting (R2, the database) is
`window_unavailable`, logged.

The real `SourceWindows` is built on first use (`default_source_windows` reads the R2
settings): the Reflex process never builds it, and `source_window` itself refuses
outside the creative worker (`wrong_process`).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from uuid import UUID

from qualify_creative.schemas import PartRef

from qualify_api.creative.media import PartWindow, PartWindowRefused
from qualify_api.creative.parts import part_window
from qualify_api.referentes.reel_analysis_types import STATUS_OK
from qualify_api.referentes.reel_analysis_window import (
    WINDOW_ANALYSIS_NOT_READY,
    WINDOW_BAD,
    WINDOW_UNAVAILABLE,
    ForeignDraft,
    SourceWindowRefused,
    SourceWindows,
    default_source_windows,
)

logger = logging.getLogger(__name__)

FOREIGN_DRAFT = "foreign_draft"


class SourcePartWindows:
    """`media.PartWindows` over VE-04d's `SourceWindows`."""

    def __init__(
        self,
        windows: SourceWindows | None = None,
        *,
        factory: Callable[[], SourceWindows] = default_source_windows,
    ) -> None:
        self._windows = windows
        self._factory = factory
        self._lock = threading.Lock()

    def _source(self) -> SourceWindows:
        with self._lock:
            if self._windows is None:
                self._windows = self._factory()
            return self._windows

    def __call__(self, *, tenant_id: UUID, draft_id: UUID, part: PartRef) -> PartWindow:
        if part.mode != "edit" or part.analysis_id is None:
            raise PartWindowRefused(WINDOW_BAD)
        try:
            windows = self._source()
            record = windows.requests.get(tenant_id, part.analysis_id)
            if record is None:
                # RLS hides another business's request, or the row is gone: worth a look
                logger.warning(
                    "part %s: its reel analysis is not visible to this business", draft_id
                )
                raise PartWindowRefused(WINDOW_ANALYSIS_NOT_READY)
            if record.status != STATUS_OK:
                raise PartWindowRefused(WINDOW_ANALYSIS_NOT_READY)
            shots = windows.requests.shots(tenant_id, part.analysis_id)
            start, end, offset = part_window(part, shots, source_seconds=record.source_seconds)
            key = windows.source_window(
                tenant_id, part.analysis_id, draft_id=draft_id, start_s=start, end_s=end
            )
        except PartWindowRefused:
            raise
        except SourceWindowRefused as exc:
            raise PartWindowRefused(exc.code) from exc
        except ForeignDraft as exc:
            logger.error("part %s: its window would go to a folder not of its business", draft_id)
            raise PartWindowRefused(FOREIGN_DRAFT) from exc
        except Exception as exc:  # noqa: BLE001 — R2 or the database: the part fails, refunded
            logger.warning("part %s: window not cut: %s", draft_id, type(exc).__name__)
            raise PartWindowRefused(WINDOW_UNAVAILABLE) from exc
        return PartWindow(key=key, start_s=start, end_s=end, offset_s=offset)


__all__ = ["FOREIGN_DRAFT", "SourcePartWindows"]

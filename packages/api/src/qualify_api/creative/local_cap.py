"""EF-15 (m-25026575): the daily cap of LOCAL builds per business.

A local build («Tu video, con efectos», EF-06, `video_pipeline.local`) costs the
business nothing — no creation, no vista previa, no video second (D3) — but it decodes
and encodes the owner's own videos on our CPU, in the creative worker. Nothing else
limits it, so a business makes at most `local_daily_cap()` of them a day (Deivid,
2026-11-16: «10 al día»).

What counts — every build that reaches the worker, whatever its fate:

- a new local piece (`ContentService.create_draft`, «Crearla otra vez» included);
- «Pedir otra versión» of a local piece (`ContentService.reject(regenerate=True)`,
  which `PartsService.regenerate_part` and «Crearla otra vez» of a part go through);
- «Intentar de nuevo» / «Cambiar» of a failed local part (`PartRecovery._restart`);
- every `local` part a video by parts creates (`PartsService.create_parts`): N parts
  that would go past the cap are refused together, before any of them exists.
- «Crear la parte N otra vez» of expired local parts
  (`FinalVideoReader.recreate_expired_parts`): refused together, like `create_parts`.

How it is counted: each of those writes ONE `creation_charges` row per (draft,
revision) with `request_kind = 'local_video'` (`weight_for` → `REQUEST_LOCAL_VIDEO`, 0
creations), in the same transaction that enqueues the job. The unique
`(draft_id, revision)` means nothing is counted twice; a refunded row (a build that
failed) keeps its row and still counts — the CPU was spent all the same. The day is the
business's own (`tenants.timezone`, empty → UTC), as `parent_texts_regenerated_today`.

The check runs BEFORE any row, charge or job; a refusal (`LocalDailyCapReached`, code
`local_daily_cap_reached`) writes nothing. A repository that cannot count (test doubles
without `local_builds_today`) is not capped — the same rule as `check_parent_text_cap`.
Under the queue the count takes a per-business transaction lock, so two builds asked at
once cannot both take the last place.

Known limit: with the monthly quota switched off (`QUALIFY_CREATIONS_QUOTA=off`) no
charge rows are written, so nothing is counted and the cap does not bite.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from functools import cache
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

#: The environment variable that sets the cap (a positive whole number).
LOCAL_DAILY_CAP_ENV = "QUALIFY_LOCAL_DAILY_CAP"
#: Deivid, 2026-11-16: «10 al día (Recomendado)».
DEFAULT_LOCAL_DAILY_CAP = 10
#: The stable code of the refusal (screens and stored outcomes read this, never the text).
LOCAL_DAILY_CAP_CODE = "local_daily_cap_reached"


@cache
def _parsed(raw: str) -> int:
    """`raw` as the cap; anything that is not a whole number above 0 is the default,
    logged once per value."""
    try:
        value = int(raw.strip())
    except ValueError:
        value = 0
    if value < 1:
        logger.warning(
            "%s=%r is not a whole number above 0: using %d",
            LOCAL_DAILY_CAP_ENV,
            raw,
            DEFAULT_LOCAL_DAILY_CAP,
        )
        return DEFAULT_LOCAL_DAILY_CAP
    return value


def local_daily_cap() -> int:
    """How many local builds a business may make a day: `QUALIFY_LOCAL_DAILY_CAP`, 10
    when unset or invalid. Read on every check, so a new value needs only a restart."""
    raw = os.environ.get(LOCAL_DAILY_CAP_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_LOCAL_DAILY_CAP
    return _parsed(raw)


def local_cap_text(*, cap: int, used: int, asked: int = 1) -> str:
    """The owner's words (Spanish, `qualify-copy-es`; the screen calls them «fotos y
    videos»): what happened and when it can be done again."""
    left = max(cap - used, 0)
    if left == 0:
        if cap == 1:
            return (
                "Por hoy ya usaste el video que puedes crear con tus fotos y videos. "
                "Mañana tienes otro."
            )
        return (
            f"Por hoy ya usaste los {cap} videos que puedes crear con tus fotos y videos. "
            "Cada parte y cada versión nueva cuenta como uno. "
            f"Mañana tienes {cap} más."
        )
    # only a video by parts asks for more than one at once («Crear las que faltan»,
    # «Crear la parte N otra vez» of several): the owner cannot pick fewer there
    # `asked` >= 2 here (one that fits is never refused); it counts only the parts made
    # with the owner's photos and videos, so the sentence names them as such
    remaining = "hoy solo te queda 1" if left == 1 else f"hoy solo te quedan {left}"
    return (
        f"Este video necesita {asked} partes con tus fotos y videos, y {remaining}. "
        "Mañana puedes crearlas. Lo que ya hiciste sigue guardado."
    )


class LocalDailyCapReached(ValueError):
    """Today's local builds of this business are spent (EF-15). Nothing was written,
    charged or enqueued. `code` is stable (`local_daily_cap_reached`), `text` the
    owner's Spanish; `used` today's builds, `cap` the cap, `asked` what this call
    wanted to build. A `ValueError`, so a screen that knows nothing of it still gives
    its button back with its generic line."""

    code = LOCAL_DAILY_CAP_CODE

    def __init__(self, *, used: int, cap: int, asked: int = 1) -> None:
        self.text = local_cap_text(cap=cap, used=used, asked=asked)
        super().__init__(self.text)
        self.used = used
        self.cap = cap
        self.asked = asked


def check_local_daily_cap(repository: Any, *, tenant_id: UUID, asking: int = 1) -> None:
    """Refuse `asking` new local builds when they do not fit in today's cap — all of
    them or none. A repository that cannot count is not capped; `asking` < 1 checks
    nothing."""
    if asking < 1:
        return
    counter: Callable[..., int] | None = getattr(repository, "local_builds_today", None)
    if counter is None:
        return
    cap = local_daily_cap()
    used = int(counter(tenant_id=tenant_id))
    if used + asking > cap:
        raise LocalDailyCapReached(used=used, cap=cap, asked=asking)


__all__ = [
    "DEFAULT_LOCAL_DAILY_CAP",
    "LOCAL_DAILY_CAP_CODE",
    "LOCAL_DAILY_CAP_ENV",
    "LocalDailyCapReached",
    "check_local_daily_cap",
    "local_cap_text",
    "local_daily_cap",
]

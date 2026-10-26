"""The paid preview's hard deadline, not the time its final joined our queue (m-24852168)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from qualify_creative.adapters.byteplus_ark import DRAFT_TTL_SECONDS

FINAL_MARGIN = timedelta(minutes=15)
FINAL_URGENT_WITHIN = timedelta(hours=24)
FINAL_EXPIRED_TEXT = (
    "La vista previa de este video ya venció. "
    "Crea una vista previa nueva para hacer el video final."
)


class FinalDeadlineExpired(ValueError):
    """Local validation proved expiry before any paid vendor submission."""


def deadline_for_preview(created_at: float | datetime) -> datetime:
    """Use the vendor preview's creation instant; never reset its TTL on retry/enqueue.

    A missing or invalid creation instant must be rejected by the caller, rather than
    silently granting another seven days to a paid preview whose age is unknown.
    """
    if isinstance(created_at, datetime):
        if created_at.tzinfo is None:
            raise ValueError("preview created_at must have a timezone")
        created = created_at.astimezone(UTC)
    elif isinstance(created_at, bool) or not isinstance(created_at, int | float):
        raise ValueError("preview created_at must be a timestamp")
    elif not math.isfinite(created_at):
        raise ValueError("preview created_at must be finite")
    else:
        created = datetime.fromtimestamp(created_at, UTC)
    return created + timedelta(seconds=DRAFT_TTL_SECONDS) - FINAL_MARGIN


def final_is_urgent(deadline: datetime | None, now: datetime) -> bool:
    """Expired jobs also go to the head so they are failed without calling the vendor."""
    return deadline is not None and deadline - now < FINAL_URGENT_WITHIN


def final_deadline_passed(deadline: datetime | None, now: datetime) -> bool:
    return deadline is not None and deadline <= now

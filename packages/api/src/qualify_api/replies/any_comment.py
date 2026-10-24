"""The per-tenant switch for public drafts to ANY comment — questions and complaints too
(ATENDER-4b, m-24848533; QUA-22 amended by the founder on 2026-10-23, epic §2b-1).

**OFF by default, on purpose.** ATENDER-4a (m-24848532) built and ran the measurement,
but only on a synthetic smoke set: the real ~400-comment golden set, its double labels
and the human review of the drafts are still missing (`docs/respuestas-comentarios-
medicion.md` §8). Until that passes, Qualify keeps drafting only what it drafted before
(positive and commercial comments) for every business, and the founder turns the new
drafting on business by business:

    QUALIFY_REPLIES_ANY_COMMENT_TENANTS=<tenant uuid>,<tenant uuid>   # those businesses
    QUALIFY_REPLIES_ANY_COMMENT_TENANTS=all                           # every business

Unset, empty or unreadable → OFF for everyone (fail closed: a typo never turns it on).
Same env-list shape as `QUALIFY_CALENDAR_WORKER_TENANTS` (`planner.embedded`). No table
and no migration: it is an operator decision, read on every call, so a change applies
on the next restart without a deploy of new code.

Turning it on never sends anything: every draft still waits for the owner's «Aprobar y
responder» (`ReplyService.send` demands a `HumanApproval`).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Final
from uuid import UUID

ENV_ANY_COMMENT_TENANTS: Final = "QUALIFY_REPLIES_ANY_COMMENT_TENANTS"
#: The review reason every complaint draft carries (blocking: «Revísala antes de
#: aprobar» — the owner edits it or ticks «Ya revisé estos puntos» before it goes out).
COMPLAINT_REASON: Final = "complaint"
ALL_TENANTS: Final = "all"

logger = logging.getLogger("qualify_api.replies.any_comment")


def any_comment_enabled(tenant_id: UUID, env: Mapping[str, str] | None = None) -> bool:
    """Whether this business gets drafts for questions and complaints too. Never raises."""
    raw = (os.environ if env is None else env).get(ENV_ANY_COMMENT_TENANTS, "").strip()
    if not raw:
        return False
    if raw.lower() == ALL_TENANTS:
        return True
    enabled: set[UUID] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            enabled.add(UUID(part))
        except ValueError:
            logger.warning("%s has an invalid UUID; the setting stays OFF", ENV_ANY_COMMENT_TENANTS)
            return False
    return tenant_id in enabled


__all__ = ["ALL_TENANTS", "COMPLAINT_REASON", "ENV_ANY_COMMENT_TENANTS", "any_comment_enabled"]

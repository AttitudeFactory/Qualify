"""Primitives shared by every assisted reply, private or public (m-24789645).

"Assisted, never autonomous" (ADR 21c) is one rule with two halves, and both used to live
inside `conversations`:

- `grounding` — the facts a tenant has validated (business name + active catalog), with
  the provenance a reviewer needs to check each one (product id, price, currency, the
  catalog row's `updated_at`). Conversaciones (DM), Fase C (followups) and the public
  comment drafts of `replies` all ground on the same thing, so it lives here instead of
  making `replies` import `conversations`.
- `approval` — `HumanApproval`, the object every send path demands. The private outbox
  (`conversations.outbox.enqueue`) and the public comment reply (`replies.ReplyService.
  send`) require the same type, so "who approved this text, and when" means one thing.

`conversations.suggest` and `conversations.outbox` re-export these names, so every
existing import keeps working. This package imports nothing from any domain module at
import time (the catalog read is lazy, inside the DB loader).
"""

from qualify_api.assisted.approval import ApprovalRequired, HumanApproval
from qualify_api.assisted.grounding import (
    GroundedProduct,
    Grounding,
    GroundingProvider,
    catalog_grounding_for,
    grounding_from_products,
)

__all__ = [
    "ApprovalRequired",
    "GroundedProduct",
    "Grounding",
    "GroundingProvider",
    "HumanApproval",
    "catalog_grounding_for",
    "grounding_from_products",
]

"""Cross-tenant resolution of a WhatsApp webhook change's owning tenant (WA-07).

Same mould as `mentions/resolve.py`, for the other product: a `messages` change names the
business number by `value.metadata.phone_number_id` — Meta's global identifier — and
carries no `tenant_id`. The processor must answer "which tenant owns this number" BEFORE
any tenant-scoped write, so this one read crosses tenants through the narrow
`qualify_webhook_worker` door (`webhook_worker_session`, BYPASSRLS):

- Migration 0057 grants that role a COLUMN-level SELECT on `whatsapp_phone_numbers` —
  exactly `id, tenant_id, connection_id, phone_number_id`. This module selects those four
  and nothing else; `SELECT *` or any other column fails with `insufficient_privilege`
  (`test_whatsapp_schema_db.py` pins it), which is the point: the worker resolves a
  number, it does not read a number's Graph metadata or its published automation.
- READ-ONLY — one `SELECT`.
- Keyed by `phone_number_id` ONLY. It never accepts a `tenant_id` from the caller: the
  payload's own claim of who it is for is not evidence.
- Two outcomes, not three: `phone_number_id` is `UNIQUE` across the table
  (`uq_wa_phone_number_id`), so unlike an Instagram account a WhatsApp number cannot be
  connected under two tenants and `AMBIGUOUS` is unrepresentable. A row count above one
  would mean the constraint is gone; it raises rather than picks.

After `RESOLVED`, every write the handler makes carries the `tenant_id` this function
produced and goes through `qualify_api.whatsapp.repository` on the same worker door (the
grants of 0057 are what bound it, not a policy — see that module).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from qualify_shared.db.webhook import webhook_worker_session
from sqlalchemy import select

from qualify_api.whatsapp.models import WhatsAppPhoneNumber

PLATFORM_WHATSAPP = "whatsapp"


class PhoneResolutionOutcome(StrEnum):
    RESOLVED = "resolved"
    ORPHAN = "orphan"


@dataclass(frozen=True)
class PhoneResolution:
    """The result of resolving one `phone_number_id`. The ids are populated ONLY when
    `outcome is RESOLVED` — switch on `outcome`, never on whether an id is set."""

    outcome: PhoneResolutionOutcome
    tenant_id: UUID | None = None
    connection_id: UUID | None = None
    phone_row_id: UUID | None = None  # `whatsapp_phone_numbers.id`: the menu/catalog key


def resolve_phone_number(phone_number_id: str) -> PhoneResolution:
    """READ-ONLY cross-tenant lookup of who owns `phone_number_id`. Deliberately takes no
    `tenant_id` — see the module docstring."""
    with webhook_worker_session() as session:
        rows = session.execute(
            select(
                WhatsAppPhoneNumber.id,
                WhatsAppPhoneNumber.tenant_id,
                WhatsAppPhoneNumber.connection_id,
            ).where(WhatsAppPhoneNumber.phone_number_id == phone_number_id)
        ).all()

    if not rows:
        return PhoneResolution(outcome=PhoneResolutionOutcome.ORPHAN)
    if len(rows) > 1:  # pragma: no cover - `uq_wa_phone_number_id` makes this unreachable
        raise RuntimeError(
            f"phone_number_id {phone_number_id!r} matches {len(rows)} rows; "
            "uq_wa_phone_number_id is missing"
        )
    phone_row_id, tenant_id, connection_id = rows[0]
    return PhoneResolution(
        outcome=PhoneResolutionOutcome.RESOLVED,
        tenant_id=tenant_id,
        connection_id=connection_id,
        phone_row_id=phone_row_id,
    )

"""WhatsApp marketing campaigns (WA-20, QUA-219): audience → one send per phone → paced
outbox rows → receipts.

Backlog: `docs/backlog-modulo-whatsapp.md` §5 WA-20; plan §2.4 (pair limit, messaging
limit), §2.5 (per-message pricing, per-user marketing limit `131049`), §5.4. Schema:
migration 0060 (`whatsapp_campaigns`, `whatsapp_campaign_sends`, the outbox mirror
trigger).

## Lifecycle

`create` → `draft` (or `scheduled` with a future `scheduled_at`) → `launch` → `running`
→ `finalize_if_complete` → `done`; `cancel` → `cancelled` from any non-final state.
`paused` is in the CHECK for the UI story; pausing is not implemented here (it needs the
outbox rows pushed out and re-paced on resume — follow-up).

## `launch`, step by step (idempotent: a relaunch resumes, never resends)

1. Guards: the campaign is `draft`/`scheduled`/`running`; its template is still sendable
   (`APPROVED`) and belongs to the WABA of the campaign's number.
2. The audience = live opt-ins matching `audience_filter` (`build_audience`).
3. One `whatsapp_campaign_sends` row per phone, `pending`, with its `cost_estimate`
   (`pricing.estimate_cost` by the template's category) — `INSERT … ON CONFLICT
   (campaign_id, phone_e164) DO NOTHING`, so a relaunch adds only new opt-ins.
4. The campaign moves to `running` (`started_at` set once).
5. Every send still `pending` without an outbox row gets one, **atomically**: the outbox
   row (`kind='campaign_send'`, the `build_template_body` payload) is inserted and linked
   to the send (`outbox_id`, `status='queued'`) in ONE transaction, under a row lock on
   the send (`CampaignRepository.enqueue_send`). A crash between two sends leaves the
   rest `pending` for the relaunch; a crash can never leave an outbox row whose send does
   not know it, so nothing is sent twice. This is why the campaign does NOT go through
   `OutboxRepository.enqueue` (two transactions) — the row shape is the same one
   `outbox.py` claims, and `window.TEMPLATE_ONLY_KINDS` already exempts it from the 24 h
   window.
6. Pace: send *i* is due at `start + i × 60 s / max_per_minute` through the outbox's own
   `next_attempt_at`; the sender never claims it earlier. The sender adds the per-pair
   6 s limit on top. The consent is re-checked right before each enqueue (a STOP between
   2. and 5. skips the phone: `not_opted_in`).

## After launch

- The outbox sender settles the row; the trigger `wa_outbox_campaign_mirror` copies
  `wamid`/`sent` (or `failed`/`skipped`) onto the send in the same transaction.
- `statuses[]` receipts arrive by `wamid` through the webhook worker
  (`PostgresCampaignReceiptRepository.apply_receipt`, the handler's `campaign_receipts`
  sink): `sent < delivered < read`, `failed`/`skipped` terminal, never regressing;
  `pricing.category` is kept whenever present. **`131049`** (per-user marketing limit)
  becomes `skipped` with the note «reintentar ≥24 h» (`retry_not_before`); this code never
  retries it by itself — retrying sooner extends the block (per-user-limits page).

**Known gap:** a STOP received AFTER a send was enqueued does not pull that outbox row
back (the worker role may not touch the outbox); the sender would need to consult the
opt-in for `campaign_send` rows. Bounded by the pacing window; recorded for the WA-08
owner.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from qualify_shared.db.webhook import webhook_worker_session
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from qualify_api.whatsapp.client import build_template_body
from qualify_api.whatsapp.models import (
    CAMPAIGN_SEND_STATUSES,
    WhatsAppCampaign,
    WhatsAppCampaignSend,
    WhatsAppOutboxItem,
)
from qualify_api.whatsapp.optins import AudienceFilter, OptInRecord, OptInRepository
from qualify_api.whatsapp.pricing import RATE_CARD_STATUS, estimate_cost
from qualify_api.whatsapp.templates import (
    TemplateNotFound,
    TemplateRecord,
    TemplateRepository,
)

logger = logging.getLogger("qualify_api.whatsapp.campaigns")

OUTBOX_KIND_CAMPAIGN: Final = "campaign_send"
DEFAULT_MAX_PER_MINUTE: Final = 30
ERROR_PER_USER_LIMIT: Final = "131049"
ERROR_NOT_OPTED_IN: Final = "not_opted_in"
ERROR_CANCELLED: Final = "campaign_cancelled"
RETRY_AFTER_PER_USER_LIMIT: Final = timedelta(hours=24)
SKIP_NOTES: Final[dict[str, str]] = {
    ERROR_PER_USER_LIMIT: "reintentar ≥24 h",
    ERROR_NOT_OPTED_IN: "sin opt-in vigente al encolar",
    ERROR_CANCELLED: "campaña cancelada",
}

LAUNCHABLE_STATUSES: Final = frozenset({"draft", "scheduled", "running"})
FINAL_STATUSES: Final = frozenset({"done", "cancelled"})
OPEN_SEND_STATUSES: Final = frozenset({"pending", "queued"})

# Receipt ordering: a receipt only moves a send forward; failed/skipped are terminal.
_SEND_RANK: Final[dict[str, int]] = {
    "pending": 0,
    "queued": 1,
    "sent": 2,
    "delivered": 3,
    "read": 4,
    "failed": 5,
    "skipped": 5,
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def receipt_status(status: str, error_code: str | None) -> str:
    """Map a `statuses[].status` (+ its first error code) to a send status: `131049`
    is not a failure of the send but a per-user limit → `skipped`."""
    if status == "failed" and error_code == ERROR_PER_USER_LIMIT:
        return "skipped"
    if status not in _SEND_RANK:
        raise ValueError(f"unknown receipt status {status!r}")
    return status


# ======================================================================================
# Records and errors
# ======================================================================================


@dataclass(frozen=True)
class CampaignRecord:
    id: UUID
    tenant_id: UUID
    connection_id: UUID
    template_id: UUID
    name: str
    created_by_user_id: UUID
    status: str = "draft"
    brand_id: UUID | None = None
    audience_filter: dict[str, Any] = field(default_factory=dict)
    send_components: list[dict[str, Any]] = field(default_factory=list)
    max_per_minute: int = DEFAULT_MAX_PER_MINUTE
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def audience(self) -> AudienceFilter:
        return AudienceFilter.from_json(self.audience_filter)


@dataclass(frozen=True)
class CampaignSendRecord:
    id: UUID
    tenant_id: UUID
    campaign_id: UUID
    phone_e164: str
    status: str = "pending"
    outbox_id: UUID | None = None
    wamid: str | None = None
    error_code: str | None = None
    price_category: str | None = None
    cost_estimate: Decimal | None = None
    currency: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def note(self) -> str | None:
        """The UI's one-liner for a skipped/failed send (Spanish, product copy)."""
        return SKIP_NOTES.get(self.error_code or "")

    @property
    def retry_not_before(self) -> datetime | None:
        """For a `131049` skip: the earliest instant a retry to this phone is sensible."""
        if self.error_code != ERROR_PER_USER_LIMIT or self.updated_at is None:
            return None
        return self.updated_at + RETRY_AFTER_PER_USER_LIMIT


@dataclass(frozen=True)
class NewSend:
    phone_e164: str
    cost_estimate: Decimal | None
    currency: str | None


@dataclass(frozen=True)
class LaunchReport:
    campaign_id: UUID
    audience: int
    inserted: int
    enqueued: int
    skipped: int
    first_due_at: datetime | None
    last_due_at: datetime | None


@dataclass(frozen=True)
class CostLine:
    currency: str
    amount: Decimal
    sends: int


@dataclass(frozen=True)
class CampaignEstimate:
    """What the UI shows before «Lanzar»: recipients and the estimated cost per currency.
    `placeholder` is True while any rate used is a `[RATE CARD PENDING]` placeholder;
    `unpriced` counts recipients whose country has no rate."""

    recipients: int
    costs: tuple[CostLine, ...]
    unpriced: int
    placeholder: bool
    rate_card_status: str = RATE_CARD_STATUS


@dataclass(frozen=True)
class CampaignSummary:
    """Delivered/read/failed/cost for the Campaigns tab."""

    campaign_id: UUID
    status: str
    counts: dict[str, int]
    costs: tuple[CostLine, ...]
    retry_after_24h: int  # sends skipped by the per-user marketing limit (131049)


class CampaignError(Exception):
    """Base for the service's domain errors."""


class CampaignNotFound(CampaignError):
    pass


class CampaignStateError(CampaignError):
    """The campaign is not in a state that allows the operation."""


class TemplateNotSendable(CampaignError):
    """The template is not APPROVED (or not on the campaign number's WABA)."""


def _costs(sends: Iterable[NewSend | CampaignSendRecord]) -> tuple[CostLine, ...]:
    totals: dict[str, tuple[Decimal, int]] = {}
    for send in sends:
        if send.cost_estimate is None or send.currency is None:
            continue
        amount, count = totals.get(send.currency, (Decimal("0"), 0))
        totals[send.currency] = (amount + send.cost_estimate, count + 1)
    return tuple(CostLine(currency=c, amount=a, sends=n) for c, (a, n) in sorted(totals.items()))


# ======================================================================================
# Repository seams
# ======================================================================================


class CampaignRepository(Protocol):
    """The app side (`qualify_app` under `tenant_session`)."""

    def insert_campaign(self, record: CampaignRecord) -> CampaignRecord: ...

    def get_campaign(self, *, tenant_id: UUID, campaign_id: UUID) -> CampaignRecord | None: ...

    def list_campaigns(self, *, tenant_id: UUID) -> list[CampaignRecord]: ...

    def transition(
        self,
        *,
        tenant_id: UUID,
        campaign_id: UUID,
        to: str,
        allowed_from: frozenset[str],
        now: datetime,
    ) -> CampaignRecord | None:
        """Move the campaign to `to` iff its status is in `allowed_from`; stamps
        `started_at` (first `running`) / `finished_at` (`done`/`cancelled`). `None` =
        not found or not allowed."""
        ...

    def insert_sends(self, *, tenant_id: UUID, campaign_id: UUID, sends: list[NewSend]) -> int:
        """`ON CONFLICT (campaign_id, phone_e164) DO NOTHING`; returns rows inserted."""
        ...

    def list_sends(
        self, *, tenant_id: UUID, campaign_id: UUID, status: str | None = None
    ) -> list[CampaignSendRecord]: ...

    def enqueue_send(
        self,
        *,
        tenant_id: UUID,
        send_id: UUID,
        connection_id: UUID,
        payload: dict[str, Any],
        next_attempt_at: datetime,
        created_by_user_id: UUID | None,
    ) -> UUID | None:
        """ONE transaction: lock the send; if still `pending` with no outbox row, insert
        the `campaign_send` outbox row and link it (`queued`). Returns the outbox id, or
        `None` when the send was already enqueued/settled."""
        ...

    def skip_send(self, *, tenant_id: UUID, send_id: UUID, error_code: str) -> bool:
        """`pending` → `skipped` (never anything else)."""
        ...

    def cancel_open_sends(self, *, tenant_id: UUID, campaign_id: UUID) -> int:
        """Pending outbox rows → `failed`/`campaign_cancelled` (the trigger turns their
        sends into `skipped`); sends never enqueued → `skipped`. Returns sends affected."""
        ...


class CampaignReceiptRepository(Protocol):
    """The worker side: `handler.CampaignReceiptSink`."""

    def apply_receipt(
        self,
        *,
        tenant_id: UUID,
        wamid: str,
        status: str,
        error_code: str | None,
        price_category: str | None,
    ) -> bool: ...


# --------------------------------------------------------------------------------------
# Postgres
# --------------------------------------------------------------------------------------


def _campaign(row: WhatsAppCampaign) -> CampaignRecord:
    return CampaignRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        brand_id=row.brand_id,
        connection_id=row.connection_id,
        template_id=row.template_id,
        name=row.name,
        status=row.status,
        audience_filter=dict(row.audience_filter or {}),
        send_components=list(row.send_components or []),
        max_per_minute=row.max_per_minute,
        scheduled_at=row.scheduled_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _send(row: WhatsAppCampaignSend) -> CampaignSendRecord:
    return CampaignSendRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        campaign_id=row.campaign_id,
        phone_e164=row.phone_e164,
        status=row.status,
        outbox_id=row.outbox_id,
        wamid=row.wamid,
        error_code=row.error_code,
        price_category=row.price_category,
        cost_estimate=row.cost_estimate,
        currency=row.currency,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PostgresCampaignRepository:
    def insert_campaign(self, record: CampaignRecord) -> CampaignRecord:
        with tenant_session(record.tenant_id) as session:
            row = WhatsAppCampaign(
                id=record.id,
                tenant_id=record.tenant_id,
                brand_id=record.brand_id,
                connection_id=record.connection_id,
                template_id=record.template_id,
                name=record.name,
                status=record.status,
                audience_filter=record.audience_filter,
                send_components=record.send_components,
                max_per_minute=record.max_per_minute,
                scheduled_at=record.scheduled_at,
                created_by_user_id=record.created_by_user_id,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            return _campaign(row)

    def get_campaign(self, *, tenant_id: UUID, campaign_id: UUID) -> CampaignRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.get(WhatsAppCampaign, campaign_id)
            return _campaign(row) if row else None

    def list_campaigns(self, *, tenant_id: UUID) -> list[CampaignRecord]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(WhatsAppCampaign).order_by(
                    WhatsAppCampaign.created_at.desc(), WhatsAppCampaign.id
                )
            )
            return [_campaign(r) for r in rows]

    def transition(
        self,
        *,
        tenant_id: UUID,
        campaign_id: UUID,
        to: str,
        allowed_from: frozenset[str],
        now: datetime,
    ) -> CampaignRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.get(WhatsAppCampaign, campaign_id, with_for_update=True)
            if row is None or row.status not in allowed_from:
                return None
            row.status = to
            row.updated_at = now
            if to == "running" and row.started_at is None:
                row.started_at = now
            if to in FINAL_STATUSES:
                row.finished_at = now
            session.flush()
            return _campaign(row)

    def insert_sends(self, *, tenant_id: UUID, campaign_id: UUID, sends: list[NewSend]) -> int:
        if not sends:
            return 0
        stmt = (
            pg_insert(WhatsAppCampaignSend)
            .values(
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "campaign_id": campaign_id,
                        "phone_e164": s.phone_e164,
                        "status": "pending",
                        "cost_estimate": s.cost_estimate,
                        "currency": s.currency,
                    }
                    for s in sends
                ]
            )
            .on_conflict_do_nothing(constraint="uq_wa_campaign_send_phone")
            # `rowcount` is -1 for a multi-row VALUES here; count what RETURNING yields.
            .returning(WhatsAppCampaignSend.id)
        )
        with tenant_session(tenant_id) as session:
            return len(session.execute(stmt).all())

    def list_sends(
        self, *, tenant_id: UUID, campaign_id: UUID, status: str | None = None
    ) -> list[CampaignSendRecord]:
        with tenant_session(tenant_id) as session:
            query = (
                select(WhatsAppCampaignSend)
                .where(WhatsAppCampaignSend.campaign_id == campaign_id)
                .order_by(WhatsAppCampaignSend.phone_e164)
            )
            if status is not None:
                query = query.where(WhatsAppCampaignSend.status == status)
            return [_send(r) for r in session.scalars(query)]

    def enqueue_send(
        self,
        *,
        tenant_id: UUID,
        send_id: UUID,
        connection_id: UUID,
        payload: dict[str, Any],
        next_attempt_at: datetime,
        created_by_user_id: UUID | None,
    ) -> UUID | None:
        with tenant_session(tenant_id) as session:
            send = session.get(WhatsAppCampaignSend, send_id, with_for_update=True)
            if send is None or send.outbox_id is not None or send.status != "pending":
                return None
            item = WhatsAppOutboxItem(
                tenant_id=tenant_id,
                connection_id=connection_id,
                thread_id=None,
                kind=OUTBOX_KIND_CAMPAIGN,
                payload=payload,
                next_attempt_at=next_attempt_at,
                created_by_user_id=created_by_user_id,
            )
            session.add(item)
            session.flush()
            send.outbox_id = item.id
            send.status = "queued"
            send.updated_at = _utcnow()
            return item.id

    def skip_send(self, *, tenant_id: UUID, send_id: UUID, error_code: str) -> bool:
        with tenant_session(tenant_id) as session:
            result = session.execute(
                update(WhatsAppCampaignSend)
                .where(
                    WhatsAppCampaignSend.id == send_id,
                    WhatsAppCampaignSend.status == "pending",
                )
                .values(status="skipped", error_code=error_code, updated_at=_utcnow())
            )
            return bool(result.rowcount)

    def cancel_open_sends(self, *, tenant_id: UUID, campaign_id: UUID) -> int:
        with tenant_session(tenant_id) as session:
            queued = session.execute(_CANCEL_OUTBOX, {"campaign_id": campaign_id}).rowcount or 0
            pending = (
                session.execute(
                    update(WhatsAppCampaignSend)
                    .where(
                        WhatsAppCampaignSend.campaign_id == campaign_id,
                        WhatsAppCampaignSend.status == "pending",
                        WhatsAppCampaignSend.outbox_id.is_(None),
                    )
                    .values(status="skipped", error_code=ERROR_CANCELLED, updated_at=_utcnow())
                ).rowcount
                or 0
            )
            return queued + pending


# Only rows the sender has not claimed yet (`pending`); a `sending` row is mid-flight and
# settles on its own. The trigger mirrors each into a `skipped` send.
_CANCEL_OUTBOX = text(
    f"""
    UPDATE whatsapp_outbox SET status = 'failed', error_code = '{ERROR_CANCELLED}'
     WHERE status = 'pending' AND kind = '{OUTBOX_KIND_CAMPAIGN}'
       AND id IN (SELECT outbox_id FROM whatsapp_campaign_sends
                   WHERE campaign_id = :campaign_id AND outbox_id IS NOT NULL)
    """
)

# Worker door. Postgres needs SELECT on every column an UPDATE *reads* — `COALESCE(:x,
# error_code)` would read `error_code`, which the worker may write but not read (0060).
# So the receipt is two statements in one transaction: lock and read `id, status` (both
# granted), decide in Python, then SET only literal values for the columns that change.
_LOCK_SEND = text(
    """
    SELECT id, status FROM whatsapp_campaign_sends
     WHERE tenant_id = :tenant_id AND wamid = :wamid
     FOR UPDATE
    """
)

SessionFactory = Callable[[], AbstractContextManager[Session]]


class PostgresCampaignReceiptRepository:
    """The worker door (`qualify_webhook_worker`, BYPASSRLS): tenant predicate in SQL."""

    def __init__(self, session_factory: SessionFactory = webhook_worker_session) -> None:
        self._session = session_factory

    def apply_receipt(
        self,
        *,
        tenant_id: UUID,
        wamid: str,
        status: str,
        error_code: str | None,
        price_category: str | None,
    ) -> bool:
        mapped = receipt_status(status, error_code)
        with self._session() as session:
            rows = session.execute(_LOCK_SEND, {"tenant_id": tenant_id, "wamid": wamid}).all()
            for send_id, current in rows:
                values: dict[str, Any] = {}
                if _SEND_RANK.get(current, 5) < _SEND_RANK[mapped]:
                    values["status"] = mapped
                    if error_code is not None:
                        values["error_code"] = error_code
                if price_category is not None:
                    values["price_category"] = price_category
                if not values:
                    continue
                values["updated_at"] = _utcnow()
                session.execute(
                    update(WhatsAppCampaignSend)
                    .where(WhatsAppCampaignSend.id == send_id)
                    .values(**values)
                )
        return bool(rows)


# --------------------------------------------------------------------------------------
# Memory (offline tests) — both seams, plus the trigger's behaviour as a helper
# --------------------------------------------------------------------------------------


class MemoryCampaignRepository:
    def __init__(self) -> None:
        self.campaigns: dict[UUID, CampaignRecord] = {}
        self.sends: dict[UUID, CampaignSendRecord] = {}
        self.outbox: dict[UUID, dict[str, Any]] = {}

    def insert_campaign(self, record: CampaignRecord) -> CampaignRecord:
        now = _utcnow()
        stored = replace(record, created_at=now, updated_at=now)
        self.campaigns[record.id] = stored
        return stored

    def get_campaign(self, *, tenant_id: UUID, campaign_id: UUID) -> CampaignRecord | None:
        row = self.campaigns.get(campaign_id)
        return row if row is not None and row.tenant_id == tenant_id else None

    def list_campaigns(self, *, tenant_id: UUID) -> list[CampaignRecord]:
        return [c for c in self.campaigns.values() if c.tenant_id == tenant_id]

    def transition(
        self,
        *,
        tenant_id: UUID,
        campaign_id: UUID,
        to: str,
        allowed_from: frozenset[str],
        now: datetime,
    ) -> CampaignRecord | None:
        row = self.get_campaign(tenant_id=tenant_id, campaign_id=campaign_id)
        if row is None or row.status not in allowed_from:
            return None
        changes: dict[str, Any] = {"status": to, "updated_at": now}
        if to == "running" and row.started_at is None:
            changes["started_at"] = now
        if to in FINAL_STATUSES:
            changes["finished_at"] = now
        self.campaigns[campaign_id] = replace(row, **changes)
        return self.campaigns[campaign_id]

    def insert_sends(self, *, tenant_id: UUID, campaign_id: UUID, sends: list[NewSend]) -> int:
        existing = {s.phone_e164 for s in self.sends.values() if s.campaign_id == campaign_id}
        inserted = 0
        for new in sends:
            if new.phone_e164 in existing:
                continue
            record = CampaignSendRecord(
                id=uuid4(),
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                phone_e164=new.phone_e164,
                cost_estimate=new.cost_estimate,
                currency=new.currency,
                updated_at=_utcnow(),
            )
            self.sends[record.id] = record
            existing.add(new.phone_e164)
            inserted += 1
        return inserted

    def list_sends(
        self, *, tenant_id: UUID, campaign_id: UUID, status: str | None = None
    ) -> list[CampaignSendRecord]:
        return sorted(
            (
                s
                for s in self.sends.values()
                if s.tenant_id == tenant_id
                and s.campaign_id == campaign_id
                and (status is None or s.status == status)
            ),
            key=lambda s: s.phone_e164,
        )

    def enqueue_send(
        self,
        *,
        tenant_id: UUID,
        send_id: UUID,
        connection_id: UUID,
        payload: dict[str, Any],
        next_attempt_at: datetime,
        created_by_user_id: UUID | None,
    ) -> UUID | None:
        send = self.sends.get(send_id)
        if send is None or send.outbox_id is not None or send.status != "pending":
            return None
        outbox_id = uuid4()
        self.outbox[outbox_id] = {
            "tenant_id": tenant_id,
            "connection_id": connection_id,
            "kind": OUTBOX_KIND_CAMPAIGN,
            "payload": payload,
            "next_attempt_at": next_attempt_at,
            "status": "pending",
        }
        self.sends[send_id] = replace(send, outbox_id=outbox_id, status="queued")
        return outbox_id

    def skip_send(self, *, tenant_id: UUID, send_id: UUID, error_code: str) -> bool:
        send = self.sends.get(send_id)
        if send is None or send.status != "pending":
            return False
        self.sends[send_id] = replace(send, status="skipped", error_code=error_code)
        return True

    def cancel_open_sends(self, *, tenant_id: UUID, campaign_id: UUID) -> int:
        affected = 0
        for send in self.list_sends(tenant_id=tenant_id, campaign_id=campaign_id):
            if send.outbox_id is not None and self.outbox[send.outbox_id]["status"] == "pending":
                self.settle_outbox(send.outbox_id, status="failed", error_code=ERROR_CANCELLED)
                affected += 1
            elif send.status == "pending" and send.outbox_id is None:
                self.skip_send(tenant_id=tenant_id, send_id=send.id, error_code=ERROR_CANCELLED)
                affected += 1
        return affected

    # The trigger `wa_outbox_campaign_mirror`, emulated for offline tests.
    def settle_outbox(
        self,
        outbox_id: UUID,
        *,
        status: str,
        wamid: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self.outbox[outbox_id]["status"] = status
        for send_id, send in list(self.sends.items()):
            if send.outbox_id != outbox_id or send.status not in OPEN_SEND_STATUSES:
                continue
            if status == "sent":
                self.sends[send_id] = replace(send, status="sent", wamid=wamid, error_code=None)
            elif status in ("failed", "dead"):
                skipped = error_code in (ERROR_PER_USER_LIMIT, ERROR_CANCELLED)
                self.sends[send_id] = replace(
                    send, status="skipped" if skipped else "failed", error_code=error_code
                )

    def apply_receipt(
        self,
        *,
        tenant_id: UUID,
        wamid: str,
        status: str,
        error_code: str | None,
        price_category: str | None,
    ) -> bool:
        mapped = receipt_status(status, error_code)
        for send_id, send in self.sends.items():
            if send.tenant_id != tenant_id or send.wamid != wamid:
                continue
            forward = _SEND_RANK[send.status] < _SEND_RANK[mapped]
            self.sends[send_id] = replace(
                send,
                status=mapped if forward else send.status,
                error_code=(error_code or send.error_code) if forward else send.error_code,
                price_category=price_category or send.price_category,
                updated_at=_utcnow(),
            )
            return True
        return False


# ======================================================================================
# Service
# ======================================================================================


class CampaignService:
    def __init__(
        self,
        repository: CampaignRepository,
        templates: TemplateRepository,
        opt_ins: OptInRepository,
        *,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._repo = repository
        self._templates = templates
        self._opt_ins = opt_ins
        self._clock = clock

    # -- reads ---------------------------------------------------------------------------

    def get(self, *, tenant_id: UUID, campaign_id: UUID) -> CampaignRecord:
        record = self._repo.get_campaign(tenant_id=tenant_id, campaign_id=campaign_id)
        if record is None:
            raise CampaignNotFound(str(campaign_id))
        return record

    def list(self, *, tenant_id: UUID) -> list[CampaignRecord]:
        return self._repo.list_campaigns(tenant_id=tenant_id)

    def sends(
        self, *, tenant_id: UUID, campaign_id: UUID, status: str | None = None
    ) -> list[CampaignSendRecord]:
        if status is not None and status not in CAMPAIGN_SEND_STATUSES:
            raise ValueError(f"status must be one of {CAMPAIGN_SEND_STATUSES}")
        return self._repo.list_sends(tenant_id=tenant_id, campaign_id=campaign_id, status=status)

    def build_audience(
        self, *, tenant_id: UUID, audience_filter: AudienceFilter | dict[str, Any] | None
    ) -> list[OptInRecord]:
        """Live (non-revoked) opt-ins matching the filter, one per phone."""
        audience = (
            audience_filter
            if isinstance(audience_filter, AudienceFilter)
            else AudienceFilter.from_json(audience_filter)
        )
        return [r for r in self._opt_ins.list_active(tenant_id=tenant_id) if audience.matches(r)]

    def estimate(self, *, tenant_id: UUID, campaign_id: UUID) -> CampaignEstimate:
        campaign = self.get(tenant_id=tenant_id, campaign_id=campaign_id)
        template = self._template(campaign)
        sends = self._new_sends(
            self.build_audience(tenant_id=tenant_id, audience_filter=campaign.audience),
            template,
        )
        return self._estimate(sends, template)

    def summary(self, *, tenant_id: UUID, campaign_id: UUID) -> CampaignSummary:
        campaign = self.get(tenant_id=tenant_id, campaign_id=campaign_id)
        sends = self._repo.list_sends(tenant_id=tenant_id, campaign_id=campaign_id)
        counts = Counter(s.status for s in sends)
        return CampaignSummary(
            campaign_id=campaign_id,
            status=campaign.status,
            counts={status: counts.get(status, 0) for status in CAMPAIGN_SEND_STATUSES},
            costs=_costs(sends),
            retry_after_24h=sum(1 for s in sends if s.error_code == ERROR_PER_USER_LIMIT),
        )

    # -- writes --------------------------------------------------------------------------

    def create(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        template_id: UUID,
        name: str,
        created_by_user_id: UUID,
        audience: AudienceFilter | None = None,
        send_components: list[dict[str, Any]] | None = None,
        max_per_minute: int = DEFAULT_MAX_PER_MINUTE,
        brand_id: UUID | None = None,
        scheduled_at: datetime | None = None,
    ) -> CampaignRecord:
        """A `draft` (or `scheduled`, when `scheduled_at` is in the future). The template
        must exist on the WABA of the connection's number; it need not be approved yet —
        that is checked at launch."""
        if not name or not name.strip():
            raise ValueError("campaign name must not be blank")
        if not 1 <= max_per_minute <= 1000:
            raise ValueError("max_per_minute must be between 1 and 1000")
        template = self._templates.get(tenant_id=tenant_id, template_id=template_id)
        if template is None:
            raise TemplateNotFound(str(template_id))
        self._check_waba(tenant_id, connection_id, template)
        now = self._clock()
        status = "scheduled" if scheduled_at is not None and scheduled_at > now else "draft"
        return self._repo.insert_campaign(
            CampaignRecord(
                id=uuid4(),
                tenant_id=tenant_id,
                brand_id=brand_id,
                connection_id=connection_id,
                template_id=template_id,
                name=name.strip(),
                status=status,
                audience_filter=(audience or AudienceFilter()).to_json(),
                send_components=list(send_components or []),
                max_per_minute=max_per_minute,
                scheduled_at=scheduled_at,
                created_by_user_id=created_by_user_id,
            )
        )

    def launch(self, *, tenant_id: UUID, campaign_id: UUID, user_id: UUID | None) -> LaunchReport:
        """See the module docstring. Safe to call again: it resumes."""
        now = self._clock()
        campaign = self.get(tenant_id=tenant_id, campaign_id=campaign_id)
        if campaign.status not in LAUNCHABLE_STATUSES:
            raise CampaignStateError(f"cannot launch a {campaign.status} campaign")
        template = self._template(campaign)
        if not template.is_sendable:
            raise TemplateNotSendable(f"template status is {template.status}")
        self._check_waba(tenant_id, campaign.connection_id, template)

        audience = self.build_audience(tenant_id=tenant_id, audience_filter=campaign.audience)
        inserted = self._repo.insert_sends(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            sends=self._new_sends(audience, template),
        )
        if (
            self._repo.transition(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                to="running",
                allowed_from=LAUNCHABLE_STATUSES,
                now=now,
            )
            is None
        ):
            raise CampaignStateError("the campaign changed state during launch")

        start = max(now, campaign.scheduled_at) if campaign.scheduled_at else now
        step = timedelta(seconds=60 / campaign.max_per_minute)
        enqueued = skipped = 0
        first_due = last_due = None
        for send in self._repo.list_sends(
            tenant_id=tenant_id, campaign_id=campaign_id, status="pending"
        ):
            if send.outbox_id is not None:
                continue
            opt_in = self._opt_ins.get(tenant_id=tenant_id, phone_e164=send.phone_e164)
            if opt_in is None or not opt_in.is_active:
                skipped += self._repo.skip_send(
                    tenant_id=tenant_id, send_id=send.id, error_code=ERROR_NOT_OPTED_IN
                )
                continue
            due = start + step * enqueued
            outbox_id = self._repo.enqueue_send(
                tenant_id=tenant_id,
                send_id=send.id,
                connection_id=campaign.connection_id,
                payload=build_template_body(
                    send.phone_e164,
                    template.name,
                    template.language,
                    campaign.send_components or None,
                ),
                next_attempt_at=due,
                created_by_user_id=user_id,
            )
            if outbox_id is None:
                continue
            enqueued += 1
            first_due = first_due or due
            last_due = due
        report = LaunchReport(
            campaign_id=campaign_id,
            audience=len(audience),
            inserted=inserted,
            enqueued=enqueued,
            skipped=skipped,
            first_due_at=first_due,
            last_due_at=last_due,
        )
        logger.info(
            "whatsapp.campaigns.launch tenant_id=%s campaign_id=%s audience=%d inserted=%d "
            "enqueued=%d skipped=%d",
            tenant_id,
            campaign_id,
            report.audience,
            report.inserted,
            report.enqueued,
            report.skipped,
        )
        return report

    def cancel(self, *, tenant_id: UUID, campaign_id: UUID) -> int:
        """Cancel a non-final campaign: unclaimed outbox rows are withdrawn, their sends
        become `skipped` (`campaign_cancelled`). Rows already being sent finish."""
        campaign = self.get(tenant_id=tenant_id, campaign_id=campaign_id)
        if campaign.status in FINAL_STATUSES:
            raise CampaignStateError(f"cannot cancel a {campaign.status} campaign")
        withdrawn = self._repo.cancel_open_sends(tenant_id=tenant_id, campaign_id=campaign_id)
        self._repo.transition(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            to="cancelled",
            allowed_from=frozenset(LAUNCHABLE_STATUSES | {"paused"}),
            now=self._clock(),
        )
        return withdrawn

    def finalize_if_complete(self, *, tenant_id: UUID, campaign_id: UUID) -> bool:
        """`running` → `done` once no send is `pending`/`queued`. Cheap to call often
        (the UI on refresh, the worker after a batch)."""
        campaign = self.get(tenant_id=tenant_id, campaign_id=campaign_id)
        if campaign.status != "running":
            return False
        sends = self._repo.list_sends(tenant_id=tenant_id, campaign_id=campaign_id)
        if any(s.status in OPEN_SEND_STATUSES for s in sends):
            return False
        return (
            self._repo.transition(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                to="done",
                allowed_from=frozenset({"running"}),
                now=self._clock(),
            )
            is not None
        )

    # -- helpers -------------------------------------------------------------------------

    def _template(self, campaign: CampaignRecord) -> TemplateRecord:
        template = self._templates.get(
            tenant_id=campaign.tenant_id, template_id=campaign.template_id
        )
        if template is None:
            raise TemplateNotFound(str(campaign.template_id))
        return template

    def _check_waba(self, tenant_id: UUID, connection_id: UUID, template: TemplateRecord) -> None:
        ref = self._templates.waba_for_connection(tenant_id=tenant_id, connection_id=connection_id)
        if ref is None or ref.waba_id != template.waba_id:
            raise TemplateNotSendable("the template is not on this number's WABA")

    @staticmethod
    def _new_sends(audience: list[OptInRecord], template: TemplateRecord) -> list[NewSend]:
        sends = []
        for opt_in in audience:
            cost = estimate_cost(opt_in.phone_e164, template.category)
            sends.append(
                NewSend(
                    phone_e164=opt_in.phone_e164,
                    cost_estimate=cost.amount if cost else None,
                    currency=cost.currency if cost else None,
                )
            )
        return sends

    @staticmethod
    def _estimate(sends: list[NewSend], template: TemplateRecord) -> CampaignEstimate:
        placeholder = any(
            (cost := estimate_cost(s.phone_e164, template.category)) is not None
            and cost.placeholder
            for s in sends
        )
        return CampaignEstimate(
            recipients=len(sends),
            costs=_costs(sends),
            unpriced=sum(1 for s in sends if s.cost_estimate is None),
            placeholder=placeholder,
        )


def production_campaign_service() -> CampaignService:
    from qualify_api.whatsapp.optins import PostgresOptInRepository  # noqa: PLC0415
    from qualify_api.whatsapp.templates import PostgresTemplateRepository  # noqa: PLC0415

    return CampaignService(
        PostgresCampaignRepository(), PostgresTemplateRepository(), PostgresOptInRepository()
    )


__all__ = [
    "DEFAULT_MAX_PER_MINUTE",
    "ERROR_CANCELLED",
    "ERROR_NOT_OPTED_IN",
    "ERROR_PER_USER_LIMIT",
    "RETRY_AFTER_PER_USER_LIMIT",
    "SKIP_NOTES",
    "CampaignEstimate",
    "CampaignError",
    "CampaignNotFound",
    "CampaignReceiptRepository",
    "CampaignRecord",
    "CampaignRepository",
    "CampaignSendRecord",
    "CampaignService",
    "CampaignStateError",
    "CampaignSummary",
    "CostLine",
    "LaunchReport",
    "MemoryCampaignRepository",
    "NewSend",
    "PostgresCampaignReceiptRepository",
    "PostgresCampaignRepository",
    "TemplateNotSendable",
    "production_campaign_service",
    "receipt_status",
]

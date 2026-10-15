"""WhatsApp message templates (WA-18, QUA-217): the WABA mirror, its service and the
template webhooks.

Backlog: `docs/backlog-modulo-whatsapp.md` §5 WA-18. Plan §2.4 (250 templates unverified →
6,000 verified; 100 creations/hour; automatic review "up to 24 h") and §5.4. Schema:
migration 0060 / `models.WhatsAppTemplate`.

## Three writers, one table

- **`TemplateService.create`** (the app, `qualify_app` under `tenant_session`) — Meta
  FIRST, then the row: `POST /{WABA_ID}/message_templates` returns `{id, status,
  category}` and the row is inserted with exactly that. The opposite order would leave a
  row Meta never heard of whenever the call fails; this order can only leave a template
  Meta has and the mirror lacks — which `sync_from_meta` repairs.
- **`TemplateService.sync_from_meta`** — `GET /{WABA_ID}/message_templates`, every page,
  upserted by the natural key `(tenant_id, waba_id, name, language)`. Templates authored
  in WhatsApp Manager appear here; nothing is deleted locally (a template Meta no longer
  lists keeps its last status — Meta reports deletions as `DELETED`/`PENDING_DELETION`
  events, not as absence).
- **`template_status_handler`** (the intake processor, `qualify_webhook_worker`) —
  `message_template_status_update` / `message_template_quality_update`. The tenant comes
  from the envelope's WABA id (`resolve.resolve_waba`), never from the payload. The row is
  found by `meta_template_id`, else by `(name, language)`; the worker may UPDATE only
  `status, quality, rejected_reason, updated_at` (0060). A webhook for a template the
  mirror does not have yet (authored elsewhere, not synced) is `processed` and changes
  nothing — the worker cannot INSERT templates, by design; the next sync brings it.

## Status, verbatim

`status` is Meta's string as given (`APPROVED`, `PENDING`, `REJECTED`, `PAUSED`,
`DISABLED`, `IN_APPEAL`, `PENDING_DELETION`, `DELETED`, `LIMIT_EXCEEDED`, `ARCHIVED`,
`LOCKED`, `FLAGGED`, `REINSTATED`, `UNARCHIVED` …). For a status event the stored status
is the `event`. Only `APPROVED` is sendable (`is_sendable`): `REINSTATED`/`UNARCHIVED`/
`FLAGGED` are transitions whose resulting state the docs read on 2026-10-14 do not pin, so
a template in one of them is NOT offered to a campaign until a sync reports its real
status. No ordering guard: the status webhook carries no timestamp in its `value`, so the
last event processed wins (Meta retries for up to 7 days; a re-sync is the repair).

`rejected_reason` keeps Meta's enum (`INVALID_FORMAT`, `PROMOTIONAL`, …) plus, when Meta
sends `rejection_info`, its explanation after a colon — Meta-authored prose, never user
text, truncated to `MAX_REJECTED_REASON_CHARS`. `NONE` is stored as `NULL`.

No user text in logs: ids, names of templates (a business identifier, not a person's
words) and enumerations only.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

from pydantic import ValidationError
from qualify_shared.db.session import tenant_session
from qualify_shared.db.webhook import webhook_worker_session
from qualify_shared.social.wa_shapes import (
    FIELD_TEMPLATE_QUALITY,
    FIELD_TEMPLATE_STATUS,
    OBJECT_WHATSAPP_BUSINESS_ACCOUNT,
    WATemplateQualityUpdate,
    WATemplateStatusUpdate,
)
from sqlalchemy import literal_column, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from qualify_api.webhooks.processor import Handler, Outcome, handler_key
from qualify_api.webhooks.repository import (
    STATUS_AMBIGUOUS,
    STATUS_DEAD,
    STATUS_ORPHAN,
    STATUS_PROCESSED,
    STATUS_UNSUPPORTED,
    ClaimedEvent,
)
from qualify_api.whatsapp.client import (
    TemplateInfo,
    WhatsAppClient,
    build_template_create_body,
)
from qualify_api.whatsapp.models import (
    TEMPLATE_CATEGORIES,
    WhatsAppPhoneNumber,
    WhatsAppTemplate,
)
from qualify_api.whatsapp.resolve import PhoneResolution, PhoneResolutionOutcome

logger = logging.getLogger("qualify_api.whatsapp.templates")

TEMPLATE_STATUS_HANDLER_KEY: Final = handler_key(
    OBJECT_WHATSAPP_BUSINESS_ACCOUNT, FIELD_TEMPLATE_STATUS
)
TEMPLATE_QUALITY_HANDLER_KEY: Final = handler_key(
    OBJECT_WHATSAPP_BUSINESS_ACCOUNT, FIELD_TEMPLATE_QUALITY
)

STATUS_APPROVED: Final = "APPROVED"
STATUS_DELETED: Final = "DELETED"
SENDABLE_TEMPLATE_STATUSES: Final = frozenset({STATUS_APPROVED})
MAX_REJECTED_REASON_CHARS: Final = 500


def is_sendable(status: str) -> bool:
    return status in SENDABLE_TEMPLATE_STATUSES


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ======================================================================================
# Records and errors
# ======================================================================================


@dataclass(frozen=True)
class TemplateRecord:
    id: UUID
    tenant_id: UUID
    waba_id: str
    name: str
    language: str
    category: str
    status: str
    components: list[dict[str, Any]] = field(default_factory=list)
    phone_number_row_id: UUID | None = None
    meta_template_id: str | None = None
    quality: str | None = None
    rejected_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_sendable(self) -> bool:
        return is_sendable(self.status)


@dataclass(frozen=True)
class WabaRef:
    """The WABA a connection's number hangs off, and that number's row."""

    waba_id: str
    phone_number_row_id: UUID


@dataclass(frozen=True)
class SyncReport:
    listed: int
    created: int
    updated: int


class TemplateError(Exception):
    """Base for the service's domain errors (the UI maps them to messages)."""


class TemplateAlreadyExists(TemplateError):
    """`(waba_id, name, language)` is already mirrored for this tenant."""


class TemplateNotFound(TemplateError):
    pass


class NoWhatsAppNumber(TemplateError):
    """The connection has no `whatsapp_phone_numbers` row — no WABA to talk to."""


def rejected_reason_from(update: WATemplateStatusUpdate) -> str | None:
    """`reason` enum (+ `rejection_info.reason` after a colon), `NONE`/null → `None`."""
    reason = update.reason if update.reason and update.reason != "NONE" else None
    detail = update.rejection_info.reason if update.rejection_info else None
    if reason is None and not detail:
        return None
    combined = f"{reason or 'REJECTED'}: {detail}" if detail else reason
    return combined[:MAX_REJECTED_REASON_CHARS] if combined else None


# ======================================================================================
# Repository seams
# ======================================================================================


class TemplateRepository(Protocol):
    """The app side (`qualify_app` under `tenant_session`): every method tenant-scoped."""

    def waba_for_connection(self, *, tenant_id: UUID, connection_id: UUID) -> WabaRef | None: ...

    def find(
        self, *, tenant_id: UUID, waba_id: str, name: str, language: str
    ) -> TemplateRecord | None: ...

    def get(self, *, tenant_id: UUID, template_id: UUID) -> TemplateRecord | None: ...

    def list(self, *, tenant_id: UUID, waba_id: str | None = None) -> list[TemplateRecord]: ...

    def insert(self, record: TemplateRecord) -> TemplateRecord:
        """Raises `TemplateAlreadyExists` on the natural key."""
        ...

    def upsert_from_meta(
        self,
        *,
        tenant_id: UUID,
        waba_id: str,
        info: TemplateInfo,
        phone_number_row_id: UUID | None,
    ) -> bool:
        """Insert or refresh by natural key; returns True when it INSERTED."""
        ...

    def set_status_by_name(self, *, tenant_id: UUID, waba_id: str, name: str, status: str) -> int:
        """Every language of `name` (Meta's delete-by-name removes them all)."""
        ...


class TemplateWebhookRepository(Protocol):
    """The worker side (`qualify_webhook_worker`, BYPASSRLS): the tenant predicate is
    applied by the code, from the WABA resolution. Returns whether a row was updated."""

    def apply_status(
        self,
        *,
        tenant_id: UUID,
        waba_id: str,
        meta_template_id: str,
        name: str,
        language: str,
        status: str,
        rejected_reason: str | None,
    ) -> bool: ...

    def apply_quality(
        self,
        *,
        tenant_id: UUID,
        waba_id: str,
        meta_template_id: str,
        name: str,
        language: str,
        quality: str,
    ) -> bool: ...


# --------------------------------------------------------------------------------------
# Postgres
# --------------------------------------------------------------------------------------


def _record(row: WhatsAppTemplate) -> TemplateRecord:
    return TemplateRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        waba_id=row.waba_id,
        name=row.name,
        language=row.language,
        category=row.category,
        status=row.status,
        components=list(row.components or []),
        phone_number_row_id=row.phone_number_row_id,
        meta_template_id=row.meta_template_id,
        quality=row.quality,
        rejected_reason=row.rejected_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PostgresTemplateRepository:
    """`qualify_app` through `tenant_session(tenant_id)` — RLS bounds every statement."""

    def waba_for_connection(self, *, tenant_id: UUID, connection_id: UUID) -> WabaRef | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                select(WhatsAppPhoneNumber.waba_id, WhatsAppPhoneNumber.id)
                .where(WhatsAppPhoneNumber.connection_id == connection_id)
                .order_by(WhatsAppPhoneNumber.created_at, WhatsAppPhoneNumber.id)
                .limit(1)
            ).first()
        return WabaRef(waba_id=row[0], phone_number_row_id=row[1]) if row else None

    def find(
        self, *, tenant_id: UUID, waba_id: str, name: str, language: str
    ) -> TemplateRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.scalars(
                select(WhatsAppTemplate).where(
                    WhatsAppTemplate.waba_id == waba_id,
                    WhatsAppTemplate.name == name,
                    WhatsAppTemplate.language == language,
                )
            ).first()
            return _record(row) if row else None

    def get(self, *, tenant_id: UUID, template_id: UUID) -> TemplateRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.get(WhatsAppTemplate, template_id)
            return _record(row) if row else None

    def list(self, *, tenant_id: UUID, waba_id: str | None = None) -> list[TemplateRecord]:
        with tenant_session(tenant_id) as session:
            query = select(WhatsAppTemplate).order_by(
                WhatsAppTemplate.name, WhatsAppTemplate.language
            )
            if waba_id is not None:
                query = query.where(WhatsAppTemplate.waba_id == waba_id)
            return [_record(r) for r in session.scalars(query)]

    def insert(self, record: TemplateRecord) -> TemplateRecord:
        try:
            with tenant_session(record.tenant_id) as session:
                row = WhatsAppTemplate(
                    id=record.id,
                    tenant_id=record.tenant_id,
                    waba_id=record.waba_id,
                    phone_number_row_id=record.phone_number_row_id,
                    meta_template_id=record.meta_template_id,
                    name=record.name,
                    language=record.language,
                    category=record.category,
                    status=record.status,
                    quality=record.quality,
                    components=record.components,
                    rejected_reason=record.rejected_reason,
                )
                session.add(row)
                session.flush()
                session.refresh(row)
                return _record(row)
        except IntegrityError as exc:
            if "uq_wa_template_natural_key" in str(exc.orig):
                raise TemplateAlreadyExists(record.name) from exc
            raise

    def upsert_from_meta(
        self,
        *,
        tenant_id: UUID,
        waba_id: str,
        info: TemplateInfo,
        phone_number_row_id: UUID | None,
    ) -> bool:
        values = {
            "meta_template_id": info.id,
            "category": info.category,
            "status": info.status,
            "quality": info.quality,
            "components": info.components,
            "rejected_reason": info.rejected_reason,
        }
        stmt = pg_insert(WhatsAppTemplate).values(
            id=uuid4(),
            tenant_id=tenant_id,
            waba_id=waba_id,
            phone_number_row_id=phone_number_row_id,
            name=info.name,
            language=info.language,
            **values,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_wa_template_natural_key",
            set_={**{k: stmt.excluded[k] for k in values}, "updated_at": text("now()")},
        ).returning(literal_column("(xmax = 0)").label("inserted"))
        with tenant_session(tenant_id) as session:
            return bool(session.execute(stmt).scalar_one())

    def set_status_by_name(self, *, tenant_id: UUID, waba_id: str, name: str, status: str) -> int:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(WhatsAppTemplate).where(
                    WhatsAppTemplate.waba_id == waba_id, WhatsAppTemplate.name == name
                )
            ).all()
            for row in rows:
                row.status = status
                row.updated_at = _utcnow()
            return len(rows)


SessionFactory = Callable[[], AbstractContextManager[Session]]

# The worker's UPDATEs read only granted columns in their WHERE (0060): `tenant_id,
# waba_id, meta_template_id` first, `name, language` as the fallback for a row whose
# `meta_template_id` is still NULL. `RETURNING id` is granted too.
_APPLY_TEMPLATE = """
    UPDATE whatsapp_templates SET {set_clause}, updated_at = now()
     WHERE tenant_id = :tenant_id AND waba_id = :waba_id
       AND (meta_template_id = :meta_template_id
            OR (meta_template_id IS NULL AND name = :name AND language = :language))
    RETURNING id
"""
_APPLY_STATUS = text(
    _APPLY_TEMPLATE.format(set_clause="status = :status, rejected_reason = :rejected_reason")
)
_APPLY_QUALITY = text(_APPLY_TEMPLATE.format(set_clause="quality = :quality"))


class PostgresTemplateWebhookRepository:
    """The worker door. `session_factory` defaults to `webhook_worker_session`."""

    def __init__(self, session_factory: SessionFactory = webhook_worker_session) -> None:
        self._session = session_factory

    def _apply(self, statement: Any, params: dict[str, Any]) -> bool:
        with self._session() as session:
            return bool(session.execute(statement, params).all())

    def apply_status(
        self,
        *,
        tenant_id: UUID,
        waba_id: str,
        meta_template_id: str,
        name: str,
        language: str,
        status: str,
        rejected_reason: str | None,
    ) -> bool:
        return self._apply(
            _APPLY_STATUS,
            {
                "tenant_id": tenant_id,
                "waba_id": waba_id,
                "meta_template_id": meta_template_id,
                "name": name,
                "language": language,
                "status": status,
                "rejected_reason": rejected_reason,
            },
        )

    def apply_quality(
        self,
        *,
        tenant_id: UUID,
        waba_id: str,
        meta_template_id: str,
        name: str,
        language: str,
        quality: str,
    ) -> bool:
        return self._apply(
            _APPLY_QUALITY,
            {
                "tenant_id": tenant_id,
                "waba_id": waba_id,
                "meta_template_id": meta_template_id,
                "name": name,
                "language": language,
                "quality": quality,
            },
        )


# --------------------------------------------------------------------------------------
# Memory (offline tests) — one object implements both seams
# --------------------------------------------------------------------------------------


class MemoryTemplateRepository:
    def __init__(self, *, clock: Callable[[], datetime] = _utcnow) -> None:
        self.rows: dict[UUID, TemplateRecord] = {}
        self.wabas: dict[tuple[UUID, UUID], WabaRef] = {}
        self._clock = clock

    # test helper
    def add_number(
        self, *, tenant_id: UUID, connection_id: UUID, waba_id: str, phone_row_id: UUID
    ) -> None:
        self.wabas[(tenant_id, connection_id)] = WabaRef(waba_id, phone_row_id)

    def waba_for_connection(self, *, tenant_id: UUID, connection_id: UUID) -> WabaRef | None:
        return self.wabas.get((tenant_id, connection_id))

    def find(
        self, *, tenant_id: UUID, waba_id: str, name: str, language: str
    ) -> TemplateRecord | None:
        return next(
            (
                r
                for r in self.rows.values()
                if (r.tenant_id, r.waba_id, r.name, r.language)
                == (tenant_id, waba_id, name, language)
            ),
            None,
        )

    def get(self, *, tenant_id: UUID, template_id: UUID) -> TemplateRecord | None:
        row = self.rows.get(template_id)
        return row if row is not None and row.tenant_id == tenant_id else None

    def list(self, *, tenant_id: UUID, waba_id: str | None = None) -> list[TemplateRecord]:
        return sorted(
            (
                r
                for r in self.rows.values()
                if r.tenant_id == tenant_id and (waba_id is None or r.waba_id == waba_id)
            ),
            key=lambda r: (r.name, r.language),
        )

    def insert(self, record: TemplateRecord) -> TemplateRecord:
        if self.find(
            tenant_id=record.tenant_id,
            waba_id=record.waba_id,
            name=record.name,
            language=record.language,
        ):
            raise TemplateAlreadyExists(record.name)
        now = self._clock()
        stored = replace(record, created_at=now, updated_at=now)
        self.rows[record.id] = stored
        return stored

    def upsert_from_meta(
        self,
        *,
        tenant_id: UUID,
        waba_id: str,
        info: TemplateInfo,
        phone_number_row_id: UUID | None,
    ) -> bool:
        existing = self.find(
            tenant_id=tenant_id, waba_id=waba_id, name=info.name, language=info.language
        )
        changes = {
            "meta_template_id": info.id,
            "category": info.category,
            "status": info.status,
            "quality": info.quality,
            "components": list(info.components),
            "rejected_reason": info.rejected_reason,
            "updated_at": self._clock(),
        }
        if existing is not None:
            self.rows[existing.id] = replace(existing, **changes)
            return False
        record = TemplateRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            waba_id=waba_id,
            name=info.name,
            language=info.language,
            category=info.category,
            status=info.status,
            phone_number_row_id=phone_number_row_id,
            created_at=self._clock(),
        )
        self.rows[record.id] = replace(record, **changes)
        return True

    def set_status_by_name(self, *, tenant_id: UUID, waba_id: str, name: str, status: str) -> int:
        hits = [
            r
            for r in self.rows.values()
            if (r.tenant_id, r.waba_id, r.name) == (tenant_id, waba_id, name)
        ]
        for r in hits:
            self.rows[r.id] = replace(r, status=status, updated_at=self._clock())
        return len(hits)

    def _match(
        self, tenant_id: UUID, waba_id: str, meta_template_id: str, name: str, language: str
    ) -> TemplateRecord | None:
        for r in self.rows.values():
            if (r.tenant_id, r.waba_id) != (tenant_id, waba_id):
                continue
            if r.meta_template_id == meta_template_id:
                return r
            if r.meta_template_id is None and (r.name, r.language) == (name, language):
                return r
        return None

    def apply_status(
        self,
        *,
        tenant_id: UUID,
        waba_id: str,
        meta_template_id: str,
        name: str,
        language: str,
        status: str,
        rejected_reason: str | None,
    ) -> bool:
        row = self._match(tenant_id, waba_id, meta_template_id, name, language)
        if row is None:
            return False
        self.rows[row.id] = replace(
            row, status=status, rejected_reason=rejected_reason, updated_at=self._clock()
        )
        return True

    def apply_quality(
        self,
        *,
        tenant_id: UUID,
        waba_id: str,
        meta_template_id: str,
        name: str,
        language: str,
        quality: str,
    ) -> bool:
        row = self._match(tenant_id, waba_id, meta_template_id, name, language)
        if row is None:
            return False
        self.rows[row.id] = replace(row, quality=quality, updated_at=self._clock())
        return True


# ======================================================================================
# Service (the app side)
# ======================================================================================


class ClientFactory(Protocol):
    """Same shape as `outbox.ClientFactory` (the production one is
    `outbox.ResolverClientFactory`): a client bound to the connection's number."""

    async def __call__(self, *, tenant_id: UUID, connection_id: UUID) -> WhatsAppClient: ...


class TemplateService:
    def __init__(self, repository: TemplateRepository, clients: ClientFactory) -> None:
        self._repo = repository
        self._clients = clients

    def _waba(self, tenant_id: UUID, connection_id: UUID) -> WabaRef:
        ref = self._repo.waba_for_connection(tenant_id=tenant_id, connection_id=connection_id)
        if ref is None:
            raise NoWhatsAppNumber(str(connection_id))
        return ref

    def list(self, *, tenant_id: UUID, connection_id: UUID | None = None) -> list[TemplateRecord]:
        """The tenant's mirror; scoped to the connection's WABA when one is given."""
        waba = self._waba(tenant_id, connection_id).waba_id if connection_id else None
        return self._repo.list(tenant_id=tenant_id, waba_id=waba)

    def get(self, *, tenant_id: UUID, template_id: UUID) -> TemplateRecord:
        record = self._repo.get(tenant_id=tenant_id, template_id=template_id)
        if record is None:
            raise TemplateNotFound(str(template_id))
        return record

    async def create(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        name: str,
        language: str,
        category: str,
        components: list[dict[str, Any]],
    ) -> TemplateRecord:
        """Validate locally (`ValueError`), refuse a duplicate natural key
        (`TemplateAlreadyExists`) BEFORE spending one of the 100 creations/hour, create
        at Meta (`WhatsAppApiError` propagates), then mirror what Meta answered."""
        build_template_create_body(name, language, category, components)
        ref = self._waba(tenant_id, connection_id)
        if self._repo.find(tenant_id=tenant_id, waba_id=ref.waba_id, name=name, language=language):
            raise TemplateAlreadyExists(name)
        client = await self._clients(tenant_id=tenant_id, connection_id=connection_id)
        result = await client.create_template(ref.waba_id, name, language, category, components)
        stored_category = (
            result.category if result.category in TEMPLATE_CATEGORIES else category.lower()
        )
        record = self._repo.insert(
            TemplateRecord(
                id=uuid4(),
                tenant_id=tenant_id,
                waba_id=ref.waba_id,
                phone_number_row_id=ref.phone_number_row_id,
                meta_template_id=result.id,
                name=name,
                language=language,
                category=stored_category,
                status=result.status,
                components=components,
            )
        )
        logger.info(
            "whatsapp.templates.created tenant_id=%s waba_id=%s template=%s/%s status=%s",
            tenant_id,
            ref.waba_id,
            name,
            language,
            result.status,
        )
        return record

    async def sync_from_meta(self, *, tenant_id: UUID, connection_id: UUID) -> SyncReport:
        ref = self._waba(tenant_id, connection_id)
        client = await self._clients(tenant_id=tenant_id, connection_id=connection_id)
        listed = await client.list_templates(ref.waba_id)
        created = 0
        for info in listed:
            if info.category not in TEMPLATE_CATEGORIES:
                logger.warning(
                    "whatsapp.templates.sync_skipped tenant_id=%s template_id=%s category=%s",
                    tenant_id,
                    info.id,
                    info.category,
                )
                continue
            created += self._repo.upsert_from_meta(
                tenant_id=tenant_id,
                waba_id=ref.waba_id,
                info=info,
                phone_number_row_id=None,
            )
        report = SyncReport(listed=len(listed), created=created, updated=len(listed) - created)
        logger.info(
            "whatsapp.templates.synced tenant_id=%s waba_id=%s listed=%d created=%d",
            tenant_id,
            ref.waba_id,
            report.listed,
            report.created,
        )
        return report

    async def delete(self, *, tenant_id: UUID, connection_id: UUID, template_id: UUID) -> int:
        """Delete at Meta BY NAME — which removes every language of that name — then mark
        every mirrored language `DELETED` (rows are kept: campaigns reference them).
        Returns how many rows were marked."""
        record = self.get(tenant_id=tenant_id, template_id=template_id)
        ref = self._waba(tenant_id, connection_id)
        if record.waba_id != ref.waba_id:
            raise TemplateNotFound(str(template_id))
        client = await self._clients(tenant_id=tenant_id, connection_id=connection_id)
        await client.delete_template(ref.waba_id, record.name)
        return self._repo.set_status_by_name(
            tenant_id=tenant_id, waba_id=ref.waba_id, name=record.name, status=STATUS_DELETED
        )


# ======================================================================================
# The webhook handler (the worker side)
# ======================================================================================

WabaResolver = Callable[[str], PhoneResolution]


def template_status_handler(*, resolve: WabaResolver, repo: TemplateWebhookRepository) -> Handler:
    """One handler for both template fields; register it under BOTH
    `TEMPLATE_STATUS_HANDLER_KEY` and `TEMPLATE_QUALITY_HANDLER_KEY`."""

    def _process(event: ClaimedEvent) -> Outcome:
        try:
            if event.field == FIELD_TEMPLATE_STATUS:
                update: WATemplateStatusUpdate | WATemplateQualityUpdate = (
                    WATemplateStatusUpdate.model_validate(event.value or {})
                )
            elif event.field == FIELD_TEMPLATE_QUALITY:
                update = WATemplateQualityUpdate.model_validate(event.value or {})
            else:
                return Outcome(STATUS_UNSUPPORTED)
        except ValidationError:
            logger.error("whatsapp templates webhook: event=%s value off-contract", event.id)
            return Outcome(STATUS_DEAD, "contract_violation")

        resolution = resolve(event.entry_id)
        if resolution.outcome is PhoneResolutionOutcome.AMBIGUOUS:
            logger.warning(
                "whatsapp templates webhook: event=%s waba_id=%s spans tenants — not applied",
                event.id,
                event.entry_id,
            )
            return Outcome(STATUS_AMBIGUOUS)
        if resolution.outcome is not PhoneResolutionOutcome.RESOLVED:
            logger.warning(
                "whatsapp templates webhook: event=%s no connected number for waba_id=%s",
                event.id,
                event.entry_id,
            )
            return Outcome(STATUS_ORPHAN)
        assert resolution.tenant_id is not None

        keys = {
            "tenant_id": resolution.tenant_id,
            "waba_id": event.entry_id,
            "meta_template_id": update.message_template_id,
            "name": update.message_template_name,
            "language": update.message_template_language,
        }
        if isinstance(update, WATemplateStatusUpdate):
            applied = repo.apply_status(
                **keys, status=update.event, rejected_reason=rejected_reason_from(update)
            )
            what = f"status={update.event}"
        else:
            applied = repo.apply_quality(**keys, quality=update.new_quality_score)
            what = f"quality={update.new_quality_score}"
        logger.info(
            "whatsapp templates webhook: tenant=%s template_id=%s %s applied=%s",
            resolution.tenant_id,
            update.message_template_id,
            what,
            applied,
        )
        return Outcome(STATUS_PROCESSED)

    async def handle(event: ClaimedEvent) -> Outcome:
        return await asyncio.to_thread(_process, event)

    return handle


def production_template_handler() -> Handler:
    from qualify_api.whatsapp.resolve import resolve_waba  # noqa: PLC0415

    return template_status_handler(resolve=resolve_waba, repo=PostgresTemplateWebhookRepository())


__all__ = [
    "MAX_REJECTED_REASON_CHARS",
    "SENDABLE_TEMPLATE_STATUSES",
    "STATUS_APPROVED",
    "STATUS_DELETED",
    "TEMPLATE_QUALITY_HANDLER_KEY",
    "TEMPLATE_STATUS_HANDLER_KEY",
    "ClientFactory",
    "MemoryTemplateRepository",
    "NoWhatsAppNumber",
    "PostgresTemplateRepository",
    "PostgresTemplateWebhookRepository",
    "SyncReport",
    "TemplateAlreadyExists",
    "TemplateError",
    "TemplateNotFound",
    "TemplateRecord",
    "TemplateRepository",
    "TemplateService",
    "TemplateWebhookRepository",
    "WabaRef",
    "is_sendable",
    "production_template_handler",
    "rejected_reason_from",
    "template_status_handler",
]

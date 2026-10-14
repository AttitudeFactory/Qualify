"""WhatsApp opt-ins (WA-19, QUA-218): who agreed to receive a tenant's messages, and who
said STOP.

Backlog: `docs/backlog-modulo-whatsapp.md` §5 WA-19; plan §5.4. Schema: migration 0060 /
`models.WhatsAppOptIn` — one row per `(tenant_id, phone_e164)`, never deleted.

## What Meta requires (getting-opt-in, read 2026-10-14)

The opt-in must make clear that the person agrees to receive messages **from this
business** and name it; any method is acceptable if it does, within local law; opt-out
requests must be honoured. Qualify therefore stores the consent TEXT with the row
(`consent_text`, NOT NULL) plus free evidence (`proof`), and treats a revocation as
permanent until a NEWER consent arrives.

## The monotonic rule (`record`)

- no row → **created**;
- an active row → **unchanged** (the first consent stands; its evidence is not
  overwritten by a later, weaker capture);
- a revoked row and a consent captured AFTER the revocation → **reconsented** (source,
  text, proof and `captured_at` replaced, `revoked_at` cleared);
- a revoked row and a consent captured at or before the revocation → **suppressed**:
  an old lead-form consent imported after the person sent STOP must not opt them back in.

## Sources

`lead_form` (`import_from_leads`), `menu` (the menu's collect node — the worker holds the
INSERT grant for it), `import` (a file with evidence, `proof` carries its key) and
`manual`. **`import_from_leads` assumes the lead form's consent text covers WhatsApp
messages from the business** — the form's text is the tenant's to write, and whether it
satisfies Meta's wording is a product check, not something this code can verify; the
proof records which text and policy version the lead agreed to.

## STOP

`is_stop_keyword` matches a WHOLE message equal to `STOP`, `BAJA` or `CANCELAR` (case,
accents, surrounding whitespace and trailing punctuation ignored) — never a substring:
"no quiero cancelar mi pedido" is not an opt-out. The inbound handler calls the worker
door (`PostgresOptOutRepository.revoke`, column grants of 0060) and skips the menu for
that message. A STOP from a phone with no opt-in row revokes nothing (there is no consent
to withdraw); see the WA-19 notes for the suppression-row follow-up.

Logs carry ids, sources and outcomes — never a phone number or a consent text.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from qualify_shared.db.webhook import webhook_worker_session
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from qualify_api.leads.models import Lead, LeadFormSettings
from qualify_api.leads.repository import normalize_phone
from qualify_api.whatsapp.models import OPT_IN_SOURCES, WhatsAppOptIn

logger = logging.getLogger("qualify_api.whatsapp.optins")

STOP_KEYWORDS: Final = frozenset({"stop", "baja", "cancelar"})
REVOKE_REASON_STOP: Final = "stop_keyword"
REVOKE_REASON_MANUAL: Final = "manual"
SOURCE_LEAD_FORM: Final = "lead_form"
SOURCE_MENU: Final = "menu"
SOURCE_IMPORT: Final = "import"
SOURCE_MANUAL: Final = "manual"

_EDGE_PUNCTUATION = re.compile(r"^[\s\W_]+|[\s\W_]+$")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def is_stop_keyword(message: str | None) -> bool:
    """True iff the WHOLE message is an opt-out word (see the module docstring)."""
    if not message:
        return False
    return _EDGE_PUNCTUATION.sub("", _fold(message)) in STOP_KEYWORDS


def phone_from_wa_id(wa_id: str) -> str:
    """Meta's `wa_id`/`from` is digits without `+`; the opt-in key is E.164 with it.
    Raises `ValueError` for anything that is not a plausible E.164 number."""
    digits = re.sub(r"\D", "", wa_id)
    return normalize_phone(f"+{digits}")


# ======================================================================================
# Records
# ======================================================================================


class RecordOutcome(StrEnum):
    CREATED = "created"
    UNCHANGED = "unchanged"
    RECONSENTED = "reconsented"
    SUPPRESSED = "suppressed"


@dataclass(frozen=True)
class OptInRecord:
    id: UUID
    tenant_id: UUID
    phone_e164: str
    source: str
    consent_text: str
    captured_at: datetime
    brand_id: UUID | None = None
    consent_policy_version: str | None = None
    proof: dict[str, Any] | None = None
    revoked_at: datetime | None = None
    revoke_reason: str | None = None

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True)
class RecordResult:
    record: OptInRecord
    outcome: RecordOutcome


@dataclass(frozen=True)
class LeadConsent:
    """One lead's consent as the lead form stored it (0005): the phone, when and against
    which policy version, plus the form's CURRENT consent text and policy version."""

    lead_id: UUID
    phone_e164: str
    consent_at: datetime
    consent_policy_version: str
    form_consent_text: str | None
    form_policy_version: str | None


@dataclass(frozen=True)
class ImportReport:
    leads: int
    created: int
    unchanged: int
    reconsented: int
    suppressed: int
    skipped: int  # no lead-form consent text to store


@dataclass(frozen=True)
class AudienceFilter:
    """The campaign audience over live opt-ins. Every field narrows; the empty filter is
    "every active opt-in of the tenant". Serialized as `whatsapp_campaigns.audience_filter`
    (`to_json`/`from_json`)."""

    brand_id: UUID | None = None
    sources: tuple[str, ...] = ()
    captured_after: datetime | None = None
    captured_before: datetime | None = None
    phone_prefixes: tuple[str, ...] = ()  # leading parts of E.164 numbers, e.g. ("+57",)

    def __post_init__(self) -> None:
        unknown = set(self.sources) - set(OPT_IN_SOURCES)
        if unknown:
            raise ValueError(f"unknown opt-in sources {sorted(unknown)}")
        for prefix in self.phone_prefixes:
            if not re.fullmatch(r"\+[1-9]\d{0,13}", prefix):
                raise ValueError(
                    "phone_prefixes must look like '+57' (a leading part of an E.164 number)"
                )

    def matches(self, record: OptInRecord) -> bool:
        if not record.is_active:
            return False
        if self.brand_id is not None and record.brand_id != self.brand_id:
            return False
        if self.sources and record.source not in self.sources:
            return False
        if self.captured_after is not None and record.captured_at < self.captured_after:
            return False
        if self.captured_before is not None and record.captured_at >= self.captured_before:
            return False
        return not self.phone_prefixes or record.phone_e164.startswith(self.phone_prefixes)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.brand_id is not None:
            out["brand_id"] = str(self.brand_id)
        if self.sources:
            out["sources"] = list(self.sources)
        if self.captured_after is not None:
            out["captured_after"] = self.captured_after.isoformat()
        if self.captured_before is not None:
            out["captured_before"] = self.captured_before.isoformat()
        if self.phone_prefixes:
            out["phone_prefixes"] = list(self.phone_prefixes)
        return out

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> AudienceFilter:
        data = data or {}
        unknown = set(data) - {
            "brand_id",
            "sources",
            "captured_after",
            "captured_before",
            "phone_prefixes",
        }
        if unknown:
            raise ValueError(f"unknown audience filter keys {sorted(unknown)}")

        def _dt(key: str) -> datetime | None:
            value = data.get(key)
            return datetime.fromisoformat(value) if value else None

        brand = data.get("brand_id")
        return cls(
            brand_id=UUID(brand) if brand else None,
            sources=tuple(data.get("sources") or ()),
            captured_after=_dt("captured_after"),
            captured_before=_dt("captured_before"),
            phone_prefixes=tuple(data.get("phone_prefixes") or ()),
        )


def decide(existing: OptInRecord | None, incoming: OptInRecord) -> RecordResult:
    """The monotonic rule of the module docstring, pure."""
    if existing is None:
        return RecordResult(incoming, RecordOutcome.CREATED)
    if existing.is_active:
        return RecordResult(existing, RecordOutcome.UNCHANGED)
    assert existing.revoked_at is not None
    if incoming.captured_at > existing.revoked_at:
        return RecordResult(
            replace(
                existing,
                source=incoming.source,
                consent_text=incoming.consent_text,
                consent_policy_version=incoming.consent_policy_version,
                proof=incoming.proof,
                captured_at=incoming.captured_at,
                brand_id=incoming.brand_id or existing.brand_id,
                revoked_at=None,
                revoke_reason=None,
            ),
            RecordOutcome.RECONSENTED,
        )
    return RecordResult(existing, RecordOutcome.SUPPRESSED)


# ======================================================================================
# Repository seams
# ======================================================================================


class OptInRepository(Protocol):
    """The app side (`qualify_app` under `tenant_session`)."""

    def get(self, *, tenant_id: UUID, phone_e164: str) -> OptInRecord | None: ...

    def save(self, record: OptInRecord) -> OptInRecord:
        """Insert, or overwrite the row with this `id` (a reconsent)."""
        ...

    def revoke(self, *, tenant_id: UUID, phone_e164: str, at: datetime, reason: str) -> bool: ...

    def list_active(self, *, tenant_id: UUID) -> list[OptInRecord]: ...

    def lead_consents(self, *, tenant_id: UUID) -> list[LeadConsent]: ...


class OptOutRepository(Protocol):
    """The worker side: only the revocation (0060 column grants)."""

    def revoke(self, *, tenant_id: UUID, phone_e164: str, at: datetime, reason: str) -> bool: ...


def _record(row: WhatsAppOptIn) -> OptInRecord:
    return OptInRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        brand_id=row.brand_id,
        phone_e164=row.phone_e164,
        source=row.source,
        consent_text=row.consent_text,
        consent_policy_version=row.consent_policy_version,
        proof=dict(row.proof) if row.proof is not None else None,
        captured_at=row.captured_at,
        revoked_at=row.revoked_at,
        revoke_reason=row.revoke_reason,
    )


class PostgresOptInRepository:
    def get(self, *, tenant_id: UUID, phone_e164: str) -> OptInRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.scalars(
                select(WhatsAppOptIn).where(WhatsAppOptIn.phone_e164 == phone_e164)
            ).first()
            return _record(row) if row else None

    def save(self, record: OptInRecord) -> OptInRecord:
        with tenant_session(record.tenant_id) as session:
            row = session.get(WhatsAppOptIn, record.id)
            if row is None:
                row = WhatsAppOptIn(id=record.id, tenant_id=record.tenant_id)
                session.add(row)
            row.brand_id = record.brand_id
            row.phone_e164 = record.phone_e164
            row.source = record.source
            row.consent_text = record.consent_text
            row.consent_policy_version = record.consent_policy_version
            row.proof = record.proof
            row.captured_at = record.captured_at
            row.revoked_at = record.revoked_at
            row.revoke_reason = record.revoke_reason
            session.flush()
            return _record(row)

    def revoke(self, *, tenant_id: UUID, phone_e164: str, at: datetime, reason: str) -> bool:
        with tenant_session(tenant_id) as session:
            return bool(
                session.execute(_REVOKE, _revoke_params(tenant_id, phone_e164, at, reason)).all()
            )

    def list_active(self, *, tenant_id: UUID) -> list[OptInRecord]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(WhatsAppOptIn)
                .where(WhatsAppOptIn.revoked_at.is_(None))
                .order_by(WhatsAppOptIn.captured_at, WhatsAppOptIn.id)
            )
            return [_record(r) for r in rows]

    def lead_consents(self, *, tenant_id: UUID) -> list[LeadConsent]:
        with tenant_session(tenant_id) as session:
            settings = session.scalars(select(LeadFormSettings)).first()
            leads = session.execute(
                select(
                    Lead.id, Lead.whatsapp_phone, Lead.consent_at, Lead.consent_policy_version
                ).order_by(Lead.created_at, Lead.id)
            ).all()
        return [
            LeadConsent(
                lead_id=lead_id,
                phone_e164=phone,
                consent_at=consent_at,
                consent_policy_version=policy,
                form_consent_text=settings.consent_text if settings else None,
                form_policy_version=settings.consent_policy_version if settings else None,
            )
            for lead_id, phone, consent_at, policy in leads
        ]


# Reads only `tenant_id, phone_e164, revoked_at` and writes `revoked_at, revoke_reason` —
# exactly the worker's 0060 column grants, so the same statement serves both doors.
_REVOKE = text(
    """
    UPDATE whatsapp_opt_ins SET revoked_at = :at, revoke_reason = :reason
     WHERE tenant_id = :tenant_id AND phone_e164 = :phone AND revoked_at IS NULL
    RETURNING id
    """
)


def _revoke_params(tenant_id: UUID, phone: str, at: datetime, reason: str) -> dict[str, Any]:
    return {"tenant_id": tenant_id, "phone": phone, "at": at, "reason": reason}


SessionFactory = Callable[[], AbstractContextManager[Session]]


class PostgresOptOutRepository:
    """The worker door (BYPASSRLS): the tenant predicate is in the statement."""

    def __init__(self, session_factory: SessionFactory = webhook_worker_session) -> None:
        self._session = session_factory

    def revoke(self, *, tenant_id: UUID, phone_e164: str, at: datetime, reason: str) -> bool:
        with self._session() as session:
            return bool(
                session.execute(_REVOKE, _revoke_params(tenant_id, phone_e164, at, reason)).all()
            )


class MemoryOptInRepository:
    """Both seams, for offline tests."""

    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, str], OptInRecord] = {}
        self.leads: dict[UUID, list[LeadConsent]] = {}

    def get(self, *, tenant_id: UUID, phone_e164: str) -> OptInRecord | None:
        return self.rows.get((tenant_id, phone_e164))

    def save(self, record: OptInRecord) -> OptInRecord:
        self.rows[(record.tenant_id, record.phone_e164)] = record
        return record

    def revoke(self, *, tenant_id: UUID, phone_e164: str, at: datetime, reason: str) -> bool:
        row = self.rows.get((tenant_id, phone_e164))
        if row is None or not row.is_active:
            return False
        self.rows[(tenant_id, phone_e164)] = replace(row, revoked_at=at, revoke_reason=reason)
        return True

    def list_active(self, *, tenant_id: UUID) -> list[OptInRecord]:
        return sorted(
            (r for r in self.rows.values() if r.tenant_id == tenant_id and r.is_active),
            key=lambda r: (r.captured_at, str(r.id)),
        )

    def lead_consents(self, *, tenant_id: UUID) -> list[LeadConsent]:
        return list(self.leads.get(tenant_id, []))


# ======================================================================================
# Service
# ======================================================================================


class OptInService:
    def __init__(
        self, repository: OptInRepository, *, clock: Callable[[], datetime] = _utcnow
    ) -> None:
        self._repo = repository
        self._clock = clock

    def record(
        self,
        *,
        tenant_id: UUID,
        phone: str,
        source: str,
        consent_text: str,
        consent_policy_version: str | None = None,
        proof: dict[str, Any] | None = None,
        brand_id: UUID | None = None,
        captured_at: datetime | None = None,
    ) -> RecordResult:
        """Normalize `phone` to E.164 (`ValueError` otherwise) and apply the monotonic
        rule. `consent_text` must be the text the person actually agreed to."""
        if source not in OPT_IN_SOURCES:
            raise ValueError(f"source must be one of {OPT_IN_SOURCES}")
        if not consent_text or not consent_text.strip():
            raise ValueError("consent_text must not be blank")
        phone_e164 = normalize_phone(phone)
        incoming = OptInRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            brand_id=brand_id,
            phone_e164=phone_e164,
            source=source,
            consent_text=consent_text,
            consent_policy_version=consent_policy_version,
            proof=proof,
            captured_at=captured_at or self._clock(),
        )
        result = decide(self._repo.get(tenant_id=tenant_id, phone_e164=phone_e164), incoming)
        if result.outcome in (RecordOutcome.CREATED, RecordOutcome.RECONSENTED):
            result = RecordResult(self._repo.save(result.record), result.outcome)
        logger.info(
            "whatsapp.optins.record tenant_id=%s opt_in_id=%s source=%s outcome=%s",
            tenant_id,
            result.record.id,
            source,
            result.outcome,
        )
        return result

    def revoke(
        self,
        *,
        tenant_id: UUID,
        phone: str,
        reason: str = REVOKE_REASON_MANUAL,
        at: datetime | None = None,
    ) -> bool:
        """True when an active opt-in was revoked; False when there was none."""
        return self._repo.revoke(
            tenant_id=tenant_id,
            phone_e164=normalize_phone(phone),
            at=at or self._clock(),
            reason=reason,
        )

    def is_opted_in(self, *, tenant_id: UUID, phone: str) -> bool:
        try:
            phone_e164 = normalize_phone(phone)
        except ValueError:
            return False
        row = self._repo.get(tenant_id=tenant_id, phone_e164=phone_e164)
        return row is not None and row.is_active

    def get(self, *, tenant_id: UUID, phone: str) -> OptInRecord | None:
        return self._repo.get(tenant_id=tenant_id, phone_e164=normalize_phone(phone))

    def list_active(
        self, *, tenant_id: UUID, audience: AudienceFilter | None = None
    ) -> list[OptInRecord]:
        rows = self._repo.list_active(tenant_id=tenant_id)
        return rows if audience is None else [r for r in rows if audience.matches(r)]

    def import_from_leads(self, *, tenant_id: UUID) -> ImportReport:
        """Every lead with a stored consent becomes a `lead_form` opt-in captured at its
        `consent_at`, carrying the lead form's consent text and, in `proof`, the lead id,
        both policy versions and whether they agree. Idempotent (monotonic rule)."""
        consents = self._repo.lead_consents(tenant_id=tenant_id)
        counts = {outcome: 0 for outcome in RecordOutcome}
        skipped = 0
        for lead in consents:
            if not lead.form_consent_text:
                skipped += 1
                continue
            try:
                result = self.record(
                    tenant_id=tenant_id,
                    phone=lead.phone_e164,
                    source=SOURCE_LEAD_FORM,
                    consent_text=lead.form_consent_text,
                    consent_policy_version=lead.consent_policy_version,
                    captured_at=lead.consent_at,
                    proof={
                        "lead_id": str(lead.lead_id),
                        "consent_at": lead.consent_at.isoformat(),
                        "lead_policy_version": lead.consent_policy_version,
                        "form_policy_version": lead.form_policy_version,
                        "text_matches_lead_policy": (
                            lead.form_policy_version == lead.consent_policy_version
                        ),
                    },
                )
            except ValueError:
                skipped += 1
                continue
            counts[result.outcome] += 1
        report = ImportReport(
            leads=len(consents),
            created=counts[RecordOutcome.CREATED],
            unchanged=counts[RecordOutcome.UNCHANGED],
            reconsented=counts[RecordOutcome.RECONSENTED],
            suppressed=counts[RecordOutcome.SUPPRESSED],
            skipped=skipped,
        )
        logger.info("whatsapp.optins.import_from_leads tenant_id=%s report=%s", tenant_id, report)
        return report


def active_phones(records: Iterable[OptInRecord]) -> list[str]:
    return [r.phone_e164 for r in records if r.is_active]


__all__ = [
    "REVOKE_REASON_MANUAL",
    "REVOKE_REASON_STOP",
    "STOP_KEYWORDS",
    "AudienceFilter",
    "ImportReport",
    "LeadConsent",
    "MemoryOptInRepository",
    "OptInRecord",
    "OptInRepository",
    "OptInService",
    "OptOutRepository",
    "PostgresOptInRepository",
    "PostgresOptOutRepository",
    "RecordOutcome",
    "RecordResult",
    "active_phones",
    "decide",
    "is_stop_keyword",
    "phone_from_wa_id",
]

"""The email of a failed avatar (m-25120319, epic m-25026566): «Uno de tus avatares no
se pudo crear. Entra para intentarlo de nuevo o quitarlo.»

**When.** The worker's first pass that sees an avatar block of a Clip failed stamps its
`failed_at` on the Clip's plan (`clip_avatar.plan_gate` → `PlanRefused("failure_seen")`),
in a new brief written under the run's fence (`ContentService._replace_clip_brief`). In
THAT same transaction `stage` writes one row per failed avatar in
`clip_avatar_failure_mails` (migration 0186): the stamp and the email commit together or
not at all.

**Once per failure.** A failure's identity is `(clip_id, slot, failed_at)` — `UNIQUE`,
staged with `ON CONFLICT DO NOTHING` — and its Resend `Idempotency-Key` is derived from
it. Re-reading the state, a second pass or a restarted worker never stages a second row
(the stamp is already on the plan; and if it were written again, the same identity
conflicts). The sender freezes the mail before its first attempt and resends it verbatim
with the same key; after `RETRY_WINDOW` of uncertain attempts it closes the row instead
of risking a double (Resend keeps keys 24 h).

**A retry that fails again** is a new failure: «Intentar de nuevo» clears the slot's
`failed_at`; when the new attempt fails, the next pass stamps a new `failed_at` — a new
identity, one more email, once. A row not sent yet when the owner retried or removed the
avatar (or the Clip moved on: made, failed at 72 h) is closed `resolved`, never sent: the
sender re-reads the Clip and the recipient before every attempt, a frozen retry included.

**Switches.** Nothing is staged for a kind whose switch (`QUALIFY_CLIP_AVATAR_PRESENTER`
/ `QUALIFY_CLIP_AVATAR_ANIMATED`) is off, nor for a `switched_off` «failure»; the sender
checks the switch again before the first attempt (`closed_reason='switched_off'`). With
both off no block can exist, so nothing is ever staged.

**Who.** The Clip's author (`content_briefs.created_by`), while still a member of the
business with a real seat and a confirmed address (`auth.confirmed_email`, fail closed).

**Privacy.** Logs carry ids and codes only — never an address, a name or a script
(`test_clip_avatar_mail.py` checks every record of a full run).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_creative.schemas import ClipAvatarSlot

from qualify_api.creative.clip_avatar import (
    BlockRow,
    PlannedBlock,
    any_block_enabled,
    block_enabled,
    owner_deadline,
    plan_states,
)
from qualify_api.mail import Mailer, MailNotConfigured, MailRejected, OutgoingMail
from qualify_api.mail.clip_avatar import TEMPLATE_VERSION, failure_mail

logger = logging.getLogger(__name__)

#: Resend keeps an idempotency key 24 h: stop retrying an uncertain send before then.
RETRY_WINDOW = timedelta(hours=23)
#: How long a claimed row is held by one sender (the send itself times out at 15 s).
LEASE = timedelta(minutes=2)
#: Why a row was closed without being sent (migration 0186's CHECK).
CLOSE_REASONS = frozenset({"resolved", "switched_off", "no_recipient", "rejected", "uncertain"})

Verifier = Callable[[UUID, str], str | None]


@dataclass(frozen=True)
class AvatarFailure:
    """One failed avatar, stamped on this pass: what one email is staged for."""

    block_id: UUID
    slot: int
    kind: str
    code: str
    failed_at: datetime


def mailable_failures(
    seen: Sequence[PlannedBlock], env: Mapping[str, str] | None = None
) -> tuple[AvatarFailure, ...]:
    """The failures stamped on this pass that get an email: a real block that failed,
    whose kind is switched on — never `switched_off` (nothing failed: the server stopped
    it) nor an entry without a block (no «Intentar de nuevo» to offer). Pure."""
    found: list[AvatarFailure] = []
    for planned in seen:
        row = planned.row
        if row is None or planned.entry.failed_at is None or planned.code == "switched_off":
            continue
        if not block_enabled(row.kind, env):
            continue
        found.append(
            AvatarFailure(
                block_id=row.id,
                slot=planned.entry.slot,
                kind=row.kind,
                code=planned.code or "failed",
                failed_at=planned.entry.failed_at,
            )
        )
    return tuple(found)


def failure_key(tenant_id: UUID, clip_id: UUID, slot: int, failed_at: datetime) -> str:
    """Resend's `Idempotency-Key` for one failure: derived from its identity, no PII."""
    stamp = failed_at.astimezone(UTC).isoformat()
    digest = hashlib.sha256(f"{tenant_id}|{clip_id}|{slot}|{stamp}".encode()).hexdigest()
    return f"clip-avatar-failed/{digest}"


@dataclass(frozen=True)
class PendingMail:
    """A staged row as the sender claimed it (its lease taken)."""

    id: UUID
    tenant_id: UUID
    clip_id: UUID
    block_id: UUID
    slot: int
    failed_at: datetime
    user_id: UUID
    idempotency_key: str
    lease: UUID
    payload: Mapping[str, Any] | None = None
    first_attempt_at: datetime | None = None


@dataclass(frozen=True)
class ClipView:
    """The Clip as the sender re-reads it before the first attempt."""

    status: str
    business: str
    timezone: str
    plan: tuple[ClipAvatarSlot, ...]
    blocks: tuple[BlockRow, ...]


@dataclass(frozen=True)
class Recipient:
    email: str
    auth_user_id: UUID


class AvatarFailureOutbox(Protocol):
    """Where failure emails wait. `stage` runs INSIDE the Clip's fenced write (`session`
    is that transaction; None for the in-memory double); every other call is its own
    transaction, fenced by the claim's `lease`."""

    def stage(
        self,
        session: Any,
        *,
        tenant_id: UUID,
        clip_id: UUID,
        user_id: UUID,
        failures: Sequence[AvatarFailure],
    ) -> int: ...

    def pending_tenants(self) -> list[UUID]: ...

    def claim(self, tenant_id: UUID, *, now: datetime, include_new: bool) -> PendingMail | None: ...

    def clip_view(self, tenant_id: UUID, clip_id: UUID) -> ClipView | None: ...

    def recipient(self, tenant_id: UUID, user_id: UUID) -> Recipient | None: ...

    def freeze(self, mail: PendingMail, payload: Mapping[str, Any], *, now: datetime) -> bool: ...

    def close(self, mail: PendingMail, reason: str, *, now: datetime) -> None: ...

    def mark_sent(self, mail: PendingMail, provider_id: str | None, *, now: datetime) -> bool: ...


# -- the sender ------------------------------------------------------------------------------


def _due(
    mail: PendingMail, clip: ClipView | None, env: Mapping[str, str] | None
) -> tuple[str | None, datetime | None]:
    """Whether a never-attempted row is still worth sending: (close reason, None), or
    (None, when the Clip stops waiting). Pure."""
    if clip is None or clip.status != "drafting":
        return "resolved", None
    entry = next((e for e in clip.plan if e.slot == mail.slot), None)
    if entry is None or entry.failed_at is None or entry.failed_at != mail.failed_at:
        return "resolved", None
    states = plan_states(clip.plan, clip.blocks, env)
    planned = next((s for s in states if s.entry.slot == mail.slot), None)
    if planned is None or planned.state != "failed" or planned.row is None:
        return "resolved", None
    if planned.row.id != mail.block_id:
        return "resolved", None
    if planned.code == "switched_off" or not block_enabled(planned.row.kind, env):
        return "switched_off", None
    return None, owner_deadline(states)


def send_pending(
    outbox: AvatarFailureOutbox,
    tenant_id: UUID,
    *,
    mailer: Mailer,
    base_url: str | None,
    verify: Verifier,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """Send this business's staged failure emails; how many were sent. The time is read
    again before each claim (`clock`, or the fixed `now`). Without a `base_url` (mail
    links not configured) only already-frozen emails go out. Every attempt — the first
    and each retry of a frozen mail — checks first that the avatar still waits for the
    owner (`_due`) and that the recipient is still a confirmed member; otherwise the row
    is closed unsent."""
    if clock is None:
        if now is None:
            raise ValueError("send_pending needs `now` or `clock`")
        fixed = now

        def clock() -> datetime:
            return fixed

    sent = 0
    while True:
        moment = clock()
        mail = outbox.claim(tenant_id, now=moment, include_new=base_url is not None)
        if mail is None:
            return sent
        frozen = mail.first_attempt_at is not None
        if frozen and moment - mail.first_attempt_at >= RETRY_WINDOW:  # type: ignore[operator]
            _close(outbox, mail, "uncertain", moment, error=True)
            continue
        clip = outbox.clip_view(tenant_id, mail.clip_id)
        reason, wait_until = _due(mail, clip, env)
        if reason is not None:
            _close(outbox, mail, reason, moment)
            continue
        confirmed = _confirmed(outbox, mail, verify)
        if confirmed is _DEFER:
            continue  # the lease lapses and a later pass tries again
        if frozen:
            assert mail.payload is not None
            outgoing = OutgoingMail(**mail.payload["mail"])
            if not confirmed or outgoing.to.casefold() != str(confirmed).casefold():
                _close(outbox, mail, "no_recipient", moment)
                continue
        else:
            if not confirmed:
                _close(outbox, mail, "no_recipient", moment)
                continue
            assert base_url is not None and clip is not None and wait_until is not None
            outgoing = failure_mail(
                to=str(confirmed),
                business=clip.business,
                clip_id=mail.clip_id,
                wait_until=wait_until,
                timezone=clip.timezone,
                base_url=base_url,
                idempotency_key=mail.idempotency_key,
            )
            if not outbox.freeze(mail, {"mail": asdict(outgoing)}, now=moment):
                continue
        try:
            provider_id = mailer.send(outgoing)
        except MailRejected:
            _close(outbox, mail, "rejected", moment, error=True)
            continue
        except Exception as exc:
            # keep the frozen mail and its key: the next pass resends it verbatim
            logger.warning(
                "clip_avatar.failure_mail send deferred tenant=%s mail=%s error_type=%s",
                tenant_id,
                mail.id,
                type(exc).__name__,
            )
            return sent
        if outbox.mark_sent(mail, provider_id, now=clock()):
            sent += 1
            logger.info(
                "clip_avatar.failure_mail sent tenant=%s mail=%s clip=%s",
                mail.tenant_id,
                mail.id,
                mail.clip_id,
            )


#: `_confirmed` could not tell (the identity provider failed): try again later.
_DEFER = object()


def _confirmed(outbox: AvatarFailureOutbox, mail: PendingMail, verify: Verifier) -> object:
    """The recipient's confirmed address, None when there is none, `_DEFER` on a
    transient failure of the check (logged with ids and the error type only)."""
    recipient = outbox.recipient(mail.tenant_id, mail.user_id)
    if recipient is None:
        return None
    try:
        return verify(recipient.auth_user_id, recipient.email)
    except Exception as exc:
        logger.warning(
            "clip_avatar.failure_mail recipient unverified tenant=%s mail=%s error_type=%s",
            mail.tenant_id,
            mail.id,
            type(exc).__name__,
        )
        return _DEFER


def _close(
    outbox: AvatarFailureOutbox,
    mail: PendingMail,
    reason: str,
    now: datetime,
    *,
    error: bool = False,
) -> None:
    outbox.close(mail, reason, now=now)
    (logger.error if error else logger.info)(
        "clip_avatar.failure_mail closed tenant=%s mail=%s reason=%s",
        mail.tenant_id,
        mail.id,
        reason,
    )


def failure_mail_chore(
    tenant_ids: Sequence[UUID] | None,
    *,
    outbox: AvatarFailureOutbox | None = None,
    mailer: Callable[[], Mailer] | None = None,
    verify: Verifier | None = None,
    clock: Callable[[], datetime] | None = None,
) -> Callable[[], int]:
    """The creative worker's pass over every business with a staged email (or only the
    ones of `--tenant`). Never raises: a business that fails is logged and skipped."""

    def run() -> int:
        from qualify_api.mail import default_mailer  # noqa: PLC0415
        from qualify_api.mail.config import public_app_url  # noqa: PLC0415

        if not any_block_enabled():
            # both switches off (every environment today): no email, not even a read
            return 0
        box = outbox or PostgresAvatarFailureOutbox()
        tick = clock or (lambda: datetime.now(UTC))
        # Never log the traceback nor the exception text here: a database error carries
        # its SQL parameters (the frozen mail: address, business, body). Ids and the type.
        try:
            ids = list(tenant_ids) if tenant_ids is not None else box.pending_tenants()
        except Exception as exc:
            logger.error(
                "clip_avatar.failure_mail discovery failed error_type=%s", type(exc).__name__
            )
            return 0
        if not ids:
            return 0
        base_url: str | None
        try:
            base_url = public_app_url()
        except MailNotConfigured as exc:
            logger.warning(
                "clip_avatar.failure_mail new mails not built error_type=%s", type(exc).__name__
            )
            base_url = None
        if verify is None:
            from qualify_api.auth.confirmed_email import confirmed_email  # noqa: PLC0415

            check: Verifier = confirmed_email
        else:
            check = verify
        count = 0
        for tenant_id in ids:
            try:
                count += send_pending(
                    box,
                    tenant_id,
                    clock=tick,
                    mailer=(mailer or default_mailer)(),
                    base_url=base_url,
                    verify=check,
                )
            except Exception as exc:
                logger.error(
                    "clip_avatar.failure_mail pass failed tenant=%s error_type=%s",
                    tenant_id,
                    type(exc).__name__,
                )
        return count

    return run


# -- Postgres ----------------------------------------------------------------------------------


_COLUMNS = (
    "id, tenant_id, clip_id, block_id, slot, failed_at, user_id, idempotency_key, "
    "payload, first_attempt_at"
)


class PostgresAvatarFailureOutbox:
    """`clip_avatar_failure_mails` (migration 0186): every read and write through
    `tenant_session` (RLS); tenant discovery (ids only) through `admin_session`."""

    def stage(
        self,
        session: Any,
        *,
        tenant_id: UUID,
        clip_id: UUID,
        user_id: UUID,
        failures: Sequence[AvatarFailure],
    ) -> int:
        from sqlalchemy import text  # noqa: PLC0415

        if session is None:
            raise RuntimeError("a failure email is staged inside the Clip's own write")
        staged = 0
        for failure in failures:
            staged += session.execute(
                text("""
                INSERT INTO clip_avatar_failure_mails
                    (tenant_id, clip_id, block_id, slot, failed_at, failure_code, user_id,
                     idempotency_key, source_version)
                VALUES (:tenant, :clip, :block, :slot, :failed_at, :code, :user, :key,
                        :version)
                ON CONFLICT DO NOTHING
            """),
                {
                    "tenant": tenant_id,
                    "clip": clip_id,
                    "block": failure.block_id,
                    "slot": failure.slot,
                    "failed_at": failure.failed_at,
                    "code": failure.code,
                    "user": user_id,
                    "key": failure_key(tenant_id, clip_id, failure.slot, failure.failed_at),
                    "version": TEMPLATE_VERSION,
                },
            ).rowcount
        return staged

    def pending_tenants(self) -> list[UUID]:
        from qualify_shared.db.admin import admin_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with admin_session() as session:
            return list(
                session.scalars(
                    text("""
                    SELECT DISTINCT tenant_id FROM clip_avatar_failure_mails
                    WHERE sent_at IS NULL AND closed_at IS NULL
                """)
                )
            )

    def claim(self, tenant_id: UUID, *, now: datetime, include_new: bool) -> PendingMail | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        lease = uuid4()
        with tenant_session(tenant_id) as session:
            row = (
                session.execute(
                    text(f"""
                SELECT {_COLUMNS} FROM clip_avatar_failure_mails
                WHERE sent_at IS NULL AND closed_at IS NULL
                  AND (lease_until IS NULL OR lease_until <= :now)
                  AND (:include_new OR first_attempt_at IS NOT NULL)
                ORDER BY created_at, id
                FOR UPDATE SKIP LOCKED LIMIT 1
            """),
                    {"now": now, "include_new": include_new},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            session.execute(
                text("""
                UPDATE clip_avatar_failure_mails SET lease_token = :lease, lease_until = :until
                WHERE id = :id
            """),
                {"lease": lease, "until": now + LEASE, "id": row["id"]},
            )
        return PendingMail(
            id=row["id"],
            tenant_id=row["tenant_id"],
            clip_id=row["clip_id"],
            block_id=row["block_id"],
            slot=int(row["slot"]),
            failed_at=row["failed_at"],
            user_id=row["user_id"],
            idempotency_key=row["idempotency_key"],
            lease=lease,
            payload=row["payload"],
            first_attempt_at=row["first_attempt_at"],
        )

    def clip_view(self, tenant_id: UUID, clip_id: UUID) -> ClipView | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        from qualify_api.creative.clip_avatar import PostgresClipAvatarStore  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.execute(
                text("""
                SELECT d.status, b.media->'clip_avatar_plan' AS plan,
                       COALESCE(NULLIF(br.name, ''), t.name) AS business,
                       COALESCE(NULLIF(t.timezone, ''), 'UTC') AS timezone
                FROM content_drafts d
                JOIN content_briefs b ON b.id = d.brief_id
                JOIN tenants t ON t.id = d.tenant_id
                LEFT JOIN brands br ON br.id = d.brand_id
                WHERE d.id = :clip
            """),
                {"clip": clip_id},
            ).first()
        if row is None:
            return None
        plan = tuple(ClipAvatarSlot.model_validate(entry) for entry in (row.plan or ()))
        blocks = PostgresClipAvatarStore().blocks_of(tenant_id=tenant_id, clip_id=clip_id)
        return ClipView(
            status=str(row.status),
            business=str(row.business),
            timezone=str(row.timezone),
            plan=plan,
            blocks=blocks,
        )

    def recipient(self, tenant_id: UUID, user_id: UUID) -> Recipient | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.execute(
                text("""
                SELECT u.email, u.auth_user_id FROM users u
                JOIN tenant_members m ON m.user_id = u.id AND m.tenant_id = u.tenant_id
                WHERE u.id = :user AND u.auth_user_id IS NOT NULL
            """),
                {"user": user_id},
            ).first()
        if row is None:
            return None
        return Recipient(email=str(row.email), auth_user_id=row.auth_user_id)

    def freeze(self, mail: PendingMail, payload: Mapping[str, Any], *, now: datetime) -> bool:
        import json  # noqa: PLC0415

        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(mail.tenant_id) as session:
            return bool(
                session.execute(
                    text("""
                    UPDATE clip_avatar_failure_mails
                    SET payload = CAST(:payload AS jsonb), first_attempt_at = :now
                    WHERE id = :id AND lease_token = :lease AND first_attempt_at IS NULL
                """),
                    {
                        "payload": json.dumps(payload),
                        "now": now,
                        "id": mail.id,
                        "lease": mail.lease,
                    },
                ).rowcount
            )

    def close(self, mail: PendingMail, reason: str, *, now: datetime) -> None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        if reason not in CLOSE_REASONS:
            raise ValueError(reason)
        with tenant_session(mail.tenant_id) as session:
            session.execute(
                text("""
                UPDATE clip_avatar_failure_mails
                SET closed_at = :now, closed_reason = :reason,
                    lease_token = NULL, lease_until = NULL
                WHERE id = :id AND lease_token = :lease AND sent_at IS NULL
            """),
                {"now": now, "reason": reason, "id": mail.id, "lease": mail.lease},
            )

    def mark_sent(self, mail: PendingMail, provider_id: str | None, *, now: datetime) -> bool:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(mail.tenant_id) as session:
            return bool(
                session.execute(
                    text("""
                    UPDATE clip_avatar_failure_mails
                    SET sent_at = :now, provider_id = :provider,
                        lease_token = NULL, lease_until = NULL
                    WHERE id = :id AND lease_token = :lease AND sent_at IS NULL
                """),
                    {"now": now, "provider": provider_id, "id": mail.id, "lease": mail.lease},
                ).rowcount
            )


# -- in memory (tests, and the in-memory ContentService) --------------------------------------


@dataclass
class _MemoryRow:
    id: UUID
    tenant_id: UUID
    clip_id: UUID
    block_id: UUID
    slot: int
    failed_at: datetime
    code: str
    user_id: UUID
    key: str
    created_at: int
    payload: dict[str, Any] | None = None
    lease: UUID | None = None
    lease_until: datetime | None = None
    first_attempt_at: datetime | None = None
    sent_at: datetime | None = None
    provider_id: str | None = None
    closed_reason: str | None = None


@dataclass
class MemoryAvatarFailureOutbox:
    """The same rules as Postgres, in memory: `(clip, slot, failed_at)` and the key are
    unique, claims take a lease. `clips` / `recipients` are what the test says the
    database holds."""

    clips: dict[tuple[UUID, UUID], ClipView] = field(default_factory=dict)
    recipients: dict[tuple[UUID, UUID], Recipient] = field(default_factory=dict)
    rows: list[_MemoryRow] = field(default_factory=list)

    def stage(
        self,
        session: Any,
        *,
        tenant_id: UUID,
        clip_id: UUID,
        user_id: UUID,
        failures: Sequence[AvatarFailure],
    ) -> int:
        staged = 0
        for failure in failures:
            key = failure_key(tenant_id, clip_id, failure.slot, failure.failed_at)
            if any(
                (r.clip_id, r.slot, r.failed_at) == (clip_id, failure.slot, failure.failed_at)
                or r.key == key
                for r in self.rows
            ):
                continue
            self.rows.append(
                _MemoryRow(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    clip_id=clip_id,
                    block_id=failure.block_id,
                    slot=failure.slot,
                    failed_at=failure.failed_at,
                    code=failure.code,
                    user_id=user_id,
                    key=key,
                    created_at=len(self.rows),
                )
            )
            staged += 1
        return staged

    def pending_tenants(self) -> list[UUID]:
        return list(
            dict.fromkeys(
                r.tenant_id for r in self.rows if r.sent_at is None and r.closed_reason is None
            )
        )

    def claim(self, tenant_id: UUID, *, now: datetime, include_new: bool) -> PendingMail | None:
        for row in sorted(self.rows, key=lambda r: r.created_at):
            if (
                row.tenant_id != tenant_id
                or row.sent_at is not None
                or row.closed_reason is not None
                or (row.lease_until is not None and row.lease_until > now)
                or (not include_new and row.first_attempt_at is None)
            ):
                continue
            row.lease, row.lease_until = uuid4(), now + LEASE
            return PendingMail(
                id=row.id,
                tenant_id=row.tenant_id,
                clip_id=row.clip_id,
                block_id=row.block_id,
                slot=row.slot,
                failed_at=row.failed_at,
                user_id=row.user_id,
                idempotency_key=row.key,
                lease=row.lease,
                payload=row.payload,
                first_attempt_at=row.first_attempt_at,
            )
        return None

    def clip_view(self, tenant_id: UUID, clip_id: UUID) -> ClipView | None:
        return self.clips.get((tenant_id, clip_id))

    def recipient(self, tenant_id: UUID, user_id: UUID) -> Recipient | None:
        return self.recipients.get((tenant_id, user_id))

    def _row(self, mail: PendingMail) -> _MemoryRow | None:
        row = next((r for r in self.rows if r.id == mail.id), None)
        return row if row is not None and row.lease == mail.lease else None

    def freeze(self, mail: PendingMail, payload: Mapping[str, Any], *, now: datetime) -> bool:
        row = self._row(mail)
        if row is None or row.first_attempt_at is not None:
            return False
        row.payload, row.first_attempt_at = dict(payload), now
        return True

    def close(self, mail: PendingMail, reason: str, *, now: datetime) -> None:
        if reason not in CLOSE_REASONS:
            raise ValueError(reason)
        row = self._row(mail)
        if row is not None and row.sent_at is None:
            row.closed_reason, row.lease, row.lease_until = reason, None, None

    def mark_sent(self, mail: PendingMail, provider_id: str | None, *, now: datetime) -> bool:
        row = self._row(mail)
        if row is None or row.sent_at is not None:
            return False
        row.sent_at, row.provider_id, row.lease, row.lease_until = now, provider_id, None, None
        return True


__all__ = [
    "AvatarFailure",
    "AvatarFailureOutbox",
    "ClipView",
    "MemoryAvatarFailureOutbox",
    "PendingMail",
    "PostgresAvatarFailureOutbox",
    "Recipient",
    "failure_key",
    "failure_mail_chore",
    "mailable_failures",
    "send_pending",
]

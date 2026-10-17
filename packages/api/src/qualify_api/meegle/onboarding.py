"""What Qualify does to an "Alta de cliente" item (plan `docs/plan-altas-meegle.md` §2-§3).

Three use-cases, all synchronous, all writing back to the same item:

- `start_invitation(work_item_id)` — the person completed **Datos**. Read the item through
  the Open API (never trust the event's payload for data), create the invite
  (`invites.create_invite`, linked to the item by `meegle_work_item_id`), email it through
  Resend, then write `Estado Qualify = invitada`, the link, `Vence`, `Qualify ref` and a
  comment. If the email is invalid or the mail fails: `Estado Qualify = error`, a comment
  with the reason (and the link when the invite does exist, so it can be sent by hand),
  and **Datos** is rolled back so it can be corrected and completed again (plan D3). A
  failure of this kind is a settled outcome, not a retry — the person fixes the item.
- `expire_for_terminated(work_item_id)` — the item was terminated (1005): every unused
  invite of that item expires now (`Estado Qualify = vencida`, best-effort).
- `mark_registered(work_item_id, tenant_id)` — `register_business` consumed the invite:
  complete **Registrada**, write `Estado Qualify = registrada`, `Tenant`, `Registrada el`.
  Called best-effort from the signup path, after its transaction, never failing a signup.
- `mark_delivered` / `mark_opened` / `mark_bounced` (M2) — the Resend webhook said the
  invitation reached the inbox (`entregada` + **Invitada** completed), was opened
  (`abierta`) or bounced (`rebotó` + a comment with the provider's reason). Called
  best-effort from `qualify_api.mail.handlers`, after the invite row is updated.

Field reads tolerate what Meegle returns for each type: a `text` is a string, a
`multi_text` arrives as `{"doc_text": …}` (or that object as a JSON string), a `select` as
its option value. Writes go through `SchemaResolver` so labels become keys and values.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from qualify_api.auth.invite_email import date_es
from qualify_api.auth.invites import (
    CreatedInvite,
    SignupNotAllowed,
    create_invite,
    expire_invites_for_work_item,
    send_invite_email,
    signup_base_url,
)
from qualify_api.mail import Mailer, MailError, MailNotConfigured, default_mailer, mail_reply_to
from qualify_api.meegle.client import MeegleApiError, MeegleClient, WorkItem
from qualify_api.meegle.schema import SchemaResolver
from qualify_api.meegle.settings import (
    STATUS_BOUNCED,
    STATUS_DELIVERED,
    STATUS_ERROR,
    STATUS_EXPIRED,
    STATUS_INVITED,
    STATUS_OPENED,
    STATUS_REGISTERED,
    MeegleNames,
)

logger = logging.getLogger("qualify_api.meegle.onboarding")

INVITED_BY_PREFIX = "meegle:"


class WorkItemNotFound(LookupError):
    """The Open API returned no item for that id (deleted, or of another type)."""


@dataclass(frozen=True)
class InvitationResult:
    ok: bool
    reason: str = ""  # short, log-safe code when not ok
    invite_id: UUID | None = None


def text_value(value: Any) -> str:
    """The plain text of a field value, whatever shape Meegle used for it."""
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("doc_text", "text", "value", "label"):
            inner = value.get(key)
            if isinstance(inner, str):
                return inner.strip()
        return ""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
            except ValueError:
                return stripped
            if isinstance(parsed, dict):
                return text_value(parsed)
        return stripped
    if isinstance(value, list):
        return " ".join(part for part in (text_value(v) for v in value) if part)
    return str(value)


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


class OnboardingEngine:
    def __init__(
        self,
        client: MeegleClient,
        resolver: SchemaResolver,
        *,
        names: MeegleNames | None = None,
        mailer: Callable[[], Mailer] = default_mailer,
        base_url: str | None = None,
        signer: str = "",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client = client
        self._resolver = resolver
        self._names = names or resolver.names
        self._mailer = mailer
        self._base_url = base_url
        self._signer = signer
        self._clock = clock

    # -- helpers ---------------------------------------------------------------------

    def _read_item(self, work_item_id: int) -> WorkItem:
        items = self._client.query([work_item_id])
        for item in items:
            if item.id == work_item_id:
                return item
        raise WorkItemNotFound(str(work_item_id))

    def _field_text(self, item: WorkItem, name: str) -> str:
        return text_value(item.fields.get(self._resolver.field_key(name)))

    def _status_pair(self, label: str) -> tuple[str, str]:
        names = self._names
        return self._resolver.field_key(names.status), self._resolver.select_value(
            names.status, label
        )

    def _link(self, invite: CreatedInvite) -> str:
        return invite.link(self._base_url or signup_base_url())

    def node_name(self, work_item_id: int, node_key: str) -> str | None:
        return self._resolver.node_name(work_item_id, node_key)

    # -- use-cases -------------------------------------------------------------------

    def start_invitation(self, work_item_id: int) -> InvitationResult:
        item = self._read_item(work_item_id)
        names = self._names
        email = self._field_text(item, names.email)
        person = self._field_text(item, names.person_name)
        note = self._field_text(item, names.note)
        business = item.name.strip()

        invite: CreatedInvite | None = None
        try:
            invite = create_invite(
                email,
                invited_by=f"{INVITED_BY_PREFIX}{work_item_id}",
                recipient_name=person,
                business_name=business,
                note=note,
                meegle_work_item_id=work_item_id,
            )
            send_invite_email(
                self._mailer(),
                invite,
                self._base_url or signup_base_url(),
                signer=self._signer,
                can_reply=bool(mail_reply_to()),
            )
        except SignupNotAllowed as exc:
            return self._fail(work_item_id, "invalid_input", exc.message, invite)
        except MailNotConfigured as exc:
            return self._fail(work_item_id, "mail_not_configured", str(exc), invite)
        except MailError as exc:
            return self._fail(work_item_id, "mail_failed", str(exc), invite)

        status_key, status_value = self._status_pair(STATUS_INVITED)
        self._client.update_fields(
            work_item_id,
            {
                status_key: status_value,
                self._resolver.field_key(names.invite_link): self._link(invite),
                self._resolver.field_key(names.expires): _ms(invite.expires_at),
                self._resolver.field_key(names.qualify_ref): str(invite.id),
            },
        )
        self._client.comment(
            work_item_id,
            f"Invitación enviada a {invite.email}. Vence el {date_es(invite.expires_at)}.",
        )
        logger.info("meegle onboarding: work_item=%s invite=%s sent", work_item_id, invite.id)
        return InvitationResult(ok=True, invite_id=invite.id)

    def _fail(
        self, work_item_id: int, reason: str, detail: str, invite: CreatedInvite | None
    ) -> InvitationResult:
        names = self._names
        status_key, status_value = self._status_pair(STATUS_ERROR)
        pairs: dict[str, Any] = {status_key: status_value}
        lines = [f"No se pudo enviar la invitación: {detail}"]
        if invite is not None:
            pairs[self._resolver.field_key(names.invite_link)] = self._link(invite)
            pairs[self._resolver.field_key(names.qualify_ref)] = str(invite.id)
            lines.append(
                f"La invitación sí quedó creada (vence el {date_es(invite.expires_at)}); "
                f"el enlace está en «{names.invite_link}» por si quieres mandarlo a mano."
            )
        lines.append(f"Corrige los datos y vuelve a completar «{names.node_data}».")
        self._client.update_fields(work_item_id, pairs)
        self._client.comment(work_item_id, "\n".join(lines))
        self._rollback_data_node(work_item_id, detail)
        logger.warning(
            "meegle onboarding: work_item=%s invitation failed (%s)", work_item_id, reason
        )
        return InvitationResult(ok=False, reason=reason, invite_id=invite.id if invite else None)

    def _rollback_data_node(self, work_item_id: int, reason: str) -> None:
        try:
            node_id = self._resolver.node_id(work_item_id, self._names.node_data)
            self._client.operate_node(
                work_item_id, node_id, action="rollback", rollback_reason=reason[:200]
            )
        except MeegleApiError as exc:
            # Already rolled back by hand, or the flow forbids it: the comment and the
            # status already say what happened; nothing to retry.
            logger.warning(
                "meegle onboarding: work_item=%s rollback of %r refused (%s)",
                work_item_id,
                self._names.node_data,
                type(exc).__name__,
            )

    def expire_for_terminated(self, work_item_id: int) -> int:
        expired = expire_invites_for_work_item(work_item_id)
        if expired:
            try:
                status_key, status_value = self._status_pair(STATUS_EXPIRED)
                self._client.update_fields(work_item_id, {status_key: status_value})
            except Exception as exc:  # noqa: BLE001 — a terminated item may refuse writes
                logger.warning(
                    "meegle onboarding: work_item=%s terminated, status not written (%s)",
                    work_item_id,
                    type(exc).__name__,
                )
        logger.info(
            "meegle onboarding: work_item=%s terminated, invites expired=%d",
            work_item_id,
            expired,
        )
        return expired

    # -- delivery (M2: fed by the Resend webhook, `qualify_api.mail.handlers`) -----------

    def _set_status(self, work_item_id: int, label: str) -> None:
        status_key, status_value = self._status_pair(label)
        self._client.update_fields(work_item_id, {status_key: status_value})

    def _confirm_node(self, work_item_id: int, name: str) -> None:
        """Complete a node by name. Meegle refuses a node that is already completed (a
        repeated event, or a person did it): the refusal is logged and is not an error."""
        try:
            node_id = self._resolver.node_id(work_item_id, name)
            self._client.operate_node(work_item_id, node_id, action="confirm")
        except MeegleApiError as exc:
            logger.info(
                "meegle onboarding: work_item=%s node %r not confirmed (%s)",
                work_item_id,
                name,
                type(exc).__name__,
            )

    def mark_delivered(self, work_item_id: int, *, already_opened: bool = False) -> None:
        """The invitation reached the inbox: `Estado Qualify = entregada` and **Invitada**
        completed. `already_opened` (the open event arrived first) keeps the status at
        `abierta` — a later state never goes backwards — but still completes the node."""
        if not already_opened:
            self._set_status(work_item_id, STATUS_DELIVERED)
        self._confirm_node(work_item_id, self._names.node_invited)
        logger.info("meegle onboarding: work_item=%s invitation delivered", work_item_id)

    def mark_opened(self, work_item_id: int) -> None:
        """The person opened the invitation: `Estado Qualify = abierta`, nodes untouched."""
        self._set_status(work_item_id, STATUS_OPENED)
        logger.info("meegle onboarding: work_item=%s invitation opened", work_item_id)

    def mark_bounced(self, work_item_id: int, reason: str) -> None:
        """The invitation bounced: `Estado Qualify = rebotó` and a comment with Resend's
        reason, so the person corrects the email and completes **Datos** again (D3)."""
        self._set_status(work_item_id, STATUS_BOUNCED)
        detail = " ".join(reason.split())[:500] or "sin detalle del proveedor"
        self._client.comment(
            work_item_id,
            f"El correo de invitación rebotó: {detail}\n"
            f"Corrige «{self._names.email}» y vuelve a completar «{self._names.node_data}».",
        )
        logger.warning("meegle onboarding: work_item=%s invitation bounced", work_item_id)

    def mark_registered(self, work_item_id: int, tenant_id: UUID) -> None:
        names = self._names
        now = self._clock()
        status_key, status_value = self._status_pair(STATUS_REGISTERED)
        self._client.update_fields(
            work_item_id,
            {
                status_key: status_value,
                self._resolver.field_key(names.tenant): str(tenant_id),
                self._resolver.field_key(names.registered_at): _ms(now),
            },
        )
        try:
            node_id = self._resolver.node_id(work_item_id, names.node_registered)
            self._client.operate_node(work_item_id, node_id, action="confirm")
        except MeegleApiError as exc:
            # The node may already be completed (a re-run of the signup, or a person did
            # it): the fields above are the record; Meegle's refusal is not an error here.
            logger.info(
                "meegle onboarding: work_item=%s node %r not confirmed (%s)",
                work_item_id,
                names.node_registered,
                type(exc).__name__,
            )
        logger.info("meegle onboarding: work_item=%s registered tenant=%s", work_item_id, tenant_id)

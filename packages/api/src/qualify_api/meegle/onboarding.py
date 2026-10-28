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
  It also reads the optional «Cuenta de Instagram» (PB-1, m-24852194) and returns it
  normalized in `InvitationResult.instagram_handle`; missing, empty or invalid it is
  `None` and the invitation goes out exactly the same.
- `expire_for_terminated(work_item_id)` — the item was terminated (1005): every unused
  invite of that item expires now (`Estado Qualify = vencida`, best-effort).
- `mark_registered(work_item_id, tenant_id)` — `register_business` consumed the invite:
  complete **Registrada**, write `Estado Qualify = registrada`, `Tenant`, `Registrada el`.
  Called best-effort from the signup path, after its transaction, never failing a signup.
- `mark_delivered` / `mark_opened` / `mark_bounced` (M2) — the Resend webhook said the
  invitation reached the inbox (`entregada` + **Invitada** completed), was opened
  (`abierta`) or bounced (`rebotó` + a comment with the provider's reason). Called
  best-effort from `qualify_api.mail.handlers`, after the invite row is updated.

- `apply_plan_update(work_item_id, …)` (m-24852131) — the team completed **Plan
  ampliado**: read «Plan» / «Paquete» / «Motivo», apply them to the business the Alta
  became (`plan_request.apply_alta_plan`) and comment the result. If the business has not
  registered yet, the choice replaces the one waiting on its invite. An invalid value or a
  refusal of the plan services: `Estado Qualify = error`, a comment with the reason and
  **Plan ampliado** rolled back, like **Datos**.

`start_invitation` also validates «Plan» / «Paquete» (m-24852131) BEFORE creating the
invite — a value that is not a plan or a pack fails like a bad email — and stores the
choice on the invite; `auth.service.register_business` applies it once the business exists
(`apply_on_registration`).

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
    AltaPlanChoice,
    CreatedInvite,
    SignupNotAllowed,
    create_invite,
    email_exists,
    expire_invites_for_work_item,
    registered_tenant_for_work_item,
    send_invite_email,
    set_pending_alta_plan,
    signup_base_url,
)
from qualify_api.mail import Mailer, MailError, MailNotConfigured, default_mailer, mail_reply_to
from qualify_api.meegle.client import MeegleApiError, MeegleClient, WorkItem
from qualify_api.meegle.handles import normalize_channel, normalize_handle
from qualify_api.meegle.instagram import normalize_instagram_handle
from qualify_api.meegle.plan_request import (
    InvalidPlanRequest,
    PlanApplied,
    apply_alta_plan,
    confirmation_text,
    describe_choice,
    read_plan_choice,
)
from qualify_api.meegle.schema import MeegleSchemaError, SchemaResolver
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
    # «Cuenta de Instagram» normalized (`normalize_instagram_handle`), None when absent or
    # invalid. The Brand Kit prefill (PB-4, `meegle.prefill`) acts on it after a success.
    instagram_handle: str | None = None
    # The address the invitation went to (the Alta draft is prepared for it, PB-4).
    email: str = ""
    network: str | None = None
    handle: str | None = None
    account_reason: str = ""


@dataclass(frozen=True)
class PlanUpdateResult:
    ok: bool
    #: `applied`, `pending_registration`, or a short failure code
    reason: str = ""
    applied: PlanApplied | None = None


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
        account_exists: Callable[[str], bool] = email_exists,
    ) -> None:
        self._client = client
        self._resolver = resolver
        self._names = names or resolver.names
        self._mailer = mailer
        self._base_url = base_url
        self._signer = signer
        self._clock = clock
        self._account_exists = account_exists

    # -- helpers ---------------------------------------------------------------------

    def _read_item(self, work_item_id: int) -> WorkItem:
        items = self._client.query([work_item_id])
        for item in items:
            if item.id == work_item_id:
                return item
        raise WorkItemNotFound(str(work_item_id))

    def _field_text(self, item: WorkItem, name: str) -> str:
        return text_value(item.fields.get(self._resolver.field_key(name)))

    def _optional_field_text(self, item: WorkItem, name: str) -> str:
        """Like `_field_text`, but "" when the type has no such field (yet)."""
        try:
            key = self._resolver.field_key(name)
        except MeegleSchemaError:
            return ""
        return text_value(item.fields.get(key))

    def instagram_handle(self, item: WorkItem) -> str | None:
        """The item's «Cuenta de Instagram» as a bare lowercase username, or None.

        Never raises for a missing field, an empty one or junk in it: an Alta without
        Instagram is still a valid Alta (PB-1)."""
        raw = self._optional_field_text(item, self._names.instagram)
        handle = normalize_instagram_handle(raw)
        if raw and handle is None:
            logger.warning(
                "meegle onboarding: work_item=%s «%s» is not an Instagram account",
                item.id,
                self._names.instagram,
            )
        return handle

    def social_account(self, item: WorkItem) -> tuple[str | None, str | None, str]:
        """Resolve the select against metadata; never guess Instagram for missing data."""
        try:
            meta = self._resolver.field(self._names.channel)
        except MeegleSchemaError:
            return None, None, "no_channel"
        raw = item.fields.get(meta.key)
        # The Open API select may carry an opaque option id, or a value/label object.
        value = text_value(raw)
        labels = {option_value: label for label, option_value in meta.options}
        network = normalize_channel(labels.get(value, value))
        if network is None:
            return None, None, "no_channel" if not value else "invalid_channel"
        try:
            account_key = self._resolver.field_key(self._names.account)
        except MeegleSchemaError:
            account_key = None
        # The original field may remain during the UI rollout; it supplies ONLY the
        # identifier. A present but empty generic field never falls back to stale data.
        account = (
            text_value(item.fields.get(account_key))
            if account_key
            else self._optional_field_text(item, self._names.instagram)
        )
        handle = normalize_handle(network, account)
        return network, handle, "" if handle else ("invalid_handle" if account else "no_handle")

    def _status_pair(self, label: str) -> tuple[str, str | dict[str, str]]:
        names = self._names
        return self._resolver.field_key(names.status), self._resolver.select_field_value(
            names.status, label
        )

    def _link(self, invite: CreatedInvite) -> str:
        return invite.link(self._base_url or signup_base_url())

    def node_name(self, work_item_id: int, node_key: str) -> str | None:
        return self._resolver.node_name(work_item_id, node_key)

    # -- use-cases -------------------------------------------------------------------

    def plan_choice(self, item: WorkItem, *, event_key: str, actor: str) -> AltaPlanChoice:
        """«Plan» / «Paquete» / «Motivo» of the item; `InvalidPlanRequest` if invalid."""
        return read_plan_choice(
            item, self._resolver, self._names, event_key=event_key, requested_by=actor
        )

    def start_invitation(
        self, work_item_id: int, *, event_key: str = "", actor: str = ""
    ) -> InvitationResult:
        item = self._read_item(work_item_id)
        names = self._names
        email = self._field_text(item, names.email)
        person = self._field_text(item, names.person_name)
        note = self._field_text(item, names.note)
        business = item.name.strip()
        network, handle, account_reason = self.social_account(item)
        instagram = handle if network == "instagram" else None
        existing_login_raw = self._optional_field_text(item, names.existing_login)
        is_add_business = existing_login_raw.lower() in (
            "sí",
            "si",
            "true",
            "1",
            "yes",
            "verdadero",
        )
        if not is_add_business and self._account_exists(email):
            return self._fail(
                work_item_id,
                "existing_login_required",
                "Ese correo ya tiene cuenta en Qualify. Marca «Inicio de sesión existente» "
                "para agregarle este negocio y completa «Datos» otra vez.",
                None,
                instagram,
            )
        try:
            choice = self.plan_choice(item, event_key=event_key, actor=actor)
        except InvalidPlanRequest as exc:
            return self._fail(work_item_id, "invalid_plan", exc.message, None, instagram)
        extra: dict[str, Any] = {} if choice.empty else {"alta_plan": choice}
        extra["is_add_business"] = is_add_business

        invite: CreatedInvite | None = None
        try:
            invite = create_invite(
                email,
                invited_by=f"{INVITED_BY_PREFIX}{work_item_id}",
                recipient_name=person,
                business_name=business,
                note=note,
                meegle_work_item_id=work_item_id,
                **extra,
            )
            send_invite_email(
                self._mailer(),
                invite,
                self._base_url or signup_base_url(),
                signer=self._signer,
                can_reply=bool(mail_reply_to()),
            )
        except SignupNotAllowed as exc:
            return self._fail(work_item_id, "invalid_input", exc.message, invite, instagram)
        except MailNotConfigured as exc:
            return self._fail(work_item_id, "mail_not_configured", str(exc), invite, instagram)
        except MailError as exc:
            return self._fail(work_item_id, "mail_failed", str(exc), invite, instagram)

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
        sent = f"Invitación enviada a {invite.email}. Vence el {date_es(invite.expires_at)}."
        if not choice.empty:
            sent += f"\nAl registrarse el negocio se aplica: {describe_choice(choice)}."
        self._client.comment(work_item_id, sent)
        logger.info("meegle onboarding: work_item=%s invite=%s sent", work_item_id, invite.id)
        return InvitationResult(
            ok=True,
            invite_id=invite.id,
            instagram_handle=instagram,
            email=invite.email,
            network=network,
            handle=handle,
            account_reason=account_reason,
        )

    def _fail(
        self,
        work_item_id: int,
        reason: str,
        detail: str,
        invite: CreatedInvite | None,
        instagram: str | None = None,
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
        self._client.comment(
            work_item_id, detail if reason == "existing_login_required" else "\n".join(lines)
        )
        self._rollback_data_node(work_item_id, detail)
        logger.warning(
            "meegle onboarding: work_item=%s invitation failed (%s)", work_item_id, reason
        )
        return InvitationResult(
            ok=False,
            reason=reason,
            invite_id=invite.id if invite else None,
            instagram_handle=instagram,
        )

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

    # -- plan and pack (m-24852131) ----------------------------------------------------

    def apply_plan_update(
        self, work_item_id: int, *, event_key: str, actor: str
    ) -> PlanUpdateResult:
        """**Plan ampliado** completed: apply «Plan» / «Paquete» to the business."""
        from qualify_api.plans.catalog import UnknownPlan  # noqa: PLC0415
        from qualify_api.plans.pack_service import PackRefused  # noqa: PLC0415
        from qualify_api.plans.schedule import PlanChangeRefused  # noqa: PLC0415
        from qualify_api.plans.service import TenantNotFound  # noqa: PLC0415

        item = self._read_item(work_item_id)
        names = self._names
        try:
            choice = self.plan_choice(item, event_key=event_key, actor=actor)
        except InvalidPlanRequest as exc:
            return self._fail_plan(work_item_id, "invalid_plan", exc.message)
        if choice.empty:
            return self._fail_plan(
                work_item_id,
                "nothing_chosen",
                f"«{names.plan}» y «{names.pack}» están vacíos: elige un plan o un paquete.",
            )
        tenant_id = registered_tenant_for_work_item(work_item_id)
        if tenant_id is None:
            if set_pending_alta_plan(work_item_id, choice):
                self._client.comment(
                    work_item_id,
                    "El negocio todavía no se registró. Cuando se registre se aplica: "
                    f"{describe_choice(choice)}.",
                )
                logger.info("meegle plan: work_item=%s choice waits for signup", work_item_id)
                return PlanUpdateResult(ok=True, reason="pending_registration")
            return self._fail_plan(
                work_item_id,
                "not_registered",
                "este negocio no se registró y no tiene una invitación vigente. "
                f"Envía la invitación de nuevo completando «{names.node_data}».",
            )
        try:
            applied = apply_alta_plan(tenant_id, choice, work_item_id=work_item_id)
        except (PlanChangeRefused, PackRefused, TenantNotFound, UnknownPlan) as exc:
            return self._fail_plan(work_item_id, "plan_refused", str(exc))
        self._set_status(work_item_id, STATUS_REGISTERED)
        self._client.comment(work_item_id, confirmation_text(applied))
        logger.info("meegle plan: work_item=%s tenant=%s applied", work_item_id, tenant_id)
        return PlanUpdateResult(ok=True, reason="applied", applied=applied)

    def _fail_plan(self, work_item_id: int, reason: str, detail: str) -> PlanUpdateResult:
        names = self._names
        self._set_status(work_item_id, STATUS_ERROR)
        self._client.comment(
            work_item_id,
            f"No se aplicó el plan: {detail}\n"
            f"Corrige «{names.plan}» o «{names.pack}» y vuelve a completar «{names.node_plan}».",
        )
        try:
            node_id = self._resolver.node_id(work_item_id, names.node_plan)
            self._client.operate_node(
                work_item_id, node_id, action="rollback", rollback_reason=detail[:200]
            )
        except (MeegleApiError, MeegleSchemaError) as exc:
            logger.warning(
                "meegle plan: work_item=%s rollback of %r refused (%s)",
                work_item_id,
                names.node_plan,
                type(exc).__name__,
            )
        logger.warning("meegle plan: work_item=%s not applied (%s)", work_item_id, reason)
        return PlanUpdateResult(ok=False, reason=reason)

    def report_registration_plan(
        self, work_item_id: int, applied: PlanApplied | None, error: str = ""
    ) -> None:
        """After `register_business` applied (or failed to apply) the Alta's plan."""
        names = self._names
        if applied is not None:
            self._client.comment(work_item_id, confirmation_text(applied))
            return
        self._set_status(work_item_id, STATUS_ERROR)
        self._client.comment(
            work_item_id,
            f"El negocio se registró, pero no se aplicó el plan: {error or 'error interno'}\n"
            f"Revisa «{names.plan}» y «{names.pack}» y completa «{names.node_plan}».",
        )

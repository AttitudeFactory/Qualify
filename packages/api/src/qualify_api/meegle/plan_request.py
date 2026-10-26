"""The plan and pack of an «Alta de cliente» (m-24852131): read them from the item, apply
them to the business through the team's write paths, and say so on the item.

Fields on the item (names in `MeegleNames`, overridable by `QUALIFY_MEEGLE_FIELD_*`):

- «Plan» — select Básico / Plus / Pro; empty = Básico (no assignment is written: a
  business without one is on the catalog's default plan, m-24852145);
- «Paquete» — optional select: «+2 videos» / «+20 creaciones» / «+10 vistas previas»
  (the fixed packs of `precios-planes-v1`, m-24852129; no free quantities);
- «Motivo» — optional text, the reason kept with the assignment.

All three are OPTIONAL in the type: until the founder creates them, an Alta behaves
exactly as before. A value that is not a plan or a pack is refused before anything is
written (`InvalidPlanRequest`, with a message for the team in Spanish).

When it applies — never on field edits (1009), which would burn the Free plan's webhooks:

- **«Datos» completed** (new Alta): the choice is validated and stored on the invite
  (`signup_invites.alta_*`, 0097), and applied by `apply_on_registration` right after
  `register_business` creates the business (there is no `tenant_id` before).
- **«Plan ampliado» completed** (an Alta already registered): `OnboardingEngine.
  apply_plan_update` applies it at once; when the business has not registered yet, it
  replaces the choice waiting on the invite.

How it reaches the app: `plans.service.set_plan` (history: who, when, why; upgrade now,
downgrade next month) and `plans.pack_service.add_pack` (90 days from now; the list price
recorded as paid, `creation_payments`, invisible to the owner). Idempotency is per Meegle
event: the keys are `meegle:<event id>:plan` and `meegle:<event id>:pack`, so a webhook
retry (or a crash between the two writes) never applies twice, while completing the node
again — a new event — adds the chosen pack once more, as the ticket asks.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from qualify_shared.db.admin import admin_session
from sqlalchemy import text

from qualify_api.auth.invite_email import date_es
from qualify_api.auth.invites import AltaPlanChoice
from qualify_api.plans.catalog import (
    PACK_NAMES,
    PLANS_VERSION,
    PRICES_VERSION,
    PlansCatalog,
    PriceList,
    UnknownPack,
    load_plans,
    load_prices,
    pack_by_name,
    pack_name,
)
from qualify_api.plans.notify import TeamNotifier
from qualify_api.plans.schedule import month_of

if TYPE_CHECKING:
    from qualify_api.meegle.client import WorkItem
    from qualify_api.meegle.schema import SchemaResolver
    from qualify_api.meegle.settings import MeegleNames

logger = logging.getLogger("qualify_api.meegle.plan_request")


class InvalidPlanRequest(ValueError):
    """The item asks for a plan or pack that does not exist. `message` is for the team."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class PlanApplied:
    business: str
    plan_code: str | None
    plan_name: str | None
    #: the month the plan counts from (next month for a downgrade)
    effective_month: date | None
    current_month: date
    pack_code: str | None
    pack_expires_at: datetime | None


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    bare = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(bare.split()).casefold()


def _select_label(resolver: SchemaResolver, name: str, raw: Any) -> str:
    """The option LABEL of a select value, whatever shape Meegle used: an option value
    string, `{"value", "label"}`, a JSON string of either, or a one-element list."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped[:1] in ("{", "["):
            try:
                raw = json.loads(stripped)
            except ValueError:
                raw = stripped
        else:
            raw = stripped
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    if isinstance(raw, dict):
        label = raw.get("label") or raw.get("name")
        if isinstance(label, str) and label.strip():
            return label.strip()
        raw = raw.get("value", "")
    value = str(raw).strip() if raw is not None else ""
    if not value:
        return ""
    for option_label, option_value in resolver.field(name).options:
        if option_value == value:
            return option_label.strip()
    return value


def _optional(resolver: SchemaResolver, item: WorkItem, name: str) -> Any:
    """The raw value of a field the type may not have yet (None then)."""
    from qualify_api.meegle.schema import MeegleSchemaError  # noqa: PLC0415

    try:
        key = resolver.field_key(name)
    except MeegleSchemaError:
        return None
    return item.fields.get(key)


def plan_code_for(label: str, catalog: PlansCatalog) -> str | None:
    """«Básico» / «basico» / «Plus» / «PRO» → its code; "" → None; else refused."""
    if not label.strip():
        return None
    wanted = _fold(label)
    for code in catalog.codes():
        if wanted in (_fold(catalog.get(code).name), _fold(code)):
            return code
    names = ", ".join(catalog.get(c).name for c in catalog.codes())
    raise InvalidPlanRequest(f"«{label}» no es un plan. Los planes son: {names}.")


def pack_code_for(label: str, prices: PriceList) -> str | None:
    if not label.strip():
        return None
    try:
        return pack_by_name(label, prices).code
    except UnknownPack:
        names = ", ".join(f"«{n}»" for n in PACK_NAMES.values())
        raise InvalidPlanRequest(
            f"«{label}» no es un paquete. Los paquetes son: {names}."
        ) from None


def read_plan_choice(
    item: WorkItem,
    resolver: SchemaResolver,
    names: MeegleNames,
    *,
    event_key: str,
    requested_by: str,
    catalog: PlansCatalog | None = None,
    prices: PriceList | None = None,
) -> AltaPlanChoice:
    """«Plan», «Paquete» and «Motivo» of the item, validated against the catalogs."""
    from qualify_api.meegle.onboarding import text_value  # noqa: PLC0415 — no cycle at import

    plans = catalog or load_plans(PLANS_VERSION)
    table = prices or load_prices(PRICES_VERSION)
    plan_raw = _optional(resolver, item, names.plan)
    pack_raw = _optional(resolver, item, names.pack)
    plan_label = _select_label(resolver, names.plan, plan_raw) if plan_raw is not None else ""
    pack_label = _select_label(resolver, names.pack, pack_raw) if pack_raw is not None else ""
    return AltaPlanChoice(
        plan_code=plan_code_for(plan_label, plans),
        pack_code=pack_code_for(pack_label, table),
        reason=text_value(_optional(resolver, item, names.plan_reason))[:500],
        requested_by=requested_by[:200],
        event_key=event_key[:200],
    )


def describe_choice(choice: AltaPlanChoice, catalog: PlansCatalog | None = None) -> str:
    """«plan Plus y el paquete «+2 videos»» — for the item's comments."""
    plans = catalog or load_plans(PLANS_VERSION)
    parts = []
    if choice.plan_code:
        parts.append(f"plan {plans.get(choice.plan_code).name}")
    if choice.pack_code:
        parts.append(f"el paquete «{pack_name(choice.pack_code)}»")
    return " y ".join(parts)


def _business_name(tenant_id: UUID) -> str:
    with admin_session() as session:
        return str(
            session.scalar(text("SELECT name FROM tenants WHERE id = :id"), {"id": tenant_id}) or ""
        )


def apply_alta_plan(
    tenant_id: UUID,
    choice: AltaPlanChoice,
    *,
    work_item_id: int,
    now: datetime | None = None,
    catalog: PlansCatalog | None = None,
    prices: PriceList | None = None,
    notifier: TeamNotifier | None = None,
) -> PlanApplied:
    """Apply `choice` to the business: plan first, then pack, each idempotent by the
    event. Raises `PlanChangeRefused` / `PackRefused` / `TenantNotFound` / `UnknownPlan`
    when the services refuse — nothing of THAT write is applied."""
    from qualify_api.plans.pack_service import add_pack  # noqa: PLC0415
    from qualify_api.plans.service import set_plan  # noqa: PLC0415

    plans = catalog or load_plans(PLANS_VERSION)
    moment = now or datetime.now(UTC)
    reason = choice.reason.strip() or f"Alta de cliente en Meegle (ítem {work_item_id})"
    by = choice.requested_by.strip() or "meegle"
    key = choice.event_key.strip() or f"item:{work_item_id}"
    effective: date | None = None
    if choice.plan_code:
        result = set_plan(
            tenant_id=tenant_id,
            plan_code=choice.plan_code,
            reason=reason,
            assigned_by=by,
            source="meegle_alta",
            meegle_work_item_id=work_item_id,
            idempotency_key=f"meegle:{key}:plan",
            now=moment,
            catalog=plans,
            notifier=notifier,
        )
        effective = result.effective_month
    expires: datetime | None = None
    if choice.pack_code:
        pack = add_pack(
            tenant_id=tenant_id,
            pack=choice.pack_code,
            reason=reason,
            granted_by=by,
            meegle_work_item_id=work_item_id,
            payment_ref=f"meegle:{work_item_id}",
            idempotency_key=f"meegle:{key}:pack",
            now=moment,
            prices=prices,
            notifier=notifier,
        )
        expires = pack.expires_at
    return PlanApplied(
        business=_business_name(tenant_id),
        plan_code=choice.plan_code,
        plan_name=plans.get(choice.plan_code).name if choice.plan_code else None,
        effective_month=effective,
        current_month=month_of(moment),
        pack_code=choice.pack_code,
        pack_expires_at=expires,
    )


def confirmation_text(applied: PlanApplied) -> str:
    """«Plan de Arepera La Nona: Plus. Se sumó el paquete +2 videos, vence el 24 de
    enero.» — the comment on the item after a plan/pack is applied."""
    business = applied.business or "el negocio"
    lines: list[str] = []
    if applied.plan_name:
        when = ""
        if applied.effective_month and applied.effective_month > applied.current_month:
            first = datetime(
                applied.effective_month.year, applied.effective_month.month, 1, 12, tzinfo=UTC
            )
            when = f" desde el {date_es(first)}"
        lines.append(f"Plan de {business}: {applied.plan_name}{when}.")
    if applied.pack_code and applied.pack_expires_at is not None:
        until = date_es(applied.pack_expires_at)
        pack = f"el paquete {pack_name(applied.pack_code)}, vence el {until}."
        lines.append(f"Se sumó {pack}" if lines else f"A {business} se le sumó {pack}")
    return " ".join(lines)


def apply_on_registration(
    work_item_id: int,
    tenant_id: UUID,
    choice: AltaPlanChoice,
    *,
    now: datetime | None = None,
    notifier: TeamNotifier | None = None,
) -> PlanApplied | None:
    """`register_business` just created the business of an Alta that chose a plan or a
    pack: apply it (registration moment = the pack's start, so it ends 90 days after the
    signup), then tell the item. Never raises: the signup already happened, a failure is
    reported on the item (`Estado Qualify = error`) for the team to fix with «Plan
    ampliado», and logged."""
    applied: PlanApplied | None = None
    error = ""
    try:
        applied = apply_alta_plan(
            tenant_id, choice, work_item_id=work_item_id, now=now, notifier=notifier
        )
        logger.info(
            "meegle plan: work_item=%s tenant=%s applied at signup", work_item_id, tenant_id
        )
    except Exception as exc:  # noqa: BLE001 — never fail (or retry) a signup over it
        error = str(exc)[:300] or type(exc).__name__
        logger.warning(
            "meegle plan: work_item=%s tenant=%s not applied at signup (%s)",
            work_item_id,
            tenant_id,
            type(exc).__name__,
        )
    try:
        from qualify_api.meegle.handlers import production_engine  # noqa: PLC0415
        from qualify_api.meegle.settings import meegle_configured  # noqa: PLC0415

        if meegle_configured():
            production_engine().report_registration_plan(work_item_id, applied, error)
    except Exception as exc:  # noqa: BLE001 — the write-back is best-effort
        logger.warning(
            "meegle plan: work_item=%s write-back skipped (%s)", work_item_id, type(exc).__name__
        )
    return applied


__all__ = [
    "InvalidPlanRequest",
    "PlanApplied",
    "apply_alta_plan",
    "apply_on_registration",
    "confirmation_text",
    "describe_choice",
    "pack_code_for",
    "plan_code_for",
    "read_plan_choice",
]

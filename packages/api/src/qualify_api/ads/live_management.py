"""Explicit two-step paid edits, exact Meta validation and immutable audited consent."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.edit_ledger import (
    EDIT_PIPELINE,
    consistent_intent,
    effective,
    operations,
    overlay,
    revision,
)
from qualify_api.ads.edit_review import (
    REPREPARE,
    TTL,
    PreparedPromotionEdit,
    PromotionEditResult,
    seal,
    unseal,
)
from qualify_api.ads.live_wizard import LiveWizardGateway, PersistedWizardSources, authorize_actor
from qualify_api.ads.promotion_repository import PostgresPromotionRepository
from qualify_api.ads.promotions import Promotion, fingerprint
from qualify_api.ads.results import ResultsUnavailable
from qualify_api.ads.results_service import (
    ResultScope,
    _claim_pause,
    _dispatch,
    _finish_pause,
    _load,
    _member,
    _same,
    _scope,
)
from qualify_api.tenancy.acting import current_acting_login

RESOURCES = ("ads", "adsets", "campaigns")
UNKNOWN = "No pudimos confirmar el cambio. Actualiza el estado antes de intentar otro cambio."


def _actor(scope: ResultScope) -> UUID:
    with tenant_session(scope.tenant_id, independent=True) as session:
        actor = session.scalar(
            text("SELECT id FROM users WHERE auth_user_id=:login"),
            {"login": current_acting_login()},
        )
    if actor is None:
        raise ResultsUnavailable("Vuelve a entrar para revisar esta promoción.")
    authorize_actor(scope.tenant_id, actor)
    return actor


def _context(scope: ResultScope) -> tuple[Promotion, str, LiveWizardGateway, Any]:
    actor = _actor(scope)
    with tenant_session(scope.tenant_id, independent=True) as session:
        consent = session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM ad_promotion_activations "
                "WHERE promotion_id=:id AND state='active' AND confirmed_by IS NOT NULL "
                "AND confirmed_at IS NOT NULL)"
            ),
            {"id": scope.promotion_id},
        )
    original = PostgresPromotionRepository().get(scope.tenant_id, scope.promotion_id)
    if (
        not consent
        or original is None
        or original.status != "active"
        or original.request.get("currency") != "COP"
        or original.request.get("meta_currency_offset") != 1
        or original.request.get("budget_kind") != "lifetime"
        or original.request.get("publish_attempt_id") is None
        or set(original.ids) != {"campaigns", "adsets", "adcreatives", "ads"}
    ):
        raise ResultsUnavailable(
            "Esta promoción necesita una comprobación inicial antes de editarla."
        )
    promotion, ledger = effective(scope.tenant_id, original)
    gateway = LiveWizardGateway(
        tenant_id=scope.tenant_id,
        actor=actor,
        sources=PersistedWizardSources(),
        authorize=authorize_actor,
    )
    source = gateway.sources.get(scope.tenant_id, UUID(promotion.request["publish_attempt_id"]))
    return promotion, ledger, gateway, source


def _local(
    scope: ResultScope,
    gateway: LiveWizardGateway,
    source: Any,
    promotion: Promotion,
    ledger: str,
    expires: datetime,
    operation: UUID | None = None,
) -> None:
    _same(scope)
    gateway.local_guard(source)
    repository = PostgresPromotionRepository()
    if (
        repository.current_enhancements(scope.tenant_id, UUID(promotion.request["brand_id"]))
        != (promotion.request["enhancements_snapshot"])
    ):
        raise ResultsUnavailable("Los permisos de la marca cambiaron. Vuelve a comprobarlos.")
    if datetime.now(UTC) >= expires:
        raise ResultsUnavailable(REPREPARE)
    with tenant_session(scope.tenant_id, independent=True) as session:
        rows = operations(session, scope.promotion_id)
    prior = [row for row in rows if row["id"] != operation]
    if revision(prior) != ledger:
        raise ResultsUnavailable(REPREPARE)
    outstanding = [row for row in rows if row["state"] in {"in_flight", "unknown"}]
    if (
        operation is None
        and outstanding
        or operation is not None
        and (
            len(outstanding) != 1
            or outstanding[0]["id"] != operation
            or outstanding[0]["state"] != "in_flight"
        )
    ):
        raise ResultsUnavailable("Hay otro cambio por comprobar. Actualiza el estado.")


async def _statuses(
    gateway: LiveWizardGateway, source: Any, promotion: Promotion
) -> tuple[str, ...]:
    active = []
    async with gateway.client(source) as client:
        for resource in RESOURCES:
            row = await client.read_object(promotion.ids[resource], fields="id,status")
            if row.get("id") != promotion.ids[resource] or row.get("status") not in {
                "ACTIVE",
                "PAUSED",
            }:
                raise ResultsUnavailable("Meta no confirmó un estado que permita este cambio.")
            if row["status"] == "ACTIVE":
                active.append(resource)
    gateway.local_guard(source)
    return tuple(active)


def _intent(
    promotion: Promotion, action: str, budget_minor: int | None, end_time: datetime | None
) -> tuple[Promotion, dict[str, Any], str]:
    request = deepcopy(promotion.request)
    if action == "budget" and end_time is None and type(budget_minor) is int:
        # A decrease is allowed only above `_decrease_floor` (lifetime spend read from the
        # ad set itself, never from daily Insights, plus Meta's measured daily minimum).
        if (
            budget_minor == request["budget_minor"]
            or budget_minor <= 0
            or budget_minor % 100
            or budget_minor >= 10**18
        ):
            raise ResultsUnavailable("Escribe un monto sin centavos y distinto del actual.")
        request["budget_minor"] = budget_minor
        payload = {"lifetime_budget": budget_minor // 100}
        amount = f"{budget_minor // 100:,}".replace(",", ".")
        summary = f"Cambiar el presupuesto total a {amount} COP."
    elif action == "end_time" and budget_minor is None and isinstance(end_time, datetime):
        if end_time.utcoffset() is None or end_time <= max(
            datetime.now(UTC), datetime.fromisoformat(request["start_time"])
        ):
            raise ResultsUnavailable(
                "La fecha de fin debe ser posterior al inicio y al momento actual."
            )
        request["end_time"] = end_time.isoformat()
        payload, summary = (
            {"end_time": end_time.isoformat()},
            "Cambiar la fecha de fin de la promoción.",
        )
    elif action == "resume" and budget_minor is None and end_time is None:
        if datetime.fromisoformat(request["end_time"]) <= datetime.now(UTC):
            raise ResultsUnavailable(
                "La promoción terminó. Revisa la fecha de fin antes de reanudarla."
            )
        payload, summary = (
            {"status": "ACTIVE"},
            "Reanudar la promoción con el presupuesto y las fechas mostrados.",
        )
    else:
        raise ResultsUnavailable("Revisa el cambio antes de confirmarlo.")
    return replace(promotion, request=request), payload, summary


def _values(promotion: Promotion) -> dict[str, Any]:
    return {key: promotion.request[key] for key in ("budget_minor", "end_time")}


def _whole(value: Any) -> int | None:
    """A Meta amount in its own unit (whole pesos for COP, offset 1): int or digit string."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value >= 0 else None
    return int(value) if isinstance(value, str) and re.fullmatch(r"[0-9]{1,18}", value) else None


def _decrease(action: str, before: Promotion, after: Promotion) -> bool:
    return action == "budget" and after.request["budget_minor"] < before.request["budget_minor"]


FLOOR_UNAVAILABLE = "No pudimos comprobar lo gastado y el mínimo de Meta. Inténtalo de nuevo."


async def _decrease_floor(
    gateway: LiveWizardGateway, source: Any, promotion: Promotion, new_minor: int
) -> dict[str, int]:
    """Lowest lifetime budget (minor units) Qualify lets the owner set right now.

    floor = max(spent + daily_min x remaining_days, daily_min x schedule_days), where
    `spent` = the ad set's `lifetime_budget - budget_remaining` and `daily_min` the
    largest `min_daily_budget*` of `act_<id>/minimum_budgets` for COP. Meta's own
    `validate_only` on the exact amount stays the final word; this only refuses earlier.
    """
    request = promotion.request
    current = request["budget_minor"] // 100
    async with gateway.client(source) as client:
        adset = await client.read_object(
            promotion.ids["adsets"], fields="id,lifetime_budget,budget_remaining"
        )
        minimums = await client.minimum_budgets()
    lifetime, remaining = (
        _whole(adset.get("lifetime_budget")),
        _whole(adset.get("budget_remaining")),
    )
    rows = [row for row in minimums.data if row.get("currency") == "COP"]
    daily = (
        [_whole(v) for k, v in rows[0].items() if k.startswith("min_daily_budget")]
        if len(rows) == 1
        else []
    )
    if (
        adset.get("id") != promotion.ids["adsets"]
        or lifetime != current
        or remaining is None
        or remaining > lifetime
        or not daily
        or any(value is None or value <= 0 for value in daily)
    ):
        raise ResultsUnavailable(FLOOR_UNAVAILABLE)
    minimum = max(daily)
    start = datetime.fromisoformat(request["start_time"])
    end = datetime.fromisoformat(request["end_time"])
    day = timedelta(days=1)
    # shortcut: 24-h blocks, not the account's calendar days (can be off by one day);
    # Meta's validate_only on the exact amount still guards. Upgrade if owners hit it.
    schedule_days = max(1, -(-(end - start) // day))
    remaining_days = max(0, -(-(end - max(datetime.now(UTC), start)) // day))
    spent = lifetime - remaining
    floor = max(spent + minimum * remaining_days, minimum * schedule_days) * 100
    if new_minor < floor:
        amount = f"{floor // 100:,}".replace(",", ".")
        raise ResultsUnavailable(
            f"Puedes bajarlo hasta ${amount}. Por debajo, Meta no deja que tu anuncio siga "
            "saliendo los días que faltan."
        )
    return {"spent_minor": spent * 100, "daily_minimum_minor": minimum * 100, "floor": floor}


async def prepare_promotion_edit(
    *,
    tenant_id: UUID,
    promotion_id: UUID,
    request_key: str,
    action: str,
    budget_minor: int | None = None,
    end_time: datetime | None = None,
) -> PreparedPromotionEdit:
    if not isinstance(request_key, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", request_key):
        raise ResultsUnavailable("Vuelve a revisar el cambio.")
    scope = _scope(tenant_id, promotion_id)
    promotion, ledger, gateway, source = _context(scope)
    changed, payload, summary = _intent(promotion, action, budget_minor, end_time)
    now = datetime.now(UTC)
    expires = now + TTL
    baseline = await _statuses(gateway, source, promotion)
    await gateway.remote_guard(promotion, active_resources=baseline)
    targets = (
        [resource for resource in RESOURCES if resource not in baseline]
        if action == "resume"
        else ["adsets"]
    )
    if not targets:
        raise ResultsUnavailable("La promoción ya está activa. Actualiza su estado.")
    floor = (
        await _decrease_floor(gateway, source, promotion, changed.request["budget_minor"])
        if _decrease(action, promotion, changed)
        else None
    )
    async with gateway.client(source) as client:
        for resource in targets:
            await client.validate_update(promotion.ids[resource], params=payload)
    _local(scope, gateway, source, promotion, ledger, expires)
    token = seal(
        {
            "tenant": str(tenant_id),
            "promotion": str(promotion_id),
            "key": request_key,
            "actor": str(gateway.actor),
            "login": str(current_acting_login()),
            "scope": fingerprint(
                {
                    "connection": str(scope.connection.connection_id),
                    "version": scope.connection.version,
                    "account": str(scope.account_id),
                }
            ),
            "original": fingerprint(
                PostgresPromotionRepository().get(tenant_id, promotion_id).request
            ),
            "ledger": ledger,
            "before": _values(promotion),
            "after": _values(changed),
            "action": action,
            "payload": payload,
            "baseline": list(baseline),
            "targets": targets,
            "effective": fingerprint(promotion.request),
            "pipeline": EDIT_PIPELINE,
            "floor": floor,
        },
        now,
    )
    return PreparedPromotionEdit(
        action,
        summary,
        expires,
        promotion.request["budget_minor"],
        changed.request["budget_minor"],
        datetime.fromisoformat(promotion.request["end_time"]),
        datetime.fromisoformat(changed.request["end_time"]),
        token,
    )


async def confirm_promotion_edit(
    *,
    tenant_id: UUID,
    promotion_id: UUID,
    request_key: str,
    approval_token: str,
    confirm_change: bool,
) -> PromotionEditResult:
    if confirm_change is not True:
        raise ResultsUnavailable("Confirma el cambio después de revisar sus detalles.")
    body = unseal(approval_token, datetime.now(UTC))
    if not consistent_intent(
        body.get("action"), body.get("payload"), body.get("before"), body.get("after")
    ):
        raise ResultsUnavailable(REPREPARE)
    scope = _scope(tenant_id, promotion_id)
    actor = _actor(scope)
    if (
        body.get("tenant"),
        body.get("promotion"),
        body.get("key"),
        body.get("actor"),
        body.get("login"),
    ) != (str(tenant_id), str(promotion_id), request_key, str(actor), str(current_acting_login())):
        raise ResultsUnavailable(REPREPARE)
    # A durable replay is always read-only, including after a new ledger revision.
    with tenant_session(tenant_id, independent=True) as session:
        previous = (
            session.execute(
                text(
                    "SELECT actor_id,promotion_id,action,payload,state "
                    "FROM ad_promotion_operations WHERE request_key=:key"
                ),
                {"key": request_key},
            )
            .mappings()
            .first()
        )
    if previous:
        if (
            previous["actor_id"],
            previous["promotion_id"],
            previous["action"],
            previous["payload"],
        ) != (actor, promotion_id, body["action"], body["payload"]):
            raise ResultsUnavailable(REPREPARE)
        state = previous["state"]
        return PromotionEditResult(
            promotion_id,
            body["action"],
            "completed" if state in {"completed", "reconciled"} else "unknown",
            UNKNOWN if state not in {"completed", "reconciled"} else "El cambio ya fue confirmado.",
        )
    promotion, ledger, gateway, source = _context(scope)
    expires = datetime.fromisoformat(body["expires_at"])
    original = PostgresPromotionRepository().get(tenant_id, promotion_id)
    if (
        ledger != body["ledger"]
        or fingerprint(promotion.request) != body["effective"]
        or fingerprint(original.request) != body["original"]
        or body["before"] != _values(promotion)
        or body["scope"]
        != fingerprint(
            {
                "connection": str(scope.connection.connection_id),
                "version": scope.connection.version,
                "account": str(scope.account_id),
            }
        )
    ):
        raise ResultsUnavailable(REPREPARE)
    changed = replace(promotion, request=deepcopy(promotion.request) | body["after"])
    active = tuple(body["baseline"])
    await gateway.remote_guard(promotion, active_resources=active)
    if _decrease(body["action"], promotion, changed):
        # Spending went on while the owner read the review: floor it again before the claim.
        await _decrease_floor(gateway, source, promotion, changed.request["budget_minor"])
    _local(scope, gateway, source, promotion, ledger, expires)
    operation, state = _claim_pause(
        scope,
        request_key,
        datetime.now(UTC),
        action=body["action"],
        payload=body["payload"],
        evidence=body | {"confirmed": True, "confirmed_at": datetime.now(UTC).isoformat()},
        expected_revision=ledger,
    )
    if state != "claimed":
        return PromotionEditResult(promotion_id, body["action"], "unknown", UNKNOWN)

    dispatched = False
    try:
        async with gateway.client(source) as client:
            for resource in body["targets"]:
                expected = promotion

                async def before_write():
                    nonlocal dispatched
                    await gateway.remote_guard(expected, active_resources=active)
                    _local(scope, gateway, source, promotion, ledger, expires, operation)
                    if not dispatched:
                        _dispatch(scope, operation)
                        dispatched = True

                await client.update(
                    promotion.ids[resource], params=body["payload"], before_write=before_write
                )
                if body["action"] == "resume":
                    active = (*active, resource)
                else:
                    promotion = changed
                await gateway.remote_guard(
                    changed if body["action"] != "resume" else promotion, active_resources=active
                )
                _local(scope, gateway, source, promotion, ledger, expires, operation)
        _local(scope, gateway, source, promotion, ledger, expires, operation)
        _finish_pause(scope, operation, "completed")
        with tenant_session(tenant_id, independent=True) as session:
            session.execute(
                text("UPDATE ad_promotion_observations SET checked_at=NULL WHERE promotion_id=:id"),
                {"id": promotion_id},
            )
        return PromotionEditResult(
            promotion_id,
            body["action"],
            "completed",
            "Meta confirmó el cambio. Actualiza los resultados para ver su estado.",
            _load(tenant_id, promotion_id),
        )
    except Exception:
        # A claim may have reached Meta even when its response/audit could not be saved.
        # Never retry a paid POST. Read-only reconciliation must settle the uncertainty.
        try:
            _finish_pause(scope, operation, "unknown")
        except Exception:
            pass
        return PromotionEditResult(promotion_id, body["action"], "unknown", UNKNOWN)


async def reconcile_promotion_edit(scope: ResultScope, *, system: bool = False) -> bool:
    """Read the entire approved chain; never resends a write with an uncertain outcome."""
    with tenant_session(scope.tenant_id, independent=True) as session:
        rows = operations(session, scope.promotion_id)
        pending = (
            session.execute(
                text(
                    "SELECT id,created_at,dispatched_at FROM ad_promotion_operations "
                    "WHERE promotion_id=:id AND state IN ('in_flight','unknown') "
                    "AND action<>'pause'"
                ),
                {"id": scope.promotion_id},
            )
            .mappings()
            .all()
        )
    if len(pending) != 1 or pending[0]["dispatched_at"] is None:
        return False
    dispatch_stamp = pending[0]["dispatched_at"]
    latest_dispatch = max(pending[0]["created_at"], dispatch_stamp)
    if latest_dispatch >= datetime.now(UTC) - timedelta(seconds=90):
        return False
    operation = pending[0]["id"]
    own = next(row for row in rows if row["id"] == operation)
    body = own["approval_evidence"]
    if (
        not isinstance(body, dict)
        or body.get("pipeline") != EDIT_PIPELINE
        or body.get("confirmed") is not True
        or not consistent_intent(
            own["action"], own["payload"], body.get("before"), body.get("after")
        )
    ):
        return False
    others = [row for row in rows if row["id"] != operation]
    if revision(others) != body.get("ledger"):
        return False
    original = PostgresPromotionRepository().get(scope.tenant_id, scope.promotion_id)
    if original is None or fingerprint(original.request) != body.get("original"):
        return False
    before = overlay(original, others)
    if _values(before) != body.get("before"):
        return False
    after = replace(before, request=deepcopy(before.request) | body["after"])

    def authorize(tenant: UUID, actor: UUID) -> None:
        _member(tenant, system=system)
        _same(scope, system=system)
        if (
            PostgresPromotionRepository().current_enhancements(
                tenant, UUID(after.request["brand_id"])
            )
            != after.request["enhancements_snapshot"]
        ):
            raise ResultsUnavailable(REPREPARE)

    gateway = LiveWizardGateway(
        tenant_id=scope.tenant_id,
        actor=UUID(body["actor"]),
        sources=PersistedWizardSources(),
        authorize=authorize,
    )
    active = tuple(RESOURCES) if own["action"] == "resume" else tuple(body["baseline"])
    try:
        await gateway.remote_guard(after, active_resources=active)
        authorize(scope.tenant_id, gateway.actor)
        with tenant_session(scope.tenant_id, independent=True) as session:
            session.execute(
                text("SELECT id FROM ad_promotions WHERE id=:id FOR UPDATE"),
                {"id": scope.promotion_id},
            ).one()
            current = operations(session, scope.promotion_id)
            observed_dispatch = session.scalar(
                text("SELECT dispatched_at FROM ad_promotion_operations WHERE id=:id"),
                {"id": operation},
            )
            current_own = next(row for row in current if row["id"] == operation)
            if (
                observed_dispatch != dispatch_stamp
                or current_own["state"] not in {"in_flight", "unknown"}
                or revision([row for row in current if row["id"] != operation]) != body["ledger"]
            ):
                return False
            session.execute(
                text(
                    "UPDATE ad_promotion_operations SET state='reconciled',finished_at=:now "
                    "WHERE id=:id AND state IN ('in_flight','unknown')"
                ),
                {"id": operation, "now": datetime.now(UTC)},
            )
        return True
    except Exception:
        return False

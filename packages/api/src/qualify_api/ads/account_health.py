"""Read-only, tenant-scoped account health with versioned daily observations."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.client import MarketingSettings
from qualify_api.ads.health_models import (
    HEALTH_FIELDS,
    SNAPSHOT_KEYS,
    AccountHealth,
    HealthObservation,
    account_status_label,
    ad_delivery_label,
    disable_reason_label,
)
from qualify_api.connections.ad_accounts import (
    AdAccountUnavailable,
    AdConnection,
    GraphAdAccountReader,
    _authenticated_client,
    _connection,
    _permission_reason,
)
from qualify_api.connections.resolver import AuthenticatedClient
from qualify_api.tenancy.acting import require_acting_member

PIPELINE_VERSION = "ad-account-health-v1"
DAILY_AGE = timedelta(hours=24)
UNAVAILABLE = "No pudimos comprobar la cuenta publicitaria. Actualiza su estado para continuar."


@dataclass(frozen=True)
class HealthTarget:
    account_id: UUID
    tenant_id: UUID
    connection: AdConnection
    meta_account_id: str
    name: str
    currency: str
    selected: bool
    snapshot: dict[str, Any] | None
    checked_at: datetime | None
    health_version: int | None
    read_failed: bool
    refresh_token: UUID | None = None
    owned_ad_ids: tuple[str, ...] = ()


class HealthReader(Protocol):
    async def read(self, target: HealthTarget) -> HealthObservation: ...


class GraphAccountHealthReader:
    """Only account fields and effective status of already-owned persisted ad IDs."""

    def __init__(
        self, client: AuthenticatedClient, settings: MarketingSettings | None = None
    ) -> None:
        self._reader = GraphAdAccountReader(client, settings)

    async def read(self, target: HealthTarget) -> HealthObservation:
        payload = await self._reader._get(
            f"/act_{target.meta_account_id}", {"fields": HEALTH_FIELDS}
        )
        try:
            observation = HealthObservation.from_graph(
                payload, account_id=target.meta_account_id, currency=target.currency
            )
        except ValueError:
            raise AdAccountUnavailable(UNAVAILABLE) from None
        if observation.account_status in {2, 3, 7, 9, 100, 101} or (
            observation.disable_reason is not None and observation.disable_reason > 0
        ):
            return replace(observation, pending_billing=None)
        pending: bool | None = False if len(target.owned_ad_ids) <= 100 else None
        for ad_id in target.owned_ad_ids[:100]:
            try:
                status = await self._reader._get(
                    f"/{ad_id}", {"fields": "id,account_id,effective_status"}
                )
            except AdAccountUnavailable:
                # A secondary read must not erase a valid account observation.
                pending = True if pending is True else None
                break
            if status.get("id") != ad_id or status.get("account_id") != target.meta_account_id:
                raise AdAccountUnavailable(UNAVAILABLE)
            if not isinstance(status.get("effective_status"), str):
                raise AdAccountUnavailable(UNAVAILABLE)
            if status["effective_status"] == "PENDING_BILLING_INFO":
                pending = True
        return replace(observation, pending_billing=pending)


def _target(tenant_id: UUID, account_id: UUID, *, claim: bool = False) -> HealthTarget:
    with tenant_session(tenant_id) as session:
        row = session.execute(
            text("SELECT connection_id FROM ad_accounts WHERE id=:id"), {"id": account_id}
        ).first()
        if row is None:
            raise AdAccountUnavailable("Esta cuenta publicitaria ya no está disponible.")
        connection = _connection(session, row.connection_id, lock=claim)
        account = (
            session.execute(
                text(
                    """SELECT * FROM ad_accounts WHERE id=:id AND available
                AND brand_id=:brand AND credential_version=:version"""
                    + (" FOR UPDATE" if claim else "")
                ),
                {"id": account_id, "brand": connection.brand_id, "version": connection.version},
            )
            .mappings()
            .first()
        )
        if account is None:
            raise AdAccountUnavailable("La cuenta cambió. Actualiza las cuentas publicitarias.")
        token = uuid4() if claim else account["health_refresh_token"]
        if claim:
            reason = _permission_reason(connection)
            if reason:
                raise AdAccountUnavailable(reason)
            session.execute(
                text(
                    "UPDATE ad_accounts SET health_refresh_token=:token, "
                    "health_last_attempt_at=:now WHERE id=:id"
                ),
                {"token": token, "now": datetime.now(UTC), "id": account_id},
            )
        ads = session.scalars(
            text("""SELECT DISTINCT p.meta_ad_id FROM ad_promotions p
              JOIN publish_attempts a ON a.id=p.publish_attempt_id AND a.tenant_id=p.tenant_id
                AND a.status='published' AND a.published_media_id=p.source_media_id
              JOIN calendar_events e ON e.publish_attempt_id=a.id AND e.tenant_id=a.tenant_id
                AND e.connection_id=a.connection_id AND e.post_id=p.content_draft_id
                AND e.brand_id=p.brand_id AND e.status='published'
              WHERE p.brand_id=:brand AND p.meta_ad_account_id=:aid
                AND a.connection_id=:cid AND p.meta_ad_id ~ '^[0-9]+$'
              ORDER BY p.meta_ad_id LIMIT 101"""),
            {
                "brand": connection.brand_id,
                "aid": account["ad_account_id"],
                "cid": connection.connection_id,
            },
        ).all()
        return HealthTarget(
            account_id,
            tenant_id,
            connection,
            account["ad_account_id"],
            account["name"],
            account["currency"],
            account["selected"],
            account["health_snapshot"],
            account["health_checked_at"],
            account["health_credential_version"],
            account["health_read_failed"],
            token,
            tuple(ads),
        )


def _snapshot_observation(target: HealthTarget) -> HealthObservation | None:
    data = target.snapshot
    if not isinstance(data, dict) or set(data) - SNAPSHOT_KEYS:
        return None
    if (
        data.get("currency") != target.currency
        or data.get("source_id") != f"act_{target.meta_account_id}"
        or data.get("pipeline_version") != PIPELINE_VERSION
    ):
        return None
    values = {key: data.get(key) for key in HealthObservation.__dataclass_fields__}
    for key in ("account_status", "disable_reason", "amount_spent_minor", "spend_cap_minor"):
        if values[key] is not None and (type(values[key]) is not int or values[key] < 0):
            return None
    for key in ("funding_present", "pending_billing", "money_units_verified"):
        if values[key] is not None and type(values[key]) is not bool:
            return None
    try:
        return HealthObservation(**values)
    except ValueError:
        return None


def project_health(target: HealthTarget, *, now: datetime | None = None) -> AccountHealth:
    now = now or datetime.now(UTC)
    observation = _snapshot_observation(target)
    fresh = bool(
        observation
        and target.health_version == target.connection.version
        and target.checked_at
        and now - DAILY_AGE < target.checked_at <= now
    )
    state, label, tone, reason = (
        "unknown",
        "Sin comprobar",
        "warn",
        "Actualiza el estado de la cuenta publicitaria.",
    )
    # Missing, stale or unreadable payment evidence cannot open a spending flow.
    # Keep its diagnosis unknown: absence was not established by a missing field.
    blocks, ready = True, False
    permission = _permission_reason(target.connection, now)
    if fresh and observation:
        code = observation.account_status
        if observation.pending_billing is True:
            state, label, reason = (
                "payment_required",
                ad_delivery_label("PENDING_BILLING_INFO"),
                "Meta pide revisar la información de pago. Revísala en Meta y actualiza el estado.",
            )
            blocks = True
        elif code in {2, 3, 7, 9, 100, 101}:
            state = "risk_review" if code == 7 else "restricted"
            label, reason = account_status_label(code), "Revisa el estado de la cuenta en Meta."
            tone, blocks = ("error" if code == 2 else "warn"), True
        elif type(observation.disable_reason) is int and observation.disable_reason != 0:
            state, label, tone, reason, blocks = (
                "restricted",
                "Cuenta restringida",
                "error",
                disable_reason_label(observation.disable_reason),
                True,
            )
        elif observation.funding_present is False:
            state, label, reason, blocks = (
                "payment_required",
                "Revisa el método de pago",
                "Falta un método de pago verificado. Revísalo en Meta y actualiza el estado.",
                True,
            )
        elif code == 1 and observation.disable_reason == 0:
            if observation.funding_present is True and observation.pending_billing is False:
                state, label, tone, ready, blocks = "active", "Cuenta activa", "ok", True, False
                reason = "La cuenta está activa en Meta. Esto no garantiza que acepte un cargo."
            else:
                state, label = "payment_unverified", "Pagos por comprobar"
                reason = "No pudimos comprobar la información de pago. Revísala en Meta."
    if permission:
        state, label, tone, reason, ready, blocks = (
            "unavailable",
            "Sin comprobar",
            "warn",
            permission,
            False,
            True,
        )
    elif target.read_failed:
        ready = False
        blocks = True
        reason += " No pudimos actualizar la comprobación. Vuelve a intentarlo."
        state, label, tone = "unavailable", "Comprobación pendiente", "warn"
    if not fresh and not permission:
        state, label, reason = "stale", "Comprobación pendiente", UNAVAILABLE
    return AccountHealth(
        target.account_id,
        target.name,
        target.currency,
        state,
        label,
        tone,
        reason,
        ready,
        target.checked_at,
        not fresh,
        observation.funding_present if fresh and observation else None,
        account_status_label(observation.account_status if fresh and observation else None),
        disable_reason_label(observation.disable_reason if fresh and observation else None),
        observation.amount_spent_minor
        if fresh and observation and observation.money_units_verified
        else None,
        observation.spend_cap_minor
        if fresh and observation and observation.money_units_verified
        else None,
        "https://business.facebook.com/billing_hub/accounts?asset_id=" + target.meta_account_id,
        blocks,
        target.read_failed,
        "https://business.facebook.com/ads/manager/account_settings/?act=" + target.meta_account_id,
    )


def get_account_health(*, tenant_id: UUID, ad_account_id: UUID) -> AccountHealth:
    require_acting_member(tenant_id)
    return project_health(_target(tenant_id, ad_account_id))


def _save(target: HealthTarget, observation: HealthObservation | None) -> None:
    require_acting_member(target.tenant_id)
    with tenant_session(target.tenant_id) as session:
        current = _connection(session, target.connection.connection_id, lock=True)
        if current != target.connection or _permission_reason(current):
            raise AdAccountUnavailable("La conexión cambió. Actualiza las cuentas publicitarias.")
        params = {
            "id": target.account_id,
            "token": target.refresh_token,
            "now": datetime.now(UTC),
            "version": current.version,
            "selected": target.selected,
            "brand": current.brand_id,
            "aid": target.meta_account_id,
            "currency": target.currency,
        }
        condition = (
            "id=:id AND health_refresh_token=:token AND credential_version=:version "
            "AND selected=:selected AND available AND brand_id=:brand AND ad_account_id=:aid "
            "AND currency=:currency"
        )
        if observation is None:
            sql = "UPDATE ad_accounts SET health_read_failed=true WHERE " + condition
        else:
            if observation.currency != target.currency:
                raise AdAccountUnavailable(UNAVAILABLE)
            snapshot = asdict(observation) | {
                "source_id": f"act_{target.meta_account_id}",
                "api_version": MarketingSettings.from_env().api_version,
                "pipeline_version": PIPELINE_VERSION,
            }
            if set(snapshot) - SNAPSHOT_KEYS:
                raise AdAccountUnavailable(UNAVAILABLE)
            params["snapshot"] = json.dumps(snapshot)
            sql = (
                "UPDATE ad_accounts SET health_snapshot=CAST(:snapshot AS jsonb), "
                "health_checked_at=:now,health_credential_version=:version,"
                "health_read_failed=false "
                "WHERE " + condition
            )
        if session.execute(text(sql), params).rowcount != 1:
            raise AdAccountUnavailable("La cuenta cambió durante la comprobación. Actualízala.")


async def refresh_account_health(
    *,
    tenant_id: UUID,
    ad_account_id: UUID,
    force: bool = False,
    reader: HealthReader | None = None,
) -> AccountHealth:
    require_acting_member(tenant_id)
    previous = get_account_health(tenant_id=tenant_id, ad_account_id=ad_account_id)
    if not force and not previous.stale and not previous.refresh_error:
        return previous
    try:
        target = _target(tenant_id, ad_account_id, claim=True)
    except AdAccountUnavailable:
        # Cached permission reasons are safe; never convert a missing grant into a fake.
        return get_account_health(tenant_id=tenant_id, ad_account_id=ad_account_id)
    client = None
    observation = None
    try:
        if reader is None:
            client = await _authenticated_client(
                tenant_id,
                target.connection.connection_id,
                expected_version=target.connection.version,
            )
            reader = GraphAccountHealthReader(client)
        observation = await reader.read(target)
    except AdAccountUnavailable:
        pass
    finally:
        if client is not None and hasattr(client, "aclose"):
            await client.aclose()
    _save(target, observation)
    return get_account_health(tenant_id=tenant_id, ad_account_id=ad_account_id)


async def refresh_daily_account_health(*, tenant_id: UUID) -> tuple[AccountHealth, ...]:
    """A tenant-scoped daily tick; only reads Meta and updates sanitized observations."""
    require_acting_member(tenant_id)
    with tenant_session(tenant_id) as session:
        ids = session.scalars(text("SELECT id FROM ad_accounts WHERE selected AND available")).all()
    results = []
    for account_id in ids:
        try:
            results.append(
                await refresh_account_health(tenant_id=tenant_id, ad_account_id=account_id)
            )
        except AdAccountUnavailable:
            continue
    return tuple(results)


__all__ = [
    "AccountHealth",
    "GraphAccountHealthReader",
    "get_account_health",
    "refresh_account_health",
    "refresh_daily_account_health",
]

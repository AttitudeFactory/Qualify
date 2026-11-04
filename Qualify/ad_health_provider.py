"""Whitelist the account-health service response before it enters Reflex state."""

from __future__ import annotations

import asyncio
from uuid import UUID

from qualify_api.ads.account_health import AccountHealth, get_account_health, refresh_account_health
from qualify_api.connections.ad_accounts import AdAccountUnavailable
from qualify_api.tenancy.acting import current_acting_login

from .ad_health_vm import AccountHealthVM, checked_label, safe_billing_url


def project_health(health: AccountHealth, timezone_name: str = "") -> AccountHealthVM:
    return AccountHealthVM(
        status=health.status,
        label=health.label,
        tone=health.tone if health.tone in {"ok", "warn", "error"} else "warn",
        reason=health.reason,
        checked_label=checked_label(health.checked_at, timezone_name),
        stale=health.stale,
        can_promote=health.can_promote and not health.stale and not health.refresh_error,
        blocks_preparation=health.blocks_preparation,
        account_status_label=health.account_status_label,
        disable_reason_label=health.disable_reason_label,
        amount_spent_label=health.amount_spent_label
        if health.amount_spent_minor is not None
        else "",
        spend_cap_label=health.spend_cap_label if health.spend_cap_minor is not None else "",
        billing_url=safe_billing_url(health.billing_url),
        action_url=safe_billing_url(health.action_url),
        action_label=health.action_label + " en Meta" if health.action_label else "",
        refresh_failed=bool(getattr(health, "refresh_error", False)),
    )


def account_health_for(
    tenant_id: UUID, account_id: UUID, timezone_name: str = ""
) -> AccountHealthVM:
    return project_health(
        get_account_health(tenant_id=tenant_id, ad_account_id=account_id), timezone_name
    )


def refresh_health(tenant_id: UUID, account_id: UUID, timezone_name: str = "") -> AccountHealthVM:
    if current_acting_login() is None:
        raise AdAccountUnavailable("Vuelve a iniciar sesión para comprobar el estado con Meta.")
    return project_health(
        asyncio.run(
            refresh_account_health(tenant_id=tenant_id, ad_account_id=account_id, force=True)
        ),
        timezone_name,
    )


def daily_health_for(tenant_id: UUID, account_id: UUID, timezone_name: str = "") -> AccountHealthVM:
    """Refresh an expired daily observation when the owner opens Conexiones."""
    if current_acting_login() is None:
        raise AdAccountUnavailable("Vuelve a iniciar sesión para comprobar el estado con Meta.")
    return project_health(
        asyncio.run(
            refresh_account_health(tenant_id=tenant_id, ad_account_id=account_id, force=False)
        ),
        timezone_name,
    )

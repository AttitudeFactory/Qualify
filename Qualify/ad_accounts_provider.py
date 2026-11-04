"""Safe advertising-account reads and delegated writes for the connections screen."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import UUID

from qualify_api.connections import start_connect
from qualify_api.connections.ad_accounts import (
    ad_account_availability,
    assign_ad_brand,
    list_ad_accounts,
    list_ad_brands,
    refresh_ad_accounts,
    select_ad_account,
)
from qualify_api.connections.state_token import StartedConnect

from .ad_accounts_vm import AdAccountsVM, AdAccountVM, AdBrandVM, account_status
from .capabilities import Capability
from .connections_vm import CapabilityVM, ConnectionVM


def ad_accounts_for(tenant_id: UUID, connection_id: UUID) -> AdAccountsVM:
    """Only display fields cross this boundary; no ORM row or authorization material."""
    accounts = list_ad_accounts(tenant_id=tenant_id, connection_id=connection_id)
    availability = ad_account_availability(tenant_id=tenant_id, connection_id=connection_id)
    rows = []
    for account in accounts:
        label, tone = account_status(account.account_status)
        rows.append(
            AdAccountVM(
                id=str(account.id),
                name=account.name or "Tu cuenta publicitaria",
                reference=f"Cuenta {account.ad_account_id}",
                currency=account.currency or "Moneda por comprobar",
                timezone=account.timezone_name or "Zona horaria por comprobar",
                status_label=label,
                status_tone=tone,
                selected=account.selected,
            )
        )
    return AdAccountsVM(
        accounts=rows,
        enabled=availability.enabled,
        reason=availability.reason,
        selected_name=next((row.name for row in rows if row.selected), ""),
        brand_id=str(availability.brand_id) if availability.brand_id else "",
        brands=[
            AdBrandVM(str(brand.id), brand.name) for brand in list_ad_brands(tenant_id=tenant_id)
        ]
        if availability.brand_id is None
        else [],
    )


def with_ad_accounts(connection: ConnectionVM, panel: AdAccountsVM) -> ConnectionVM:
    """The displayed capability requires the usable account, beyond the OAuth grant."""
    enabled = [
        cap for cap in connection.enabled_capabilities if cap.key != str(Capability.ADVERTISE)
    ]
    disabled = [
        cap for cap in connection.disabled_capabilities if cap.key != str(Capability.ADVERTISE)
    ]
    original = next(
        (
            cap
            for cap in connection.enabled_capabilities + connection.disabled_capabilities
            if cap.key == str(Capability.ADVERTISE)
        ),
        None,
    )
    verdict = CapabilityVM(
        key=str(Capability.ADVERTISE),
        label="Anunciar",
        enabled=panel.enabled,
        reason="" if panel.enabled else panel.reason,
        provisional=original.provisional if original is not None else False,
    )
    (enabled if panel.enabled else disabled).append(verdict)
    return replace(
        connection,
        ad_accounts=panel,
        enabled_capabilities=enabled,
        disabled_capabilities=disabled,
        has_provisional_capabilities=any(cap.provisional for cap in enabled),
    )


def refresh_accounts(tenant_id: UUID, connection_id: UUID) -> None:
    """Run on a worker thread: the async seam also performs synchronous DB work."""
    asyncio.run(refresh_ad_accounts(tenant_id=tenant_id, connection_id=connection_id))


def choose_account(tenant_id: UUID, connection_id: UUID, account_id: UUID) -> None:
    select_ad_account(tenant_id=tenant_id, connection_id=connection_id, ad_account_id=account_id)


def choose_brand(tenant_id: UUID, connection_id: UUID, brand_id: UUID) -> None:
    assign_ad_brand(tenant_id=tenant_id, connection_id=connection_id, brand_id=brand_id)


def begin_ads_connect(tenant_id: UUID, connection_id: UUID, user_id: UUID) -> StartedConnect:
    """Optional, account-specific consent, attributed to the authenticated user."""
    return start_connect(
        tenant_id=tenant_id,
        brand_id=None,
        user_id=user_id,
        connection_id=connection_id,
        request_ads=True,
        rerequest=True,
    )

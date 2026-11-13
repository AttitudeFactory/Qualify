"""Ad-account webhooks as a signal for an authenticated status read (m-24828979, ADS-09).

Meta notifies an app subscribed to an ad account (`act_<id>/subscribed_apps`) under
`object = "ad_account"`. The fields used here are `with_issues_ad_objects` (an ad, ad
set or campaign has issues, e.g. it was rejected) and `in_process_ad_objects` (it left or
entered processing, so its effective status changed). Their `value` carries the object
`id` (and `level`); nothing else in it is trusted or stored beyond the intake's own row.

The notification is a TRIGGER, never authority (docs/anuncios-estado-resultados.md):

- the owners are the ones frozen at intake by `admit_meta_webhook` (migration 0154) —
  the selected, available ad account of a live connection — never a tenant named by Meta;
- under each owner's RLS session only that tenant's promotions on that ad account whose
  ad, ad set or campaign id equals `value.id` are taken;
- each is refreshed by the same authenticated read as the 25-min poller
  (`results_service.refresh_promotion_from_signal`): ownership chain, effective status,
  sanitized `issues_info` reason («Rechazado por Meta» + «Motivo informado por Meta»).

Idempotent: a replay only re-reads Meta and rewrites the same observation. A failed read
raises, so the queue retries with its backoff (and the poller remains the fallback).

`subscribe_ad_account_webhooks` is the explicit, assisted subscription: only on the
owner's confirmed action, never automatic, like `subscribe_lead_form`.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.client import MarketingClient
from qualify_api.ads.errors import MarketingError
from qualify_api.ads.results import ResultsUnavailable
from qualify_api.connections.ad_accounts import (
    AdAccountUnavailable,
    _authenticated_client,
    _connection,
    _permission_reason,
)
from qualify_api.tenancy.acting import current_acting_login, require_acting_member
from qualify_api.webhooks.processor import Handler, Outcome, _sent_at, handler_key
from qualify_api.webhooks.repository import (
    STATUS_DEAD,
    STATUS_ORPHAN,
    STATUS_PROCESSED,
    STATUS_UNSUPPORTED,
    ClaimedEvent,
)

AD_ACCOUNT_OBJECT = "ad_account"
STATUS_FIELDS = ("with_issues_ad_objects", "in_process_ad_objects")
NOT_A_PROMOTION = "ad_object_not_a_promotion"
SUBSCRIBE_FAILED = "No pudimos activar los avisos de Meta para esta cuenta. Inténtalo de nuevo."
# What the future screen offers the owner before calling `subscribe_ad_account_webhooks`.
SUBSCRIBE_OFFER = "Activa los avisos para enterarte aquí si Meta rechaza o detiene tu anuncio."
FRESH_WINDOW = timedelta(seconds=60)
RECENTLY_READ = "recently_read"

Refresh = Callable[[UUID, UUID], Awaitable[Any]]
_DIGITS = re.compile(r"[0-9]{1,64}")


def _meta_id(value: Any) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    return value if isinstance(value, str) and _DIGITS.fullmatch(value) else None


def owned_promotions(event: ClaimedEvent, object_id: str) -> list[tuple[UUID, UUID]]:
    """(tenant, promotion) pairs for the frozen owners only, each read under its own RLS."""
    account = event.entry_id.removeprefix("act_")
    found: set[tuple[UUID, UUID]] = set()
    for tenant_id, connection_id in set(event.owners or ()):
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                text("""SELECT p.id FROM ad_promotions p JOIN ad_accounts a
                  ON a.tenant_id=p.tenant_id AND a.ad_account_id=p.meta_ad_account_id
                  AND a.connection_id=:cid AND a.selected AND a.available
                  WHERE p.meta_ad_account_id=:account
                    AND :object IN (p.meta_ad_id,p.meta_adset_id,p.meta_campaign_id)"""),
                {"cid": connection_id, "account": account, "object": object_id},
            ).all()
        found.update((tenant_id, promotion_id) for promotion_id in rows)
    return sorted(found)


def read_since(tenant_id: UUID, promotion_id: UUID, since: datetime) -> bool:
    """True when a successful status read of this promotion started at or after `since`."""
    with tenant_session(tenant_id) as session:
        return bool(
            session.scalar(
                text("""SELECT EXISTS(SELECT 1 FROM ad_promotion_observations
                  WHERE promotion_id=:id AND checked_at >= :since)"""),
                {"id": promotion_id, "since": since},
            )
        )


def ad_status_handler(*, refresh: Refresh | None = None) -> Handler:
    async def handle(event: ClaimedEvent) -> Outcome:
        if (
            event.object != AD_ACCOUNT_OBJECT
            or event.field not in STATUS_FIELDS
            or not isinstance(event.value, dict)
            or _meta_id(event.entry_id.removeprefix("act_")) is None
        ):
            return Outcome(STATUS_DEAD, "ad_status_contract")
        object_id = _meta_id(event.value.get("id"))
        if object_id is None:
            return Outcome(STATUS_DEAD, "ad_status_contract")
        if not event.owners:
            return Outcome(STATUS_ORPHAN)
        targets = owned_promotions(event, object_id)
        if not targets:
            # An ad of this account that Qualify did not create: kept, never read.
            return Outcome(STATUS_UNSUPPORTED, NOT_A_PROMOTION)
        do_refresh = refresh
        if do_refresh is None:
            from qualify_api.ads.results_service import refresh_promotion_from_signal

            async def do_refresh(tenant: UUID, promotion: UUID) -> Any:
                return await refresh_promotion_from_signal(tenant_id=tenant, promotion_id=promotion)

        # One review fires several notifications (both fields x ad/adset/campaign): a read
        # started after Meta sent this one, within the last minute, already reflects it.
        now = datetime.now(UTC)
        sent = _sent_at(event.entry_time)
        # shortcut: trusts our clock against Meta's (NTP keeps skew <1 s); a skewed miss
        # waits for the poller, add a margin only if rejections are seen arriving late.
        since = max(sent, now - FRESH_WINDOW) if sent is not None else now - FRESH_WINDOW
        refreshed = 0
        for tenant_id, promotion_id in targets:
            if read_since(tenant_id, promotion_id, since):
                continue
            # Raises on a failed read: the queue retries with backoff.
            await do_refresh(tenant_id, promotion_id)
            refreshed += 1
        return Outcome(STATUS_PROCESSED, None if refreshed else RECENTLY_READ)

    return handle


def production_ad_status_handlers() -> dict[str, Handler]:
    handler = ad_status_handler()
    return {handler_key(AD_ACCOUNT_OBJECT, field): handler for field in STATUS_FIELDS}


async def subscribe_ad_account_webhooks(
    *,
    tenant_id: UUID,
    ad_account_id: UUID,
    confirmed: bool,
    client_factory: Callable[[UUID, UUID, int], Awaitable[Any]] | None = None,
    app_id: str | None = None,
) -> bool:
    """Owner-confirmed `POST act_<id>/subscribed_apps` for Qualify's app. Returns False
    when the app was already subscribed (nothing written). Never retried on ambiguity."""
    if current_acting_login() is None:
        raise ResultsUnavailable("Vuelve a entrar para revisar tus anuncios.")
    require_acting_member(tenant_id)
    if confirmed is not True:
        raise ResultsUnavailable("Confirma que quieres recibir los avisos de Meta de esta cuenta.")

    def guard() -> tuple[str, UUID, int]:
        require_acting_member(tenant_id)
        with tenant_session(tenant_id, independent=True) as session:
            row = (
                session.execute(
                    text("""SELECT ad_account_id,connection_id,credential_version
                    FROM ad_accounts WHERE id=:id AND selected AND available"""),
                    {"id": ad_account_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ResultsUnavailable("Elige primero la cuenta publicitaria de esta marca.")
            connection = _connection(session, row["connection_id"])
        if _permission_reason(connection) or connection.version != row["credential_version"]:
            raise ResultsUnavailable("Autoriza los anuncios de nuevo para activar los avisos.")
        return row["ad_account_id"], row["connection_id"], row["credential_version"]

    account, connection_id, version = guard()
    if app_id is None:
        from qualify_api.config import MetaOAuthSettings

        app_id = MetaOAuthSettings.from_env().app_id
    try:
        if client_factory is not None:
            api = await client_factory(tenant_id, connection_id, version)
        else:
            api = MarketingClient(
                client=await _authenticated_client(
                    tenant_id, connection_id, expected_version=version
                ),
                account_id=account,
            )
    except AdAccountUnavailable as exc:
        raise ResultsUnavailable(str(exc)) from None
    try:
        page = await api.subscribed_apps()
        if any(str(row.get("app_id", "")) == app_id for row in page.data):
            return False

        def before_write() -> None:
            # Membership, selection and credential may change while reading.
            if guard() != (account, connection_id, version):
                raise ResultsUnavailable(
                    "Cambiaste la cuenta de anuncios mientras guardábamos. "
                    "Ábrela de nuevo y vuelve a intentarlo."
                )

        await api.subscribe_app(app_id, before_write=before_write)
        return True
    except MarketingError:
        raise ResultsUnavailable(SUBSCRIBE_FAILED) from None
    finally:
        if hasattr(api, "aclose"):
            await api.aclose()

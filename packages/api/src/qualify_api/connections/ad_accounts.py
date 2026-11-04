"""Optional advertising account selection; safe UI seam and promotion authorization.

All Meta calls here are reads. Page tokens are never used for advertising.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

import httpx
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.client import MarketingClient, MarketingSettings
from qualify_api.ads.promotions import AccountAccess
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.resolver import AuthenticatedClient, InjectingCredentialResolver
from qualify_api.tenancy.acting import require_acting_member

PIPELINE_VERSION = "ad-accounts-v1"
MAX_SNAPSHOT_AGE = timedelta(minutes=15)
UNAVAILABLE = "No pudimos consultar tus cuentas publicitarias. Vuelve a intentarlo."


class AdAccountUnavailable(ValueError):
    """A safe, client-readable reason; never includes platform response material."""


def require_ads_member(tenant_id: UUID, user_id: UUID) -> None:
    """Recheck the signed tenant-local OAuth actor, also on the callback without a session."""
    with tenant_session(tenant_id) as session:
        present = session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM tenant_members WHERE tenant_id=:tid AND user_id=:uid)"
            ),
            {"tid": tenant_id, "uid": user_id},
        )
    if not present:
        raise AdAccountUnavailable("Ya no tienes acceso a este negocio. Vuelve a entrar.")


@dataclass(frozen=True)
class AdAccountSummary:
    id: UUID
    connection_id: UUID
    brand_id: UUID | None
    ad_account_id: str
    name: str
    currency: str
    timezone_name: str
    account_status: int | None
    disable_reason: int | None
    has_funding_source: bool | None
    instagram_assigned: bool | None
    business_id: str | None
    last_checked_at: datetime
    selected: bool


@dataclass(frozen=True)
class AdAccountAvailability:
    enabled: bool
    reason: str
    selected_account_id: UUID | None = None
    brand_id: UUID | None = None


@dataclass(frozen=True)
class AdBrandSummary:
    id: UUID
    name: str


def list_ad_brands(*, tenant_id: UUID) -> tuple[AdBrandSummary, ...]:
    with tenant_session(tenant_id) as session:
        rows = session.execute(text("SELECT id,name FROM brands ORDER BY name,id")).all()
        return tuple(AdBrandSummary(row.id, row.name) for row in rows)


def assign_ad_brand(*, tenant_id: UUID, connection_id: UUID, brand_id: UUID) -> None:
    """Explicitly assign a previously unbranded connection; never reassign an existing brand."""
    require_acting_member(tenant_id)
    with tenant_session(tenant_id) as session:
        brand = session.scalar(
            text("SELECT id FROM brands WHERE id=:bid FOR UPDATE"), {"bid": brand_id}
        )
        if brand is None:
            raise AdAccountUnavailable("Esta marca no está disponible en tu negocio.")
        connection = _connection(session, connection_id, lock=True)
        if connection.brand_id is not None:
            if connection.brand_id == brand_id:
                return
            raise AdAccountUnavailable("Esta conexión ya pertenece a otra marca.")
        session.execute(
            text("UPDATE ad_accounts SET selected=false,available=false WHERE connection_id=:cid"),
            {"cid": connection_id},
        )
        session.execute(
            text("UPDATE social_connections SET brand_id=:bid WHERE id=:cid"),
            {"bid": brand_id, "cid": connection_id},
        )


@dataclass(frozen=True)
class AdAccountObservation:
    ad_account_id: str
    name: str
    currency: str
    timezone_name: str
    account_status: int | None
    disable_reason: int | None
    has_funding_source: bool | None
    instagram_assigned: bool | None
    business_id: str | None


@dataclass(frozen=True)
class AdConnection:
    connection_id: UUID
    brand_id: UUID | None
    external_account_id: str
    version: int
    status: str
    scopes: tuple[str, ...]
    expires_at: datetime | None
    has_grant: bool


def _connection(session: Any, connection_id: UUID, *, lock: bool = False) -> AdConnection:
    row = session.execute(
        text(
            """SELECT c.id,c.brand_id,c.external_account_id,c.current_credential_version,
            c.status,g.granted_scopes,g.expires_at,g.version AS grant_version
            FROM social_connections c LEFT JOIN ad_oauth_credentials g
              ON g.connection_id=c.id AND g.tenant_id=c.tenant_id
                AND g.version=c.current_credential_version
            WHERE c.id=:cid AND c.platform='instagram' AND c.purged_at IS NULL
              AND c.purge_started_at IS NULL"""
            + (" FOR UPDATE OF c" if lock else "")
        ),
        {"cid": connection_id},
    ).first()
    if row is None:
        raise AdAccountUnavailable("Esta conexión ya no está disponible. Vuelve a conectarla.")
    return AdConnection(
        row.id,
        row.brand_id,
        row.external_account_id,
        row.current_credential_version,
        row.status,
        tuple(row.granted_scopes or ()),
        row.expires_at,
        row.grant_version is not None,
    )


def _permission_reason(connection: AdConnection, now: datetime | None = None) -> str:
    if connection.status != "active":
        return "Vuelve a conectar Instagram para anunciar con este negocio."
    if not connection.has_grant or "ads_management" not in connection.scopes:
        return "Falta el permiso para anunciar. Autoriza los anuncios para continuar."
    if connection.expires_at is not None and connection.expires_at <= (now or datetime.now(UTC)):
        return "El permiso para anunciar venció. Autoriza los anuncios de nuevo."
    if connection.brand_id is None:
        return "Asocia esta conexión a una marca antes de elegir una cuenta publicitaria."
    return ""


def account_block_reason(account: AdAccountSummary, now: datetime | None = None) -> str:
    if account.last_checked_at < (now or datetime.now(UTC)) - MAX_SNAPSHOT_AGE:
        return "Actualiza las cuentas publicitarias para comprobar su estado."
    if account.account_status is None or account.disable_reason is None:
        return "No pudimos comprobar el estado de la cuenta publicitaria. Actualiza las cuentas."
    if account.account_status != 1 or account.disable_reason != 0:
        return "La cuenta publicitaria no está activa. Revisa su estado en Meta."
    if account.instagram_assigned is None:
        return "No pudimos comprobar la asignación de Instagram. Actualiza las cuentas."
    if account.instagram_assigned is False:
        return "Asigna esta cuenta de Instagram a la cuenta publicitaria en Meta y actualiza."
    # Presence is an observation, not a complete billing-health check (m-24828978).
    if account.has_funding_source is None:
        return "No pudimos comprobar el método de pago. Actualiza las cuentas publicitarias."
    if account.has_funding_source is False:
        return "Revisa el método de pago de la cuenta publicitaria en Meta y actualiza."
    return ""


def _summary(row: Any) -> AdAccountSummary:
    return AdAccountSummary(
        **{key: getattr(row, key) for key in AdAccountSummary.__dataclass_fields__}
    )


_SUMMARY_COLUMNS = ",".join("a." + key for key in AdAccountSummary.__dataclass_fields__)


def list_ad_accounts(*, tenant_id: UUID, connection_id: UUID) -> tuple[AdAccountSummary, ...]:
    with tenant_session(tenant_id) as session:
        connection = _connection(session, connection_id)
        rows = session.execute(
            text(
                f"SELECT {_SUMMARY_COLUMNS} FROM ad_accounts a WHERE a.connection_id=:cid "
                "AND a.credential_version=:version AND a.available ORDER BY a.name,a.id"
            ),
            {"cid": connection_id, "version": connection.version},
        ).all()
        return tuple(_summary(row) for row in rows)


def ad_account_availability(*, tenant_id: UUID, connection_id: UUID) -> AdAccountAvailability:
    with tenant_session(tenant_id) as session:
        connection = _connection(session, connection_id)
    reason = _permission_reason(connection)
    if reason:
        return AdAccountAvailability(False, reason, brand_id=connection.brand_id)
    accounts = list_ad_accounts(tenant_id=tenant_id, connection_id=connection_id)
    if not accounts:
        return AdAccountAvailability(
            False,
            "No hay cuentas publicitarias en la lista. "
            "Pulsa «Actualizar cuentas» para consultarlas con Meta.",
            brand_id=connection.brand_id,
        )
    selected = next(
        (a for a in accounts if a.selected and a.brand_id == connection.brand_id),
        None,
    )
    if selected is None:
        return AdAccountAvailability(
            False,
            "Elige la cuenta publicitaria que usará esta marca.",
            brand_id=connection.brand_id,
        )
    reason = account_block_reason(selected)
    return AdAccountAvailability(
        not reason,
        reason or "Cuenta publicitaria lista para anunciar.",
        selected.id,
        connection.brand_id,
    )


class PostgresAdsGrantRecorder:
    def record(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        version: int,
        ciphertext: bytes,
        key_id: str,
        granted_scopes: tuple[str, ...],
        expires_at: datetime | None,
    ) -> None:
        with tenant_session(tenant_id) as session:
            # Match the grant just committed by OAuth, not a newer concurrent reconnect.
            connection = _connection(session, connection_id, lock=True)
            if connection.version != version:
                raise AdAccountUnavailable("La conexión cambió. Autoriza los anuncios de nuevo.")
            session.execute(
                text("""INSERT INTO ad_oauth_credentials
                (tenant_id,connection_id,version,ciphertext,key_id,granted_scopes,expires_at)
                VALUES (:tid,:cid,:version,:ciphertext,:key,:scopes,:expiry)
                ON CONFLICT (connection_id,version) DO NOTHING"""),
                {
                    "tid": tenant_id,
                    "cid": connection_id,
                    "version": version,
                    "ciphertext": ciphertext,
                    "key": key_id,
                    "scopes": list(granted_scopes),
                    "expiry": expires_at,
                },
            )


class AdAccountReader(Protocol):
    async def list_accounts(self, instagram_id: str) -> tuple[AdAccountObservation, ...]: ...


class GraphAdAccountReader:
    def __init__(
        self, client: AuthenticatedClient, settings: MarketingSettings | None = None
    ) -> None:
        self.client = client
        self.settings = settings or MarketingSettings.from_env()

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        failed = False
        try:
            response = await self.client.get(
                self.settings.graph_url + path, params=params, follow_redirects=False, timeout=30
            )
            if response.status_code != 200:
                failed = True
            else:
                payload = response.json()
                if isinstance(payload, dict) and "error" not in payload:
                    return payload
                failed = True
        except (httpx.HTTPError, ValueError):
            failed = True
        if failed:
            raise AdAccountUnavailable(UNAVAILABLE)
        raise AdAccountUnavailable(UNAVAILABLE)

    async def _all(self, path: str, fields: str) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        params = {"fields": fields, "limit": "100"}
        for _ in range(100):
            payload = await self._get(path, params)
            data = payload.get("data")
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise AdAccountUnavailable(UNAVAILABLE)
            rows.extend(data)
            paging = payload.get("paging") or {}
            if not isinstance(paging, dict):
                raise AdAccountUnavailable(UNAVAILABLE)
            if not paging.get("next"):
                return tuple(rows)
            cursors = paging.get("cursors") or {}
            after = cursors.get("after") if isinstance(cursors, dict) else None
            if not isinstance(after, str) or not after or after in seen:
                raise AdAccountUnavailable(UNAVAILABLE)
            seen.add(after)
            # Rebuild trusted path; never follow token-bearing/untrusted next URLs.
            params["after"] = after
        raise AdAccountUnavailable(UNAVAILABLE)

    async def list_accounts(self, instagram_id: str) -> tuple[AdAccountObservation, ...]:
        rows = await self._all(
            "/me/adaccounts",
            "account_id,name,currency,timezone_name,"
            "account_status,disable_reason,funding_source,business",
        )
        accounts = []
        for row in rows:
            account_id = str(row.get("account_id") or "")
            currency = str(row.get("currency") or "")
            if not re.fullmatch(r"[0-9]+", account_id) or not re.fullmatch(r"[A-Z]{3}", currency):
                raise AdAccountUnavailable(UNAVAILABLE)
            ig_rows = await self._all(f"/act_{account_id}/connected_instagram_accounts", "id")
            if any(not isinstance(item.get("id"), str) or not item["id"] for item in ig_rows):
                raise AdAccountUnavailable(UNAVAILABLE)
            business = row.get("business")
            funding = row.get("funding_source")
            funding_present = (
                int(str(funding)) > 0
                if isinstance(funding, (str, int)) and re.fullmatch(r"[0-9]+", str(funding))
                else None
            )
            accounts.append(
                AdAccountObservation(
                    account_id,
                    str(row.get("name") or "Cuenta publicitaria"),
                    currency,
                    str(row.get("timezone_name") or ""),
                    row.get("account_status") if type(row.get("account_status")) is int else None,
                    row.get("disable_reason") if type(row.get("disable_reason")) is int else None,
                    funding_present,
                    any(item["id"] == instagram_id for item in ig_rows),
                    str(business["id"])
                    if isinstance(business, dict) and business.get("id")
                    else None,
                )
            )
        if len({item.ad_account_id for item in accounts}) != len(accounts):
            raise AdAccountUnavailable(UNAVAILABLE)
        return tuple(accounts)


def _persist_observations(
    tenant_id: UUID,
    original: AdConnection,
    observations: tuple[AdAccountObservation, ...],
    *,
    now: datetime,
    api_version: str,
) -> None:
    with tenant_session(tenant_id) as session:
        current = _connection(session, original.connection_id, lock=True)
        if current != original or _permission_reason(current):
            raise AdAccountUnavailable("La conexión cambió. Autoriza los anuncios de nuevo.")
        session.execute(
            text(
                "UPDATE ad_accounts SET available=false,selected=false "
                "WHERE connection_id=:cid AND ad_account_id != ALL(:ids)"
            ),
            {"cid": current.connection_id, "ids": [a.ad_account_id for a in observations]},
        )
        for account in observations:
            values = account.__dict__ | {
                "tid": tenant_id,
                "cid": current.connection_id,
                "brand": current.brand_id,
                "version": current.version,
                "now": now,
                "api": api_version,
                "pipeline": PIPELINE_VERSION,
                "source": f"act_{account.ad_account_id}",
            }
            session.execute(
                text("""INSERT INTO ad_accounts
                (tenant_id,connection_id,brand_id,ad_account_id,name,currency,timezone_name,
                 account_status,disable_reason,has_funding_source,instagram_assigned,business_id,
                 last_checked_at,credential_version,source_id,api_version,pipeline_version)
                VALUES (:tid,:cid,:brand,:ad_account_id,:name,:currency,:timezone_name,
                 :account_status,:disable_reason,:has_funding_source,:instagram_assigned,:business_id,
                 :now,:version,:source,:api,:pipeline)
                ON CONFLICT (connection_id,ad_account_id) DO UPDATE SET
                 name=EXCLUDED.name,currency=EXCLUDED.currency,timezone_name=EXCLUDED.timezone_name,
                 account_status=EXCLUDED.account_status,disable_reason=EXCLUDED.disable_reason,
                 has_funding_source=EXCLUDED.has_funding_source,
                 instagram_assigned=EXCLUDED.instagram_assigned,business_id=EXCLUDED.business_id,
                 last_checked_at=EXCLUDED.last_checked_at,
                 selected=ad_accounts.selected AND ad_accounts.brand_id IS NOT DISTINCT FROM
                    EXCLUDED.brand_id
                    AND ad_accounts.credential_version=EXCLUDED.credential_version,
                 brand_id=EXCLUDED.brand_id,credential_version=EXCLUDED.credential_version,
                 available=true,source_id=EXCLUDED.source_id,api_version=EXCLUDED.api_version,
                 pipeline_version=EXCLUDED.pipeline_version"""),
                values,
            )


async def _authenticated_client(
    tenant_id: UUID, connection_id: UUID, *, expected_version: int
) -> AuthenticatedClient:
    from qualify_api.config import MetaOAuthSettings
    from qualify_api.connections.credential_reader import CredentialNotFound, DbAdCredentialReader

    try:
        return await InjectingCredentialResolver(
            DbAdCredentialReader(tenant_id, expected_version=expected_version), DevEncryptor()
        ).client_for(connection_id, scheme=MetaOAuthSettings.from_env().graph_auth_scheme)
    except CredentialNotFound:
        raise AdAccountUnavailable("Autoriza los anuncios de nuevo para continuar.") from None


async def refresh_ad_accounts(
    *, tenant_id: UUID, connection_id: UUID
) -> tuple[AdAccountSummary, ...]:
    require_acting_member(tenant_id)
    with tenant_session(tenant_id) as session:
        connection = _connection(session, connection_id)
    reason = _permission_reason(connection)
    if reason:
        raise AdAccountUnavailable(reason)
    client = await _authenticated_client(
        tenant_id, connection_id, expected_version=connection.version
    )
    try:
        settings = MarketingSettings.from_env()
        observations = await GraphAdAccountReader(client, settings).list_accounts(
            connection.external_account_id
        )
    finally:
        if hasattr(client, "aclose"):
            await client.aclose()
    require_acting_member(tenant_id)
    _persist_observations(
        tenant_id, connection, observations, now=datetime.now(UTC), api_version=settings.api_version
    )
    return list_ad_accounts(tenant_id=tenant_id, connection_id=connection_id)


def select_ad_account(*, tenant_id: UUID, connection_id: UUID, ad_account_id: UUID) -> None:
    require_acting_member(tenant_id)
    with tenant_session(tenant_id) as session:
        initial = _connection(session, connection_id)
        if initial.brand_id is None:
            raise AdAccountUnavailable(
                "Asocia esta conexión a una marca antes de elegir una cuenta."
            )
        # Serialize choices across ALL connections of this brand, before clearing the old choice.
        session.execute(
            text("SELECT id FROM brands WHERE id=:bid FOR UPDATE"), {"bid": initial.brand_id}
        ).one()
        connection = _connection(session, connection_id, lock=True)
        reason = _permission_reason(connection)
        if reason or connection.brand_id != initial.brand_id:
            raise AdAccountUnavailable(reason or "La conexión cambió. Actualiza las cuentas.")
        account = session.execute(
            text(
                f"SELECT {_SUMMARY_COLUMNS} FROM ad_accounts a "
                "WHERE a.id=:id AND a.connection_id=:cid AND a.brand_id=:bid "
                "AND a.credential_version=:version AND a.available FOR UPDATE"
            ),
            {
                "id": ad_account_id,
                "cid": connection_id,
                "bid": connection.brand_id,
                "version": connection.version,
            },
        ).first()
        if account is None:
            raise AdAccountUnavailable("Esta cuenta ya no está disponible. Actualiza las cuentas.")
        session.execute(
            text("UPDATE ad_accounts SET selected=false WHERE brand_id=:bid AND selected"),
            {"bid": connection.brand_id},
        )
        session.execute(
            text("UPDATE ad_accounts SET selected=true WHERE id=:id"), {"id": ad_account_id}
        )


class PostgresAccountBinding:
    """Promotion boundary: selected brand + fresh verified snapshot + current user grant."""

    async def resolve(
        self, tenant_id: UUID, brand_id: UUID, meta_ad_account_id: str
    ) -> AccountAccess:
        require_acting_member(tenant_id)
        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(
                    "SELECT connection_id FROM ad_accounts WHERE brand_id=:bid "
                    "AND ad_account_id=:aid AND selected AND available"
                ),
                {"bid": brand_id, "aid": meta_ad_account_id},
            ).first()
        if row is None:
            raise AdAccountUnavailable("Elige una cuenta publicitaria para esta marca.")
        # A fresh read invalidates revoked access, removed assignments and disabled accounts.
        await refresh_ad_accounts(tenant_id=tenant_id, connection_id=row.connection_id)
        with tenant_session(tenant_id) as session:
            connection = _connection(session, row.connection_id)
            chosen = session.execute(
                text(
                    f"SELECT {_SUMMARY_COLUMNS} FROM ad_accounts a "
                    "WHERE a.connection_id=:cid AND a.brand_id=:bid AND a.ad_account_id=:aid "
                    "AND a.selected AND a.available AND a.credential_version=:version"
                ),
                {
                    "cid": row.connection_id,
                    "bid": brand_id,
                    "aid": meta_ad_account_id,
                    "version": connection.version,
                },
            ).first()
        reason = _permission_reason(connection)
        if reason or chosen is None or connection.brand_id != brand_id:
            raise AdAccountUnavailable(reason or "La cuenta elegida cambió. Actualiza las cuentas.")
        account = _summary(chosen)
        reason = account_block_reason(account)
        if reason:
            raise AdAccountUnavailable(reason)
        client = await _authenticated_client(
            tenant_id, row.connection_id, expected_version=connection.version
        )
        # The resolver must never silently swap a refreshed v1 selection to a v2 token.
        # Check again after decrypting. A later revocation cannot cancel an in-flight request.
        with tenant_session(tenant_id) as session:
            current = _connection(session, row.connection_id)
            still_selected = session.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM ad_accounts "
                    "WHERE id=:id AND selected AND available AND credential_version=:version "
                    "AND brand_id=:bid AND last_checked_at=:checked)"
                ),
                {
                    "id": account.id,
                    "version": connection.version,
                    "bid": brand_id,
                    "checked": account.last_checked_at,
                },
            )
        if current != connection or not still_selected:
            if hasattr(client, "aclose"):
                await client.aclose()
            raise AdAccountUnavailable("La conexión cambió. Autoriza los anuncios de nuevo.")
        return AccountAccess(
            tenant_id,
            brand_id,
            meta_ad_account_id,
            account.currency,
            MarketingClient(client=client, account_id=meta_ad_account_id),
        )

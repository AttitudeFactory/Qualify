"""Authenticated read-only discovery and local CAS persistence for one published source."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.audience import (
    AudienceDraft,
    AudienceUnavailable,
    InterestOption,
    LocationOption,
    ReachEstimate,
    SavedAudience,
)
from qualify_api.ads.client import MarketingAPI, MarketingClient
from qualify_api.ads.errors import MarketingError
from qualify_api.connections.ad_accounts import (
    AdAccountUnavailable,
    AdConnection,
    _authenticated_client,
    _connection,
    _permission_reason,
)
from qualify_api.tenancy.acting import current_acting_login, require_acting_member

PIPELINE_VERSION = "ad-audience-v1"


@dataclass(frozen=True)
class AudienceScope:
    tenant_id: UUID
    content_draft_id: UUID
    publish_attempt_id: UUID
    ad_account_id: UUID
    brand_id: UUID
    connection: AdConnection
    meta_account_id: str


def _scope(
    *, tenant_id: UUID, content_draft_id: UUID, publish_attempt_id: UUID, ad_account_id: UUID
) -> AudienceScope:
    if current_acting_login() is None:
        raise AudienceUnavailable("Vuelve a entrar para preparar el público.")
    require_acting_member(tenant_id)
    with tenant_session(tenant_id) as session:
        row = session.execute(
            text("""
            SELECT a.connection_id,a.brand_id,a.ad_account_id,a.credential_version
            FROM ad_accounts a JOIN social_connections c
              ON c.id=a.connection_id AND c.tenant_id=a.tenant_id
            JOIN content_drafts d ON d.brand_id=a.brand_id AND d.tenant_id=a.tenant_id
            JOIN calendar_events e ON e.post_id=d.id
              AND e.tenant_id=d.tenant_id AND e.brand_id=d.brand_id AND e.connection_id=c.id
            JOIN publish_attempts p ON p.id=e.publish_attempt_id AND p.tenant_id=e.tenant_id
              AND p.connection_id=c.id
            WHERE a.id=:account AND d.id=:draft AND p.id=:published
              AND a.selected AND a.available AND a.credential_version=c.current_credential_version
              AND c.brand_id=a.brand_id AND c.platform='instagram'
              AND e.status='published' AND p.status='published'
              AND p.published_media_id ~ '^[0-9]+$'
              AND p.media_product_type <> 'STORIES'
              AND (e.destination IS NULL OR e.destination <> 'story')
              AND c.purged_at IS NULL AND c.purge_started_at IS NULL
            """),
            {"account": ad_account_id, "draft": content_draft_id, "published": publish_attempt_id},
        ).first()
        if row is None:
            raise AudienceUnavailable(
                "La publicación o la cuenta cambió. Vuelve a abrir la promoción."
            )
        connection = _connection(session, row.connection_id)
        reason = _permission_reason(connection)
        if reason:
            raise AudienceUnavailable(reason)
        return AudienceScope(
            tenant_id,
            content_draft_id,
            publish_attempt_id,
            ad_account_id,
            row.brand_id,
            connection,
            row.ad_account_id,
        )


def _same(scope: AudienceScope) -> None:
    current = _scope(
        tenant_id=scope.tenant_id,
        content_draft_id=scope.content_draft_id,
        publish_attempt_id=scope.publish_attempt_id,
        ad_account_id=scope.ad_account_id,
    )
    if current != scope:
        raise AudienceUnavailable("La cuenta cambió durante la consulta. Vuelve a intentarlo.")


def _query(value: str) -> str:
    if (
        not isinstance(value, str)
        or not 2 <= len(value.strip()) <= 100
        or any(ord(c) < 32 for c in value)
    ):
        raise AudienceUnavailable("Escribe entre dos y cien letras para buscar.")
    return value.strip()


async def _read(
    scope: AudienceScope, operation: str, params: dict[str, Any], *, api: MarketingAPI | None = None
) -> tuple[dict[str, Any], ...]:
    client = None
    try:
        if api is None:
            client = await _authenticated_client(
                scope.tenant_id,
                scope.connection.connection_id,
                expected_version=scope.connection.version,
            )
            api = MarketingClient(client=client, account_id=scope.meta_account_id)
        _same(scope)
        if operation == "reach":
            page = await api.reachestimate(targeting_spec=params)
        elif operation == "validate":
            page = await api.audience_validation(interest_ids=tuple(params["ids"]))
        else:
            page = await api.audience_search(params=params)
        _same(scope)
        return page.data[:50]
    except (MarketingError, AdAccountUnavailable):
        raise AudienceUnavailable(
            "No pudimos consultar el público en Meta. Vuelve a intentarlo."
        ) from None
    finally:
        if client is not None and hasattr(client, "aclose"):
            await client.aclose()


def _locations(rows: tuple[dict[str, Any], ...], kind: str) -> tuple[LocationOption, ...]:
    result = []
    for row in rows:
        try:
            option = LocationOption(
                row["key"],
                row["name"],
                row["type"],
                row.get("country_code", row["key"] if kind == "country" else ""),
                row.get("region", ""),
            )
            option.validate()
        except (KeyError, TypeError, ValueError):
            continue
        if option.type == kind and option.key not in {item.key for item in result}:
            result.append(option)
    return tuple(result)


def _interests(rows: tuple[dict[str, Any], ...]) -> tuple[InterestOption, ...]:
    result = []
    for row in rows:
        try:
            option = InterestOption(row["id"], row["name"])
            option.validate()
        except (KeyError, TypeError, ValueError):
            continue
        if option.id not in {item.id for item in result}:
            result.append(option)
    return tuple(result)


async def _interest_status(
    scope: AudienceScope, options: tuple[InterestOption, ...]
) -> tuple[InterestOption, ...]:
    if not options:
        return ()
    try:
        rows = await _read(scope, "validate", {"ids": [option.id for option in options]})
    except AudienceUnavailable:
        # This is not evidence that an interest is available or retiring.
        _same(scope)
        return options
    statuses: dict[str, bool] = {}
    for row in rows:
        if isinstance(row.get("id"), str) and type(row.get("valid")) is bool:
            statuses[row["id"]] = row["valid"]
    return tuple(
        replace(
            option,
            status="active"
            if statuses.get(option.id) is True
            else "unavailable"
            if statuses.get(option.id) is False
            else "unknown",
        )
        for option in options
    )


async def search_audience_locations(
    *,
    tenant_id: UUID,
    content_draft_id: UUID,
    publish_attempt_id: UUID,
    ad_account_id: UUID,
    query: str,
    location_type: str,
) -> tuple[LocationOption, ...]:
    if location_type not in {"country", "region", "city"}:
        raise AudienceUnavailable("Elige buscar un país, una región o una ciudad.")
    scope = _scope(
        tenant_id=tenant_id,
        content_draft_id=content_draft_id,
        publish_attempt_id=publish_attempt_id,
        ad_account_id=ad_account_id,
    )
    return _locations(
        await _read(
            scope,
            "search",
            {
                "type": "adgeolocation",
                "q": _query(query),
                "location_types": [location_type],
                "limit": 25,
            },
        ),
        location_type,
    )


async def search_audience_interests(
    *,
    tenant_id: UUID,
    content_draft_id: UUID,
    publish_attempt_id: UUID,
    ad_account_id: UUID,
    query: str,
) -> tuple[InterestOption, ...]:
    scope = _scope(
        tenant_id=tenant_id,
        content_draft_id=content_draft_id,
        publish_attempt_id=publish_attempt_id,
        ad_account_id=ad_account_id,
    )
    return await _interest_status(
        scope,
        _interests(
            await _read(scope, "search", {"type": "adinterest", "q": _query(query), "limit": 25})
        ),
    )


async def suggest_audience_interests(
    *,
    tenant_id: UUID,
    content_draft_id: UUID,
    publish_attempt_id: UUID,
    ad_account_id: UUID,
    interest_ids: tuple[str, ...],
) -> tuple[InterestOption, ...]:
    if (
        not interest_ids
        or len(interest_ids) > 20
        or any(
            not isinstance(i, str) or not i.isascii() or not i.isdigit() or len(i) > 30
            for i in interest_ids
        )
    ):
        raise AudienceUnavailable("Elige primero uno de los intereses de la búsqueda.")
    scope = _scope(
        tenant_id=tenant_id,
        content_draft_id=content_draft_id,
        publish_attempt_id=publish_attempt_id,
        ad_account_id=ad_account_id,
    )
    return await _interest_status(
        scope,
        _interests(
            await _read(
                scope,
                "search",
                {"type": "adinterestsuggestion", "interest_list": list(interest_ids), "limit": 25},
            )
        ),
    )


async def estimate_audience(
    *,
    tenant_id: UUID,
    content_draft_id: UUID,
    publish_attempt_id: UUID,
    ad_account_id: UUID,
    audience: AudienceDraft,
) -> ReachEstimate:
    scope = _scope(
        tenant_id=tenant_id,
        content_draft_id=content_draft_id,
        publish_attempt_id=publish_attempt_id,
        ad_account_id=ad_account_id,
    )
    targeting = audience.targeting()
    # Radius and special-category policy cannot be inferred from an SDK schema.
    if audience.radius_km is not None or audience.housing:
        return ReachEstimate(
            message="Falta comprobar con Meta las reglas de este público.",
            audience_hash=audience.fingerprint,
        )
    try:
        rows = await _read(scope, "reach", targeting)
    except AudienceUnavailable:
        return ReachEstimate(audience_hash=audience.fingerprint)
    return (
        ReachEstimate.from_graph(rows[0], audience.fingerprint)
        if len(rows) == 1
        else ReachEstimate(audience_hash=audience.fingerprint)
    )


def _params(scope: AudienceScope) -> dict[str, Any]:
    return {
        "tenant": scope.tenant_id,
        "draft": scope.content_draft_id,
        "published": scope.publish_attempt_id,
        "account": scope.ad_account_id,
        "brand": scope.brand_id,
        "credential": scope.connection.version,
    }


def load_audience(
    *, tenant_id: UUID, content_draft_id: UUID, publish_attempt_id: UUID, ad_account_id: UUID
) -> SavedAudience | None:
    scope = _scope(
        tenant_id=tenant_id,
        content_draft_id=content_draft_id,
        publish_attempt_id=publish_attempt_id,
        ad_account_id=ad_account_id,
    )
    with tenant_session(tenant_id) as session:
        row = session.execute(
            text(
                "SELECT audience,version FROM ad_audience_drafts WHERE content_draft_id=:draft "
                "AND publish_attempt_id=:published AND ad_account_id=:account "
                "AND credential_version=:credential AND brand_id=:brand"
            ),
            _params(scope),
        ).first()
    result = SavedAudience(AudienceDraft.from_snapshot(row.audience), row.version) if row else None
    _same(scope)
    return result


def save_audience(
    *,
    tenant_id: UUID,
    content_draft_id: UUID,
    publish_attempt_id: UUID,
    ad_account_id: UUID,
    audience: AudienceDraft,
    expected_version: int = 0,
) -> SavedAudience:
    if type(expected_version) is not int or expected_version < 0:
        raise AudienceUnavailable("Vuelve a cargar el público antes de guardarlo.")
    scope = _scope(
        tenant_id=tenant_id,
        content_draft_id=content_draft_id,
        publish_attempt_id=publish_attempt_id,
        ad_account_id=ad_account_id,
    )
    values = _params(scope) | {
        "audience": json.dumps(audience.snapshot()),
        "targeting": json.dumps(audience.targeting()),
        "version": expected_version,
        "pipeline": PIPELINE_VERSION,
    }
    with tenant_session(tenant_id) as session:
        # Lock the connection/account before the CAS: a selection or credential change
        # cannot commit between source validation and this write.
        session.execute(
            text("SELECT id FROM social_connections WHERE id=:id FOR UPDATE"),
            {"id": scope.connection.connection_id},
        )
        session.execute(
            text("SELECT id FROM ad_accounts WHERE id=:id FOR UPDATE"), {"id": ad_account_id}
        )
        _same(scope)
        row = session.execute(
            text("""INSERT INTO ad_audience_drafts
            (tenant_id,brand_id,content_draft_id,publish_attempt_id,ad_account_id,
             credential_version,version,audience,targeting,pipeline_version)
            SELECT :tenant,:brand,:draft,:published,:account,:credential,1,
             CAST(:audience AS jsonb),CAST(:targeting AS jsonb),:pipeline WHERE :version=0
            ON CONFLICT (content_draft_id,publish_attempt_id,ad_account_id,credential_version)
            DO NOTHING RETURNING version"""),
            values,
        ).first()
        if row is None:
            row = session.execute(
                text("""UPDATE ad_audience_drafts SET audience=CAST(:audience AS jsonb),
                targeting=CAST(:targeting AS jsonb),version=version+1,
                updated_at=now(),pipeline_version=:pipeline
                WHERE content_draft_id=:draft AND publish_attempt_id=:published
                  AND ad_account_id=:account AND brand_id=:brand
                  AND credential_version=:credential AND version=:version RETURNING version"""),
                values,
            ).first()
        if row is None:
            raise AudienceUnavailable(
                "El público cambió en otra sesión. Vuelve a cargarlo antes de guardar."
            )
        return SavedAudience(audience, row.version)

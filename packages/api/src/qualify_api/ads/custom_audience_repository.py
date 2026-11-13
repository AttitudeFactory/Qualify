"""Durable tenant/account-bound, one-shot audience creation claims."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.audience import AudienceUnavailable
from qualify_api.ads.audience_service import AudienceScope, _same
from qualify_api.ads.client import MarketingSettings
from qualify_api.ads.custom_audiences import CustomAudienceRequest
from qualify_api.tenancy.acting import current_acting_login, require_acting_member


def scope_params(scope: AudienceScope) -> dict[str, Any]:
    return {
        "tenant": scope.tenant_id,
        "brand": scope.brand_id,
        "connection": scope.connection.connection_id,
        "account": scope.ad_account_id,
        "credential": scope.connection.version,
        "instagram": scope.connection.external_account_id,
    }


SCOPE_WHERE = """tenant_id=:tenant AND brand_id=:brand AND connection_id=:connection
    AND ad_account_id=:account AND credential_version=:credential
    AND source_instagram_id=:instagram"""


def list_rows(scope: AudienceScope) -> tuple[dict[str, Any], ...]:
    with tenant_session(scope.tenant_id) as session:
        rows = (
            session.execute(
                text(
                    f"SELECT * FROM ad_custom_audiences WHERE {SCOPE_WHERE} "
                    "ORDER BY approved_at DESC,id LIMIT 50"
                ),
                scope_params(scope),
            )
            .mappings()
            .all()
        )
        return tuple(dict(row) for row in rows)


def get_row(scope: AudienceScope, local_id: str) -> dict[str, Any]:
    try:
        identifier = UUID(local_id)
    except (ValueError, TypeError, AttributeError):
        raise AudienceUnavailable("Vuelve a elegir el público de este negocio.") from None
    with tenant_session(scope.tenant_id) as session:
        row = (
            session.execute(
                text(f"SELECT * FROM ad_custom_audiences WHERE {SCOPE_WHERE} AND id=:id"),
                scope_params(scope) | {"id": identifier},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise AudienceUnavailable("Este público no pertenece a la cuenta y marca elegidas.")
        return dict(row)


def claim(
    scope: AudienceScope, request: CustomAudienceRequest, request_key: UUID, payload: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    login = current_acting_login()
    if login is None:
        raise AudienceUnavailable("Vuelve a entrar para confirmar la creación del público.")
    require_acting_member(scope.tenant_id)
    values = scope_params(scope) | {
        "key": request_key,
        "hash": request.fingerprint,
        "login": login,
        "request": json.dumps(request.snapshot()),
        "payload": json.dumps(payload),
        "name": request.name.strip(),
        "kind": request.kind,
        "api": MarketingSettings.from_env().api_version,
    }
    with tenant_session(scope.tenant_id, independent=True) as session:
        session.execute(
            text("SELECT id FROM social_connections WHERE id=:connection FOR UPDATE"), values
        )
        session.execute(text("SELECT id FROM ad_accounts WHERE id=:account FOR UPDATE"), values)
        _same(scope)
        actor = session.scalar(
            text("""SELECT u.id FROM users u JOIN tenant_members m
            ON m.user_id=u.id AND m.tenant_id=:tenant WHERE u.auth_user_id=:login"""),
            values,
        )
        if actor is None:
            raise AudienceUnavailable("Vuelve a entrar para confirmar el público de este negocio.")
        row = (
            session.execute(
                text("""INSERT INTO ad_custom_audiences
            (tenant_id,brand_id,connection_id,ad_account_id,credential_version,source_instagram_id,
             request_key,request_hash,request,payload,kind,name,approved_by,api_version)
            VALUES (:tenant,:brand,:connection,:account,:credential,:instagram,
             :key,:hash,CAST(:request AS jsonb),CAST(:payload AS jsonb),:kind,:name,:actor,:api)
            ON CONFLICT (tenant_id,request_key) DO NOTHING RETURNING *"""),
                values | {"actor": actor},
            )
            .mappings()
            .first()
        )
        if row is not None:
            return dict(row), True
        row = (
            session.execute(
                text("""SELECT * FROM ad_custom_audiences
            WHERE tenant_id=:tenant AND request_key=:key"""),
                values,
            )
            .mappings()
            .one()
        )
        if (
            row["request_hash"] != request.fingerprint
            or row["payload"] != payload
            or any(
                row[column] != values[param]
                for column, param in (
                    ("brand_id", "brand"),
                    ("connection_id", "connection"),
                    ("ad_account_id", "account"),
                    ("credential_version", "credential"),
                    ("source_instagram_id", "instagram"),
                )
            )
        ):
            raise AudienceUnavailable(
                "Esta solicitud ya se usó con otro público. Revisa los datos."
            )
        return dict(row), False


def finish(scope: AudienceScope, local_id: UUID, remote_id: str | None) -> dict[str, Any]:
    with tenant_session(scope.tenant_id, independent=True) as session:
        row = (
            session.execute(
                text(f"""UPDATE ad_custom_audiences
            SET status=:status,meta_audience_id=:remote,updated_at=now()
            WHERE {SCOPE_WHERE} AND id=:id AND status='creating' RETURNING *"""),
                scope_params(scope)
                | {
                    "id": local_id,
                    "remote": remote_id,
                    "status": "created" if remote_id else "unknown",
                },
            )
            .mappings()
            .first()
        )
        if row is None:
            raise AudienceUnavailable("Consulta de nuevo el estado del público antes de continuar.")
        return dict(row)

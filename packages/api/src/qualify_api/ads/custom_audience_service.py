"""Explicit audience creation without activating or funding an advertisement."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from qualify_api.ads import custom_audience_repository as repository
from qualify_api.ads.audience import AudienceUnavailable
from qualify_api.ads.audience_service import AudienceScope, _same, _scope
from qualify_api.ads.client import MarketingClient
from qualify_api.ads.custom_audience_client import CustomAudienceClient
from qualify_api.ads.custom_audiences import (
    CustomAudienceCatalog,
    CustomAudienceRequest,
    CustomAudienceSelection,
    CustomAudienceSummary,
    accepted_terms,
    ready_audience,
)
from qualify_api.ads.errors import MarketingError
from qualify_api.connections.ad_accounts import AdAccountUnavailable, _authenticated_client

TERMS_REQUIRED = (
    "Acepta los términos de públicos personalizados en el administrador de anuncios de Meta "
    "y vuelve a consultar los públicos."
)
TERMS_UNKNOWN = "No pudimos comprobar los términos de esta cuenta en Meta. Vuelve a consultar."


@asynccontextmanager
async def _client(scope: AudienceScope):
    authenticated = await _authenticated_client(
        scope.tenant_id, scope.connection.connection_id, expected_version=scope.connection.version
    )
    try:
        _same(scope)
        yield CustomAudienceClient(
            MarketingClient(client=authenticated, account_id=scope.meta_account_id)
        )
    finally:
        await authenticated.aclose()


def _json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def _matches_remote(row: dict[str, Any], remote: dict[str, Any]) -> bool:
    payload = row["payload"]
    if remote.get("subtype") != payload["subtype"]:
        return False
    if row["kind"] != "lookalike":
        return _json_object(remote.get("rule")) == payload["rule"]
    spec = _json_object(remote.get("lookalike_spec"))
    if spec is None:
        return False
    origin = spec.get("origin")
    return (
        isinstance(origin, list)
        and len(origin) == 1
        and isinstance(origin[0], dict)
        and origin[0].get("id") == payload["origin_audience_id"]
        and all(spec.get(key) == value for key, value in payload["lookalike_spec"].items())
    )


def _summary(
    row: dict[str, Any], *, available: bool = False, reason: str = ""
) -> CustomAudienceSummary:
    if row["status"] in {"creating", "unknown"}:
        reason = (
            "La creación no está confirmada. Revisa el público en Meta antes de crear otro. "
            "Esta solicitud no se enviará de nuevo."
        )
    return CustomAudienceSummary(
        row["id"],
        row["name"],
        row["kind"],
        row["status"],
        row.get("meta_audience_id") or "",
        available,
        reason,
    )


async def _observe(
    scope: AudienceScope, client: CustomAudienceClient, row: dict[str, Any], accepted: bool | None
) -> CustomAudienceSummary:
    if row["status"] != "created":
        return _summary(row)
    try:
        remote = await client.read(row["meta_audience_id"])
        _same(scope)
        available = (
            accepted is True
            and ready_audience(
                remote, remote_id=row["meta_audience_id"], account_id=scope.meta_account_id
            )
            and _matches_remote(row, remote)
        )
    except MarketingError:
        available = False
    return _summary(
        row,
        available=available,
        reason=""
        if available
        else ("Meta todavía no confirmó que este público esté listo y corresponda a esta cuenta."),
    )


async def list_custom_audiences(
    *, tenant_id: UUID, content_draft_id: UUID, publish_attempt_id: UUID, ad_account_id: UUID
) -> CustomAudienceCatalog:
    scope = _scope(
        tenant_id=tenant_id,
        content_draft_id=content_draft_id,
        publish_attempt_id=publish_attempt_id,
        ad_account_id=ad_account_id,
    )
    rows = repository.list_rows(scope)
    try:
        async with _client(scope) as client:
            accepted = accepted_terms(await client.terms(), scope.meta_account_id)
            _same(scope)
            summaries = tuple([await _observe(scope, client, row, accepted) for row in rows])
        _same(scope)
    except (MarketingError, AdAccountUnavailable):
        _same(scope)
        return CustomAudienceCatalog(
            None, False, TERMS_UNKNOWN, tuple(_summary(row) for row in rows)
        )
    return CustomAudienceCatalog(
        accepted,
        accepted is True,
        "" if accepted is True else TERMS_REQUIRED if accepted is False else TERMS_UNKNOWN,
        summaries,
    )


async def create_custom_audience(
    *,
    tenant_id: UUID,
    content_draft_id: UUID,
    publish_attempt_id: UUID,
    ad_account_id: UUID,
    request: CustomAudienceRequest,
    request_key: UUID,
    confirmed: bool,
    housing: bool = False,
) -> CustomAudienceSummary:
    request.validate()
    if confirmed is not True or not isinstance(request_key, UUID):
        raise AudienceUnavailable("Confirma los datos antes de crear el público en Meta.")
    if type(housing) is not bool or (housing and request.kind == "lookalike"):
        raise AudienceUnavailable("Los anuncios de vivienda no admiten públicos similares.")
    scope = _scope(
        tenant_id=tenant_id,
        content_draft_id=content_draft_id,
        publish_attempt_id=publish_attempt_id,
        ad_account_id=ad_account_id,
    )
    async with _client(scope) as client:
        accepted = accepted_terms(await client.terms(), scope.meta_account_id)
        _same(scope)
        if accepted is not True:
            raise AudienceUnavailable(TERMS_REQUIRED if accepted is False else TERMS_UNKNOWN)
        seed_meta_id = ""
        if request.kind == "lookalike":
            seed = repository.get_row(scope, request.seed_id)
            if (
                seed["kind"] == "lookalike"
                or not (await _observe(scope, client, seed, accepted)).available
            ):
                raise AudienceUnavailable("Elige un público de origen que Meta haya confirmado.")
            seed_meta_id = seed["meta_audience_id"]
        payload = request.payload(scope.connection.external_account_id, seed_meta_id=seed_meta_id)
        row, claimed = repository.claim(scope, request, request_key, payload)
        if not claimed:
            return await _observe(scope, client, row, accepted)
        try:
            # This callback runs after any client lock/cooldown. No membership or
            # asset captured before waiting is treated as permanent authorization.
            remote_id = await client.create(payload, before_write=lambda: _same(scope))
        except Exception:
            row = repository.finish(scope, row["id"], None)
            return _summary(row)
        row = repository.finish(scope, row["id"], remote_id)
        _same(scope)
        return await _observe(scope, client, row, accepted)


def verify_local_selection(scope: AudienceScope, selection: CustomAudienceSelection) -> None:
    selection.validate()
    row = repository.get_row(scope, selection.local_id)
    if (
        row["status"] != "created"
        or row["meta_audience_id"] != selection.id
        or row["name"] != selection.name
        or row["kind"] != selection.kind
    ):
        raise AudienceUnavailable("El público cambió. Vuelve a consultarlo antes de guardar.")

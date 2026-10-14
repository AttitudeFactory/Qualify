"""The seam between `/whatsapp` → Plantillas (WA-18, QUA-217) and the real backend.

In-process calls to `qualify_api.whatsapp.templates.TemplateService` — the same service
the HTTP layer would wrap — built over:

- `PostgresTemplateRepository` (`qualify_app` under `tenant_session`: RLS scopes every
  row to the tenant), and
- `outbox.ResolverClientFactory`: an `HttpWhatsAppClient` whose Graph client came out of
  `InjectingCredentialResolver` — **no token ever reaches this module, the state or the
  browser** (same door as `whatsapp_provider.open_whatsapp_client`).

A Graph call that comes back 401 / code 190 degrades the connection through
`degrade_connection_on_auth_error` before the error propagates (the posture of
`whatsapp_provider._call`), so the Conexión card tells the truth afterwards.

Everything is injectable (`service`, `degrader`) so `test_whatsapp_templates.py` drives
it with `MemoryTemplateRepository` and a fake client — no network, no database.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from qualify_api.connections.composition import degrade_connection_on_auth_error
from qualify_api.whatsapp.client import WhatsAppApiError
from qualify_api.whatsapp.templates import (
    PostgresTemplateRepository,
    SyncReport,
    TemplateRecord,
    TemplateService,
)

from .whatsapp_templates_vm import TemplateForm, TemplateVM, build_components, build_template_vm

Degrader = Callable[..., object]


def production_client_factory() -> Any:
    """WA-08's resolver-built client factory. Imports resolved here so importing this
    module needs no Meta settings."""
    from qualify_api.config import MetaOAuthSettings  # noqa: PLC0415
    from qualify_api.connections.crypto import DevEncryptor  # noqa: PLC0415
    from qualify_api.whatsapp.outbox import ResolverClientFactory  # noqa: PLC0415

    return ResolverClientFactory(MetaOAuthSettings.from_env(), DevEncryptor())


def production_template_service() -> TemplateService:
    return TemplateService(PostgresTemplateRepository(), production_client_factory())


async def degrading[T](
    tenant_id: UUID,
    connection_id: UUID,
    call: Callable[[], Awaitable[T]],
    *,
    degrader: Degrader = degrade_connection_on_auth_error,
) -> T:
    """Run one Graph-backed service call; on an auth error degrade the connection, then
    re-raise. Every other error propagates untouched."""
    try:
        return await call()
    except WhatsAppApiError as exc:
        if exc.is_auth_error:
            await asyncio.to_thread(degrader, tenant_id=tenant_id, connection_id=connection_id)
        raise


def template_vm(record: TemplateRecord) -> TemplateVM:
    return build_template_vm(
        template_id=str(record.id),
        name=record.name,
        language=record.language,
        category=record.category,
        status=record.status,
        quality=record.quality,
        rejected_reason=record.rejected_reason,
        components=record.components,
        updated_at=record.updated_at,
    )


def _sort_key(vm: TemplateVM) -> tuple[int, str, str]:
    # Live templates first, gone ones (deleted) last; then by name.
    return (0 if vm.can_delete else 1, vm.name, vm.language)


async def list_templates(
    tenant_id: UUID, connection_id: UUID, *, service: TemplateService | None = None
) -> list[TemplateVM]:
    """The mirror for this number's WABA — Postgres only, no Graph call. Raises
    `NoWhatsAppNumber` when the connection has no number row."""
    svc = service or production_template_service()
    records = await asyncio.to_thread(svc.list, tenant_id=tenant_id, connection_id=connection_id)
    return sorted((template_vm(r) for r in records), key=_sort_key)


async def sync_templates(
    tenant_id: UUID,
    connection_id: UUID,
    *,
    service: TemplateService | None = None,
    degrader: Degrader = degrade_connection_on_auth_error,
) -> SyncReport:
    svc = service or production_template_service()
    return await degrading(
        tenant_id,
        connection_id,
        lambda: svc.sync_from_meta(tenant_id=tenant_id, connection_id=connection_id),
        degrader=degrader,
    )


async def create_template(
    tenant_id: UUID,
    connection_id: UUID,
    form: TemplateForm,
    *,
    service: TemplateService | None = None,
    degrader: Degrader = degrade_connection_on_auth_error,
) -> TemplateVM:
    """Raises `ValueError` (the client's local check), `TemplateAlreadyExists` (before any
    Graph call), `NoWhatsAppNumber`, or `WhatsAppApiError` (Meta refused)."""
    svc = service or production_template_service()
    components = build_components(form)
    record = await degrading(
        tenant_id,
        connection_id,
        lambda: svc.create(
            tenant_id=tenant_id,
            connection_id=connection_id,
            name=form.name.strip(),
            language=form.language,
            category=form.category,
            components=components,
        ),
        degrader=degrader,
    )
    return template_vm(record)


async def delete_template(
    tenant_id: UUID,
    connection_id: UUID,
    template_id: UUID,
    *,
    service: TemplateService | None = None,
    degrader: Degrader = degrade_connection_on_auth_error,
) -> int:
    """Delete at Meta BY NAME (every language of it), then mark the mirror `DELETED`."""
    svc = service or production_template_service()
    return await degrading(
        tenant_id,
        connection_id,
        lambda: svc.delete(
            tenant_id=tenant_id, connection_id=connection_id, template_id=template_id
        ),
        degrader=degrader,
    )

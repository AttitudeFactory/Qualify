"""The seam between the Menú tab (WA-16) and the real menu backend (WA-14/WA-15).

Same split as `whatsapp_provider.py`:

- **Postgres** goes through the sanctioned doors only. Menu rows and versions through
  `PostgresMenuRepository` (every call is `tenant_session(tenant_id)`, so RLS scopes it);
  the number's own row, the preview catalog and the publisher's user id through
  `tenant_session` here. Every function in this group is blocking — callers on the
  event loop run them off-thread.
- **Graph** (the one call this tab makes: `set_conversational_automation` on publish)
  goes through `whatsapp_provider.open_whatsapp_client` — the `CredentialResolver` path —
  so no token reaches this module, the state or the browser. A 401 / code 190 degrades
  the connection before the error is reported, as everywhere else on the screen.

**A menu belongs to ONE number.** Every call that takes a `menu_id` (it arrives from the
browser) re-checks that the menu hangs from the number on screen (`_owned_menu`), on top
of RLS: another tenant's menu is invisible, and another number's menu of the same tenant
is refused here.

**Publishing is two writes in a fixed order.** First the database (`publish_version`:
the version goes live in Qualify, atomically demoting the number's previous menu), then
WhatsApp's copy of the shortcuts (`set_conversational_automation` with
`to_conversational_automation(definition)` — the SAME datum, plan §5.3). If Meta refuses,
the database publish is kept and the outcome says so with Meta's code; the next publish
retries. On success the body sent is stored in `whatsapp_phone_numbers.automation`
(«as published to Meta», WA-04) so a later diff has something to compare against.

Every collaborator is injectable (`repo`, `opener`, `degrader`, `store_automation`), so
`test_whatsapp_menu_provider.py` runs the whole flow with fakes and no network.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from qualify_api.catalog.models import BrandProduct
from qualify_api.connections.composition import degrade_connection_on_auth_error
from qualify_api.connections.credential_reader import CredentialNotFound
from qualify_api.connections.token_health import TokenHealthError
from qualify_api.tenancy.models import Brand, User
from qualify_api.whatsapp.catalog import to_catalog_items
from qualify_api.whatsapp.client import (
    Command,
    ConversationalAutomation,
    WhatsAppApiError,
)
from qualify_api.whatsapp.menus import (
    MenuNotFound,
    MenuRecord,
    MenuRepository,
    MenuVersionNotFound,
    MenuVersionRecord,
    PostgresMenuRepository,
)
from qualify_api.whatsapp.menus.automation import to_conversational_automation
from qualify_api.whatsapp.menus.engine import CatalogItem
from qualify_api.whatsapp.menus.schema import MenuDefinition
from qualify_api.whatsapp.models import WhatsAppPhoneNumber
from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .whatsapp_menu_vm import (
    MenuSummaryVM,
    MenuVersionVM,
    build_menu_summary,
    build_version_vm,
    publish_notice,
    template_definition,
)
from .whatsapp_provider import ClientOpener, Degrader, UnknownWhatsAppNumber, open_whatsapp_client

logger = logging.getLogger(__name__)

AutomationStore = Callable[[UUID, UUID, dict[str, Any]], None]

# Failures that are infrastructure, not a verdict from Meta. Only the TYPE is logged.
_INFRA_ERRORS = (
    CredentialNotFound,
    TokenHealthError,
    UnknownWhatsAppNumber,
    httpx.HTTPError,
    SQLAlchemyError,
)


def default_repository() -> MenuRepository:
    return PostgresMenuRepository()


# ======================================================================================
# The number on screen (tenant_session)
# ======================================================================================


@dataclass(frozen=True)
class NumberScope:
    """The `whatsapp_phone_numbers` row a connection maps to: menus hang from its `id`,
    the preview catalog from its brand."""

    phone_row_id: UUID
    brand_id: UUID | None
    brand_name: str


def number_scope(tenant_id: UUID, connection_id: UUID) -> NumberScope:
    """Raises `UnknownWhatsAppNumber` when no row is visible (unknown, or another tenant's:
    RLS makes the two the same read)."""
    with tenant_session(tenant_id) as session:
        row = session.execute(
            select(WhatsAppPhoneNumber.id, WhatsAppPhoneNumber.brand_id, Brand.name)
            .outerjoin(Brand, Brand.id == WhatsAppPhoneNumber.brand_id)
            .where(WhatsAppPhoneNumber.connection_id == connection_id)
        ).first()
    if row is None:
        raise UnknownWhatsAppNumber(str(connection_id))
    return NumberScope(phone_row_id=row[0], brand_id=row[1], brand_name=row[2] or "la marca")


def preview_catalog(tenant_id: UUID, brand_id: UUID | None) -> tuple[CatalogItem, ...]:
    """The brand's active products, mapped exactly as the production `catalog_loader` maps
    them (`to_catalog_items`) — but read as `qualify_app` under RLS, because the editor is
    a tenant-scoped session, not the tenant-blind webhook worker."""
    if brand_id is None:
        return ()
    with tenant_session(tenant_id) as session:
        rows = session.execute(
            select(
                BrandProduct.id,
                BrandProduct.name,
                BrandProduct.price_amount,
                BrandProduct.price_currency,
                BrandProduct.category,
                BrandProduct.is_active,
                BrandProduct.position,
            ).where(BrandProduct.brand_id == brand_id, BrandProduct.is_active.is_(True))
        ).all()
        return to_catalog_items(rows)


def user_id_for(tenant_id: UUID, email: str) -> UUID | None:
    """The session's user (for `published_by_user_id` / `created_by_user_id`); None when
    the email is not a user of the tenant — the columns are nullable on purpose."""
    if not email:
        return None
    with tenant_session(tenant_id) as session:
        return session.scalar(select(User.id).where(User.email == email))


def store_published_automation(
    tenant_id: UUID, connection_id: UUID, automation: dict[str, Any]
) -> None:
    """Record what WhatsApp now shows on the number (`qualify_app` holds UPDATE, 0057)."""
    with tenant_session(tenant_id) as session:
        phone = session.scalar(
            select(WhatsAppPhoneNumber).where(WhatsAppPhoneNumber.connection_id == connection_id)
        )
        if phone is None:
            raise UnknownWhatsAppNumber(str(connection_id))
        phone.automation = dict(automation)
        session.flush()


# ======================================================================================
# Menus and versions (repository, tenant_session)
# ======================================================================================


def _summary(menu: MenuRecord, versions: list[MenuVersionRecord]) -> MenuSummaryVM:
    published = next((v.version for v in versions if v.id == menu.published_version_id), None)
    return build_menu_summary(
        menu_id=str(menu.id),
        name=menu.name,
        published_version=published,
        is_paused=menu.is_paused,
        updated_at=menu.updated_at,
    )


def _version_vms(menu: MenuRecord, versions: list[MenuVersionRecord]) -> list[MenuVersionVM]:
    """Newest first: the history reads top-down from what was just saved."""
    return [
        build_version_vm(
            version_id=str(v.id),
            version=v.version,
            created_at=v.created_at,
            published_at=v.published_at,
            is_live=v.id == menu.published_version_id,
        )
        for v in sorted(versions, key=lambda v: v.version, reverse=True)
    ]


def _owned_menu(
    repo: MenuRepository, tenant_id: UUID, scope: NumberScope, menu_id: UUID
) -> MenuRecord:
    menu = repo.get_menu(tenant_id=tenant_id, menu_id=menu_id)
    if menu is None or menu.phone_number_row_id != scope.phone_row_id:
        raise MenuNotFound(str(menu_id))
    return menu


def menus_for(
    tenant_id: UUID, scope: NumberScope, *, repo: MenuRepository | None = None
) -> list[MenuSummaryVM]:
    repo = repo or default_repository()
    menus = repo.list_menus(tenant_id=tenant_id, phone_number_row_id=scope.phone_row_id)
    return [
        _summary(menu, repo.list_versions(tenant_id=tenant_id, menu_id=menu.id)) for menu in menus
    ]


@dataclass(frozen=True)
class MenuDetail:
    """One open menu: its summary, its history, and the definition the editor starts
    from (the newest version; None for a menu nothing was saved to yet). `payloads` maps a
    version id to its definition JSON so «Abrir» needs no second read."""

    summary: MenuSummaryVM
    versions: list[MenuVersionVM]
    latest: MenuDefinition | None
    payloads: dict[str, dict[str, Any]]


def menu_detail(
    tenant_id: UUID, scope: NumberScope, menu_id: UUID, *, repo: MenuRepository | None = None
) -> MenuDetail:
    repo = repo or default_repository()
    menu = _owned_menu(repo, tenant_id, scope, menu_id)
    versions = repo.list_versions(tenant_id=tenant_id, menu_id=menu_id)
    latest = max(versions, key=lambda v: v.version).definition if versions else None
    return MenuDetail(
        summary=_summary(menu, versions),
        versions=_version_vms(menu, versions),
        latest=latest,
        payloads={str(v.id): v.definition.model_dump(mode="json") for v in versions},
    )


def create_menu(
    tenant_id: UUID,
    scope: NumberScope,
    name: str,
    template: str,
    *,
    user_id: UUID | None = None,
    repo: MenuRepository | None = None,
) -> MenuDetail:
    """A new menu on the number. From the example it is saved as version 1 at once (it is
    valid, and leaving the tab must not lose it); an empty menu has no version until its
    first «Guardar versión» — an empty menu is not a valid definition."""
    repo = repo or default_repository()
    menu = repo.create_menu(
        tenant_id=tenant_id,
        phone_number_row_id=scope.phone_row_id,
        name=name.strip(),
        brand_id=scope.brand_id,
        created_by_user_id=user_id,
    )
    definition = template_definition(template)
    if definition is not None:
        repo.save_version(tenant_id=tenant_id, menu_id=menu.id, definition=definition)
    return menu_detail(tenant_id, scope, menu.id, repo=repo)


def save_version(
    tenant_id: UUID,
    scope: NumberScope,
    menu_id: UUID,
    payload: Mapping[str, Any],
    *,
    repo: MenuRepository | None = None,
) -> MenuDetail:
    """Raises `pydantic.ValidationError` (the repository validates again — the editor's
    check is a convenience, the write is the guarantee)."""
    repo = repo or default_repository()
    _owned_menu(repo, tenant_id, scope, menu_id)
    repo.save_version(tenant_id=tenant_id, menu_id=menu_id, definition=payload)
    return menu_detail(tenant_id, scope, menu_id, repo=repo)


def set_paused(
    tenant_id: UUID,
    scope: NumberScope,
    menu_id: UUID,
    paused: bool,
    *,
    repo: MenuRepository | None = None,
) -> MenuDetail:
    repo = repo or default_repository()
    _owned_menu(repo, tenant_id, scope, menu_id)
    repo.set_paused(tenant_id=tenant_id, menu_id=menu_id, paused=paused)
    return menu_detail(tenant_id, scope, menu_id, repo=repo)


# ======================================================================================
# Publish (repository, then Graph through the CredentialResolver)
# ======================================================================================


def automation_for(definition: MenuDefinition) -> ConversationalAutomation:
    """`to_conversational_automation` (WA-14, the body Meta expects) as the client's
    typed value — one datum, two shapes, nothing re-derived here."""
    body = to_conversational_automation(definition)
    return ConversationalAutomation(
        ice_breakers=list(body["prompts"]),
        commands=[
            Command(name=c["command_name"], hint=c["command_description"]) for c in body["commands"]
        ],
        enable_welcome_message=bool(body["enable_welcome_message"]),
    )


@dataclass(frozen=True)
class PublishOutcome:
    detail: MenuDetail
    notice: str
    tone: str
    graph_ok: bool
    auth_error: bool  # the connection got degraded: the shell must re-read the numbers


async def publish_version(
    tenant_id: UUID,
    connection_id: UUID,
    scope: NumberScope,
    menu_id: UUID,
    version_id: UUID,
    *,
    user_id: UUID | None = None,
    repo: MenuRepository | None = None,
    opener: ClientOpener = open_whatsapp_client,
    degrader: Degrader = degrade_connection_on_auth_error,
    store_automation: AutomationStore = store_published_automation,
) -> PublishOutcome:
    """«Publicar esta versión». Raises `MenuNotFound`/`MenuVersionNotFound` (nothing
    written) and `SQLAlchemyError` from the database publish; never raises for a Graph
    failure — that is an outcome, because the database publish already happened."""
    repo = repo or default_repository()

    def publish_in_db() -> MenuDefinition:
        _owned_menu(repo, tenant_id, scope, menu_id)
        versions = repo.list_versions(tenant_id=tenant_id, menu_id=menu_id)
        version = next((v for v in versions if v.id == version_id), None)
        if version is None:
            raise MenuVersionNotFound(str(version_id))
        repo.publish_version(
            tenant_id=tenant_id, menu_id=menu_id, version_id=version_id, user_id=user_id
        )
        return version.definition

    definition = await asyncio.to_thread(publish_in_db)
    automation = automation_for(definition)
    graph_ok = auth_error = False
    try:
        async with opener(tenant_id, connection_id) as client:
            try:
                await client.set_conversational_automation(automation)
            except WhatsAppApiError as exc:
                if exc.is_auth_error:
                    await asyncio.to_thread(
                        degrader, tenant_id=tenant_id, connection_id=connection_id
                    )
                raise
    except WhatsAppApiError as exc:
        auth_error = exc.is_auth_error
        notice = publish_notice(
            graph_ok=False,
            code=exc.code,
            is_auth_error=exc.is_auth_error,
            is_transport=exc.is_transport,
        )
    except ValueError:
        # The client's own limit check (its emoji rule is broader than the schema's).
        notice = publish_notice(graph_ok=False, rejected_locally=True)
    except _INFRA_ERRORS as exc:
        logger.error("whatsapp menu automation publish failed: %s", type(exc).__name__)
        notice = publish_notice(graph_ok=False)
    else:
        graph_ok = True
        notice = publish_notice(graph_ok=True)
        try:
            await asyncio.to_thread(
                store_automation,
                tenant_id,
                connection_id,
                to_conversational_automation(definition),
            )
        except (SQLAlchemyError, UnknownWhatsAppNumber) as exc:
            # Meta already has it; only our record of it lags. Not worth a warning banner.
            logger.error("whatsapp automation record failed: %s", type(exc).__name__)
    detail = await asyncio.to_thread(menu_detail, tenant_id, scope, menu_id, repo=repo)
    return PublishOutcome(
        detail=detail, notice=notice[0], tone=notice[1], graph_ok=graph_ok, auth_error=auth_error
    )


__all__ = [
    "MenuDetail",
    "MenuNotFound",
    "MenuVersionNotFound",
    "NumberScope",
    "PublishOutcome",
    "automation_for",
    "create_menu",
    "default_repository",
    "menu_detail",
    "menus_for",
    "number_scope",
    "preview_catalog",
    "publish_version",
    "save_version",
    "set_paused",
    "store_published_automation",
    "user_id_for",
]

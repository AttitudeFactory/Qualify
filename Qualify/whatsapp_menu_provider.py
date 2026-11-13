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

**«Eliminar» archives** (`archive_menu`, m-24986800, decision D1): the row, its versions
and the chats that used them stay; the menu leaves the list for good. The menu that is
answering is refused (`MenuIsAnswering`) by the repository, under a row lock — the
screen's «Para eliminarlo, primero páusalo.» is a courtesy, not the guarantee. No Graph
call: archiving is only allowed on a paused or never-published menu, which already
answers nobody.

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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

import httpx
from qualify_api.catalog.models import BrandProduct, BrandProductCategory
from qualify_api.catalog.service import CatalogError, CatalogService
from qualify_api.claude_tools import Attribution, ClientFactory, default_client
from qualify_api.connections.composition import degrade_connection_on_auth_error
from qualify_api.connections.credential_reader import CredentialNotFound
from qualify_api.connections.token_health import TokenHealthError
from qualify_api.creative.brand_kit_store import BrandKitStore
from qualify_api.tenancy.models import Brand, User
from qualify_api.whatsapp.catalog import to_catalog_items
from qualify_api.whatsapp.client import (
    Command,
    ConversationalAutomation,
    WhatsAppApiError,
)
from qualify_api.whatsapp.menus import (
    MenuIsAnswering,
    MenuNotFound,
    MenuRecord,
    MenuRepository,
    MenuVersionNotFound,
    MenuVersionRecord,
    PostgresMenuRepository,
)
from qualify_api.whatsapp.menus.automation import to_conversational_automation
from qualify_api.whatsapp.menus.engine import CatalogItem
from qualify_api.whatsapp.menus.import_ai import FEATURE as IMPORT_FEATURE
from qualify_api.whatsapp.menus.import_ai import (
    Fetch,
    FoundProduct,
    ImportProposal,
    ImportSource,
    ImportUnavailable,
    NothingFound,
    SourceUnsupported,
    default_fetch,
    propose_menu_facts,
)
from qualify_api.whatsapp.menus.schema import MenuDefinition, normalize_keyword
from qualify_api.whatsapp.menus.starter import (
    PAYMENT_ANSWER_NODE_ID,
    MenuHasGaps,
    PaymentAnswer,
    StarterFacts,
    definition_gaps,
    payment_answer,
)
from qualify_api.whatsapp.menus.suggest_ai import FEATURE as SUGGEST_FEATURE
from qualify_api.whatsapp.menus.suggest_ai import (
    KitStore,
    SuggestInput,
    SuggestProposal,
    SuggestUnavailable,
    suggest_for_brand,
)
from qualify_api.whatsapp.menus.suggest_ai import suggest_text as _suggest_without_brand
from qualify_api.whatsapp.models import WhatsAppPhoneNumber
from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .whatsapp_menu_vm import (
    MenuCardInput,
    MenuSummaryVM,
    MenuVersionVM,
    build_menu_summary,
    build_version_vm,
    card_input_from,
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
    # The business's real name for a new menu's greeting (m-24936836): the brand's name,
    # else the number's verified name; "" when neither is known (the greeting keeps a gap).
    business_name: str = ""


def number_scope(tenant_id: UUID, connection_id: UUID) -> NumberScope:
    """Raises `UnknownWhatsAppNumber` when no row is visible (unknown, or another tenant's:
    RLS makes the two the same read)."""
    with tenant_session(tenant_id) as session:
        row = session.execute(
            select(
                WhatsAppPhoneNumber.id,
                WhatsAppPhoneNumber.brand_id,
                Brand.name,
                WhatsAppPhoneNumber.verified_name,
            )
            .outerjoin(Brand, Brand.id == WhatsAppPhoneNumber.brand_id)
            .where(WhatsAppPhoneNumber.connection_id == connection_id)
        ).first()
    if row is None:
        raise UnknownWhatsAppNumber(str(connection_id))
    return NumberScope(
        phone_row_id=row[0],
        brand_id=row[1],
        brand_name=row[2] or "la marca",
        business_name=(row[2] or row[3] or "").strip(),
    )


def starter_facts(
    tenant_id: UUID,
    scope: NumberScope,
    *,
    address: str = "",
    store: BrandKitStore | None = None,
    payment_names: Callable[[UUID, UUID], Sequence[str]] | None = None,
) -> StarterFacts:
    """What a new menu is born with (m-24936836) — facts already in Postgres, read under
    RLS: the business's name (`number_scope`), and the city and sector «Tu marca» saved
    (`brand_kit_details.connect`, through `BrandKitStore` → `tenant_session`). `address`
    is the WhatsApp profile's, only when the screen already read it: no Graph call here."""
    city = sector = ""
    if scope.brand_id is not None:
        connect = (
            (store or BrandKitStore())
            .load_details(tenant_id=tenant_id, brand_id=scope.brand_id)
            .connect
        )
        city = str(connect.get("city") or "").strip()
        sector = str(connect.get("sector") or "").strip()
    # m-24955648: «Formas de pago» lists the business's active methods (no gap then).
    payments: tuple[str, ...] = ()
    if scope.brand_id is not None:
        payments = tuple((payment_names or _active_payment_names)(tenant_id, scope.brand_id))
    return StarterFacts(
        business_name=scope.business_name,
        address=address.strip(),
        city=city,
        sector=sector,
        payment_methods=payments,
    )


def _active_payment_names(tenant_id: UUID, brand_id: UUID) -> tuple[str, ...]:
    from qualify_api.whatsapp.menus.starter import payment_phrase  # noqa: PLC0415
    from qualify_api.whatsapp.payments import active_payment_methods  # noqa: PLC0415

    return tuple(
        payment_phrase(m.name, m.currency, m.pay_on_delivery)
        for m in active_payment_methods(tenant_id, brand_id)
    )


def offers_payment_methods(tenant_id: UUID, brand_id: UUID | None) -> bool:
    """Whether the business offers ≥ 1 payment method now (RLS read). A failed read is
    «no» — the publish then keeps blocking on the gap, never the other way round."""
    if brand_id is None:
        return False
    try:
        from qualify_api.whatsapp.payments import active_payment_methods  # noqa: PLC0415

        return bool(active_payment_methods(tenant_id, brand_id))
    except Exception as exc:  # noqa: BLE001 — fail closed
        logger.warning("whatsapp menu: payment methods unreadable: %s", type(exc).__name__)
        return False


def payment_options(tenant_id: UUID, brand_id: UUID | None) -> tuple[Any, ...] | None:
    """The methods the business offers now, as the engine reads them (`as_option`) — ONE
    read per editor load: it drives the live «Formas de pago» answer, the gap rule
    (`definition_gaps(..., payments_offered=…)`) and the phone preview. None when it
    cannot be read (the editor then keeps the old rule: the stored gap blocks)."""
    if brand_id is None:
        return ()
    try:
        from qualify_api.whatsapp.payments import (  # noqa: PLC0415
            active_payment_methods,
            as_option,
        )

        return tuple(as_option(m) for m in active_payment_methods(tenant_id, brand_id))
    except Exception as exc:  # noqa: BLE001 — fail closed
        logger.warning("whatsapp menu: payment methods unreadable: %s", type(exc).__name__)
        return None


def payment_answer_view(
    tenant_id: UUID,
    scope: NumberScope,
    definition: MenuDefinition,
    *,
    methods: Callable[[UUID, UUID], Sequence[Any]] | None = None,
) -> PaymentAnswer | None:
    """For the editor (m-24955648 §6): whether the starter's «Formas de pago» answer is
    composed live now (`auto_composed`, show «Se arma sola con tus formas de pago») and
    the text a customer reads (`text`); `None` when the menu has no such answer. The
    methods are read only when the answer exists."""
    if definition.nodes.get(PAYMENT_ANSWER_NODE_ID) is None or scope.brand_id is None:
        return payment_answer(definition, ())
    if methods is None:
        from qualify_api.whatsapp.payments import active_payment_methods  # noqa: PLC0415

        methods = active_payment_methods
    return payment_answer(definition, tuple(methods(tenant_id, scope.brand_id)))


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
        # The owner's category order (m-24955643): the same order the customer gets.
        order = session.scalars(
            select(BrandProductCategory.name)
            .where(BrandProductCategory.brand_id == brand_id)
            .order_by(BrandProductCategory.position, BrandProductCategory.name_key)
        ).all()
        return to_catalog_items(rows, tuple(order))


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


def _card_input(menu: MenuRecord, versions: list[MenuVersionRecord]) -> MenuCardInput:
    """What the menu's card in «Menús de este número» is built from (m-24955645)."""
    return card_input_from(
        menu_id=str(menu.id),
        name=menu.name,
        published_version_id=str(menu.published_version_id) if menu.published_version_id else None,
        is_paused=menu.is_paused,
        versions=[(str(v.id), v.version, v.created_at, v.published_at) for v in versions],
    )


def _owned_menu(
    repo: MenuRepository, tenant_id: UUID, scope: NumberScope, menu_id: UUID
) -> MenuRecord:
    menu = repo.get_menu(tenant_id=tenant_id, menu_id=menu_id)
    if menu is None or menu.phone_number_row_id != scope.phone_row_id:
        raise MenuNotFound(str(menu_id))
    return menu


def _owned_menu_any(
    repo: MenuRepository, tenant_id: UUID, scope: NumberScope, menu_id: UUID
) -> MenuRecord:
    """`_owned_menu`, archived menus included — only for `archive_menu`'s idempotency."""
    menu = repo.get_menu(tenant_id=tenant_id, menu_id=menu_id, include_archived=True)
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


def menu_overview(
    tenant_id: UUID, scope: NumberScope, *, repo: MenuRepository | None = None
) -> tuple[list[MenuSummaryVM], list[MenuCardInput]]:
    """The number's menus for the tab: their summaries and their cards' input
    (m-24955645), from one read of each menu's versions."""
    repo = repo or default_repository()
    summaries: list[MenuSummaryVM] = []
    cards: list[MenuCardInput] = []
    for menu in repo.list_menus(tenant_id=tenant_id, phone_number_row_id=scope.phone_row_id):
        versions = repo.list_versions(tenant_id=tenant_id, menu_id=menu.id)
        summaries.append(_summary(menu, versions))
        cards.append(_card_input(menu, versions))
    return summaries, cards


@dataclass(frozen=True)
class MenuDetail:
    """One open menu: its summary, its history, and the definition the editor starts
    from (the newest version; None for a menu nothing was saved to yet). `payloads` maps a
    version id to its definition JSON so «Abrir» needs no second read."""

    summary: MenuSummaryVM
    versions: list[MenuVersionVM]
    latest: MenuDefinition | None
    payloads: dict[str, dict[str, Any]]
    card: MenuCardInput | None = None  # its card in «Menús de este número»


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
        card=_card_input(menu, versions),
    )


def create_menu(
    tenant_id: UUID,
    scope: NumberScope,
    name: str,
    template: str,
    *,
    facts: StarterFacts | None = None,
    user_id: UUID | None = None,
    repo: MenuRepository | None = None,
) -> MenuDetail:
    """A new menu on the number. With the usual answers (`starter_facts` → the starter,
    m-24936836) it is saved as version 1 at once (it is valid, and leaving the tab must
    not lose it; its gaps keep it from being published); an empty menu has no version
    until its first «Guardar versión» — an empty menu is not a valid definition."""
    repo = repo or default_repository()
    menu = repo.create_menu(
        tenant_id=tenant_id,
        phone_number_row_id=scope.phone_row_id,
        name=name.strip(),
        brand_id=scope.brand_id,
        created_by_user_id=user_id,
    )
    definition = template_definition(template, facts)
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


@dataclass(frozen=True)
class ArchiveOutcome:
    """What «Eliminar» leaves on screen: the archived menu's id and name (for the toast
    and to drop it from the picker) and the number's menus after it — the same pair
    `menu_overview` returns, so the tab needs no second read. Empty lists = the number
    has no menu left (the screen shows «Este número aún no tiene menú»)."""

    menu_id: str
    name: str
    summaries: list[MenuSummaryVM]
    cards: list[MenuCardInput]


def archive_menu(
    tenant_id: UUID,
    scope: NumberScope,
    menu_id: UUID,
    *,
    repo: MenuRepository | None = None,
) -> ArchiveOutcome:
    """«Eliminar» a menu of the number on screen (m-24986800) — an archive (D1).

    Raises `MenuNotFound` (unknown id, another tenant's menu, or another number's) and
    `MenuIsAnswering` (it is the number's live menu: pause it first); both write nothing.
    Idempotent: a second call on the same menu returns the same outcome. Blocking — the
    state runs it off-thread. `SQLAlchemyError` propagates (the screen's
    «No pudimos eliminar el menú»)."""
    repo = repo or default_repository()
    menu = _owned_menu_any(repo, tenant_id, scope, menu_id)
    if menu.archived_at is None:
        menu = repo.archive_menu(tenant_id=tenant_id, menu_id=menu_id)
    summaries, cards = menu_overview(tenant_id, scope, repo=repo)
    return ArchiveOutcome(menu_id=str(menu.id), name=menu.name, summaries=summaries, cards=cards)


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
    payments_offered: Callable[[UUID, UUID | None], bool] | None = None,
) -> PublishOutcome:
    """«Publicar esta versión». Raises `MenuNotFound`/`MenuVersionNotFound`/`MenuHasGaps`
    (nothing written) and `SQLAlchemyError` from the database publish; never raises for a
    Graph failure — that is an outcome, because the database publish already happened.
    A version with a gap («[hora de abrir]») never goes live: the editor already refuses,
    this is the guarantee (m-24936836)."""
    repo = repo or default_repository()

    def publish_in_db() -> MenuDefinition:
        _owned_menu(repo, tenant_id, scope, menu_id)
        versions = repo.list_versions(tenant_id=tenant_id, menu_id=menu_id)
        version = next((v for v in versions if v.id == version_id), None)
        if version is None:
            raise MenuVersionNotFound(str(version_id))
        gaps = definition_gaps(version.definition)
        # m-24955648 §6: the starter's «Formas de pago» is composed live while the
        # business offers methods — its stored gap is never read then. Asked only when a
        # gap exists, so a menu without one never reads the methods.
        if gaps and definition_gaps(
            version.definition,
            payments_offered=(payments_offered or offers_payment_methods)(
                tenant_id, scope.brand_id
            ),
        ):
            raise MenuHasGaps(str(version_id))
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
        # Meta's code goes to the log only; the owner reads what to do next.
        logger.warning(
            "whatsapp menu automation rejected: code=%s auth=%s transport=%s",
            exc.code,
            exc.is_auth_error,
            exc.is_transport,
        )
        notice = publish_notice(graph_ok=False, is_auth_error=exc.is_auth_error)
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


# ======================================================================================
# «Mejorar mi texto» on the greeting and each answer (m-24936838)
# ======================================================================================


def suggest_text(
    tenant_id: UUID,
    brand_id: UUID | None,
    data: SuggestInput,
    *,
    client_factory: ClientFactory = default_client,
    kit_store: KitStore | None = None,
) -> SuggestProposal:
    """Claude's proposal for one field, in the voice of the number's brand. The brand
    identity is read through the tenant door (`suggest_for_brand` → `BrandKitService`);
    a number with no brand gets the neutral voice. Blocking (Claude takes seconds): the
    state runs it off-thread. Raises `SuggestUnavailable` when there is no proposal.
    Nothing is stored or published here — the owner's «Guardar» does that."""
    if brand_id is None:
        attribution = Attribution(tenant_id=tenant_id, feature=SUGGEST_FEATURE)
        return _suggest_without_brand(
            data, None, attribution=attribution, client_factory=client_factory
        )
    return suggest_for_brand(
        tenant_id, brand_id, data, client_factory=client_factory, kit_store=kit_store
    )


# ======================================================================================
# «Cargar desde una foto o mi página» (m-24936840)
# ======================================================================================


def import_menu_facts(
    source: ImportSource,
    *,
    tenant_id: UUID | None,
    brand_id: UUID | None,
    client_factory: ClientFactory = default_client,
    fetch: Fetch = default_fetch,
) -> ImportProposal:
    """Claude reads the photo, PDF or web page and PROPOSES the menu's facts and products,
    each with its quote (`import_ai.propose_menu_facts`). No database, nothing stored or
    published: the owner accepts field by field on screen. Blocking (a read takes
    seconds): the state runs it off-thread. Raises `SourceUnsupported` (a Spanish reason
    for the owner), `NothingFound` or `ImportUnavailable`."""
    attribution = (
        Attribution(tenant_id=tenant_id, brand_id=brand_id, feature=IMPORT_FEATURE)
        if tenant_id is not None
        else Attribution.no_business(IMPORT_FEATURE)
    )
    return propose_menu_facts(
        source, attribution=attribution, client_factory=client_factory, fetch=fetch
    )


class CatalogWriter(Protocol):
    """The two `CatalogService` calls this flow needs (a fake in the tests)."""

    def list_products(
        self, *, tenant_id: UUID, brand_id: UUID, include_inactive: bool = False
    ) -> tuple[Any, ...]: ...

    def create_product(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        user_id: UUID | None,
        name: str,
        price_amount: Decimal | None = None,
        price_currency: str = "",
        description: str = "",
        category: str = "",
    ) -> UUID: ...


@dataclass(frozen=True)
class AddedProducts:
    """What «Agregar los marcados a la Galería» did, by product name."""

    added: tuple[str, ...]
    existing: tuple[str, ...]  # «ya está en tu catálogo»: not created, not changed
    failed: tuple[str, ...]  # the service refused it (a name it cannot take)


def _default_catalog() -> CatalogWriter:
    # Neither `list_products` nor `create_product` touches the media store or ffmpeg.
    from qualify_api.creative.composition import media_root  # noqa: PLC0415 — heavy import
    from qualify_api.creative.media import LocalMediaStore  # noqa: PLC0415

    return CatalogService(store=LocalMediaStore(media_root()))


def _tenant_currency(tenant_id: UUID) -> str:
    from .catalog_provider import business_currency  # noqa: PLC0415 — tenant_session read

    return business_currency(tenant_id)


def add_catalog_products(
    tenant_id: UUID,
    brand_id: UUID,
    products: Sequence[FoundProduct],
    user_id: UUID | None,
    *,
    catalog: CatalogWriter | None = None,
    currency: str | None = None,
) -> AddedProducts:
    """Create the products the owner ticked, through the catalog service (every read and
    write is `tenant_session(tenant_id)`). A name already in the brand's catalog, active
    or archived (the whole name, case and accents folded — never a part of it: «Pan» is
    not «Empanada») is NOT created and is reported in `existing`: this flow never
    changes a product or a price that is already there. A price whose currency the
    source did not say takes the business's own currency (`tenants.currency`) — the menu
    is the business's, so its prices are in that currency. No photo: the owner adds it
    later in Galería."""
    service = catalog or _default_catalog()
    taken = {
        normalize_keyword(p.name)
        # Archived products count too: one the owner removed is not created again.
        for p in service.list_products(
            tenant_id=tenant_id, brand_id=brand_id, include_inactive=True
        )
    }
    fallback: str | None = currency
    added: list[str] = []
    existing: list[str] = []
    failed: list[str] = []
    for product in products:
        name = " ".join(product.name.split())
        key = normalize_keyword(name)
        if not key:
            continue
        if key in taken:
            existing.append(name)
            continue
        code = product.price_currency
        if product.price_amount is not None and not code:
            if fallback is None:
                fallback = _tenant_currency(tenant_id)
            code = fallback
        try:
            service.create_product(
                tenant_id=tenant_id,
                brand_id=brand_id,
                user_id=user_id,
                name=name,
                price_amount=product.price_amount,
                price_currency=code if product.price_amount is not None else "",
                description=product.description,
                # m-24955643: a category the owner set while reviewing the import.
                **({"category": product.category.strip()} if product.category.strip() else {}),
            )
        except CatalogError:
            failed.append(name)
            continue
        taken.add(key)
        added.append(name)
    return AddedProducts(tuple(added), tuple(existing), tuple(failed))


__all__ = [
    "AddedProducts",
    "ArchiveOutcome",
    "CatalogWriter",
    "FoundProduct",
    "ImportProposal",
    "ImportSource",
    "ImportUnavailable",
    "NothingFound",
    "SourceUnsupported",
    "add_catalog_products",
    "archive_menu",
    "import_menu_facts",
    "MenuDetail",
    "MenuHasGaps",
    "MenuIsAnswering",
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
    "starter_facts",
    "store_published_automation",
    "SuggestInput",
    "SuggestProposal",
    "SuggestUnavailable",
    "suggest_text",
    "user_id_for",
]

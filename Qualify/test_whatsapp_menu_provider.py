"""Network-free tests for `whatsapp_menu_provider` (WA-16).

The repository is WA-14's `MemoryMenuRepository` (same contract as the Postgres one) and
Graph is a fake client behind the injectable `opener`, so nothing here touches Meta,
Postgres or a credential. They pin:

- a menu belongs to ONE number: a menu id from another number is refused;
- «Nuevo menú» from the example saves version 1, an empty one saves nothing;
- publishing = database first, then `set_conversational_automation` with exactly
  `to_conversational_automation(definition)`; the body is recorded on success;
- a Graph refusal keeps the database publish and reports Meta's code; an auth error
  also degrades the connection; an infrastructure failure never leaks its text;
- structural guarantees: Postgres only through `tenant_session`, Graph only through the
  shared `open_whatsapp_client`, no token handling.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from qualify_api.whatsapp.client import ConversationalAutomation, WhatsAppApiError
from qualify_api.whatsapp.menus import (
    MemoryMenuRepository,
    MenuIsAnswering,
    MenuNotFound,
    MenuVersionNotFound,
)
from qualify_api.whatsapp.menus.automation import to_conversational_automation
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.menus.starter import MenuHasGaps, StarterFacts, build_starter_menu

from . import whatsapp_menu_provider
from .whatsapp_menu_provider import (
    ArchiveOutcome,
    NumberScope,
    archive_menu,
    automation_for,
    create_menu,
    menu_detail,
    menus_for,
    publish_version,
    save_version,
    set_paused,
    starter_facts,
)
from .whatsapp_menu_vm import (
    TEMPLATE_EMPTY,
    TEMPLATE_FAST_FOOD,
    definition_to_form,
    form_to_payload,
)

TENANT = UUID("00000000-0000-0000-0000-0000000000aa")
CONNECTION = UUID("00000000-0000-0000-0000-0000000000bb")
SCOPE = NumberScope(phone_row_id=uuid4(), brand_id=uuid4(), brand_name="Bianki")
OTHER_NUMBER = NumberScope(phone_row_id=uuid4(), brand_id=None, brand_name="Otra")


class FakeClient:
    def __init__(self, fail_with: Exception | None = None) -> None:
        self.calls: list[ConversationalAutomation] = []
        self.fail_with = fail_with

    async def set_conversational_automation(self, automation: ConversationalAutomation) -> None:
        self.calls.append(automation)
        if self.fail_with is not None:
            raise self.fail_with


class Harness:
    def __init__(self, fail_with: Exception | None = None) -> None:
        self.client = FakeClient(fail_with)
        self.repo = MemoryMenuRepository()
        self.degraded: list[tuple[UUID, UUID]] = []
        self.stored: list[tuple[UUID, UUID, dict[str, Any]]] = []
        self.opened: list[tuple[UUID, UUID]] = []

    @asynccontextmanager
    async def opener(self, tenant_id: UUID, connection_id: UUID) -> AsyncIterator[FakeClient]:
        self.opened.append((tenant_id, connection_id))
        yield self.client

    def degrader(self, *, tenant_id: UUID, connection_id: UUID) -> None:
        self.degraded.append((tenant_id, connection_id))

    def store(self, tenant_id: UUID, connection_id: UUID, automation: dict[str, Any]) -> None:
        self.stored.append((tenant_id, connection_id, automation))

    async def publish(self, menu_id: UUID, version_id: UUID, scope: NumberScope = SCOPE) -> Any:
        return await publish_version(
            TENANT,
            CONNECTION,
            scope,
            menu_id,
            version_id,
            repo=self.repo,
            opener=self.opener,
            degrader=self.degrader,
            store_automation=self.store,
        )


def _example_menu(h: Harness, name: str = "Principal") -> tuple[UUID, UUID]:
    """A menu whose version 1 is the complete example (no gaps: publishable)."""
    created = create_menu(TENANT, SCOPE, name, TEMPLATE_EMPTY, repo=h.repo)
    menu_id = UUID(created.summary.menu_id)
    payload = BIANKI_DEMO_MENU.model_dump(mode="json")
    detail = save_version(TENANT, SCOPE, menu_id, payload, repo=h.repo)
    return menu_id, UUID(detail.versions[0].version_id)


# --- menus ------------------------------------------------------------------------------


def test_create_with_the_usual_answers_saves_version_one() -> None:
    h = Harness()
    facts = StarterFacts(business_name="La Esquina")
    detail = create_menu(
        TENANT, SCOPE, "  Principal ", TEMPLATE_FAST_FOOD, facts=facts, repo=h.repo
    )
    assert detail.summary.name == "Principal"
    assert [v.label for v in detail.versions] == ["Versión 1"]
    assert detail.latest == build_starter_menu(facts)
    assert detail.latest != BIANKI_DEMO_MENU  # never the invented example
    assert detail.summary.published_label == "Sin publicar"
    assert detail.summary.status_label == "Sin publicar"


def test_create_empty_saves_nothing() -> None:
    h = Harness()
    detail = create_menu(TENANT, SCOPE, "Vacío", TEMPLATE_EMPTY, repo=h.repo)
    assert detail.versions == [] and detail.latest is None


def test_menus_are_listed_per_number_only() -> None:
    h = Harness()
    create_menu(TENANT, SCOPE, "Principal", TEMPLATE_EMPTY, repo=h.repo)
    create_menu(TENANT, OTHER_NUMBER, "Del otro", TEMPLATE_EMPTY, repo=h.repo)
    assert [m.name for m in menus_for(TENANT, SCOPE, repo=h.repo)] == ["Principal"]


def test_a_menu_of_another_number_is_refused() -> None:
    h = Harness()
    menu_id, _ = _example_menu(h)
    with pytest.raises(MenuNotFound):
        menu_detail(TENANT, OTHER_NUMBER, menu_id, repo=h.repo)
    with pytest.raises(MenuNotFound):
        set_paused(TENANT, OTHER_NUMBER, menu_id, True, repo=h.repo)
    with pytest.raises(MenuNotFound):
        save_version(TENANT, OTHER_NUMBER, menu_id, BIANKI_DEMO_MENU.model_dump(), repo=h.repo)


def test_save_version_numbers_up_and_validates_again() -> None:
    h = Harness()
    menu_id, _ = _example_menu(h)
    payload = form_to_payload(definition_to_form(BIANKI_DEMO_MENU))
    detail = save_version(TENANT, SCOPE, menu_id, payload, repo=h.repo)
    assert [v.label for v in detail.versions] == ["Versión 2", "Versión 1"]  # newest first
    bad = {**payload, "start_node": "nope"}
    with pytest.raises(ValidationError):
        save_version(TENANT, SCOPE, menu_id, bad, repo=h.repo)
    assert len(menu_detail(TENANT, SCOPE, menu_id, repo=h.repo).versions) == 2


def test_pause_toggles_the_status() -> None:
    h = Harness()
    menu_id, version_id = _example_menu(h)
    h.repo.publish_version(tenant_id=TENANT, menu_id=menu_id, version_id=version_id, user_id=None)
    detail = set_paused(TENANT, SCOPE, menu_id, True, repo=h.repo)
    assert detail.summary.is_paused and detail.summary.status_label == "En pausa"
    assert detail.summary.status_tone == "warn"
    detail = set_paused(TENANT, SCOPE, menu_id, False, repo=h.repo)
    assert detail.summary.status_label == "Respondiendo a tus clientes"


# --- «Eliminar» = archive (m-24986800, decision D1) -------------------------------------


def test_archive_refuses_the_answering_menu_and_writes_nothing() -> None:
    h = Harness()
    menu_id, version_id = _example_menu(h)
    h.repo.publish_version(tenant_id=TENANT, menu_id=menu_id, version_id=version_id, user_id=None)
    with pytest.raises(MenuIsAnswering):
        archive_menu(TENANT, SCOPE, menu_id, repo=h.repo)
    assert [m.name for m in menus_for(TENANT, SCOPE, repo=h.repo)] == ["Principal"]
    assert h.repo.load_published_menu_for_phone(SCOPE.phone_row_id) is not None


def test_archive_a_paused_menu_returns_the_menus_left() -> None:
    h = Harness()
    live_id, live_version = _example_menu(h, "Navidad")
    paused_id, paused_version = _example_menu(h, "Principal")
    h.repo.publish_version(
        tenant_id=TENANT, menu_id=paused_id, version_id=paused_version, user_id=None
    )
    set_paused(TENANT, SCOPE, paused_id, True, repo=h.repo)
    outcome = archive_menu(TENANT, SCOPE, paused_id, repo=h.repo)
    assert isinstance(outcome, ArchiveOutcome)
    assert (outcome.menu_id, outcome.name) == (str(paused_id), "Principal")
    assert [m.name for m in outcome.summaries] == ["Navidad"]
    assert [c.menu_id for c in outcome.cards] == [str(live_id)]
    # Gone from the tab and from every call that takes its id; never answers.
    assert [m.name for m in menus_for(TENANT, SCOPE, repo=h.repo)] == ["Navidad"]
    with pytest.raises(MenuNotFound):
        menu_detail(TENANT, SCOPE, paused_id, repo=h.repo)
    with pytest.raises(MenuNotFound):
        set_paused(TENANT, SCOPE, paused_id, False, repo=h.repo)
    assert h.repo.load_published_menu_for_phone(SCOPE.phone_row_id) is None


async def test_an_archived_menu_cannot_be_published() -> None:
    h = Harness()
    menu_id, version_id = _example_menu(h)
    archive_menu(TENANT, SCOPE, menu_id, repo=h.repo)
    with pytest.raises(MenuNotFound):
        await h.publish(menu_id, version_id)
    assert h.client.calls == [] and h.opened == []


def test_archive_is_idempotent_and_the_last_menu_leaves_the_number_empty() -> None:
    h = Harness()
    menu_id, _ = _example_menu(h)
    first = archive_menu(TENANT, SCOPE, menu_id, repo=h.repo)
    again = archive_menu(TENANT, SCOPE, menu_id, repo=h.repo)
    assert first == again
    assert (first.summaries, first.cards) == ([], [])


def test_archive_refuses_another_numbers_or_tenants_menu() -> None:
    h = Harness()
    menu_id, _ = _example_menu(h)
    with pytest.raises(MenuNotFound):
        archive_menu(TENANT, OTHER_NUMBER, menu_id, repo=h.repo)
    with pytest.raises(MenuNotFound):
        archive_menu(uuid4(), SCOPE, menu_id, repo=h.repo)
    with pytest.raises(MenuNotFound):
        archive_menu(TENANT, SCOPE, uuid4(), repo=h.repo)
    assert [m.name for m in menus_for(TENANT, SCOPE, repo=h.repo)] == ["Principal"]


# --- publish ----------------------------------------------------------------------------


async def test_publish_calls_the_client_with_the_definitions_automation() -> None:
    h = Harness()
    menu_id, version_id = _example_menu(h)
    outcome = await h.publish(menu_id, version_id)

    assert outcome.graph_ok and outcome.tone == "ok"
    assert h.opened == [(TENANT, CONNECTION)]
    [sent] = h.client.calls
    assert sent.ice_breakers == ["Ver menú", "Hacer pedido", "Horario", "Ubicación"]
    assert [(c.name, c.hint) for c in sent.commands] == [
        ("menu", "Ver el menú y hacer un pedido"),
        ("horario", "Horario de atención"),
        ("ubicacion", "Dónde estamos"),
        ("persona", "Hablar con una persona del equipo"),
    ]
    assert sent.enable_welcome_message is True
    # The recorded body is exactly the WA-14 automation, the same datum.
    assert h.stored == [(TENANT, CONNECTION, to_conversational_automation(BIANKI_DEMO_MENU))]
    assert outcome.detail.summary.published_label == "Publicado: versión 1"
    assert outcome.detail.versions[0].is_live
    assert outcome.detail.versions[0].published_at != ""


def test_automation_for_matches_the_wa14_body() -> None:
    automation = automation_for(BIANKI_DEMO_MENU)
    body = to_conversational_automation(BIANKI_DEMO_MENU)
    assert automation.ice_breakers == body["prompts"]
    assert [
        {"command_name": c.name, "command_description": c.hint} for c in automation.commands
    ] == (body["commands"])
    assert automation.enable_welcome_message == body["enable_welcome_message"]


async def test_publish_with_a_graph_error_keeps_the_db_publish() -> None:
    h = Harness(fail_with=WhatsAppApiError("bad param", status=400, code=100))
    menu_id, version_id = _example_menu(h)
    outcome = await h.publish(menu_id, version_id)

    assert not outcome.graph_ok and not outcome.auth_error
    assert outcome.notice.startswith(
        "Tu WhatsApp ya responde con este menú, pero no tomó los atajos de inicio."
    )
    assert "100" not in outcome.notice and "código" not in outcome.notice
    assert outcome.tone == "warn"
    assert h.degraded == [] and h.stored == []
    menu = h.repo.get_menu(tenant_id=TENANT, menu_id=menu_id)
    assert menu is not None and menu.published_version_id == version_id
    assert outcome.detail.summary.is_published


async def test_publish_with_an_auth_error_degrades_the_connection() -> None:
    h = Harness(fail_with=WhatsAppApiError("expired", status=401, code=190))
    menu_id, version_id = _example_menu(h)
    outcome = await h.publish(menu_id, version_id)
    assert outcome.auth_error and outcome.tone == "error"
    assert (
        outcome.notice.startswith(
            "Tu WhatsApp ya responde con este menú, pero no tomó los atajos de inicio."
        )
        and "190" not in outcome.notice
    )
    assert h.degraded == [(TENANT, CONNECTION)]
    assert outcome.detail.summary.is_published


async def test_publish_with_an_infrastructure_error_never_leaks_its_text() -> None:
    import httpx

    h = Harness(fail_with=httpx.ConnectError("secret-host:443 refused"))
    menu_id, version_id = _example_menu(h)
    outcome = await h.publish(menu_id, version_id)
    assert not outcome.graph_ok
    assert "secret-host" not in outcome.notice
    assert outcome.notice.startswith(
        "Tu WhatsApp ya responde con este menú, pero no tomó los atajos de inicio."
    )
    assert "Vuelve a tocar «Publicar en mi WhatsApp»" in outcome.notice


async def test_publish_a_client_side_limit_refusal() -> None:
    h = Harness(fail_with=ValueError("ice breaker contains emoji"))
    menu_id, version_id = _example_menu(h)
    outcome = await h.publish(menu_id, version_id)
    assert "emojis" in outcome.notice and outcome.tone == "warn"


async def test_publish_refuses_a_version_of_another_menu_before_any_write() -> None:
    h = Harness()
    menu_id, _ = _example_menu(h)
    _other_id, other_version = _example_menu(h, "Otro")
    with pytest.raises(MenuVersionNotFound):
        await h.publish(menu_id, other_version)
    with pytest.raises(MenuNotFound):
        await h.publish(menu_id, uuid4(), scope=OTHER_NUMBER)
    assert h.client.calls == []
    menu = h.repo.get_menu(tenant_id=TENANT, menu_id=menu_id)
    assert menu is not None and menu.published_version_id is None


async def test_publishing_another_menu_demotes_the_first() -> None:
    h = Harness()
    first_id, first_version = _example_menu(h)
    await h.publish(first_id, first_version)
    second_id, second_version = _example_menu(h, "Segundo")
    await h.publish(second_id, second_version)
    names = {m.name: m.is_published for m in menus_for(TENANT, SCOPE, repo=h.repo)}
    assert names == {"Principal": False, "Segundo": True}


async def test_a_version_with_gaps_is_never_published() -> None:
    h = Harness()
    detail = create_menu(TENANT, SCOPE, "Con huecos", TEMPLATE_FAST_FOOD, repo=h.repo)
    menu_id, version_id = UUID(detail.summary.menu_id), UUID(detail.versions[0].version_id)
    with pytest.raises(MenuHasGaps):
        await h.publish(menu_id, version_id)
    assert h.client.calls == [] and h.opened == []
    menu = h.repo.get_menu(tenant_id=TENANT, menu_id=menu_id)
    assert menu is not None and menu.published_version_id is None


class _FakeStore:
    def __init__(self, connect: dict[str, Any]) -> None:
        self.connect = connect
        self.calls: list[tuple[UUID, UUID]] = []

    def load_details(self, *, tenant_id: UUID, brand_id: UUID) -> Any:
        self.calls.append((tenant_id, brand_id))
        return type("Details", (), {"connect": self.connect})()


def test_starter_facts_read_the_brand_and_take_the_address_on_screen() -> None:
    store = _FakeStore({"city": " Villa Clara ", "sector": "comida"})
    scope = NumberScope(
        phone_row_id=uuid4(), brand_id=uuid4(), brand_name="La Esquina", business_name="La Esquina"
    )
    facts = starter_facts(
        TENANT,
        scope,
        address=" Av. 5 ",
        store=store,  # type: ignore[arg-type]
        payment_names=lambda tenant, brand: ("Pago móvil", "Efectivo"),
    )
    assert facts == StarterFacts(
        business_name="La Esquina",
        address="Av. 5",
        city="Villa Clara",
        sector="comida",
        payment_methods=("Pago móvil", "Efectivo"),
    )
    assert store.calls == [(TENANT, scope.brand_id)]
    no_brand = NumberScope(phone_row_id=uuid4(), brand_id=None, brand_name="la marca")
    assert starter_facts(TENANT, no_brand, store=store) == StarterFacts()  # type: ignore[arg-type]
    assert len(store.calls) == 1  # no brand, no read


# --- structure --------------------------------------------------------------------------


def test_postgres_only_through_tenant_session_and_graph_only_through_the_resolver() -> None:
    source = inspect.getsource(whatsapp_menu_provider)
    assert "tenant_session(" in source
    for forbidden in ("admin_session", "credential_session", "create_engine", "Session("):
        assert forbidden not in source, forbidden
    assert "open_whatsapp_client" in source
    for forbidden in ("access_token", "ciphertext", "Authorization", "decrypt"):
        assert forbidden not in source, forbidden

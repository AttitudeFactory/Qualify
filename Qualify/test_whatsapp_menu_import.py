"""m-24936840: «Cargar desde una foto o mi página» in `/whatsapp` → Respuesta automática.
Spec: docs/ux-whatsapp-respuestas-de-siempre.md §4 and §6. The reader is faked: no
Claude call, no network, no database; the only write (products) goes to a fake catalog.
"""

from __future__ import annotations

import inspect
import json
import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.catalog.service import CatalogError
from qualify_api.whatsapp.menus.import_ai import (
    REASON_SOCIAL,
    FoundFact,
    FoundProduct,
    ImportProposal,
    ImportSource,
    ImportUnavailable,
    NothingFound,
    SourceUnsupported,
)
from qualify_api.whatsapp.menus.starter import (
    HOURS_TEXT,
    PAYMENT_TEXT,
    StarterFacts,
    build_starter_menu,
    find_gaps,
)

from . import whatsapp_menu_state as module
from .whatsapp_menu_provider import AddedProducts, MenuDetail, add_catalog_products
from .whatsapp_menu_state import WhatsAppMenuState
from .whatsapp_menu_vm import (
    FACT_SKIPPED,
    FACT_USED,
    IMPORT_CHOOSE,
    IMPORT_EMPTY_PHASE,
    IMPORT_FAILED,
    IMPORT_FAILED_PHASE,
    IMPORT_PAGE,
    IMPORT_PAGE_NEEDS_LINK,
    IMPORT_PHOTO,
    IMPORT_REVIEW,
    MenuSummaryVM,
    MenuVersionVM,
    definition_to_form,
    fact_plan,
    fill_fact,
    import_empty_text,
    import_view,
    product_rows,
    read_answers,
)

TENANT = uuid4()
BRAND = uuid4()
WARN = (
    "Revisa cada dato con tu foto antes de usarlo: lo leímos de la imagen y puede haber "
    "algún error."
)


class _Proxy:
    """Reflex's StateProxy in a test: `async with self` is a no-op lock."""

    def __init__(self, state: WhatsAppMenuState) -> None:
        object.__setattr__(self, "_state", state)

    async def __aenter__(self) -> _Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __getattr__(self, name: str) -> object:
        return getattr(self._state, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._state, name, value)


class _Upload:
    def __init__(self, data: bytes, name: str = "menu.jpg") -> None:
        self.data, self.name = data, name

    async def read(self, size: int = -1) -> bytes:
        return self.data if size < 0 else self.data[:size]


class _Reader:
    """Records every `ImportSource`; answers with the queued proposals (or raises)."""

    def __init__(self, *answers: ImportProposal | Exception) -> None:
        self.answers = list(answers)
        self.calls: list[ImportSource] = []
        #: Who each read is booked to (m-24955649).
        self.payers: list[dict[str, object]] = []

    def __call__(self, source: ImportSource, **payer: object) -> ImportProposal:
        self.calls.append(source)
        self.payers.append(payer)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _proposal(
    facts: tuple[FoundFact, ...] = (),
    products: tuple[FoundProduct, ...] = (),
    *,
    kind: str = "image",
    label: str = "menu.jpg",
    warnings: tuple[str, ...] = (WARN,),
) -> ImportProposal:
    return ImportProposal(
        facts=facts,
        products=products,
        source_kind=kind,
        source_label=label,
        warnings=warnings,
        model_id="claude-sonnet-5-5",
        input_tokens=1,
        output_tokens=1,
    )


HOURS = FoundFact("hours", "lunes a domingo, de 12:00 m. a 10:00 p. m.", "Lun a Dom 12m - 10pm")
PAYMENT = FoundFact("payment_methods", "efectivo y pago móvil", "Pago móvil · Efectivo")
ZONE = FoundFact("delivery_zone", "todo el centro", "Domicilios a todo el centro")
SHAWARMA = FoundProduct("Shawarma mixto", Decimal("6"), "USD", "", "Shawarma mixto 6 $")
FALAFEL = FoundProduct("Falafel", Decimal("4"), "", "", "Falafel 4")
SALAD = FoundProduct("Ensalada del día", None, "", "", "Ensalada del día")


def _state(monkeypatch: pytest.MonkeyPatch, reader: _Reader) -> WhatsAppMenuState:
    async def session(self: object) -> tuple[str, UUID | None, str]:
        return str(TENANT), TENANT, "duena@example.com"

    async def connection(self: object) -> str:
        return "conn-1"

    def no_write(*_a: object, **_k: object) -> None:
        raise AssertionError("nothing is saved without «Guardar»")

    monkeypatch.setattr(WhatsAppMenuState, "_session", session)
    monkeypatch.setattr(WhatsAppMenuState, "_connection_id", connection)
    monkeypatch.setattr(module, "import_menu_facts", reader)
    monkeypatch.setattr(module, "business_currency", lambda tenant: "COP")
    for write in ("save_version", "publish_version", "create_menu"):
        monkeypatch.setattr(module, write, no_write)

    definition = build_starter_menu(StarterFacts(business_name="La Esquina"))
    menu_id, version_id = str(uuid4()), str(uuid4())
    summary = MenuSummaryVM(
        menu_id=menu_id,
        name="Menú principal",
        published_label="Sin publicar",
        is_published=False,
        is_paused=False,
        status_label="Sin publicar",
        status_tone="neutral",
        updated_at="hoy",
    )
    version = MenuVersionVM(
        version_id=version_id, label="Versión 1", created_at="hoy", published_at="", is_live=False
    )
    state = WhatsAppMenuState()
    state._scope = {
        "phone_row_id": str(uuid4()),
        "brand_id": str(BRAND),
        "brand_name": "La Esquina",
        "business_name": "La Esquina",
    }
    state._catalog = [
        {
            "product_id": str(uuid4()),
            "name": "SHAWARMA Mixto",
            "price_amount": "5",
            "price_currency": "USD",
            "category": "",
        }
    ]
    state.menus = [summary]
    state._show_detail(
        MenuDetail(
            summary=summary,
            versions=[version],
            latest=definition,
            payloads={version_id: definition.model_dump(mode="json")},
        ),
        load_form=True,
    )
    return state


async def _run(handler: Any, state: WhatsAppMenuState) -> list[Any]:
    """Run a background handler; the events it yields (if it is a generator)."""
    result = handler.fn(_Proxy(state))
    if inspect.isasyncgen(result):
        return [event async for event in result]
    await result
    return []


async def _upload(state: WhatsAppMenuState, data: bytes = b"\xff\xd8\xff-photo") -> None:
    state.open_import()
    state.choose_import_source(IMPORT_PHOTO)
    await WhatsAppMenuState.handle_import_upload.fn(state, [_Upload(data)])
    await _run(WhatsAppMenuState.read_import_file, state)


def _text(state: WhatsAppMenuState, label: str) -> str:
    form = state._form()
    for a in read_answers(form):
        if a.label == label:
            return next(n.body for n in form.nodes if n.node_id == a.next)
    raise KeyError(label)


def _fact(state: WhatsAppMenuState, key: str) -> int:
    return next(i for i, f in enumerate(state._import_facts) if f["key"] == key)


# --- reading -------------------------------------------------------------------------------


async def test_upload_reads_the_photo_and_shows_the_review_without_touching_the_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _Reader(_proposal((HOURS, PAYMENT), (SHAWARMA,)))
    state = _state(monkeypatch, reader)
    before = dict(state._valid_payload)
    await _upload(state)
    assert reader.calls == [ImportSource(filename="menu.jpg", data=b"\xff\xd8\xff-photo")]
    # m-24955649: the paid read is booked to the business on screen
    assert reader.payers[0]["tenant_id"] == TENANT
    assert state.import_phase == IMPORT_REVIEW and state.suggest_busy == ""
    review = state.import_review
    assert review.title == "Esto encontramos en tu foto"
    assert review.warnings == [WARN]  # «revisa cada dato con tu foto»
    assert [f.title for f in review.facts] == ["Horario", "Formas de pago"]
    hours = review.facts[0]
    assert hours.evidence_line == "En tu foto dice: «Lun a Dom 12m - 10pm»"
    assert hours.note == "Así queda tu respuesta «Horario»:"
    assert hours.preview.startswith("Abrimos de lunes a domingo, de 12:00 m. a 10:00 p. m.")
    # «Domicilio» was not in the photo: it says so and stays for the owner
    assert any(line.startswith("Domicilio: no lo encontramos") for line in review.not_found)
    # nothing changed without «Usar», nothing saved, the staged file is gone
    assert state._valid_payload == before and not state.dirty
    assert state._import_staged == ""


async def test_use_fills_the_right_gaps_and_no_use_leaves_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch, _Reader(_proposal((HOURS, PAYMENT, ZONE))))
    await _upload(state)
    state.use_import_fact(_fact(state, "hours"))
    assert _text(state, "Horario") == (
        "Abrimos de lunes a domingo, de 12:00 m. a 10:00 p. m. Cuando quieras pedir, "
        "escribe *menú*."
    )
    state.skip_import_fact(_fact(state, "payment_methods"))
    assert _text(state, "Formas de pago") == PAYMENT_TEXT
    state.use_import_fact(_fact(state, "delivery_zone"))
    delivery = _text(state, "Domicilio")
    assert delivery.startswith("Llevamos tu pedido a todo el centro.")
    assert find_gaps(delivery) == ["precio del envío", "minutos"]  # the others stay
    statuses = [f["status"] for f in state._import_facts]
    assert statuses == [FACT_USED, FACT_SKIPPED, FACT_USED]
    assert state.dirty  # on screen only: saved by the owner's own «Guardar»
    # a used fact cannot be used twice
    state.use_import_fact(_fact(state, "hours"))
    assert _text(state, "Horario").count("lunes a domingo") == 1


async def test_edit_changes_the_value_before_use(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch, _Reader(_proposal((PAYMENT,))))
    await _upload(state)
    state.edit_import_fact(0)
    assert state.import_review.facts[0].editing
    state.set_import_fact_value("efectivo, Nequi y pago móvil")
    assert "Nequi" in state.import_review.facts[0].preview
    state.use_import_fact(0)
    assert _text(state, "Formas de pago").startswith("Puedes pagar con efectivo, Nequi y pago")


async def test_a_removed_answer_is_offered_again_with_the_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch, _Reader(_proposal((HOURS,))))
    index = next(
        a.index for a in state.answers.buttons + state.answers.rows if a.label == "Horario"
    )
    state.open_answer_panel(index)
    state.ask_remove_answer()
    state.remove_answer()
    assert "Horario" not in [a.label for a in read_answers(state._form())]
    await _upload(state)
    fact = state.import_review.facts[0]
    assert fact.note.startswith("Quitaste la respuesta «Horario».") and fact.can_use
    state.use_import_fact(0)
    assert _text(state, "Horario").startswith("Abrimos de lunes a domingo")


async def test_the_page_link_path(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = _Reader(_proposal((HOURS,), kind="url", label="bianki.com", warnings=()))
    state = _state(monkeypatch, reader)
    state.open_import()
    state.choose_import_source(IMPORT_PAGE)
    await _run(WhatsAppMenuState.submit_import_url, state)
    assert state.import_url_error == IMPORT_PAGE_NEEDS_LINK and reader.calls == []
    state.set_import_url("  bianki.com/menu ")
    await _run(WhatsAppMenuState.submit_import_url, state)
    assert reader.calls == [ImportSource(url="bianki.com/menu")]
    assert state.import_review.title == "Esto encontramos en tu página"
    assert state.import_review.facts[0].evidence_line.startswith("En tu página dice: «")


async def test_an_unsupported_source_shows_its_own_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch, _Reader(SourceUnsupported(REASON_SOCIAL)))
    state.open_import()
    state.choose_import_source(IMPORT_PAGE)
    state.set_import_url("instagram.com/bianki")
    await _run(WhatsAppMenuState.submit_import_url, state)
    assert state.import_phase == IMPORT_FAILED_PHASE and state.import_error == REASON_SOCIAL
    state.import_back()  # «Probar otro enlace»
    assert state.import_phase == IMPORT_PAGE


async def test_nothing_found_and_a_failed_read(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch, _Reader(NothingFound("x"), ImportUnavailable("budget")))
    await _upload(state)
    assert state.import_phase == IMPORT_EMPTY_PHASE
    assert state.import_error == import_empty_text("image")
    assert "No encontramos horarios, precios ni formas de pago en esta foto." in state.import_error
    state.import_back()  # «Probar otra foto»
    assert state.import_phase == IMPORT_PHOTO
    await WhatsAppMenuState.handle_import_upload.fn(state, [_Upload(b"\xff\xd8\xff")])
    await _run(WhatsAppMenuState.read_import_file, state)
    assert state.import_phase == IMPORT_FAILED_PHASE and state.import_error == IMPORT_FAILED
    state.close_import()  # «Seguir sin la foto»
    assert state.import_phase == "" and not state.dirty


async def test_a_late_result_after_switching_menu_or_cancelling_is_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    box: list[WhatsAppMenuState] = []

    def switch(source: ImportSource, **_payer: object) -> ImportProposal:
        box[0]._load_definition(None, "Otro menú")  # another menu / number meanwhile
        assert box[0].suggest_busy == "import"  # the slot is still held
        return _proposal((HOURS,))

    state = _state(monkeypatch, _Reader())
    box.append(state)
    monkeypatch.setattr(module, "import_menu_facts", switch)
    await _upload(state)
    assert state.import_phase == "" and state._import_facts == []
    assert state.suggest_busy == ""

    def cancel(source: ImportSource, **_payer: object) -> ImportProposal:
        box[0].close_import()  # «Cancelar»
        return _proposal((HOURS,))

    state2 = _state(monkeypatch, _Reader())
    box[0] = state2
    monkeypatch.setattr(module, "import_menu_facts", cancel)
    await _upload(state2)
    assert state2.import_phase == "" and state2._import_facts == []
    assert state2.suggest_busy == ""


async def test_one_read_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = _Reader(_proposal((HOURS,)))
    state = _state(monkeypatch, reader)
    state.open_import()
    state.choose_import_source(IMPORT_PAGE)
    state.set_import_url("bianki.com")
    state.suggest_busy = "greeting"  # «Mejorar mi texto» is writing
    await _run(WhatsAppMenuState.submit_import_url, state)
    assert reader.calls == [] and state.import_phase == IMPORT_PAGE


async def test_a_slow_read_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    box: list[WhatsAppMenuState] = []
    seen: list[bool] = []

    def slow(source: ImportSource, **_payer: object) -> ImportProposal:
        time.sleep(0.3)
        seen.append(box[0].import_slow)
        return _proposal((HOURS,))

    state = _state(monkeypatch, _Reader())
    box.append(state)
    monkeypatch.setattr(module, "import_menu_facts", slow)
    monkeypatch.setattr(module, "IMPORT_SLOW_AFTER", 0.05)
    await _upload(state)
    assert seen == [True] and not state.import_slow and state.import_phase == IMPORT_REVIEW


def test_a_rejected_file_says_what_to_upload() -> None:
    state = WhatsAppMenuState()
    state.import_phase = IMPORT_PHOTO
    state.import_file_rejected([{"name": "IMG_1.HEIC"}])
    assert state.import_phase == IMPORT_FAILED_PHASE
    assert "JPG, PNG o WEBP" in state.import_error


# --- products ------------------------------------------------------------------------------


async def test_products_dedupe_against_the_catalog_and_default_ticks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch, _Reader(_proposal((), (SHAWARMA, FALAFEL, SALAD))))
    await _upload(state)
    review = state.import_review
    assert review.products_title == "Productos: 3 en tu foto"
    assert review.existing_line == "1 ya está en la Galería: no lo cambiamos."
    assert review.conflicts == [
        "SHAWARMA Mixto: en tu foto dice USD 6 y en la Galería USD 5. Dejamos el de la "
        "Galería; si cambió, cámbialo ahí."
    ]
    # a bare «$»: saved in the business's own currency, and the row says so first
    falafel = next(p for p in review.new_products if p.name == "Falafel")
    assert falafel.price == "COP 4 (moneda de tu negocio)"
    assert review.checked_line == "Marcamos los que tienen precio (1 de 2)"
    assert [(p.name, p.checked) for p in review.new_products] == [
        ("Falafel", True),  # with a price: ticked
        ("Ensalada del día", False),  # without: not
    ]
    assert review.checked_count == 1


async def test_add_creates_only_the_ticked_new_products(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[UUID, UUID, list[FoundProduct]]] = []

    currencies: list[str | None] = []

    def add(
        tenant_id: UUID,
        brand_id: UUID,
        products: list[FoundProduct],
        user_id: Any,
        *,
        currency: str | None = None,
    ) -> AddedProducts:
        calls.append((tenant_id, brand_id, list(products)))
        currencies.append(currency)
        return AddedProducts(tuple(p.name for p in products), (), ())

    monkeypatch.setattr(module, "add_catalog_products", add)
    monkeypatch.setattr(module, "user_id_for", lambda tenant, email: None)
    monkeypatch.setattr(module, "preview_catalog", lambda tenant, brand: ())
    state = _state(monkeypatch, _Reader(_proposal((), (SHAWARMA, FALAFEL, SALAD))))
    await _upload(state)
    salad = next(p.index for p in state.import_review.new_products if p.name == "Ensalada del día")
    state.toggle_import_product(salad, True)
    await _run(WhatsAppMenuState.add_import_products, state)
    assert len(calls) == 1 and calls[0][:2] == (TENANT, BRAND)
    assert [p.name for p in calls[0][2]] == ["Falafel", "Ensalada del día"]  # never Shawarma
    assert calls[0][2][0].price_amount == Decimal("4")
    assert currencies == ["COP"]  # the same currency the row showed
    assert state.import_review.added_lines[0].startswith("Agregamos 2 productos a la Galería.")
    assert not state.import_adding


class _Catalog:
    def __init__(self, names: list[str], refuse: str = "", archived: list[str] | None = None):
        self.names, self.refuse, self.archived = names, refuse, archived or []
        self.created: list[dict[str, Any]] = []

    def list_products(self, *, tenant_id: UUID, brand_id: UUID, include_inactive: bool = False):
        names = self.names + (self.archived if include_inactive else [])
        return tuple(type("P", (), {"name": n})() for n in names)

    def create_product(self, **kwargs: Any) -> UUID:
        if kwargs["name"] == self.refuse:
            raise CatalogError("Ponle un nombre al producto.")
        self.created.append(kwargs)
        return uuid4()


def test_the_provider_never_duplicates_and_never_changes_a_price() -> None:
    catalog = _Catalog(["Shawarma Mixto", "Ensalada del Dia"], refuse="Raro")
    products = [
        FoundProduct("shawarma  mixto", Decimal("6"), "USD", "", "e"),  # same, other case
        FoundProduct("Ensalada del día", None, "", "", "e"),  # same, accents folded
        FoundProduct("Falafel", Decimal("4"), "", "Con salsa", "e"),  # «$»: the tenant's
        FoundProduct("Falafel", Decimal("4"), "", "", "e"),  # repeated in the source
        FoundProduct("Raro", None, "", "", "e"),
    ]
    result = add_catalog_products(TENANT, BRAND, products, None, catalog=catalog, currency="COP")
    assert result.added == ("Falafel",)
    assert result.existing == ("shawarma mixto", "Ensalada del día", "Falafel")
    assert result.failed == ("Raro",)
    assert len(catalog.created) == 1
    created = catalog.created[0]
    assert created["tenant_id"] == TENANT and created["brand_id"] == BRAND
    assert created["price_amount"] == Decimal("4") and created["price_currency"] == "COP"
    assert created["description"] == "Con salsa"
    assert not hasattr(catalog, "update_product")  # the flow has no way to change a price


# --- the pure helpers ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("delivery_time", "30 a 40", "tarda unos 30 a 40 minutos."),
        ("delivery_time", "45 minutos", "tarda unos 45 minutos."),
        ("delivery_time", "entre 30 y 45 minutos", "tarda entre 30 y 45 minutos."),
        ("delivery_cost", "gratis", "El envío es gratis y tarda"),
        ("delivery_cost", "$3.000", "El envío cuesta $3.000 y tarda"),
    ],
)
def test_delivery_facts_fill_their_own_gap(key: str, value: str, expected: str) -> None:
    form = definition_to_form(build_starter_menu(StarterFacts(business_name="X")))
    plan = fact_plan(form, key, value)
    assert plan.mode == "fill" and expected in plan.text


def test_hours_and_brackets() -> None:
    assert fill_fact(HOURS_TEXT, "hours", "Lunes a sábado, 12 a 10.").startswith(
        "Abrimos de Lunes a sábado, 12 a 10. Cuando"
    )
    assert fill_fact("Abrimos todos los días.", "hours", "lunes") is None  # owner's own text
    # a value never reads as a gap
    assert "[" not in (fill_fact(PAYMENT_TEXT, "payment_methods", "[efectivo]") or "")


def test_an_answer_written_by_the_owner_is_replaced_only_by_use() -> None:
    form = definition_to_form(build_starter_menu(StarterFacts(business_name="X")))
    index = next(i for i, a in enumerate(read_answers(form)) if a.label == "Formas de pago")
    from .whatsapp_menu_vm import answer_set_text

    form = answer_set_text(form, index, "Aceptamos efectivo.")
    plan = fact_plan(form, "payment_methods", "Nequi")
    assert plan.mode == "replace" and plan.text.startswith("Puedes pagar con Nequi.")
    view = import_view(
        form,
        kind="image",
        label="",
        warnings=(),
        facts=[{"key": "payment_methods", "value": "Nequi", "evidence": "Nequi", "status": "p"}],
        products=product_rows(()),
        catalog=(),
    )
    assert view.facts[0].note == "Cambiamos el texto de tu respuesta «Formas de pago» por:"


# --- entry points and render ----------------------------------------------------------------


async def test_creating_a_menu_offers_the_import_with_not_now(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch, _Reader())
    detail = MenuDetail(
        summary=state.menu,
        versions=state.versions,
        latest=build_starter_menu(StarterFacts(business_name="La Esquina")),
        payloads={},
    )

    async def address(self: object) -> str:
        return ""

    monkeypatch.setattr(WhatsAppMenuState, "_profile_address", address)
    monkeypatch.setattr(module, "user_id_for", lambda tenant, email: None)
    monkeypatch.setattr(module, "starter_facts", lambda *a, **k: StarterFacts("La Esquina"))
    monkeypatch.setattr(module, "create_menu", lambda *a, **k: detail)
    state.set_new_open(True)
    state.set_new_name("Menú de la tarde")
    await _run(WhatsAppMenuState.create_new_menu, state)
    assert state.import_phase == IMPORT_CHOOSE and state.import_offer
    state.close_import()  # «Ahora no»
    assert state.import_phase == "" and state.guided_step == 1


def test_the_step_and_the_review_render() -> None:
    from . import whatsapp_tab_menu

    rendered = str(whatsapp_tab_menu.menu_tab().render())

    def present(text: str) -> bool:
        escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
        return text in rendered or escaped in rendered

    for text in (
        "¿Tienes tu menú en una foto o en tu página?",
        "Ahora no",
        "Una foto o PDF",
        "Mi página web",
        "Cargar desde una foto o mi página",
        "Sube una foto de tu menú o tu volante",
        "Elegir una foto o un PDF",
        "Pega el enlace de tu página",
        "Leer mi página",
        "Solo leemos los datos de tu negocio; no publicamos nada.",
        "Estamos leyendo tu menú… Toma menos de un minuto.",
        "Revisa cada dato. Solo usamos lo que aceptes, y queda guardado cuando toques «Guardar».",
        "De tu menú impreso, tu volante o una captura de tu Instagram.",
        "Marcar todos",
        "Desmarcar todos",
        "Usar",
        "No usar",
        "Usar este texto",
        "Agregar los marcados a la Galería",
        "Volver a tus respuestas",
        "Seguir sin la foto",
    ):
        assert present(text), text
    for handler in ("open_import", "use_import_fact", "add_import_products", "finish_import"):
        assert handler in rendered, handler
    assert set(whatsapp_tab_menu.IMPORT_ACCEPT) == {
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/pdf",
    }
    assert "aria-live" in rendered


def test_only_the_products_button_writes() -> None:
    import inspect

    for name in (
        "_run_import",
        "use_import_fact",
        "skip_import_fact",
        "handle_import_upload",
        "finish_import",
    ):
        member = getattr(WhatsAppMenuState, name)
        source = inspect.getsource(getattr(member, "fn", member))
        for write in ("save_version", "publish_version", "_save_now", "add_catalog_products"):
            assert write not in source, (name, write)
    tab = (Path(__file__).parent / "whatsapp_tab_menu.py").read_text()
    assert "qualify_api" not in tab


def test_archived_products_count_and_names_match_whole() -> None:
    catalog = _Catalog(["Pan"], archived=["Té frío"])
    products = [
        FoundProduct("Empanada", Decimal("2"), "COP", "", "e"),  # «Pan» is not part of it
        FoundProduct("te frio", Decimal("3"), "COP", "", "e"),  # archived: not again
    ]
    result = add_catalog_products(TENANT, BRAND, products, None, catalog=catalog)
    assert result.added == ("Empanada",) and result.existing == ("te frio",)


async def test_an_oversized_upload_is_cut_before_it_is_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _Reader()
    state = _state(monkeypatch, reader)
    state.open_import()
    state.choose_import_source(IMPORT_PHOTO)
    big = _Upload(b"\xff\xd8\xff" + b"0" * module.IMPORT_MAX_BYTES)
    await WhatsAppMenuState.handle_import_upload.fn(state, [big])
    assert state.import_phase == IMPORT_FAILED_PHASE
    assert state.import_error.startswith("El archivo pesa más de 10 MB.")
    assert state._import_staged == "" and reader.calls == []
    # a declared size over the cap is refused without reading at all
    state.import_back()
    declared = _Upload(b"")
    declared.size = module.IMPORT_MAX_BYTES + 1  # type: ignore[attr-defined]

    async def never(size: int = -1) -> bytes:
        raise AssertionError("not read")

    declared.read = never  # type: ignore[method-assign]
    await WhatsAppMenuState.handle_import_upload.fn(state, [declared])
    assert state.import_error.startswith("El archivo pesa más de 10 MB.")


async def test_the_staged_file_is_removed_when_the_read_never_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _Reader(_proposal((HOURS,)))
    state = _state(monkeypatch, reader)
    state.open_import()
    state.choose_import_source(IMPORT_PHOTO)
    await WhatsAppMenuState.handle_import_upload.fn(state, [_Upload(b"\xff\xd8\xff")])
    path = state._import_staged
    assert path and os.path.exists(path)
    state.suggest_busy = "greeting"  # the slot is taken: the guard returns early
    await _run(WhatsAppMenuState.read_import_file, state)
    assert reader.calls == [] and not os.path.exists(path)


async def test_outside_taps_keep_the_read_and_the_review(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch, _Reader(_proposal((HOURS,))))
    state.open_import()
    state.choose_import_source(IMPORT_PHOTO)
    await WhatsAppMenuState.handle_import_upload.fn(state, [_Upload(b"\xff\xd8\xff")])
    events = await _run(WhatsAppMenuState.read_import_file, state)
    assert state.import_phase == IMPORT_REVIEW
    assert len(events) == 1  # focus moves to «Esto encontramos en…»
    state.set_import_open(False)  # a tap outside / Escape
    assert state.import_phase == IMPORT_REVIEW
    state.finish_import()  # the explicit way out
    assert state.import_phase == ""
    state.open_import()
    state.set_import_open(False)  # on the chooser it still closes
    assert state.import_phase == ""


async def test_mark_and_unmark_all(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch, _Reader(_proposal((), (SHAWARMA, FALAFEL, SALAD))))
    await _upload(state)
    state.set_all_import_products(True)
    assert state.import_review.checked_count == 2
    state.set_all_import_products(False)
    assert state.import_review.checked_count == 0
    assert state._import_products[0]["checked"] == "1"  # the catalog's own row is untouched


async def test_a_failed_currency_read_saves_the_price_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    currencies: list[str | None] = []

    def add(tenant_id: UUID, brand_id: UUID, products: Any, user_id: Any, *, currency=None):
        currencies.append(currency)
        return AddedProducts(tuple(p.name for p in products), (), ())

    def broken(tenant: UUID) -> str:
        raise RuntimeError("db")

    state = _state(monkeypatch, _Reader(_proposal((), (FALAFEL,))))
    monkeypatch.setattr(module, "business_currency", broken)
    monkeypatch.setattr(module, "add_catalog_products", add)
    monkeypatch.setattr(module, "user_id_for", lambda tenant, email: None)
    monkeypatch.setattr(module, "preview_catalog", lambda tenant, brand: ())
    await _upload(state)
    assert state.import_review.new_products[0].price == "4"  # the amount alone
    await _run(WhatsAppMenuState.add_import_products, state)
    assert currencies == [""]  # and saved alone: no fallback to the tenant's
    catalog = _Catalog([])
    add_catalog_products(TENANT, BRAND, [FALAFEL], None, catalog=catalog, currency="")
    assert catalog.created[0]["price_currency"] == ""


# --- sentences (m-24945867): an explanation is never pasted into a gap -----------------------

ZONE_SENTENCE = FoundFact(
    "delivery_zone",
    "La cobertura se confirma por WhatsApp según la dirección de entrega.",
    "La cobertura se confirma por WhatsApp según la dirección de entrega",
    "sentence",
)
COST_SENTENCE = FoundFact(
    "delivery_cost",
    "El costo exacto se confirma por WhatsApp según la dirección de entrega.",
    "El costo exacto se confirma por WhatsApp según la dirección de entrega",
    "sentence",
)
PRODUCTION_DELIVERY = (
    "La cobertura se confirma por WhatsApp según la dirección de entrega. El costo exacto se "
    "confirma por WhatsApp según la dirección de entrega. El envío tarda unos [minutos] "
    "minutos. Para pedir, escribe *menú*."
)


async def test_the_production_case_reads_as_one_text_with_the_time_gap_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch, _Reader(_proposal((ZONE_SENTENCE, COST_SENTENCE), kind="url")))
    await _upload(state)
    review = state.import_review
    assert len(review.facts) == 1  # zone and cost offered together
    row = review.facts[0]
    assert row.is_sentence and row.title == "Domicilio" and row.can_use
    assert row.note == "Si lo usas, tu respuesta «Domicilio» queda así:"
    assert row.preview == PRODUCTION_DELIVERY
    assert row.evidence_line == (
        "En tu página dice: «La cobertura se confirma por WhatsApp según la dirección de "
        "entrega» y «El costo exacto se confirma por WhatsApp según la dirección de entrega»"
    )
    state.use_import_fact(row.index)
    delivery = _text(state, "Domicilio")
    assert delivery == PRODUCTION_DELIVERY
    assert "a La cobertura" not in delivery and "cuesta El costo" not in delivery
    assert ".." not in delivery
    assert find_gaps(delivery) == ["minutos"]
    assert [f["status"] for f in state._import_facts] == [FACT_USED, FACT_USED]
    used = state.import_review.facts
    assert [f.status_label for f in used] == ["Lo usamos"]
    assert used[0].used_note == "Revisa el texto: lo copiamos tal cual de tu página."


async def test_identical_sentences_are_offered_once(monkeypatch: pytest.MonkeyPatch) -> None:
    same = FoundFact("delivery_cost", ZONE_SENTENCE.value, ZONE_SENTENCE.evidence, "sentence")
    state = _state(monkeypatch, _Reader(_proposal((ZONE_SENTENCE, same))))
    await _upload(state)
    preview = state.import_review.facts[0].preview
    assert preview.count("La cobertura se confirma") == 1
    assert preview.endswith("El envío tarda unos [minutos] minutos. Para pedir, escribe *menú*.")


async def test_no_lo_usamos_skips_the_whole_text(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch, _Reader(_proposal((ZONE_SENTENCE, COST_SENTENCE))))
    await _upload(state)
    before = _text(state, "Domicilio")
    state.skip_import_fact(state.import_review.facts[0].index)
    assert [f["status"] for f in state._import_facts] == [FACT_SKIPPED, FACT_SKIPPED]
    assert _text(state, "Domicilio") == before


async def test_a_value_and_a_sentence_of_the_same_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    time_value = FoundFact("delivery_time", "30", "Entrega en 30 min")
    state = _state(monkeypatch, _Reader(_proposal((ZONE_SENTENCE, time_value))))
    await _upload(state)
    rows = state.import_review.facts
    assert [(r.title, r.is_sentence) for r in rows] == [
        ("Zona de domicilio", True),
        ("Tiempo de entrega", False),
    ]
    # the value first: the sentence's text keeps it
    state.use_import_fact(_fact(state, "delivery_time"))
    assert "tarda unos 30 minutos" in _text(state, "Domicilio")
    sentence = state.import_review.facts[0]
    assert sentence.preview == (
        "La cobertura se confirma por WhatsApp según la dirección de entrega. El envío cuesta "
        "[precio del envío] y tarda unos 30 minutos. Para pedir, escribe *menú*."
    )
    state.use_import_fact(sentence.index)
    delivery = _text(state, "Domicilio")
    assert delivery == sentence.preview and find_gaps(delivery) == ["precio del envío"]


async def test_a_value_after_the_sentence_fills_the_gap_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    time_value = FoundFact("delivery_time", "30", "Entrega en 30 min")
    state = _state(monkeypatch, _Reader(_proposal((ZONE_SENTENCE, COST_SENTENCE, time_value))))
    await _upload(state)
    state.use_import_fact(_fact(state, "delivery_zone"))
    state.use_import_fact(_fact(state, "delivery_time"))
    assert _text(state, "Domicilio") == PRODUCTION_DELIVERY.replace(
        "unos [minutos] minutos", "unos 30 minutos"
    )


async def test_a_sentence_shortened_into_a_value_fills_its_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch, _Reader(_proposal((ZONE_SENTENCE, COST_SENTENCE))))
    await _upload(state)
    zone = _fact(state, "delivery_zone")
    state.edit_import_fact(zone)
    editing = state.import_review.facts[0]
    assert editing.editing and editing.title == "Zona de domicilio"  # alone while edited
    assert editing.edit_hint == "Escribe solo la zona, por ejemplo: todo el centro"
    assert len(state.import_review.facts) == 2
    state.set_import_fact_value("todo el centro")
    assert state._import_facts[zone]["kind"] == "value"
    row = state.import_review.facts[0]
    assert not row.is_sentence
    assert row.preview.startswith("Llevamos tu pedido a todo el centro. El envío cuesta [")
    state.use_import_fact(zone)
    assert _text(state, "Domicilio").startswith("Llevamos tu pedido a todo el centro.")
    # the cost sentence is still offered as a whole text, never in the gap
    cost = state.import_review.facts[1]
    assert cost.is_sentence and cost.pending
    assert cost.preview == (
        "El costo exacto se confirma por WhatsApp según la dirección de entrega. Llevamos tu "
        "pedido a todo el centro. El envío tarda unos [minutos] minutos. Para pedir, escribe "
        "*menú*."
    )


def test_sentence_helpers_follow_the_starter() -> None:
    from qualify_api.whatsapp.menus.starter import DELIVERY_TEXT

    from .whatsapp_menu_vm import as_sentence, sentence_text, starter_closing

    assert as_sentence("la cobertura se confirma..") == "La cobertura se confirma."
    assert as_sentence("  ¿Dudas? Escríbenos!  ") == "¿Dudas? Escríbenos!"
    assert starter_closing(DELIVERY_TEXT) == "Para pedir, escribe *menú*."
    assert starter_closing(HOURS_TEXT) == "Cuando quieras pedir, escribe *menú*."
    assert starter_closing(PAYMENT_TEXT) == ""
    # nothing covered: the starter's own gaps, as in DELIVERY_TEXT
    lines = sentence_text("domicilio", [("delivery_time", "depende del tráfico")])
    assert lines == (
        "Depende del tráfico. Llevamos tu pedido a [barrios o zona]. El envío cuesta "
        "[precio del envío]. Para pedir, escribe *menú*."
    )
    assert "Llevamos tu pedido a [barrios o zona]." in DELIVERY_TEXT
    assert "El envío cuesta [precio del envío] y tarda unos [minutos] minutos." in DELIVERY_TEXT
    hours = sentence_text("horario", [("hours", "Atendemos según la temporada")])
    assert hours == "Atendemos según la temporada. Cuando quieras pedir, escribe *menú*."


def test_older_rows_without_kind_are_values() -> None:
    from .whatsapp_menu_vm import fact_rows, row_kind

    assert fact_rows([ZONE])[0]["kind"] == "value"
    assert fact_rows([ZONE_SENTENCE])[0]["kind"] == "sentence"
    assert row_kind({"key": "hours", "value": "x", "status": "pending"}) == "value"


async def test_a_sentence_used_alone_stays_when_the_next_one_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch, _Reader(_proposal((ZONE_SENTENCE, COST_SENTENCE))))
    await _upload(state)
    zone = _fact(state, "delivery_zone")
    state.edit_import_fact(zone)
    state.set_import_fact_value("La cobertura se confirma por WhatsApp según tu dirección.")
    assert state._import_facts[zone]["kind"] == "sentence"
    state.use_import_fact(zone)  # alone, while edited
    state.use_import_fact(_fact(state, "delivery_cost"))
    delivery = _text(state, "Domicilio")
    assert delivery == (
        "La cobertura se confirma por WhatsApp según tu dirección. El costo exacto se confirma "
        "por WhatsApp según la dirección de entrega. El envío tarda unos [minutos] minutos. "
        "Para pedir, escribe *menú*."
    )
    assert find_gaps(delivery) == ["minutos"]


def test_the_closing_line_is_never_said_twice() -> None:
    from .whatsapp_menu_vm import sentence_text

    text = sentence_text(
        "domicilio",
        [("delivery_zone", "Para pedir, escribe *menú* y te decimos si llegamos")],
    )
    assert text.count("*menú*") == 1
    assert text.startswith("Para pedir, escribe *menú* y te decimos si llegamos.")

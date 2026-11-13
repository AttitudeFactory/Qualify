"""m-25017912 — «Tu producto en sticker» offline: the words (creaciones, never money), the
five steps with their defaults, «Pedir otro dibujo» keeping every drawing, picking one,
the cost-changed path, messages and variants, the free «Preparar», the library and chat
picker showing product stickers after the seasons, and the logout reset."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from . import product_sticker_state as state_module
from .product_sticker_provider import (
    CharacterCard,
    CreationsCost,
    ProductOption,
    ProductStep,
    StickerCard,
    cost_texts,
)
from .product_sticker_state import ProductStickerState
from .product_sticker_vm import (
    NO_VARIANT,
    STEP_DRAWING,
    STEP_MESSAGE,
    STEP_MOTION,
    STEP_PRODUCT,
    STEP_REVIEW,
    chosen_messages,
    own_message_error,
    prepare_label,
    review_line,
    start_cost_line,
    without_photo_line,
)

TENANT = UUID("a0000000-0000-4000-8000-000025017912")
BRAND = UUID("c0000000-0000-4000-8000-000025017912")
SHAWARMA = "50000000-0000-4000-8000-000000000001"
ENSALADA = "50000000-0000-4000-8000-000000000002"
PRESETS = (
    "¡Gracias por tu pedido!",
    "Bienvenido",
    "En camino",
    "Entregado",
    "Listo para recoger",
)


def _cost(left: int | None = 12, creations: int = 1, message: str = "") -> CreationsCost:
    line, button = cost_texts(creations, left, False)
    return CreationsCost(
        creations=creations,
        left=left,
        unlimited=False,
        can_pay=not message,
        cost_line=line,
        button_label=button,
        message=message,
    )


@dataclass
class FakeGateway:
    products_step: ProductStep = field(
        default_factory=lambda: ProductStep(
            products=(
                ProductOption(SHAWARMA, "Shawarma mixto", "/r2media/a"),
                ProductOption(ENSALADA, "Ensalada griega", ""),
            ),
            without_photo=3,
            preselected=SHAWARMA,
        )
    )
    quote: CreationsCost = field(default_factory=_cost)
    drawings: dict[str, list[CharacterCard]] = field(default_factory=dict)
    made: list[StickerCard] = field(default_factory=list)
    calls: list[tuple[str, Any]] = field(default_factory=list)
    refuse_create: BaseException | None = None

    def brand(self, tenant_id: UUID) -> UUID:
        return BRAND

    def acting_user(self, tenant_id: UUID) -> None:
        return None

    def products(self, tenant_id: UUID, brand_id: UUID) -> ProductStep:
        return self.products_step

    def cost(self, tenant_id: UUID, brand_id: UUID) -> CreationsCost:
        return self.quote

    def presets(self) -> tuple[str, ...]:
        return PRESETS

    def max_message_chars(self) -> int:
        return 25

    def create_character(self, tenant_id, brand_id, product_id, user_id, accepted):  # noqa: ANN001, ANN201
        self.calls.append(("create", (str(product_id), accepted)))
        if self.refuse_create is not None:
            raise self.refuse_create
        card = CharacterCard(
            id=str(uuid4()),
            product_id=str(product_id),
            product_name="Shawarma mixto",
            status="pending",
            created_at=datetime(2026, 11, 12),
        )
        self.drawings.setdefault(str(product_id), []).insert(0, card)
        return card

    def characters(self, tenant_id, brand_id, product_id=None):  # noqa: ANN001, ANN201
        return list(self.drawings.get(str(product_id), []))

    def _set(self, drawing_id: UUID, status: str) -> CharacterCard:
        for cards in self.drawings.values():
            for i, c in enumerate(cards):
                if c.id == str(drawing_id):
                    cards[i] = CharacterCard(**{**c.__dict__, "status": status})
                    return cards[i]
        raise KeyError(drawing_id)

    def use_character(self, tenant_id, brand_id, character_id, user_id):  # noqa: ANN001, ANN201
        self.calls.append(("use", str(character_id)))
        return self._set(character_id, "approved")

    def discard_character(self, tenant_id, brand_id, character_id, user_id):  # noqa: ANN001, ANN201
        self.calls.append(("discard", str(character_id)))
        card = self._set(character_id, "discarded")
        for cards in self.drawings.values():
            cards[:] = [c for c in cards if c.status != "discarded"]
        return card

    def make_stickers(  # noqa: ANN201
        self,
        tenant_id,  # noqa: ANN001
        brand_id,  # noqa: ANN001
        character_id,  # noqa: ANN001
        messages,  # noqa: ANN001
        user_id,  # noqa: ANN001
        *,
        animated=True,  # noqa: ANN001
        still=False,  # noqa: ANN001
    ):
        self.calls.append(("make", (str(character_id), list(messages), animated, still)))
        return []

    def stickers(self, tenant_id: UUID, brand_id: UUID) -> list[StickerCard]:
        return list(self.made)


def _ready(product: str, name: str = "Shawarma mixto", status: str = "ready") -> CharacterCard:
    return CharacterCard(
        id=str(uuid4()), product_id=product, product_name=name, status=status, src="/r2s/x"
    )


@pytest.fixture
def gw(monkeypatch: pytest.MonkeyPatch) -> FakeGateway:
    fake = FakeGateway()
    monkeypatch.setattr(state_module, "gateway", lambda: fake)

    async def tenant(self: ProductStickerState) -> UUID:
        return TENANT

    monkeypatch.setattr(ProductStickerState, "_tenant", tenant)
    return fake


async def _drain(gen: Any) -> list[Any]:
    return [e async for e in gen]


async def _open(state: ProductStickerState) -> None:
    await ProductStickerState.open_flow.fn(state)


async def _to_drawings(state: ProductStickerState) -> None:
    state.flow_next()
    assert state.flow_step == STEP_DRAWING
    await _drain(ProductStickerState.read_drawings.fn(state))


# --- words -----------------------------------------------------------------------------


def test_the_words_say_creaciones_never_money() -> None:
    assert start_cost_line(1) == (
        "Cada dibujo usa 1 creación. Los stickers que hagas con él son gratis."
    )
    assert start_cost_line(0) == "Los stickers que hagas con tu dibujo son gratis."
    assert without_photo_line(3) == "3 productos no salen porque no tienen foto."
    assert without_photo_line(1) == "1 producto no sale porque no tiene foto."
    assert without_photo_line(0) == ""
    assert prepare_label(1) == "Preparar el sticker · gratis"
    assert prepare_label(4) == "Preparar 4 stickers · gratis"
    assert own_message_error("   ", 25) == "Escribe el mensaje del sticker."
    assert own_message_error("x" * 26, 25).startswith("Máximo 25 letras.")
    assert own_message_error("¡Feliz finde!", 25) == ""
    assert chosen_messages(PRESETS, ["En camino", PRESETS[0]], True, " Hola ") == [
        PRESETS[0],
        "En camino",
        "Hola",
    ]
    assert review_line("Shawarma mixto", [PRESETS[0]], True, False) == (
        "Vamos a preparar 1 sticker con el dibujo de Shawarma mixto: "
        "«¡Gracias por tu pedido!», con movimiento."
    )
    assert review_line("Shawarma mixto", [PRESETS[0], "En camino"], True, True) == (
        "Vamos a preparar 4 stickers con el dibujo de Shawarma mixto: "
        "«¡Gracias por tu pedido!» y «En camino», con movimiento y quietos."
    )
    for text in (start_cost_line(1), prepare_label(2)):
        assert "US$" not in text and "kawaii" not in text.lower()


# --- the flow -------------------------------------------------------------------------


async def test_opens_with_everything_already_chosen(gw: FakeGateway) -> None:
    state = ProductStickerState()
    await _open(state)
    assert state.flow_open and state.flow_step == STEP_PRODUCT
    assert state.flow_title == "¿Qué producto dibujamos?"
    assert state.product_id == SHAWARMA and state.product_name == "Shawarma mixto"
    assert state.without_photo_text == "3 productos no salen porque no tienen foto."
    assert state.picked == [PRESETS[0]] and state.animated and not state.still
    assert state.cost_line == "Este dibujo usa 1 creación. Te quedan 12 este mes."
    assert not state.show_search and state.can_go_on


async def test_no_product_with_a_photo_is_an_empty_state(gw: FakeGateway) -> None:
    gw.products_step = ProductStep(products=(), without_photo=2, preselected="")
    state = ProductStickerState()
    await _open(state)
    assert state.no_products and not state.can_go_on


async def test_search_from_ten_products(gw: FakeGateway) -> None:
    gw.products_step = ProductStep(
        products=tuple(ProductOption(str(uuid4()), f"Producto {i}") for i in range(10))
        + (ProductOption(SHAWARMA, "Shawarma mixto"),),
        without_photo=0,
        preselected=SHAWARMA,
    )
    state = ProductStickerState()
    await _open(state)
    assert state.show_search
    state.set_product_query("shawar")
    assert [p.name for p in state.shown_products] == ["Shawarma mixto"]


async def test_first_drawing_then_another_keeps_both_and_the_owner_picks(
    gw: FakeGateway,
) -> None:
    state = ProductStickerState()
    await _open(state)
    await _to_drawings(state)
    assert state.drawings == [] and state.drawing_button == "Crear dibujo · 1 creación"
    assert not state.can_go_on  # no drawing yet
    await _drain(ProductStickerState.ask_drawing.fn(state))
    assert gw.calls[-1] == ("create", (SHAWARMA, 1))
    assert state.any_drawing_pending and state.drawing_id == ""
    assert state.drawing_button == "Pedir otro dibujo · 1 creación"
    # the first one is drawn; «Pedir otro» makes a SECOND one, the first is kept
    first = gw.drawings[SHAWARMA][0]
    gw._set(UUID(first.id), "ready")
    await state._read_drawings(state._gen)
    assert state.drawing_id == first.id and state.can_go_on
    await _drain(ProductStickerState.ask_drawing.fn(state))
    await state._read_drawings(state._gen)
    assert len(state.drawings) == 2 and state.drawing_id == first.id
    second = gw.drawings[SHAWARMA][0]
    gw._set(UUID(second.id), "ready")
    await state._read_drawings(state._gen)
    state.pick_drawing(second.id)
    assert state.drawing_id == second.id
    nxt = state.flow_next()
    assert nxt is not None
    await ProductStickerState.use_drawing.fn(state)
    assert gw.calls[-1] == ("use", second.id) and state.flow_step == STEP_MESSAGE
    assert first.id in [d.id for d in state.drawings]  # still there to pick later


async def test_pending_or_failed_drawings_cannot_be_picked(gw: FakeGateway) -> None:
    failed = CharacterCard(
        id=str(uuid4()),
        product_id=SHAWARMA,
        product_name="Shawarma mixto",
        status="failed",
        failure_text="Este dibujo no salió y no se te cobró. Puedes pedir otro.",
    )
    gw.drawings[SHAWARMA] = [failed]
    state = ProductStickerState()
    await _open(state)
    await _to_drawings(state)
    state.pick_drawing(failed.id)
    assert state.drawing_id == "" and not state.can_go_on
    assert state.drawings[0].failure_text.endswith("Puedes pedir otro.")
    state.flow_next()
    assert state.flow_error == "Elige un dibujo listo para seguir."
    await ProductStickerState.discard_drawing.fn(state, failed.id)
    assert state.drawings == [] and ("discard", failed.id) in gw.calls


async def test_cost_changed_shows_the_new_cost_before_spending(gw: FakeGateway) -> None:
    from qualify_api.creative.product_stickers import CostChanged

    state = ProductStickerState()
    await _open(state)
    await _to_drawings(state)
    gw.refuse_create = CostChanged()
    gw.quote = _cost(left=12, creations=2)
    await _drain(ProductStickerState.ask_drawing.fn(state))
    assert state.flow_error == "El costo cambió. Revísalo antes de crear."
    assert state.cost_line == "Este dibujo usa 2 creaciones. Te quedan 12 este mes."
    assert state.drawing_button == "Crear dibujo · 2 creaciones"
    assert not state.drawings


async def test_an_empty_month_has_no_create_button(gw: FakeGateway) -> None:
    gw.quote = _cost(left=0, message="Te falta 1 creación este mes.")
    state = ProductStickerState()
    await _open(state)
    await _to_drawings(state)
    assert not state.can_ask_drawing and state.cost_message.startswith("Te falta")
    await _drain(ProductStickerState.ask_drawing.fn(state))
    assert not [c for c in gw.calls if c[0] == "create"]


async def test_messages_variants_and_the_free_create(gw: FakeGateway) -> None:
    drawing = _ready(SHAWARMA, status="approved")
    gw.drawings[SHAWARMA] = [drawing]
    state = ProductStickerState()
    await _open(state)
    await _to_drawings(state)
    state.flow_next()
    await ProductStickerState.use_drawing.fn(state)  # already used: straight on
    assert state.flow_step == STEP_MESSAGE and ("use", drawing.id) not in gw.calls
    state.toggle_message("En camino")
    state.toggle_own()
    state.set_own_text("x" * 40)
    assert len(state.own_text) == 25 and state.own_count == "25/25"
    state.set_own_text("  ")
    assert not state.can_go_on
    state.flow_next()
    assert state.flow_error == "Escribe el mensaje del sticker."
    state.set_own_text("¡Feliz finde!")
    state.flow_next()
    assert state.flow_step == STEP_MOTION
    state.toggle_animated()
    state.flow_next()
    assert state.flow_error == NO_VARIANT and state.flow_step == STEP_MOTION
    state.toggle_still()
    state.toggle_animated()
    state.flow_next()
    assert state.flow_step == STEP_REVIEW
    assert state.total == 6 and state.prepare_button == "Preparar 6 stickers · gratis"
    events = await _drain(ProductStickerState.create.fn(state))
    assert gw.calls[-1] == (
        "make",
        (drawing.id, [PRESETS[0], "En camino", "¡Feliz finde!"], True, True),
    )
    assert not state.flow_open
    assert "Por aprobar" in json.dumps(str(events), ensure_ascii=False)


async def test_the_last_message_used_is_chosen_again(gw: FakeGateway) -> None:
    gw.made = [
        StickerCard(id="1", character_id="c", message="En camino", animated=True, status="ready"),
        StickerCard(id="2", character_id="c", message="Hola vecino", animated=True, status="ready"),
    ]
    state = ProductStickerState()
    await _open(state)
    assert state.own_on and state.own_text == "Hola vecino" and state.picked == []
    gw.made = gw.made[:1]
    await _open(state)
    assert state.picked == ["En camino"] and not state.own_on


async def test_back_keeps_everything_and_closes_on_step_one(gw: FakeGateway) -> None:
    state = ProductStickerState()
    await _open(state)
    state.choose_product(ENSALADA)
    await _to_drawings(state)
    state.flow_back()
    assert state.flow_step == STEP_PRODUCT and state.product_id == ENSALADA
    state.flow_back()
    assert not state.flow_open


def test_open_from_query_and_logout_reset() -> None:
    from .auth_state import business_state_classes
    from .seasonal_ui import brand_section

    assert ProductStickerState in business_state_classes()
    page = str(brand_section())
    for text in (
        "Tu producto en sticker",
        "Crear sticker de producto",
        "Crear para esta temporada",
    ):
        assert text in page or json.dumps(text)[1:-1] in page, text
    assert "kawaii" not in page.lower() and "US$" not in page


# --- the library and the chat picker ----------------------------------------------------


def _media(status: str, season: str = "productos", message: str = "En camino") -> Any:
    return SimpleNamespace(
        id=uuid4(),
        kind="sticker",
        status=status,
        season_key=season,
        season_label="De tus productos" if season == "productos" else "Navidad 2026",
        recipe="k-animado" if season == "productos" else "e-latido",
        source_kind="character" if season == "productos" else "logo",
        source_ref=f"{uuid4()}:{message}" if season == "productos" else "logo",
        bytes=90_000,
        cost_usd=0,
        fail_reason=None,
    )


def test_library_shows_the_message_and_a_free_redo() -> None:
    from .seasonal_vm import build_season

    season = build_season("productos", "De tus productos", False, [_media("ready")])
    item = season.pending_pieces[0]
    assert item.caption == "En camino" and item.another_label == "Hacer de nuevo"
    assert item.kind_label == "Sticker con movimiento"
    assert item.alt == "Sticker con movimiento que dice «En camino»" and not item.paid
    other = build_season("navidad-2026", "Navidad 2026", False, [_media("ready", "navidad")])
    assert other.pieces[0].caption == "" and other.pieces[0].another_label == "Pedir otro"


def test_chat_picker_lists_product_stickers_after_the_seasons() -> None:
    from .whatsapp_chats_vm import build_seasonal_picks

    rows = [_media("approved", "navidad"), _media("approved", "productos", "Entregado")]
    picks = build_seasonal_picks(rows)
    assert [(p.current, p.product) for p in picks] == [(True, False), (False, True)]
    assert picks[1].alt == "Sticker que dice «Entregado»"
    only = build_seasonal_picks([_media("approved", "productos")])
    assert not only[0].current and only[0].product


# --- review: races, stale reads, failures ------------------------------------------------


async def test_a_double_tap_asks_for_one_drawing_only(
    gw: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import threading

    state = ProductStickerState()
    await _open(state)
    await _to_drawings(state)
    release = threading.Event()
    original = gw.create_character

    def slow(*args: Any) -> CharacterCard:
        release.wait(5)
        return original(*args)

    monkeypatch.setattr(gw, "create_character", slow)
    first = asyncio.create_task(_drain(ProductStickerState.ask_drawing.fn(state)))
    await asyncio.sleep(0.05)
    assert state.asking and not state.can_ask_drawing
    await _drain(ProductStickerState.ask_drawing.fn(state))  # the second tap: nothing
    release.set()
    await first
    assert [c for c in gw.calls if c[0] == "create"] == [("create", (SHAWARMA, 1))]


async def test_a_read_of_another_product_never_lands(
    gw: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    gw.drawings[SHAWARMA] = [_ready(SHAWARMA)]
    gw.drawings[ENSALADA] = [_ready(ENSALADA, "Ensalada griega")]
    state = ProductStickerState()
    await _open(state)
    original = gw.characters

    def owner_changes_product_meanwhile(*args: Any) -> list[CharacterCard]:
        state.product_id = ENSALADA  # «Atrás», another product, while this read runs
        return original(*args)

    monkeypatch.setattr(gw, "characters", owner_changes_product_meanwhile)
    state.flow_step = STEP_DRAWING
    assert await state._read_drawings(state._gen) is False
    assert state.drawings == [] and state.drawing_id == ""


async def test_leaving_the_page_closes_the_panel_and_stops_polling(gw: FakeGateway) -> None:
    state = ProductStickerState()
    await _open(state)
    poll = state._poll_gen
    state.stop_poll()
    assert not state.flow_open and state._poll_gen == poll + 1
    await _open(state)
    state.asking = True  # a paid request on its way keeps it open
    state.stop_poll()
    assert state.flow_open


async def test_using_a_drawing_that_changed_says_so(gw: FakeGateway) -> None:
    from qualify_api.creative.product_stickers import CharacterChanged

    drawing = _ready(SHAWARMA)
    gw.drawings[SHAWARMA] = [drawing]

    def refuse(*args: Any) -> CharacterCard:
        raise CharacterChanged()

    gw.use_character = refuse  # type: ignore[method-assign]
    state = ProductStickerState()
    await _open(state)
    await _to_drawings(state)
    state.flow_next()
    await ProductStickerState.use_drawing.fn(state)
    assert state.flow_step == STEP_DRAWING and not state.picking
    assert state.flow_error == "Este dibujo cambió mientras tanto. Actualiza la pantalla."


async def test_discarding_the_chosen_drawing_picks_the_next_one(gw: FakeGateway) -> None:
    newer, older = _ready(SHAWARMA), _ready(SHAWARMA)
    gw.drawings[SHAWARMA] = [newer, older]
    state = ProductStickerState()
    await _open(state)
    await _to_drawings(state)
    assert state.drawing_id == newer.id
    await ProductStickerState.discard_drawing.fn(state, newer.id)
    assert [d.id for d in state.drawings] == [older.id] and state.drawing_id == older.id


async def test_an_answer_for_an_older_open_is_dropped(gw: FakeGateway) -> None:
    gw.drawings[SHAWARMA] = [_ready(SHAWARMA)]
    state = ProductStickerState()
    await _open(state)
    state.flow_step = STEP_DRAWING
    old_gen = state._gen
    state._gen += 1  # the panel was opened again meanwhile
    assert await state._read_drawings(old_gen) is False and state.drawings == []


async def test_a_reload_never_restores_a_stale_panel(
    gw: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = ProductStickerState()
    await _open(state)
    query: dict[str, str] = {}
    monkeypatch.setattr(
        ProductStickerState,
        "router",
        property(lambda self: SimpleNamespace(url=SimpleNamespace(query_parameters=query))),
    )
    assert state.open_from_query() is None and not state.flow_open
    query["crear"] = "producto"
    assert state.open_from_query() is not None

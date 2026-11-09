"""Live test of «Crear publicación» (2026-11-03): the summary's counts,
one search box per inspiration slot, slots of several files, the campaign carried by
«Crear otra» and the «Publicaciones» thumbnails."""

from __future__ import annotations

import time
from uuid import UUID

import pytest

from . import content_generator
from . import creative_state as creative_state_module
from .creative_state import (
    CLIP_MAX_VIDEOS,
    INSPIRATION_SLOT_LIMITS,
    PIECE_VIEWS_FRESH_SECONDS,
    CreativeState,
)
from .generator_summary_vm import (
    CLIP_LOGO_PLACEMENT_TEXT,
    brand_resources_text,
    campaign_hint,
    clip_references_text,
    flyer_photos_text,
)
from .r2_media import VIEW_TTL_SECONDS

STOCK_IMAGE = "t/tenant/stock/pixabay/1.jpg"


def _summary(state: CreativeState) -> dict[str, dict[str, str]]:
    state.go_to_view(str(len(state.gen_views) - 1))  # the summary
    return {row["label"]: row for row in state.gen_summary}


# -- 1. «Fotos» counts by role, wherever they came from --------------------------------


def test_flyer_photos_count_the_background_and_every_product_photo() -> None:
    assert flyer_photos_text(background=True, products=2) == "Fondo: 1 foto · Producto: 2 fotos"
    assert flyer_photos_text(background=False, products=1) == "Producto: 1 foto"
    assert flyer_photos_text(background=False, products=0) == "Ninguna"
    assert "subida" not in flyer_photos_text(background=True, products=3)


def test_the_flyer_summary_counts_the_catalog_photos_too() -> None:
    state = CreativeState()
    state.choose_category("image")
    state.selected_product_id = "burger"
    state._selected_product_photo_keys = ["uploads/t/a.jpg", "uploads/t/b.jpg"]
    state.media_background_key, state.media_background_name = STOCK_IMAGE, "Inspiración"
    if state.brief_kind != "static_flyer":
        state._set_kind("static_flyer")
    assert _summary(state)["Fotos"]["value"] == "Fondo: 1 foto · Producto: 2 fotos"
    # the payload sends the same photos the summary counts
    assert state._product_keys_in("static_flyer") == ["uploads/t/a.jpg", "uploads/t/b.jpg"]


# -- 2. «Recursos de tu marca» names the main logo --------------------------------------


def test_the_brand_resources_name_the_main_logo_and_agree_in_number() -> None:
    assert (
        brand_resources_text(logo_label="Isotipo", other_logos=2, elements=0)
        == "Tu logo: solo el dibujo · 2 logos más"
    )
    assert (
        brand_resources_text(logo_label="Isotipo", other_logos=1, elements=1)
        == "Tu logo: solo el dibujo · 1 logo más · 1 imagen de tu marca"
    )
    assert brand_resources_text(logo_label="", other_logos=0, elements=3) == (
        "Sin logo · 3 imágenes de tu marca"
    )


def test_the_summary_uses_the_chosen_logo_label() -> None:
    state = CreativeState()
    state.choose_category("clip")
    state.brand_media_items = [
        {"key": "r2/logo.png", "label": "Isotipo", "kind": "logo", "view": ""},
        {"key": "r2/logo2.png", "label": "Logotipo", "kind": "logo", "view": ""},
    ]
    state.brand_logo_key = "r2/logo.png"
    state.brand_logo_reference_keys = ["r2/logo2.png"]
    summary = _summary(state)
    # draft 35a5918b (2026-11-03): every chosen logo by its name, never «1 logo más»
    # UX review 2026-11-03: in plain words, not the designer's
    assert summary["Recursos de tu marca"]["value"] == (
        "Tu logo: solo el dibujo · También: solo el nombre"
    )
    # and where a clip's logo goes, said before creating
    assert summary["Dónde irá tu logo"]["value"] == CLIP_LOGO_PLACEMENT_TEXT


def test_the_other_logos_are_named_when_their_names_are_known() -> None:
    assert (
        brand_resources_text(
            logo_label="Imagotipo",
            other_logos=2,
            elements=1,
            other_logo_labels=("Isologo", "Isotipo"),
        )
        == "Tu logo: el dibujo con el nombre · También: el nombre y el dibujo unidos, "
        "solo el dibujo · 1 imagen de tu marca"
    )
    # a name missing (a deleted logo): counted, as before
    assert (
        brand_resources_text(
            logo_label="Imagotipo", other_logos=2, elements=0, other_logo_labels=("Isologo", "")
        )
        == "Tu logo: el dibujo con el nombre · 2 logos más"
    )


def test_a_clip_without_a_logo_says_nothing_about_its_place() -> None:
    state = CreativeState()
    state.choose_category("clip")
    state.brand_media_items = [
        {"key": "r2/logo.png", "label": "Isotipo", "kind": "logo", "view": ""},
    ]
    assert "Dónde irá tu logo" not in _summary(state)


# -- 3. «Referencias» agree in number and skip what is not there -----------------------


def test_clip_references_agree_in_number_and_omit_zeros() -> None:
    assert clip_references_text(images=2, videos=1, audios=0) == "2 imágenes · 1 video"
    assert clip_references_text(images=1, videos=0, audios=2) == "1 imagen · 2 audios"
    assert clip_references_text(images=0, videos=0, audios=0) == "Ninguna"


# -- 4. each inspiration slot has its own words -----------------------------------------


def test_each_inspiration_box_keeps_its_own_words() -> None:
    state = CreativeState()
    CreativeState.set_inspiration_query.fn(state, "background", "interior de hamburguesería")
    CreativeState.set_inspiration_query.fn(state, "products", "hamburguesa doble")
    view = state.inspiration_query_view
    assert view["background"] == "interior de hamburguesería"
    assert view["products"] == "hamburguesa doble"
    assert view["clip_videos"] == "" and view["clip_images"] == ""
    assert state.stock_query == ""  # the product screen's box is untouched
    CreativeState.set_inspiration_query.fn(state, "nope", "x")
    assert "nope" not in state.inspiration_queries


TENANT_IDS = (
    UUID("a0000000-0000-4000-8000-000000000001"),
    UUID("a0000000-0000-4000-8000-000000000002"),
    UUID("a0000000-0000-4000-8000-000000000003"),
)
TILE = {"id": "pixabay:1", "thumb": "https://cdn/t.jpg", "author": "Ana"}


def _banks(monkeypatch: pytest.MonkeyPatch, imported: list[str]) -> None:
    """The stock banks and the import, offline: what each search returns and the
    query an import records."""

    async def session_ids(self: CreativeState) -> tuple[UUID, UUID, UUID]:
        return TENANT_IDS

    def kit(tenant_id: UUID, queries: list[str], *, page: int, media: str = "image"):
        return ["hamburguesa", "local"], [TILE], {TILE["id"]: {"id": TILE["id"]}}, False

    def typed(tenant_id: UUID, text: str, *, page: int, media: str = "image"):
        return [TILE], {TILE["id"]: {"id": TILE["id"]}}, False

    def importer(tenant_id, brand_id, user_id, item, *, query: str) -> dict[str, str]:
        imported.append(query)
        return {"key": "t/x/stock/pixabay/1/a.jpg", "view": "/r2media/a", "author": "Ana"}

    monkeypatch.setattr(CreativeState, "_session_ids", session_ids)
    monkeypatch.setattr(creative_state_module, "kit_search_queries", lambda t, b: ["burger"])
    monkeypatch.setattr(creative_state_module, "search_stock_from_kit", kit)
    monkeypatch.setattr(creative_state_module, "search_stock_images", typed)
    monkeypatch.setattr(creative_state_module, "import_stock_image", importer)


async def test_an_import_records_the_words_that_brought_the_hit(monkeypatch) -> None:
    """Review 2026-11-03: Brand Kit hits imported from a slot record the kit's words,
    never a box left over from the product screen («pizza»)."""
    imported: list[str] = []
    _banks(monkeypatch, imported)
    state = CreativeState()
    state.stock_query = "pizza"  # stale, from the product screen
    await CreativeState.search_inspiration.fn(state, "background")  # empty box: the kit
    assert state.stock_results_for == ""
    await CreativeState.use_inspiration_hit.fn(state, "background", TILE["id"], "image")
    assert imported == ["hamburguesa local"]

    state.inspiration_queries = {"background": "local de noche"}
    await CreativeState.search_inspiration.fn(state, "background")
    assert state.stock_results_for == "background"
    await CreativeState.use_inspiration_hit.fn(state, "background", TILE["id"], "image")
    assert imported[-1] == "local de noche"


async def test_a_second_search_while_one_runs_is_refused(monkeypatch) -> None:
    """Review 2026-11-03 (race): the hits never change owner before they land."""
    calls: list[str] = []

    async def search(self: CreativeState, **kwargs: object) -> None:
        calls.append("search")

    monkeypatch.setattr(CreativeState, "_stock_search", search)
    monkeypatch.setattr(CreativeState, "_vstock_search", search)
    state = CreativeState()
    state.inspiration_queries = {"products": "papas", "background": "local"}
    state.stock_results_for = "products"
    state.stock_loading = True  # the products slot's search is running
    await CreativeState.search_inspiration.fn(state, "background")
    assert calls == [] and state.stock_results_for == "products"


def test_enter_searches_only_that_slot() -> None:
    state = CreativeState()
    assert CreativeState.inspiration_search_on_enter.fn(state, "background", "a") is None
    spec = CreativeState.inspiration_search_on_enter.fn(state, "background", "Enter")
    assert spec is not None


# -- 5. a slot of several keeps its inspiration open until full -------------------------


def _stock_video(n: int) -> dict[str, str]:
    return {"key": f"t/tenant/stock/pixabay/v{n}.mp4", "name": "Inspiración", "source": "x"}


def test_clip_videos_take_up_to_three_from_inspiration() -> None:
    state = CreativeState()
    state.choose_category("clip")
    state.clip_videos = [_stock_video(1)]
    assert "clip_videos" not in state.inspiration_held
    state.clip_videos = [_stock_video(n) for n in range(1, CLIP_MAX_VIDEOS + 1)]
    assert "clip_videos" in state.inspiration_held
    assert INSPIRATION_SLOT_LIMITS["clip_videos"] == CLIP_MAX_VIDEOS
    assert content_generator.SEVERAL_FILE_TARGETS == ("products", "clip_images", "clip_videos")


def test_the_products_slot_counts_each_photo_once() -> None:
    """Review 2026-11-03: a catalog photo also in the piece's own list counts once."""
    state = CreativeState()
    state._set_kind("static_flyer")
    stock = [f"t/tenant/stock/pixabay/p{n}.jpg" for n in range(5)]
    state._selected_product_photo_keys = stock
    state.media_product_keys = list(stock)  # the same five, picked again
    assert len(state._product_keys_in("static_flyer")) == 5
    assert "products" not in state.inspiration_held  # 5 of 10: still room
    state.media_product_keys = [*stock, *(f"t/tenant/stock/pixabay/q{n}.jpg" for n in range(5))]
    assert "products" in state.inspiration_held


def test_a_single_slot_still_folds_after_one_inspiration() -> None:
    state = CreativeState()
    state.reference_video_key = "t/tenant/stock/pixabay/v1.mp4"
    assert "reference" in state.inspiration_held


# -- 6. the campaign «Crear otra» keeps is named while folded ---------------------------


def test_the_folded_hint_names_the_campaign_the_piece_goes_into() -> None:
    assert campaign_hint("nosotros", clip=True) == (
        "Va en la campaña «nosotros». Puedes cambiarla o quitarla aquí."
    )
    assert campaign_hint("", clip=True).startswith("El sonido, los subtítulos")
    assert campaign_hint("", clip=False).startswith("Agrupa esta publicación")
    assert campaign_hint("", clip=True, new=True) == (
        "Va en una campaña nueva. Puedes cambiarla o quitarla aquí."
    )


# -- 7. «Publicaciones» thumbnails are read again before their tokens die ---------------


def test_piece_thumbnails_are_read_again_before_their_tokens_expire() -> None:
    assert PIECE_VIEWS_FRESH_SECONDS < VIEW_TTL_SECONDS
    state = CreativeState()
    state.piece_items = [{"key": "r2/p.jpg", "media_type": "image", "label": "P", "view": "/v"}]
    state._pieces_loaded_at = time.time()
    assert CreativeState.set_picker_tab.fn(state, "background", "pieces") is None
    state._pieces_loaded_at = time.time() - PIECE_VIEWS_FRESH_SECONDS - 1
    reload = CreativeState.set_picker_tab.fn(state, "background", "pieces")
    assert reload is not None


async def test_a_slot_search_uses_its_words_and_an_empty_box_the_brand_kit(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    async def typed(
        self: CreativeState, *, more: bool, text: str | None = None, owner: str = ""
    ) -> None:
        calls.append(("typed", text))
        self.stock_results_for = owner

    async def kit(self: CreativeState, *, more: bool = False) -> None:
        calls.append(("kit", None))
        self.stock_results_for = ""

    async def videos(
        self: CreativeState, *, more: bool, from_kit: bool, text: str = "", owner: str = ""
    ) -> None:
        calls.append(("videos", "kit" if from_kit else text))

    monkeypatch.setattr(CreativeState, "_stock_search", typed)
    monkeypatch.setattr(CreativeState, "_stock_kit_search", kit)
    monkeypatch.setattr(CreativeState, "_vstock_search", videos)
    state = CreativeState()
    state.inspiration_queries = {"background": "local de noche", "products": "papas"}
    await CreativeState.search_inspiration.fn(state, "products")
    assert calls == [("typed", "papas"), ("videos", "papas")]
    assert state.stock_results_for == "products" and state.stock_query == ""
    calls.clear()
    await CreativeState.search_inspiration.fn(state, "clip_videos")
    assert calls == [("kit", None), ("videos", "kit")]
    assert state.stock_results_for == ""


def test_the_reel_line_and_its_link() -> None:
    from .generator_summary_vm import source_reel_href, source_reel_text

    reel = {"handle": "@inspiracion", "platform": "instagram", "url": "https://i.co/r/1"}
    assert source_reel_text(reel) == "@inspiracion (Instagram)"
    assert source_reel_href(reel) == "https://i.co/r/1"
    assert source_reel_href({"url": "javascript:alert(1)"}) == ""
    assert source_reel_text({"platform": "tiktok"}) == "Un reel de TikTok"

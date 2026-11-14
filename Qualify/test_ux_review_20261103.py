"""UX review of m-24820842 (2026-11-03), the `Qualify/` side: «Crear otra» split in two,
«Mejorando…» that never spins forever, «Recursos de tu marca» one decision at a time,
the summary's plain logo names, the partial gallery's button and the minor texts."""

from __future__ import annotations

import asyncio
import json
import time
from uuid import uuid4

import pytest

from . import creative_state as module
from .creative_state import CreativeState
from .creative_vm import (
    FINISH_GALLERY_MANY,
    FINISH_GALLERY_ONE,
    finish_gallery_label,
    gallery_missing_slides,
)
from .generator_summary_vm import (
    LOGO_SIGNATURE_REQUEST,
    LOGO_SIGNATURE_TEXT,
    brand_resources_text,
    logo_plain_name,
)


def _js(text: str) -> str:
    return json.dumps(text)[1:-1]


class _Proxy:
    """Reflex's StateProxy in a test: `async with self` is a no-op lock."""

    def __init__(self, state: CreativeState) -> None:
        object.__setattr__(self, "_state", state)

    async def __aenter__(self) -> _Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __getattr__(self, name: str) -> object:
        return getattr(self._state, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._state, name, value)


def _summary(state: CreativeState) -> dict[str, dict[str, str]]:
    state.go_to_view(str(len(state.gen_views) - 1))  # the summary
    return {row["label"]: row for row in state.gen_summary}


_LOGOS = [
    {"key": "r2/imago.png", "label": "Imagotipo", "kind": "logo", "view": "/r2media/a"},
    {"key": "r2/iso.png", "label": "Isotipo", "kind": "logo", "view": "/r2media/b"},
    {"key": "r2/bag.png", "label": "Bolsa", "kind": "element", "view": "/r2media/c"},
]


def _piece_in_progress() -> CreativeState:
    state = CreativeState()
    state.choose_category("carousel")
    state.brief_topic = "Promo de la galería"
    state.brief_highlights = [{"key": "precio", "value": "20 $"}]
    state.brief_must_mention = "Envío gratis"
    state.brief_must_avoid = "Descuento"
    state.brand_media_items = list(_LOGOS)
    state.brand_logo_key = "r2/imago.png"
    state.brand_element_keys = ["r2/bag.png"]
    state.media_product_keys = ["uploads/t/p.jpg"]
    state.media_product_names = ["p.jpg"]
    state.gen_campaign = "camp-1"
    return state


# -- 1. «Crear otra»: another version, or a new publication -----------------------------


def test_the_result_offers_another_version_and_a_new_publication() -> None:
    from .content_generator import NEW_PIECE_LABEL, NEW_VERSION_LABEL, _result_view

    rendered = str(_result_view())
    assert _js(NEW_VERSION_LABEL) in rendered and "new_generation" in rendered
    assert _js(NEW_PIECE_LABEL) in rendered and "start_new_piece" in rendered
    assert NEW_VERSION_LABEL == "Hacer otra versión de esta"
    assert NEW_PIECE_LABEL == "Crear una publicación nueva"


def test_a_new_publication_starts_with_the_brand_only() -> None:
    state = _piece_in_progress()
    CreativeState.start_new_piece.fn(state)
    assert state.brief_topic == "" and state.brief_highlights == []
    assert state.brief_must_mention == "" and state.brief_must_avoid == ""
    assert state.brand_logo_key == "" and state.brand_element_keys == []
    assert state.media_product_keys == [] and state.clip_images == []
    assert state.gen_campaign == CreativeState().gen_campaign
    assert state.selected_product_id == "" and not state.media_drawer_open
    assert state.brand_media_items == _LOGOS  # the brand stays


def test_another_version_keeps_everything_but_the_campaign() -> None:
    state = _piece_in_progress()
    CreativeState.new_generation.fn(state)
    assert state.brief_topic == "Promo de la galería"
    assert state.brand_logo_key == "r2/imago.png"
    assert state.media_product_keys == ["uploads/t/p.jpg"]
    assert state.carried_text_kind == "carousel"
    assert state.carried_text_notice is False  # same kind: nothing to warn about


def test_another_kind_with_the_last_text_shows_the_notice_and_borrarlo_clears_it() -> None:
    from .content_generator import CARRIED_TEXT_NOTICE, _section_topic

    state = _piece_in_progress()
    CreativeState.new_generation.fn(state)
    state.choose_category("clip")
    assert state.carried_text_notice is True
    rendered = str(_section_topic())
    assert _js(CARRIED_TEXT_NOTICE) in rendered and "clear_carried_text" in rendered
    CreativeState.clear_carried_text.fn(state)
    assert state.brief_topic == "" and state.carried_text_notice is False


def test_the_notice_needs_text_and_goes_once_the_piece_is_created() -> None:
    state = _piece_in_progress()
    state.brief_topic = ""
    CreativeState.new_generation.fn(state)
    state.choose_category("clip")
    assert state.carried_text_notice is False  # no text came along
    state = _piece_in_progress()
    CreativeState.start_new_piece.fn(state)
    assert state.carried_text_kind == ""


def test_crear_otra_publicacion_after_approval_starts_clean_too() -> None:
    state = _piece_in_progress()
    CreativeState.go_create_another.fn(state)
    assert state.brief_topic == "" and state.brand_logo_key == ""
    assert state.media_product_keys == []


# -- 2. «Mejorando…» never spins forever -----------------------------------------------


def _stuck(state: CreativeState, *, alive: bool, age: float) -> None:
    token = uuid4().hex
    state.context_enhancing = True
    state._context_enhance_token = token
    state._context_enhance_started = time.time() - age
    if alive:
        module._ENHANCE_RUNNING.add(token)


def test_a_run_that_died_with_the_server_gives_the_button_back_on_load() -> None:
    state = CreativeState()
    _stuck(state, alive=False, age=1)
    state._settle_stuck_enhance()
    assert state.context_enhancing is False
    assert state.context_enhance_error.startswith("No pudimos mejorar tu texto esta vez.")


def test_a_live_run_within_the_limit_is_left_alone_but_not_past_it() -> None:
    state = CreativeState()
    _stuck(state, alive=True, age=1)
    state._settle_stuck_enhance()
    assert state.context_enhancing is True
    _stuck(state, alive=True, age=module.ENHANCE_TIMEOUT_SECONDS + 1)
    state._settle_stuck_enhance()
    assert state.context_enhancing is False


async def test_load_create_and_reconnects_settle_a_stuck_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_session(self: CreativeState) -> None:
        return None

    monkeypatch.setattr(CreativeState, "_session_ids", no_session)
    state = CreativeState()
    _stuck(state, alive=False, age=5)
    await CreativeState.load_create.fn(_Proxy(state))
    assert state.context_enhancing is False


async def test_a_slow_rewrite_times_out_with_the_message_and_keeps_the_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def ids(self: CreativeState) -> tuple[object, object, object]:
        return uuid4(), uuid4(), uuid4()

    def slow(*args: object, **kwargs: object) -> object:
        time.sleep(0.3)
        raise AssertionError("never read: the run timed out")

    monkeypatch.setattr(module, "enhance_generator_context", slow)
    monkeypatch.setattr(module, "ENHANCE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(CreativeState, "_session_ids", ids)
    state = CreativeState()
    state.choose_category("clip")
    state.brief_topic = "smash doble con papas"
    await CreativeState.enhance_context.fn(_Proxy(state))
    assert state.context_enhancing is False
    assert state.brief_topic == "smash doble con papas"
    assert "Tu texto quedó igual" in state.context_enhance_error
    assert not module._ENHANCE_RUNNING or state._context_enhance_token == ""
    await asyncio.sleep(0.3)  # let the abandoned thread finish


# -- 3. «Recursos de tu marca»: the logo, where it goes, and «Más opciones» -------------


def test_the_brand_block_asks_one_thing_at_a_time() -> None:
    from .content_generator import (
        BRAND_LOGO_PLACE_TITLE,
        BRAND_LOGO_TITLE,
        BRAND_OTHER_IMAGES_TITLE,
        _brand_resources,
    )

    rendered = str(_brand_resources())
    for text in (BRAND_LOGO_TITLE, BRAND_LOGO_PLACE_TITLE, BRAND_OTHER_IMAGES_TITLE):
        assert _js(text) in rendered
    # the first answer names the piece (review 2026-11-04): the state's label
    assert "logo_in_scene_label" in rendered and _js(LOGO_SIGNATURE_TEXT) in rendered
    assert "set_brand_logo_usage" in rendered and "toggle_brand_more_open" in rendered
    assert '"radiogroup"' in rendered
    for gone in ("variantes", "notas de uso", "Sin nota de uso", "se cuenta aparte"):
        assert gone not in rendered
    # an avatar's block is already inside «Más opciones»: not folded twice
    assert "toggle_brand_more_open" not in str(_brand_resources(folded=False))


def test_the_corner_choice_travels_as_a_field_not_in_the_owners_words() -> None:
    """m-24820842 (2026-11-04): «En una esquina, como firma» is
    `MediaInputs.brand_logo_placement`; the topic is only what the owner wrote."""
    state = CreativeState()
    state.choose_category("image")
    state.ad_scene_prompt = "Un vaso en la barra"
    state.brand_media_items = list(_LOGOS)
    CreativeState.toggle_brand_logo.fn(state, "r2/imago.png")
    form = state._generator_form()
    assert form["topic"] == "Un vaso en la barra"
    assert form["media"]["brand_logo_placement"] == "scene"  # type: ignore[index]
    CreativeState.set_brand_logo_usage.fn(state, "signature")
    form = state._generator_form()
    assert form["topic"] == "Un vaso en la barra"
    assert form["media"]["brand_logo_placement"] == "signature"  # type: ignore[index]
    # the summary shows the owner's words, and repeats the choice
    rows = _summary(state)
    assert rows["Escena"]["value"] == "Un vaso en la barra"
    assert rows["Dónde irá tu logo"]["value"] == LOGO_SIGNATURE_TEXT


def test_a_replicas_corner_choice_leaves_its_guidance_alone() -> None:
    state = CreativeState()
    state.choose_category("clip")
    state.brief_topic = "Mi smash"
    state.replication_context = "Guía del reel"
    state.clip_videos = [{"key": "uploads/t/reel.mp4", "name": "reel", "source": "reel"}]
    state.brand_media_items = list(_LOGOS)
    CreativeState.toggle_brand_logo.fn(state, "r2/imago.png")
    CreativeState.set_brand_logo_usage.fn(state, "signature")
    form = state._generator_form()
    assert LOGO_SIGNATURE_REQUEST not in str(form["topic"])
    assert str(form["topic"]).startswith("Mi smash")
    assert form["media"]["brand_logo_placement"] == "signature"  # type: ignore[index]


def test_a_template_never_gets_a_placement() -> None:
    state = CreativeState()
    state.choose_category("template")
    state.brief_topic = "Promo"
    state.brand_media_items = list(_LOGOS)
    state.brand_logo_key = "r2/imago.png"
    state.brand_logo_in_scene = False
    form = state._generator_form()
    assert form["topic"] == "Promo"
    assert "brand_logo_placement" not in form["media"]  # type: ignore[operator]


# -- 4. «Revisa y crea»: the logo by sight and in plain words ---------------------------


def test_the_logos_have_plain_names() -> None:
    assert logo_plain_name("Imagotipo") == "el dibujo con el nombre"
    assert logo_plain_name("Isotipo") == "solo el dibujo"
    assert logo_plain_name("Mi sello") == "Mi sello"
    assert (
        brand_resources_text(
            logo_label="Imagotipo", other_logos=1, elements=1, other_logo_labels=("Isotipo",)
        )
        == "Tu logo: el dibujo con el nombre · También: solo el dibujo · 1 imagen de tu marca"
    )
    assert brand_resources_text(logo_label="Logo", other_logos=0, elements=2) == (
        "Tu logo · 2 imágenes de tu marca"
    )


def test_the_summary_shows_the_logos_picture() -> None:
    from .content_generator import _summary_view

    state = CreativeState()
    state.choose_category("clip")
    state.brand_media_items = list(_LOGOS)
    state.brand_logo_key = "r2/imago.png"
    row = _summary(state)["Recursos de tu marca"]
    assert row["thumb"] == "/r2media/a"
    assert '["thumb"]' in str(_summary_view())


# -- 5. the partial gallery: the button agrees with the number, and says what it costs --


def test_the_missing_slides_come_from_the_backends_counts() -> None:
    assert gallery_missing_slides(3, 2) == 1
    assert gallery_missing_slides(3, 1) == 2
    assert gallery_missing_slides(0, 2) == gallery_missing_slides(3, 0) == 0
    assert finish_gallery_label(1) == FINISH_GALLERY_ONE == "Crear la que falta"
    assert finish_gallery_label(2) == finish_gallery_label(0) == FINISH_GALLERY_MANY


def test_the_button_names_one_or_many_and_the_cost() -> None:
    from .creative_pages import finish_gallery_button

    rendered = str(finish_gallery_button(CreativeState.finish_gallery_current, 1))  # type: ignore[arg-type]
    assert _js(FINISH_GALLERY_ONE) in rendered and _js(FINISH_GALLERY_MANY) in rendered
    # the cost note is the state's: "" (and hidden) when no creations apply (2026-11-04)
    assert "finish_gallery_note" in rendered


# -- 6. minor texts ----------------------------------------------------------------------


def test_the_minor_texts() -> None:
    from .content_generator import (
        BACKGROUND_UPLOAD_HINT,
        CLIP_SUBTITLES_HINT,
        CLIP_SUBTITLES_LABEL,
        _ad_image_section,
    )
    from .reel_replication import REPLICA_TEXT_OFF

    assert BACKGROUND_UPLOAD_HINT.startswith("Toca para subir la foto del lugar")
    assert "Arrastra la foto de tu local" not in str(_ad_image_section())
    assert CLIP_SUBTITLES_LABEL == "Poner en el video la frase inicial y la invitación a comprar"
    assert "antes de aprobarlo" in CLIP_SUBTITLES_HINT
    assert REPLICA_TEXT_OFF == "Quitamos los textos de la otra marca y no agregamos tus frases"
    state = CreativeState()
    state.choose_category("clip")
    assert _summary(state)["Subtítulos"]["value"] == "Sin subtítulos"
    state.set_clip_subtitles(True)
    assert _summary(state)["Subtítulos"]["value"] == "Frase inicial e invitación a comprar"


# -- a clip's middle catalog photo reaches the brief (draft 9808559f) -------------------


def test_a_clips_middle_catalog_photo_reaches_the_brief() -> None:
    """Live 2026-11-03, draft 9808559f: opening = a catalog photo, middle = a second
    catalog photo as «Producto», closing = a Pixabay image, and two Pixabay videos. The
    middle photo is a reference image of the brief, never dropped on the way."""
    from .creative_provider import build_brief

    state = CreativeState()
    state.choose_category("clip")
    state.clip_images = [
        {"key": "t/catalog/p1.jpg", "name": "Foto", "source": "catalog", "role": "product"},
        {"key": "t/catalog/p2.jpg", "name": "Foto", "source": "catalog", "role": "product"},
        {"key": "t/stock/pixabay/i.jpg", "name": "Insp", "source": "inspiration", "role": "style"},
    ]
    state._sync_clip_frames()
    state.clip_videos = [
        {"key": f"t/stock/pixabay/v{n}.mp4", "name": "Insp", "source": "inspiration"}
        for n in (1, 2)
    ]
    state._sync_clip_frames()
    assert [i["key"] for i in state._clip_strip()] == [
        "t/catalog/p1.jpg",
        "t/catalog/p2.jpg",
        "t/stock/pixabay/v1.mp4",
        "t/stock/pixabay/v2.mp4",
        "t/stock/pixabay/i.jpg",
    ]
    state.brief_topic = "Mi producto"
    form = state._generator_form()
    media = form["media"]
    assert media["clip_first_frame_key"] == "t/catalog/p1.jpg"  # type: ignore[index]
    assert media["clip_last_frame_key"] == "t/stock/pixabay/i.jpg"  # type: ignore[index]
    assert media["clip_image_keys"] == ["t/catalog/p2.jpg"]  # type: ignore[index]
    assert media["clip_image_roles"] == ["product"]  # type: ignore[index]
    brief = build_brief(uuid4(), **form)  # type: ignore[arg-type]
    assert brief.media.clip_image_keys == ("t/catalog/p2.jpg",)
    assert len(brief.media.clip_video_keys) == 2


async def test_the_live_clip_sequence_through_the_real_handlers_keeps_the_middle_photo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Draft 9808559f, replayed with the event handlers the screen calls, in order: the
    catalog product (its photo A opens the clip), catalog photo B, an Inspiración image
    C (it closes the clip), two Inspiración videos, steps 3 and 4. B stays a middle
    reference image all the way to the brief."""

    async def ids(self: CreativeState) -> tuple[object, object, object]:
        return uuid4(), uuid4(), uuid4()

    def imported(*args: object, **kwargs: object) -> dict[str, str]:
        item = args[3]
        return {"key": item["key"], "author": "a", "view": "/v", "poster_view": "/p"}  # type: ignore[index]

    monkeypatch.setattr(CreativeState, "_session_ids", ids)
    monkeypatch.setattr(module, "import_stock_image", imported)
    monkeypatch.setattr(module, "import_stock_video", imported)
    a, b, c = "t/c/A.jpg", "t/c/B.jpg", "t/stock/pixabay/C.jpg"
    state = CreativeState()
    state.catalog_items = [
        {"id": "p1", "name": "Smash", "photo_key": a, "photo_keys": f"{a}\n{b}", "video_keys": ""}
    ]
    state.choose_product("p1")
    state.choose_category("clip")
    assert state.clip_first_frame_key == a  # the product's photo opens the clip
    # m-24985141: both product photos came in (b too)
    state._stock_items = {"c": {"key": c}}
    state._vstock_items = {f"v{n}": {"key": f"t/stock/pixabay/V{n}.mp4"} for n in (1, 2)}
    await CreativeState.use_inspiration_hit.fn(_Proxy(state), "clip_images", "c", "image")
    for n in (1, 2):
        await CreativeState.use_inspiration_hit.fn(_Proxy(state), "clip_videos", f"v{n}", "video")
    state.next_view()
    state.next_view()
    assert [item["key"] for item in state._clip_strip()] == [
        a,
        b,
        "t/stock/pixabay/V1.mp4",
        "t/stock/pixabay/V2.mp4",
        c,
    ]
    media = state._generator_form()["media"]
    assert media["clip_first_frame_key"] == a  # type: ignore[index]
    assert media["clip_last_frame_key"] == c  # type: ignore[index]
    assert media["clip_image_keys"] == [b]  # type: ignore[index]
    assert media["clip_image_roles"] == ["product"]  # type: ignore[index]


async def test_changing_the_duration_and_creating_still_sends_the_middle_photo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Draft 9808559f: «Revisa y crea» counted 3 images; the owner then changed 10 s →
    5 s and pressed «Crear». What «Crear» hands to the provider still holds B."""
    a, b, c = "t/c/A.jpg", "t/c/B.jpg", "t/stock/pixabay/C.jpg"
    state = CreativeState()
    state.catalog_items = [
        {"id": "p1", "name": "Smash", "photo_key": a, "photo_keys": f"{a}\n{b}", "video_keys": ""}
    ]
    state.choose_product("p1")
    state.choose_category("clip")
    # m-24985141: both product photos came in (b too)
    state._inspiration_files = {c: {"name": "Inspiración · rolfvandewal", "media": "image"}}
    state.pick_media("clip_images", "inspiration", c)
    state.set_clip_duration("10")
    assert _summary(state)["Referencias"]["value"] == "3 fotos"
    state.set_clip_duration("5")
    sent: list[dict[str, object]] = []

    async def create(self: CreativeState, form: dict[str, object], **_: object) -> None:
        sent.append(form)
        return None

    monkeypatch.setattr(CreativeState, "_create_draft", create)
    async for _ in CreativeState.submit_generator_form.fn(_Proxy(state)):
        pass
    media = sent[0]["media"]
    assert media["duration_seconds"] == 5  # type: ignore[index]
    assert media["clip_first_frame_key"] == a and media["clip_last_frame_key"] == c  # type: ignore[index]
    assert media["clip_image_keys"] == [b]  # type: ignore[index]

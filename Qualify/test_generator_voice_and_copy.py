"""The generator's three asks of 2026-10-06: a flag when the Brand Kit's Tu voz y tono is
still to configure (and the way there), the copy prompt printed to the console on
«¿Todo listo?» before Generar, and "Copiar guion" taking the shots too."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from . import brand_finish, creative_provider
from .creative_state import TONE_DEFAULT, CreativeState, generator_sections
from .creative_vm import KitFormVM, build_variant_vm, script_clipboard

_TENANT_ID = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND_ID = UUID("b0000000-0000-4000-8000-000000000001")


# --------------------------------------------------------------------------------------
# Copiar guion: the script and its shots
# --------------------------------------------------------------------------------------


def test_copying_the_script_takes_its_shots_under_it() -> None:
    vm = build_variant_vm(
        variant_id="v1",
        ordinal=0,
        copy={
            "hook": "Mira esto",
            "caption": "Caption",
            "script": "Hola, hoy te muestro la smash.\n",
            "shots": [
                {"visual": "Plano de la plancha", "line": "Así se aplasta", "seconds": 4},
                {"visual": "Primer plano del queso", "line": "", "seconds": 3},
            ],
        },
        edited_copy=None,
        fidelity={"passed": True},
    )
    assert vm.script_clipboard == (
        "Hola, hoy te muestro la smash.\n"
        "\n"
        "Tomas:\n"
        "1 · 4 s — Plano de la plancha: «Así se aplasta»\n"
        "2 · 3 s — Primer plano del queso"
    )


def test_a_scripts_description_is_its_caption_and_cta_without_the_hook() -> None:
    vm = build_variant_vm(
        variant_id="v1",
        ordinal=0,
        copy={
            "hook": "Mira esto",
            "caption": "La smash llegó.",
            "cta": "Pide al DM",
            "hashtags": ["smash", "#burger"],
            "script": "Mira esto. La smash llegó.",
        },
        edited_copy=None,
        fidelity={"passed": True},
    )
    assert vm.description == "La smash llegó.\n\nPide al DM"
    assert vm.hashtags_text == "#smash #burger"


def test_the_script_result_shows_the_description_and_the_hashtags() -> None:
    from .content_generator import _script_result

    rendered = str(_script_result())
    assert (
        r"Descripci\u00f3n de la publicaci\u00f3n" in rendered and "description" in rendered
    )  # JS-escaped
    assert "Hashtags" in rendered and "hashtags_text" in rendered


def test_a_script_without_shots_copies_alone() -> None:
    assert script_clipboard("Solo el guion.", ()) == "Solo el guion."


def test_the_copy_button_puts_the_script_and_shots_on_the_clipboard() -> None:
    from .content_generator import _script_result

    rendered = str(_script_result())
    assert "script_clipboard" in rendered
    assert "Copiar guion y tomas" in rendered


# --------------------------------------------------------------------------------------
# The voice flag
# --------------------------------------------------------------------------------------


def _fake_kit_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    saved: bool = False,
    tone: int = TONE_DEFAULT,
    clone: object | None = None,
) -> None:
    from qualify_api.creative import voice_clone

    details = SimpleNamespace(connect={"voice_configured": True} if saved else {})
    monkeypatch.setattr(
        brand_finish,
        "BrandKitStore",
        lambda: SimpleNamespace(load_details=lambda **_: details),
    )
    form = KitFormVM(tone_formal_casual=tone)
    monkeypatch.setattr(creative_provider, "load_kit_form", lambda *_: form)
    monkeypatch.setattr(
        voice_clone, "VoiceCloneService", lambda: SimpleNamespace(current=lambda **_: clone)
    )


@pytest.mark.parametrize(
    ("sources", "configured"),
    [
        ({}, False),
        ({"saved": True}, True),
        ({"tone": TONE_DEFAULT + 20}, True),
        ({"clone": object()}, True),
    ],
)
def test_voice_counts_as_configured_like_the_brand_kit_editor(
    monkeypatch: pytest.MonkeyPatch, sources: dict[str, Any], configured: bool
) -> None:
    _fake_kit_sources(monkeypatch, **sources)
    assert brand_finish.kit_voice_configured(_TENANT_ID, _BRAND_ID) is configured


async def test_a_failed_voice_check_never_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: object) -> bool:
        raise RuntimeError("db down")

    monkeypatch.setattr(brand_finish, "kit_voice_configured", broken)
    assert await CreativeState._kit_voice_missing(_TENANT_ID, _BRAND_ID) is False
    monkeypatch.setattr(brand_finish, "kit_voice_configured", lambda *_: False)
    assert await CreativeState._kit_voice_missing(_TENANT_ID, _BRAND_ID) is True


def test_the_flag_shows_on_the_form_and_sends_to_the_brand_kit() -> None:
    from .content_generator import _voice_flag, generator_page

    assert "kit_voice_missing" in str(generator_page())
    flag = str(_voice_flag())
    assert "Preparar mi voz" in flag and "no tiene su voz" in flag
    assert CreativeState.configure_voice.fn(CreativeState()) is not None  # rx.redirect


# --------------------------------------------------------------------------------------
# The prompt in the console before Generar
# --------------------------------------------------------------------------------------


def test_generar_prints_the_prompt_it_sends() -> None:
    """§ 2026-10-08: no «¿Todo listo?» step any more — Generar itself prints the prompt
    (`preview_prompt`) right before the draft is created."""
    import inspect

    source = inspect.getsource(CreativeState.submit_generator_form.fn)
    assert "CreativeState.preview_prompt" in source
    assert source.index("preview_prompt") < source.index("_create_draft(form)")


def test_the_preview_renders_the_brief_generar_would_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class _Service:
        def preview_prompt(self, *, tenant_id: UUID, brand_id: UUID, brief: Any) -> bool:
            seen["brief"] = brief
            return True

    monkeypatch.setattr(creative_provider, "production_content_service", _Service)
    state = CreativeState()
    state.brief_kind = "creator_script"
    state.brief_topic = "  Smash doble  "
    state.brief_must_mention = "jueves, 2x1"
    form = state._generator_form()
    assert creative_provider.preview_brief_prompt(_TENANT_ID, _BRAND_ID, **form) is True
    assert seen["brief"] == creative_provider.build_brief(_BRAND_ID, **form)
    assert seen["brief"].topic == "Smash doble"
    assert seen["brief"].constraints.must_mention == ("jueves", "2x1")


# --------------------------------------------------------------------------------------
# § request 2026-10-06 (second round): videos take one option, «Revisar y aprobar» waits
# for the piece, the topic is a general context, imagen publicitaria leaves the picker
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "options"),
    [
        ("creator_script", 3),
        ("avatar_video", 1),
        ("animated_avatar_video", 1),
        ("template", 1),
        ("static_flyer", 1),
    ],
)
def test_only_the_creators_script_offers_options(kind: str, options: int) -> None:
    """§ 2026-10-08: options only for a real creator's script; one copy for the rest
    until the angles engine exists."""
    state = CreativeState()
    state.brief_kind = kind
    assert state._generator_form()["variants_requested"] == options


def test_review_waits_until_the_piece_is_done() -> None:
    from .content_generator import _result_view
    from .creative_vm import DraftVM

    state = CreativeState()
    assert state.gen_is_done is False  # nothing yet
    state.gen_draft = DraftVM(
        draft_id="d", status="drafting", status_label="", status_tone="", is_drafting=True
    )
    assert state.gen_is_done is False
    state.gen_draft = DraftVM(draft_id="d", status="generated", status_label="", status_tone="")
    assert state.gen_is_done is True
    rendered = str(_result_view())
    assert "gen_is_done" in rendered and "Disponible cuando termine de crearse" in rendered


def test_the_picker_offers_its_categories_with_the_ad_image_back() -> None:
    """Imagen publicitaria left on 2026-10-06 and came back on 2026-10-07, generated by
    Seedream; Carrusel joined on 2026-10-09. § request 2026-10-14: the panel names them
    Guion · Clip · Galería · Flyer · Plantilla · Ad (the template's Reel, out of Video),
    under «Descubrir reels»; Borradores keeps the kind's own name."""
    from .content_generator import _kind_picker
    from .creative_vm import CATEGORY_OPTIONS, KIND_LABELS, VIDEO_TYPE_OPTIONS

    assert [(key, title) for key, title, *_ in CATEGORY_OPTIONS] == [
        ("script", "Guion para grabar"),
        ("video", "Avatar"),
        ("clip", "Clip"),
        ("carousel", "Galería"),
        ("image", "Imagen"),
        ("template", "Plantilla"),
    ]  # «Ad» left the panel on 2026-10-14
    assert [(key, title) for key, title, *_ in VIDEO_TYPE_OPTIONS] == [
        ("avatar_video", "Avatar humano"),
        ("animated_avatar_video", "Avatar animado"),
    ]
    rendered = str(_kind_picker())
    assert "Descubrir reels" in rendered and "Imagen" in rendered and '"Ad"' not in rendered
    assert KIND_LABELS["static_flyer"] == "Imagen publicitaria"
    state = CreativeState()
    assert (state.gen_category, state.brief_kind) == ("script", "creator_script")
    state.choose_category("image")
    assert (state.gen_category, state.brief_kind) == ("image", "static_flyer")
    assert state.gen_kind_label == "Imagen publicitaria"
    # § 2026-10-20: the scene is the ad image's context, asked in «Contexto»
    assert generator_sections(state.brief_kind) == ["topic", "channel", "details"]


def test_the_options_live_in_a_side_panel_and_the_centre_names_the_choice() -> None:
    """§ request 2026-10-14: the kinds are a side panel; the centre heads with the
    chosen one (for Clip, its type) and no longer repeats the picker."""
    from .content_generator import _kind_header, _options_panel, generator_page
    from .creative_vm import CATEGORY_OPTIONS, VIDEO_TYPE_OPTIONS

    def shown(text: str, rendered: str) -> bool:  # the render escapes non-ASCII
        return text in rendered or json.dumps(text)[1:-1] in rendered

    panel = str(_options_panel())
    assert "q-cr-options" in panel and shown("¿Qué creamos?", panel)
    assert "Tipo de contenido" in panel and "open_discover" in panel
    header = str(_kind_header())
    for _key, title, blurb, _icon in (*CATEGORY_OPTIONS, *VIDEO_TYPE_OPTIONS):
        assert shown(title, header) and shown(blurb, header)
    page = str(generator_page())
    assert "q-cr-layout" in page
    assert page.count("Tipo de contenido") == 1  # the picker is only in the panel


def test_each_option_is_a_sequence_of_views() -> None:
    """CREAR-2 (m-24848530): every option is four short steps — ① Qué mostrar ② Qué
    decir ③ Cómo la quieres ④ Revisa y crea. What a kind cannot do without is in step
    1; «Datos clave» and «Campaña» are in step 3, behind «Más opciones»."""
    from .creative_state import generator_steps, generator_views

    assert generator_views("video", "avatar_video") == [
        "avatar_type",
        "presenter",
        "details",
        "topic",
        "channel",
        "rules",
        "campaign",
        "summary",
    ]
    assert generator_steps("video", "avatar_video") == [
        ("show", ["avatar_type", "presenter", "details"]),
        ("say", ["topic"]),
        ("how", ["channel", "rules", "campaign"]),
        ("review", ["summary"]),
    ]
    # no «Presentador» for the animated avatar: its character is in «Tipo de avatar»
    assert "presenter" not in generator_views("video", "animated_avatar_video")
    # the ad's photos, the template's photos and the gallery's slides are in step 1
    assert generator_steps("image", "static_flyer")[0] == ("show", ["details"])
    assert generator_steps("template", "template")[0] == ("show", ["details"])
    assert generator_steps("carousel", "carousel")[0] == ("show", ["details"])
    # Clip and Ad take their references in step 1
    assert generator_steps("clip", "clip")[0] == ("show", ["reference"])
    # the creator's script shows nothing of its own: «Paso N de 3», never an empty step
    assert [step for step, _ in generator_steps("script", "creator_script")] == [
        "say",
        "how",
        "review",
    ]
    for category, kind in (
        ("video", "avatar_video"),
        ("image", "static_flyer"),
        ("clip", "clip"),
        ("carousel", "carousel"),
        ("template", "template"),
    ):
        steps = generator_steps(category, kind)
        assert [step for step, _ in steps] == ["show", "say", "how", "review"]
        # nothing optional in step 1, nothing a kind needs behind «Más opciones»
        assert not {"rules", "campaign"} & set(steps[0][1])
    state = CreativeState()
    state.choose_category("video")
    assert state.gen_view == "avatar_type" and state.gen_is_first_view
    assert state.gen_step_count == "Paso 1 de 4"
    state.next_view()
    assert state.gen_step_key == "say" and state.gen_step_count == "Paso 2 de 4"
    state.go_to_view("99")  # clamped to the last step
    assert state.gen_step_key == "review" and state.gen_is_last_view
    state.next_view()
    assert state.gen_step_key == "review"
    state.prev_view()
    assert state.gen_step_key == "how"
    assert state.gen_step_views == ["channel", "rules", "campaign"]
    steps = state.gen_view_steps
    assert [step["label"] for step in steps] == [
        "Qué mostrar",
        "Qué decir",
        "Cómo la quieres",
        "Revisa y crea",
    ]
    assert steps[0]["done"] == "true" and steps[2]["current"] == "true"
    # another option starts on its own first step
    state.choose_category("carousel")
    assert state.gen_step == 0 and state.gen_view == "details"
    # «Descubrir reels» is a mode of its own; picking an option goes back to creating
    state.open_discover()
    assert state.gen_mode == "discover"
    state.choose_category("carousel")
    assert state.gen_mode == "create"


def test_the_topic_and_siguiente_reach_crear() -> None:
    """CREAR-2: with the same kind and format as last time, writing the topic and
    «Siguiente» reach «Crear» with nothing missing; «Atrás» keeps what was written."""
    for category in ("script", "clip", "image"):
        state = CreativeState()
        state.choose_category(category)
        while state.gen_step_key != "say":
            state.next_view()
        if state.brief_kind == "static_flyer":
            state.set_ad_scene_prompt("Una mano sosteniendo el vaso, luz cálida")
        else:
            state.set_brief_topic("La smash doble, solo este fin de semana")
        while not state.gen_is_last_view:
            state.next_view()
        assert state.gen_step_key == "review"
        assert state.gen_problem == "", category
        state.prev_view()
        state.prev_view()
        assert state.gen_step_key == "say"
        assert state.brief_topic or state.ad_scene_prompt


def test_the_four_steps_render_with_mas_opciones_folded() -> None:
    """CREAR-2: «Paso N de M», «Más opciones» folded with its 44 px target, «Crear» as
    the last step's action, and «Datos clave» saying they never change the brand."""
    from .content_generator import _create_view, _more_options, _section_rules, _step_say

    view = str(_create_view())
    assert "gen_step_count" in view and "gen_step_key" in view
    assert '"Crear"' in view and '"Generar"' not in view
    more = str(_more_options())
    assert json.dumps("Más opciones")[1:-1] in more
    assert "toggle_rules" in more and "44px" in more
    rules = str(_section_rules())
    assert "tu marca no cambia" in rules
    # the avatar's script is asked in «Qué decir»
    assert "set_own_script_on" in str(_step_say())


def test_avatar_holds_the_presenters_and_clip_follows_it() -> None:
    """§ request 2026-10-14: the human and animated presenters are «Avatar»; «Clip» is
    the next option — a generated video with no presenter."""
    from .content_generator import _avatar_type_view, _kind_picker

    picker = str(_kind_picker())
    assert picker.index('"Avatar"') < picker.index('"Clip"') < picker.index("Galer")
    assert "Tipo de avatar" in str(_avatar_type_view())
    state = CreativeState()
    state.choose_category("video")
    assert state.gen_mode == "create" and state.gen_view == "avatar_type"


def _clip_state_with_product() -> CreativeState:
    state = CreativeState()
    state.catalog_items = [
        {
            "id": "p1",
            "name": "Smash doble",
            "photo_key": "uploads/t/p1.jpg",
            "photo_keys": "uploads/t/p1.jpg\nuploads/t/p1b.jpg",
        }
    ]
    state.choose_product("p1")
    state.confirm_product()
    return state


def test_a_clip_follows_the_ads_flow_and_starts_on_the_catalog_photo() -> None:
    """§ requests 2026-10-14/20: Clip is Referencias → Publicación → Datos clave →
    Contexto → Campaña → Resumen;
    the catalog product chosen first is a reference and, applied from it, the opening
    frame — sent once, as the frame."""
    state = _clip_state_with_product()
    state.choose_category("clip")
    assert (state.gen_category, state.brief_kind) == ("clip", "clip")
    assert state.gen_views == ["reference", "topic", "channel", "rules", "campaign", "summary"]
    labels = [step["label"] for step in state.gen_view_steps]
    assert labels == [
        "Qué mostrar",
        "Qué decir",
        "Cómo la quieres",
        "Revisa y crea",
    ]
    assert state.clip_first_frame_key == "uploads/t/p1.jpg"
    assert state.clip_image_keys == ["uploads/t/p1.jpg"]
    assert state.product_photo_keys == ["uploads/t/p1.jpg", "uploads/t/p1b.jpg"]
    media = state._media_inputs()
    assert media["clip_first_frame_key"] == "uploads/t/p1.jpg"
    assert media["clip_image_keys"] == [] and "product_keys" not in media
    assert state.brief_product_ref == "Smash doble"


def test_a_clip_takes_catalog_and_uploaded_references_and_frames() -> None:
    """§ request 2026-10-14: the images are dragged into order — the first opens the
    clip, the last closes it; the ones between are references with a role."""
    from qualify_creative.schemas import MediaInputs

    p1, p1b, ref = "uploads/t/p1.jpg", "uploads/t/p1b.jpg", "uploads/t/ref.mp4"
    state = _clip_state_with_product()
    state.choose_category("clip")
    state.pick_media("clip_images", "catalog", p1b)
    state.pick_media("clip_images", "catalog", "uploads/other-tenant/x.jpg")  # not listed
    assert state.clip_image_keys == [p1, p1b]
    assert (state.clip_first_frame_key, state.clip_last_frame_key) == (p1, p1b)
    assert state.clip_image_room == 7
    # dragging the second onto the first swaps the frames
    state.start_clip_image_drag(1)
    state.drop_clip_image(0)
    assert (state.clip_first_frame_key, state.clip_last_frame_key) == (p1b, p1)
    assert state.clip_drag_from == -1
    state.start_clip_image_drag(0)
    state.drop_clip_image(0)  # onto itself: nothing moves
    assert state.clip_image_keys == [p1b, p1]
    # a reference video joins the strip BETWEEN the frames: it lends its movement and
    # only opens or closes the clip when it is dragged there (§ 2026-10-19)
    state.clip_videos = [{"key": ref, "name": "ref.mp4", "source": "upload"}]
    state.clip_audios = [{"key": "uploads/t/song.mp3", "name": "song.mp3", "source": "upload"}]
    state._sync_clip_frames()
    assert [item["key"] for item in state.clip_strip] == [p1b, ref, p1]
    assert (state.clip_first_frame_key, state.clip_last_frame_key) == (p1b, p1)
    assert state.clip_has_references
    media = MediaInputs.model_validate(state._media_inputs())
    assert media.clip_image_keys == ()  # both images are frames
    assert media.clip_video_keys == (ref,)
    assert media.clip_audio_keys == ("uploads/t/song.mp3",)
    assert state._kind_problem() == ""
    # one image left: it opens the clip and nothing closes it; none: no frames
    state.remove_clip_video(ref)
    state.remove_clip_image(p1)
    assert (state.clip_first_frame_key, state.clip_last_frame_key) == (p1b, "")
    state.remove_clip_image(p1b)
    assert (state.clip_first_frame_key, state.clip_last_frame_key) == ("", "")


def test_a_video_can_open_or_close_the_clip() -> None:
    """§ request 2026-10-19: «que el drag and drop incluya los videos y estos se puedan
    poner como inicio y final» — the brief carries the video as the frame (the producer
    takes its first or last frame) and keeps it as a moving reference."""
    from qualify_creative.schemas import MediaInputs

    p1, p1b, ref = "uploads/t/p1.jpg", "uploads/t/p1b.jpg", "uploads/t/ref.mp4"
    state = _clip_state_with_product()
    state.choose_category("clip")
    state.pick_media("clip_images", "catalog", p1b)
    state.clip_videos = [{"key": ref, "name": "ref.mp4", "source": "upload"}]
    state._sync_clip_frames()
    assert [item["kind"] for item in state.clip_strip] == ["image", "video", "image"]
    state.start_clip_image_drag(1)
    state.drop_clip_image(0)  # the video opens the clip
    assert (state.clip_first_frame_key, state.clip_last_frame_key) == (ref, p1b)
    media = MediaInputs.model_validate(state._media_inputs())
    assert media.clip_first_frame_key == ref and media.clip_last_frame_key == p1b
    assert media.clip_image_keys == (p1,)  # the image between: a reference
    assert media.clip_video_keys == (ref,)
    state.start_clip_image_drag(0)
    state.drop_clip_image(2)  # and now it closes it
    assert (state.clip_first_frame_key, state.clip_last_frame_key) == (p1, ref)
    assert state.clip_image_keys == [p1, p1b]


def test_the_clip_views_render() -> None:
    """§ request 2026-10-14: the images are dragged into order (the drag script, the
    drop handler); the frames are marked on them; no Seedance note."""
    from .content_generator import _SLIDE_DRAG_JS, _clip_references_view

    refs = str(_clip_references_view())
    assert "clip_images" in refs and "clip_videos" in refs and "clip_audios" in refs
    assert "pick_media" in refs and "drop_clip_image" in refs and "start_clip_image_drag" in refs
    assert "data-slide-group" in refs and "q-cr-slide--drag" in refs
    assert "Inicio" in refs and "Final" in refs and "Seedance" not in refs
    assert "clip" in _SLIDE_DRAG_JS


def test_generar_guion_explains_that_a_ugc_creator_records_it() -> None:
    """§ request 2026-10-14: «Generar guion», with a tooltip saying a UGC creator gets
    it and what UGC is."""
    from .content_generator import _kind_picker

    picker = str(_kind_picker())
    assert "Guion para grabar" in picker
    assert "lo graba una persona real" in picker
    assert "UGC" not in picker  # m-24842979: no anglicisms facing the owner


def test_every_kind_takes_the_catalog_product_chosen_first() -> None:
    """§ request 2026-10-14 («verifica si todo está tomando como referencia lo
    seleccionado del catálogo»): the product's name goes on every brief; its photos
    reach every kind that shows a product — the flyer's mode counts them (before, with
    nothing uploaded, the flyer was the scene alone and dropped them), and each gallery
    slide picks among them."""
    state = _clip_state_with_product()
    photos = ["uploads/t/p1.jpg", "uploads/t/p1b.jpg"]
    assert state.brief_product_ref == "Smash doble"
    for category in ("video", "image", "template", "ad"):
        state.choose_category(category)
        media = state._media_inputs()
        assert media["product_keys"] == photos, category
    state.choose_category("image")
    assert state._ad_mode() == "product"
    state.choose_category("clip")
    assert state._media_inputs()["clip_first_frame_key"] == "uploads/t/p1.jpg"
    state.choose_category("carousel")
    # no photo by default (2026-10-14, «quita las imágenes por defecto»): each slide
    # picks its own among the catalog product's
    assert [s["photo_key"] for s in state.carousel_slides] == [""] * 3
    state.select_carousel_slide(2)
    state.set_slide_photo_from_catalog("uploads/t/p1b.jpg")
    assert state.carousel_slides[2]["photo_key"] == "uploads/t/p1b.jpg"
    state.set_slide_photo_from_catalog("uploads/other/x.jpg")  # not the product's
    assert state.carousel_slides[2]["photo_key"] == "uploads/t/p1b.jpg"
    state.select_carousel_slide(0)
    state.set_slide_photo_from_catalog("uploads/t/p1.jpg")
    photos_sent, _slides = state._carousel_slides_payload(False)
    assert photos_sent == ["uploads/t/p1.jpg", "uploads/t/p1b.jpg"]
    state.set_slide_photo_from_catalog("uploads/t/p1.jpg")  # the same again: taken off
    assert state.carousel_slides[0]["photo_key"] == ""
    state.choose_category("script")
    assert state._media_inputs()["product_keys"] == []  # a real creator records it


def test_the_gallery_slide_editor_sits_under_the_slides_and_picks_catalog_photos() -> None:
    """§ request 2026-10-14: the slide's kind, photo, «¿Qué muestra?», text and length
    under the slides across the view; the photo picked among the catalog product's,
    no upload while the product has photos; the drag animated by `slide-drag.js`."""
    from pathlib import Path

    from .content_generator import _carousel_section, _slide_editor, _slide_photo

    photo = str(_slide_photo())
    assert "pick_media" in photo and "product_photo_keys" in photo
    assert "creative_slide_photo" in photo  # only the fallback, with no catalog photos
    editor = str(_slide_editor())
    for label in ("Tipo de diapositiva", "Foto del producto", "Título", "Duración"):
        assert label in editor or json.dumps(label)[1:-1] in editor, label
    section = str(_carousel_section())
    assert "data-slide-key" in section and "q-cr-slide--drag" in section
    from .content_generator import _SLIDE_DRAG_JS

    assert "__qSlideDrag" in _SLIDE_DRAG_JS  # the motion, sent when the gallery mounts
    assert "draggable" not in section  # the browser's own drag is gone
    assert "40rem" not in section  # the slides take the whole view
    script = (Path(__file__).parent.parent / "assets" / "slide-drag.js").read_text("utf-8")
    assert '"dragstart"' in script and '"drop"' in script and "q-shifting" in script
    css = (Path(__file__).parent.parent / "assets" / "qualify-creative.css").read_text("utf-8")
    assert ".q-cr-slide--drag.q-shifting" in css and "q-cr-slide-land" in css


def test_a_gallery_slide_keeps_its_identity_through_moves_and_kind_changes() -> None:
    """`slide-drag.js` tells the slides apart by `data-slide-key`: the key follows the
    slide when it moves and survives a change of kind or a piece put in its place."""
    state = _clip_state_with_product()
    state.choose_category("carousel")
    uids = [row["uid"] for row in state.carousel_slide_rows]
    assert len(set(uids)) == 3 and all(uids)
    state.start_slide_drag(0)
    state.drop_slide(2)
    assert [row["uid"] for row in state.carousel_slide_rows] == [uids[1], uids[2], uids[0]]
    state.select_carousel_slide(1)
    state.set_slide_source("animated")
    assert state.carousel_slides[1]["uid"] == uids[2]
    state.piece_items = [{"key": "t/x/a.jpg", "media_type": "image", "label": "A", "view": ""}]
    state.pick_piece("t/x/a.jpg")
    assert state.carousel_slides[1]["uid"] == uids[2]
    _photos, payload = state._carousel_slides_payload(False)
    assert all("uid" not in slide for slide in payload)  # never reaches the brief


def _picker_state() -> CreativeState:
    state = _clip_state_with_product()
    state.piece_items = [
        {"key": "t/x/generated/d/r1/a.png", "media_type": "image", "label": "Promo", "view": "/v"},
        {"key": "t/x/generated/d/r2/v.mp4", "media_type": "video", "label": "Reel", "view": ""},
    ]
    return state


def test_every_slot_takes_the_catalog_an_upload_or_a_piece() -> None:
    """§ request 2026-10-14: «en todas partes se puedan ver y seleccionar lo que venga del
    catálogo, importarlo a mano y/o desde las piezas ya creadas». The catalog and the
    pieces go through `pick_media`, which only places what the session listed."""
    state = _picker_state()
    piece, reel = "t/x/generated/d/r1/a.png", "t/x/generated/d/r2/v.mp4"
    # the catalog's photos are in by default; each can be ticked out
    state.choose_category("image")
    assert state._media_inputs()["product_keys"] == ["uploads/t/p1.jpg", "uploads/t/p1b.jpg"]
    state.pick_media("products", "catalog", "uploads/t/p1b.jpg")
    assert state.catalog_off == ["uploads/t/p1b.jpg"]
    assert state._media_inputs()["product_keys"] == ["uploads/t/p1.jpg"]
    # a piece's image as a product photo and as the background
    state.pick_media("products", "pieces", piece)
    assert state._media_inputs()["product_keys"] == [piece, "uploads/t/p1.jpg"]
    assert state.product_items == [{"key": piece, "name": "Promo"}]
    assert state.picker_selected["products"] == [piece, "uploads/t/p1.jpg"]
    # § 2026-10-19: the background has a picker too — a piece's image goes in, and the
    # same one again takes it out
    state.pick_media("background", "pieces", piece)
    assert state.media_background_key == piece
    state.pick_media("background", "pieces", piece)
    assert state.media_background_key == ""
    # never a key nobody listed, nor a video where a photo goes
    state.pick_media("products", "pieces", "t/other/forged.png")
    state.pick_media("products", "pieces", reel)
    state.pick_media("products", "catalog", "uploads/other/x.jpg")
    state.pick_media("nowhere", "pieces", piece)
    assert len(state.media_product_keys) == 1
    # the avatar's reference video and the clip's frames, references and videos
    state.choose_category("video")
    state.pick_media("reference", "pieces", reel)
    assert (state.reference_video_key, state.reference_video_name) == (reel, "Reel")
    state.choose_category("clip")
    state.pick_media("clip_images", "pieces", piece)  # the last image: closes it
    state.pick_media("clip_videos", "pieces", reel)
    clip = state._media_inputs()
    assert clip["clip_first_frame_key"] == "uploads/t/p1.jpg"
    assert clip["clip_last_frame_key"] == piece
    assert clip["clip_image_keys"] == []
    assert clip["clip_video_keys"] == [reel]
    state.pick_media("clip_images", "pieces", piece)  # out: the video is last now
    assert state.clip_last_frame_key == reel  # a video closes the clip (§ 2026-10-19)
    # a gallery slide's photo from a piece
    state.choose_category("carousel")
    state.pick_media("slide", "pieces", piece)
    assert state.carousel_slides[0]["photo_key"] == piece
    assert state._carousel_slides_payload(False)[0] == [piece]


def test_each_slot_opens_on_the_catalog_when_it_has_something_for_it() -> None:
    state = _picker_state()
    tabs = state.picker_tab_view
    assert tabs["products"] == "catalog" and tabs["clip_images"] == "catalog"
    assert tabs["background"] == "upload"  # no catalog tab: not a product (2026-10-19)
    assert tabs["reference"] == "upload"  # the product has no videos
    assert state.set_picker_tab("reference", "pieces") is None  # pieces already listed
    assert state.picker_tab_view["reference"] == "pieces"
    state.set_picker_tab("reference", "nowhere")
    assert state.picker_tab_view["reference"] == "pieces"
    state.piece_items = []
    assert state.set_picker_tab("products", "pieces") is not None  # loads the pieces
    state.clear_product()
    assert state.picker_tab_view["clip_images"] == "upload"


def test_the_picker_is_in_every_slot_that_takes_a_file() -> None:
    from .content_generator import (
        _background_upload,
        _clip_references_view,
        _products_upload,
        _reference_view,
        _slide_photo,
    )

    for slot, target in (
        (_products_upload("Productos"), "products"),
        (_reference_view(), "reference"),
        (_clip_references_view(), "clip_images"),
        (_clip_references_view(), "clip_videos"),
        (_slide_photo(), "slide"),
    ):
        rendered = str(slot)
        assert "pick_media" in rendered and "set_picker_tab" in rendered, target
        assert target in rendered, target
        for tab in ("Catálogo", "Subir", "Publicaciones"):
            assert tab in rendered or json.dumps(tab)[1:-1] in rendered, (target, tab)
    # § 2026-10-19: the background has «Inspiración», «Subir» and «Piezas» — no catalog
    background = str(_background_upload("Fondo", "Arrastra"))
    assert "pick_media" in background and "creative_background" in background
    assert "Inspiraci" in background


def test_datos_clave_carry_any_fact() -> None:
    """§ request 2026-10-14: «Reglas» is «Datos clave»: facts like a price or a
    discount, as rows, that the brief carries (the prompt gets them as JSON). § 2026-10-19:
    the catalog has no price any more, so a product brings none."""
    state = _clip_state_with_product()
    state.choose_product("p1")  # off
    state.choose_product("p1")  # on again
    assert state.brief_highlights == []
    state.add_highlight()
    state.add_highlight()
    state.set_highlight(0, "key", "precio")
    state.set_highlight(0, "value", "$18.900")
    state.set_highlight(1, "key", "descuento")
    state.set_highlight(1, "value", "20 %")
    state.set_highlight(9, "value", "nope")  # no such row
    assert state._highlight_pairs() == [["precio", "$18.900"], ["descuento", "20 %"]]
    state.set_highlight(0, "value", "")  # an empty value is not sent
    assert state._highlight_pairs() == [["descuento", "20 %"]]
    state.remove_highlight(0)
    state.choose_category("image")
    form = state._generator_form()
    assert form["highlights"] == [["descuento", "20 %"]]
    brief = creative_provider.build_brief(_BRAND_ID, **form)
    assert brief.constraints.highlights == (("descuento", "20 %"),)
    # a fact typed by hand stays with the product cleared
    state.clear_product()
    assert state.brief_highlights == [{"key": "descuento", "value": "20 %"}]


def test_datos_clave_are_bounded() -> None:
    from qualify_creative.brand import render_prompt  # noqa: F401 — the module renders it
    from qualify_creative.schemas import BriefConstraints

    with pytest.raises(ValueError):
        BriefConstraints(highlights=(("precio", ""),))
    with pytest.raises(ValueError):
        BriefConstraints(highlights=tuple((f"k{i}", "v") for i in range(13)))


def test_datos_clave_view_offers_rows_and_the_old_rules() -> None:
    from .content_generator import _section_rules

    rendered = str(_section_rules())
    for text in ("Datos clave", "Agregar dato", "Debe mencionar"):
        assert text in rendered or json.dumps(text)[1:-1] in rendered, text
    assert "JSON" not in rendered and "Reglas" not in rendered


def test_the_flyer_puts_its_background_first_and_shows_its_photos() -> None:
    """§ request 2026-10-14: no «Tus fotos (opcionales)»; the background first, uploaded
    only; the product photos — the catalog's ticked and the uploaded — as pictures."""
    from .content_generator import _ad_image_section, _carousel_section

    flyer = str(_ad_image_section())
    assert "Tus fotos" not in flyer and "aparece tal cual" not in flyer
    assert flyer.index("creative_background") < flyer.index("creative_products")
    assert "product_previews" in flyer and "remove_product_preview" in flyer
    gallery = str(_carousel_section())
    assert "Las escenas se generan con IA" not in gallery
    state = _clip_state_with_product()
    state.choose_category("image")
    keys = [item["key"] for item in state.product_previews]
    assert keys == ["uploads/t/p1.jpg", "uploads/t/p1b.jpg"]
    state.remove_product_preview("uploads/t/p1b.jpg")  # a catalog one: unticked
    assert state.catalog_off == ["uploads/t/p1b.jpg"]
    state.media_product_keys, state.media_product_names = ["uploads/t/mine.jpg"], ["mine.jpg"]
    state.remove_product_preview("uploads/t/mine.jpg")
    assert [item["key"] for item in state.product_previews] == ["uploads/t/p1.jpg"]


def test_generar_guion_asks_its_length_in_publicacion() -> None:
    from .content_generator import _section_channel

    channel = str(_section_channel())
    assert "set_media_duration" in channel and "creator_script" in channel
    state = CreativeState()
    state.choose_category("script")
    assert state.gen_views[0] == "topic" and state.gen_views[-1] == "summary"
    assert state.gen_step_count == "Paso 1 de 3"


def test_a_piece_is_named_by_its_title_not_its_prompt() -> None:
    """§ request 2026-10-14: «el título del video, no lo del prompt»."""
    from datetime import datetime

    label = creative_provider._piece_label
    assert label("La smash que te cambia el domingo", "video", None) == (
        "La smash que te cambia el domingo"
    )
    assert label("x" * 50, "image", None) == "x" * 40 + "…"
    assert label("", "video", datetime(2026, 10, 14)) == "Video del 14 oct"
    assert label("", "image", None) == "Imagen"


def test_each_clip_reference_image_has_a_role() -> None:
    """§ request 2026-10-14: «quiero el rol de las imágenes» — the product, the place or
    a style; a piece already made starts as a style, a catalog photo as the product. The
    first and last images are the frames: only the ones between carry a role."""
    state = _picker_state()
    state.choose_category("clip")
    piece = "t/x/generated/d/r1/a.png"
    state.pick_media("clip_images", "catalog", "uploads/t/p1b.jpg")
    state.pick_media("clip_images", "pieces", piece)
    assert [item["role"] for item in state.clip_images] == ["product", "product", "style"]
    state.set_clip_image_role("uploads/t/p1b.jpg", "place")
    state.set_clip_image_role(piece, "hero")  # not a role
    media = state._media_inputs()
    assert media["clip_first_frame_key"] == "uploads/t/p1.jpg"
    assert media["clip_last_frame_key"] == piece
    assert media["clip_image_keys"] == ["uploads/t/p1b.jpg"]
    assert media["clip_image_roles"] == ["place"]
    from .content_generator import _clip_references_view

    rendered = str(_clip_references_view())
    assert "set_clip_image_role" in rendered
    for word in ("Producto", "Lugar", "Estilo"):
        assert word in rendered


def test_a_picture_is_removed_with_its_trash_button() -> None:
    """§ request 2026-10-14: «quiero poder eliminar las imágenes subidas de los
    productos» — every picture has a visible trash button; an uploaded product photo
    goes, a catalog one is unticked."""
    from .content_generator import _products_upload

    rendered = str(_products_upload("Productos"))
    assert "remove_product_preview" in rendered and "trash-2" in rendered.lower().replace(
        "trash2", "trash-2"
    )
    state = _clip_state_with_product()
    state.choose_category("image")
    state.media_product_keys, state.media_product_names = ["uploads/t/mine.jpg"], ["mine.jpg"]
    state.remove_product_preview("uploads/t/mine.jpg")
    assert state.media_product_keys == [] and state.media_product_names == []


# -- «Resumen» and «Potenciar con IA» (§ request 2026-10-20) -----------------------------


def test_the_summary_names_every_choice_and_edits_it_in_its_own_view() -> None:
    state = CreativeState()
    state.choose_category("clip")
    state.brief_highlights = [{"key": "precio", "value": "20 $"}]
    # review 2026-10-20: worked out only while the summary is on screen
    assert state.gen_summary == [] and state.gen_problem == ""
    state.go_to_view(str(len(state.gen_views) - 1))  # the summary
    rows = {row["label"]: row for row in state.gen_summary}
    assert rows["Qué creamos"]["value"] == "Clip"
    assert rows["Datos clave"]["value"] == "precio: 20 $"
    assert rows["Contexto"]["value"].startswith("Falta")
    assert state.gen_problem != ""  # the context is still missing
    # «Editar» goes back to the step that sets it (CREAR-2)
    assert (rows["Contexto"]["view"], rows["Contexto"]["index"]) == ("topic", "1")
    assert (rows["Referencias"]["view"], rows["Referencias"]["index"]) == ("reference", "0")
    assert rows["Datos clave"]["index"] == "2"
    state.edit_view(rows["Datos clave"]["view"])  # behind «Más opciones»: unfolded
    assert state.gen_step_key == "how" and state.rules_open
    state.edit_view(rows["Contexto"]["view"])
    assert state.gen_step_key == "say"
    state.go_to_view("99")
    state.brief_topic = "La smash doble cayendo en cámara lenta"
    rows = {row["label"]: row for row in state.gen_summary}
    assert rows["Contexto"]["value"] == "La smash doble cayendo en cámara lenta"
    assert state.gen_problem == ""


def test_the_animated_avatar_takes_its_character_from_the_brand_kit() -> None:
    """§ request 2026-10-20 (2): «quita lo de abajo… quiero que se obtenga desde el
    brandkit» — nothing to fill in under «Avatar animado»; the character is loaded."""
    from .content_generator import _avatar_type_view

    rendered = str(_avatar_type_view())
    assert "set_avatar_source" not in rendered and "set_avatar_prompt" not in rendered
    state = CreativeState()
    state.choose_category("video")
    events = state.choose_video_type("animated_avatar_video")
    names = [str(e) for e in (events if isinstance(events, list) else [events])]
    assert any("load_brand_character" in name for name in names)
    assert "presenter" not in state.gen_views and "reference" not in state.gen_views
    state.go_to_view(str(len(state.gen_views) - 1))  # the summary
    rows = {row["label"]: row for row in state.gen_summary}
    assert rows["Personaje"]["index"] == ""  # the Brand Kit's: not edited here
    assert rows["Video de referencia"]["view"] == "details"
    assert rows["Video de referencia"]["index"] == "0"  # step 1, «Qué mostrar»


async def test_the_brand_kits_drawn_avatar_is_the_character(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4

    from . import creative_state as module

    async def ids(self: CreativeState) -> tuple[object, object, object]:
        return uuid4(), uuid4(), uuid4()

    monkeypatch.setattr(CreativeState, "_session_ids", ids)
    monkeypatch.setattr(
        module,
        "brand_character",
        lambda *a: {"source": "image", "key": "t/x/brand/b/avatar/a.jpg", "name": "El avatar"},
    )
    state = CreativeState()
    state.choose_category("video")
    state.choose_video_type("animated_avatar_video")
    await CreativeState.load_brand_character.fn(_Proxy(state))
    assert (state.avatar_source, state.avatar_image_key) == ("image", "t/x/brand/b/avatar/a.jpg")
    assert state.avatar_rights_confirmed and state.brand_character_label == "El avatar"
    state.brief_topic = "La smash doble"
    assert "personaje" not in state._form_problem()
    # no drawn avatar: a mascot described from the kit
    monkeypatch.setattr(
        module,
        "brand_character",
        lambda *a: {"source": "ai", "prompt": "A friendly mascot", "name": "La mascota"},
    )
    await CreativeState.load_brand_character.fn(_Proxy(state))
    assert (state.avatar_source, state.avatar_prompt) == ("ai", "A friendly mascot")
    assert state.avatar_image_key == ""
    # no kit at all: Generar says so
    monkeypatch.setattr(module, "brand_character", lambda *a: {})
    await CreativeState.load_brand_character.fn(_Proxy(state))
    assert "Tu marca" in state._form_problem()


def test_the_flyer_asks_its_scene_in_the_context_view() -> None:
    from .content_generator import _ad_image_section, _section_topic

    assert "set_ad_scene_prompt" in str(_section_topic())
    assert "set_ad_scene_prompt" not in str(_ad_image_section())
    state = CreativeState()
    state.choose_category("image")
    state.ad_scene_prompt = "Una mano con el vaso"
    state.go_to_view(str(len(state.gen_views) - 1))  # the summary
    rows = {row["label"]: row for row in state.gen_summary}
    assert rows["Escena"]["value"] == "Una mano con el vaso"


class _Proxy:
    """Reflex's StateProxy in a test (as `test_dashboard_state.py`): `async with self`
    is a no-op lock, every attribute goes to the real state."""

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


async def test_potenciar_replaces_the_context_and_deshacer_brings_it_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4

    from qualify_api.creative.context_ai import ContextProposal

    from . import creative_state as module

    seen: dict[str, object] = {}

    def fake(tenant_id: object, brand_id: object, **form: object) -> ContextProposal:
        seen.update(form)
        return ContextProposal(text="Quiero mostrar la smash doble…", added_facts=("2x1",))

    async def ids(self: CreativeState) -> tuple[object, object, object]:
        return uuid4(), uuid4(), uuid4()

    monkeypatch.setattr(module, "enhance_generator_context", fake)
    monkeypatch.setattr(CreativeState, "_session_ids", ids)
    state = CreativeState()
    state.choose_category("clip")
    state.brief_topic = "smash doble"
    state.brief_highlights = [{"key": "precio", "value": "20 $"}]
    await CreativeState.enhance_context.fn(_Proxy(state))

    assert state.brief_topic == "Quiero mostrar la smash doble…"
    assert seen["text"] == "smash doble" and seen["piece"] == "Clip"
    assert seen["highlights"] == [["precio", "20 $"]]
    assert "2x1" in state.context_enhance_note and not state.context_enhancing
    state.undo_enhance_context()
    assert state.brief_topic == "smash doble" and state.context_before_enhance == ""


async def test_potenciar_writes_a_flyers_scene_and_needs_some_words_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4

    from qualify_api.creative.context_ai import ContextProposal

    from . import creative_state as module

    async def ids(self: CreativeState) -> tuple[object, object, object]:
        return uuid4(), uuid4(), uuid4()

    monkeypatch.setattr(
        module, "enhance_generator_context", lambda *a, **k: ContextProposal(text="Escena rica")
    )
    monkeypatch.setattr(CreativeState, "_session_ids", ids)
    state = CreativeState()
    state.choose_category("image")
    state.ad_scene_prompt = "vaso"
    await CreativeState.enhance_context.fn(_Proxy(state))
    assert state.context_enhance_error != "" and state.ad_scene_prompt == "vaso"
    state.ad_scene_prompt = "un vaso en la barra"
    await CreativeState.enhance_context.fn(_Proxy(state))
    assert state.ad_scene_prompt == "Escena rica" and state.brief_topic == ""
    state.choose_category("clip")  # another kind: nothing of the flyer's to undo
    assert state.context_before_enhance == ""


def test_the_clips_middle_images_are_named_on_the_summary() -> None:
    """Review 2026-10-20: what sits between the first and last file is a reference, and
    the summary says what that needs before Generar."""
    state = CreativeState()
    state.choose_category("clip")
    state.clip_images = [{"key": "uploads/t/a.jpg", "name": "a", "source": "upload"}]
    state.clip_videos = [{"key": "uploads/t/v.mp4", "name": "v", "source": "upload"}]
    state._sync_clip_frames()
    # a third file in the middle is a reference, and the summary says what that needs
    state.clip_images = [
        *state.clip_images,
        {"key": "uploads/t/b.jpg", "name": "b", "source": "upload"},
    ]
    state.clip_sequence = ["uploads/t/a.jpg", "uploads/t/b.jpg", "uploads/t/v.mp4"]
    state._sync_clip_frames()
    assert state._media_inputs()["clip_image_keys"] == ["uploads/t/b.jpg"]
    state.go_to_view(str(len(state.gen_views) - 1))  # the summary
    rows = {row["label"]: row for row in state.gen_summary}
    assert "modelo de video avanzado" in rows["Imágenes del medio"]["value"]

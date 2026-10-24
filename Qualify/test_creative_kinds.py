"""The /create side of the generator's content kinds (§ request 2026-09-25): what the
state asks of each kind before sending, the inputs it sends, how `submit_brief` derives
the image route from them, and how a draft's media and script are shown."""

from __future__ import annotations

import dataclasses
from typing import Any
from uuid import UUID

import pytest
from qualify_api.stock.guard import stock_problems
from qualify_creative.enums import ContentKind, ImageRoute

from . import creative_provider
from .creative_state import CreativeState, generator_sections
from .creative_vm import KIND_OPTIONS, build_media_vms, build_variant_vm

_TENANT_ID = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND_ID = UUID("b0000000-0000-4000-8000-000000000001")
_USER_ID = UUID("c0000000-0000-4000-8000-000000000001")


def test_the_picker_offers_the_seven_kinds_in_order() -> None:
    assert (
        [key for key, *_ in KIND_OPTIONS]
        == [kind.value for kind in ContentKind if kind]
        == [
            "creator_script",
            "avatar_video",
            "animated_avatar_video",
            "static_flyer",
            "template",
            "carousel",
            "clip",
        ]
    )


def test_the_template_kind_is_chosen_and_reads_the_catalog_once() -> None:
    """Since the template engine landed (plan-mvp-plantillas-remotion.md, 2026-10-05)
    «Con plantilla» is a real choice: picking it chains the catalog read for the
    product picker — once, like the avatar kinds and their voices."""
    state = CreativeState()
    assert state.choose_kind("template") is not None  # chains load_catalog_products
    assert state.brief_kind == "template"
    state.catalog_items = [{"id": "p1", "name": "Shawarma mixto"}]
    assert state.choose_kind("template") is None
    assert state.choose_kind("creator_script") is None
    assert state.brief_kind == "creator_script"


def test_an_omnihuman_avatar_kind_loads_its_voices_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_VIDEO_ENGINE", "omnihuman")
    state = CreativeState()
    assert state.choose_kind("avatar_video") is not None  # chains load_voice_options
    assert state.video_engine == "omnihuman" and state.video_reads_with_voice
    state.voice_options = [{"id": "vo", "name": "Elena"}]
    # the voices are not loaded twice; the animated avatar loads its Brand Kit character
    events = state.choose_kind("animated_avatar_video")
    assert [e.fn.__name__ for e in events] == ["load_brand_character"]


def test_a_stale_heygen_engine_falls_back_until_the_presenter_keys_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ request 2026-10-16: HeyGen is retired; OmniHuman takes over on its own the day
    both BytePlus keys are set («dejar todo preparado para cuando tenga las api key»)."""
    from . import creative_provider

    monkeypatch.setenv("QUALIFY_VIDEO_ENGINE", "heygen")
    for env in creative_provider.PRESENTER_KEY_ENVS:
        monkeypatch.delenv(env, raising=False)
    assert creative_provider.configured_video_engine() == "seedance"
    for env in creative_provider.PRESENTER_KEY_ENVS:
        monkeypatch.setenv(env, "k")
    # the keys alone are not enough: OmniHuman downloads the photo and the voice
    monkeypatch.setattr("qualify_api.creative.composition.public_media_ready", lambda: False)
    assert creative_provider.configured_video_engine() == "seedance"
    monkeypatch.setattr("qualify_api.creative.composition.public_media_ready", lambda: True)
    assert creative_provider.configured_video_engine() == "omnihuman"
    monkeypatch.setenv("QUALIFY_VIDEO_ENGINE", "seedance")  # an explicit choice wins
    assert creative_provider.configured_video_engine() == "seedance"


def test_on_seedance_an_avatar_kind_loads_no_voices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ request 2026-10-07: Seedance, the engine while the presenter's keys are missing —
    no library, no voices."""
    from . import creative_provider

    monkeypatch.delenv("QUALIFY_VIDEO_ENGINE", raising=False)
    for env in creative_provider.PRESENTER_KEY_ENVS:
        monkeypatch.delenv(env, raising=False)
    state = CreativeState()
    assert state.choose_kind("avatar_video") is None
    assert state.video_engine == "seedance" and state.video_on_seedance


def test_a_seedance_presenter_is_always_described_and_needs_no_voice() -> None:
    state = CreativeState()
    state.brief_kind = "avatar_video"
    state.video_engine = "seedance"
    assert state._kind_problem() == ""  # «Mujer»: no look, no voice to pick
    media = state._media_inputs()
    assert media["video_engine"] == "seedance"
    assert media["avatar_source"] == "ai" and "Mujer" in str(media["avatar_prompt"])
    assert "voice_id" not in media and "avatar_look_id" not in media
    state.set_human_avatar_mode("custom")
    assert "Describe cómo es la persona" in state._kind_problem()
    state.set_human_avatar_prompt("Chef de 40 años con delantal verde")
    assert state._media_inputs()["avatar_prompt"] == "Chef de 40 años con delantal verde"
    state.brief_kind = "animated_avatar_video"
    state.avatar_source = "image"
    state.avatar_image_key = "uploads/t/mascota.png"
    state.avatar_rights_confirmed = True
    assert state._kind_problem() == ""
    media = state._media_inputs()
    assert media["avatar_image_key"] == "uploads/t/mascota.png" and "voice_id" not in media


_VOICES = [
    {"id": "vo_elena", "name": "Elena", "gender": "female"},
    {"id": "vo_jorge", "name": "Jorge", "gender": "male"},
]


def _catalog_state() -> CreativeState:
    state = CreativeState()
    state.brief_kind = "avatar_video"
    state.video_engine = "omnihuman"
    state.voice_options = list(_VOICES)
    state._sync_voice()
    return state


def test_the_presenters_gender_picks_the_voices_gender() -> None:
    state = _catalog_state()
    assert state.voice_id == "vo_elena"
    assert state._kind_problem() == ""  # «Mujer»: described, no library look to pick
    state.set_human_avatar_mode("male")
    assert [voice["id"] for voice in state.visible_voices] == ["vo_jorge"]
    assert state.voice_id == "vo_jorge"


def test_a_custom_or_animated_presenter_picks_the_voice_gender_itself() -> None:
    state = _catalog_state()
    state.set_human_avatar_mode("custom")
    state.set_voice_gender("male")
    assert state.voice_id == "vo_jorge"
    state.set_voice_gender("robot")  # not a voice gender: ignored
    assert state.voice_gender == "male"


def test_a_custom_human_avatar_is_sent_as_a_described_person() -> None:
    state = _catalog_state()
    state.set_human_avatar_mode("custom")
    assert "Describe cómo es la persona" in state._kind_problem()
    state.set_human_avatar_prompt("  Mujer de 30 años, pelo rizado  ")
    assert state._kind_problem() == ""
    media = state._media_inputs()
    assert media["avatar_source"] == "ai"
    assert media["avatar_prompt"] == "Mujer de 30 años, pelo rizado"
    assert media["voice_id"] == "vo_elena" and "avatar_look_id" not in media


def test_the_ad_image_shows_no_ai_scene_note() -> None:
    """§ request 2026-10-13: «Generamos la escena con IA…» left the ad image's section."""
    from .content_generator import _ad_image_section

    assert "Generamos la escena con IA" not in str(_ad_image_section().render())


def test_the_template_shows_no_note_when_no_catalog_product_is_picked() -> None:
    """§ request 2026-10-13: «Sin producto del catálogo…» left the ad video's section."""
    from .content_generator import _template_details

    assert "Sin producto del catálogo" not in str(_template_details().render())


def test_an_ad_image_asks_only_for_its_scene() -> None:
    """§ request 2026-10-12: the product and background photos are optional — no mode
    to pick, nothing to upload; only the scene is required (§ 2026-10-08)."""
    state = CreativeState()
    state.brief_kind = "static_flyer"
    assert "escena" in state._kind_problem()
    state.set_ad_scene_prompt("Una mano con el vaso")
    assert state._kind_problem() == ""
    state.media_product_keys = ["uploads/t/vaso.png"]
    assert state._kind_problem() == ""


def test_an_ad_image_sends_the_photos_it_has_and_the_mode_they_make() -> None:
    """§ 2026-10-12: the `AdImageMode` follows the uploads — both, one of them, or the
    scene alone — instead of being picked."""
    state = CreativeState()
    state.brief_kind = "static_flyer"
    state.set_ad_scene_prompt("  una mano con el vaso  ")

    alone = state._media_inputs()
    assert alone["ad_mode"] == "scene" and alone["scene_prompt"] == "una mano con el vaso"
    assert alone["background_key"] is None and alone["product_keys"] == []

    state.media_background_key = "uploads/t/bar.jpg"
    assert state._media_inputs()["ad_mode"] == "background"

    state.media_product_keys = ["uploads/t/vaso.png"]
    state.media_carousel = True
    both = state._media_inputs()
    assert both["ad_mode"] == "both"
    assert both["background_key"] == "uploads/t/bar.jpg"
    assert both["product_keys"] == ["uploads/t/vaso.png"]

    state.media_background_key = ""
    product = state._media_inputs()
    assert product["ad_mode"] == "product" and product["background_key"] is None


def test_the_ad_images_scene_is_its_whole_brief() -> None:
    """§ request 2026-10-08: the scene is what the piece is about — sent as its topic."""
    state = CreativeState()
    state.brief_kind = "static_flyer"
    state.brief_topic = "left over from another kind"
    state.set_ad_scene_prompt("  Una mano con el vaso en el local  ")
    assert state._generator_form()["topic"] == "Una mano con el vaso en el local"
    state.brief_kind = "creator_script"
    assert state._generator_form()["topic"] == "left over from another kind"


def test_going_to_review_starts_the_generator_over() -> None:
    """§ request 2026-10-08: back on «Crear pieza» after «Revisar y aprobar», the first
    screen — not the piece already sent to Borradores."""
    state = CreativeState()
    state.generator_view = "result"
    state.gen_draft_id = "d0000000-0000-4000-8000-000000000001"
    state.brief_topic = "Smash doble"
    state.ad_scene_prompt = "Una mano con la smash"
    state.media_product_keys = ["uploads/t/p.png"]

    events = state.review_in_drafts()

    assert "/drafts/d0000000-0000-4000-8000-000000000001" in str(events)
    assert state.generator_view == "form"
    assert state.gen_draft_id == "" and state.brief_topic == ""
    assert state.ad_scene_prompt == "" and state.media_product_keys == []


def test_leaving_the_flyer_drops_the_carousel() -> None:
    state = CreativeState()
    state.media_carousel = True
    state.choose_kind("creator_script")
    assert state.media_carousel is False


@pytest.mark.parametrize(
    ("kind", "fields", "problem"),
    [
        ("avatar_video", {"voice_id": "vo"}, ""),  # «Mujer», described: nothing to pick
        ("avatar_video", {"voice_id": "vo", "human_avatar_mode": "custom"}, "Describe"),
        ("avatar_video", {}, "Elige la voz"),
        # § 2026-10-20: the character comes from the Brand Kit — nothing to describe
        ("animated_avatar_video", {"voice_id": "vo", "avatar_source": "ai"}, "Tu marca"),
        ("animated_avatar_video", {"voice_id": "vo", "avatar_source": "image"}, "Tu marca"),
        (
            "animated_avatar_video",
            {"voice_id": "vo", "avatar_source": "image", "avatar_image_key": "uploads/t/a.png"},
            "Confirma",
        ),
        (
            "static_flyer",
            {"media_product_keys": ["uploads/t/p.png"], "ad_scene_prompt": "Una mano con el vaso"},
            "",
        ),
        ("static_flyer", {"ad_scene_prompt": "Una mano con el vaso"}, ""),  # no photo needed
        ("static_flyer", {"media_product_keys": ["uploads/t/p.png"]}, "Describe la escena"),
        ("static_flyer", {}, "Describe la escena"),
        ("creator_script", {}, ""),
    ],
)
def test_what_each_kind_still_needs_is_said_before_sending(
    kind: str, fields: dict[str, Any], problem: str
) -> None:
    state = CreativeState()
    state.brief_kind = kind
    state.video_engine = "omnihuman"  # the presenter reads in a picked voice
    for name, value in fields.items():
        setattr(state, name, value)
    if problem:
        assert problem in state._kind_problem()
    else:
        assert state._kind_problem() == ""


def test_the_inputs_sent_are_only_the_kinds_own() -> None:
    state = CreativeState()
    state.media_background_key = "uploads/t/bg.png"
    state.media_product_keys = ["uploads/t/p1.png"]
    state.media_carousel = True
    state.avatar_prompt = "un chef"

    state.brief_kind = "creator_script"
    script = state._media_inputs()
    assert script["background_key"] is None and script["product_keys"] == []
    assert script["carousel"] is False

    state.brief_kind = "static_flyer"
    flyer = state._media_inputs()
    # § 2026-10-09: the ad image is one image — the carousel is its own kind
    assert flyer["product_keys"] == ["uploads/t/p1.png"] and flyer["carousel"] is False
    assert "avatar_prompt" not in flyer

    state.brief_kind = "animated_avatar_video"
    state.voice_id = "vo"
    animated = state._media_inputs()
    assert animated["avatar_source"] == "ai" and animated["avatar_prompt"] == "un chef"
    assert animated["carousel"] is False and animated["background_key"] == "uploads/t/bg.png"


def test_removing_a_product_keeps_the_others_in_order() -> None:
    state = CreativeState()
    state.media_product_keys = ["k1", "k2", "k3"]
    state.media_product_names = ["a.png", "b.png", "c.png"]
    state.remove_product("k2")
    assert state.media_product_keys == ["k1", "k3"]
    assert state.media_product_names == ["a.png", "c.png"]


# --------------------------------------------------------------------------------------
# submit_brief derives the image route
# --------------------------------------------------------------------------------------


class _RecordingService:
    def __init__(self) -> None:
        self.briefs: list[Any] = []

    def create_draft(self, *, tenant_id, brand_id, brief, user_id):  # noqa: ANN001, ANN201
        self.briefs.append(brief)
        return UUID("d0000000-0000-4000-8000-000000000001")


def _submit(monkeypatch: pytest.MonkeyPatch, kind: str, media: dict[str, Any]) -> Any:
    service = _RecordingService()
    monkeypatch.setattr(creative_provider, "production_content_service", lambda: service)
    creative_provider.submit_brief(
        _TENANT_ID,
        _BRAND_ID,
        _USER_ID,
        objective="sale",
        content_type="product",
        topic="Smash doble",
        product_ref="",
        intent="organic",
        image_route="",
        source_media_key="",
        must_mention="",
        must_avoid="",
        kind=kind,
        media=media,
    )
    return service.briefs[0]


def test_a_flyer_with_products_is_the_untouched_upload_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brief = _submit(monkeypatch, "static_flyer", {"product_keys": ["uploads/t/p1.png"]})
    assert brief.image_route is ImageRoute.FROM_UPLOAD
    assert brief.source_media_key == "uploads/t/p1.png"
    assert brief.kind is ContentKind.STATIC_FLYER


_STOCK_PHOTO = f"t/{_TENANT_ID}/stock/pixabay/7221445/43104764eeaa4549.jpg"
_STOCK_BACKGROUND = f"t/{_TENANT_ID}/stock/pixabay/10260393/e55e89304d49f8b5.jpg"


def test_an_inspiration_photo_is_never_the_upload_routes_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Draft d75dc864 (2026-10-20): an «Inspiración» photo first among the products became
    `source_media_key`, where the stock guard refuses it — «Esa imagen de stock no puede
    usarse ahí». The operator's own photo is the source; the stock one stays a product."""
    own = f"uploads/{_TENANT_ID}/catalog/p/ef0466ae.jpg"
    brief = _submit(
        monkeypatch,
        "static_flyer",
        {"product_keys": [_STOCK_PHOTO, own], "background_key": _STOCK_BACKGROUND},
    )
    assert brief.image_route is ImageRoute.FROM_UPLOAD
    assert brief.source_media_key == own
    assert brief.media.product_keys == (_STOCK_PHOTO, own)
    assert stock_problems(brief) is None


def test_a_piece_with_only_inspiration_images_has_no_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brief = _submit(
        monkeypatch,
        "static_flyer",
        {"product_keys": [_STOCK_PHOTO], "background_key": _STOCK_BACKGROUND},
    )
    assert brief.image_route is ImageRoute.TEMPLATE_ONLY
    assert brief.source_media_key is None
    assert stock_problems(brief) is None


def test_a_piece_without_images_is_template_only(monkeypatch: pytest.MonkeyPatch) -> None:
    brief = _submit(monkeypatch, "creator_script", {"duration_seconds": 45})
    assert brief.image_route is ImageRoute.TEMPLATE_ONLY
    assert brief.media.duration_seconds == 45


def test_a_clip_brief_carries_the_chosen_length(monkeypatch: pytest.MonkeyPatch) -> None:
    """§ request 2026-10-23: «un límite de tiempo en los clips … desde 5 seg» — 5 s by
    default, 10 or 15 when picked, and nothing else."""
    state = CreativeState()
    assert state.clip_duration == "5"
    assert _submit(monkeypatch, "clip", state._clip_media()).media.duration_seconds == 5
    state.set_clip_duration("10")
    brief = _submit(monkeypatch, "clip", state._clip_media())
    assert brief.kind is ContentKind.CLIP and brief.media.duration_seconds == 10
    for unknown in ("30", "4", "", []):
        state.set_clip_duration(unknown)
        assert state.clip_duration == "10"
    state.set_clip_duration(["15"])
    assert state.clip_duration == "15"


def test_a_clip_comes_with_sound_unless_turned_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """§ request 2026-10-23: «Con audio» — on by default (every clip had sound before)."""
    from .content_generator import _section_channel

    state = CreativeState()
    assert state.clip_audio is True
    assert _submit(monkeypatch, "clip", state._clip_media()).media.clip_audio is True
    state.set_clip_audio(False)
    assert _submit(monkeypatch, "clip", state._clip_media()).media.clip_audio is False
    channel = str(_section_channel())
    assert "set_clip_audio" in channel and "Con audio" in channel
    state.set_clip_duration("10")
    state._reset_media_inputs()
    assert state.clip_audio is True
    assert state.clip_duration == "5"  # the whole clip form goes back to its defaults


def test_the_gallerys_video_is_silent_unless_turned_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """§ request 2026-10-23: «igual la galería» — the animated slide's «Con audio», off
    by default; only the animated slide takes it, and it goes on the brief."""
    from .content_generator import _slide_generated_fields

    state = _carousel_state()
    assert [slide["audio"] for slide in state.carousel_slides] == ["", "", ""]
    state.set_slide_field(0, "audio", "1")  # a still has no sound
    assert state.carousel_slides[0]["audio"] == ""
    state.toggle_slide_audio(1)
    assert state.carousel_slides[1]["audio"] == "1"
    _, slides = state._carousel_slides_payload(False)
    assert [slide.get("audio") for slide in slides] == [None, True, None]
    brief = _submit(monkeypatch, "carousel", {"slides": slides})
    assert [slide.audio for slide in brief.media.slides] == [False, True, False]
    # back to a still: the sound goes with the video
    state.select_carousel_slide(1)
    state.set_slide_source("generated")
    assert state.carousel_slides[1]["audio"] == ""
    state.toggle_slide_audio(1)
    assert state.carousel_slides[1]["audio"] == ""
    fields = str(_slide_generated_fields())
    assert "toggle_slide_audio" in fields and "Con audio" in fields


def test_a_script_can_be_as_short_as_five_seconds() -> None:
    """§ request 2026-10-23: the avatar / script lengths start at 5 s, default 30."""
    state = CreativeState()
    assert state.media_duration == "30"
    for value in ("5", "10", "15", "60"):
        state.set_media_duration(value)
        assert state.media_duration == value
    for unknown in ("20", "90", "", []):
        state.set_media_duration(unknown)
        assert state.media_duration == "60"


def test_a_video_is_vertical_and_carries_its_avatar(monkeypatch: pytest.MonkeyPatch) -> None:
    brief = _submit(monkeypatch, "avatar_video", {"avatar_look_id": "lk", "voice_id": "vo"})
    assert brief.format.value == "reels_9_16"
    assert brief.media.avatar_look_id == "lk" and brief.requires_ai_disclosure


# --------------------------------------------------------------------------------------
# the draft screen
# --------------------------------------------------------------------------------------


def test_media_is_shown_in_order_with_readable_labels() -> None:
    carousel = build_media_vms(
        [
            ("k/2.png", "image", 1, None),
            ("k/1.png", "image", 0, None),
            ("k/3.png", "image", 2, None),
        ]
    )
    assert [(m.key, m.label) for m in carousel] == [
        ("k/1.png", "Diapositiva 1 de 3"),
        ("k/2.png", "Diapositiva 2 de 3"),
        ("k/3.png", "Diapositiva 3 de 3"),
    ]
    (single,) = build_media_vms([("k/1.png", "image", 0, None)])
    assert single.label == "Imagen"
    (video,) = build_media_vms([("k/v.mp4", "video", 0, {"thumbnail_key": "k/t.jpg"})])
    assert (video.label, video.poster_key) == ("Video", "k/t.jpg")


def test_a_variant_shows_its_script_and_shot_list() -> None:
    vm = build_variant_vm(
        variant_id="v1",
        ordinal=0,
        copy={
            "hook": "Mira esto",
            "caption": "Caption",
            "script": "Hola, hoy te muestro la smash.",
            "shots": [
                {"visual": "Plano de la plancha", "line": "Así se aplasta", "seconds": 4},
                {"visual": "Primer plano del queso", "line": "", "seconds": 3},
            ],
        },
        edited_copy=None,
        fidelity={"passed": True},
    )
    assert vm.script == "Hola, hoy te muestro la smash."
    assert vm.shots == (
        "1 · 4 s — Plano de la plancha: «Así se aplasta»",
        "2 · 3 s — Primer plano del queso",
    )


# --------------------------------------------------------------------------------------
# the generator's views: the format, and the result view's state
# --------------------------------------------------------------------------------------


def _formats(state: CreativeState) -> list[str]:
    return [value for value, _ in state.format_options]


ALL_FORMATS = ["reels_9_16", "story_9_16", "feed_4_5", "feed_1_1"]


def test_each_kind_offers_its_formats_and_starts_on_its_default() -> None:
    """§ request 2026-10-13: every kind in every Instagram format that suits it — the
    ad video the Story and the feed posts, the template the square post; a carousel stays
    in the feed, where Instagram takes it. § request 2026-10-21: the Flyer is an image and
    no longer offers the Reel (it animated the still into a video)."""
    state = CreativeState()
    state.choose_kind("static_flyer")
    assert _formats(state) == ["feed_4_5", "feed_1_1", "story_9_16"]
    assert state.effective_format == "feed_4_5"
    # a Reel picked under another kind, or forced, never reaches a flyer's brief
    state.set_brief_format("reels_9_16")
    assert state.effective_format == "feed_4_5"
    assert state._generator_form()["content_format"] == "feed_4_5"
    state.choose_kind("avatar_video")
    assert state.effective_format == "reels_9_16"
    assert ["feed_1_1", "Publicación cuadrada 1:1"] in state.format_options
    for kind in ("creator_script", "avatar_video", "animated_avatar_video"):
        state.choose_kind(kind)
        assert sorted(_formats(state)) == sorted(ALL_FORMATS), kind
    state.choose_category("carousel")
    assert _formats(state) == ["feed_4_5", "feed_1_1"]


def test_the_ad_video_is_offered_in_every_format_and_the_template_as_a_still() -> None:
    """«Ad» (the «Video publicitario», its own option since 2026-10-14) is the template's
    video in any placement; «Plantilla» its still in the feed and story — never a Reel,
    which is a video."""
    state = CreativeState()
    state.choose_category("ad")
    assert state.brief_kind == "template"
    assert _formats(state) == ALL_FORMATS
    state.set_brief_format("story_9_16")
    assert state._media_inputs()["template_video"] is True
    state.choose_category("template")
    assert _formats(state) == ["feed_4_5", "feed_1_1", "story_9_16"]
    assert state._media_inputs()["template_video"] is False


def test_only_a_template_sends_the_template_video_flag() -> None:
    state = CreativeState()
    state.choose_kind("static_flyer")
    assert "template_video" not in state._media_inputs()


def test_a_format_the_kind_does_not_offer_is_ignored_and_a_new_kind_resets_it() -> None:
    state = CreativeState()
    state.choose_category("carousel")
    state.set_brief_format("story_9_16")  # Instagram takes a carousel only in the feed
    assert state.effective_format == "feed_4_5"
    state.set_brief_format("feed_1_1")
    assert state.effective_format == "feed_1_1"
    state.choose_kind("static_flyer")
    assert state.brief_format == "" and state.effective_format == "feed_4_5"


def test_the_ad_image_is_never_a_carousel_any_more() -> None:
    """§ request 2026-10-09: «quitar la opción de carrusel en imágenes publicitarias»."""
    state = CreativeState()
    state.choose_kind("static_flyer")
    state.set_media_carousel(True)
    assert not state.carousel_allowed and state.media_carousel is False
    state.media_carousel = True  # a stale flag never reaches the brief
    assert state._media_inputs()["carousel"] is False
    from .content_generator import _products_upload

    assert "Hacerlo carrusel" not in str(_products_upload("Foto del producto"))


def test_back_to_the_form_keeps_the_inputs() -> None:
    state = CreativeState()
    state.brief_topic = "Smash doble"
    state.generator_view = "result"
    state.gen_draft_id = "d1"
    state.new_generation()
    assert state.generator_view == "form" and state.gen_draft_id == ""
    assert state.brief_topic == "Smash doble"


def test_the_result_view_follows_the_draft() -> None:
    from .creative_vm import build_draft_vm

    state = CreativeState()
    assert state.gen_is_drafting and not state.gen_is_ready  # nothing landed yet
    variants = [
        build_variant_vm(
            variant_id=f"v{i}",
            ordinal=i,
            copy={"hook": "h", "caption": "c", "script": f"guion {i}"},
            edited_copy=None,
            fidelity={"passed": True},
        )
        for i in range(2)
    ]
    state.gen_draft = build_draft_vm(
        draft_id="d1",
        status="generated",
        failure_reason=None,
        variants=variants,
        image_url=None,
        total_cost_usd=None,
        voice_profile_version=1,
        model_ids=(),
        requires_ai_disclosure=False,
        created_label="",
        kind="creator_script",
    )
    assert state.gen_is_ready and state.gen_kind == "creator_script"
    assert state.gen_variant_labels == [["0", "Opción 1"], ["1", "Opción 2"]]
    state.choose_gen_variant("1")
    assert state.gen_variant_vm is not None and state.gen_variant_vm.script == "guion 1"
    state.choose_gen_variant("9")  # out of range → the last one
    assert state.gen_variant_vm.script == "guion 1"


def test_the_chosen_format_reaches_the_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _RecordingService()
    monkeypatch.setattr(creative_provider, "production_content_service", lambda: service)
    creative_provider.submit_brief(
        _TENANT_ID,
        _BRAND_ID,
        _USER_ID,
        objective="sale",
        content_type="product",
        topic="Smash doble",
        product_ref="",
        intent="organic",
        image_route="",
        source_media_key="",
        must_mention="",
        must_avoid="",
        kind="static_flyer",
        media={},
        content_format="story_9_16",
    )
    assert service.briefs[0].format.value == "story_9_16"


def test_an_own_script_and_the_engine_reach_the_inputs() -> None:
    state = CreativeState()
    state.choose_kind("avatar_video")
    state.video_engine = "omnihuman"
    state.voice_id = "vo"
    state.set_own_script_on(True)
    assert "Escribe tu guion" in state._kind_problem()
    state.set_own_script("  Hola, soy Doña Rosa.  ")
    assert state._kind_problem() == ""
    media = state._media_inputs()
    assert media["own_script"] == "Hola, soy Doña Rosa."
    assert media["video_engine"] == "omnihuman" and media["voice_id"] == "vo"
    assert "engine" not in media  # HeyGen's avatar engine is gone
    state.set_own_script_on(False)
    assert "own_script" not in state._media_inputs()


def test_the_subtitles_switch_reaches_an_avatar_videos_inputs_only() -> None:
    """m-24828920: subtitles are the operator's choice, off until they turn them on."""
    state = CreativeState()
    state.choose_kind("avatar_video")
    state.video_engine = "omnihuman"
    state.voice_id = "vo"
    assert state._media_inputs()["subtitles"] is False
    state.set_media_subtitles(True)
    assert state._media_inputs()["subtitles"] is True
    state.choose_kind("static_flyer")
    assert "subtitles" not in state._media_inputs()


# -- the generator as one view with sections (§ request 2026-10-08) --------------------


def test_each_kind_shows_only_its_sections_in_order() -> None:
    assert generator_sections("avatar_video") == ["topic", "channel", "presenter", "details"]
    # § 2026-10-20: the animated avatar's character is chosen in «Tipo de avatar»
    assert generator_sections("animated_avatar_video") == ["topic", "channel", "details"]
    # the script's length is asked in «Publicación» (2026-10-14): no «details»
    assert generator_sections("creator_script") == ["topic", "channel"]
    assert generator_sections("clip") == ["topic", "channel"]
    assert generator_sections("template") == ["topic", "channel", "details"]
    # § 2026-10-20: the ad image's scene is asked in «Contexto», like every context
    assert generator_sections("static_flyer") == ["topic", "channel", "details"]


def test_the_sections_renumber_as_the_kind_changes() -> None:
    state = CreativeState()
    state.brief_kind = "creator_script"
    assert state.gen_section_numbers == {"topic": 1, "channel": 2}
    state.brief_kind = "avatar_video"
    assert state.gen_section_numbers["presenter"] == 3
    assert state.gen_section_numbers["details"] == 4
    state.brief_kind = "static_flyer"
    assert state.gen_section_numbers == {"topic": 1, "channel": 2, "details": 3}


def test_generar_says_the_first_thing_still_missing_in_section_order() -> None:
    state = CreativeState()
    state.brief_kind = "avatar_video"
    state.video_engine = "omnihuman"
    assert "Cuéntanos qué quieres" in state._form_problem()
    state.brief_topic = "Smash doble"
    assert "Elige la voz" in state._form_problem()
    state.voice_id = "vo"
    state.own_script_on = True
    assert "Escribe tu guion" in state._form_problem()
    state.own_script = "Hola, mano."
    assert state._form_problem() == ""


def test_a_creators_script_takes_no_brand_resources() -> None:
    """§ 2026-10-08: no «Recursos de tu marca» for a real creator's script — not shown,
    and nothing chosen for another kind leaks into its brief."""
    state = CreativeState()
    state.brand_logo_key = "t/x/logo.png"
    state.brand_element_keys = ["t/x/sello.png"]
    state.brief_kind = "creator_script"
    media = state._media_inputs()
    assert media["brand_logo_key"] is None and media["brand_element_keys"] == []
    state.brief_kind = "static_flyer"
    media = state._media_inputs()
    assert media["brand_logo_key"] == "t/x/logo.png"
    assert media["brand_element_keys"] == ["t/x/sello.png"]


def test_the_rules_are_folded_until_opened() -> None:
    state = CreativeState()
    assert state.rules_open is False
    state.toggle_rules()
    assert state.rules_open is True


def test_no_kind_asks_for_objetivo_or_destino() -> None:
    """§ request 2026-10-05 ("quitar objetivo y destino en todas las opciones"): every
    kind shares the topic and channel sections, and neither asks any more; the brief
    still carries both fields at their defaults."""
    from .content_generator import _section_channel, _section_topic

    for section in (_section_topic(), _section_channel()):
        rendered = str(section)
        assert '"Objetivo"' not in rendered and '"Destino"' not in rendered
    state = CreativeState()
    assert (state.brief_objective, state.brief_intent) == ("consideration", "organic")


def test_generar_waits_while_a_piece_is_generating() -> None:
    state = CreativeState()
    assert state.gen_generating is False
    state.generator_view = "result"
    state.gen_draft_id = "d1"
    assert state.gen_generating is True  # created, nothing read back yet
    state.gen_timed_out = True
    assert state.gen_generating is False  # it outlasted the wait: free to try again


def test_crear_otro_takes_the_result_away_and_keeps_the_inputs() -> None:
    state = CreativeState()
    state.generator_view = "result"
    state.gen_draft_id = "d1"
    state.brief_topic = "Smash doble"
    event = state.new_generation()
    assert state.generator_view == "form" and state.gen_draft_id == ""
    assert state.brief_topic == "Smash doble"  # to try a variation
    assert "scrollTo" in str(event)


# -- the template kind (plan-mvp-plantillas-remotion.md, 2026-10-05) ---------------------


def test_picking_a_catalog_product_sets_the_reference_photos_and_topic() -> None:
    state = CreativeState()
    state.brief_kind = "template"
    state.catalog_items = [
        {
            "id": "p1",
            "name": "Shawarma mixto",
            "photo_key": "uploads/t/catalog/p1/a.jpg",
            "photo_keys": "uploads/t/catalog/p1/a.jpg\nuploads/t/catalog/p1/b.jpg",
        }
    ]
    state.choose_product("p1")
    assert state.brief_product_ref == "Shawarma mixto"
    assert state.brief_topic == "Shawarma mixto"  # an empty topic takes the name
    assert state.selected_product_photo_key == "uploads/t/catalog/p1/a.jpg"
    assert state.template_photo_count == 2
    # the product's photos ride along in the brief, after the piece's own uploads
    state.media_product_keys = ["uploads/t/extra.jpg", "uploads/t/catalog/p1/a.jpg"]
    media = state._media_inputs()
    assert media["product_keys"] == [
        "uploads/t/extra.jpg",
        "uploads/t/catalog/p1/a.jpg",
        "uploads/t/catalog/p1/b.jpg",
    ]
    assert media["background_key"] is None  # a template takes no background
    assert "template_id" not in media  # the router picks the template
    # a typed topic is never overwritten; picking the same product again unpicks it
    state.brief_topic = "Promo de martes"
    state.choose_product("p1")
    assert state.selected_product_id == "" and state.brief_product_ref == ""
    assert state.brief_topic == "Promo de martes"
    assert state.template_photo_count == 2  # only the piece's own uploads remain


def test_a_template_needs_two_photos_before_generating() -> None:
    """§ 2026-10-08: the template keeps its 2 photos (only the ad image takes one), and
    says so in its own section instead of on Generar."""
    state = CreativeState()
    state.brief_kind = "template"
    state.brief_topic = "Promo"
    assert "al menos 2" in state._form_problem()
    state.media_product_keys = ["uploads/t/a.jpg"]
    assert "al menos 2" in state._form_problem()
    state.media_product_keys = ["uploads/t/a.jpg", "uploads/t/b.jpg"]
    assert state._form_problem() == ""


# -- a carousel shown as a carousel (§ request 2026-10-08) -------------------------------


def _draft_with_media(draft_id: str, *media_types: str):  # noqa: ANN202
    from .creative_vm import MediaVM, build_draft_vm

    return build_draft_vm(
        draft_id=draft_id,
        status="generated",
        failure_reason=None,
        variants=(),
        image_url=None,
        total_cost_usd=None,
        voice_profile_version=None,
        model_ids=(),
        requires_ai_disclosure=True,
        created_label="",
        media=tuple(
            MediaVM(key=f"k/{i}", media_type=kind, position=i, label=f"Slide {i + 1}")
            for i, kind in enumerate(media_types)
        ),
    )


def test_only_several_images_make_a_carousel() -> None:
    state = CreativeState()
    assert not state.gen_is_carousel and not state.draft_is_carousel
    state.gen_draft = _draft_with_media("d1", "image")
    assert not state.gen_is_carousel  # one image: shown as today
    state.gen_draft = _draft_with_media("d1", "video")
    assert not state.gen_is_carousel
    state.gen_draft = _draft_with_media("d1", "image", "image", "image")
    state.draft = _draft_with_media("d2", "image", "image")
    assert state.gen_is_carousel and state.draft_is_carousel


def test_the_arrows_and_dots_stay_within_the_slides() -> None:
    state = CreativeState()
    state.gen_draft = _draft_with_media("d1", "image", "image", "image")
    state.gen_slide_step(-1)
    assert state.gen_slide == 0  # no slide before the first
    state.gen_slide_step(1)
    state.gen_slide_step(1)
    state.gen_slide_step(1)
    assert state.gen_slide == 2  # nor after the last
    state.gen_slide_pick(1)
    assert state.gen_slide == 1
    state.draft = _draft_with_media("d2", "image", "image")
    state.draft_slide_pick(9)
    assert state.draft_slide == 1


def test_the_carousel_moves_on_by_itself_and_wraps_around() -> None:
    """§ 2026-10-08: the slides change by themselves after a short delay."""
    state = CreativeState()
    state.gen_draft = _draft_with_media("d1", "image", "image", "image")
    state.gen_slide_auto()
    state.gen_slide_auto()
    assert state.gen_slide == 2
    state.gen_slide_auto()
    assert state.gen_slide == 0  # after the last, the first again
    state.draft = _draft_with_media("d2", "image", "image")
    state.draft_slide_auto()
    state.draft_slide_auto()
    assert state.draft_slide == 0


def test_a_new_piece_or_another_draft_opens_on_its_first_slide() -> None:
    state = CreativeState()
    state.gen_draft = _draft_with_media("d1", "image", "image")
    state.gen_slide_pick(1)
    state.new_generation()
    assert state.gen_slide == 0
    state._apply_detail(_draft_with_media("d2", "image", "image"))
    state.draft_slide_pick(1)
    state._apply_detail(_draft_with_media("d2", "image", "image"))  # the same, re-read
    assert state.draft_slide == 1
    state._apply_detail(_draft_with_media("d3", "image", "image"))
    assert state.draft_slide == 0


def test_both_screens_show_a_carousel_with_arrows_dots_and_a_counter() -> None:
    from .content_generator import _media_result
    from .creative_pages import _media_column

    for rendered, prefix in (
        (str(_media_result(title="Imagen", icon="image")), "gen"),
        (str(_media_column()), "draft"),
    ):
        assert f"{prefix}_is_carousel" in rendered
        assert f"{prefix}_slide_step" in rendered and f"{prefix}_slide_pick" in rendered
        assert "Diapositiva anterior" in rendered and "Diapositiva siguiente" in rendered
        assert f"{prefix}_slide_auto" in rendered and "10000" in rendered  # the autoplay


def test_the_review_screen_says_when_a_regeneration_kept_the_previous_version() -> None:
    """m-24828909: a regeneration that did not come out leaves the draft `generated` with
    its previous version and a note — shown above the review, not only when it failed."""
    from .creative_pages import _failed_panel, draft_detail_index

    detail_var = "failure_detail"
    in_failed_panel = str(_failed_panel()).count(detail_var)
    assert str(draft_detail_index()).count(detail_var) > in_failed_panel


def test_the_viewer_arrows_are_centred_without_a_transform() -> None:
    """2026-10-09: the kit lifts a solid button on hover with `transform`, which replaced
    the centring `translateY(-50%)` and made the arrow jump away from the pointer."""
    from .media_carousel import AUTOPLAY_MS, _arrow

    assert AUTOPLAY_MS == 10000
    rendered = str(
        _arrow("chevron-right", "Diapositiva siguiente", "right", CreativeState.gen_slide_step(1))
    )
    assert "translateY" not in rendered and "marginTop" in rendered


def test_a_carousel_video_slide_keeps_its_feed_shape_in_both_previews() -> None:
    """2026-10-09: framed 9:16 like a Reel, a 4:5 video slide lost its sides — and the
    words printed on them."""
    from .content_generator import _media_preview
    from .creative_pages import _media_item

    for rendered in (
        str(_media_preview(CreativeState.gen_draft.media[0])),
        str(_media_item(CreativeState.draft.media[0])),
    ):
        assert "q-rv-media--slide" in rendered and "q-rv-media--video" in rendered
        assert "is_slide" in rendered


def test_the_form_is_off_while_a_piece_generates() -> None:
    from .content_generator import generator_page

    rendered = str(generator_page())
    assert "q-cr-form--busy" in rendered and "gen_generating" in rendered
    assert "El formulario se reactiva cuando termine" in rendered


def test_the_app_says_when_the_piece_lands() -> None:
    from .creative_state import _generation_done_events, _notify_js

    ready = [str(event) for event in _generation_done_events("ready")]
    failed = [str(event) for event in _generation_done_events("failed")]
    assert any("Tu publicación est" in event for event in ready)
    assert any("No se pudo crear" in event for event in failed)
    # a piece regenerated in Por aprobar (ex-Piezas) says where to look (pendientes §5)
    draft_ready = [str(event) for event in _generation_done_events("ready", source="draft")]
    draft_failed = [str(event) for event in _generation_done_events("failed", source="draft")]
    assert any("nueva versi" in event and "Por aprobar" in event for event in draft_ready)
    assert any("No se pudo crear la nueva" in event for event in draft_failed)
    # the browser's own notice only when the tab is in the background, and only if allowed
    script = _notify_js("Qualify", "lista")
    assert "document.hidden" in script and "Notification.permission === 'granted'" in script


# -- the carousel kind (§ request 2026-10-09) -------------------------------------------


def _carousel_state() -> CreativeState:
    """A gallery (ex-carrusel): it opens on its three generated slides (§ 2026-10-14);
    the first carries the hook, the second is animated — its one video."""
    state = CreativeState()
    state.choose_category("carousel")
    state.brief_topic = "Promo de la smash doble"
    state.set_slide_field(0, "text", "hook")
    state.select_carousel_slide(1)
    state.set_slide_source("animated")
    state.select_carousel_slide(0)
    return state


def test_the_gallery_opens_on_three_slides_without_a_closing_one() -> None:
    """§ request 2026-10-14: three slides, no closing slide, ready to generate."""
    state = CreativeState()
    state.choose_category("carousel")
    state.brief_topic = "Promo de la smash doble"
    assert (state.gen_category, state.brief_kind) == ("carousel", "carousel")
    # its slides come before where it is published (§ request 2026-10-15)
    assert generator_sections("carousel") == ["topic", "details", "channel"]
    assert [slide["source"] for slide in state.carousel_slides] == ["generated"] * 3
    assert not state.carousel_closing and state.carousel_full
    assert [value for value, _ in state.format_options] == ["feed_4_5", "feed_1_1"]
    assert state._form_problem() == ""
    assert state._media_inputs()["closing_slide"] is False


def test_the_gallery_reorders_by_drag_and_drop() -> None:
    state = _carousel_state()
    state.start_slide_drag(1)  # the animated one
    state.drop_slide(2)
    assert [slide["source"] for slide in state.carousel_slides] == [
        "generated",
        "generated",
        "animated",
    ]
    assert state.carousel_selected == 2 and state.carousel_drag_from == -1
    state.start_slide_drag(0)
    state.drop_slide(0)  # onto itself: nothing moves
    assert state.carousel_slides[0]["text"] == "hook"
    state.select_carousel_slide(9)  # not a slide: ignored
    assert state.carousel_selected == 2


def test_a_slide_changes_kind_and_the_gallery_takes_one_video() -> None:
    state = _carousel_state()
    state.select_carousel_slide(2)
    assert state.carousel_video_taken  # slide 2 is already the video
    state.set_slide_source("animated")
    assert state.carousel_slides[2]["source"] == "generated"
    assert "como máximo 1 video" in state.carousel_notice
    state.select_carousel_slide(1)
    assert not state.carousel_video_taken  # the video is this one
    state.set_slide_source("generated")
    state.select_carousel_slide(2)
    state.set_slide_source("animated")
    assert [slide["source"] for slide in state.carousel_slides] == [
        "generated",
        "generated",
        "animated",
    ]
    assert state.carousel_notice == ""
    assert state.carousel_slides[0]["text"] == "hook"  # a kind change keeps the inputs


def test_a_piece_replaces_the_open_slide_and_respects_one_video() -> None:
    state = _carousel_state()
    state.piece_items = [
        {"key": "t/x/generated/d/r1/video.mp4", "media_type": "video", "label": "Reel", "view": ""},
        {"key": "t/x/a.jpg", "media_type": "image", "label": "A", "view": ""},
    ]
    state.pick_piece("t/other/forged.jpg")  # not in the brand's list
    assert [slide["source"] for slide in state.carousel_slides][2] == "generated"
    state.select_carousel_slide(2)
    state.pick_piece("t/x/generated/d/r1/video.mp4")  # slide 1 is the video
    assert state.carousel_slides[2]["source"] == "generated" and state.carousel_notice
    state.set_slide_source("existing")
    assert state.piece_picker_open
    state.pick_piece("t/x/a.jpg")
    reused = state.carousel_slides[2]
    assert (reused["source"], reused["key"], reused["media_type"]) == (
        "existing",
        "t/x/a.jpg",
        "image",
    )
    assert len(state.carousel_slides) == 3 and not state.piece_picker_open
    state.set_slide_field(2, "text", "hook")  # a reused piece goes as it is
    assert state.carousel_slides[2]["text"] == "none"


def test_a_gallery_without_its_three_slides_or_with_two_videos_blocks_generar() -> None:
    state = _carousel_state()
    state.carousel_slides = state.carousel_slides[:2]
    assert "3 diapositivas" in state._form_problem()
    state = _carousel_state()
    slides = [dict(slide) for slide in state.carousel_slides]
    slides[2]["source"] = "animated"
    state.carousel_slides = slides
    assert "como máximo 1 video" in state._form_problem()


def test_each_slide_brings_its_own_photo_to_the_brief() -> None:
    """§ 2026-10-09: the product photo is the slide's own; the brief carries the photos
    once each and every slide points at its own. No closing slide (2026-10-14)."""
    state = _carousel_state()
    state.media_product_keys = ["uploads/t/left-over.jpg"]  # not the gallery's
    state.media_background_key = "uploads/t/bar.jpg"
    state.carousel_slides = [
        {**state.carousel_slides[0], "photo_key": "uploads/t/burger.jpg"},
        {**state.carousel_slides[1], "photo_key": "uploads/t/burger.jpg", "background": ""},
        state.carousel_slides[2],
    ]
    state.piece_items = [{"key": "t/x/a.jpg", "media_type": "image", "label": "A", "view": ""}]
    state.select_carousel_slide(2)
    state.pick_piece("t/x/a.jpg")
    media = state._media_inputs()
    assert media["product_keys"] == ["uploads/t/burger.jpg"]
    assert media["background_key"] == "uploads/t/bar.jpg"
    assert media["closing_slide"] is False and media["carousel"] is False
    first, second, third = media["slides"]
    assert first == {
        "source": "generated",
        "scene_prompt": "",
        "product_index": 0,
        "use_background": True,
        "text": "hook",
        "seconds": 5,
    }
    assert (second["source"], second["product_index"], second["use_background"]) == (
        "animated",
        0,
        False,
    )
    assert third == {"source": "existing", "object_key": "t/x/a.jpg"}


def test_a_slide_photo_is_uploaded_into_the_open_slide(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    state = _carousel_state()
    state.select_carousel_slide(1)

    async def saved(self: CreativeState, files: list) -> list[tuple[str, str]]:
        return [("uploads/t/papas.jpg", "papas.jpg")]

    monkeypatch.setattr(CreativeState, "_save_uploads", saved)
    asyncio.run(state.handle_slide_photo_upload([object()]))  # type: ignore[list-item]
    assert state.carousel_slides[1]["photo_key"] == "uploads/t/papas.jpg"
    assert state.carousel_slides[0]["photo_key"] == ""
    state.clear_slide_photo()
    assert state.carousel_slides[1]["photo_key"] == ""


def test_a_mixed_carousel_is_shown_as_one_and_holds_on_a_video() -> None:
    from .creative_vm import build_media_vms

    media = build_media_vms(
        [
            ("k/1.jpg", "image", 0, {"slide": 1}),
            ("k/2.mp4", "video", 1, {"slide": 2, "thumbnail_key": "k/2.jpg"}),
        ]
    )
    assert [item.label for item in media] == ["Diapositiva 1 de 2", "Diapositiva 2 de 2"]
    assert media[1].poster_key == "k/2.jpg" and all(item.is_slide for item in media)
    state = CreativeState()
    state.gen_draft = dataclasses.replace(_draft_with_media("d1", "image"), media=media)
    assert state.gen_is_carousel
    state.gen_slide_auto()
    assert state.gen_slide == 1
    state.gen_slide_auto()
    assert state.gen_slide == 1  # a video slide holds until the arrows move on


def test_the_gallery_explains_its_options_and_says_titulo_and_boton() -> None:
    """§ request 2026-10-09: a «?» on each kind of slide, the photo and the background;
    «Gancho» / «Llamado (CTA)» renamed for the operator. The kinds are the open slide's
    since 2026-10-14 (no «+», no closing slide)."""
    import json

    from .content_generator import (
        _carousel_section,
        _slide_generated_fields,
        _slide_kind_picker,
        _slide_stock_fields,
    )

    def rendered(text: str) -> str:  # the compiled JSX escapes every accent
        return json.dumps(text)[1:-1]

    section = str(_carousel_section())
    kinds = str(_slide_kind_picker())
    # § 2026-10-14: only the title — the scene already holds the button
    assert rendered("Título") in section and "toggle_slide_title" in section
    assert rendered("Botón de acción") not in str(_slide_generated_fields())
    # § 2026-10-16: a «Video de stock» slide has no scene holding a button, and it must
    # carry words — the title or, when the title is on another slide, the button
    assert rendered("Botón de acción") in str(_slide_stock_fields())
    assert "Gancho" not in section and "Llamado (CTA)" not in section
    for help_title in ("Foto del producto", "Fondo común (opcional)"):
        assert rendered(f"Qué es «{help_title}»") in section
    assert "Diapositiva de cierre" not in section
    for kind in ("Imagen generada", "Video animado", "De una publicación"):
        assert rendered(f"Qué es «{kind}»") in kinds
    # § 2026-10-19: no «Video de stock» kind — stock comes in as the inspiration
    assert rendered("Video de stock") not in kinds
    state = _carousel_state()
    assert [row["text_label"] for row in state.carousel_slide_rows] == ["Título", "", ""]


def test_the_title_goes_on_one_slide_and_the_button_is_gone() -> None:
    """§ request 2026-10-14: the «Botón de acción» left the slide (the scene holds the
    button); the title is the same hook on every slide, so it goes on one only — the
    first by default."""
    state = CreativeState()
    state.choose_category("carousel")
    assert [slide["text"] for slide in state.carousel_slides] == ["hook", "none", "none"]
    state.toggle_slide_title(2)
    assert [slide["text"] for slide in state.carousel_slides] == ["none", "none", "hook"]
    state.toggle_slide_title(2)
    assert [slide["text"] for slide in state.carousel_slides] == ["none", "none", "none"]
    state.set_slide_field(1, "text", "cta")  # not offered any more
    assert state.carousel_slides[1]["text"] == "none"


def test_back_from_borradores_the_animated_avatar_reloads_its_character() -> None:
    """Review 2026-10-20: the reset clears the character while the kind stays — it is
    loaded again from the Brand Kit, or the next piece would be blocked."""
    state = CreativeState()
    state.brief_kind = "animated_avatar_video"
    state.avatar_prompt = "A friendly mascot"
    state.brand_character_label = "La mascota"
    state.gen_draft_id = "d0000000-0000-4000-8000-000000000001"
    events = state.review_in_drafts()
    assert state.avatar_prompt == "" and state.brand_character_label == ""
    assert events[0].fn.__name__ == "load_brand_character"
    assert "/drafts/d0000000-0000-4000-8000-000000000001" in str(events[1])
    state.brief_kind = "clip"
    assert all("load_brand_character" not in str(e) for e in state.review_in_drafts())

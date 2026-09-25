"""The /create side of the generator's content kinds (§ request 2026-09-25): what the
state asks of each kind before sending, the inputs it sends, how `submit_brief` derives
the image route from them, and how a draft's media and script are shown."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from qualify_creative.enums import ContentKind, ImageRoute

from . import creative_provider
from .creative_state import CreativeState
from .creative_vm import KIND_OPTIONS, build_media_vms, build_variant_vm

_TENANT_ID = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND_ID = UUID("b0000000-0000-4000-8000-000000000001")
_USER_ID = UUID("c0000000-0000-4000-8000-000000000001")


def test_the_picker_offers_the_five_kinds_in_order() -> None:
    assert (
        [key for key, *_ in KIND_OPTIONS]
        == [kind.value for kind in ContentKind if kind]
        == [
            "creator_script",
            "avatar_video",
            "animated_avatar_video",
            "static_flyer",
            "template",
        ]
    )


def test_the_template_is_shown_but_cannot_be_chosen() -> None:
    state = CreativeState()
    state.choose_kind("template")
    assert state.brief_kind == "static_flyer"
    assert state.choose_kind("creator_script") is None
    assert state.brief_kind == "creator_script"


def test_an_avatar_kind_loads_heygens_catalog_once() -> None:
    state = CreativeState()
    assert state.choose_kind("avatar_video") is not None  # chains load_heygen_catalog
    state.heygen_voices = [{"id": "vo", "name": "Elena"}]
    assert state.choose_kind("animated_avatar_video") is None


def test_leaving_the_flyer_drops_the_carousel() -> None:
    state = CreativeState()
    state.media_carousel = True
    state.choose_kind("creator_script")
    assert state.media_carousel is False


@pytest.mark.parametrize(
    ("kind", "fields", "problem"),
    [
        ("avatar_video", {"voice_id": "vo"}, "Elige el avatar"),
        ("avatar_video", {"avatar_look_id": "lk"}, "Elige la voz"),
        ("animated_avatar_video", {"voice_id": "vo", "avatar_source": "ai"}, "Describe"),
        ("animated_avatar_video", {"voice_id": "vo", "avatar_source": "image"}, "Sube la imagen"),
        (
            "animated_avatar_video",
            {"voice_id": "vo", "avatar_source": "image", "avatar_image_key": "uploads/t/a.png"},
            "Confirma",
        ),
        ("static_flyer", {}, ""),
        ("creator_script", {}, ""),
    ],
)
def test_what_each_kind_still_needs_is_said_before_sending(
    kind: str, fields: dict[str, Any], problem: str
) -> None:
    state = CreativeState()
    state.brief_kind = kind
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
    assert flyer["product_keys"] == ["uploads/t/p1.png"] and flyer["carousel"] is True
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


def test_a_piece_without_images_is_template_only(monkeypatch: pytest.MonkeyPatch) -> None:
    brief = _submit(monkeypatch, "creator_script", {"duration_seconds": 45})
    assert brief.image_route is ImageRoute.TEMPLATE_ONLY
    assert brief.media.duration_seconds == 45


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
        ("k/1.png", "Slide 1 de 3"),
        ("k/2.png", "Slide 2 de 3"),
        ("k/3.png", "Slide 3 de 3"),
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


def test_each_kind_offers_its_formats_and_starts_on_its_default() -> None:
    state = CreativeState()
    state.choose_kind("static_flyer")
    assert [value for value, _ in state.format_options] == ["feed_4_5", "feed_1_1", "story_9_16"]
    assert state.effective_format == "feed_4_5"
    state.choose_kind("avatar_video")
    assert state.effective_format == "reels_9_16"
    assert ["feed_1_1", "Post cuadrado 1:1"] in state.format_options


def test_a_format_the_kind_does_not_offer_is_ignored_and_a_new_kind_resets_it() -> None:
    state = CreativeState()
    state.choose_kind("creator_script")
    state.set_brief_format("feed_1_1")  # not offered for a creator's script
    assert state.effective_format == "reels_9_16"
    state.set_brief_format("story_9_16")
    assert state.effective_format == "story_9_16"
    state.choose_kind("static_flyer")
    assert state.brief_format == "" and state.effective_format == "feed_4_5"


def test_the_carousel_is_only_offered_for_a_flyer_in_a_feed_format() -> None:
    state = CreativeState()
    state.choose_kind("static_flyer")
    state.set_media_carousel(True)
    assert state.carousel_allowed and state.media_carousel
    state.set_brief_format("story_9_16")
    assert not state.carousel_allowed and state.media_carousel is False
    state.set_media_carousel(True)
    assert state.media_carousel is False
    assert state._media_inputs()["carousel"] is False


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
    state.avatar_look_id, state.voice_id = "lk", "vo"
    state.set_own_script_on(True)
    assert "Escribe tu guion" in state._kind_problem()
    state.set_own_script("  Hola, soy Doña Rosa.  ")
    state.set_avatar_engine("avatar_iii")
    state.set_avatar_engine("avatar_v")  # not an engine: ignored
    assert state._kind_problem() == ""
    media = state._media_inputs()
    assert media["own_script"] == "Hola, soy Doña Rosa." and media["engine"] == "avatar_iii"
    state.set_own_script_on(False)
    assert "own_script" not in state._media_inputs()

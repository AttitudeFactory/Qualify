"""The /create side of the generator's content kinds (§ request 2026-09-25): what the
state asks of each kind before sending, the inputs it sends, how `submit_brief` derives
the image route from them, and how a draft's media and script are shown."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from qualify_creative.enums import ContentKind, ImageRoute

from . import creative_provider
from .creative_state import CreativeState, generator_steps
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


def test_the_template_kind_is_chosen_and_reads_the_catalog_once() -> None:
    """Since the template engine landed (plan-mvp-plantillas-remotion.md, 2026-10-05)
    «Con plantilla» is a real choice: picking it chains the catalog read for the
    product picker — once, like the avatar kinds and HeyGen's catalog."""
    state = CreativeState()
    assert state.choose_kind("template") is not None  # chains load_catalog_products
    assert state.brief_kind == "template"
    state.catalog_items = [{"id": "p1", "name": "Shawarma mixto"}]
    assert state.choose_kind("template") is None
    assert state.choose_kind("creator_script") is None
    assert state.brief_kind == "creator_script"


def test_an_avatar_kind_loads_heygens_catalog_once() -> None:
    state = CreativeState()
    assert state.choose_kind("avatar_video") is not None  # chains load_heygen_catalog
    state.heygen_voices = [{"id": "vo", "name": "Elena"}]
    assert state.choose_kind("animated_avatar_video") is None


_LOOKS = [
    {"id": "lk_ana", "name": "Ana", "preview": "", "gender": "female"},
    {"id": "lk_leo", "name": "Leo", "preview": "", "gender": "male"},
]
_VOICES = [
    {"id": "vo_elena", "name": "Elena", "gender": "female"},
    {"id": "vo_jorge", "name": "Jorge", "gender": "male"},
]


def _catalog_state() -> CreativeState:
    state = CreativeState()
    state.brief_kind = "avatar_video"
    state.heygen_looks = list(_LOOKS)
    state.heygen_voices = list(_VOICES)
    state._sync_voice()
    return state


def test_the_library_is_split_by_gender_and_the_voice_follows_it() -> None:
    state = _catalog_state()
    assert [look["id"] for look in state.visible_looks] == ["lk_ana"]
    assert state.voice_id == "vo_elena"

    state.choose_look("lk_ana")
    state.set_human_avatar_mode("male")
    assert [look["id"] for look in state.visible_looks] == ["lk_leo"]
    assert state.avatar_look_id == ""  # a woman's look does not survive picking "Hombre"
    assert [voice["id"] for voice in state.visible_voices] == ["vo_jorge"]
    assert state.voice_id == "vo_jorge"


def test_a_custom_or_animated_presenter_picks_the_voice_gender_itself() -> None:
    state = _catalog_state()
    state.set_human_avatar_mode("custom")
    assert state.visible_looks == []
    state.set_voice_gender("male")
    assert state.voice_id == "vo_jorge"
    state.set_voice_gender("robot")  # not a HeyGen gender: ignored
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


def test_the_catalog_samples_both_genders_per_character() -> None:
    class _Adapter:
        def __init__(self) -> None:
            self.voice_genders: list[str | None] = []

        def list_avatar_groups(self, *, api_key: str, limit: int) -> list[dict[str, Any]]:
            return [
                {"id": "g_dante", "gender": "male"},
                {"id": "g_liza", "gender": "female"},
                {"id": "g_x", "gender": None},  # no gender: not offered
            ]

        def list_avatar_looks(
            self, *, api_key: str, limit: int, group_id: str
        ) -> list[dict[str, Any]]:
            if group_id == "g_dante":
                raise RuntimeError("boom")  # one character failing does not empty the picker
            return [
                {"id": f"{group_id}_1", "name": "Liza Office", "status": "completed"},
                {"id": f"{group_id}_2", "name": "Liza Kitchen", "status": "processing"},
            ]

        def list_voices(
            self, *, api_key: str, language: str, gender: str | None, limit: int
        ) -> list[dict[str, Any]]:
            self.voice_genders.append(gender)
            return [{"voice_id": f"v_{gender}", "name": f"Voz {gender}"}]

    adapter = _Adapter()
    looks, voices = creative_provider.build_heygen_catalog(adapter, "key")
    assert looks == [{"id": "g_liza_1", "name": "Liza Office", "preview": "", "gender": "female"}]
    assert adapter.voice_genders == ["female", "male"]
    assert [(v["id"], v["gender"]) for v in voices] == [
        ("v_female", "female"),
        ("v_male", "male"),
    ]


def test_an_ad_image_asks_for_the_photos_its_mode_names() -> None:
    state = CreativeState()
    state.brief_kind = "static_flyer"
    assert "producto" in state._kind_problem()  # default mode: product + background
    state.media_product_keys = ["uploads/t/vaso.png"]
    assert "fondo" in state._kind_problem()
    state.set_ad_mode("product")
    assert state._kind_problem() == ""
    state.set_ad_mode("background")
    assert "fondo" in state._kind_problem()
    state.set_ad_mode("anything")  # not an AdImageMode: ignored
    assert state.ad_mode == "background"


def test_an_ad_image_sends_only_its_modes_photos_and_the_scene() -> None:
    state = CreativeState()
    state.brief_kind = "static_flyer"
    state.media_background_key = "uploads/t/bar.jpg"
    state.media_product_keys = ["uploads/t/vaso.png"]
    state.media_carousel = True
    state.set_ad_scene_prompt("  una mano con el vaso  ")

    both = state._media_inputs()
    assert both["ad_mode"] == "both" and both["scene_prompt"] == "una mano con el vaso"
    assert both["background_key"] == "uploads/t/bar.jpg"
    assert both["product_keys"] == ["uploads/t/vaso.png"]

    state.set_ad_mode("background")
    background = state._media_inputs()
    assert background["product_keys"] == [] and background["carousel"] is False

    state.set_ad_mode("product")
    assert state._media_inputs()["background_key"] is None


def test_leaving_the_flyer_drops_the_carousel() -> None:
    state = CreativeState()
    state.media_carousel = True
    state.choose_kind("creator_script")
    assert state.media_carousel is False


@pytest.mark.parametrize(
    ("kind", "fields", "problem"),
    [
        ("avatar_video", {"voice_id": "vo"}, "Elige el avatar"),
        ("avatar_video", {"voice_id": "vo", "human_avatar_mode": "custom"}, "Describe"),
        ("avatar_video", {"avatar_look_id": "lk"}, "Elige la voz"),
        ("animated_avatar_video", {"voice_id": "vo", "avatar_source": "ai"}, "Describe"),
        ("animated_avatar_video", {"voice_id": "vo", "avatar_source": "image"}, "Sube la imagen"),
        (
            "animated_avatar_video",
            {"voice_id": "vo", "avatar_source": "image", "avatar_image_key": "uploads/t/a.png"},
            "Confirma",
        ),
        ("static_flyer", {"ad_mode": "product", "media_product_keys": ["uploads/t/p.png"]}, ""),
        ("static_flyer", {}, "Sube la foto de tu producto"),
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


# -- the generator as a wizard (§ request 2026-09-30) ----------------------------------


def test_only_the_avatar_kinds_ask_who_presents() -> None:
    assert generator_steps("avatar_video") == [
        "kind",
        "topic",
        "channel",
        "presenter",
        "details",
        "rules",
        "review",
    ]
    assert "presenter" in generator_steps("animated_avatar_video")
    for kind in ("creator_script", "static_flyer"):
        assert "presenter" not in generator_steps(kind)
        assert "recipe" not in generator_steps(kind)
        assert len(generator_steps(kind)) == 6


def test_only_the_template_kind_asks_how_it_is_made() -> None:
    """«¿Cómo la hacemos?» (the recipe step, plan §2.1 #4) sits right before the review
    and only for the template kind."""
    steps = generator_steps("template")
    assert steps == ["kind", "topic", "channel", "details", "rules", "recipe", "review"]
    for kind in ("creator_script", "avatar_video", "animated_avatar_video", "static_flyer"):
        assert "recipe" not in generator_steps(kind)


def test_the_counter_follows_the_kind() -> None:
    state = CreativeState()
    state.brief_kind = "creator_script"
    state.gen_step = "details"
    assert (state.gen_step_number, state.gen_step_total) == (4, 6)
    state.brief_kind = "avatar_video"
    assert (state.gen_step_number, state.gen_step_total) == (5, 7)


def test_continuar_walks_the_kinds_steps_and_atras_walks_back() -> None:
    state = CreativeState()
    state.brief_kind = "creator_script"
    state.brief_topic = "Smash doble"
    seen = [state.gen_step]
    for _ in range(10):
        state.gen_next()
        seen.append(state.gen_step)
    assert seen[:6] == generator_steps("creator_script")
    assert set(seen[6:]) == {"review"}  # the last step stays put: Generar takes over
    state.gen_back()
    assert state.gen_step == "rules"
    for _ in range(10):
        state.gen_back()
    assert state.gen_step == "kind"


def test_a_step_does_not_move_on_until_it_is_complete() -> None:
    state = CreativeState()
    state.brief_kind = "avatar_video"
    state.gen_step = "topic"
    state.gen_next()
    assert state.gen_step == "topic" and state.create_error != ""
    state.brief_topic = "Smash doble"
    state.gen_next()
    assert state.gen_step == "channel" and state.create_error == ""
    state.gen_next()
    assert state.gen_step == "presenter"
    state.gen_next()
    assert state.gen_step == "presenter" and "Elige el avatar" in state.create_error
    state.avatar_look_id = "lk"
    state.voice_id = "vo"
    state.gen_next()
    assert state.gen_step == "details"
    state.own_script_on = True
    state.gen_next()
    assert state.gen_step == "details" and "Escribe tu guion" in state.create_error
    state.gen_back()
    assert state.gen_step == "presenter" and state.create_error == ""


def test_no_kind_asks_for_objetivo_or_destino() -> None:
    """§ request 2026-10-05 ("quitar objetivo y destino en todas las opciones"): every
    kind shares the topic and channel steps, and neither asks any more; the brief still
    carries both fields at their defaults."""
    from .content_generator import _step_channel, _step_topic

    for step in (_step_topic(), _step_channel()):
        rendered = str(step)
        assert '"Objetivo"' not in rendered and '"Destino"' not in rendered
    state = CreativeState()
    assert (state.brief_objective, state.brief_intent) == ("consideration", "organic")


def test_the_review_recaps_the_brief() -> None:
    state = CreativeState()
    state.brief_kind = "static_flyer"
    state.brief_topic = "  Smash doble  "
    state.brief_objective = "sale"
    state.brief_intent = "ads"
    state.brief_must_mention = "envío gratis"
    recap = dict(state.gen_recap)
    assert recap["Tipo de pieza"] == {key: title for key, title, *_ in KIND_OPTIONS}["static_flyer"]
    assert recap["Tema o producto"] == "Smash doble"
    # § 2026-10-05: Objetivo and Destino are no longer asked nor recapped
    assert "Objetivo" not in recap and "Destino" not in recap
    assert recap["Formato"] != ""
    assert recap["Debe mencionar"] == "envío gratis"
    assert recap["Debe evitar"] == ""


def test_crear_otro_starts_the_wizard_again() -> None:
    state = CreativeState()
    state.gen_step = "review"
    state.generator_view = "result"
    state.new_generation()
    assert state.gen_step == "kind"


# -- the template kind (plan-mvp-plantillas-remotion.md, 2026-10-05) ---------------------


def _recipe(key: str, **kw: Any):
    from .creative_vm import RecipeOptionVM

    base: dict[str, Any] = {
        "key": key,
        "engine_label": key.title(),
        "engine_tone": "accent",
        "label": "Promo de producto",
        "template_id": "promo_producto" if key == "remotion" else "",
        "template_version": 1 if key == "remotion" else 0,
        "cost_label": "USD 0.00",
        "eta_label": "~38 s",
        "outputs_label": "Reel · Feed · Historia",
        "suggested": False,
        "available": True,
        "reason": "",
        "selectable": key != "ugc",
        "rule": 0,
    }
    base.update(kw)
    return RecipeOptionVM(**base)


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
    assert "template_id" not in media  # no recipe pinned yet
    # a typed topic is never overwritten; picking the same product again unpicks it
    state.brief_topic = "Promo de martes"
    state.choose_product("p1")
    assert state.selected_product_id == "" and state.brief_product_ref == ""
    assert state.brief_topic == "Promo de martes"
    assert state.template_photo_count == 2  # only the piece's own uploads remain


def test_a_template_without_any_photo_cannot_leave_the_details_step() -> None:
    state = CreativeState()
    state.brief_kind = "template"
    state.brief_topic = "Promo"
    state.gen_step = "details"
    assert state.gen_next() is None
    assert state.gen_step == "details"
    assert "foto" in state.create_error.lower()
    state.media_product_keys = ["uploads/t/a.jpg"]
    state.gen_next()
    assert state.gen_step == "rules"
    # Continuar out of the rules step lands on the recipes and quotes them
    assert state.gen_next() is not None  # chains load_recipe_options
    assert state.gen_step == "recipe"


def test_choosing_a_remotion_recipe_pins_the_template_on_the_brief() -> None:
    state = CreativeState()
    state.brief_kind = "template"
    state.media_product_keys = ["uploads/t/a.jpg", "uploads/t/b.jpg"]
    state.recipe_items = [
        _recipe("remotion", suggested=True, rule=2),
        _recipe("heygen", available=False, selectable=False, reason="sin avatar"),
        _recipe("ugc", reason="solo cotiza"),
    ]
    state.gen_step = "recipe"
    # nothing picked yet: Continuar refuses
    assert state.gen_next() is None and state.gen_step == "recipe"
    assert state.create_error != ""

    assert state.choose_recipe("remotion") is None
    assert state.selected_recipe == "remotion"
    assert (state.media_template_id, state.media_template_version) == ("promo_producto", 1)
    media = state._media_inputs()
    assert (media["template_id"], media["template_version"]) == ("promo_producto", 1)
    assert state.selected_recipe_label == "Promo de producto · Remotion"
    assert state.selected_recipe_cost == "USD 0.00 · ~38 s"
    assert ["Receta", "Promo de producto · Remotion"] in state.gen_recap
    assert ["Costo estimado", "USD 0.00 · ~38 s"] in state.gen_recap

    state.gen_next()
    assert state.gen_step == "review"


def test_ugc_only_quotes_and_an_unavailable_recipe_says_why() -> None:
    state = CreativeState()
    state.brief_kind = "template"
    state.recipe_items = [
        _recipe("remotion", available=False, selectable=False, reason="necesita 2 fotos"),
        _recipe("heygen", available=False, selectable=False, reason="sin avatar"),
        _recipe("ugc", reason="solo cotiza"),
    ]
    assert state.choose_recipe("ugc") is None
    assert state.selected_recipe == "" and "cotiza" in state.recipe_notice
    assert state.choose_recipe("remotion") is None
    assert state.selected_recipe == "" and "necesita 2 fotos" in state.recipe_notice


def test_choosing_heygen_turns_the_piece_into_an_avatar_video() -> None:
    state = CreativeState()
    state.brief_kind = "template"
    state.gen_step = "recipe"
    state.recipe_items = [
        _recipe("remotion"),
        _recipe("heygen", engine_tone="info", label="Avatar hablando a cámara"),
        _recipe("ugc"),
    ]
    assert state.choose_recipe("heygen") is not None  # chains load_heygen_catalog
    assert state.brief_kind == "avatar_video"
    assert state.gen_step == "presenter"
    assert "avatar" in state.recipe_notice.lower()
    assert state.media_template_id == "" and state.recipe_items == []
    assert "recipe" not in generator_steps(state.brief_kind)

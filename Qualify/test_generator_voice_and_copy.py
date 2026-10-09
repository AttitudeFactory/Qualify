"""The generator's three asks of 2026-10-06: a flag when the Brand Kit's Tu voz y tono is
still to configure (and the way there), the copy prompt printed to the console on
«¿Todo listo?» before Generar, and "Copiar guion" taking the shots too."""

from __future__ import annotations

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
    assert r"Descripci\u00f3n del post" in rendered and "description" in rendered  # JS-escaped
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
    assert "Configurar voz" in flag and "voz y tono" in flag
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
    assert "gen_is_done" in rendered and "Disponible cuando termine de generarse" in rendered


def test_the_picker_offers_its_categories_with_the_ad_image_back() -> None:
    """Imagen publicitaria left on 2026-10-06 and came back on 2026-10-07, generated by
    Seedream ("crea de nuevo la generación de imágenes publicitarias"); Carrusel joined
    on 2026-10-09."""
    from .content_generator import _kind_picker
    from .creative_vm import CATEGORY_OPTIONS, KIND_LABELS, VIDEO_TYPE_OPTIONS

    assert [key for key, *_ in CATEGORY_OPTIONS] == [
        "script",
        "video",
        "image",
        "template",
        "carousel",
    ]
    assert [key for key, *_ in VIDEO_TYPE_OPTIONS] == [
        "avatar_video",
        "animated_avatar_video",
        "ad_video",
    ]
    rendered = str(_kind_picker())
    assert "Imagen publicitaria" in rendered and "Video publicitario" in rendered
    assert KIND_LABELS["static_flyer"] == "Imagen publicitaria"
    state = CreativeState()
    assert (state.gen_category, state.brief_kind) == ("script", "creator_script")
    state.choose_category("image")
    assert (state.gen_category, state.brief_kind) == ("image", "static_flyer")
    assert state.gen_kind_label == "Imagen publicitaria"
    # § 2026-10-08: no «¿Qué quieres en la imagen?» — the scene, in its details, is it
    assert generator_sections(state.brief_kind) == ["channel", "details"]


def test_video_opens_on_its_first_type_and_each_type_is_its_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUALIFY_VIDEO_ENGINE", "heygen")
    state = CreativeState()
    assert state.choose_category("video") is not None  # an avatar loads HeyGen's catalog
    assert (state.brief_kind, state.video_type) == ("avatar_video", "avatar_video")
    state.heygen_voices = [{"id": "vo", "name": "Elena"}]
    state.choose_video_type("animated_avatar_video")
    assert state.brief_kind == "animated_avatar_video"
    state.choose_video_type("ad_video")  # the template's Reel
    assert (state.brief_kind, state.video_type) == ("template", "ad_video")
    assert state.gen_kind_label == "Video publicitario"
    assert [value for value, _ in state.format_options] == ["reels_9_16"]
    # choosing Video again keeps the type already picked
    state.choose_category("video")
    assert state.video_type == "ad_video"


def test_con_plantilla_is_one_image_for_the_feed_or_the_story() -> None:
    state = CreativeState()
    state.choose_category("template")
    assert (state.brief_kind, state.video_type) == ("template", "")
    assert state.gen_kind_label == "Con plantilla"
    assert [value for value, _ in state.format_options] == ["feed_4_5", "story_9_16"]
    assert state.effective_format == "feed_4_5"
    state.choose_category("script")
    assert (state.gen_category, state.brief_kind) == ("script", "creator_script")


def test_a_template_reel_draft_is_named_video_publicitario() -> None:
    from .creative_vm import MediaVM, build_draft_vm

    def draft(media: tuple[MediaVM, ...]) -> str:
        return build_draft_vm(
            draft_id="d",
            status="generated",
            failure_reason=None,
            variants=(),
            image_url=None,
            total_cost_usd=None,
            voice_profile_version=None,
            model_ids=(),
            requires_ai_disclosure=False,
            created_label="",
            kind="template",
            media=media,
        ).kind_label

    reel = MediaVM(key="k/reel.mp4", media_type="video", position=0, label="Reel 9:16")
    feed = MediaVM(key="k/feed.jpg", media_type="image", position=0, label="Feed 4:5")
    assert draft((reel,)) == "Video publicitario"
    assert draft((feed,)) == "Con plantilla"


def test_the_topic_is_asked_as_a_general_context() -> None:
    from .content_generator import _section_topic

    rendered = str(_section_topic())
    assert "Tema o producto" not in rendered
    assert "quieres en el video?" in rendered and "Un contexto general" in rendered


def _remotion_option(**kw: Any):
    from .creative_vm import RecipeOptionVM

    base: dict[str, Any] = {
        "key": "remotion",
        "engine_label": "Remotion",
        "engine_tone": "accent",
        "label": "Promo de producto",
        "template_id": "promo_producto",
        "template_version": 1,
        "cost_label": "USD 0.00",
        "eta_label": "",
        "outputs_label": "",
        "suggested": True,
        "available": True,
        "reason": "",
        "selectable": True,
        "rule": 2,
    }
    base.update(kw)
    return RecipeOptionVM(**base)


@pytest.mark.parametrize(
    ("option", "fmt", "problem"),
    [
        ({}, "feed_4_5", ""),
        ({}, "reels_9_16", ""),
        (
            {"available": False, "reason": "la plantilla «Promo de producto» necesita 2 fotos"},
            "feed_4_5",
            "necesita 2 fotos",
        ),
    ],
)
def test_review_says_why_a_template_cannot_be_made(
    monkeypatch: pytest.MonkeyPatch, option: dict[str, Any], fmt: str, problem: str
) -> None:
    """«¿Cómo la hacemos?» used to say it; since it left, «¿Todo listo?» does — with the
    real published template (`promo_producto`, which renders reel, feed and story)."""
    monkeypatch.setattr(
        creative_provider, "recipe_options", lambda *_a, **_k: (_remotion_option(**option),)
    )
    found = creative_provider.template_blocker(
        _TENANT_ID,
        _BRAND_ID,
        content_type="product",
        product_ref="",
        product_keys=["uploads/t/a.jpg"],
        source_media_key="",
        content_format=fmt,
    )
    assert (problem in found) if problem else found == ""


def test_generar_checks_the_template_before_creating_anything() -> None:
    """§ 2026-10-08: the template check moved from «¿Todo listo?» into Generar, before
    the draft exists — with what the piece really has."""
    import inspect

    state = CreativeState()
    state.choose_category("template")
    state.brief_topic = "Promo"
    state.media_product_keys = ["uploads/t/a.jpg"]
    form = state._template_form()
    assert form["product_keys"] == ["uploads/t/a.jpg"]
    assert form["content_format"] == state.effective_format
    source = inspect.getsource(CreativeState.submit_generator_form.fn)
    assert source.index("_template_blocker") < source.index("_create_draft(form)")


def test_a_template_still_is_published_as_what_it_is() -> None:
    from qualify_creative.enums import ContentFormat, ContentKind, PostCategory, default_category

    assert default_category(ContentKind.TEMPLATE, ContentFormat.FEED_4_5) is PostCategory.GALERIA
    assert default_category(ContentKind.TEMPLATE, ContentFormat.STORY_9_16) is PostCategory.STORY
    assert default_category(ContentKind.TEMPLATE, ContentFormat.REELS_9_16) is PostCategory.REEL


# --------------------------------------------------------------------------------------
# «Del Brand Kit»: the images already saved there, used as the piece's media
# --------------------------------------------------------------------------------------


def test_the_brand_kits_images_are_offered_but_never_its_fonts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.creative import brand_kit_store as store_module
    from qualify_api.creative.brand_kit_store import BrandAsset

    prefix = f"t/{_TENANT_ID}/brand/{_BRAND_ID}"
    assets = [
        BrandAsset(kind="logo", slot="", object_key=f"{prefix}/logo.png", content_type="image/png"),
        BrandAsset(kind="logo_version", slot="isologo", object_key=f"{prefix}/iso.jpg"),
        BrandAsset(
            kind="extra",
            slot="1",
            object_key=f"{prefix}/bolsa.webp",
            label="Bolsa",
            context="En  la bolsa de delivery,\n siempre visible",
        ),
        BrandAsset(kind="extra", slot="2", object_key=f"{prefix}/manual.pdf", label="Manual"),
        BrandAsset(kind="font", slot="heading", object_key=f"{prefix}/f.woff2"),
    ]
    monkeypatch.setattr(
        store_module, "BrandKitStore", lambda: SimpleNamespace(list_assets=lambda **_: assets)
    )
    monkeypatch.setattr(creative_provider, "issue_view_path", lambda *_a, **_k: "/r2media/tok")
    rows = creative_provider.brand_media(_TENANT_ID, _BRAND_ID)
    assert [(r["label"], r["key"].rsplit("/", 1)[-1]) for r in rows] == [
        ("Logo", "logo.png"),
        ("Isologo", "iso.jpg"),
        ("Bolsa", "bolsa.webp"),
    ]
    assert {r["view"] for r in rows} == {"/r2media/tok"}
    assert [r["kind"] for r in rows] == ["logo", "logo", "element"]
    assert rows[2]["usage"] == "En la bolsa de delivery, siempre visible"


def _state_with_brand_media() -> CreativeState:
    state = CreativeState()
    prefix = f"t/{_TENANT_ID}/brand"
    state.brand_media_items = [
        {"key": f"{prefix}/logo.png", "label": "Logo", "view": "/r2media/a", "kind": "logo"},
        {"key": f"{prefix}/iso.png", "label": "Isologo", "view": "/r2media/i", "kind": "logo"},
        {
            "key": f"{prefix}/bolsa.png",
            "label": "Bolsa",
            "view": "/r2media/b",
            "kind": "element",
            "usage": "En la bolsa de delivery",
        },
    ]
    return state


def test_brand_resources_are_a_section_of_their_own() -> None:
    """§ 2026-10-06: apart from the background and the products — one logo for the brand
    mark's place, and the elements, each used as its usage note says."""
    state = _state_with_brand_media()
    logo, iso, bag = (item["key"] for item in state.brand_media_items)
    state.toggle_brand_logo(logo)
    state.toggle_brand_logo(iso)  # one logo: another one replaces it
    state.toggle_brand_element(bag)
    assert (state.brand_logo_key, state.brand_element_keys) == (iso, [bag])
    # never mixed with the background or the products
    assert state.media_product_keys == [] and state.media_background_key == ""
    # a logo is not an element, and an element is not a logo
    state.toggle_brand_element(logo)
    state.toggle_brand_logo(bag)
    assert (state.brand_logo_key, state.brand_element_keys) == (iso, [bag])
    assert [c["chosen"] for c in state.brand_logo_choices] == ["", "1"]
    assert [c["chosen"] for c in state.brand_element_choices] == ["1"]
    state.brief_kind = "avatar_video"
    media = state._media_inputs()
    assert (media["brand_logo_key"], media["brand_element_keys"]) == (iso, [bag])
    # a second click takes each one out again
    state.toggle_brand_logo(iso)
    state.toggle_brand_element(bag)
    assert state._media_inputs()["brand_logo_key"] is None
    assert state._media_inputs()["brand_element_keys"] == []


def test_a_brand_image_can_still_be_the_animated_character() -> None:
    state = _state_with_brand_media()
    logo = state.brand_media_items[0]["key"]
    state.use_brand_avatar_image(logo)
    assert (state.avatar_image_key, state.avatar_image_name) == (logo, "Logo")
    assert state.brand_media_choices[0]["avatar"] == "1"
    state.use_brand_avatar_image(logo)
    assert state.avatar_image_key == ""


def test_only_a_key_the_brand_kit_listed_is_accepted() -> None:
    state = _state_with_brand_media()
    foreign = "t/00000000-0000-4000-8000-000000000999/brand/secret.png"
    state.toggle_brand_logo(foreign)
    state.toggle_brand_element(foreign)
    state.use_brand_avatar_image(foreign)
    assert state.brand_logo_key == "" and state.brand_element_keys == []
    assert state.avatar_image_key == ""


def test_the_resources_are_their_own_section_not_the_uploads() -> None:
    from .content_generator import (
        _avatar_section,
        _brand_resources,
        _images_section,
        _section_details,
        _template_details,
    )

    for section in (_images_section(), _template_details()):
        assert "brand_media_choices" not in str(section)  # not mixed into the uploads
    resources = str(_brand_resources())
    assert "Recursos de tu marca" in resources and "brand_logo_choices" in resources
    assert "brand_element_choices" in resources and "toggle_brand_element" in resources
    assert "Recursos de tu marca" in str(_section_details())
    assert "use_brand_avatar_image" in str(_avatar_section())


def _kit(**overrides: Any) -> Any:
    from qualify_creative.schemas import BrandKit, ToneAxes

    return BrandKit(
        brand_id=_BRAND_ID,
        positioning="p",
        audience="a",
        tone_axes=ToneAxes(
            formal_casual=50, sober_enthusiastic=50, technical_plain=50, brief_elaborate=50
        ),
        **overrides,
    )


def _voice() -> Any:
    from qualify_creative.enums import VoiceProfileStatus
    from qualify_creative.schemas import BrandVoiceProfile, ToneAxes

    return BrandVoiceProfile(
        brand_id=_BRAND_ID,
        version=1,
        status=VoiceProfileStatus.ACTIVE,
        tone_axes=ToneAxes(
            formal_casual=50, sober_enthusiastic=50, technical_plain=50, brief_elaborate=50
        ),
    )


def test_the_copy_is_told_the_chosen_resources_and_their_use() -> None:
    from qualify_creative.brand.render import render_prompt
    from qualify_creative.enums import BriefObjective, ContentKind, GenerationTask, ImageRoute
    from qualify_creative.schemas import BrandContext, BrandElement, ContentBrief, MediaInputs

    context = BrandContext(
        elements=(
            BrandElement(name="Isologo", context="Sobre fondo oscuro", key="t/x/iso", kind="logo"),
            BrandElement(name="Bolsa", context="En la bolsa de delivery", key="t/x/bolsa"),
            BrandElement(name="Patrón", key="t/x/patron"),
        )
    )
    brief = ContentBrief(
        brand_id=_BRAND_ID,
        objective=BriefObjective.AWARENESS,
        topic="La triple",
        image_route=ImageRoute.TEMPLATE_ONLY,
        kind=ContentKind.AVATAR_VIDEO,
        media=MediaInputs(
            avatar_look_id="lk",
            voice_id="vo",
            brand_logo_key="t/x/iso",
            brand_element_keys=("t/x/bolsa", "t/x/patron", "t/x/borrado"),
        ),
    )
    rendered = render_prompt(
        kit=_kit(logo_asset_key="t/x/iso"),
        voice=_voice(),
        brief=brief,
        task=GenerationTask.COPY,
        context=context,
    )
    suffix = rendered.volatile_suffix
    assert "Brand resources chosen for this piece" in suffix
    assert "- Logo «Isologo»: it is shown in a corner of the video, behind the presenter." in suffix
    assert "Usage note: Sobre fondo oscuro." in suffix
    assert "- «Bolsa» — En la bolsa de delivery" in suffix
    assert "- «Patrón» — no usage note" in suffix
    assert "borrado" not in suffix  # a key the Brand Kit no longer has is skipped
    # and the cached prefix names no storage key any more
    assert "Logo: on file" in rendered.stable_prefix
    assert "t/x/iso" not in rendered.stable_prefix

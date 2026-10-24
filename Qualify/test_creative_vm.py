"""Pure tests for the creative view-model builders (design §6) — no Reflex, no DB.

Import only `creative_vm` (stdlib + `qualify_creative`), so this runs with a plain
interpreter, same convention as `test_clarity_vm.py`.

Pins:
1. Every `DraftStatus` has a label and a reserved-tone badge color.
2. The image accordion comes back in `ImageRoute.rank` order — GENERATE last.
3. A policy-blocked route stays VISIBLE, disabled, with `ImagePolicy.reason_for`'s text.
4. GENERATE carries the §6.4 "NO RECOMENDADA" badge and the ⚠ warning; nothing else
   does — and a sellable content type disables it even when policy would allow it.
5. Cost label formatting: cents, sub-cent honesty, free, and the provenance parts.
6. Every `FailureReason` maps to a Spanish label plus a CONCRETE action.
7. Readiness gaps link to the screen that fixes them (all under /brand post voice-merge).
8. Variant projection: edited copy wins, fidelity failures surface as labels.
"""

from __future__ import annotations

from decimal import Decimal

from qualify_creative.enums import ContentType, DraftStatus, FailureReason, ImageRoute
from qualify_creative.schemas import ImagePolicy

from .creative_vm import (
    GENERATE_WARNING,
    STATUS_LABELS,
    STATUS_TONES,
    build_draft_summary_vm,
    build_draft_vm,
    build_readiness_vm,
    build_route_options,
    build_variant_vm,
    build_voice_proposal_vm,
    failure_vm,
    format_cost_label,
    status_label,
    status_tone,
)

_ALL_ROUTES_POLICY = ImagePolicy(allowed_routes=frozenset(ImageRoute))


# ---------------------------------------------------------------------------
# 1. Status labels / tones


def test_every_draft_status_has_label_and_tone() -> None:
    for status in DraftStatus:
        assert status.value in STATUS_LABELS, status
        assert status.value in STATUS_TONES, status
        assert STATUS_LABELS[status.value]  # non-empty Spanish label
        assert STATUS_TONES[status.value]


def test_status_tone_families() -> None:
    assert status_tone("failed") == "tomato"
    assert status_tone("published") == "grass"
    assert status_tone("drafting") == "blue"
    # Unknown status degrades to a neutral badge, not a crash.
    assert status_tone("something_new") == "gray"
    assert status_label("something_new") == "something_new"


def test_summary_vm_carries_status_display_and_failure_label() -> None:
    vm = build_draft_summary_vm(
        draft_id="d-1",
        topic="Combo de la semana",
        status="failed",
        created_label="17 ago 2026, 10:00",
        failure_reason="timeout",
    )
    assert vm.status_label == STATUS_LABELS["failed"]
    assert vm.status_tone == "tomato"
    assert "5 minutos" not in vm.failure_label  # translated failure, not the poll copy
    assert vm.failure_label  # non-empty for FAILED

    ok = build_draft_summary_vm(
        draft_id="d-2",
        topic="",
        status="generated",
        created_label="",
        failure_reason=None,
    )
    assert ok.failure_label == ""


# ---------------------------------------------------------------------------
# 2-4. The image accordion


def test_accordion_order_matches_image_route_rank() -> None:
    options = build_route_options(
        policy=_ALL_ROUTES_POLICY, content_type=ContentType.HOURS_LOCATION
    )
    assert [opt.key for opt in options] == [
        route.value for route in sorted(ImageRoute, key=lambda r: r.rank)
    ]
    assert [opt.rank for opt in options] == sorted(opt.rank for opt in options)
    assert options[-1].key == ImageRoute.GENERATE.value  # GENERATE is last


def test_blocked_route_stays_visible_with_policy_reason() -> None:
    reason = "Marca de comida: el producto no se inventa."
    policy = ImagePolicy(
        allowed_routes=frozenset({ImageRoute.TEMPLATE_ONLY, ImageRoute.FROM_UPLOAD}),
        blocked_reason={ImageRoute.GENERATE: reason},
    )
    options = {
        opt.key: opt
        for opt in build_route_options(policy=policy, content_type=ContentType.HOURS_LOCATION)
    }
    generate = options[ImageRoute.GENERATE.value]
    assert not generate.enabled
    assert generate.disabled_reason == reason  # ImagePolicy.reason_for's text, verbatim
    # A blocked route without a configured reason still explains itself.
    enhance = options[ImageRoute.RESTYLE_ENHANCE.value]
    assert not enhance.enabled
    assert enhance.disabled_reason == ImagePolicy().reason_for(ImageRoute.RESTYLE_ENHANCE)
    # And the allowed ones are enabled with no reason.
    assert options[ImageRoute.FROM_UPLOAD.value].enabled
    assert options[ImageRoute.FROM_UPLOAD.value].disabled_reason == ""


def test_generate_carries_warning_and_no_recomendada_badge() -> None:
    options = {
        opt.key: opt
        for opt in build_route_options(
            policy=_ALL_ROUTES_POLICY, content_type=ContentType.HOURS_LOCATION
        )
    }
    generate = options[ImageRoute.GENERATE.value]
    assert generate.badge == "NO RECOMENDADA"
    assert generate.warning == GENERATE_WARNING
    assert "NO será" not in generate.description  # warning lives in `warning`, once
    for key, opt in options.items():
        if key != ImageRoute.GENERATE.value:
            assert opt.warning == ""


def test_generate_disabled_for_sellable_content_type_even_when_policy_allows() -> None:
    options = {
        opt.key: opt
        for opt in build_route_options(policy=_ALL_ROUTES_POLICY, content_type=ContentType.PRODUCT)
    }
    generate = options[ImageRoute.GENERATE.value]
    assert not generate.enabled
    assert generate.disabled_reason != ""


def test_recommended_badge_follows_content_type_default_route() -> None:
    for content_type in (ContentType.PRODUCT, ContentType.HOURS_LOCATION):
        options = {
            opt.key: opt
            for opt in build_route_options(policy=_ALL_ROUTES_POLICY, content_type=content_type)
        }
        default = content_type.default_image_route.value
        assert options[default].badge == "RECOMENDADO"
    # Disclosure fact travels on the option, shown BEFORE choosing.
    options = {
        opt.key: opt
        for opt in build_route_options(
            policy=_ALL_ROUTES_POLICY, content_type=ContentType.HOURS_LOCATION
        )
    }
    assert options[ImageRoute.RESTYLE_SCENE.value].badge == "requiere etiqueta"
    assert options[ImageRoute.RESTYLE_SCENE.value].requires_disclosure
    assert not options[ImageRoute.RESTYLE_ENHANCE.value].requires_disclosure


# ---------------------------------------------------------------------------
# 5. Cost label


def test_cost_label_formats_cents_with_provenance() -> None:
    label = format_cost_label(Decimal("0.04"), 1, ["claude-opus-5"])
    assert label == "$0.04 · Perfil v1 · claude-opus-5"


def test_cost_label_subcent_is_not_rounded_to_free() -> None:
    label = format_cost_label(Decimal("0.004"), 2, [])
    assert label.startswith("$0.004")
    assert "$0.00 " not in label


def test_cost_label_free_and_deduplicated_models() -> None:
    assert format_cost_label(Decimal("0"), None, []) == "Gratis"
    assert format_cost_label(None, 3, []) == "Gratis · Perfil v3"
    label = format_cost_label(Decimal("0.10"), 1, ["m-a", "m-a", "m-b"])
    assert label.endswith("m-a + m-b")


# ---------------------------------------------------------------------------
# 6. Failure reason -> concrete action


def test_every_failure_reason_maps_to_action() -> None:
    for reason in FailureReason:
        vm = failure_vm(reason.value)
        assert vm is not None
        assert vm.label and not vm.label.startswith("Falló la generación (")  # translated
        assert vm.action_label  # a CONCRETE action, never empty


def test_failure_vm_none_and_unknown() -> None:
    assert failure_vm(None) is None
    assert failure_vm("") is None
    unknown = failure_vm("brand_new_reason")
    assert unknown is not None  # degrades to visible, never hides the failure
    assert "brand_new_reason" in unknown.label


def test_specific_failure_actions() -> None:
    assert "límite" in failure_vm("budget_exceeded").label
    assert "$" not in failure_vm("budget_exceeded").label
    assert failure_vm("credential_invalid").action_label.startswith("Renueva")
    assert failure_vm("timeout").action_route == "/create"


# ---------------------------------------------------------------------------
# 7. Readiness gaps link to their fix


def test_readiness_gaps_link_to_fix_screens() -> None:
    vm = build_readiness_vm(
        has_kit=True,
        kit_completeness=0.65,
        has_active_voice=False,
        can_distill=True,
        can_generate=False,
        missing=("dont_examples", "active_voice_profile"),
    )
    assert vm.completeness_pct == 65
    routes = {gap.key: gap.fix_route for gap in vm.gaps}
    assert routes["dont_examples"] == "/brand/kit"
    assert routes["active_voice_profile"] == "/brand/kit"
    assert {gap.fix_label for gap in vm.gaps} == {"Completar mi marca"}
    for gap in vm.gaps:
        assert gap.label and gap.fix_label


# ---------------------------------------------------------------------------
# 8. Variants and the draft VM


_COPY = {
    "hook": "¿Tu próxima casa ya te espera?",
    "caption": "Un apartamento con vista al parque.",
    "hashtags": ["LaRiviera", "vivienda"],
    "cta": "Agenda tu visita",
}


def test_variant_vm_shows_model_copy_with_fidelity_failures() -> None:
    vm = build_variant_vm(
        variant_id="v-1",
        ordinal=0,
        copy=_COPY,
        edited_copy=None,
        fidelity={
            "passed": False,
            "hard_failures": [{"rule": "forbidden_claim", "detail": "«el mejor precio»"}],
        },
    )
    assert vm.label == "Variante 1"
    assert not vm.passed
    # A detail that is not in the engine's own shape still shows, labelled — never lost.
    assert vm.failure_labels == ("Regla de marca (forbidden_claim): «el mejor precio»",)
    assert vm.hashtags_text == "#LaRiviera #vivienda"
    assert not vm.was_edited
    assert "Agenda tu visita" in vm.rendered_caption


def test_variant_vm_edited_copy_wins_and_passes() -> None:
    edited = dict(_COPY, caption="Caption corregida por el humano.")
    vm = build_variant_vm(
        variant_id="v-2",
        ordinal=1,
        copy=_COPY,
        edited_copy=edited,
        fidelity={"passed": False, "hard_failures": [{"rule": "x", "detail": "y"}]},
    )
    # The service only stores edits that PASSED layer 1, so the edit shows as passing.
    assert vm.was_edited
    assert vm.passed
    assert vm.failure_labels == ()
    assert vm.caption == "Caption corregida por el humano."


def _variant(variant_id: str, ordinal: int, passed: bool) -> object:
    return build_variant_vm(
        variant_id=variant_id,
        ordinal=ordinal,
        copy=_COPY,
        edited_copy=None,
        fidelity={"passed": passed, "hard_failures": []},
    )


def test_draft_vm_generated_is_approvable_with_fidelity_summary() -> None:
    vm = build_draft_vm(
        draft_id="d-1",
        status="generated",
        failure_reason=None,
        variants=[_variant("v-1", 0, True), _variant("v-2", 1, False)],
        image_url=None,
        total_cost_usd=Decimal("0.04"),
        voice_profile_version=1,
        model_ids=["claude-opus-5"],
        requires_ai_disclosure=False,
        created_label="hoy",
    )
    assert vm.can_approve
    assert vm.blocking_reason is None
    assert vm.fidelity_summary == "1 de 2 textos cumplen las reglas de tu marca"
    assert vm.cost_label == "$0.04 · Perfil v1 · claude-opus-5"
    assert vm.cost_short == "$0.04"  # the pill; the provenance is its hover
    assert not vm.is_drafting and not vm.is_failed


def test_draft_vm_failed_carries_translated_failure_and_never_approves() -> None:
    vm = build_draft_vm(
        draft_id="d-2",
        status="failed",
        failure_reason="refusal",
        variants=[],
        image_url=None,
        total_cost_usd=None,
        voice_profile_version=None,
        model_ids=[],
        requires_ai_disclosure=False,
        created_label="",
    )
    assert vm.is_failed
    assert not vm.can_approve
    assert vm.failure is not None
    assert vm.failure.reason == "refusal"
    assert vm.status_tone == "tomato"


def test_draft_vm_drafting_flags_poll_state() -> None:
    vm = build_draft_vm(
        draft_id="d-3",
        status="drafting",
        failure_reason=None,
        variants=[],
        image_url=None,
        total_cost_usd=None,
        voice_profile_version=1,
        model_ids=[],
        requires_ai_disclosure=False,
        created_label="",
    )
    assert vm.is_drafting
    assert not vm.can_approve


# ---------------------------------------------------------------------------
# Voice proposal projection (HITL #0 evidence)


def test_voice_proposal_marks_differing_axes_and_labels_sources() -> None:
    vm = build_voice_proposal_vm(
        version=1,
        status="proposed",
        tone_axes={
            "formal_casual": 72,
            "sober_enthusiastic": 58,
            "technical_plain": 40,
            "brief_elaborate": 50,
        },
        kit_tone_axes={
            "formal_casual": 65,
            "sober_enthusiastic": 58,
            "technical_plain": 40,
            "brief_elaborate": 50,
        },
        lexicon=["acompañamos", "a tu medida"],
        avoid_lexicon=["barato"],
        signature_moves=["Abre con pregunta directa"],
        sources=[{"kind": "manual_kit", "ref": "brand_kit", "excerpt": "Te acompañamos…"}],
    )
    assert vm.can_approve
    rows = {row.axis: row for row in vm.tone_rows}
    assert rows["formal_casual"].differs
    assert not rows["sober_enthusiastic"].differs
    assert rows["formal_casual"].label == "formal ↔ coloquial"
    assert vm.sources[0].kind_label == "tu marca"
    # An ACTIVE profile is not re-approvable.
    active = build_voice_proposal_vm(
        version=1,
        status="active",
        tone_axes={},
        kit_tone_axes=None,
        lexicon=[],
        avoid_lexicon=[],
        signature_moves=[],
        sources=[],
    )
    assert not active.can_approve


def _vm_for(status: str):
    return build_draft_vm(
        draft_id="d1",
        status=status,
        failure_reason=None,
        variants=(),
        image_url=None,
        total_cost_usd=None,
        voice_profile_version=None,
        model_ids=(),
        requires_ai_disclosure=False,
        created_label="",
    )


def test_review_buttons_follow_the_fsm() -> None:
    generated, rejected, approved = _vm_for("generated"), _vm_for("rejected"), _vm_for("approved")
    assert generated.can_reject and generated.can_regenerate
    assert not rejected.can_reject and rejected.can_regenerate  # regenerate is still legal
    assert not approved.can_reject and not approved.can_regenerate  # Piezas, not here


# --- brand-rule failures in the operator's words (request 2026-09-30) -------------------


def test_brand_rule_failures_read_in_spanish_with_what_to_do() -> None:
    from qualify_creative.brand import fidelity
    from qualify_creative.enums import EmojiPolicy
    from qualify_creative.schemas import BrandKit, CopyPayload, ToneAxes

    from .creative_vm import failure_label

    kit = BrandKit.model_validate(
        {
            "brand_id": "b0000000-0000-4000-8000-000000000001",
            "positioning": "x",
            "audience": "y",
            "tone_axes": ToneAxes(
                formal_casual=50, sober_enthusiastic=50, technical_plain=50, brief_elaborate=50
            ),
            "banned_words": ("gratis",),
            "emoji_policy": EmojiPolicy.NONE,
        }
    )
    copy = CopyPayload.model_validate(
        {"hook": "Hola", "caption": "es gratis 🎉", "hashtags": [], "cta": ""}
    )
    labels = [failure_label(f.rule, f.detail) for f in fidelity.check_hard_rules(copy, kit)]
    assert "El texto usa «gratis», una palabra que tu marca tiene prohibida." in labels
    assert any(
        label.startswith("El texto de la publicación tiene 11 caracteres y tu marca pide")
        for label in labels
    )
    assert "Tu marca no usa emojis y el texto tiene 1." in labels
    assert not any("caption_length" in label or "below the brand" in label for label in labels)


def test_the_reported_message_is_translated() -> None:
    from .creative_vm import failure_label

    assert (
        failure_label("caption_length", "caption is 19 characters, below the brand minimum of 80")
        == "El texto de la publicación tiene 19 caracteres y tu marca pide al menos 80: "
        "agrega 61 más."
    )


def test_an_unknown_failure_still_shows() -> None:
    from .creative_vm import failure_label

    assert failure_label("new_rule", "something") == "Regla de marca (new_rule): something"


def test_editable_statuses_mirror_the_fsm() -> None:
    from qualify_api.creative.fsm import EDITABLE_STATUSES

    from .creative_vm import EDITABLE_DRAFT_STATUSES

    assert EDITABLE_DRAFT_STATUSES == EDITABLE_STATUSES


def test_template_outputs_are_labelled_by_port_not_as_slides() -> None:
    from .creative_vm import build_media_vms

    rows = [
        ("t/d/story.png", "image", 2, {"port": "story", "template_id": "promo_producto"}),
        ("t/d/reel.mp4", "video", 0, {"port": "reel"}),
        ("t/d/feed.png", "image", 1, {"port": "feed"}),
    ]
    labels = [vm.label for vm in build_media_vms(rows)]
    assert labels == ["Reel (video corto) 9:16", "Publicación 4:5", "Historia 9:16"]
    # without a port the old behaviour stands: numbered slides and a plain video
    plain = build_media_vms([("a", "image", 0, {}), ("b", "image", 1, None)])
    assert [vm.label for vm in plain] == ["Diapositiva 1 de 2", "Diapositiva 2 de 2"]


# ---------------------------------------------------------------------------
# 9. The recipe step of the template kind (plan-mvp-plantillas-remotion.md §2.1 #4)

_PROMO_MANIFEST: dict[str, object] = {
    "id": "promo_producto",
    "version": 1,
    "name": "Promo de producto",
    "niche": ["shawarma", "helado"],
    "serves_angles": ["product", "new_product", "promotion", "price", "sold_out"],
    "inputs": {
        "hook": {"type": "string", "max": 60},
        "price_line": {"type": "string", "max": 24, "optional": True},
        "cta": {"type": "string", "max": 40},
        "photos": {"type": "image[]", "min": 2, "max": 4},
        "brand": {"type": "brand_kit"},
    },
    "outputs": {
        "reel": {
            "kind": "video",
            "width": 1080,
            "height": 1920,
            "composition": "promo-producto-v1--reel",
        },
        "feed": {
            "kind": "still",
            "width": 1080,
            "height": 1350,
            "composition": "promo-producto-v1--feed",
        },
        "story": {
            "kind": "still",
            "width": 1080,
            "height": 1920,
            "composition": "promo-producto-v1--story",
        },
    },
    "duration": {"from": "script", "min_sec": 8, "max_sec": 30},
    "cost_model": {"seconds_per_video_sec": 2.0, "seconds_per_still": 4.0},
}


def _recipes(photo_count: int, video_count: int = 0):
    from qualify_creative.render import (
        PostFacts,
        TemplateManifest,
        TemplateRegistry,
        suggest_recipes,
    )

    registry = TemplateRegistry([TemplateManifest.model_validate(_PROMO_MANIFEST)])
    facts = PostFacts(angle=ContentType.PROMOTION, photo_count=photo_count, video_count=video_count)
    return suggest_recipes(facts, registry)


def test_recipe_cards_carry_engine_cost_eta_outputs_and_the_suggestion() -> None:
    from .creative_vm import build_recipe_options

    cards = build_recipe_options(_recipes(photo_count=3))
    assert [c.key for c in cards] == ["remotion", "omnihuman", "ugc"]
    remotion, presenter, ugc = cards

    assert remotion.suggested and remotion.rule == 2  # ≥2 photos, no video
    assert remotion.selectable and remotion.available
    assert (remotion.template_id, remotion.template_version) == ("promo_producto", 1)
    assert remotion.label == "Promo de producto"
    assert (remotion.engine_label, remotion.engine_tone) == ("Remotion", "accent")
    assert remotion.cost_label == "USD 0.00"  # our own machine: no money, only time
    # 15 s of video × 2 s/s + two stills × 4 s = 38 s
    assert remotion.eta_label == "~38 s"
    assert remotion.outputs_label == "Reel · Feed · Historia"

    assert not presenter.suggested and not presenter.available and not presenter.selectable
    assert presenter.reason == "el negocio no tiene avatar configurado"
    assert (presenter.engine_label, presenter.engine_tone) == ("Avatar", "info")
    assert presenter.cost_label == "USD 1.80 a 3.70"
    assert presenter.eta_label == ""
    assert presenter.outputs_label == "Reel"

    assert ugc.engine_label == "Para grabar" and not ugc.selectable
    assert "solo cotiza" in ugc.reason
    assert ugc.cost_label == "USD 1.50 a 3.50"


def test_a_template_short_of_photos_is_shown_disabled_with_the_reason() -> None:
    from .creative_vm import build_recipe_options

    remotion, _heygen, ugc = build_recipe_options(_recipes(photo_count=1))
    assert not remotion.available and not remotion.selectable
    assert "necesita 2 fotos" in remotion.reason
    assert not remotion.suggested
    # nothing renderable → nothing suggested, UGC still only quotes
    assert not ugc.suggested and not ugc.selectable


def test_eta_and_outputs_labels() -> None:
    from .creative_vm import eta_label, outputs_label

    assert eta_label(None) == ""
    assert eta_label(0.4) == "~1 s"
    assert eta_label(38.0) == "~38 s"
    assert eta_label(90) == "~90 s"
    assert eta_label(91) == "~2 min"
    assert eta_label(600) == "~10 min"
    assert outputs_label(("reel", "feed", "story")) == "Reel · Feed · Historia"
    assert outputs_label(("square",)) == "Square"
    assert outputs_label(()) == ""


# --- draft review: hashtags suggested from the caption (QUA-118 v2 polish) -------------


def test_hashtag_list_normalises_what_the_field_holds() -> None:
    from .creative_vm import format_hashtags, hashtag_list

    assert hashtag_list("#Promoción, #2x1  sabor #2x1") == ["promocion", "2x1", "sabor"]
    assert hashtag_list("") == []
    assert format_hashtags(["promo", "taro"]) == "#promo #taro"


def test_suggestions_come_from_the_caption_and_skip_what_is_chosen() -> None:
    from .creative_vm import caption_hashtag_suggestions

    caption = "Nuevo sabor de taro en nuestra heladería. El taro llega por tiempo limitado #helado"
    tags = caption_hashtag_suggestions(caption, "#postre #taro", extra=("heladoartesanal",))
    assert tags[0] == "heladoartesanal"  # the catalog's real tag comes first
    assert "helado" in tags and "heladeria" in tags  # the caption's own tag, then its words
    assert "taro" not in tags  # already chosen
    assert "nuestra" not in tags and "para" not in tags  # fillers never become hashtags
    assert caption_hashtag_suggestions("", "") == []


def test_the_stored_script_has_no_length_cap() -> None:
    from qualify_creative.schemas import SCRIPT_MAX, CopyPayload

    long_script = "palabra " * (SCRIPT_MAX // 4)
    assert len(long_script) > SCRIPT_MAX
    assert CopyPayload(hook="Hola", caption="x", script=long_script).script == long_script


def test_cta_list_splits_and_formats() -> None:
    from .creative_vm import cta_list, format_ctas, seen_label

    assert cta_list("Escríbenos por DM · Guarda este post" + chr(10) + "Visítanos") == [
        "Escríbenos por DM",
        "Guarda este post",
        "Visítanos",
    ]
    assert format_ctas(["A", "B"]) == "A · B"
    assert seen_label(0) == "" and seen_label(1) == "visto 1 vez en publicaciones reales"
    assert seen_label(1200) == "visto 1.2k veces en publicaciones reales"


def test_draft_vm_carries_what_the_composition_left_out() -> None:
    """Ticket 24803289: a catalog price too long to print whole is told on /drafts/{id};
    a draft without warnings shows none."""
    common = dict(
        draft_id="d-9",
        status="generated",
        failure_reason=None,
        variants=[_variant("v-1", 0, True)],
        image_url=None,
        total_cost_usd=None,
        voice_profile_version=1,
        model_ids=[],
        requires_ai_disclosure=False,
        created_label="hoy",
    )
    warned = build_draft_vm(**common, warnings=["El precio no cabe completo."])
    assert warned.warnings == ("El precio no cabe completo.",)
    assert warned.can_approve  # a warning informs; the price guard is what refuses
    assert build_draft_vm(**common).warnings == ()


def test_the_draft_screen_reads_the_composition_warnings_of_the_draft(monkeypatch) -> None:
    """The provider turns `DraftDetail.warnings` (kept in `image_assets.params`) into the
    sentences /drafts/{id} shows — the stored ones, not a guess from the brief."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from qualify_api.creative.service import COMPOSITION_WARNINGS_PARAM, DraftDetail, ImageRecord

    from . import creative_provider

    monkeypatch.setattr(creative_provider, "_draft_costs", lambda t, d: (None, ()))
    # «Descargar todo» (m-24828908) mints its own token: kept off the real Redis here
    monkeypatch.setattr(creative_provider, "issue_download_path", lambda t, d: "/piece-download/t")
    monkeypatch.setattr(creative_provider, "_brand_name", lambda t: "Marca")
    cover = ImageRecord(
        id=uuid4(),
        media_url="generated/t/d/slide-1.png",
        width=1080,
        height=1350,
        aspect_ratio="4:5",
        params={
            COMPOSITION_WARNINGS_PARAM: [
                {"code": "price_not_printed", "detail": "El precio no cabe completo."}
            ]
        },
    )
    detail = DraftDetail(
        id=uuid4(),
        brand_id=uuid4(),
        brief_id=uuid4(),
        status="generated",
        failure_reason=None,
        selected_variant_id=None,
        voice_profile_version=1,
        pipeline_version="creative-v1",
        requires_ai_disclosure=False,
        approved_by=None,
        approved_at=None,
        created_at=datetime.now(UTC),
        variants=(),
        image=cover,
        media=(cover,),
    )
    vm = creative_provider._detail_to_vm(uuid4(), detail)
    assert vm.warnings == ("El precio no cabe completo.",)


def test_the_draft_page_shows_each_composition_warning_as_a_warn_callout() -> None:
    """Ticket 24803289: /drafts/{id} renders `draft.warnings` — one `warn` callout each
    (design-system tone, never a raw colour) — so a price left out of the piece is seen
    before approving, not discovered after publishing."""
    import reflex as rx

    from .creative_pages import draft_detail_index
    from .ui import tokens as T

    def walk(component):  # noqa: ANN001, ANN202
        yield component
        for child in getattr(component, "children", None) or ():
            yield from walk(child)

    (loop,) = [
        c
        for c in walk(draft_detail_index())
        if type(c).__name__ == "Foreach" and '["warnings"]' in str(c.iterable)
    ]
    tile = loop.render_fn(rx.Var("w", _var_type=str))
    rendered = str(tile.render())
    assert "Callout" in rendered
    assert all(str(value) in rendered for value in T.tone_scheme("warn").values())


# -- Seedance 2.5 draft mode (m-24820142) ----------------------------------------------


def test_a_draft_video_is_badged_as_a_preview_without_money() -> None:
    """m-24851824 (founder decision 8): the owner never sees money — the badge is
    «Vista previa» whatever the draft cost; m-24851826: no resolutions either."""
    from Qualify.creative_vm import NO_VIDEO_DRAFT, video_draft_vm

    draft = video_draft_vm("draft", "0.513600")
    assert draft.badge == "Vista previa"
    for state in ("draft", "rendering", "failed", "expired", "final"):
        for approved in (False, True):
            vm = video_draft_vm(state, "0.513600", approved=approved)
            for text in (vm.badge, vm.note):
                assert "USD" not in text and "$" not in text and "0,51" not in text
                assert "480p" not in text and "1080p" not in text
                assert "Final pendiente" not in text and "Generando final" not in text
    assert draft.tone == "info" and not draft.can_retry and not draft.rendering
    assert video_draft_vm("rendering", None).rendering
    failed = video_draft_vm("failed", None, "ModelArk falló.", approved=True)
    assert failed.can_retry and failed.note == "ModelArk falló." and failed.tone == "error"
    expired = video_draft_vm("expired", "0.5")
    assert not expired.can_retry and expired.badge == "La vista previa venció"
    assert expired.note == (
        "Las vistas previas duran 7 días. Crea la publicación otra vez para tener una nueva."
    )
    assert video_draft_vm("final", None).badge == "Video final"
    assert video_draft_vm("", None) is NO_VIDEO_DRAFT


def test_draft_summary_shows_the_state_that_needs_the_operator_first() -> None:
    import time

    from qualify_api.creative.draft_mode import draft_summary

    now = time.time()
    ready = {"draft": {"status": "draft", "created_at": now, "cost_usd": "0.5"}}
    failed = {"draft": {"status": "failed", "created_at": now, "cost_usd": "0.25", "error": "x"}}
    old = {"draft": {"status": "draft", "created_at": now - 8 * 86400, "cost_usd": "0.5"}}
    assert draft_summary([ready, failed]) == ("failed", "0.75", "x")
    assert draft_summary([ready, old])[0] == "expired"
    assert draft_summary([{"resolution": "720p"}, None]) == ("", None, "")
    final = {"draft": {"status": "final", "created_at": now - 8 * 86400, "cost_usd": "0.5"}}
    assert draft_summary([final])[0] == "final"  # a final never expires


def test_a_final_left_rendering_by_a_dead_process_shows_as_retryable() -> None:
    import time

    from qualify_api.creative.draft_mode import (
        FINAL_STALE_SECONDS,
        draft_rendering,
        draft_summary,
    )

    from Qualify.creative_vm import video_draft_vm

    now = time.time()
    stale = {
        "draft": {
            "status": "rendering",
            "created_at": now,
            "rendering_at": now - FINAL_STALE_SECONDS,
        }
    }
    fresh = {"draft": {"status": "rendering", "created_at": now, "rendering_at": now}}
    state, _, error = draft_summary([stale], now)
    assert state == "failed" and "a medias" in error
    assert video_draft_vm(state, None, error, approved=True).can_retry
    assert draft_summary([fresh], now)[0] == "rendering"
    assert draft_rendering([stale, fresh], now) and not draft_rendering([stale], now)


def test_the_final_poll_waits_for_every_video_and_stays_quiet_on_a_regenerated_piece() -> None:
    from Qualify.creative_vm import (
        FINAL_POLL_CONTINUE,
        FINAL_POLL_DONE,
        FINAL_POLL_FAILED,
        FINAL_POLL_STOP,
        final_poll_step,
        video_draft_vm,
    )

    assert final_poll_step(video_draft_vm("rendering", None)) == FINAL_POLL_CONTINUE
    # one video failed while another still renders: keep polling, no toast yet
    failed_while_rendering = video_draft_vm(
        "failed", None, "x", still_rendering=True, approved=True
    )
    assert failed_while_rendering.can_retry
    assert final_poll_step(failed_while_rendering) == FINAL_POLL_CONTINUE
    assert final_poll_step(video_draft_vm("failed", None, "x", approved=True)) == FINAL_POLL_FAILED
    assert final_poll_step(video_draft_vm("expired", None)) == FINAL_POLL_FAILED
    assert final_poll_step(video_draft_vm("final", None)) == FINAL_POLL_DONE
    # regenerated: back to a draft, or no draft video at all
    assert final_poll_step(video_draft_vm("draft", None)) == FINAL_POLL_STOP
    assert final_poll_step(video_draft_vm("", None)) == FINAL_POLL_STOP


def test_the_approval_toast_follows_the_piece_not_the_poll() -> None:
    """Review 2026-10-23: a poll already running for the piece used to turn «we are
    making the final» into «ya puedes programarlo»."""
    from .creative_vm import VideoDraftVM, approval_notice, video_draft_vm

    rendering = video_draft_vm("rendering", None)
    assert approval_notice(rendering)[0] == "info"
    failed = video_draft_vm("failed", None, "x", approved=True)
    assert approval_notice(failed)[0] == "error"
    assert approval_notice(VideoDraftVM("", "", "neutral", ""))[0] == "success"


def test_every_screen_words_the_approval_notice_from_the_same_choice() -> None:
    """Review round 3: the gallery and Variaciones use the piece's own notice too — a
    final that could not be ordered never reads «ya puedes programarlo»."""
    from .creative_vm import NO_VIDEO_DRAFT, POST_APPROVED_TEXT, approval_notice, video_draft_vm

    failed = video_draft_vm("failed", None, "x", approved=True)
    kind, text, offer, offer_open = approval_notice(failed, elsewhere="Ábrela")
    assert kind == "error" and text.endswith("Ábrela para reintentarlo.")
    assert "programarlo" not in text and offer is False
    assert offer_open is True  # m-24842981: «Ver publicación» goes with «Ábrela»
    kind, text, offer, offer_open = approval_notice(
        video_draft_vm("rendering", None), elsewhere="Ábrela en Por aprobar"
    )
    assert kind == "info" and text.endswith("Ábrela en Por aprobar para ver cuándo está listo.")
    assert offer is False and offer_open is True
    # on the publication's own page there is nowhere else to go
    assert approval_notice(video_draft_vm("rendering", None)).offer_open is False
    assert approval_notice(NO_VIDEO_DRAFT) == ("success", POST_APPROVED_TEXT, True, False)
    assert approval_notice(NO_VIDEO_DRAFT, approved="Pieza aprobada.")[1] == "Pieza aprobada."


def test_the_approval_notice_offers_a_day_and_time_only_when_nothing_holds_it_back() -> None:
    """m-24842978 merged with m-24820142: «Elegir día y hora» goes with the notice only
    when the publication can be planned AND its own 1080p final is not still being made
    or failed — a draft-pending video cannot be scheduled (MEDIA_DRAFT_PENDING)."""
    from .creative_vm import (
        APPROVED_NOT_READY_TOAST,
        APPROVED_TOAST,
        FINAL_FAILED_NOTE,
        FINAL_RENDERING_NOTE,
        NO_VIDEO_DRAFT,
        approval_notice,
        final_pending_note,
        video_draft_vm,
    )

    assert approval_notice(NO_VIDEO_DRAFT, ready=True) == (
        "success",
        APPROVED_TOAST,
        True,
        False,
    )
    assert approval_notice(NO_VIDEO_DRAFT, ready=False) == (
        "success",
        APPROVED_NOT_READY_TOAST,
        False,
        False,
    )
    rendering = video_draft_vm("rendering", None)
    failed = video_draft_vm("failed", None, "x", approved=True)
    for video in (rendering, failed):
        notice = approval_notice(video, ready=True)
        assert notice.offer_schedule is False and "Ahora elige" not in notice.text
    assert final_pending_note(rendering) == FINAL_RENDERING_NOTE
    assert final_pending_note(failed) == FINAL_FAILED_NOTE
    assert final_pending_note(video_draft_vm("final", None)) == ""
    assert final_pending_note(NO_VIDEO_DRAFT) == ""
    for text in (APPROVED_TOAST, FINAL_RENDERING_NOTE, FINAL_FAILED_NOTE):
        assert "POST" not in text and "Planificador" not in text


def test_the_view_models_video_states_are_draft_modes_own() -> None:
    """Review round 3: the view-model keeps `draft_mode`'s states as strings (it never
    imports the backend); a test, which may import both, keeps them equal."""
    from qualify_api.creative import draft_mode

    from . import creative_vm

    assert creative_vm.VIDEO_DRAFT == draft_mode.DRAFT_READY
    assert creative_vm.VIDEO_RENDERING == draft_mode.DRAFT_RENDERING
    assert creative_vm.VIDEO_FINAL == draft_mode.DRAFT_FINAL
    assert creative_vm.VIDEO_FAILED == draft_mode.DRAFT_FAILED
    assert creative_vm.VIDEO_EXPIRED == draft_mode.DRAFT_EXPIRED
    # and the module stays pure: no backend import of its own
    import ast
    from pathlib import Path

    tree = ast.parse(Path(creative_vm.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(name.startswith("qualify_api") for name in imported)


def test_an_approved_piece_whose_final_was_never_ordered_offers_to_order_it() -> None:
    """Review 2026-10-23: the approval is saved before the finals are ordered; when
    ordering fails the video stays at its draft — on an approved piece that is a final
    to order, with «Reintentar»."""
    from qualify_api.creative.draft_mode import (
        FINAL_NOT_ORDERED_TEXT,
        draft_summary,
        final_retryable,
    )

    from .creative_vm import video_draft_vm

    ready = {"draft": {"status": "draft", "cost_usd": "0.5"}}
    assert draft_summary([ready])[0] == "draft"
    state, cost, error = draft_summary([ready], approved=True)
    assert (state, error) == ("failed", FINAL_NOT_ORDERED_TEXT)
    vm = video_draft_vm(state, cost, error, approved=True)
    assert vm.can_retry and vm.note == FINAL_NOT_ORDERED_TEXT
    assert final_retryable(ready["draft"], approved=True)
    assert not final_retryable(ready["draft"])


def test_a_failed_final_on_a_piece_edited_after_approval_offers_no_retry() -> None:
    """Review round 4: an edit takes the piece back to «generated» and `retry_final`
    orders finals of an approved piece only — the button was offered and always failed.
    The state shows, without «Reintentar», saying that approving again orders it."""
    from .creative_vm import FINAL_NEEDS_APPROVAL_TEXT, approval_notice, video_draft_vm

    edited = video_draft_vm("failed", None, "ModelArk falló.")
    assert not edited.can_retry and edited.badge == "Falta el video final"
    assert edited.note == FINAL_NEEDS_APPROVAL_TEXT and "aprobar" in edited.note
    assert approval_notice(edited)[0] == "success"  # nothing to retry from a toast
    assert video_draft_vm("failed", None, "ModelArk falló.", approved=True).can_retry

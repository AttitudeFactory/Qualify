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
    assert "tope" in failure_vm("budget_exceeded").label
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
    assert routes["dont_examples"] == "/brand"
    assert routes["active_voice_profile"] == "/brand"
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
    assert vm.failure_labels == ("forbidden_claim: «el mejor precio»",)
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
    assert vm.fidelity_summary == "1 de 2 variantes pasan las reglas duras"
    assert vm.cost_label == "$0.04 · Perfil v1 · claude-opus-5"
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
    assert vm.sources[0].kind_label == "brand kit"
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

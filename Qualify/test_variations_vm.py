"""`variations_vm` (ticket 24803289, PR 4): the pure view models of «Variaciones» —
labels and design-system tones, what each tile may do, the «no price» note, the price
conflict text, the outcome of a generation and the Spanish message of every error."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from qualify_api.catalog.service import UnknownProduct
from qualify_api.creative.angle_sets import (
    ANGLE_DISCARDED,
    ANGLE_FAILED,
    ANGLE_PROPOSED,
    ANGLE_QUEUED,
    INTERRUPTED,
    SET_ANGLES_READY,
    AngleGenerationFailed,
    AngleNotActionable,
    AngleRecord,
    AngleSetDetail,
    AngleSetRecord,
    AngleView,
    GenerationOutcome,
    PresetNotAvailable,
    UnknownAngle,
    UnknownAngleSet,
)
from qualify_api.creative.service import BrandNotReady
from qualify_creative.angles import (
    PRESETS,
    AngleProduct,
    AngleSetPlan,
    UnknownPreset,
    price_problem,
)
from qualify_creative.enums import DraftStatus

from .variations_vm import (
    NO_PRICE_TEXT,
    build_angle_vm,
    build_outcome_vm,
    build_plan_vm,
    build_preset_vms,
    build_product_check_vm,
    build_set_summary_vm,
    build_set_vm,
    money,
    variation_error_message,
)

TONES = {"ok", "warn", "error", "info", "neutral"}


def _angle(status: str = ANGLE_PROPOSED, **fields: object) -> AngleRecord:
    base: dict[str, object] = {
        "id": uuid4(),
        "set_id": uuid4(),
        "position": 1,
        "title": "Mesa de cafetería",
        "scene": "sobre una tabla de madera",
        "composition": "plano medio",
        "hook": "Hoy se antoja",
        "cta": "Pide ya",
        "rationale": "vende",
        "status": status,
    }
    base.update(fields)
    return AngleRecord(**base)  # type: ignore[arg-type]


def _set(**fields: object) -> AngleSetRecord:
    base: dict[str, object] = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "brand_id": uuid4(),
        "product_id": uuid4(),
        "preset_key": "escena_producto",
        "requested_count": 10,
        "status": SET_ANGLES_READY,
        "product_name": "Shawarma mixto",
        "price_label": "$18.000",
        "price_missing": False,
        "created_at": datetime(2026, 10, 21, 9, 30, tzinfo=UTC),
    }
    base.update(fields)
    return AngleSetRecord(**base)  # type: ignore[arg-type]


def _no_url(key: str) -> str:
    return ""


def test_money_keeps_sub_cent_amounts_visible() -> None:
    assert money(Decimal("0.35")) == "$0.35"
    assert money(Decimal("0.004")) == "$0.0040"
    assert money(Decimal("0")) == "$0.00"


def test_presets_say_why_they_are_not_available() -> None:
    template = next(p for p in PRESETS if p.needs_render_service)
    scene = next(p for p in PRESETS if not p.needs_render_service)
    vms = build_preset_vms(
        [(scene, None), (template, "La plantilla necesita una foto.")], render_ready=True
    )
    assert vms[0].available and vms[0].reason == ""
    assert not vms[1].available and "foto" in vms[1].reason
    # with photos but no render service, the template still cannot be used
    (no_render,) = build_preset_vms([(template, None)], render_ready=False)
    assert not no_render.available and "servicio de plantillas" in no_render.reason
    assert no_render.format_label == template.format.aspect_ratio


def test_a_product_without_price_carries_the_note() -> None:
    priced = build_product_check_vm(
        AngleProduct(product_id=uuid4(), name="X", price_label="$18.000", photo_keys=("a",))
    )
    bare = build_product_check_vm(AngleProduct(product_id=uuid4(), name="X"))
    assert not priced.price_missing and priced.price_note == "" and priced.photo_count == 1
    assert bare.price_missing and bare.price_note == NO_PRICE_TEXT


def test_the_plan_shows_the_image_cost_only_with_a_rate() -> None:
    assert build_plan_vm(AngleSetPlan(count=10, image_unit_usd=Decimal("0.035"))).images_label == (
        "10 imágenes · $0.35"
    )
    assert build_plan_vm(AngleSetPlan(count=10, image_unit_usd=Decimal(0))).images_label == (
        "10 imágenes"
    )


def test_tile_permissions_follow_the_angle_and_its_draft() -> None:
    proposed = build_angle_vm(AngleView(angle=_angle(ANGLE_PROPOSED)), _no_url)
    assert proposed.can_discard and not proposed.can_restore and not proposed.can_approve
    discarded = build_angle_vm(AngleView(angle=_angle(ANGLE_DISCARDED)), _no_url)
    assert discarded.can_restore and not discarded.can_discard
    draft_id = uuid4()
    ready = build_angle_vm(
        AngleView(
            angle=_angle(ANGLE_QUEUED, draft_id=draft_id),
            draft_status=DraftStatus.GENERATED.value,
            variant_id=uuid4(),
            preview_key="uploads/t/p.jpg",
        ),
        _no_url,
    )
    assert ready.can_approve and not ready.can_retry and ready.draft_id == str(draft_id)
    assert ready.draft_label == "Listo para revisar" and ready.draft_tone == "warn"
    assert ready.preview_key == "uploads/t/p.jpg" and ready.preview_url == ""
    assert {proposed.status_tone, ready.status_tone, ready.draft_tone} <= TONES
    # a piece that landed may be looked at again: another take, new words, or out
    assert ready.can_regenerate and ready.can_edit and ready.can_discard
    assert proposed.can_edit and not proposed.can_regenerate
    assert not discarded.can_edit and not discarded.can_regenerate
    making = build_angle_vm(
        AngleView(angle=_angle(ANGLE_QUEUED, draft_id=uuid4()), draft_status="drafting"),
        _no_url,
    )
    assert not (making.can_edit or making.can_discard or making.can_regenerate)


def test_a_copy_quoting_another_price_cannot_be_approved_and_says_why() -> None:
    vm = build_angle_vm(
        AngleView(
            angle=_angle(ANGLE_QUEUED, draft_id=uuid4()),
            draft_status=DraftStatus.GENERATED.value,
            variant_id=uuid4(),
            price_conflicts=("$15.000",),
            price_problem=price_problem(("Hoy $15.000",), "$18.000"),
        ),
        _no_url,
    )
    assert not vm.can_approve and "$15.000" in vm.failure_text
    assert "($18.000)" in vm.failure_text


def test_a_tile_tells_an_invented_price_and_what_the_composition_left_out() -> None:
    vm = build_angle_vm(
        AngleView(
            angle=_angle(ANGLE_QUEUED, draft_id=uuid4()),
            draft_status=DraftStatus.GENERATED.value,
            variant_id=uuid4(),
            price_conflicts=("$9.900",),
            price_problem=price_problem(("Hoy $9.900",), ""),
            warnings=("El precio del catálogo no cabe completo en esta pieza.",),
        ),
        _no_url,
    )
    assert not vm.can_approve and "no tiene precio en el catálogo" in vm.failure_text
    assert vm.warnings == ("El precio del catálogo no cabe completo en esta pieza.",)


def test_failures_read_in_spanish() -> None:
    interrupted = build_angle_vm(
        AngleView(angle=_angle(ANGLE_FAILED, failure_reason=INTERRUPTED)), _no_url
    )
    assert interrupted.can_retry and "interrumpió" in interrupted.failure_text
    failed_draft = build_angle_vm(
        AngleView(
            angle=_angle(ANGLE_QUEUED, draft_id=uuid4()),
            draft_status=DraftStatus.FAILED.value,
            draft_failure_reason="timeout",
        ),
        _no_url,
    )
    assert failed_draft.can_retry and failed_draft.failure_text
    assert failed_draft.draft_tone == "error"


def test_the_set_view_counts_and_tells_a_missing_price() -> None:
    record = _set(price_missing=True, price_label="")
    detail = AngleSetDetail(
        set=record,
        angles=(
            AngleView(angle=_angle(ANGLE_PROPOSED)),
            AngleView(angle=_angle(ANGLE_DISCARDED, position=2)),
        ),
    )
    vm = build_set_vm(detail, _no_url)
    assert vm.pending_count == 1 and vm.kept_count == 1 and len(vm.angles) == 2
    assert vm.price_missing and vm.price_note == NO_PRICE_TEXT
    assert vm.status_label == "Ángulos listos" and vm.status_tone == "ok"
    summary = build_set_summary_vm(record)
    assert summary.created_label == "21/10 09:30" and summary.count == 10


def test_the_outcome_of_a_generation_in_one_line() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    all_ok = build_outcome_vm(GenerationOutcome(queued=(a, b)))
    assert all_ok.message == "2 en generación" and all_ok.tone == "ok"
    mixed = build_outcome_vm(
        GenerationOutcome(
            queued=(a,), failed=((b, "La marca necesita su Brand Kit"),), unresolved=(c,)
        )
    )
    assert mixed.tone == "warn" and "1 por confirmar" in mixed.message
    assert mixed.details == ("La marca necesita su Brand Kit",)
    assert build_outcome_vm(GenerationOutcome()).tone == "neutral"


@pytest.mark.parametrize(
    ("error", "words"),
    [
        (AngleGenerationFailed("Anthropic no respondió.", reason="provider_error"), "Anthropic"),
        (AngleNotActionable("Esa propuesta ya se está generando."), "ya se está generando"),
        (PresetNotAvailable("La plantilla necesita una foto."), "foto"),
        (UnknownProduct("x"), "catálogo"),
        (UnknownPreset("x"), "estilo"),
        (UnknownAngleSet("x"), "grupo de variaciones"),
        (UnknownAngle("x"), "propuesta"),
        (BrandNotReady(missing=("voice_profile",)), "Brand Kit"),
        (ValueError("badly formed hexadecimal UUID string"), "no son válidos"),
        (RuntimeError("connection reset by peer"), "Inténtalo de nuevo"),
    ],
)
def test_every_error_has_a_spanish_message(error: BaseException, words: str) -> None:
    message = variation_error_message(error)
    assert words in message
    assert "connection reset" not in message and "hexadecimal" not in message

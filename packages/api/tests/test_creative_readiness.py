"""Pure tests for `qualify_api.creative.readiness` (design §6.1 as amended by D4):
weighted completeness, the distill/generate gates, and gap reporting. No database —
`compute_readiness` takes the kit and the voice fact as plain arguments."""

from __future__ import annotations

from uuid import UUID

from qualify_creative.schemas import BrandKit, ToneAxes

from qualify_api.creative.readiness import (
    ACTIVE_VOICE_GAP,
    compute_readiness,
)

_BRAND = UUID("e0000000-0000-4000-8000-0000000000d0")

_TONE = ToneAxes(formal_casual=30, sober_enthusiastic=70, technical_plain=80, brief_elaborate=40)


def _kit(**overrides: object) -> BrandKit:
    """A kit that is empty except the schema-required fields; tests opt fields in."""
    base: dict[str, object] = {
        "brand_id": _BRAND,
        "positioning": "",
        "audience": "",
        "tone_axes": _TONE,
    }
    base.update(overrides)
    return BrandKit.model_validate(base)


def _full_kit() -> BrandKit:
    return _kit(
        positioning="artisan arepas, zero shortcuts",
        audience="walk-in customers in Cali",
        do_examples=("¡Llegó la arepa de chócolo!",),
        dont_examples=("Estimado cliente, le informamos...",),
        cta_patterns=("Pide por WhatsApp",),
        palette_rgb=("#FFD100",),
        logo_asset_key="brand/logo.png",
    )


def test_no_kit_is_fully_missing() -> None:
    readiness = compute_readiness(None, has_active_voice=False)
    assert readiness.has_kit is False
    assert readiness.kit_completeness == 0.0
    assert readiness.has_active_voice is False
    assert readiness.can_distill is False
    assert readiness.can_generate is False
    # Every weighted field is a gap, plus the voice gate.
    assert set(readiness.missing) >= {"positioning", "audience", "do_examples"}
    assert ACTIVE_VOICE_GAP in readiness.missing


def test_full_kit_with_active_voice_is_fully_ready() -> None:
    readiness = compute_readiness(_full_kit(), has_active_voice=True)
    assert readiness.has_kit is True
    assert readiness.kit_completeness == 1.0
    assert readiness.missing == ()
    assert readiness.can_distill is True
    assert readiness.can_generate is True


def test_minimal_distillable_kit_gates() -> None:
    """positioning + audience + tone axes + one do-example is enough to distill, but
    generating additionally requires the approved voice (D4: nothing else — no key)."""
    kit = _kit(
        positioning="artisan arepas",
        audience="walk-in customers",
        do_examples=("¡Llegó la arepa!",),
    )
    without_voice = compute_readiness(kit, has_active_voice=False)
    assert without_voice.can_distill is True
    assert without_voice.can_generate is False
    assert ACTIVE_VOICE_GAP in without_voice.missing
    # The optional fields still show as gaps without blocking the distill gate.
    assert "dont_examples" in without_voice.missing
    assert "palette_rgb" in without_voice.missing

    with_voice = compute_readiness(kit, has_active_voice=True)
    assert with_voice.can_generate is True
    assert ACTIVE_VOICE_GAP not in with_voice.missing


def test_each_distill_requirement_blocks_the_gate() -> None:
    distillable = {
        "positioning": "artisan arepas",
        "audience": "walk-in customers",
        "do_examples": ("¡Llegó la arepa!",),
    }
    assert compute_readiness(_kit(**distillable), has_active_voice=True).can_distill is True
    for dropped, empty in (("positioning", ""), ("audience", ""), ("do_examples", ())):
        broken = dict(distillable, **{dropped: empty})
        readiness = compute_readiness(_kit(**broken), has_active_voice=True)
        assert readiness.can_distill is False, dropped
        assert readiness.can_generate is False, dropped
        assert dropped in readiness.missing


def test_whitespace_positioning_counts_as_missing() -> None:
    kit = _kit(positioning="   ", audience="someone", do_examples=("x example here",))
    readiness = compute_readiness(kit, has_active_voice=True)
    assert "positioning" in readiness.missing
    assert readiness.can_distill is False


def test_copy_fields_outweigh_visual_fields() -> None:
    """§6.2: the copy examples move the output more than the palette. A kit filled
    only with copy substance must score strictly above one filled only with visuals."""
    copy_side = compute_readiness(
        _kit(do_examples=("uno bueno",), dont_examples=("uno malo",)),
        has_active_voice=False,
    )
    visual_side = compute_readiness(
        _kit(palette_rgb=("#FFD100",), logo_asset_key="brand/logo.png"),
        has_active_voice=False,
    )
    assert copy_side.kit_completeness > visual_side.kit_completeness
    # Even the do-examples alone outweigh palette + logo together.
    do_only = compute_readiness(_kit(do_examples=("uno bueno",)), has_active_voice=False)
    assert do_only.kit_completeness > visual_side.kit_completeness


def test_completeness_is_monotonic_in_filled_fields() -> None:
    empty = compute_readiness(_kit(), has_active_voice=False)
    partial = compute_readiness(_kit(do_examples=("uno",)), has_active_voice=False)
    full = compute_readiness(_full_kit(), has_active_voice=False)
    assert empty.kit_completeness < partial.kit_completeness < full.kit_completeness
    assert 0.0 <= empty.kit_completeness <= 1.0
    assert full.kit_completeness == 1.0

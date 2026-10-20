"""«Tu avatar animado» (scaffold, § request 2026-10-19): the prompt built from the kit,
the off-switch that guarantees nothing is attempted without the BytePlus key, and the
orchestration against fakes — no network, no R2, no Postgres."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.schemas import BrandContext, BrandKit, ToneAxes

from qualify_api.creative import brand_avatar as ba
from qualify_api.creative.brand_kit_store import AVATAR_KEY, carry_reserved

TENANT = UUID("00000000-0000-0000-0000-0000000000aa")
BRAND = UUID("00000000-0000-0000-0000-0000000000bb")
ON = {ba.AVATAR_SWITCH_ENV: "on", ba.ARK_KEY_ENV: "ark-test-key"}


def _kit(**overrides: Any) -> BrandKit:
    values: dict[str, Any] = {
        "brand_id": BRAND,
        "positioning": "Smash burgers   hechas al momento",
        "audience": "Jóvenes de Medellín",
        "tone_axes": ToneAxes(
            formal_casual=80, sober_enthusiastic=75, technical_plain=20, brief_elaborate=50
        ),
        "palette_rgb": ("#c4622d", "F5C518", "not-a-colour", "#C4622D"),
        "logo_asset_key": f"t/{TENANT}/brand/{BRAND}/logo/x_logo.png",
    }
    values.update(overrides)
    return BrandKit(**values)


# ---------------------------------------------------------------------------------------
# the switch


@pytest.mark.parametrize(
    ("env", "reason"),
    [
        ({}, ba.REASON_SWITCH_OFF),
        ({ba.ARK_KEY_ENV: "k"}, ba.REASON_SWITCH_OFF),
        ({ba.AVATAR_SWITCH_ENV: "off", ba.ARK_KEY_ENV: "k"}, ba.REASON_SWITCH_OFF),
        ({ba.AVATAR_SWITCH_ENV: "1"}, ba.REASON_MISSING_KEY),
        ({ba.AVATAR_SWITCH_ENV: "true", ba.ARK_KEY_ENV: "   "}, ba.REASON_MISSING_KEY),
        (ON, None),
    ],
)
def test_the_feature_needs_the_switch_and_the_key(env: dict[str, str], reason: str | None) -> None:
    assert ba.avatar_unavailable_reason(env) == reason
    assert ba.avatar_enabled(env) is (reason is None)


def test_the_switch_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ba.AVATAR_SWITCH_ENV, raising=False)
    assert ba.avatar_enabled() is False


class _Boom:
    """Deps that fail the test if anything is touched."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"deps.{name} touched while the feature is off")


@pytest.mark.parametrize("env", [{}, {ba.AVATAR_SWITCH_ENV: "on"}])
def test_off_raises_before_touching_anything(env: dict[str, str]) -> None:
    with pytest.raises(ba.BrandAvatarUnavailable):
        ba.generate_brand_avatar(TENANT, BRAND, env=env, deps=_Boom())  # type: ignore[arg-type]


def test_off_the_completion_hook_is_a_silent_no_op() -> None:
    assert ba.maybe_generate_after_kit(TENANT, BRAND, env={}, deps=_Boom()) is None  # type: ignore[arg-type]


def test_off_never_builds_the_production_wiring(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode() -> None:
        raise AssertionError("production_deps built while off")

    monkeypatch.setattr(ba, "production_deps", explode)
    assert ba.maybe_generate_after_kit(TENANT, BRAND, env={}) is None


# ---------------------------------------------------------------------------------------
# the prompt


def test_the_inputs_come_from_the_kit_and_what_the_brand_kit_saved() -> None:
    inputs = ba.avatar_inputs(
        _kit(),
        brand_name="Burger  Lab",
        context=BrandContext(sector="Hamburguesería", location="Medellín, CO"),
        logo_brief={"feeling": "cercanía", "style": "  divertido\ny urbano "},
    )
    assert inputs.brand_name == "Burger Lab"
    assert inputs.positioning == "Smash burgers hechas al momento"
    assert inputs.sector == "Hamburguesería"
    # valid hex only, normalized, de-duplicated
    assert inputs.palette == ("#C4622D", "#F5C518")
    assert inputs.tone == (80, 75, 20, 50)
    assert inputs.style == "divertido y urbano"
    assert inputs.logo_key == f"t/{TENANT}/brand/{BRAND}/logo/x_logo.png"


def test_the_prompt_carries_the_brand_its_colours_its_tone_and_the_logo() -> None:
    prompt = ba.build_avatar_prompt(
        ba.avatar_inputs(
            _kit(),
            brand_name="Burger Lab",
            context=BrandContext(sector="Hamburguesería"),
            logo_brief={"feeling": "cercanía"},
        )
    )
    assert '"Burger Lab"' in prompt
    assert '"Hamburguesería"' in prompt
    assert "#C4622D, #F5C518" in prompt
    assert "playful" in prompt and "big warm smile" in prompt
    assert "expertise of the trade" in prompt  # técnico ≤ 40
    assert "reference image is the brand's logo" in prompt
    assert prompt.endswith("No text, no letters, no logos, no watermark.")


def test_an_empty_kit_still_makes_a_valid_short_prompt() -> None:
    kit = _kit(positioning="", audience="", palette_rgb=(), logo_asset_key=None)
    prompt = ba.build_avatar_prompt(ba.avatar_inputs(kit))
    assert "mascot" in prompt
    assert "reference image" not in prompt
    assert "brand colours" not in prompt
    assert len(prompt) < 1000


def test_long_kit_texts_are_capped() -> None:
    inputs = ba.avatar_inputs(_kit(positioning="x" * 2000))
    assert len(inputs.positioning) <= 180
    assert len(ba.build_avatar_prompt(inputs)) < 3000  # the adapter's hard cap


# ---------------------------------------------------------------------------------------
# the orchestration, against fakes


class _Fakes:
    def __init__(self, *, fail_render: bool = False, inputs: ba.AvatarInputs | None = None):
        self.records: list[dict[str, Any] | None] = []
        self.puts: list[tuple[UUID, str, bytes, str]] = []
        self.renders: list[tuple[str, list[bytes]]] = []
        self.fail_render = fail_render
        self.inputs = inputs if inputs is not None else ba.avatar_inputs(_kit())

    def deps(self) -> ba.AvatarDeps:
        def render(t: UUID, b: UUID, prompt: str, refs: list[bytes]) -> ba.SeedreamImage:
            self.renders.append((prompt, refs))
            if self.fail_render:
                raise RuntimeError("ModelArk said no")
            return ba.SeedreamImage(
                data=b"jpeg",
                provider="seedream",
                model_id="seedream-5-0-lite-260128",
                model_revision="seedream-5-0-260128",
                cost_usd=Decimal("0.035"),
            )

        def save(t: UUID, b: UUID, record: Mapping[str, Any] | None) -> None:
            self.records.append(dict(record) if record else None)

        return ba.AvatarDeps(
            load_inputs=lambda t, b: self.inputs,
            read_media=lambda key: b"logo-bytes",
            render=render,
            put_media=lambda t, key, data, ct: self.puts.append((t, key, data, ct)),
            save_record=save,
        )


def test_a_generation_stores_the_image_and_its_provenance() -> None:
    fakes = _Fakes()
    avatar = ba.generate_brand_avatar(TENANT, BRAND, env=ON, deps=fakes.deps())
    assert [r["status"] for r in fakes.records if r] == ["pending", "ready"]
    (tenant, key, data, content_type) = fakes.puts[0]
    assert tenant == TENANT and data == b"jpeg" and content_type == "image/jpeg"
    assert key.startswith(f"t/{TENANT}/brand/{BRAND}/avatar/") and key.endswith(".jpg")
    assert fakes.renders[0][1] == [b"logo-bytes"]  # the logo goes as a reference
    assert avatar.status is ba.AvatarStatus.READY
    assert avatar.object_key == key
    assert avatar.model_revision == "seedream-5-0-260128"
    assert avatar.prompt_version == ba.PROMPT_VERSION
    assert avatar.cost_usd == "0.035"
    assert ba.BrandAvatar.from_record(fakes.records[-1]) == avatar


def test_a_failed_generation_leaves_a_failed_record_and_says_so() -> None:
    fakes = _Fakes(fail_render=True)
    with pytest.raises(ba.BrandAvatarFailed):
        ba.generate_brand_avatar(TENANT, BRAND, env=ON, deps=fakes.deps())
    assert fakes.records[-1] is not None and fakes.records[-1]["status"] == "failed"
    assert fakes.puts == []
    # the completion hook swallows it: finishing the kit never looks failed
    assert ba.maybe_generate_after_kit(TENANT, BRAND, env=ON, deps=fakes.deps()) is None


def test_no_kit_is_unavailable_and_writes_nothing() -> None:
    fakes = _Fakes()
    fakes.inputs = None  # type: ignore[assignment]  # the brand has no kit yet
    with pytest.raises(ba.BrandAvatarUnavailable) as caught:
        ba.generate_brand_avatar(TENANT, BRAND, env=ON, deps=fakes.deps())
    assert caught.value.reason == ba.REASON_NO_KIT
    assert fakes.records == [] and fakes.renders == []


def test_each_generation_gets_a_fresh_key() -> None:
    assert ba.avatar_object_key(TENANT, BRAND) != ba.avatar_object_key(TENANT, BRAND)


def test_an_unknown_record_reads_as_none() -> None:
    assert ba.BrandAvatar.from_record(None) is None
    assert ba.BrandAvatar.from_record({"status": "weird"}) is None


# ---------------------------------------------------------------------------------------
# storage: the wizards' saves keep the avatar


def test_a_wizard_save_of_the_logo_brief_keeps_the_avatar() -> None:
    record = {"status": "ready", "object_key": f"t/{TENANT}/brand/{BRAND}/avatar/a.jpg"}
    stored = {"style": "old", AVATAR_KEY: record}
    written = carry_reserved("logo_brief", stored, {"style": "new", "feeling": "x"})
    assert written == {"style": "new", "feeling": "x", AVATAR_KEY: record}


def test_only_the_reserved_key_is_carried_and_only_in_its_document() -> None:
    assert carry_reserved("logo_brief", {"style": "old"}, {"feeling": "x"}) == {"feeling": "x"}
    assert carry_reserved("connect", {AVATAR_KEY: {"a": 1}}, {"network": "ig"}) == {"network": "ig"}
    mine = {"status": "failed"}
    assert carry_reserved("logo_brief", {AVATAR_KEY: {"x": 1}}, {AVATAR_KEY: mine}) == {
        AVATAR_KEY: mine
    }
    assert carry_reserved("logo_brief", None, {"style": "s"}) == {"style": "s"}


def test_a_fresh_uuid_does_not_leak_into_the_key_prefix() -> None:
    other = uuid4()
    assert not ba.avatar_object_key(other, BRAND).startswith(f"t/{TENANT}/")


def test_the_animated_avatar_videos_character_is_described_from_the_kit() -> None:
    """§ request 2026-10-20: the «Avatar animado» video's character comes from the Brand
    Kit — described from it while the kit has no drawn avatar: the character only (the
    video composes the background), within the avatar prompt's field."""
    inputs = ba.AvatarInputs(
        brand_name="Nibbles' Burgers",
        sector="Hamburguesería smash",
        palette=("#C4622D", "#F5C518", "#111111", "#FFFFFF"),
        tone=(80, 75, 90, 30),
        style="ilustración cálida",
    )
    text = ba.describe_character(inputs)
    assert "Nibbles' Burgers" in text and "Hamburguesería smash" in text
    assert "#C4622D, #F5C518, #111111" in text and "#FFFFFF" not in text
    assert "background" not in text and len(text) <= ba.CHARACTER_MAX_CHARS
    assert "Style" not in ba.describe_character(ba.AvatarInputs(brand_name="x", style="a"))
    long = ba.describe_character(ba.AvatarInputs(brand_name="x", style="y " * 400))
    assert len(long) <= ba.CHARACTER_MAX_CHARS and long.endswith("…")

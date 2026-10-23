"""Per-origin capabilities of Fase C (m-24789646, B6): every unverified Meta operation is
behind a switch that is OFF by default, only `on` turns it on, and a capability with no
code behind it stays off whatever its switch says. The pinned states below are the
ticket's evidence trail: moving one is a code change with its proof, never a setting.
"""

from __future__ import annotations

import pytest

from qualify_api.followups import (
    REGISTRY,
    STATE_LABELS,
    Capabilities,
    Capability,
    CapabilityState,
)
from qualify_api.inbox.composition import STORY_COMMENTS_ENV

ALL_ON = {spec.env_var: "on" for spec in REGISTRY.values()}


def test_every_capability_is_registered_with_its_own_switch() -> None:
    assert set(REGISTRY) == set(Capability)
    env_vars = [spec.env_var for spec in REGISTRY.values()]
    assert len(set(env_vars)) == len(env_vars)
    assert all(spec.reason for spec in REGISTRY.values())


def test_every_state_has_a_label() -> None:
    assert set(STATE_LABELS) == set(CapabilityState)


def test_story_comments_reuses_the_switch_of_m_24789644() -> None:
    assert REGISTRY[Capability.STORY_COMMENTS].env_var == STORY_COMMENTS_ENV


def test_current_states_are_pinned() -> None:
    """What is true on main. R1, R3 and R4 ran against Meta on 2026-10-22 with a tester
    (evidence in docs/conversaciones-limitaciones-meta.md §7): the three capabilities are
    verified — still OFF by default, each deployment turns them on with its switch."""
    assert {cap: spec.state for cap, spec in REGISTRY.items()} == {
        Capability.COMMENT_PRIVATE_REPLY: CapabilityState.VERIFIED,
        Capability.STORY_COMMENTS: CapabilityState.META_LIMITATION,
        Capability.STORY_REPLY_CONTEXT: CapabilityState.VERIFIED,
        Capability.PUBLIC_NOTICE: CapabilityState.VERIFIED,
        # m-24789472: built from the corpus, no live test yet (R6).
        Capability.ICE_BREAKERS: CapabilityState.TO_VERIFY,
    }


@pytest.mark.parametrize("capability", list(Capability))
def test_everything_is_off_by_default(capability: Capability) -> None:
    caps = Capabilities.from_env({})
    availability = caps.availability(capability)
    assert availability.enabled is False
    assert availability.reason
    assert caps.enabled(capability) is False


@pytest.mark.parametrize("value", ["", "off", "true", "1", "yes", "enabled", " o n "])
def test_only_on_switches_a_capability_on(value: str) -> None:
    caps = Capabilities.from_env({STORY_COMMENTS_ENV: value})
    assert caps.switched_on == frozenset()


@pytest.mark.parametrize("value", ["on", "ON", " On "])
def test_on_is_case_and_space_insensitive(value: str) -> None:
    caps = Capabilities.from_env({STORY_COMMENTS_ENV: value})
    assert caps.switched_on == frozenset({Capability.STORY_COMMENTS})


def test_a_not_implemented_capability_stays_off_even_when_switched_on() -> None:
    caps = Capabilities.from_env(ALL_ON)
    for capability, spec in REGISTRY.items():
        if spec.state is CapabilityState.NOT_IMPLEMENTED:
            availability = caps.availability(capability)
            assert availability.enabled is False
            assert availability.reason == spec.reason


@pytest.mark.parametrize(
    "capability",
    [
        Capability.STORY_COMMENTS,
        Capability.COMMENT_PRIVATE_REPLY,
        Capability.PUBLIC_NOTICE,
        Capability.STORY_REPLY_CONTEXT,
    ],
)
def test_an_implemented_capability_follows_its_switch(capability: Capability) -> None:
    off = Capabilities.from_env({}).availability(capability)
    on = Capabilities.from_env(ALL_ON).availability(capability)
    assert off.enabled is False
    assert on.enabled is True and on.reason == ""


@pytest.mark.parametrize(
    ("capability", "test_id"),
    [
        (Capability.COMMENT_PRIVATE_REPLY, "R1"),
        (Capability.STORY_REPLY_CONTEXT, "R3"),
        (Capability.PUBLIC_NOTICE, "R4"),
    ],
)
def test_a_verified_capability_is_still_off_by_default_and_names_its_switch(
    capability: Capability, test_id: str
) -> None:
    availability = Capabilities.from_env({}).availability(capability)
    assert availability.enabled is False
    assert availability.state_label == "Verificado"
    assert test_id in availability.reason and "2026-10-22" in availability.reason
    assert REGISTRY[capability].env_var in availability.reason


def test_a_meta_limitation_explains_the_limitation_not_the_switch() -> None:
    availability = Capabilities.from_env({}).availability(Capability.STORY_COMMENTS)
    assert availability.state is CapabilityState.META_LIMITATION
    assert availability.state_label == "Limitación de Meta"
    assert "Comments cannot be made on story media" in availability.reason


def test_from_env_reads_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for spec in REGISTRY.values():
        monkeypatch.delenv(spec.env_var, raising=False)
    assert Capabilities.from_env().switched_on == frozenset()
    monkeypatch.setenv(STORY_COMMENTS_ENV, "on")
    assert Capabilities.from_env().switched_on == frozenset({Capability.STORY_COMMENTS})


def test_ice_breakers_has_its_own_switch_and_a_spanish_reason() -> None:
    spec = REGISTRY[Capability.ICE_BREAKERS]
    assert spec.env_var == "QUALIFY_ICE_BREAKERS"
    off = Capabilities.from_env({}).availability(Capability.ICE_BREAKERS)
    assert off.enabled is False
    assert off.state_label == "Por verificar"
    assert "preguntas iniciales" in off.reason and "QUALIFY_ICE_BREAKERS" in off.reason
    on = Capabilities.from_env({"QUALIFY_ICE_BREAKERS": "on"})
    assert on.enabled(Capability.ICE_BREAKERS) is True

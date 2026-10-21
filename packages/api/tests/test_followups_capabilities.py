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
    """What is true on this branch. PR 2/4/5 flip their own row; R1-R4 move them to
    `verified` (or document them) with evidence in docs/conversaciones-limitaciones-meta.md."""
    assert {cap: spec.state for cap, spec in REGISTRY.items()} == {
        Capability.COMMENT_PRIVATE_REPLY: CapabilityState.TO_VERIFY,
        Capability.STORY_COMMENTS: CapabilityState.META_LIMITATION,
        Capability.STORY_REPLY_CONTEXT: CapabilityState.NOT_IMPLEMENTED,
        Capability.PUBLIC_NOTICE: CapabilityState.NOT_IMPLEMENTED,
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
    "capability", [Capability.STORY_COMMENTS, Capability.COMMENT_PRIVATE_REPLY]
)
def test_an_implemented_capability_follows_its_switch(capability: Capability) -> None:
    off = Capabilities.from_env({}).availability(capability)
    on = Capabilities.from_env(ALL_ON).availability(capability)
    assert off.enabled is False
    assert on.enabled is True and on.reason == ""


def test_a_capability_to_verify_says_why_and_which_switch_is_off() -> None:
    availability = Capabilities.from_env({}).availability(Capability.COMMENT_PRIVATE_REPLY)
    assert availability.state_label == "Por verificar"
    assert "R1" in availability.reason
    assert "QUALIFY_COMMENT_PRIVATE_REPLY" in availability.reason


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

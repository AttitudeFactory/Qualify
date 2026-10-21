"""The published `IntentSignal` contract (m-24789644, B4): validation, the derived
`commercial_intent` flag, JSON round-trip and the shipped fixture."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from qualify_api.intent import (
    COMMERCIAL_CLASSES,
    INTENT_CLASS_LABELS,
    IntentClass,
    IntentSignal,
    load_fixture_signals,
)


def _signal(classes: Mapping[str, float], **overrides: Any) -> IntentSignal:
    payload: dict[str, Any] = {
        "comment_id": uuid4(),
        "source_id": "17900000000000099",
        "classes": classes,
        "detector_version": "intent-test-v1",
        "pipeline_version": "p1",
        "model_id": "test-model",
    }
    payload.update(overrides)
    return IntentSignal.model_validate(payload)


def test_commercial_classes_are_every_class_but_general() -> None:
    assert IntentClass.GENERAL not in COMMERCIAL_CLASSES
    assert COMMERCIAL_CLASSES | {IntentClass.GENERAL} == set(IntentClass)


def test_every_class_has_a_visible_label() -> None:
    assert set(INTENT_CLASS_LABELS) == set(IntentClass)


def test_multi_label_signal_keeps_a_confidence_per_class() -> None:
    signal = _signal({"price": 0.9, "availability": 0.4})

    assert signal.classes == {IntentClass.PRICE: 0.9, IntentClass.AVAILABILITY: 0.4}
    assert signal.commercial_intent is True


def test_general_only_is_not_commercial() -> None:
    assert _signal({"general": 0.99}).commercial_intent is False


def test_general_cannot_be_combined_with_a_commercial_class() -> None:
    with pytest.raises(ValidationError, match="general"):
        _signal({"general": 0.6, "price": 0.5})


def test_at_least_one_class_is_required() -> None:
    with pytest.raises(ValidationError, match="at least one class"):
        _signal({})


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_must_be_within_unit_interval(confidence: float) -> None:
    with pytest.raises(ValidationError, match=r"\[0, 1\]"):
        _signal({"price": confidence})


def test_unknown_class_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _signal({"discount": 0.8})


@pytest.mark.parametrize("field", ["source_id", "detector_version", "pipeline_version", "model_id"])
def test_provenance_fields_cannot_be_empty(field: str) -> None:
    with pytest.raises(ValidationError):
        _signal({"price": 0.8}, **{field: ""})


def test_model_revision_defaults_to_null() -> None:
    assert _signal({"price": 0.8}).model_revision is None


def test_signal_is_immutable() -> None:
    signal = _signal({"price": 0.8})

    with pytest.raises(ValidationError):
        signal.model_id = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        signal.classes[IntentClass.HOURS] = 0.5  # type: ignore[index]


def test_json_round_trip_serializes_the_derived_flag() -> None:
    signal = _signal({"hours": 0.7, "location": 0.8}, model_revision="abc123")

    dumped = signal.model_dump(mode="json")
    assert dumped["commercial_intent"] is True
    assert dumped["classes"] == {"hours": 0.7, "location": 0.8}

    assert IntentSignal.model_validate_json(signal.model_dump_json()) == signal


def test_commercial_intent_in_a_payload_is_recomputed_not_trusted() -> None:
    signal = _signal({"general": 0.9}, commercial_intent=True)

    assert signal.commercial_intent is False


def test_fixture_loads_valid_signals_covering_every_class() -> None:
    fixtures = load_fixture_signals()

    assert fixtures
    assert all(item.text for item in fixtures)
    assert all(item.signal.detector_version == "fixture" for item in fixtures)
    assert len({item.signal.comment_id for item in fixtures}) == len(fixtures)
    covered = {intent_class for item in fixtures for intent_class in item.signal.classes}
    assert covered == set(IntentClass)
    assert any(not item.signal.commercial_intent for item in fixtures)

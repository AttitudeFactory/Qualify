"""Signed intent isolation, immutable overlays and exact unit validation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qualify_api.ads.edit_ledger import EDIT_PIPELINE, consistent_intent, overlay, revision
from qualify_api.ads.edit_review import PreparedPromotionEdit, seal, unseal
from qualify_api.ads.live_management import _intent
from qualify_api.ads.promotions import Promotion
from qualify_api.ads.results import ResultsUnavailable

NOW = datetime(2026, 11, 8, tzinfo=UTC)


@pytest.fixture(autouse=True)
def review_secret(monkeypatch):
    monkeypatch.setenv("QUALIFY_OAUTH_STATE_SECRET", "test-only-edit-signing-key-32-characters")


def test_review_is_bounded_domain_separated_expiring_and_rotation_safe(monkeypatch):
    token = seal({"tenant": str(uuid4()), "payload": {"lifetime_budget": 50000}}, NOW)
    assert unseal(token, NOW + timedelta(seconds=299))["payload"] == {"lifetime_budget": 50000}
    for invalid in (token + "x", "x" * 48001, "", "not.json", token.replace(".", "..")):
        with pytest.raises(ResultsUnavailable):
            unseal(invalid, NOW)
    for when in (NOW - timedelta(seconds=1), NOW + timedelta(minutes=5)):
        with pytest.raises(ResultsUnavailable):
            unseal(token, when)
    monkeypatch.setenv(
        "QUALIFY_OAUTH_STATE_SECRET", "different-test-only-signing-key-32-characters"
    )
    with pytest.raises(ResultsUnavailable):
        unseal(token, NOW)


def test_review_token_not_in_repr_and_dev_secret_fails_closed(monkeypatch):
    prepared = PreparedPromotionEdit(
        "budget", "Cambiar presupuesto", NOW, 100, 200, NOW, NOW, "private-review-token"
    )
    assert "private-review-token" not in repr(prepared)
    monkeypatch.delenv("QUALIFY_OAUTH_STATE_SECRET")
    with pytest.raises(ResultsUnavailable):
        seal({}, NOW)


def promotion():
    return Promotion(
        uuid4(),
        {
            "budget_minor": 5000000,
            "end_time": "2099-01-01T00:00:00+00:00",
            "start_time": "2026-01-01T00:00:00+00:00",
        },
    )


def test_overlay_only_completed_verified_intents_preserves_initial_request():
    original = promotion()
    before = {k: original.request[k] for k in ("budget_minor", "end_time")}
    after = before | {"budget_minor": 6000000}
    row = {
        "id": uuid4(),
        "state": "unknown",
        "action": "budget",
        "payload": {"lifetime_budget": 60000},
        "approval_evidence": {
            "pipeline": EDIT_PIPELINE,
            "confirmed": True,
            "before": before,
            "after": after,
        },
    }
    assert overlay(original, [row]).request == original.request
    row["state"] = "reconciled"
    assert overlay(original, [row]).request["budget_minor"] == 6000000
    assert original.request["budget_minor"] == 5000000
    row["approval_evidence"]["before"] = before | {"budget_minor": 1}
    with pytest.raises(ResultsUnavailable):
        overlay(original, [row])


def test_revision_changes_on_new_operation_even_remote_baseline_restored():
    row = {"id": uuid4(), "state": "completed"}
    assert revision([]) != revision([row])
    assert revision([row]) != revision([row | {"state": "unknown"}])


def test_ledger_never_adopts_mismatched_payload_and_displayed_after_values():
    before = {"budget_minor": 10000, "end_time": "2099-01-01T00:00:00+00:00"}
    after = before | {"budget_minor": 20000}
    assert consistent_intent("budget", {"lifetime_budget": 200}, before, after)
    assert not consistent_intent("budget", {"lifetime_budget": 201}, before, after)
    assert not consistent_intent("resume", {"status": "ACTIVE"}, before, after)
    assert not consistent_intent("end_time", {"end_time": before["end_time"]}, before, after)


def test_cop_increase_uses_meta_offset_one_and_rejects_reduction_fraction():
    original = promotion()
    changed, payload, _ = _intent(original, "budget", 6000000, None)
    assert payload == {"lifetime_budget": 60000}
    assert changed.request["budget_minor"] == 6000000
    assert original.request["budget_minor"] == 5000000
    for value in (5000000, 6000001, 4999901, 0, -100, True):
        with pytest.raises(ResultsUnavailable):
            _intent(original, "budget", value, None)
    # A whole-peso decrease is a valid intent; its floor is checked against Meta later.
    lowered, payload, _ = _intent(original, "budget", 4000000, None)
    assert payload == {"lifetime_budget": 40000} and lowered.request["budget_minor"] == 4000000


def test_ledger_accepts_a_recorded_decrease_but_never_a_no_op():
    before = {"budget_minor": 20000, "end_time": "2099-01-01T00:00:00+00:00"}
    assert consistent_intent(
        "budget", {"lifetime_budget": 100}, before, before | {"budget_minor": 10000}
    )
    assert not consistent_intent("budget", {"lifetime_budget": 200}, before, before)
    assert not consistent_intent(
        "budget", {"lifetime_budget": 0}, before, before | {"budget_minor": 0}
    )

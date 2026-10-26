"""ADR 41: first-night scheduling and object-bound human confirmation."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from qualify_api.creative.final_review import final_confirmed, schedule_final
from qualify_api.planner.post_reader import NotPublishable, PublishablePost, UnpublishableReason
from qualify_api.planner.publishable import evaluate

from .test_planner_publishable import _post, _video

NOW = datetime(2026, 10, 26, 15, tzinfo=UTC)


@pytest.mark.parametrize("publications", [(), (NOW + timedelta(days=3),)])
def test_approval_orders_first_night_even_without_publication(publications: tuple) -> None:
    plan = schedule_final(
        now=NOW,
        timezone="America/Caracas",
        preview_created_at=NOW.timestamp(),
        publications=publications,
    )
    assert plan.not_before == datetime(2026, 10, 27, 4, tzinfo=UTC)
    assert plan.lane == "nightly"


@pytest.mark.parametrize("manual,publications", [(True, ()), (False, (NOW + timedelta(hours=1),))])
def test_manual_and_same_day_are_immediate(manual: bool, publications: tuple) -> None:
    plan = schedule_final(
        now=NOW,
        timezone="America/Caracas",
        preview_created_at=NOW.timestamp(),
        manual=manual,
        publications=publications,
    )
    assert plan.not_before == NOW
    assert plan.lane == "immediate" and plan.priority == 8


def test_early_publication_promotes_without_waiting_for_night() -> None:
    plan = schedule_final(
        now=NOW,
        timezone="America/Caracas",
        preview_created_at=NOW.timestamp(),
        publications=(datetime(2026, 10, 27, 12, tzinfo=UTC),),
    )
    assert plan.not_before == NOW
    assert plan.deadline == datetime(2026, 10, 27, 0, tzinfo=UTC)


def test_hard_deadline_wins_over_far_publication() -> None:
    plan = schedule_final(
        now=NOW,
        timezone="UTC",
        preview_created_at=(NOW - timedelta(days=6)).timestamp(),
        publications=(NOW + timedelta(days=10),),
    )
    assert plan.deadline == NOW + timedelta(days=1, minutes=-15)


def test_configured_night_uses_business_timezone() -> None:
    plan = schedule_final(
        now=NOW,
        timezone="Asia/Tokyo",
        preview_created_at=NOW.timestamp(),
        night_start=1,
        night_end=5,
    )
    assert plan.not_before == datetime(2026, 10, 26, 16, tzinfo=UTC)


def test_same_day_review_target_does_not_create_an_already_expired_deadline() -> None:
    plan = schedule_final(
        now=NOW,
        timezone="UTC",
        preview_created_at=NOW.timestamp(),
        publications=(NOW + timedelta(hours=2),),
    )
    assert plan.not_before == NOW
    assert plan.deadline == NOW + timedelta(days=7, minutes=-15)


def test_legacy_final_is_unconfirmed_not_grandfathered() -> None:
    assert not final_confirmed({"draft": {"status": "final"}}, object_key="same")


def test_final_identity_requires_every_confirmation_component() -> None:
    block = {
        "status": "final",
        "final_sha256": "a" * 64,
        "confirmed_sha256": "a" * 64,
        "final_object_key": "key",
        "confirmed_object_key": "key",
        "confirmed_by": "owner",
        "confirmed_at": NOW.isoformat(),
        "confirmed_revision": 2,
    }
    assert final_confirmed({"draft": block}, object_key="key", revision=2)
    for field in block:
        missing = {key: value for key, value in block.items() if key != field}
        assert not final_confirmed({"draft": missing}, object_key="key", revision=2), field
    assert not final_confirmed({"draft": block}, object_key="changed", revision=2)
    assert not final_confirmed({"draft": block}, object_key="key", revision=3)
    assert final_confirmed({}, object_key="image")


def test_unconfirmed_final_can_be_scheduled_but_never_published() -> None:
    candidate = _post(_video(final_unconfirmed=True, draft_pending=True), category="reel")
    verdict = evaluate(candidate)
    assert isinstance(verdict, NotPublishable)
    assert verdict.reason is UnpublishableReason.MEDIA_FINAL_UNCONFIRMED
    assert isinstance(evaluate(candidate, for_scheduling=True), PublishablePost)
    invalid = replace(candidate, media=(_video(final_unconfirmed=True, content_type=None),))
    assert isinstance(evaluate(invalid, for_scheduling=True), NotPublishable)
    invalid = replace(candidate, media=(_video(final_unconfirmed=True, object_key="other/key"),))
    assert isinstance(evaluate(invalid, for_scheduling=True), NotPublishable)

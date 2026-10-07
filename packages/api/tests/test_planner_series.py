"""QUA-118 Phase 2: `schedule_many` (N accounts) and `schedule_series` (weekly) over the
in-memory repository — one plan, validated whole, written whole (`add_many`), and every
occurrence an independent `calendar_event` afterwards. No DB: the Postgres side
(a real rollback) is in `test_planner_db.py`."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from qualify_api.planner.post_reader import ApprovalStatus, PostOutput, PostSummary
from qualify_api.planner.recurrence import SERIES_CAP
from qualify_api.planner.repository import MemoryPlannerRepository, NewEvent
from qualify_api.planner.rules import ExecutionDecision, decide_execution
from qualify_api.planner.service import (
    DuplicateEvent,
    InactiveConnection,
    IncompatibleConnection,
    InvalidSchedule,
    InvalidSeries,
    PlannerService,
    PostNotSchedulable,
    UnknownOutput,
)

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
TENANT = uuid4()
BRAND = uuid4()
USER = uuid4()
CONN = uuid4()
CONN2 = uuid4()
DEGRADED_CONN = uuid4()
TIKTOK_CONN = uuid4()
CARACAS = "America/Caracas"
NEW_YORK = "America/New_York"


class FakePosts:
    def __init__(self, *posts: PostSummary) -> None:
        self.by_id = {p.post_id: p for p in posts}

    def get(self, *, tenant_id: UUID, post_id: UUID) -> PostSummary | None:
        return self.by_id.get(post_id) if tenant_id == TENANT else None

    def get_many(self, *, tenant_id: UUID, post_ids: Iterable[UUID]) -> dict[UUID, PostSummary]:
        return {p: self.by_id[p] for p in post_ids if tenant_id == TENANT and p in self.by_id}

    def list_schedulable(self, *, tenant_id: UUID, brand_id: UUID) -> list[PostSummary]:
        return [p for p in self.by_id.values() if p.approval.is_schedulable]


class FakeConnections:
    _STATUS = {CONN: "active", CONN2: "active", DEGRADED_CONN: "degraded", TIKTOK_CONN: "active"}
    _PLATFORM = {CONN: "instagram", CONN2: "instagram", DEGRADED_CONN: "instagram"}

    def status(self, *, tenant_id: UUID, connection_id: UUID) -> str | None:
        return self._STATUS.get(connection_id) if tenant_id == TENANT else None

    def platform(self, *, tenant_id: UUID, connection_id: UUID) -> str | None:
        if tenant_id != TENANT:
            return None
        return self._PLATFORM.get(connection_id, "tiktok" if connection_id == TIKTOK_CONN else None)


class ExplodingRepository(MemoryPlannerRepository):
    """Fails inside `add_many` after building the batch — what a constraint or a lost
    connection does in Postgres — so the service's "all or nothing" can be observed."""

    def add_many(self, news: Sequence[NewEvent]) -> list:
        raise RuntimeError("the database went away mid-batch")


def _post(approval: ApprovalStatus = ApprovalStatus.APPROVED, **kw: object) -> PostSummary:
    kw.setdefault("is_publishable", approval is ApprovalStatus.APPROVED)
    return PostSummary(post_id=uuid4(), brand_id=BRAND, title="Promo", approval=approval, **kw)  # type: ignore[arg-type]


def _service(*posts: PostSummary, repo: MemoryPlannerRepository | None = None) -> PlannerService:
    return PlannerService(
        repository=repo or MemoryPlannerRepository(),
        posts=FakePosts(*posts),
        connections=FakeConnections(),
        clock=lambda: NOW,
    )


def _series(svc: PlannerService, post: PostSummary, **kw: object):
    params: dict[str, object] = {
        "tenant_id": TENANT,
        "brand_id": BRAND,
        "post_id": post.post_id,
        "connection_ids": [CONN],
        "first_day": date(2026, 10, 12),  # a Monday, in the future
        "at": time(10, 0),
        "scheduled_tz": CARACAS,
        "user_id": USER,
        "count": 3,
    }
    params.update(kw)
    return svc.schedule_series(**params)  # type: ignore[arg-type]


def _many(svc: PlannerService, post: PostSummary, **kw: object):
    params: dict[str, object] = {
        "tenant_id": TENANT,
        "brand_id": BRAND,
        "post_id": post.post_id,
        "connection_ids": [CONN, CONN2],
        "scheduled_at": NOW + timedelta(days=2),
        "scheduled_tz": CARACAS,
        "user_id": USER,
    }
    params.update(kw)
    return svc.schedule_many(**params)  # type: ignore[arg-type]


def _rows(svc: PlannerService, post: PostSummary):
    return svc._repo.list_for_post(tenant_id=TENANT, post_id=post.post_id)


# --- schedule_series: the occurrences -----------------------------------------------


def test_a_weekly_series_creates_one_independent_event_per_occurrence() -> None:
    post = _post()
    svc = _service(post)
    events = _series(svc, post, count=3)
    assert len(events) == 3 and len({e.id for e in events}) == 3
    assert [e.status for e in events] == ["scheduled"] * 3
    assert [e.revision for e in events] == [1, 1, 1]
    assert {e.connection_id for e in events} == {CONN}
    assert all(e.scheduled_tz == CARACAS and e.output_port is None for e in events)
    caracas = ZoneInfo(CARACAS)
    locals_ = [e.scheduled_at.astimezone(caracas) for e in events]
    assert [d.date() for d in locals_] == [
        date(2026, 10, 12),
        date(2026, 10, 19),
        date(2026, 10, 26),
    ]
    assert {d.time() for d in locals_} == {time(10, 0)}  # same wall-clock time every week
    assert [e.scheduled_at - events[0].scheduled_at for e in events] == [
        timedelta(0),
        timedelta(days=7),
        timedelta(days=14),
    ]


def test_a_series_by_end_date_stops_on_or_before_it() -> None:
    post = _post()
    svc = _service(post)
    events = _series(svc, post, count=None, until=date(2026, 10, 28))
    assert [e.scheduled_at.astimezone(ZoneInfo(CARACAS)).date() for e in events] == [
        date(2026, 10, 12),
        date(2026, 10, 19),
        date(2026, 10, 26),
    ]


def test_the_same_wall_clock_time_survives_a_dst_change() -> None:
    """New York falls back on 2026-11-01: 10:00 local is 14:00 UTC before and 15:00 UTC
    after. The series keeps the local hour, not the UTC offset."""
    post = _post()
    svc = _service(post)
    events = _series(
        svc, post, first_day=date(2026, 10, 26), count=2, scheduled_tz=NEW_YORK, at=time(10, 0)
    )
    assert [e.scheduled_at.hour for e in events] == [14, 15]
    ny = ZoneInfo(NEW_YORK)
    assert {e.scheduled_at.astimezone(ny).time() for e in events} == {time(10, 0)}


def test_a_wall_clock_time_that_does_not_exist_on_one_day_refuses_the_whole_series() -> None:
    """New York springs forward on 2027-03-14: 02:30 does not exist that day. The
    first occurrence (03-07) is fine, the second is not — nothing is created."""
    post = _post()
    svc = _service(post)
    with pytest.raises(InvalidSchedule):
        _series(
            svc, post, first_day=date(2027, 3, 7), count=2, scheduled_tz=NEW_YORK, at=time(2, 30)
        )
    assert _rows(svc, post) == []


def test_the_cap_is_enforced_and_creates_nothing() -> None:
    post = _post()
    svc = _service(post)
    with pytest.raises(InvalidSeries) as excinfo:
        _series(svc, post, count=SERIES_CAP + 1)
    assert excinfo.value.code == "too_many"
    assert _rows(svc, post) == []
    assert len(_series(svc, post, count=SERIES_CAP)) == SERIES_CAP


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"count": None}, "end_required"),
        ({"count": 2, "until": date(2026, 11, 2)}, "end_required"),
        ({"count": 0}, "count_too_small"),
        ({"count": None, "until": date(2026, 10, 5)}, "until_before_first"),
    ],
)
def test_an_ill_formed_series_is_refused_with_its_code(kw: dict, code: str) -> None:
    post = _post()
    svc = _service(post)
    with pytest.raises(InvalidSeries) as excinfo:
        _series(svc, post, **kw)
    assert excinfo.value.code == code
    assert _rows(svc, post) == []


def test_a_series_whose_first_occurrence_is_in_the_past_is_refused_whole() -> None:
    post = _post()
    svc = _service(post)
    with pytest.raises(InvalidSchedule):
        # 07:00 Caracas on NOW's day = 11:00 UTC, an hour before NOW.
        _series(svc, post, first_day=date(2026, 10, 5), at=time(7, 0), count=3)
    assert _rows(svc, post) == []


# --- all or nothing -------------------------------------------------------------------


def test_a_failure_inside_the_write_leaves_no_occurrence_behind() -> None:
    post = _post()
    repo = ExplodingRepository()
    svc = _service(post, repo=repo)
    with pytest.raises(RuntimeError):
        _series(svc, post, count=3)
    assert repo.list_for_post(tenant_id=TENANT, post_id=post.post_id) == []
    with pytest.raises(RuntimeError):
        _many(svc, post)
    assert repo.list_for_post(tenant_id=TENANT, post_id=post.post_id) == []


def test_a_duplicate_occurrence_refuses_the_whole_series() -> None:
    """The second Monday is already planned on that account: nothing of the new series
    is created, not even the free Mondays (A4: the set is atomic)."""
    post = _post()
    svc = _service(post)
    taken = svc.schedule(
        tenant_id=TENANT,
        brand_id=BRAND,
        post_id=post.post_id,
        connection_id=CONN,
        scheduled_at=datetime(2026, 10, 19, 10, 0, tzinfo=ZoneInfo(CARACAS)),
        scheduled_tz=CARACAS,
        user_id=USER,
    )
    with pytest.raises(DuplicateEvent):
        _series(svc, post, count=3)
    assert [e.id for e in _rows(svc, post)] == [taken.id]
    # Planning the same series twice is the same refusal.
    _series(svc, post, first_day=date(2026, 11, 9), count=2)
    with pytest.raises(DuplicateEvent):
        _series(svc, post, first_day=date(2026, 11, 9), count=2)
    assert len(_rows(svc, post)) == 3


def test_a_post_that_is_not_schedulable_gets_no_series() -> None:
    pending = _post(ApprovalStatus.PENDING, is_publishable=True)
    unready = _post(is_publishable=False, unpublishable_reason="Falta el formato.")
    svc = _service(pending, unready)
    with pytest.raises(PostNotSchedulable):
        _series(svc, pending)
    with pytest.raises(PostNotSchedulable) as excinfo:
        _series(svc, unready)
    assert excinfo.value.reason == "Falta el formato."
    assert _rows(svc, pending) == [] and _rows(svc, unready) == []


def test_an_inactive_or_incompatible_account_refuses_the_whole_plan() -> None:
    post = _post()
    svc = _service(post)
    with pytest.raises(InactiveConnection):
        _series(svc, post, connection_ids=[CONN, DEGRADED_CONN])
    with pytest.raises(IncompatibleConnection):
        _many(svc, post, connection_ids=[CONN, TIKTOK_CONN])
    with pytest.raises(InactiveConnection):
        _many(svc, post, connection_ids=[])
    with pytest.raises(DuplicateEvent):
        _many(svc, post, connection_ids=[CONN, CONN])
    assert _rows(svc, post) == []


# --- independence after creation ----------------------------------------------------


def test_occurrences_never_affect_each_other() -> None:
    post = _post()
    svc = _service(post)
    first, second, third = _series(svc, post, count=3)
    repo = svc._repo
    repo._rows[first.id] = replace(repo._rows[first.id], status="published")
    repo._rows[second.id] = replace(repo._rows[second.id], status="failed")
    moved = svc.reschedule(
        tenant_id=TENANT,
        event_id=third.id,
        scheduled_at=third.scheduled_at + timedelta(hours=2),
        scheduled_tz=CARACAS,
    )
    assert moved.revision == 2 and moved.status == "scheduled"
    assert repo.get(tenant_id=TENANT, event_id=first.id).status == "published"
    assert repo.get(tenant_id=TENANT, event_id=second.id).status == "failed"
    assert repo.get(tenant_id=TENANT, event_id=first.id).revision == 1
    # Each occurrence decides its own execution.
    later = third.scheduled_at + timedelta(hours=3)
    assert (
        decide_execution(status="published", scheduled_at=first.scheduled_at, post=post, now=later)
        is ExecutionDecision.NOT_SCHEDULED
    )
    assert (
        decide_execution(status="scheduled", scheduled_at=moved.scheduled_at, post=post, now=later)
        is ExecutionDecision.READY
    )


def test_cancelling_one_occurrence_leaves_the_others_scheduled() -> None:
    post = _post()
    svc = _service(post)
    first, second, third = _series(svc, post, count=3)
    svc.cancel_and_delete(tenant_id=TENANT, event_id=second.id)
    remaining = _rows(svc, post)
    assert [e.id for e in remaining] == [first.id, third.id]
    assert {e.status for e in remaining} == {"scheduled"}


def test_a_recurrente_post_can_get_a_second_series_while_the_first_is_live() -> None:
    post = _post(reuse_type="recurrente")
    svc = _service(post)
    _series(svc, post, count=2)
    assert [p.post_id for p in svc.list_unscheduled(tenant_id=TENANT, brand_id=BRAND)] == [
        post.post_id
    ]
    _series(svc, post, first_day=date(2026, 10, 14), count=2)  # Wednesdays
    assert len(_rows(svc, post)) == 4


# --- schedule_many: accounts, and series × accounts ---------------------------------


def test_schedule_many_creates_one_event_per_account_at_the_same_instant() -> None:
    post = _post()
    svc = _service(post)
    events = _many(svc, post)
    assert [e.connection_id for e in events] == [CONN, CONN2]
    assert len({e.scheduled_at for e in events}) == 1
    assert len({e.id for e in events}) == 2
    svc.cancel_and_delete(tenant_id=TENANT, event_id=events[0].id)
    assert [e.id for e in _rows(svc, post)] == [events[1].id]


def test_a_series_on_two_accounts_is_occurrences_times_accounts_in_instant_order() -> None:
    post = _post()
    svc = _service(post)
    events = _series(svc, post, connection_ids=[CONN, CONN2], count=3)
    assert len(events) == 6
    assert [e.connection_id for e in events] == [CONN, CONN2] * 3
    instants = [e.scheduled_at for e in events]
    assert instants == sorted(instants)
    assert len(set(instants)) == 3  # the cap counts occurrences, not events


def test_a_package_series_plans_one_output_on_every_occurrence() -> None:
    post = _post(
        outputs=(
            PostOutput(port="reel", media_type="video", is_publishable=True),
            PostOutput(
                port="story", media_type="image", is_publishable=False, unpublishable_reason="R2"
            ),
        )
    )
    svc = _service(post)
    reels = _series(svc, post, count=2, output_port="reel")
    assert {e.output_port for e in reels} == {"reel"}
    with pytest.raises(PostNotSchedulable):
        _series(svc, post, count=2, output_port="story")
    with pytest.raises(UnknownOutput):
        _series(svc, post, count=2, output_port="feed")
    assert len(_rows(svc, post)) == 2

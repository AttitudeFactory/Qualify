"""`PlannerService` against the in-memory repository, a fake `PostReader` and a fake
connection gate (QUA-108). No DB — the Postgres side is `test_planner_db.py`."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from qualify_api.planner.post_reader import ApprovalStatus, PostSummary
from qualify_api.planner.repository import MemoryPlannerRepository
from qualify_api.planner.rules import ExecutionDecision, decide_execution
from qualify_api.planner.service import (
    EventConflict,
    EventNotModifiable,
    InactiveConnection,
    InvalidSchedule,
    InvalidTag,
    PlannerService,
    PostNotSchedulable,
    UnknownEvent,
    UnknownPost,
    UnknownTag,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
TENANT = uuid4()
OTHER_TENANT = uuid4()
BRAND = uuid4()
USER = uuid4()
CONN = uuid4()
DEGRADED_CONN = uuid4()


class FakePosts:
    def __init__(self, *posts: PostSummary, tenant: UUID = TENANT) -> None:
        self.by_id = {p.post_id: p for p in posts}
        self.tenant = tenant

    def get(self, *, tenant_id: UUID, post_id: UUID) -> PostSummary | None:
        return self.by_id.get(post_id) if tenant_id == self.tenant else None

    def get_many(self, *, tenant_id: UUID, post_ids: Iterable[UUID]) -> dict[UUID, PostSummary]:
        return {
            pid: self.by_id[pid]
            for pid in post_ids
            if tenant_id == self.tenant and pid in self.by_id
        }

    def list_schedulable(self, *, tenant_id: UUID, brand_id: UUID) -> list[PostSummary]:
        if tenant_id != self.tenant:
            return []
        return [
            p for p in self.by_id.values() if p.brand_id == brand_id and p.approval.is_schedulable
        ]


class FakeConnections:
    def status(self, *, tenant_id: UUID, connection_id: UUID) -> str | None:
        if tenant_id != TENANT:
            return None
        return {CONN: "active", DEGRADED_CONN: "degraded"}.get(connection_id)


def _post(approval: ApprovalStatus = ApprovalStatus.APPROVED, **kw: object) -> PostSummary:
    return PostSummary(
        post_id=uuid4(),
        brand_id=BRAND,
        title="Promo",
        approval=approval,
        **kw,  # type: ignore[arg-type]
    )


def _service(*posts: PostSummary, clock: list[datetime] | None = None) -> PlannerService:
    now = clock if clock is not None else [NOW]
    return PlannerService(
        repository=MemoryPlannerRepository(),
        posts=FakePosts(*posts),
        connections=FakeConnections(),
        clock=lambda: now[0],
    )


def _schedule(svc: PlannerService, post: PostSummary, *, hours: int = 24, **kw: object):
    params = {
        "tenant_id": TENANT,
        "brand_id": BRAND,
        "post_id": post.post_id,
        "connection_id": CONN,
        "scheduled_at": NOW + timedelta(hours=hours),
        "scheduled_tz": "America/Caracas",
        "user_id": USER,
    }
    params.update(kw)
    return svc.schedule(**params)  # type: ignore[arg-type]


# --- schedule --------------------------------------------------------------


def test_schedule_creates_a_scheduled_event_at_revision_1() -> None:
    post = _post()
    svc = _service(post)
    event = _schedule(svc, post)
    assert event.status == "scheduled"
    assert event.revision == 1
    assert event.post_id == post.post_id
    assert event.connection_id == CONN
    assert event.scheduled_tz == "America/Caracas"
    assert event.scheduled_at == NOW + timedelta(hours=24)


def test_scheduled_at_is_stored_in_utc() -> None:
    post = _post()
    svc = _service(post)
    caracas = ZoneInfo("America/Caracas")
    local = datetime(2026, 9, 28, 15, 0, tzinfo=caracas)
    event = _schedule(svc, post, scheduled_at=local)
    assert event.scheduled_at.utcoffset() == timedelta(0)
    assert event.scheduled_at == local  # same instant
    assert event.scheduled_at.hour == 19


def test_a_pending_post_can_be_planned_approval_gates_execution_not_planning() -> None:
    post = _post(ApprovalStatus.PENDING)
    svc = _service(post)
    assert _schedule(svc, post).status == "scheduled"


@pytest.mark.parametrize("approval", [ApprovalStatus.REJECTED, ApprovalStatus.NOT_READY])
def test_a_rejected_or_unfinished_post_cannot_be_planned(approval: ApprovalStatus) -> None:
    post = _post(approval)
    with pytest.raises(PostNotSchedulable):
        _schedule(_service(post), post)


def test_unknown_or_other_brand_post_is_refused() -> None:
    other_brand = replace(_post(), brand_id=uuid4())
    svc = _service(other_brand)
    with pytest.raises(UnknownPost):
        _schedule(svc, other_brand)
    with pytest.raises(UnknownPost):
        _schedule(svc, _post())  # not known to the reader at all


def test_past_or_naive_instant_is_refused() -> None:
    post = _post()
    svc = _service(post)
    with pytest.raises(InvalidSchedule):
        _schedule(svc, post, hours=-1)
    with pytest.raises(InvalidSchedule):
        _schedule(svc, post, scheduled_at=datetime(2030, 1, 1, 9, 0))


def test_unknown_timezone_is_refused() -> None:
    post = _post()
    with pytest.raises(InvalidSchedule):
        _schedule(_service(post), post, scheduled_tz="Not/AZone")


def test_inactive_or_foreign_connection_is_refused() -> None:
    post = _post()
    svc = _service(post)
    with pytest.raises(InactiveConnection):
        _schedule(svc, post, connection_id=DEGRADED_CONN)
    with pytest.raises(InactiveConnection):
        _schedule(svc, post, connection_id=uuid4())


# --- reschedule / cancel -----------------------------------------------------


def test_reschedule_moves_the_event_and_bumps_revision() -> None:
    post = _post()
    svc = _service(post)
    event = _schedule(svc, post)
    new_at = NOW + timedelta(days=3)
    moved = svc.reschedule(
        tenant_id=TENANT, event_id=event.id, scheduled_at=new_at, scheduled_tz="America/Bogota"
    )
    assert moved.scheduled_at == new_at
    assert moved.scheduled_tz == "America/Bogota"
    assert moved.revision == 2
    assert moved.connection_id == CONN  # unchanged when not given


def test_reschedule_can_change_connection_but_only_to_an_active_one() -> None:
    post = _post()
    svc = _service(post)
    event = _schedule(svc, post)
    with pytest.raises(InactiveConnection):
        svc.reschedule(
            tenant_id=TENANT,
            event_id=event.id,
            scheduled_at=NOW + timedelta(days=2),
            scheduled_tz="America/Caracas",
            connection_id=DEGRADED_CONN,
        )


def test_reschedule_into_the_past_is_refused() -> None:
    post = _post()
    svc = _service(post)
    event = _schedule(svc, post)
    with pytest.raises(InvalidSchedule):
        svc.reschedule(
            tenant_id=TENANT,
            event_id=event.id,
            scheduled_at=NOW - timedelta(minutes=5),
            scheduled_tz="America/Caracas",
        )


def test_cancel_then_no_further_moves() -> None:
    post = _post()
    svc = _service(post)
    event = _schedule(svc, post)
    assert svc.cancel(tenant_id=TENANT, event_id=event.id).status == "cancelled"
    with pytest.raises(EventNotModifiable):
        svc.cancel(tenant_id=TENANT, event_id=event.id)
    with pytest.raises(EventNotModifiable):
        svc.reschedule(
            tenant_id=TENANT,
            event_id=event.id,
            scheduled_at=NOW + timedelta(days=1),
            scheduled_tz="America/Caracas",
        )


def test_stale_revision_is_a_conflict_not_a_silent_overwrite() -> None:
    post = _post()
    repo = MemoryPlannerRepository()
    svc = PlannerService(
        repository=repo, posts=FakePosts(post), connections=FakeConnections(), clock=lambda: NOW
    )
    event = _schedule(svc, post)
    # Another tab moves it first.
    repo.reschedule(
        tenant_id=TENANT,
        event_id=event.id,
        expected_revision=1,
        scheduled_at=NOW + timedelta(days=5),
        scheduled_tz="America/Caracas",
        connection_id=CONN,
    )
    assert (
        repo.reschedule(
            tenant_id=TENANT,
            event_id=event.id,
            expected_revision=1,
            scheduled_at=NOW + timedelta(days=6),
            scheduled_tz="America/Caracas",
            connection_id=CONN,
        )
        is None
    )
    # The service reads the current revision, so a fresh call succeeds.
    assert (
        svc.reschedule(
            tenant_id=TENANT,
            event_id=event.id,
            scheduled_at=NOW + timedelta(days=6),
            scheduled_tz="America/Caracas",
        ).revision
        == 3
    )


def test_event_conflict_is_raised_when_the_compare_and_set_loses() -> None:
    post = _post()

    class LosingRepo(MemoryPlannerRepository):
        def set_status(self, **kw: object) -> None:  # type: ignore[override]
            return None

    svc = PlannerService(
        repository=LosingRepo(),
        posts=FakePosts(post),
        connections=FakeConnections(),
        clock=lambda: NOW,
    )
    event = _schedule(svc, post)
    with pytest.raises(EventConflict):
        svc.cancel(tenant_id=TENANT, event_id=event.id)


# --- tenant isolation --------------------------------------------------------


def test_another_tenant_cannot_see_or_touch_the_event() -> None:
    post = _post()
    svc = _service(post)
    event = _schedule(svc, post)
    with pytest.raises(UnknownEvent):
        svc.get(tenant_id=OTHER_TENANT, event_id=event.id)
    with pytest.raises(UnknownEvent):
        svc.cancel(tenant_id=OTHER_TENANT, event_id=event.id)
    assert (
        svc.list_week(
            tenant_id=OTHER_TENANT, brand_id=BRAND, monday=date(2026, 9, 21), tz_name="UTC"
        )
        == []
    )


# --- queries -----------------------------------------------------------------


def test_list_week_returns_only_that_week_joined_with_the_post() -> None:
    post = _post(caption_excerpt="Hola")
    svc = _service(post)
    this_week = _schedule(svc, post, hours=24)  # 2026-09-26
    _schedule(svc, post, hours=24 * 8)  # next week
    week = svc.list_week(
        tenant_id=TENANT, brand_id=BRAND, monday=date(2026, 9, 21), tz_name="America/Caracas"
    )
    assert [p.event.id for p in week] == [this_week.id]
    assert week[0].post is not None and week[0].post.caption_excerpt == "Hola"


def test_list_week_can_filter_by_connection() -> None:
    post = _post()
    svc = _service(post)
    _schedule(svc, post)
    week = svc.list_week(
        tenant_id=TENANT,
        brand_id=BRAND,
        monday=date(2026, 9, 21),
        tz_name="UTC",
        connection_id=uuid4(),
    )
    assert week == []


def test_unscheduled_lists_schedulable_posts_without_an_active_event() -> None:
    planned, free, rejected = _post(), _post(ApprovalStatus.PENDING), _post(ApprovalStatus.REJECTED)
    svc = _service(planned, free, rejected)
    _schedule(svc, planned)
    unscheduled = {p.post_id for p in svc.list_unscheduled(tenant_id=TENANT, brand_id=BRAND)}
    assert unscheduled == {free.post_id}


def test_cancelling_frees_the_post_back_into_unscheduled() -> None:
    post = _post()
    svc = _service(post)
    event = _schedule(svc, post)
    assert svc.list_unscheduled(tenant_id=TENANT, brand_id=BRAND) == []
    svc.cancel(tenant_id=TENANT, event_id=event.id)
    assert [p.post_id for p in svc.list_unscheduled(tenant_id=TENANT, brand_id=BRAND)] == [
        post.post_id
    ]


def test_overdue_unapproved_event_is_flagged_and_would_not_execute() -> None:
    post = _post(ApprovalStatus.PENDING, is_publishable=True)
    clock = [NOW]
    svc = _service(post, clock=clock)
    event = _schedule(svc, post, hours=1)
    clock[0] = NOW + timedelta(hours=2)  # the instant has passed
    planned = svc.get(tenant_id=TENANT, event_id=event.id)
    assert planned.overdue_unapproved
    assert planned.event.status == "scheduled"  # nothing moved it
    assert (
        decide_execution(
            status=planned.event.status,
            scheduled_at=planned.event.scheduled_at,
            post=planned.post,
            now=clock[0],
        )
        is ExecutionDecision.BLOCKED_NOT_APPROVED
    )


def test_list_due_returns_only_scheduled_events_whose_instant_arrived() -> None:
    post = _post()
    clock = [NOW]
    svc = _service(post, clock=clock)
    soon = _schedule(svc, post, hours=1)
    later = _schedule(svc, post, hours=48)
    cancelled = _schedule(svc, post, hours=1)
    svc.cancel(tenant_id=TENANT, event_id=cancelled.id)
    clock[0] = NOW + timedelta(hours=2)
    due = svc.list_due(tenant_id=TENANT)
    assert [e.id for e in due] == [soon.id]
    assert later.id not in {e.id for e in due}


# --- planning tags ------------------------------------------------------------------


def test_create_tag_trims_dedupes_case_insensitively_and_rotates_colours() -> None:
    svc = _service()
    first = svc.create_tag(tenant_id=TENANT, name="  Campaña   octubre ")
    assert first.name == "Campaña octubre"
    assert svc.create_tag(tenant_id=TENANT, name="campaña OCTUBRE").id == first.id
    second = svc.create_tag(tenant_id=TENANT, name="Lanzamiento")
    assert second.color != first.color
    assert [t.name for t in svc.list_tags(tenant_id=TENANT)] == ["Campaña octubre", "Lanzamiento"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 41])
def test_invalid_tag_names_are_refused(name: str) -> None:
    with pytest.raises(InvalidTag):
        _service().create_tag(tenant_id=TENANT, name=name)


def test_tags_are_per_tenant() -> None:
    svc = _service()
    svc.create_tag(tenant_id=TENANT, name="Promo")
    assert svc.list_tags(tenant_id=OTHER_TENANT) == []


def test_set_event_tags_replaces_the_set_and_does_not_bump_revision() -> None:
    post = _post()
    svc = _service(post)
    event = _schedule(svc, post)
    promo = svc.create_tag(tenant_id=TENANT, name="Promo")
    launch = svc.create_tag(tenant_id=TENANT, name="Lanzamiento")
    svc.set_event_tags(tenant_id=TENANT, event_id=event.id, tag_ids=[promo.id, launch.id])
    planned = svc.get(tenant_id=TENANT, event_id=event.id)
    assert {t.name for t in planned.tags} == {"Promo", "Lanzamiento"}
    assert planned.event.revision == 1
    svc.set_event_tags(tenant_id=TENANT, event_id=event.id, tag_ids=[promo.id])
    assert [t.name for t in svc.get(tenant_id=TENANT, event_id=event.id).tags] == ["Promo"]


def test_another_tenants_tag_cannot_be_attached() -> None:
    post = _post()
    svc = _service(post)
    event = _schedule(svc, post)
    foreign = svc.create_tag(tenant_id=OTHER_TENANT, name="Ajena")
    with pytest.raises(UnknownTag):
        svc.set_event_tags(tenant_id=TENANT, event_id=event.id, tag_ids=[foreign.id])


def test_list_week_filters_by_any_selected_tag() -> None:
    post = _post()
    svc = _service(post)
    tagged = _schedule(svc, post, hours=24)
    untagged = _schedule(svc, post, hours=30)
    promo = svc.create_tag(tenant_id=TENANT, name="Promo")
    svc.set_event_tags(tenant_id=TENANT, event_id=tagged.id, tag_ids=[promo.id])
    week = svc.list_week(
        tenant_id=TENANT,
        brand_id=BRAND,
        monday=date(2026, 9, 21),
        tz_name="America/Caracas",
        tag_ids=frozenset({promo.id}),
    )
    assert [p.event.id for p in week] == [tagged.id]
    assert untagged.id not in {p.event.id for p in week}


def test_create_tag_uses_a_given_palette_colour_and_ignores_an_unknown_one() -> None:
    svc = _service()
    assert svc.create_tag(tenant_id=TENANT, name="Promoción", color="amber").color == "amber"
    assert svc.create_tag(tenant_id=TENANT, name="Otra", color="chartreuse").color in (
        "teal",
        "blue",
        "violet",
        "pink",
        "amber",
        "green",
        "orange",
        "gray",
    )


def test_delete_tag_removes_it_from_every_event_without_touching_the_events() -> None:
    post = _post()
    svc = _service(post)
    event = _schedule(svc, post)
    promo = svc.create_tag(tenant_id=TENANT, name="Promo")
    keep = svc.create_tag(tenant_id=TENANT, name="Marca")
    svc.set_event_tags(tenant_id=TENANT, event_id=event.id, tag_ids=[promo.id, keep.id])
    svc.delete_tag(tenant_id=TENANT, tag_id=promo.id)
    assert [t.name for t in svc.list_tags(tenant_id=TENANT)] == ["Marca"]
    planned = svc.get(tenant_id=TENANT, event_id=event.id)
    assert [t.name for t in planned.tags] == ["Marca"]
    assert planned.event.status == "scheduled" and planned.event.revision == 1


def test_deleting_another_tenants_or_unknown_tag_is_refused() -> None:
    svc = _service()
    foreign = svc.create_tag(tenant_id=OTHER_TENANT, name="Ajena")
    with pytest.raises(UnknownTag):
        svc.delete_tag(tenant_id=TENANT, tag_id=foreign.id)
    assert [t.name for t in svc.list_tags(tenant_id=OTHER_TENANT)] == ["Ajena"]


def test_only_a_cancelled_event_can_be_deleted_and_the_post_returns_to_unscheduled() -> None:
    post = _post()
    svc = _service(post)
    event = _schedule(svc, post)
    with pytest.raises(EventNotModifiable):
        svc.delete(tenant_id=TENANT, event_id=event.id)  # still scheduled
    svc.cancel(tenant_id=TENANT, event_id=event.id)
    svc.delete(tenant_id=TENANT, event_id=event.id)
    with pytest.raises(UnknownEvent):
        svc.get(tenant_id=TENANT, event_id=event.id)
    assert [p.post_id for p in svc.list_unscheduled(tenant_id=TENANT, brand_id=BRAND)] == [
        post.post_id
    ]


def test_another_tenant_cannot_delete_the_event() -> None:
    post = _post()
    svc = _service(post)
    event = _schedule(svc, post)
    svc.cancel(tenant_id=TENANT, event_id=event.id)
    with pytest.raises(UnknownEvent):
        svc.delete(tenant_id=OTHER_TENANT, event_id=event.id)

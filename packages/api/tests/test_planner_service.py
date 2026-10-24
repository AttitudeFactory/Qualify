"""`PlannerService` against the in-memory repository, a fake `PostReader` and a fake
connection gate (QUA-108). No DB — the Postgres side is `test_planner_db.py`."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from qualify_api.planner.post_reader import ApprovalStatus, PostOutput, PostSummary
from qualify_api.planner.repository import MemoryPlannerRepository
from qualify_api.planner.rules import ExecutionDecision, decide_execution
from qualify_api.planner.service import (
    DuplicateEvent,
    EventConflict,
    EventNotModifiable,
    InactiveConnection,
    InvalidSchedule,
    InvalidTag,
    OutputRequired,
    PlannerService,
    PostNotRejected,
    PostNotSchedulable,
    UnknownEvent,
    UnknownOutput,
    UnknownPost,
    UnknownTag,
    UnsupportedDestination,
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

    def platform(self, *, tenant_id: UUID, connection_id: UUID) -> str | None:
        if tenant_id != TENANT:
            return None
        return "instagram" if connection_id in (CONN, DEGRADED_CONN) else None


def _post(approval: ApprovalStatus = ApprovalStatus.APPROVED, **kw: object) -> PostSummary:
    # QUA-118 D1: an approved POST is publishable unless the test says otherwise.
    kw.setdefault("is_publishable", approval is ApprovalStatus.APPROVED)
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


def test_a_pending_post_cannot_be_planned_nothing_incomplete_enters_the_calendar() -> None:
    """QUA-118 D1 (2026-10-05) reverses QUA-108 AC 4 ("approval gates execution, not
    planning"): a POST in review never reaches the calendar."""
    post = _post(ApprovalStatus.PENDING, is_publishable=True)
    svc = _service(post)
    with pytest.raises(PostNotSchedulable) as excinfo:
        _schedule(svc, post)
    assert excinfo.value.reason == "La publicación no está aprobada."
    assert svc._repo.list_for_post(tenant_id=TENANT, post_id=post.post_id) == []


def test_an_approved_but_unpublishable_post_cannot_be_planned_and_says_why() -> None:
    reason = "Falta el formato de algún archivo de la publicación."
    post = _post(is_publishable=False, unpublishable_reason=reason)
    svc = _service(post)
    with pytest.raises(PostNotSchedulable) as excinfo:
        _schedule(svc, post)
    assert excinfo.value.reason == reason  # the evaluator's exact text, for the screen
    assert svc._repo.list_for_post(tenant_id=TENANT, post_id=post.post_id) == []


def test_a_package_output_that_is_not_publishable_cannot_be_planned() -> None:
    reason = "Los archivos de la publicación todavía no están listos para publicar."
    post = _post(
        outputs=(
            PostOutput(port="reel", media_type="video", is_publishable=True),
            PostOutput(
                port="story", media_type="image", is_publishable=False, unpublishable_reason=reason
            ),
        )
    )
    svc = _service(post)
    assert _schedule(svc, post, output_port="reel").status == "scheduled"
    with pytest.raises(PostNotSchedulable) as excinfo:
        _schedule(svc, post, hours=30, output_port="story")
    assert excinfo.value.reason == reason


def test_reschedule_is_refused_once_the_post_is_edited_after_approval() -> None:
    """QUA-118 AC 2: neither assign nor move. The event stays (it reads «Pendiente»)."""
    post = _post()
    svc = _service(post)
    event = _schedule(svc, post)
    svc._posts.by_id[post.post_id] = replace(post, approval=ApprovalStatus.PENDING)
    with pytest.raises(PostNotSchedulable):
        svc.reschedule(
            tenant_id=TENANT,
            event_id=event.id,
            scheduled_at=NOW + timedelta(hours=48),
            scheduled_tz="America/Caracas",
        )
    assert svc.get(tenant_id=TENANT, event_id=event.id).event.revision == 1


def test_cancel_and_delete_removes_the_event_through_the_fsm_and_frees_the_post() -> None:
    """QUA-118 A1: «Cancelar publicación» leaves no visible row — `cancelled` is not one
    of the five visible states. An event that already ran has no cancel edge and stays."""
    post = _post()
    svc = _service(post)
    event = _schedule(svc, post)
    svc.cancel_and_delete(tenant_id=TENANT, event_id=event.id)
    with pytest.raises(UnknownEvent):
        svc.get(tenant_id=TENANT, event_id=event.id)
    assert [p.post_id for p in svc.list_unscheduled(tenant_id=TENANT, brand_id=BRAND)] == [
        post.post_id
    ]
    published = _schedule(svc, post, hours=48)
    svc._repo._rows[published.id] = replace(svc._repo._rows[published.id], status="published")
    with pytest.raises(EventNotModifiable):
        svc.cancel_and_delete(tenant_id=TENANT, event_id=published.id)
    assert svc.get(tenant_id=TENANT, event_id=published.id).event.status == "published"


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
    planned, free = _post(), _post()
    pending, rejected = _post(ApprovalStatus.PENDING), _post(ApprovalStatus.REJECTED)
    svc = _service(planned, free, pending, rejected)
    _schedule(svc, planned)
    unscheduled = {p.post_id for p in svc.list_unscheduled(tenant_id=TENANT, brand_id=BRAND)}
    assert unscheduled == {free.post_id}  # D1: a pending POST is not schedulable any more


def test_a_recurrente_post_stays_unscheduled_while_an_occurrence_is_live_or_published() -> None:
    """QUA-118 A2: a live or published occurrence never blocks the next one."""
    post = _post(reuse_type="recurrente")
    svc = _service(post)
    event = _schedule(svc, post)

    def unscheduled() -> list[UUID]:
        return [p.post_id for p in svc.list_unscheduled(tenant_id=TENANT, brand_id=BRAND)]

    assert unscheduled() == [post.post_id]
    svc._repo._rows[event.id] = replace(svc._repo._rows[event.id], status="published")
    assert unscheduled() == [post.post_id]
    one_shot = _post(reuse_type="promocional")
    svc._posts.by_id[one_shot.post_id] = one_shot
    _schedule(svc, one_shot)
    assert unscheduled() == [post.post_id]


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
    post = _post()
    clock = [NOW]
    svc = _service(post, clock=clock)
    event = _schedule(svc, post, hours=1)
    # Edited after approval (QUA-118 P4): the POST is back in review, the event stays.
    svc._posts.by_id[post.post_id] = replace(post, approval=ApprovalStatus.PENDING)
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
    # Its own instant: the same (POST, connection, instant) as `soon` is a duplicate (MP-11).
    cancelled = _schedule(svc, post, scheduled_at=NOW + timedelta(hours=1, minutes=30))
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


# --- "Quitar del calendario" for a rejected POST (2026-09-30) -----------------------------


def _rejectable_world():
    repo = MemoryPlannerRepository()
    post = _post()  # approved when planned (D1); the tests then change its approval
    posts = FakePosts(post)
    svc = PlannerService(
        repository=repo, posts=posts, connections=FakeConnections(), clock=lambda: NOW
    )
    return repo, posts, post, svc


def test_a_rejected_posts_unpublished_events_are_removed_and_history_is_kept() -> None:
    repo, posts, post, svc = _rejectable_world()
    scheduled = _schedule(svc, post, hours=24)
    cancelled = _schedule(svc, post, hours=48)
    svc.cancel(tenant_id=TENANT, event_id=cancelled.id)
    published = _schedule(svc, post, hours=72)
    repo._rows[published.id] = replace(repo._rows[published.id], status="published")
    other_post = _post()
    posts.by_id[other_post.post_id] = other_post
    unrelated = _schedule(svc, other_post, hours=24)

    posts.by_id[post.post_id] = replace(post, approval=ApprovalStatus.REJECTED)
    removed = svc.remove_rejected_post(tenant_id=TENANT, event_id=scheduled.id)

    assert removed == 2
    assert repo.get(tenant_id=TENANT, event_id=scheduled.id) is None
    assert repo.get(tenant_id=TENANT, event_id=cancelled.id) is None
    assert repo.get(tenant_id=TENANT, event_id=published.id).status == "published"  # history
    assert repo.get(tenant_id=TENANT, event_id=unrelated.id).status == "scheduled"  # other POST


@pytest.mark.parametrize(
    "approval", [ApprovalStatus.PENDING, ApprovalStatus.APPROVED, ApprovalStatus.NOT_READY]
)
def test_only_a_rejected_post_can_be_taken_off_the_calendar(approval: ApprovalStatus) -> None:
    repo, posts, post, svc = _rejectable_world()
    event = _schedule(svc, post)
    posts.by_id[post.post_id] = replace(post, approval=approval)
    with pytest.raises(PostNotRejected):
        svc.remove_rejected_post(tenant_id=TENANT, event_id=event.id)
    assert repo.get(tenant_id=TENANT, event_id=event.id).status == "scheduled"


def test_another_tenant_cannot_remove_the_events() -> None:
    repo, posts, post, svc = _rejectable_world()
    event = _schedule(svc, post)
    posts.by_id[post.post_id] = replace(post, approval=ApprovalStatus.REJECTED)
    with pytest.raises(UnknownEvent):
        svc.remove_rejected_post(tenant_id=OTHER_TENANT, event_id=event.id)
    assert repo.get(tenant_id=TENANT, event_id=event.id).status == "scheduled"


# --- MP-11: one event per output ----------------------------------------------------


def _package_post(**kw: object) -> PostSummary:
    """A template POST with the three `promo_producto` outputs."""
    return _post(
        outputs=(
            PostOutput(port="reel", media_type="video", is_publishable=True),
            PostOutput(port="feed", media_type="image", is_publishable=True),
            PostOutput(port="story", media_type="image", is_publishable=True),
        ),
        **kw,
    )


def _events_of(svc: PlannerService, post: PostSummary) -> set[UUID]:
    return {e.id for e in svc._repo.list_for_post(tenant_id=TENANT, post_id=post.post_id)}


def test_a_package_is_planned_one_event_per_output() -> None:
    post = _package_post()
    svc = _service(post)
    reel = _schedule(svc, post, output_port="reel")
    feed = _schedule(svc, post, output_port="feed")  # same instant, same account: fine
    story = _schedule(svc, post, hours=30, output_port="story")
    assert (reel.output_port, feed.output_port, story.output_port) == ("reel", "feed", "story")
    assert reel.scheduled_at == feed.scheduled_at
    assert _events_of(svc, post) == {reel.id, feed.id, story.id}


def test_a_package_requires_an_output_and_only_its_own() -> None:
    post = _package_post()
    svc = _service(post)
    with pytest.raises(OutputRequired):
        _schedule(svc, post)
    with pytest.raises(UnknownOutput):
        _schedule(svc, post, output_port="poster")
    assert _events_of(svc, post) == set()


def test_a_post_without_outputs_takes_only_none() -> None:
    post = _post()
    svc = _service(post)
    with pytest.raises(UnknownOutput):
        _schedule(svc, post, output_port="reel")
    assert _schedule(svc, post).output_port is None


def test_the_same_output_at_the_same_instant_on_the_same_account_is_a_duplicate() -> None:
    post = _package_post()
    svc = _service(post)
    first = _schedule(svc, post, output_port="reel")
    with pytest.raises(DuplicateEvent):
        _schedule(svc, post, output_port="reel")
    # A cancelled event no longer occupies the slot.
    svc.cancel(tenant_id=TENANT, event_id=first.id)
    again = _schedule(svc, post, output_port="reel")
    assert again.id != first.id
    # Another instant is a second publication of the same output, not a duplicate.
    _schedule(svc, post, hours=48, output_port="reel")


def test_a_whole_post_cannot_be_planned_twice_at_the_same_instant_either() -> None:
    post = _post()
    svc = _service(post)
    _schedule(svc, post)
    with pytest.raises(DuplicateEvent):
        _schedule(svc, post)


def test_a_package_leaves_sin_programar_only_when_every_output_is_planned() -> None:
    post = _package_post()
    svc = _service(post)

    def unscheduled() -> list[UUID]:
        return [p.post_id for p in svc.list_unscheduled(tenant_id=TENANT, brand_id=BRAND)]

    assert unscheduled() == [post.post_id]
    _schedule(svc, post, output_port="reel")
    _schedule(svc, post, output_port="feed")
    assert unscheduled() == [post.post_id]
    story = _schedule(svc, post, hours=30, output_port="story")
    assert unscheduled() == []
    occupied = svc.occupied_outputs(tenant_id=TENANT, brand_id=BRAND)[post.post_id]
    assert set(occupied) == {"reel", "feed", "story"} and occupied["story"].id == story.id
    # Cancelling one output brings the POST back for that output.
    svc.cancel(tenant_id=TENANT, event_id=story.id)
    assert unscheduled() == [post.post_id]
    assert "story" not in svc.occupied_outputs(tenant_id=TENANT, brand_id=BRAND)[post.post_id]


def test_a_reschedule_keeps_the_output() -> None:
    post = _package_post()
    svc = _service(post)
    feed = _schedule(svc, post, output_port="feed")
    moved = svc.reschedule(
        tenant_id=TENANT,
        event_id=feed.id,
        scheduled_at=NOW + timedelta(hours=72),
        scheduled_tz="America/Caracas",
    )
    assert moved.output_port == "feed" and moved.revision == 2


# --- QUA-118 v2: the event's destination ------------------------------------------------


def test_without_a_destination_the_event_keeps_what_the_post_publishes_as() -> None:
    reel = _post(category="reel", media_product_type="REELS", media_types=("VIDEO",))
    assert _schedule(_service(reel), reel).destination == "reel"
    image = _post(category="galeria", media_product_type="IMAGE", media_types=("IMAGE",))
    assert _schedule(_service(image), image).destination == "post"


def test_the_same_video_can_go_out_as_a_reel_and_as_a_historia() -> None:
    video = _post(category="reel", media_product_type="REELS", media_types=("VIDEO",))
    svc = _service(video)
    as_reel = _schedule(svc, video, hours=24, destination="reel")
    as_story = _schedule(svc, video, hours=24, destination="story")  # same instant: allowed
    assert (as_reel.destination, as_story.destination) == ("reel", "story")
    with pytest.raises(DuplicateEvent):
        _schedule(svc, video, hours=24, destination="story")


@pytest.mark.parametrize(
    ("media", "size", "destination", "reason_part"),
    [
        (("VIDEO",), None, "post", ""),  # not offered for a video
        (("IMAGE",), (1080, 1350), "reel", "necesita un video"),
        (("IMAGE",), (1080, 1920), "post", "4:5"),
        (("IMAGE", "VIDEO"), None, "story", "carruseles"),
        (("IMAGE",), None, "nonsense", ""),
    ],
)
def test_an_impossible_destination_creates_nothing(media, size, destination, reason_part) -> None:
    post = _post(category="galeria", media_product_type="IMAGE", media_types=media, image_size=size)
    svc = _service(post)
    with pytest.raises(UnsupportedDestination) as exc:
        _schedule(svc, post, destination=destination)
    assert reason_part in exc.value.reason
    assert svc._repo.list_for_post(tenant_id=TENANT, post_id=post.post_id) == []  # nothing


def test_a_weekly_series_on_several_days_is_created_all_at_once() -> None:
    from datetime import date, time

    post = _post(category="reel", media_product_type="REELS", media_types=("VIDEO",))
    svc = _service(post)
    events = svc.schedule_weekly(
        tenant_id=TENANT,
        brand_id=BRAND,
        post_id=post.post_id,
        connection_ids=[CONN],
        start=date(2026, 10, 6),  # a Tuesday
        weekdays=[1, 3],  # Tuesday and Thursday
        weeks=2,
        at=time(10, 0),
        scheduled_tz="America/Caracas",
        user_id=USER,
        destination="story",
    )
    local = [e.scheduled_at.astimezone(ZoneInfo("America/Caracas")) for e in events]
    assert [d.date().isoformat() for d in local] == [
        "2026-10-06",
        "2026-10-08",
        "2026-10-13",
        "2026-10-15",
    ]
    assert all(d.hour == 10 for d in local) and {e.destination for e in events} == {"story"}


def test_the_plan_goals_are_kept_on_every_event_and_unknown_ones_refused() -> None:
    from qualify_api.planner.service import UnknownGoal

    post = _post(category="reel", media_product_type="REELS", media_types=("VIDEO",))
    svc = _service(post)
    event = _schedule(svc, post, goals=["likes", "views", "likes"])
    assert event.goals == ("likes", "views")  # each once, in order
    with pytest.raises(UnknownGoal):
        _schedule(svc, post, hours=48, goals=["fama"])


def test_an_events_goals_can_be_changed_afterwards() -> None:
    from qualify_api.planner.service import UnknownGoal

    post = _post(category="reel", media_product_type="REELS", media_types=("VIDEO",))
    svc = _service(post)
    event = _schedule(svc, post, goals=["likes"])
    svc.set_event_goals(tenant_id=TENANT, event_id=event.id, goals=["views", "ads", "views"])
    stored = svc._repo.get(tenant_id=TENANT, event_id=event.id)
    assert stored.goals == ("views", "ads") and stored.revision == event.revision
    with pytest.raises(UnknownGoal):
        svc.set_event_goals(tenant_id=TENANT, event_id=event.id, goals=["fama"])

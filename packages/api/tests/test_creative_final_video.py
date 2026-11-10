"""m-24921084 offline: «Tu video completo» — the joined preview's state, the «Aprobar»
rule, the month's seconds and the nearest deadline, on a fake clock. No database.

The database side (the read under RLS, «Juntar otra vez», «Crearla otra vez») is
`test_creative_final_video_db.py`."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

from qualify_creative.adapters.byteplus_ark import DRAFT_TTL_SECONDS

from qualify_api.creative.creations import CreationsBalance
from qualify_api.creative.final_video import (
    Blocker,
    JoinRun,
    JoinState,
    PreviewUse,
    VideoUse,
    final_video_from,
    video_use_from,
)
from qualify_api.creative.fsm import DRAFTING, FAILED

from .test_creative_part_final import _approved, _part, _snapshot
from .test_creative_part_join import TENANT

NOW = 1_800_000_000.0
DAY = 86_400.0
PENDING = JoinRun(pending=True)
DONE = JoinRun(pending=False)


def _parts(*ages_days: float):  # noqa: ANN202
    return tuple(
        _part(i, created_at=NOW - age * DAY, seconds=4 + i)
        for i, age in enumerate(ages_days, start=1)
    )


def _read(snapshot, run=PENDING, **kwargs):  # noqa: ANN001, ANN003, ANN202
    return final_video_from(snapshot, TENANT, now=NOW, run=run, **kwargs)


def test_every_part_with_its_preview_and_the_join_theirs_lets_approve() -> None:
    snapshot = _snapshot(*_parts(1, 2, 3))
    card = _read(snapshot, plan_seconds=(5, 6, 7))
    assert card.state is JoinState.READY
    assert card.can_approve and card.blocker is None
    assert card.video_key == snapshot.joined_object_key
    assert [p.has_preview for p in card.parts] == [True, True, True]


def test_the_header_seconds_are_the_joined_previews_once_ready_else_the_plans() -> None:
    parts = _parts(1, 1)
    block = dict(_snapshot(*parts).joined_block or {}, duration_seconds=9.4)
    ready = _read(_snapshot(*parts, block=block), plan_seconds=(5, 6))
    assert ready.seconds == 9
    waiting = _read(_snapshot(parts[0], block=block), plan_seconds=(5, 6))
    assert waiting.seconds == 11


def test_a_removed_part_is_neither_listed_nor_waited_for() -> None:
    """m-24985192: part 2 of 3 was removed — the card lists 1 and 3 as «1» and «2»,
    approves without it and counts neither its seconds nor its deadline."""
    parts = _parts(1, 8, 2)
    kept = (parts[0], replace(parts[2], status=FAILED))
    snapshot = replace(_snapshot(*kept), planned=3, removed=frozenset({2}))
    card = _read(snapshot, plan_seconds=(5, 7))
    assert card.planned == 2
    assert [(p.index, p.shown) for p in card.parts] == [(1, 1), (3, 2)]
    assert card.failed_parts == (2,)  # the number shown of the plan's part 3
    assert card.expired_parts == ()  # the removed part 2 had expired: not counted
    assert card.blocker is Blocker.PART_FAILED

    ready = replace(_snapshot(parts[0], parts[2]), planned=3, removed=frozenset({2}))
    card = _read(ready, plan_seconds=(5, 7))
    assert card.state is JoinState.READY and card.can_approve


def test_expired_parts_name_the_number_shown_and_keep_the_plans_index() -> None:
    parts = _parts(1, 1, 8)
    snapshot = replace(_snapshot(parts[0], parts[2]), planned=3, removed=frozenset({2}))
    card = _read(snapshot)
    assert card.expired_parts == (2,) and card.expired_part_indexes == (3,)


def test_a_part_without_its_preview_keeps_approve_off() -> None:
    parts = _parts(1, 1)
    snapshot = replace(_snapshot(*parts), planned=3)  # part 3 not made yet
    card = _read(snapshot)
    assert card.state is JoinState.WAITING
    assert not card.can_approve and card.blocker is Blocker.NOT_READY
    assert card.parts[2].draft_id is None and not card.parts[2].has_preview


def test_a_failed_part_blocks_approve_before_anything_else() -> None:
    parts = _parts(1, 1, 1)
    snapshot = _snapshot(parts[0], replace(parts[1], status=FAILED), parts[2])
    card = _read(snapshot)
    assert card.blocker is Blocker.PART_FAILED and not card.can_approve
    assert card.parts[1].failed


def test_an_expired_part_blocks_approve_and_is_listed_for_crearla_otra_vez() -> None:
    snapshot = _snapshot(*_parts(1, 8, 2))
    card = _read(snapshot, recreate_use=PreviewUse(uses=1, left=9, quota=20))
    assert card.blocker is Blocker.EXPIRED and not card.can_approve
    assert card.expired_parts == (2,)
    assert card.recreate_use is not None and card.recreate_use.uses == 1


def test_no_expired_part_drops_the_recreate_use() -> None:
    card = _read(_snapshot(*_parts(1, 2)), recreate_use=PreviewUse(uses=1, left=9, quota=20))
    assert card.expired_parts == () and card.recreate_use is None


def test_a_needs_redo_part_blocks_approve() -> None:
    from qualify_api.creative.final_video import blocker_for

    card = _read(_snapshot(*_parts(1, 1)))
    redo = (card.parts[0], replace(card.parts[1], needs_redo=True))
    assert blocker_for(card.state, redo, None) is Blocker.NEEDS_REDO


def test_the_deadline_is_the_nearest_of_the_parts() -> None:
    card = _read(_snapshot(*_parts(1, 5, 3)))
    oldest = NOW - 5 * DAY
    assert card.expires_at == datetime.fromtimestamp(oldest + DRAFT_TTL_SECONDS, UTC)


def test_an_expired_part_does_not_set_the_deadline() -> None:
    card = _read(_snapshot(*_parts(8, 1)))
    assert card.expires_at == datetime.fromtimestamp(NOW - DAY + DRAFT_TTL_SECONDS, UTC)


def test_a_changed_part_rejoins_showing_the_earlier_preview() -> None:
    parts = _parts(1, 1)
    snapshot = _snapshot(*parts)
    changed = replace(snapshot, parts=(parts[0], replace(parts[1], version_id=uuid4())))
    card = _read(changed, run=PENDING)
    assert card.state is JoinState.REJOINING
    assert card.blocker is Blocker.JOINING and not card.can_approve
    assert card.video_key == snapshot.joined_object_key


def test_the_first_join_on_its_way_is_joining() -> None:
    snapshot = replace(
        _snapshot(*_parts(1, 1)), joined_fingerprint=None, joined_block=None, joined_object_key=None
    )
    card = _read(snapshot, run=PENDING)
    assert card.state is JoinState.JOINING and card.blocker is Blocker.JOINING


def test_a_join_run_done_without_a_joined_preview_failed() -> None:
    snapshot = replace(_snapshot(*_parts(1, 1)), joined_fingerprint="other")
    for run in (DONE, None):
        card = _read(snapshot, run=run)
        assert card.state is JoinState.FAILED
        assert card.blocker is Blocker.JOIN_FAILED and not card.can_approve


def test_a_new_parent_text_is_a_rejoin_not_an_approvable_preview() -> None:
    snapshot = replace(_snapshot(*_parts(1, 1)), revision=2)
    card = _read(snapshot)
    assert card.state is JoinState.REJOINING and not card.can_approve


def test_an_approved_video_shows_no_approve_nor_deadline() -> None:
    card = _read(_approved(_snapshot(*_parts(1, 1))))
    assert card.state is JoinState.APPROVED and card.approved
    assert card.blocker is Blocker.APPROVED and not card.can_approve
    assert card.expires_at is None


def test_the_months_seconds_at_approval() -> None:
    balance = CreationsBalance(
        quota=30,
        used=0,
        weights_version="v3",
        video_quota=40,
        videos_used=10,
        video_in_seconds=True,
        renews_on=date(2026, 12, 1),
    )
    use = video_use_from(15, balance)
    assert (use.uses, use.quota, use.left, use.after) == (15, 40, 30, 15)
    assert not use.short and use.in_seconds and use.renews_on == date(2026, 12, 1)
    assert VideoUse(uses=31, quota=40, left=30).short
    assert not VideoUse(uses=31, quota=40, left=30, unlimited=True).short
    card = _read(_snapshot(*_parts(1)), video_use=use)
    assert card.video_use == use


def test_a_part_being_made_again_has_not_expired() -> None:
    parts = _parts(1, 8)
    card = _read(_snapshot(parts[0], replace(parts[1], status=DRAFTING)))
    assert card.expired_parts == () and card.blocker is Blocker.NOT_READY
    assert card.state is JoinState.WAITING


def _extend(part, created_at: float):  # noqa: ANN001, ANN202
    params = dict(part.params)
    params["part"] = {**params["part"], "mode": "extend"}
    params["draft"] = {**params["draft"], "created_at": created_at}
    return replace(part, params=params)


def test_an_extend_part_older_than_its_previous_must_be_redone() -> None:
    first, second = _parts(1, 2)  # part 1 made a day ago
    stale = _extend(second, NOW - 2 * DAY)  # made before part 1's current vista previa
    card = _read(_snapshot(first, stale), run=PENDING)
    assert [p.needs_redo for p in card.parts] == [False, True]
    assert card.blocker is Blocker.NEEDS_REDO and not card.can_approve
    assert card.redo_parts == (2,)
    fresh = _extend(second, NOW - 0.5 * DAY)  # made after part 1
    assert not _read(_snapshot(first, fresh)).parts[1].needs_redo
    # a plain `reference` part never needs redoing for being older
    assert not _read(_snapshot(first, second)).parts[1].needs_redo


def test_an_extend_part_waits_for_a_previous_without_preview() -> None:
    first, second = _parts(1, 2)
    card = _read(_snapshot(replace(first, status=FAILED), _extend(second, NOW - 2 * DAY)))
    assert not card.parts[1].needs_redo and card.blocker is Blocker.PART_FAILED


def test_a_purged_video_reads_purged_not_waiting_forever() -> None:
    parts = _parts(1, 1)
    for snapshot, purged in (
        (_snapshot(parts[0], replace(parts[1], purged=True)), False),
        (_snapshot(*parts), True),
    ):
        card = _read(snapshot, purged=purged, recreate_use=PreviewUse(uses=1, left=9, quota=20))
        assert card.state is JoinState.PURGED and card.blocker is Blocker.PURGED
        assert card.video_key is None and card.expires_at is None
        assert card.expired_parts == () and card.recreate_use is None


def test_a_run_of_another_revision_counts_as_pending_not_failed() -> None:
    snapshot = replace(_snapshot(*_parts(1, 1)), joined_fingerprint="other")
    assert _read(snapshot, run=JoinRun(pending=False, revision=0)).state is JoinState.REJOINING
    assert _read(snapshot, run=JoinRun(pending=False, revision=1)).state is JoinState.FAILED

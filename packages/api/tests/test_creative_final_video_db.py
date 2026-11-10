"""m-24921084 against Postgres: «Tu video completo» read under RLS, «Juntar otra vez» and
«Crearla otra vez» (only the expired parts, all or nothing on the month's vistas previas).

The real `ContentService`, `PostgresCreationsLedger`, `DbPartJoins`, the worker's
`PipelinePreparation` and RLS (the `world` of VE-10b: a parent with 3 parts and their
joined preview); the producer is a fake and the encoder a recording stand-in."""

from __future__ import annotations

import time
from uuid import UUID, uuid4

import pytest
from qualify_creative.adapters.byteplus_ark import DRAFT_TTL_SECONDS
from qualify_creative.creations import CreationPrice
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative.creations import NotEnoughCreations, PostgresCreationsLedger
from qualify_api.creative.final_video import (
    Blocker,
    FinalVideoReader,
    JoinState,
    RecreateRefused,
    rejoin,
)
from qualify_api.creative.parts import PartChanges

from . import test_creative_parts_db as parts_db
from .test_creative_part_final_db import (  # noqa: F401 — `world` is a fixture
    SECONDS,
    _approve,
    _scalar,
    _seconds_left,
    _worker_pass,
    world,
)

pytestmark = pytest.mark.db

DAY = 86_400


def _read(world, now: float | None = None):  # noqa: ANN001, ANN202, F811
    service, *_, tenant, _, _, parent, _ = world
    clock = time.time if now is None else (lambda: now)
    return FinalVideoReader(service, clock=clock).read(tenant_id=tenant, parent_id=parent)


def _age(tenant: UUID, child: UUID, days: float) -> None:
    """Make `child`'s vista previa `days` old (its draft block's `created_at`)."""
    with tenant_session(tenant) as session:
        session.execute(
            text("""
            UPDATE image_assets a SET params = jsonb_set(a.params, '{draft,created_at}',
                to_jsonb(CAST(:at AS double precision)))
            FROM content_drafts d
            WHERE d.id = a.draft_id AND a.draft_id = :c AND a.version_id = d.active_version_id
            """),
            {"c": child, "at": time.time() - days * DAY},
        )


def _revision(tenant: UUID, draft: UUID) -> int:
    return int(_scalar(tenant, "SELECT revision FROM content_drafts WHERE id=:d", d=draft))


def _previews_left(brand: UUID, tenant: UUID) -> int:
    return PostgresCreationsLedger().balance(tenant_id=tenant, brand_id=brand).previews_left


def test_a_joined_preview_of_ready_parts_is_approvable_with_its_seconds_db(world) -> None:  # noqa: ANN001, F811
    _, _, _, tenant, brand, _, parent, ids = world
    card = _read(world)
    assert card is not None and card.state is JoinState.READY
    assert card.can_approve and card.blocker is None and card.planned == 3
    assert card.video_key is not None and card.video_key.startswith(f"t/{tenant}/")
    assert card.video_use is not None
    left = _seconds_left(brand, tenant)
    assert (card.video_use.uses, card.video_use.left) == (sum(SECONDS), left)
    assert card.expires_at is not None
    # the nearest deadline is at most 7 days away
    assert card.expires_at.timestamp() <= time.time() + DRAFT_TTL_SECONDS

    # what the card announced is exactly what approving charges
    _approve(world)
    assert _seconds_left(brand, tenant) == left - card.video_use.uses
    approved = _read(world)
    assert approved.state is JoinState.APPROVED and approved.blocker is Blocker.APPROVED
    assert approved.video_use is not None and approved.video_use.uses == 0
    assert approved.expires_at is None


def test_another_business_reads_nothing_and_rejoins_nothing_db(world, monkeypatch) -> None:  # noqa: ANN001, F811
    service, *_, tenant, _, _, parent, _ = world
    other, _, _ = parts_db._business(monkeypatch)
    assert FinalVideoReader(service).read(tenant_id=other, parent_id=parent) is None
    assert rejoin(tenant_id=other, parent_id=parent) is False
    with pytest.raises(RecreateRefused):
        FinalVideoReader(service).recreate_expired_parts(
            tenant_id=other, parent_id=parent, user_id=world[5]
        )
    assert _read(world).state is JoinState.READY


def test_a_changed_part_rejoins_then_is_ready_again_db(world) -> None:  # noqa: ANN001, F811
    service, parts, _, tenant, _, user, parent, ids = world
    shown = _read(world).video_key
    parts.regenerate_part(
        tenant_id=tenant,
        parent_id=parent,
        part_index=2,
        changes=PartChanges(description="Papas recién fritas."),
        user_id=user,
    )
    card = _read(world)
    assert card.state is JoinState.WAITING and card.blocker is Blocker.NOT_READY
    service.run_generation(tenant_id=tenant, draft_id=ids[1])
    card = _read(world)
    assert card.state is JoinState.REJOINING and not card.can_approve
    assert card.video_key == shown  # the earlier joined preview is still shown
    _worker_pass(service, tenant)
    card = _read(world)
    assert card.state is JoinState.READY and card.can_approve and card.video_key != shown


def test_a_join_that_could_not_be_made_is_joined_again_on_request_db(world) -> None:  # noqa: ANN001, F811
    service, _, _, tenant, brand, _, parent, _ = world
    left = _seconds_left(brand, tenant)
    with tenant_session(tenant) as session:
        # as when the parts could not be decoded: the run is done, the join is not theirs
        session.execute(
            text("""
            UPDATE image_assets SET params = jsonb_set(params, '{draft,fingerprint}', '"lost"')
            WHERE draft_id = :p AND params->'draft'->>'finish' = 'join'
            """),
            {"p": parent},
        )
        session.execute(
            text("""
            UPDATE creative_pipeline_runs SET prepared_version = dirty_version,
                lease_token = NULL, lease_until = NULL
            WHERE draft_id = :p AND phase = 'join'
            """),
            {"p": parent},
        )
    card = _read(world)
    assert card.state is JoinState.FAILED and card.blocker is Blocker.JOIN_FAILED
    assert rejoin(tenant_id=tenant, parent_id=parent) is True
    assert _read(world).state is JoinState.REJOINING
    _worker_pass(service, tenant)
    assert _read(world).state is JoinState.READY
    assert _seconds_left(brand, tenant) == left  # joining again charges nothing


def test_an_approved_video_is_not_joined_again_db(world) -> None:  # noqa: ANN001, F811
    _, _, _, tenant, _, _, parent, _ = world
    _approve(world)
    assert rejoin(tenant_id=tenant, parent_id=parent) is False


def test_an_expired_part_blocks_approve_and_only_it_is_made_again_db(world) -> None:  # noqa: ANN001, F811
    service, _, _, tenant, brand, user, parent, ids = world
    _age(tenant, ids[1], 8)
    _age(tenant, ids[2], 3)
    card = _read(world)
    assert card.blocker is Blocker.EXPIRED and not card.can_approve
    assert card.expired_parts == (2,)
    assert card.recreate_use is not None and card.recreate_use.uses == 1
    # the nearest deadline is part 3's (part 2 already expired)
    assert abs(card.expires_at.timestamp() - (time.time() - 3 * DAY + DRAFT_TTL_SECONDS)) < 60
    reader = FinalVideoReader(service)
    revisions = [_revision(tenant, c) for c in ids]
    previews = _previews_left(brand, tenant)

    # a part that has not expired is never made again by this button
    with pytest.raises(RecreateRefused):
        reader.recreate_expired_parts(
            tenant_id=tenant, parent_id=parent, user_id=user, part_indexes=[2, 3]
        )
    assert [_revision(tenant, c) for c in ids] == revisions
    assert _previews_left(brand, tenant) == previews

    made = reader.recreate_expired_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    assert made == (2,)
    assert [_revision(tenant, c) for c in ids] == [
        revisions[0],
        revisions[1] + 1,
        revisions[2],
    ]
    assert _previews_left(brand, tenant) == previews - 1

    # in the interval (part 2 being made again, still pointing at its old file): it is
    # not «vencida», and a second tap is refused — never an InvalidTransition, never
    # charged twice
    assert _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:d", d=ids[1]) == "drafting"
    between = _read(world)
    assert between.expired_parts == () and between.blocker is Blocker.NOT_READY
    with pytest.raises(RecreateRefused):
        reader.recreate_expired_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    assert _revision(tenant, ids[1]) == revisions[1] + 1
    assert _previews_left(brand, tenant) == previews - 1

    service.run_generation(tenant_id=tenant, draft_id=ids[1])
    _worker_pass(service, tenant)
    card = _read(world)
    assert card.expired_parts == () and card.state is JoinState.READY and card.can_approve


def test_recreate_without_enough_previews_makes_nothing_db(world) -> None:  # noqa: ANN001, F811
    service, _, _, tenant, brand, user, parent, ids = world
    _age(tenant, ids[0], 8)
    _age(tenant, ids[2], 9)
    left = _previews_left(brand, tenant)
    PostgresCreationsLedger().charge(
        tenant_id=tenant,
        brand_id=brand,
        draft_id=uuid4(),
        revision=1,
        price=CreationPrice("generated_video", 0, videos=left - 1),
    )
    assert _previews_left(brand, tenant) == 1
    revisions = [_revision(tenant, c) for c in ids]
    with pytest.raises(NotEnoughCreations):
        FinalVideoReader(service).recreate_expired_parts(
            tenant_id=tenant, parent_id=parent, user_id=user
        )
    assert [_revision(tenant, c) for c in ids] == revisions
    assert _previews_left(brand, tenant) == 1


def _charge_rows(tenant: UUID, ids: list[UUID]) -> int:
    return int(
        _scalar(tenant, "SELECT count(*) FROM creation_charges WHERE draft_id = ANY(:i)", i=ids)
    )


def test_one_part_failing_makes_none_and_charges_nothing_db(world, monkeypatch) -> None:  # noqa: ANN001, F811
    from qualify_api.creative.parts import PartsService

    service, _, _, tenant, brand, user, parent, ids = world
    _age(tenant, ids[0], 8)
    _age(tenant, ids[2], 9)
    revisions = [_revision(tenant, c) for c in ids]
    previews = _previews_left(brand, tenant)
    charges = _charge_rows(tenant, ids)
    real = PartsService._change_part
    calls: list[int] = []

    def flaky(self, tenant_id, child, new, part_index, user_id):  # noqa: ANN001, ANN202
        calls.append(part_index)
        if len(calls) == 2:
            raise RuntimeError("the second part could not be made again")
        return real(self, tenant_id, child, new, part_index, user_id)

    monkeypatch.setattr(PartsService, "_change_part", flaky)
    with pytest.raises(RuntimeError):
        FinalVideoReader(service).recreate_expired_parts(
            tenant_id=tenant, parent_id=parent, user_id=user
        )
    assert calls == [1, 3]  # part 1 WAS made again inside the unit… and rolled back
    assert [_revision(tenant, c) for c in ids] == revisions
    assert _previews_left(brand, tenant) == previews
    assert _charge_rows(tenant, ids) == charges
    statuses = [_scalar(tenant, "SELECT status FROM content_drafts WHERE id=:d", d=c) for c in ids]
    assert statuses == ["generated"] * 3

    monkeypatch.setattr(PartsService, "_change_part", real)
    made = FinalVideoReader(service).recreate_expired_parts(
        tenant_id=tenant, parent_id=parent, user_id=user
    )
    assert made == (1, 3)
    assert _previews_left(brand, tenant) == previews - 2


# ---------------------------------------------------------------------------
# «Crearla otra vez» of ONE part (`PartRecovery.recreate_part`): only redo / expired


def _status(tenant: UUID, draft: UUID) -> str:
    return str(_scalar(tenant, "SELECT status FROM content_drafts WHERE id=:d", d=draft))


def _recreate(world, index: int):  # noqa: ANN001, ANN202, F811
    from qualify_api.creative.part_actions import PartRecovery

    _, parts, _, tenant, _, user, parent, _ = world
    return PartRecovery(parts).recreate_part(
        tenant_id=tenant, parent_id=parent, part_index=index, user_id=user
    )


def test_recreate_refuses_a_part_to_review_and_writes_nothing_db(world) -> None:  # noqa: ANN001, F811
    from qualify_api.creative.part_actions import PART_NOT_FAILED_TEXT
    from qualify_api.creative.parts import PartChangeRefused

    _, _, _, tenant, brand, _, parent, ids = world
    revisions, previews = [_revision(tenant, c) for c in ids], _previews_left(brand, tenant)
    for index in (1, 2, 3):
        with pytest.raises(PartChangeRefused, match=PART_NOT_FAILED_TEXT):
            _recreate(world, index)
    assert [_revision(tenant, c) for c in ids] == revisions
    assert _previews_left(brand, tenant) == previews
    assert _status(tenant, parent) == "generated"


def test_recreate_refuses_ready_parts_of_an_approved_video_db(world) -> None:  # noqa: ANN001, F811
    from qualify_api.creative.part_actions import PART_NOT_FAILED_TEXT
    from qualify_api.creative.parts import PartChangeRefused

    _, _, _, tenant, brand, _, parent, ids = world
    _approve(world)
    assert _status(tenant, ids[0]) == "approved"
    revisions, previews = [_revision(tenant, c) for c in ids], _previews_left(brand, tenant)
    seconds = _seconds_left(brand, tenant)
    with pytest.raises(PartChangeRefused, match=PART_NOT_FAILED_TEXT):
        _recreate(world, 1)
    assert [_revision(tenant, c) for c in ids] == revisions
    assert _previews_left(brand, tenant) == previews and _seconds_left(brand, tenant) == seconds
    assert _status(tenant, parent) == "approved"  # never sent back to the gate


def test_recreate_expired_refuses_an_approved_video_db(world) -> None:  # noqa: ANN001, F811
    """Third review (money): an approved video's parts are never made again here."""
    service, _, _, tenant, brand, user, parent, ids = world
    _approve(world)
    _age(tenant, ids[1], 8)
    revisions, previews = [_revision(tenant, c) for c in ids], _previews_left(brand, tenant)
    reader = FinalVideoReader(service)
    for asked in (None, [2]):
        with pytest.raises(RecreateRefused):
            reader.recreate_expired_parts(
                tenant_id=tenant, parent_id=parent, user_id=user, part_indexes=asked
            )
    assert [_revision(tenant, c) for c in ids] == revisions
    assert _previews_left(brand, tenant) == previews
    assert _status(tenant, parent) == "approved"


def test_recreate_expired_refuses_an_approved_part_of_a_video_back_at_the_gate_db(world) -> None:  # noqa: ANN001, F811
    service, parts, _, tenant, brand, user, parent, ids = world
    _approve(world)
    # «Cambiar» part 1: the video goes back to the gate, parts 2 and 3 stay approved
    parts.regenerate_part(
        tenant_id=tenant, parent_id=parent, part_index=1, changes=PartChanges(), user_id=user
    )
    assert _status(tenant, parent) != "approved" and _status(tenant, ids[1]) == "approved"
    _age(tenant, ids[1], 8)
    revisions, previews = [_revision(tenant, c) for c in ids], _previews_left(brand, tenant)
    reader = FinalVideoReader(service)
    for asked in (None, [2]):
        with pytest.raises(RecreateRefused):
            reader.recreate_expired_parts(
                tenant_id=tenant, parent_id=parent, user_id=user, part_indexes=asked
            )
    assert [_revision(tenant, c) for c in ids] == revisions
    assert _previews_left(brand, tenant) == previews
    assert _status(tenant, ids[1]) == "approved"
    assert 2 not in (_read(world).expired_parts or ())


def _as_redo(tenant: UUID, ids: list[UUID]) -> None:
    """Part 3 «Sigue a la anterior», its preview older than part 2's."""
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE content_briefs SET media = jsonb_set(jsonb_set(media, '{part,mode}', "
                "'\"extend\"'), '{clip_reference_mode}', '\"extend\"') "
                "WHERE id = (SELECT brief_id FROM content_drafts WHERE id=:c)"
            ),
            {"c": ids[2]},
        )
    _age(tenant, ids[2], 2)
    _age(tenant, ids[1], 1)


@pytest.mark.parametrize("how", ["expired", "redo"])
def test_recreate_never_takes_an_approved_part_db(world, how: str) -> None:  # noqa: ANN001, F811
    """Second review (money): an approved part whose vista previa expired, or an approved
    «Sigue a la anterior» whose previous part changed, is refused — no charge, and the
    approved video stays approved."""
    from qualify_api.creative.part_actions import PART_NOT_FAILED_TEXT
    from qualify_api.creative.parts import PartChangeRefused

    _, _, _, tenant, brand, _, parent, ids = world
    _approve(world)
    if how == "expired":
        _age(tenant, ids[1], 8)
        index = 2
    else:
        _as_redo(tenant, ids)
        index = 3
    revisions, previews = [_revision(tenant, c) for c in ids], _previews_left(brand, tenant)
    seconds = _seconds_left(brand, tenant)
    with pytest.raises(PartChangeRefused, match=PART_NOT_FAILED_TEXT):
        _recreate(world, index)
    assert [_revision(tenant, c) for c in ids] == revisions
    assert _previews_left(brand, tenant) == previews and _seconds_left(brand, tenant) == seconds
    assert _status(tenant, parent) == "approved"
    assert [_status(tenant, c) for c in ids] == ["approved"] * 3


def test_recreate_makes_an_expired_part_again_charged_db(world) -> None:  # noqa: ANN001, F811
    _, _, _, tenant, brand, _, _parent, ids = world
    _age(tenant, ids[1], 8)
    revision, previews = _revision(tenant, ids[1]), _previews_left(brand, tenant)
    assert _recreate(world, 2) == ids[1]
    assert _revision(tenant, ids[1]) == revision + 1
    assert _previews_left(brand, tenant) == previews - 1


def test_recreate_makes_a_redo_part_again_db(world) -> None:  # noqa: ANN001, F811
    _, _, _, tenant, brand, _, _parent, ids = world
    # part 3 «Sigue a la anterior» and its preview is older than part 2's: «Hay que
    # rehacerla»
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE content_briefs SET media = jsonb_set(jsonb_set(media, '{part,mode}', "
                "'\"extend\"'), '{clip_reference_mode}', '\"extend\"') "
                "WHERE id = (SELECT brief_id FROM content_drafts WHERE id=:c)"
            ),
            {"c": ids[2]},
        )
    _age(tenant, ids[2], 2)
    _age(tenant, ids[1], 1)
    revision, previews = _revision(tenant, ids[2]), _previews_left(brand, tenant)
    assert _recreate(world, 3) == ids[2]
    assert _revision(tenant, ids[2]) == revision + 1
    assert _previews_left(brand, tenant) == previews - 1

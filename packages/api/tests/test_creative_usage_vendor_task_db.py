"""`db`: m-25112161 against Postgres — a usage event names the vendor task it paid for
(`creative_usage_events.vendor_task_id`, 0179), and the same `(tenant, task)` is written
once: a repeat adds neither a row nor spend to `budget_spent_usd`. Events without a task
id are written every time, as before.

Every task id is fresh per test (`uuid4`): the key is unique for the tenant, and the
shared test database outlives a run."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from qualify_api.creative.draft_mode import DRAFT_RENDERING, FINAL_USAGE_DUE
from qualify_api.creative.fsm import DRAFTING
from qualify_api.creative.service import PostgresContentRepository, UsageWrite

from .test_creative_final_db import (
    TENANT_G,
    _budget,
    _budgeted_brand,
    _draft_with_video,
    _raw,
    _usage,
    _usage_rows,
)
from .test_creative_regenerate_db import _drafting_draft

pytestmark = pytest.mark.db


def _task() -> str:
    return f"cgt-{uuid4().hex}"


def _tasked(cost: str, task: str | None) -> UsageWrite:
    return replace(_usage(cost), vendor_task_id=task)


def _settle_failed(
    repo: PostgresContentRepository,
    brand_id: UUID,
    draft_id: UUID,
    asset_id: UUID,
    usage: tuple[UsageWrite, ...],
) -> None:
    repo.settle_final(
        tenant_id=TENANT_G,
        draft_id=draft_id,
        brand_id=brand_id,
        asset_id=asset_id,
        media=None,
        error="No se pudo recodificar.",
        usage=usage,
        spent_usd=sum((u.cost_usd for u in usage), Decimal(0)),
    )


def test_the_same_vendor_task_twice_is_one_event_and_one_spend() -> None:
    repo = PostgresContentRepository()
    brand_id, draft_id, asset_id = _draft_with_video(repo, _budgeted_brand(), TENANT_G)
    spent = _budget(brand_id)
    task = _task()

    for _ in range(2):  # a retried settle of the same paid task
        _settle_failed(repo, brand_id, draft_id, asset_id, (_tasked("2.84", task),))

    (row,) = _usage_rows(draft_id, TENANT_G)
    assert row.vendor_task_id == task and row.cost_usd == Decimal("2.84")
    assert _budget(brand_id) - spent == Decimal("2.84")


def test_a_repeated_checkpoint_adds_only_its_new_task() -> None:
    """`finish_generation` (a DRAFTING checkpoint, recorded as it comes): a task already
    recorded adds nothing; the new task in the same call is written and spent."""
    repo = PostgresContentRepository()
    brand_id = _budgeted_brand()
    draft_id = _drafting_draft(TENANT_G, brand_id)
    spent = _budget(brand_id)
    first, second = _task(), _task()

    def checkpoint(*usage: UsageWrite) -> None:
        repo.finish_generation(
            tenant_id=TENANT_G,
            draft_id=draft_id,
            brand_id=brand_id,
            new_status=DRAFTING,
            failure_reason=None,
            variants=(),
            usage=usage,
            spent_usd=sum((u.cost_usd for u in usage), Decimal(0)),
        )

    checkpoint(_tasked("0.26", first))
    checkpoint(_tasked("0.26", first), _tasked("0.30", second))

    rows = _usage_rows(draft_id, TENANT_G)
    assert sorted((r.vendor_task_id, r.cost_usd) for r in rows) == sorted(
        [(first, Decimal("0.26")), (second, Decimal("0.30"))]
    )
    assert _budget(brand_id) - spent == Decimal("0.56")


def test_events_without_a_vendor_task_are_written_every_time() -> None:
    repo = PostgresContentRepository()
    brand_id, draft_id, asset_id = _draft_with_video(repo, _budgeted_brand(), TENANT_G)
    spent = _budget(brand_id)

    for _ in range(2):
        _settle_failed(repo, brand_id, draft_id, asset_id, (_usage("0.035"),))

    rows = _usage_rows(draft_id, TENANT_G)
    assert [r.vendor_task_id for r in rows] == [None, None]
    assert _budget(brand_id) - spent == Decimal("0.070")


def test_the_same_task_id_in_another_tenant_is_its_own_event() -> None:
    """The key is per tenant: a task id never blocks another tenant's row."""
    from .test_creative_final_db import TENANT_F

    repo = PostgresContentRepository()
    task = _task()
    brand_g, draft_g, asset_g = _draft_with_video(repo, _budgeted_brand(), TENANT_G)
    _settle_failed(repo, brand_g, draft_g, asset_g, (_tasked("1.00", task),))
    brand_f, draft_f, asset_f = _draft_with_video(repo)
    repo.settle_final(
        tenant_id=TENANT_F,
        draft_id=draft_f,
        brand_id=brand_f,
        asset_id=asset_f,
        media=None,
        error="No se pudo recodificar.",
        usage=(_tasked("1.00", task),),
        spent_usd=Decimal("1.00"),
    )
    assert [r.vendor_task_id for r in _usage_rows(draft_g, TENANT_G)] == [task]
    assert [r.vendor_task_id for r in _usage_rows(draft_f, TENANT_F)] == [task]


def test_a_lost_raw_final_is_recorded_once_on_its_own_task_id() -> None:
    """The rare case of m-25111780: raw T1 was kept and marked due, then could not be
    read, so this pass paid T2 (which took the block's mark). T1's spend rides as a held
    row naming T1 and is recorded on that key; T2 as this pass's raw spend. A second
    settle of the same outcome adds nothing."""
    repo = PostgresContentRepository()
    brand_id, draft_id, asset_id = _draft_with_video(repo, _budgeted_brand(), TENANT_G)
    spent = _budget(brand_id)
    t1, t2 = _task(), _task()
    raw = _raw(draft_id, t2, TENANT_G)
    repo.set_video_draft(
        tenant_id=TENANT_G,
        asset_id=asset_id,
        changes={"status": DRAFT_RENDERING, "raw_final": raw, FINAL_USAGE_DUE: t2},
    )

    def settle() -> None:
        repo.settle_final(
            tenant_id=TENANT_G,
            draft_id=draft_id,
            brand_id=brand_id,
            asset_id=asset_id,
            media=None,
            error="No se pudo recodificar.",
            usage=(),
            spent_usd=Decimal("2.84"),
            draft_changes={"raw_final": raw},
            held_usage=(_tasked("2.00", t1),),
            final_task_id=t2,
            raw_usage=(_tasked("2.84", t2),),
        )

    settle()
    settle()

    rows = _usage_rows(draft_id, TENANT_G)
    assert sorted((r.vendor_task_id, r.cost_usd) for r in rows) == sorted(
        [(t1, Decimal("2.00")), (t2, Decimal("2.84"))]
    )
    assert _budget(brand_id) - spent == Decimal("4.84")
    (asset,) = repo.media_for(tenant_id=TENANT_G, draft_id=draft_id)
    assert FINAL_USAGE_DUE not in asset.params["draft"]


def test_a_lost_task_still_marked_is_recorded_once_and_its_mark_cleared() -> None:
    """Review of ff9be91a: T1 was kept and marked due, could not be read, and the write
    that would have put T2 in the block (`on_raw_kept`) never landed — the block still
    names T1, raw and mark. The settle records T1 on its key and T2 as this pass's raw
    spend, and the mark goes with it; a second settle adds nothing to the budget and the
    mark stays gone."""
    repo = PostgresContentRepository()
    brand_id, draft_id, asset_id = _draft_with_video(repo, _budgeted_brand(), TENANT_G)
    spent = _budget(brand_id)
    t1, t2 = _task(), _task()
    repo.set_video_draft(
        tenant_id=TENANT_G,
        asset_id=asset_id,
        changes={
            "status": DRAFT_RENDERING,
            "raw_final": _raw(draft_id, t1, TENANT_G),
            FINAL_USAGE_DUE: t1,
        },
    )
    raw = _raw(draft_id, t2, TENANT_G)

    def settle() -> None:
        repo.settle_final(
            tenant_id=TENANT_G,
            draft_id=draft_id,
            brand_id=brand_id,
            asset_id=asset_id,
            media=None,
            error="No se pudo recodificar.",
            usage=(),
            spent_usd=Decimal("2.84"),
            draft_changes={"raw_final": raw},
            held_usage=(_tasked("2.00", t1),),
            final_task_id=t2,
            raw_usage=(_tasked("2.84", t2),),
        )

    settle()
    (asset,) = repo.media_for(tenant_id=TENANT_G, draft_id=draft_id)
    assert FINAL_USAGE_DUE not in asset.params["draft"]
    assert asset.params["draft"]["raw_final"] == raw
    assert _budget(brand_id) - spent == Decimal("4.84")

    settle()
    (asset,) = repo.media_for(tenant_id=TENANT_G, draft_id=draft_id)
    assert FINAL_USAGE_DUE not in asset.params["draft"]
    assert _budget(brand_id) - spent == Decimal("4.84")
    assert sorted(r.vendor_task_id for r in _usage_rows(draft_id, TENANT_G)) == sorted([t1, t2])


def test_a_lost_task_with_no_new_one_is_recorded_and_its_mark_cleared() -> None:
    """`final_task_id` None: T1 marked due was unreadable and the 1080p ordered in its
    place never came back. T1 is still recorded once on its key, and its mark goes."""
    repo = PostgresContentRepository()
    brand_id, draft_id, asset_id = _draft_with_video(repo, _budgeted_brand(), TENANT_G)
    spent = _budget(brand_id)
    t1 = _task()
    repo.set_video_draft(
        tenant_id=TENANT_G,
        asset_id=asset_id,
        changes={
            "status": DRAFT_RENDERING,
            "raw_final": _raw(draft_id, t1, TENANT_G),
            FINAL_USAGE_DUE: t1,
        },
    )
    for _ in range(2):
        repo.settle_final(
            tenant_id=TENANT_G,
            draft_id=draft_id,
            brand_id=brand_id,
            asset_id=asset_id,
            media=None,
            error="Seedance no entregó el video final.",
            usage=(),
            spent_usd=Decimal("0"),
            held_usage=(_tasked("2.00", t1),),
            final_task_id=None,
        )
        (asset,) = repo.media_for(tenant_id=TENANT_G, draft_id=draft_id)
        assert FINAL_USAGE_DUE not in asset.params["draft"]
    assert [r.vendor_task_id for r in _usage_rows(draft_id, TENANT_G)] == [t1]
    assert _budget(brand_id) - spent == Decimal("2.00")


def test_an_omnihuman_timeout_estimate_and_its_success_cost_once() -> None:
    """Review of ff9be91a: the estimate a timed-out OmniHuman render records and the row
    of that same task's success meet on the key — one event, one spend."""
    repo = PostgresContentRepository()
    brand_id = _budgeted_brand()
    draft_id = _drafting_draft(TENANT_G, brand_id)
    spent = _budget(brand_id)
    task = f"omni-{uuid4().hex}"
    omni = replace(
        _usage("0.90"), provider="omnihuman", model_id="omnihuman-1-5", vendor_task_id=task
    )
    for row in (omni, replace(omni, cost_usd=Decimal("0.88"))):  # estimate, then success
        repo.finish_generation(
            tenant_id=TENANT_G,
            draft_id=draft_id,
            brand_id=brand_id,
            new_status=DRAFTING,
            failure_reason=None,
            variants=(),
            usage=(row,),
            spent_usd=row.cost_usd,
        )
    (event,) = _usage_rows(draft_id, TENANT_G)
    assert event.vendor_task_id == task and event.cost_usd == Decimal("0.90")
    assert _budget(brand_id) - spent == Decimal("0.90")

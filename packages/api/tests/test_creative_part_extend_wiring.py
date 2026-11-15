"""VE-13 (m-24921070): the per-part wiring of «Sigue a la anterior» — a part waiting
in line for the previous one, «Hay que rehacerla» when the previous part shows another
file (a restored older version too), a cut over 10 s made `reference` + `extend`, and a
plan with an `extend` still refused while the switch is off. Offline."""

from __future__ import annotations

from uuid import uuid4

import pytest
from qualify_creative.schemas import VideoPartPlan

from qualify_api.creative.part_extend import EXTEND_OUTPUT_SWITCH, EXTEND_SWITCH
from qualify_api.creative.part_progress import PartFacts, PartState, derive_state
from qualify_api.creative.parts import PartsExtendUnavailable, check_extend_parts

NOW = 1_800_000_000.0


@pytest.fixture
def extend_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    monkeypatch.delenv(EXTEND_OUTPUT_SWITCH, raising=False)


def _facts(index: int, mode: str, *, made: float, source: str, continued: str | None = None):
    return PartFacts(
        index=index,
        mode=mode,
        seconds=5,
        draft_id=uuid4(),
        status="generated",
        preview={"created_at": made},
        has_video=True,
        source_key=source,
        continued_key=continued,
    )


def test_a_restored_older_version_of_the_previous_part_asks_to_redo_it() -> None:
    previous = _facts(1, "reference", made=NOW - 600, source="old")  # restored: older
    part = _facts(2, "extend", made=NOW - 60, source="mine", continued="new")
    row = derive_state(part, previous, now=NOW)
    assert row.state is PartState.REDO and row.changed_part == 1
    same = derive_state(
        _facts(2, "extend", made=NOW - 60, source="mine", continued="old"), previous, now=NOW
    )
    assert same.state is PartState.TO_REVIEW


def test_a_waiting_extend_part_reads_in_line_for_the_previous_one() -> None:
    previous = PartFacts(index=1, mode="reference", seconds=5, draft_id=uuid4(), status="drafting")
    part = PartFacts(
        index=2, mode="extend", seconds=5, draft_id=uuid4(), status="drafting", jobs=("queued",)
    )
    row = derive_state(part, previous, now=NOW)
    assert row.state is PartState.QUEUED and row.waiting_for == 1


# ---------------------------------------------------------------------------
# a cut over 10 s → `reference` + `extend` (VE-13 criterion 3)


def test_a_cut_over_ten_seconds_is_made_reference_then_extend(extend_on: None) -> None:
    from .test_creative_parts import TENANT_ID as T
    from .test_creative_parts import USER_ID, _children, analysis, shot, world

    reel = analysis(shot(0, 0.0, 14.0))
    from qualify_api.creative.parts import plan_from_analysis

    plan = plan_from_analysis(reel)
    assert [p.mode for p in plan] == ["reference", "extend"] or [p.mode for p in plan] == [
        "edit",
        "extend",
    ]
    assert sum(p.seconds for p in plan) == 14
    check_extend_parts(plan, reel)
    parts, _content, repo, _ledger, dispatcher, _router, parent = world(plan=plan)
    parts.create_parts(tenant_id=T, parent_id=parent, user_id=USER_ID, analysis=reel)
    children = sorted(_children(repo, parent), key=lambda c: c.part_index or 0)
    assert len(children) == 2 and len(dispatcher.calls) == 2
    second = repo.get_brief(tenant_id=T, brief_id=children[1].brief_id)
    assert second is not None and second.media.clip_reference_mode == "extend"
    assert second.media.part is not None and second.media.part.mode == "extend"
    assert second.media.clip_video_keys == ()  # its source is found when it is made


def test_switched_off_a_plan_with_an_extend_is_still_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(EXTEND_SWITCH, raising=False)
    from .test_creative_parts import TENANT_ID as T
    from .test_creative_parts import USER_ID, _children, world

    plan = (VideoPartPlan(seconds=5), VideoPartPlan(mode="extend", seconds=5))
    parts, _c, repo, _l, dispatcher, _r, parent = world(plan=plan)
    with pytest.raises(PartsExtendUnavailable):
        parts.create_parts(tenant_id=T, parent_id=parent, user_id=USER_ID)
    assert _children(repo, parent) == [] and dispatcher.calls == []

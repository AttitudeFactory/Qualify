"""The POST's temperature (`ui/thermal.py`): the state → temperature mapping and the
transition table, pinned against the vocabularies they translate.

Pins:
1. Every temperature is a design-system tone, has a word, a lucide glyph and — if it
   animates — a file that exists under `assets/lottie/` and is under the 50 KB budget.
2. Every `DraftStatus` maps to a temperature (never `unknown`); unknown input degrades
   to neutral, never to an alarm.
3. The reuse rule: recurrente → reutilizable, promocional → archivado, else publicado.
4. The calendar event refines an approved POST (date → programado, in flight → en camino,
   failure → fallido) and never promotes an unapproved one.
5. **Every edge of the real creative FSM lands on an allowed temperature transition** —
   the table here cannot drift from `qualify_api.creative.fsm._TRANSITIONS`.
6. The three "moment" animations (freeze, thaw, deliver) sit on the edges the doc says.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from qualify_api.creative import fsm
from qualify_creative.enums import DraftStatus, ReuseType

from .ui import tokens as T
from .ui.thermal import (
    ARCHIVED,
    DELIVER,
    FAILED,
    FREEZE,
    FROZEN,
    HOT,
    IGNITE,
    LIT,
    OFF,
    PUBLISHED,
    PUBLISHING,
    REUSABLE,
    SCALE_ORDER,
    SCHEDULED,
    STEAMING,
    TEMPERATURES,
    THAW,
    TRANSITIONS,
    UNKNOWN,
    allowed_next,
    temperature,
    thermal_for,
    transition,
)

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "lottie"
LOTTIE_BUDGET_BYTES = 50 * 1024


# --- 1. the scale ----------------------------------------------------------------------


def test_every_temperature_is_a_tone_with_word_and_glyph() -> None:
    for key, temp in TEMPERATURES.items():
        assert temp.key == key
        assert temp.tone in T.TONE_SCALE, (key, temp.tone)
        assert temp.tone != "accent", "accent is the action colour, never a state"
        assert temp.label and temp.icon and temp.hint, key


def test_scale_order_covers_every_temperature_but_unknown() -> None:
    assert set(SCALE_ORDER) == set(TEMPERATURES) - {UNKNOWN}
    assert SCALE_ORDER[0] == LIT and SCALE_ORDER[-1] == FAILED


def test_hot_side_is_warn_cold_side_is_info_delivered_is_ok() -> None:
    assert {TEMPERATURES[k].tone for k in (HOT, STEAMING)} == {"warn"}
    assert {TEMPERATURES[k].tone for k in (FROZEN, SCHEDULED, PUBLISHING, REUSABLE)} == {"info"}
    assert TEMPERATURES[PUBLISHED].tone == "ok"
    assert TEMPERATURES[FAILED].tone == "error"
    assert {TEMPERATURES[k].tone for k in (LIT, OFF, ARCHIVED, UNKNOWN)} == {"neutral"}


def test_animated_temperatures_point_at_existing_small_files() -> None:
    animated = {k for k, t in TEMPERATURES.items() if t.lottie}
    assert animated == {HOT, STEAMING, FROZEN, SCHEDULED, PUBLISHED, REUSABLE}
    for key in animated:
        src = TEMPERATURES[key].lottie
        assert src is not None and src.startswith("/lottie/")
        path = ASSETS / src.removeprefix("/lottie/")
        assert path.is_file(), path
        assert path.stat().st_size <= LOTTIE_BUDGET_BYTES, path
        json.loads(path.read_text(encoding="utf-8"))  # well-formed


def test_only_the_cold_states_melt_and_the_melt_file_exists() -> None:
    """The thaw is a file of its own (a reversed autoplay is unreliable in the engine)."""
    assert {k for k, t in TEMPERATURES.items() if t.melt} == {FROZEN, REUSABLE}
    path = ASSETS / TEMPERATURES[FROZEN].melt.removeprefix("/lottie/")
    assert path.is_file() and path.stat().st_size <= LOTTIE_BUDGET_BYTES


def test_only_the_two_waiting_states_loop() -> None:
    assert {k for k, t in TEMPERATURES.items() if t.loop} == {HOT, STEAMING}


def test_failed_never_animates() -> None:
    assert TEMPERATURES[FAILED].lottie is None


# --- 2. mapping from the FSM -----------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (DraftStatus.DRAFTING, HOT),
        (DraftStatus.GENERATED, STEAMING),
        (DraftStatus.REJECTED, OFF),
        (DraftStatus.APPROVED, FROZEN),
        (DraftStatus.STAGED, PUBLISHING),
        (DraftStatus.PUBLISHED, PUBLISHED),
        (DraftStatus.FAILED, FAILED),
    ],
)
def test_every_draft_status_maps(status: DraftStatus, expected: str) -> None:
    assert thermal_for(status.value) == expected


def test_brief_without_a_row_is_lit() -> None:
    assert thermal_for("") == LIT
    assert thermal_for("brief") == LIT


def test_unknown_status_degrades_to_neutral() -> None:
    assert thermal_for("something_new") == UNKNOWN
    assert temperature("something_new").tone == "neutral"
    assert temperature(UNKNOWN).tone == "neutral"


# --- 3. reuse --------------------------------------------------------------------------


def test_reuse_rule_after_publishing() -> None:
    assert thermal_for("published", reuse_type=ReuseType.RECURRENTE.value) == REUSABLE
    assert thermal_for("published", reuse_type=ReuseType.PROMOCIONAL.value) == ARCHIVED
    assert thermal_for("published") == PUBLISHED


def test_recurrente_approved_again_after_a_publish_is_reusable_not_merely_frozen() -> None:
    assert thermal_for("approved", reuse_type="recurrente", publish_count=1) == REUSABLE
    assert thermal_for("approved", reuse_type="recurrente", publish_count=0) == FROZEN
    assert thermal_for("approved", reuse_type="promocional", publish_count=1) == FROZEN


# --- 4. the calendar event -------------------------------------------------------------


def test_event_refines_an_approved_post() -> None:
    assert thermal_for("approved", event_status="scheduled") == SCHEDULED
    assert thermal_for("approved", event_status="publishing") == PUBLISHING
    assert thermal_for("approved", event_status="failed") == FAILED
    assert thermal_for("approved", event_status="cancelled") == FROZEN


def test_event_never_promotes_an_unapproved_post() -> None:
    assert thermal_for("generated", event_status="scheduled") == STEAMING
    assert thermal_for("drafting", event_status="scheduled") == HOT


def test_failure_anywhere_wins() -> None:
    assert thermal_for("drafting", event_status="failed") == FAILED
    assert thermal_for("failed", event_status="scheduled") == FAILED


# --- 5. the transition table vs the real FSM ------------------------------------------


def test_every_fsm_edge_is_an_allowed_temperature_transition() -> None:
    for (current, _trigger), nxt in fsm._TRANSITIONS.items():
        frm, to = thermal_for(current), thermal_for(nxt)
        assert (frm, to) in TRANSITIONS, (current, _trigger, nxt, frm, to)


def test_transition_table_only_names_real_temperatures() -> None:
    for frm, to in TRANSITIONS:
        assert frm in TEMPERATURES and to in TEMPERATURES
        assert frm != UNKNOWN and to != UNKNOWN


def test_unknown_transition_raises() -> None:
    with pytest.raises(KeyError):
        transition(PUBLISHED, HOT)


def test_allowed_next_excludes_self_edges() -> None:
    assert OFF in allowed_next(STEAMING)
    assert STEAMING not in allowed_next(STEAMING)


# --- 6. the moments --------------------------------------------------------------------


def test_the_three_moments_sit_on_the_right_edges() -> None:
    assert transition(STEAMING, FROZEN) == FREEZE
    assert transition(FROZEN, STEAMING) == THAW
    assert transition(PUBLISHING, PUBLISHED) == DELIVER
    assert transition(LIT, HOT) == IGNITE
    assert transition(HOT, FAILED) is None, "an error is never a show"


def test_thaw_is_the_edit_edge_of_the_fsm() -> None:
    """`approved --edit--> generated` is the FSM's descongelar; it must be THAW."""
    assert fsm.apply_transition(fsm.APPROVED, fsm.DraftTrigger.EDIT) == fsm.GENERATED
    assert transition(thermal_for(fsm.APPROVED), thermal_for(fsm.GENERATED)) == THAW

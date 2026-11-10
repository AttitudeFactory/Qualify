"""UI-7 (m-24921082): the «Creando tus partes» panel renders with the design system —
one `aria-live="polite"` region, the bar's `aria-valuetext`, no spinner, mount/unmount
hooks — and the provider runs a service only when a FRESH read still offers the action."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.creative.part_progress import (
    PartAction,
    PartProgress,
    PartProgressRow,
    PartState,
)

from . import part_progress_provider as provider
from .part_progress_panel import part_progress_panel


@pytest.fixture
def js() -> str:
    return str(part_progress_panel("parent").render())


def test_one_polite_live_region(js: str) -> None:
    assert js.count("aria-live") == 1
    assert '"polite"' in js
    assert "announce" in js


def test_the_purged_notice_is_not_a_live_region(js: str) -> None:
    assert 'role:"note"' in js
    assert 'role:"status"' not in js  # no callout with an implicit polite role


def test_the_bar_says_its_value_in_words(js: str) -> None:
    assert js.count("aria-valuetext") == 1
    assert "value_text" in js


def test_no_spinner_and_busy_keeps_the_focus(js: str) -> None:
    assert "Spinner" not in js and "spinner" not in js
    assert "loading" not in js
    assert "aria-disabled" in js or "ariaDisabled" in js


def test_mount_and_unmount_drive_the_poll(js: str) -> None:
    triggers = part_progress_panel("parent").event_triggers
    assert "watch" in str(triggers["on_mount"])
    assert "leave" in str(triggers["on_unmount"])
    assert "has_progress" in js  # nothing renders without parts
    # the session/read error shows even without rows: outside the has_progress branch
    assert js.index("top_error") < js.index("has_progress")


def test_rows_are_a_list_with_their_names(js: str) -> None:
    assert '"list"' in js and '"listitem"' in js
    assert "aria_label" in js


# -- the provider -----------------------------------------------------------------------

PARENT = uuid4()


def fresh(state: PartState, *actions: PartAction) -> PartProgress:
    return PartProgress(
        parent_id=PARENT,
        parts=(
            PartProgressRow(
                index=3,
                total=3,
                draft_id=uuid4(),
                mode="reference",
                seconds=4,
                state=state,
                actions=tuple(actions),
            ),
        ),
    )


@pytest.fixture
def services(monkeypatch: pytest.MonkeyPatch) -> Any:
    calls: list[str] = []
    reads: dict[str, PartProgress | None] = {"now": None}

    class Recovery:
        def __init__(self, parts: Any) -> None:
            pass

        def retry_part(self, **kw: Any) -> UUID:
            calls.append("retry_part")
            return uuid4()

        def make_part_new(self, **kw: Any) -> UUID:
            calls.append("make_part_new")
            return uuid4()

        def recreate_part(self, **kw: Any) -> UUID:
            calls.append("recreate_part")
            return uuid4()

        def remove_part(self, **kw: Any) -> bool:
            calls.append("remove_part")
            return True

    monkeypatch.setattr(provider, "PartRecovery", Recovery)
    monkeypatch.setattr(provider, "_parts", lambda: None)
    monkeypatch.setattr(provider, "read_part_progress", lambda **_kw: reads["now"])
    return calls, reads


IDS = {"tenant_id": uuid4(), "parent_id": PARENT, "part_index": 3, "user_id": uuid4()}


@pytest.mark.parametrize(
    ("action", "row", "service"),
    [
        ("retry", fresh(PartState.FAILED, PartAction.RETRY), "retry_part"),
        ("make_new", fresh(PartState.ORIGINAL_REFUSED, PartAction.MAKE_NEW), "make_part_new"),
        ("recreate", fresh(PartState.REDO, PartAction.RECREATE), "recreate_part"),
        ("recreate", fresh(PartState.EXPIRED, PartAction.RECREATE), "recreate_part"),
        ("remove", fresh(PartState.FAILED, PartAction.REMOVE), "remove_part"),
    ],
)
def test_each_action_runs_its_service(services: Any, action: str, row: Any, service: str) -> None:
    calls, reads = services
    reads["now"] = row
    provider.run_action(action, **IDS)
    assert calls == [service]


@pytest.mark.parametrize(
    "now",
    [
        # a recreate that a fresh read no longer allows: it would charge a vista previa
        fresh(PartState.TO_REVIEW),
        fresh(PartState.READY),
        fresh(PartState.TO_REVIEW, PartAction.RECREATE),  # offered, but not redo/expired
        None,  # not a video by parts of this business (any more)
    ],
)
def test_a_stale_recreate_never_regenerates(services: Any, now: Any) -> None:
    calls, reads = services
    reads["now"] = now
    with pytest.raises(provider.StaleAction):
        provider.run_action("recreate", **IDS)
    assert calls == []


def test_a_retry_on_a_part_already_queued_never_retries(services: Any) -> None:
    calls, reads = services
    reads["now"] = fresh(PartState.QUEUED)
    with pytest.raises(provider.StaleAction):
        provider.run_action("retry", **IDS)
    assert calls == []


def test_unserved_actions_raise_before_any_read(services: Any) -> None:
    calls, _ = services
    for action in ("change", "nonsense"):
        with pytest.raises(provider.UnservedAction):
            provider.run_action(action, **IDS)
    assert calls == []


def test_a_stale_remove_never_removes(services: Any) -> None:
    calls, reads = services
    for now in (fresh(PartState.QUEUED), fresh(PartState.TO_REVIEW), None):
        reads["now"] = now
        with pytest.raises(provider.StaleAction):
            provider.run_action("remove", **IDS)
    assert calls == []


def test_remove_asks_in_the_row_and_says_it_without_a_second_live_region(js: str) -> None:
    assert "Dejarla" in js and "removed_text" in js
    assert '"group"' in js
    assert js.count("aria-live") == 1


def test_the_fold_controls_rows_that_stay_in_the_page(js: str) -> None:
    assert "aria-expanded" in js or "ariaExpanded" in js
    assert '"part-rows"' in js  # the toggle's aria-controls and the rows' id
    assert "aria-controls" in js or "ariaControls" in js
    assert "rows_open" in js and '"none"' in js  # folded = not displayed, not unmounted

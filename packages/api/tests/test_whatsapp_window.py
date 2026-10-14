"""WA-08 — the 24-hour window policy (`whatsapp/window.py`), pure and boundary-exact."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qualify_api.whatsapp.models import OUTBOX_KINDS
from qualify_api.whatsapp.window import (
    FREE_FORM_KINDS,
    TEMPLATE_ONLY_KINDS,
    WINDOW,
    WindowState,
    WindowStatus,
    is_free_form_allowed,
    window_state,
)

T0 = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


# --- window_state ---------------------------------------------------------------------


def test_no_inbound_ever_means_closed_with_no_closing_instant() -> None:
    state = window_state(None, now=T0)
    assert state == WindowState(WindowStatus.CLOSED, closes_at=None)
    assert not state.is_open


def test_open_right_after_the_inbound_and_says_when_it_closes() -> None:
    state = window_state(T0, now=T0 + timedelta(seconds=1))
    assert state.is_open
    assert state.closes_at == T0 + WINDOW


def test_open_one_second_before_the_boundary() -> None:
    assert window_state(T0, now=T0 + WINDOW - timedelta(seconds=1)).is_open


def test_closed_exactly_at_the_boundary() -> None:
    state = window_state(T0, now=T0 + WINDOW)
    assert state.status is WindowStatus.CLOSED
    assert state.closes_at is None


def test_closed_after_the_boundary() -> None:
    assert not window_state(T0, now=T0 + WINDOW + timedelta(hours=3)).is_open


def test_an_inbound_in_the_future_is_still_open() -> None:
    # Clock skew between Meta's timestamp and ours must not close a window that just opened.
    assert window_state(T0 + timedelta(minutes=2), now=T0).is_open


def test_naive_datetimes_are_taken_as_utc() -> None:
    naive_inbound = datetime(2026, 10, 14, 12, 0)
    assert window_state(naive_inbound, now=T0 + timedelta(hours=1)).is_open
    assert window_state(T0, now=datetime(2026, 10, 15, 12, 0)).status is WindowStatus.CLOSED


# --- is_free_form_allowed ---------------------------------------------------------------


OPEN = WindowState(WindowStatus.OPEN, closes_at=T0 + WINDOW)
CLOSED = WindowState(WindowStatus.CLOSED)


@pytest.mark.parametrize("kind", sorted(FREE_FORM_KINDS))
def test_free_form_kinds_need_an_open_window(kind: str) -> None:
    assert is_free_form_allowed(kind, OPEN)
    assert not is_free_form_allowed(kind, CLOSED)


@pytest.mark.parametrize("kind", sorted(TEMPLATE_ONLY_KINDS))
def test_template_only_kinds_pass_whatever_the_window(kind: str) -> None:
    assert is_free_form_allowed(kind, OPEN)
    assert is_free_form_allowed(kind, CLOSED)


def test_every_outbox_kind_is_classified_exactly_once() -> None:
    # A kind the CHECK admits but this module does not classify would be refused silently.
    assert FREE_FORM_KINDS | TEMPLATE_ONLY_KINDS == set(OUTBOX_KINDS)
    assert not (FREE_FORM_KINDS & TEMPLATE_ONLY_KINDS)


def test_an_unknown_kind_is_refused_even_when_open() -> None:
    assert not is_free_form_allowed("broadcast", OPEN)

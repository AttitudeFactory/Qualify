"""m-24828907: what the screens say about a piece's retention — the detail warning, the
«Contenido eliminado» label and the gallery card badge. Pure view-model functions."""

from __future__ import annotations

import pytest

from .creative_vm import (
    PURGED_TITLE,
    purged_label,
    retention_notice,
    short_date,
)
from .planner_vm import build_post_option, retention_badge

DEADLINE = "2027-01-10T12:00:00+00:00"


def test_short_date_is_day_month_year() -> None:
    assert short_date(DEADLINE) == "10/01/2027"
    assert short_date(None) == "" and short_date("tomorrow") == ""


@pytest.mark.parametrize(
    ("days", "countdown"),
    [(10, "en 10 días"), (2, "en 2 días"), (1, "mañana"), (0, "hoy")],
)
def test_the_warning_names_the_date_and_counts_down(days: int, countdown: str) -> None:
    assert retention_notice("warning", DEADLINE, days) == (
        f"Descarga esta pieza: se elimina el 10/01/2027 ({countdown})."
    )


@pytest.mark.parametrize("state", ["active", "held", "expired", "purged", "not_applicable", ""])
def test_no_warning_outside_the_window(state: str) -> None:
    assert retention_notice(state, DEADLINE, 5) == ""


def test_the_warning_needs_a_date() -> None:
    assert retention_notice("warning", None, 5) == ""
    assert retention_notice("warning", DEADLINE, None) == ""


def test_the_purged_label_carries_the_date_when_known() -> None:
    assert purged_label("2027-04-11T03:00:00+00:00") == f"{PURGED_TITLE} el 11/04/2027"
    assert purged_label(None) == PURGED_TITLE


@pytest.mark.parametrize(
    ("state", "days", "expected"),
    [
        ("warning", 12, ("Se elimina en 12 días", "warn")),
        ("warning", 1, ("Se elimina mañana", "warn")),
        ("warning", 0, ("Se elimina hoy", "warn")),
        ("purged", None, ("Contenido eliminado", "neutral")),
        ("active", 40, ("", "neutral")),
        ("held", 0, ("", "neutral")),
        ("", None, ("", "neutral")),
    ],
)
def test_the_gallery_badge(state: str, days: int | None, expected: tuple[str, str]) -> None:
    assert retention_badge(state, days) == expected


def test_the_gallery_card_carries_the_badge() -> None:
    card = build_post_option(
        post_id="p",
        title="Pieza",
        caption_excerpt="",
        thumbnail_url=None,
        category="galeria",
        approval="approved",
        detail_href="/drafts/p",
        is_publishable=True,
        unpublishable_reason="",
        retention_state="warning",
        purge_days_left=3,
    )
    assert (card.retention_label, card.retention_tone) == ("Se elimina en 3 días", "warn")
    plain = build_post_option(
        post_id="p",
        title="Pieza",
        caption_excerpt="",
        thumbnail_url=None,
        category="galeria",
        approval="approved",
        detail_href="/drafts/p",
        is_publishable=True,
        unpublishable_reason="",
    )
    assert plain.retention_label == ""

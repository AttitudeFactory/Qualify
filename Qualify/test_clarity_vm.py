"""VM-parsing tests for the Clarity screen: the docs' sample payload must flatten into
the headline stats and generic metric tables the page renders. Pure functions, offline."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

from qualify_api.clarity.repository import SnapshotRow

from .clarity_provider import (
    _action_items,
    _friction_cards,
    _headline_stats,
    _metric_table,
    _to_vm,
    _traffic_note,
)

# The documented response shape (learn.microsoft.com, Data Export API), abridged.
DOCS_PAYLOAD = [
    {
        "metricName": "Traffic",
        "information": [
            {
                "totalSessionCount": "9554",
                "totalBotSessionCount": "8369",
                "distantUserCount": "189733",
                "PagesPerSessionPercentage": 1.0931,
                "OS": "Other",
            },
            {
                "totalSessionCount": "291942",
                "totalBotSessionCount": "31076",
                "distantUserCount": "212836",
                "PagesPerSessionPercentage": 2.2609,
                "OS": "Android",
            },
        ],
    },
    {
        "metricName": "ScrollDepth",
        "information": [{"averageScrollDepth": 40.19, "OS": "Android"}],
    },
    {"metricName": "DeadClickCount", "information": []},
]


def test_headline_stats_sum_across_dimension_rows() -> None:
    stats = _headline_stats(DOCS_PAYLOAD)
    assert ["Visitas", "301,496"] in stats
    assert ["Visitas de robots", "39,445"] in stats
    assert ["Personas", "402,569"] in stats


def test_headline_stats_survive_non_numeric_counts() -> None:
    stats = _headline_stats(
        [{"metricName": "Traffic", "information": [{"totalSessionCount": "n/a"}]}]
    )
    assert ["Visitas", "0"] in stats


def test_metric_table_leads_with_dimension_column() -> None:
    table = _metric_table(DOCS_PAYLOAD[0])
    assert table.name == "Visitas"
    # The non-numeric (dimension) column sorts first so each row reads label-first, and
    # every known API key reaches the owner in their words (m-24842999).
    assert table.columns[0] == "Sistema"
    assert set(table.columns) == {
        "Sistema",
        "Visitas",
        "Visitas de robots",
        "Personas",
        "Páginas por visita",
    }
    assert table.rows[0][0] == "Other"
    assert len(table.rows) == 2


# What the live API actually returns with dimension1=URL (measured 2026-08-18):
# friction rows carry Url/subTotal/sessionsCount/sessionsWithMetricPercentage.
FRICTION_PAYLOAD = [
    {
        "metricName": "Traffic",
        "information": [
            {
                "Url": "https://example.com/reservas",
                "distinctUserCount": "40",
                "totalSessionCount": "60",
                "totalBotSessionCount": "5",
            }
        ],
    },
    {
        "metricName": "EngagementTime",
        "information": [
            {"Url": "https://example.com/reservas", "totalTime": "505", "activeTime": "125"}
        ],
    },
    {
        "metricName": "RageClickCount",
        "information": [
            {
                "Url": "https://example.com/reservas",
                "subTotal": "12",
                "sessionsCount": "45",
                "sessionsWithMetricPercentage": 8,
            }
        ],
    },
    {
        "metricName": "DeadClickCount",
        "information": [
            {
                "Url": "https://example.com/menu",
                "subTotal": "2",
                "sessionsCount": "30",
                "sessionsWithMetricPercentage": 3,
            }
        ],
    },
    {
        "metricName": "ScriptErrorCount",
        "information": [
            {
                "Url": "https://example.com/reservas",
                "subTotal": "0",
                "sessionsCount": "45",
                "sessionsWithMetricPercentage": 0,
            }
        ],
    },
]


def test_headline_stats_accept_live_distinct_spelling_and_engagement() -> None:
    stats = _headline_stats(FRICTION_PAYLOAD)
    assert ["Personas", "40"] in stats
    assert ["Tiempo que se quedaron", "2 min 5 s"] in stats


def test_friction_cards_traffic_light_by_volume() -> None:
    cards = {card.label: card for card in _friction_cards(FRICTION_PAYLOAD)}
    # 12 events >= the act-now threshold → "bad", and the affected share is surfaced.
    assert cards["Toques repetidos con enojo"].status == "bad"
    assert cards["Toques repetidos con enojo"].total == "12"
    assert cards["Toques repetidos con enojo"].affected == "8% de las visitas"
    # 2 events under both thresholds → "warn"; 0 events → "ok" with no percentage.
    assert cards["Toques en cosas que no hacen nada"].status == "warn"
    assert cards["Fallas de la página"].status == "ok"
    assert cards["Fallas de la página"].affected == ""


def test_action_items_rank_worst_first_and_skip_zero_rows() -> None:
    actions = _action_items(FRICTION_PAYLOAD)
    assert [action.severity for action in actions] == ["alta", "media"]
    assert actions[0].title == "Toques repetidos con enojo en https://example.com/reservas"
    assert "12 veces en 45 visitas (8% de las visitas)" in actions[0].detail
    # The zero-count ScriptErrorCount row must not produce an actionable.
    assert all("JavaScript" not in action.title for action in actions)


def test_traffic_note_flags_low_sample_windows() -> None:
    assert _traffic_note(FRICTION_PAYLOAD) == ""  # 55 human sessions — fine
    tiny = [
        {
            "metricName": "Traffic",
            "information": [{"totalSessionCount": "3", "totalBotSessionCount": "1"}],
        }
    ]
    assert "Solo hubo 2 visitas de personas" in _traffic_note(tiny)


def test_snapshot_vm_carries_friction_and_actions() -> None:
    snapshot = SnapshotRow(
        id=uuid4(),
        num_of_days=3,
        dimensions=["URL"],
        payload=FRICTION_PAYLOAD,
        fetched_at=datetime(2026, 8, 18, 1, 13, tzinfo=UTC),
    )
    vm = _to_vm(snapshot)
    assert len(vm.friction) == 3
    assert len(vm.actions) == 2
    assert vm.traffic_note == ""


def test_snapshot_vm_drops_empty_metrics_and_labels_the_window() -> None:
    snapshot = SnapshotRow(
        id=uuid4(),
        num_of_days=3,
        dimensions=["OS"],
        payload=DOCS_PAYLOAD,
        fetched_at=datetime(2026, 8, 15, 14, 3, tzinfo=UTC),
    )
    vm = _to_vm(snapshot)
    assert vm.fetched_at == "2026-08-15 14:03 UTC"
    assert vm.window == "últimas 72 h"
    assert vm.dimensions == "Sistema"
    # DeadClickCount had no rows — it must not render an empty card.
    assert [table.name for table in vm.tables] == ["Visitas", "Hasta dónde bajaron"]
    assert len(vm.stats) == 3


def test_owner_copy_has_no_analytics_jargon() -> None:
    """m-24842999: every label, hint, recommendation and message the owner reads speaks
    their words — no English analytics jargon and no internal vocabulary."""
    from . import clarity_provider, clarity_state

    forbidden = ("rage", "scroll", "bot", "javascript", "snapshot", "device", "browser")
    # «sesiones» (analytics sessions) is jargon; «tu sesión se cerró» (login) is not.
    forbidden += ("token", "sesiones", "clic", "clics", "dimensión")
    texts = [
        text
        for label, hint, advice in clarity_provider._FRICTION_METRICS.values()
        for text in (label, hint, advice)
    ]
    texts += list(clarity_provider._COLUMN_LABELS.values())
    texts += list(clarity_provider._METRIC_LABELS.values())
    texts += clarity_state.DIMENSION_CHOICES
    messages = [
        value
        for name, value in vars(clarity_state).items()
        if name.startswith("_") and name[1:].isupper() and isinstance(value, str)
    ]
    assert len(messages) >= 10
    for text in texts + messages:
        for word in forbidden:
            # Whole words only: «botón» is plain Spanish, «bot» is jargon.
            assert not re.search(rf"\b{word}\b", text.lower()), (word, text)
    assert "OS" not in clarity_state.DIMENSION_CHOICES

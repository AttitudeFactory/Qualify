"""RESULTADOS-3 (m-24843001): «Tu página web» reads like the owner talks.

Offline: the daily-refresh rule and the VM split are pure, the support adapter is
called with a fake, and the page checks read the source (the static-guard style of
`test_clarity_settings.py`)."""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from qualify_api.clarity.repository import SnapshotRow

from . import clarity_provider
from . import clarity_vm as W
from .clarity_provider import _to_vm
from .test_clarity_vm import FRICTION_PAYLOAD

_HERE = Path(__file__).parent
_NOW = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("fetched_at", "expected"),
    [
        (None, True),
        (_NOW - timedelta(hours=2), False),
        (_NOW.replace(hour=0, minute=1), False),
        (_NOW - timedelta(days=1), True),
        (_NOW.replace(hour=0) - timedelta(minutes=1), True),
    ],
)
def test_needs_daily_refresh_once_per_utc_day(fetched_at: datetime | None, expected: bool) -> None:
    assert W.needs_daily_refresh(fetched_at, _NOW) is expected


def test_window_label_in_owner_words() -> None:
    assert W.window_label(3) == "Últimos 3 días"
    assert W.window_label(1) == "Último día"


def _vm():
    return _to_vm(
        SnapshotRow(
            id=uuid4(),
            num_of_days=3,
            dimensions=["URL"],
            payload=FRICTION_PAYLOAD,
            fetched_at=datetime(2026, 10, 22, 7, 30, tzinfo=UTC),
        )
    )


def test_headline_is_visits_and_people_only() -> None:
    vm = _vm()
    assert [label for label, _value in vm.headline] == ["Visitas", "Personas"]
    assert vm.window == "Últimos 3 días"
    assert vm.fetched_at == "22 de octubre"


def test_only_urgent_problems_lead_and_the_rest_is_flagged() -> None:
    vm = _vm()
    assert [item.severity for item in vm.urgent] == ["alta"]
    assert vm.urgent[0].title.startswith("Toques repetidos con enojo")
    assert vm.has_minor is True


def test_alert_team_files_a_closed_context_ticket(monkeypatch) -> None:
    seen: dict = {}

    def fake_create(**kwargs):
        seen.update(kwargs)
        return "ticket"

    monkeypatch.setattr(clarity_provider, "create_support_request", fake_create)
    tenant = uuid4()
    result = clarity_provider.alert_team(
        tenant, contact_email="a@b.co", title="Fallas de la página en /reservas", detail="3 veces."
    )
    assert result == "ticket"
    assert seen["tenant_id"] == tenant
    assert seen["topic"] == "other"
    assert seen["context"] == {"screen": W.TEAM_ALERT_SCREEN}
    assert "Fallas de la página en /reservas" in seen["message"]


def _page_source() -> str:
    return (_HERE / "clarity_page.py").read_text(encoding="utf-8")


def _string_constants(source: str) -> list[str]:
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_reading_screen_has_no_quota_selector_or_jargon() -> None:
    source = _page_source()
    for gone in (
        "remaining_budget",
        "refresh_days",
        "refresh_dimension",
        "refresh_from_clarity",
        "rx.select",
        "snapshot.dimensions",
    ):
        assert gone not in source, gone
    owner_texts = _string_constants(source) + [
        value for name, value in vars(W).items() if name.isupper() and isinstance(value, str)
    ]
    for text in owner_texts:
        for word in ("token", "snapshot", "dimensión", "dimension", "llamadas", "cupo"):
            assert not re.search(rf"\b{word}\b", text.lower()), (word, text)


def test_every_urgent_problem_has_avisar_al_equipo() -> None:
    source = _page_source()
    assert W.WARN_TEAM == "Avisar al equipo"
    assert "rx.foreach(ClarityState.snapshot.urgent, _urgent_item)" in source
    urgent_fn = source[source.index("def _urgent_item(") : source.index("def _all_good(")]
    assert "_alert_button(item)" in urgent_fn
    assert "ClarityState.alert_team_about(item.title)" in source


def test_not_connected_says_the_exact_message_and_no_form() -> None:
    assert W.NOT_CONNECTED_BODY.startswith("No hace falta: tus redes ya cuentan.")
    source = _page_source()
    panel = source[source.index("def _not_connected(") : source.index("def _messages(")]
    assert "W.NOT_CONNECTED_BODY" in panel
    for field in ("rx.input", "rx.form", "form_api_token", "form_project_id"):
        assert field not in panel

"""RESULTADOS-4 (m-24843002): the Clarity connection lives in Configuración, the reading
screen shows no configuration field, and the access key stays write-only.

Offline: the guided-step function is pure, the page checks read the source (the same
static-guard style as `test_design_system_guard.py`), and the support adapter is called
with a fake service."""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import uuid4

import pytest

from . import clarity_provider
from . import clarity_vm as W
from .clarity_vm import website_step

_HERE = Path(__file__).parent


@pytest.mark.parametrize(
    ("configured", "answer", "expected"),
    [
        (True, "", "connected"),
        (True, W.ANSWER_NO, "connected"),
        (False, "", "ask"),
        (False, W.ANSWER_NO, "no_site"),
        (False, W.ANSWER_YES, "ask_team"),
        (False, "otra cosa", "ask"),
    ],
)
def test_website_step(configured: bool, answer: str, expected: str) -> None:
    assert website_step(configured=configured, answer=answer) == expected


def _calls(source: str) -> set[str]:
    """Every dotted call name in a module (`rx.input`, `ClarityState.save_settings`…)."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        target = node.func if isinstance(node, ast.Call) else node
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            names.add(f"{target.value.id}.{target.attr}")
    return names


def test_reading_screen_has_no_configuration_field() -> None:
    names = _calls((_HERE / "clarity_page.py").read_text(encoding="utf-8"))
    for forbidden in (
        "rx.input",
        "rx.text_area",
        "rx.form",
        "ClarityState.form_project_id",
        "ClarityState.form_api_token",
        "ClarityState.save_settings",
    ):
        assert forbidden not in names, forbidden


def test_settings_has_labelled_fields_that_fit_a_phone() -> None:
    source = (_HERE / "settings_page.py").read_text(encoding="utf-8")
    names = _calls(source)
    assert "ClarityState.save_settings" in names
    assert "ClarityState.form_api_token" in names
    # Each field has a visible label tied to its id, and no fixed rem width (N12).
    for field_id in ("q-website-project", "q-website-key"):
        assert source.count(f'"{field_id}"') == 2, field_id
    assert 'width="14rem"' not in source and 'width="22rem"' not in source
    for name in ("FIELD_PROJECT", "FIELD_KEY", "QUESTION", "NO_SITE", "ASK_TEAM_BUTTON"):
        assert f"W.{name}" in source, name  # the copy lives in clarity_vm


def test_no_screen_reads_the_key_back() -> None:
    """The key is write-only: no VM carries it, so nothing can render it."""
    fields = clarity_provider.ClarityConfigVM.__dataclass_fields__
    assert set(fields) == {"configured", "project_id", "remaining_budget"}


def test_request_website_connection_uses_closed_context(monkeypatch) -> None:
    seen: dict = {}

    def fake_create(**kwargs):
        seen.update(kwargs)
        return "ticket"

    monkeypatch.setattr(clarity_provider, "create_support_request", fake_create)
    tenant = uuid4()
    assert clarity_provider.request_website_connection(tenant, contact_email="a@b.co") == "ticket"
    assert seen["tenant_id"] == tenant
    assert seen["topic"] == "other"
    assert seen["contact_email"] == "a@b.co"
    assert seen["context"] == {"screen": W.TEAM_REQUEST_SCREEN}
    assert seen["message"] == W.TEAM_REQUEST_MESSAGE


def test_copy_has_no_english_or_keys_words() -> None:
    texts = [
        W.QUESTION,
        W.NO_SITE,
        W.ASK_TEAM,
        W.ASK_TEAM_BUTTON,
        W.CONNECTED,
        W.TEAM_FOLD,
        W.TEAM_FOLD_HINT,
        W.FIELD_PROJECT,
        W.FIELD_KEY,
        W.SAVE,
    ]
    for text in texts:
        lowered = text.lower()
        for word in ("token", "api", "dashboard", "settings", "snapshot"):
            assert word not in lowered, (word, text)

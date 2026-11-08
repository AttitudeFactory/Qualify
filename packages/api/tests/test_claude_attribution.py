"""m-24955649: every paid Claude call is booked in the consumption ledger, to a business
and a function, by ONE interceptor (`claude_tools.messages_create`).

- a paid call leaves exactly one booking, with the business, brand, function, prompt
  version, tokens, cost and price-sheet version (`v7`) — a call that leaves none fails;
- a refusal is billed, so it is booked too;
- a booking that cannot be written never breaks the owner's action, and says so at ERROR;
- «sin negocio» (no business) is booked as a WARNING with every field, never dropped;
- `Attribution` is required (no default) on `create_turn` and `messages_create`, and a
  walk over every caller in the repo fails if one call does not pass it;
- `Attribution.no_business` is allowed only where no business pays on purpose;
- the prices the interceptor books with are the `v7` sheet it names.
"""

from __future__ import annotations

import ast
import inspect
import logging
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.pricing import JsonPricingTable

from qualify_api import claude_tools
from qualify_api.claude_tools import (
    Attribution,
    ClaudeConsumption,
    ClaudeToolError,
    Meter,
    ModelConfig,
    create_turn,
    messages_create,
)

_REPO = Path(__file__).resolve().parents[3]
_MODEL = ModelConfig("claude-haiku-5-5")
TENANT = uuid4()
BRAND = uuid4()


def _response(stop: str = "tool_use") -> Any:
    usage = SimpleNamespace(
        input_tokens=1_000,
        output_tokens=200,
        cache_read_input_tokens=3_000,
        cache_creation_input_tokens=500,
    )
    block = SimpleNamespace(type="tool_use", name="t", input={})
    return SimpleNamespace(
        usage=usage, model="claude-haiku-5-5-20261008", stop_reason=stop, content=[block]
    )


def _client(response: Any) -> Any:
    return SimpleNamespace(messages=SimpleNamespace(create=lambda **_kw: response))


@pytest.fixture
def booked(monkeypatch: pytest.MonkeyPatch) -> list[ClaudeConsumption]:
    rows: list[ClaudeConsumption] = []
    monkeypatch.setattr(claude_tools, "_consumption_sink", rows.append)
    return rows


def _turn(client: Any, attribution: Attribution) -> Any:
    return create_turn(
        client,
        _MODEL,
        Meter(_MODEL),
        system="s",
        messages=[{"role": "user", "content": "hola"}],
        tools=[],
        tool_choice={"type": "auto"},
        max_tokens=100,
        attribution=attribution,
    )


# -- the interceptor --------------------------------------------------------------------


def test_a_paid_call_leaves_exactly_one_booking_with_its_business_and_function(
    booked: list[ClaudeConsumption],
) -> None:
    paid = Attribution(tenant_id=TENANT, brand_id=BRAND, feature="wa-suggest")
    _turn(_client(_response()), paid.versioned("wa-suggest-1"))
    assert len(booked) == 1, "a paid Claude call left no booking in the ledger"
    row = booked[0]
    assert row.attribution.tenant_id == TENANT and row.attribution.brand_id == BRAND
    assert row.attribution.feature == "wa-suggest"
    assert row.attribution.prompt_version == "wa-suggest-1"
    assert row.model_id == "claude-haiku-5-5"
    assert row.model_revision == "claude-haiku-5-5-20261008"
    assert (row.input_tokens, row.output_tokens) == (1_000, 200)
    assert (row.cache_read_tokens, row.cache_creation_tokens) == (3_000, 500)
    # every token at its own rate: 1000x0.10 + 3000x0.01 + 500x0.125 + 200x0.50, per MTok
    assert row.cost_usd == Decimal("0.0002925") and row.priced
    assert row.pricing_table_version == "v7"


def test_each_turn_of_a_run_is_its_own_booking(booked: list[ClaudeConsumption]) -> None:
    paid = Attribution(tenant_id=TENANT, feature="hashtags-catalogo")
    client = _client(_response())
    _turn(client, paid)
    _turn(client, paid)
    assert len(booked) == 2


def test_a_refusal_is_billed_so_it_is_booked(booked: list[ClaudeConsumption]) -> None:
    with pytest.raises(ClaudeToolError):
        _turn(_client(_response("refusal")), Attribution(tenant_id=TENANT, feature="angulos"))
    assert len(booked) == 1


def test_a_call_that_raised_before_an_answer_books_nothing(
    booked: list[ClaudeConsumption],
) -> None:
    def boom(**_kw: Any) -> Any:
        raise TimeoutError("no answer")

    client = SimpleNamespace(messages=SimpleNamespace(create=boom))
    with pytest.raises(TimeoutError):
        _turn(client, Attribution(tenant_id=TENANT, feature="angulos"))
    assert booked == []


def test_a_booking_that_fails_never_breaks_the_owners_action_and_says_so(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(_record: ClaudeConsumption) -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(claude_tools, "_consumption_sink", broken)
    response = _response()
    with caplog.at_level(logging.ERROR, logger="qualify_api.claude_tools"):
        got = _turn(_client(response), Attribution(tenant_id=TENANT, feature="wa-import"))
    assert got is response
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and "NOT booked" in errors[0].getMessage()
    assert "wa-import" in errors[0].getMessage() and errors[0].exc_info is not None


def test_messages_create_is_the_interceptor_too(booked: list[ClaudeConsumption]) -> None:
    messages_create(
        _client(_response("end_turn")),
        _MODEL,
        attribution=Attribution(tenant_id=TENANT, feature="respuesta-comentario"),
        model="claude-haiku-5-5",
    )
    assert [r.attribution.feature for r in booked] == ["respuesta-comentario"]


def test_an_unpriced_model_is_booked_at_zero_and_marked(booked: list[ClaudeConsumption]) -> None:
    messages_create(
        _client(_response()),
        ModelConfig("claude-unknown-1"),
        attribution=Attribution(tenant_id=TENANT, feature="x"),
    )
    assert booked[0].cost_usd == 0 and booked[0].priced is False


# -- the production sink ----------------------------------------------------------------


def _record(attribution: Attribution) -> ClaudeConsumption:
    return ClaudeConsumption(
        attribution=attribution,
        model_id="claude-haiku-5-5",
        model_revision="rev",
        input_tokens=10,
        output_tokens=2,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        cost_usd=Decimal("0.000002"),
        priced=True,
    )


def test_the_ledger_sink_writes_one_row_through_the_tenant_door(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api import consumption

    rows: list[dict[str, Any]] = []
    monkeypatch.setattr(consumption, "record_now", lambda **row: rows.append(row))
    paid = Attribution(tenant_id=TENANT, brand_id=BRAND, feature="wa-suggest", prompt_version="p1")
    claude_tools.ledger_sink(_record(paid))
    assert rows == [
        {
            "tenant_id": TENANT,
            "brand_id": BRAND,
            "operation": "wa-suggest",
            "provider": "anthropic",
            "model_id": "claude-haiku-5-5",
            "input_tokens": 10,
            "output_tokens": 2,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "cost_usd": Decimal("0.000002"),
            "metadata": {"model_revision": "rev", "prompt_version": "p1"},
            "pricing_table_version": "v7",
        }
    ]


def test_sin_negocio_is_logged_with_every_field_and_never_written(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from qualify_api import consumption

    def no_write(**_row: Any) -> None:
        raise AssertionError("a row with no business has no tenant to be written under")

    monkeypatch.setattr(consumption, "record_now", no_write)
    with caplog.at_level(logging.WARNING, logger="qualify_api.claude_tools"):
        claude_tools.ledger_sink(_record(Attribution.no_business("reel-analysis")))
    (warning,) = [r for r in caplog.records if "sin negocio" in r.getMessage()]
    text = warning.getMessage()
    assert "feature=reel-analysis" in text and "cost_usd=0.000002" in text
    assert "input=10" in text and "model=claude-haiku-5-5" in text


def test_an_attribution_needs_a_function() -> None:
    with pytest.raises(ValueError):
        Attribution(tenant_id=TENANT, feature=" ")


def test_versioned_keeps_a_version_the_caller_already_set() -> None:
    paid = Attribution(tenant_id=TENANT, feature="f", prompt_version="mine")
    assert paid.versioned("other").prompt_version == "mine"
    assert Attribution(tenant_id=TENANT, feature="f").versioned("v2").prompt_version == "v2"


# -- no caller can forget it ------------------------------------------------------------


@pytest.mark.parametrize("entry", [create_turn, messages_create])
def test_attribution_is_a_required_keyword_with_no_default(entry: Any) -> None:
    parameter = inspect.signature(entry).parameters["attribution"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


#: Where Claude callers live: the backend, the app, the evals.
_CALLER_ROOTS = ("packages/api/src", "packages/api/evals", "Qualify")
_ENTRY_POINTS = frozenset({"create_turn", "messages_create"})


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in _CALLER_ROOTS:
        files += [
            p
            for p in (_REPO / root).rglob("*.py")
            if "/tests/" not in p.as_posix() and not p.name.startswith("test_")
        ]
    return files


def _name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def test_every_claude_call_in_the_repo_passes_its_attribution() -> None:
    """Walks every caller of `create_turn` / `messages_create`: each call names who
    pays (`attribution=`). A call without it would not even run (the keyword is
    required), but this catches it before a test of that path exists."""
    callers: list[str] = []
    missing: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _name(node) in _ENTRY_POINTS:
                where = f"{path.relative_to(_REPO)}:{node.lineno}"
                if path.name == "claude_tools.py" and _name(node) == "messages_create":
                    continue  # create_turn's own hop, checked by the signature test
                callers.append(where)
                if not any(k.arg == "attribution" for k in node.keywords):
                    missing.append(where)
    assert missing == [], f"Claude calls with no attribution: {missing}"
    # the walk really walked: the known callers are many (19 modules on 2026-11-08)
    assert len(callers) >= 19, callers


#: The only places a call is booked to no business ON PURPOSE (ADR 44's shared reel
#: analysis; offline evals the founder runs; the app's session-less fallbacks). Anything
#: new here is a decision, not an accident: add it with its reason.
_NO_BUSINESS_ALLOWED = {
    "packages/api/src/qualify_api/referentes/reel_analysis_ai.py": "ADR 44: shared analysis",
    "packages/api/src/qualify_api/evals/brief_reading.py": "eval",
    "packages/api/src/qualify_api/evals/parts_proposal.py": "eval",
    "packages/api/src/qualify_api/evals/legibility_claude.py": "eval",
    "packages/api/src/qualify_api/intent/eval.py": "eval",
    "packages/api/evals/hashtag_ai/run_eval.py": "eval",
    "packages/api/evals/reels_ai/run_eval.py": "eval",
    "packages/api/evals/referentes_ai/run_eval.py": "eval",
    "packages/api/evals/replies_ai/run_experiment.py": "eval",
    "Qualify/referentes_review.py": "a review asked with no business session",
}


def test_sin_negocio_is_used_only_where_it_is_a_decision() -> None:
    found: set[str] = set()
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        if "no_business(" in text and path.name != "claude_tools.py":
            found.add(path.relative_to(_REPO).as_posix())
    assert found <= set(_NO_BUSINESS_ALLOWED), sorted(found - set(_NO_BUSINESS_ALLOWED))


def test_only_claude_tools_talks_to_the_messages_api() -> None:
    """A direct `client.messages.create` would bypass the interceptor. The reel
    analysis' `_Recording` wrapper is the one exception: it is the client handed TO
    `create_turn`, so its calls are still booked."""
    allowed = {
        "packages/api/src/qualify_api/claude_tools.py",
        "packages/api/src/qualify_api/referentes/reel_analysis_ai.py",
    }
    direct: list[str] = []
    for path in _python_files():
        relative = path.relative_to(_REPO).as_posix()
        if relative.startswith("packages/api/evals/"):
            continue  # offline experiment scripts, never in production
        if ".messages.create(" in path.read_text(encoding="utf-8") and relative not in allowed:
            direct.append(relative)
    assert direct == []


# -- the price sheet it books with ------------------------------------------------------


@pytest.mark.parametrize("model_id", sorted(claude_tools.PRICES))
def test_the_booked_prices_are_the_v7_sheet(model_id: str) -> None:
    sheet = JsonPricingTable(claude_tools.PRICING_TABLE_VERSION)
    price_in, price_out = claude_tools.PRICES[model_id]
    assert sheet.unit_price(model_id=model_id, unit="per_mtok_in") == Decimal(repr(price_in))
    assert sheet.unit_price(model_id=model_id, unit="per_mtok_out") == Decimal(repr(price_out))
    assert sheet.unit_price(model_id=model_id, unit="per_mtok_cache_read") == Decimal(
        repr(claude_tools.CACHE_READ_PRICES[model_id])
    )

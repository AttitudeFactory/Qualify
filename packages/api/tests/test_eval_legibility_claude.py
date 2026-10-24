"""The Claude legibility reader of the plantillas_ai eval (m-24849234 PR 3), offline: a fake
`messages_create` stands in for the API, so nothing here reaches the network. Covers the
reader's own cap (reads and USD, reserved before each call), the request shape, the
retry counted as a read, and the runner's `lector` block."""

from __future__ import annotations

import base64
import importlib.util
import io
import json
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
import pytest
from PIL import Image
from qualify_creative.pricing import JsonPricingTable

from qualify_api.claude_tools import ClaudeToolError
from qualify_api.evals import image_metrics as im
from qualify_api.evals import legibility_claude as lc
from qualify_api.evals import spend_control as sc
from qualify_api.evals import template_transfer as tt

EVAL_DIR = Path(__file__).resolve().parents[1] / "evals" / "plantillas_ai"
#: One read at the fake usage below: 1700 x 2/M + 60 x 10/M.
READ_USD = Decimal("0.004")


def _png(size: tuple[int, int] = (64, 32)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, format="PNG")
    return out.getvalue()


def _response(
    text: str | None, *, stop_reason: str = "tool_use", tool: bool = True
) -> SimpleNamespace:
    if tool:
        block = SimpleNamespace(type="tool_use", name=lc.READ_TOOL, input={"texto": text})
    else:
        block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(
        model="claude-sonnet-5",
        stop_reason=stop_reason,
        content=[block],
        usage=SimpleNamespace(
            input_tokens=1700,
            output_tokens=60,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


class FakeCreate:
    """Stands in for `claude_tools.messages_create`: answers in order, records kwargs."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, client: Any, config: Any, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _reader(create: FakeCreate, budget: lc.ReadBudget | None = None) -> lc.ClaudeLegibilityReader:
    return lc.ClaudeLegibilityReader(
        "dummy-not-a-key", budget=budget, client_factory=lambda _key: object(), create=create
    )


def test_worst_case_is_bounded_by_tokens_and_prices() -> None:
    # 4000 input tokens x 1.25 x USD 2/M + 2048 output tokens x USD 10/M
    assert lc.worst_case_usd("claude-sonnet-5") == Decimal("0.03048")
    with pytest.raises(ValueError, match="no price"):
        lc.worst_case_usd("claude-unknown")
    with pytest.raises(ValueError, match="no price"):
        lc.ClaudeLegibilityReader("k", model="claude-unknown", client_factory=lambda _key: object())


def test_a_read_reserves_the_worst_case_and_settles_the_real_usage() -> None:
    create = FakeCreate(_response("LUMA"))
    reader = _reader(create)
    assert reader.read_text(_png()) == "LUMA"
    budget = reader.budget
    assert budget.reads == 1 and budget.spent_usd == READ_USD and budget.held_usd == 0
    assert budget.overage_usd == 0


def test_the_request_is_one_strict_tool_call_at_low_effort() -> None:
    create = FakeCreate(_response("LUMA"))
    _reader(create).read_text(_png((3000, 1200)))
    (kwargs,) = create.calls
    assert kwargs["model"] == "claude-sonnet-5" and kwargs["max_tokens"] == lc.MAX_OUTPUT_TOKENS
    assert kwargs["output_config"] == {"effort": "low"}
    assert "temperature" not in kwargs
    (tool,) = kwargs["tools"]
    assert tool["name"] == lc.READ_TOOL and tool["strict"] is True
    assert kwargs["tool_choice"] == {"type": "auto"}  # a thinking model: auto, then checked
    image, text = kwargs["messages"][0]["content"]
    assert text["type"] == "text" and "texto exacto" in text["text"]
    sent = Image.open(io.BytesIO(base64.b64decode(image["source"]["data"])))
    assert max(sent.size) <= lc.READ_IMAGE_MAX_SIDE  # bounds the image tokens
    assert "exactamente" in kwargs["system"]


def test_the_count_cap_refuses_before_calling() -> None:
    create = FakeCreate(_response("LUMA"))
    reader = _reader(create, lc.ReadBudget(max_reads=2))
    reader.read_text(_png())
    reader.read_text(_png())
    with pytest.raises(lc.ReadBudgetExceeded, match="2 of its 2"):
        reader.read_text(_png())
    assert len(create.calls) == 2 and reader.budget.reads == 2


def test_the_usd_cap_refuses_before_calling() -> None:
    create = FakeCreate(_response("LUMA"))
    reader = _reader(create, lc.ReadBudget(max_usd=Decimal("0.05")))
    reads = 0
    with pytest.raises(lc.ReadBudgetExceeded, match="cap of USD 0.05"):
        while True:
            reader.read_text(_png())
            reads += 1
    # n reads fit while 0.004 n + 0.03048 <= 0.05: n = 0..4
    assert reads == 5 and len(create.calls) == 5
    assert reader.budget.spent_usd == 5 * READ_USD <= Decimal("0.05")


def test_a_failed_call_settles_the_worst_case_and_blocks_what_no_longer_fits() -> None:
    create = FakeCreate(httpx.ReadTimeout("dropped"), _response("LUMA"))
    reader = _reader(create, lc.ReadBudget(max_usd=Decimal("0.05")))
    with pytest.raises(httpx.ReadTimeout):
        reader.read_text(_png())
    assert reader.budget.spent_usd == Decimal("0.03048") and reader.budget.held_usd == 0
    with pytest.raises(lc.ReadBudgetExceeded):  # 0.03048 + 0.03048 > 0.05
        reader.read_text(_png())
    assert len(create.calls) == 1


def test_a_refusal_is_an_error_and_its_usage_is_spent() -> None:
    reader = _reader(FakeCreate(_response(None, stop_reason="refusal", tool=False)))
    with pytest.raises(ClaudeToolError, match="refusal"):
        reader.read_text(_png())
    assert reader.budget.reads == 1 and reader.budget.spent_usd == READ_USD


def test_a_text_only_answer_is_not_a_reading() -> None:
    reader = _reader(FakeCreate(_response("La imagen dice CAFÉ RÍO", tool=False)))
    with pytest.raises(ClaudeToolError, match="no final tool"):
        reader.read_text(_png())
    assert reader.budget.reads == 1 and reader.budget.spent_usd == READ_USD  # it was billed
    record_reader = _reader(FakeCreate(_response("prosa", tool=False)))
    with pytest.raises(ClaudeToolError):  # never becomes `leido`, never triggers the retry
        im.legibility_record(record_reader, _png(), "CAFÉ RÍO")
    assert record_reader.budget.reads == 1


@pytest.mark.parametrize(
    ("reads", "usd"), [(0, "0.5"), (51, "0.5"), (10, "0.51"), (10, "0"), (10, "-1")]
)
def test_the_budget_never_goes_above_the_founders_caps(reads: int, usd: str) -> None:
    with pytest.raises(ValueError):
        lc.ReadBudget(max_reads=reads, max_usd=Decimal(usd))
    assert lc.ReadBudget().max_reads == 50 and lc.ReadBudget().max_usd == Decimal("0.50")


def test_the_retry_on_a_mismatch_is_a_counted_read() -> None:
    create = FakeCreate(_response("LUMO"), _response("LUMA"))
    reader = _reader(create)
    record = im.legibility_record(reader, _png(), "LUMA")
    assert record["coincide"] is True and record["reintento"] is True
    assert record["lecturas"] == ["LUMO", "LUMA"]
    assert reader.budget.reads == 2 and reader.budget.spent_usd == 2 * READ_USD


def test_the_retry_refused_by_the_cap_keeps_the_first_reading() -> None:
    reader = _reader(FakeCreate(_response("LUMO")), lc.ReadBudget(max_reads=1))
    record = im.legibility_record(reader, _png(), "LUMA")
    assert record["estado"] == "leido" and record["coincide"] is False
    assert record["reintento"] is False and "1 of its 1" in str(record["motivo_sin_reintento"])


def _runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "plantillas_runner_reader", EVAL_DIR / "run_experiment.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ok() -> httpx.Response:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(out, format="JPEG")
    return httpx.Response(
        200,
        json={
            "model": sc.SEEDREAM_PRO,
            "data": [{"b64_json": base64.b64encode(out.getvalue()).decode(), "size": "8x8"}],
            "usage": {"generated_images": 1, "output_tokens": 1},
        },
    )


def test_the_report_carries_the_reader_block_and_each_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    cases = tt.load_cases(EVAL_DIR / "cases.json")
    planned = tt.plan_calls(
        tt.build_matrix(cases, blocks=["texture"], limit=2),
        JsonPricingTable("v6"),
        model_ids=[sc.SEEDREAM_PRO],
        size="1K",
    )
    create = FakeCreate(_response("LUMO"), _response("LUMA"), _response("NÚCLEO"))
    reader = _reader(create)
    report = runner.run_paid(
        planned,
        tt,
        ledger=sc.SpendLedger(Decimal("1")),
        api_key="dummy",
        args=runner.build_parser().parse_args(["--results-dir", str(tmp_path / "res")]),
        inner_transport=httpx.MockTransport(lambda _r: _ok()),
        reader=reader,
    )
    lector = report["lector"]
    assert lector["tipo"] == "claude" and lector["modelo"] == "claude-sonnet-5"
    assert lector["prompt_version"] == lc.READER_PROMPT_VERSION
    assert lector["lecturas"] == 3 and Decimal(lector["gastado_usd"]) == 3 * READ_USD
    assert lector["tope_lecturas"] == 50 and lector["tope_usd"] == "0.50"
    luma = report["items"][f"texture:fix-luma+textura-rayas-cobre@{sc.SEEDREAM_PRO}"]
    nucleo = report["items"][f"texture:fix-nucleo+textura-puntos-mostaza@{sc.SEEDREAM_PRO}"]
    assert luma["legibilidad"]["reintento"] is True and luma["legibilidad"]["coincide"] is True
    assert nucleo["legibilidad"]["leido"] == "NÚCLEO" and nucleo["legibilidad"]["coincide"]
    saved = json.loads(next((tmp_path / "res").glob("*.json")).read_text(encoding="utf-8"))
    assert saved["lector"]["lecturas"] == 3
    # Seedream spend and reader spend are separate ledgers
    assert Decimal(report["spent_usd"]) == Decimal("0.096")


def test_without_a_reader_the_report_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    cases = tt.load_cases(EVAL_DIR / "cases.json")
    planned = tt.plan_calls(
        tt.build_matrix(cases, blocks=["texture"], limit=1),
        JsonPricingTable("v6"),
        model_ids=[sc.SEEDREAM_PRO],
        size="1K",
    )
    report = runner.run_paid(
        planned,
        tt,
        ledger=sc.SpendLedger(Decimal("1")),
        api_key="dummy",
        args=runner.build_parser().parse_args(["--results-dir", str(tmp_path / "res")]),
        inner_transport=httpx.MockTransport(lambda _r: _ok()),
    )
    assert report["lector"] == {"tipo": "ninguno"}
    (record,) = report["items"].values()
    assert record["legibilidad"]["estado"] == "pendiente"

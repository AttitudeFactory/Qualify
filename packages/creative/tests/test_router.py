"""CreativeRouter: (F) fallback with recorded hops, (P) pre-flight budget block."""

from decimal import Decimal
from typing import Any
from uuid import uuid4

from qualify_creative.enums import GenerationTask, PaidBy
from qualify_creative.providers import (
    GenerationRequest,
    GenerationResult,
    RenderedPrompt,
    ResolvedKey,
    Usage,
)
from qualify_creative.router import BudgetContext, CreativeRouter, HopAction, RouterOutcome

TENANT_ID = uuid4()
BRAND_ID = uuid4()


def make_request() -> GenerationRequest:
    return GenerationRequest(
        task=GenerationTask.COPY,
        rendered_prompt=RenderedPrompt(
            stable_prefix="kit", volatile_suffix="brief", prefix_fingerprint="fp"
        ),
    )


def make_result(provider: str) -> GenerationResult:
    return GenerationResult(
        payload={"hook": "h"},
        model_id="claude-opus-5",
        provider=provider,
        usage=Usage(input_tokens=10, output_tokens=5),
    )


class FakeProvider:
    def __init__(
        self,
        name: str,
        *,
        estimate: Decimal = Decimal("0.10"),
        result: GenerationResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.supports = frozenset({GenerationTask.COPY})
        self._estimate = estimate
        self._result = result
        self._error = error
        self.generate_keys: list[str] = []
        self.estimate_calls = 0

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        self.generate_keys.append(api_key)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result

    def estimate_cost_usd(
        self, request: GenerationRequest, pricing: Any, *, api_key: str | None = None
    ) -> Decimal:
        self.estimate_calls += 1
        return self._estimate


class FakeResolver:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def resolve(self, *, tenant_id: Any, brand_id: Any, provider: str) -> ResolvedKey:
        self.calls.append(provider)
        return ResolvedKey(
            api_key=f"key-{provider}", paid_by=PaidBy.PLATFORM, fingerprint=f"fp-{provider}"
        )


class NullPricing:
    version = "test"

    def unit_price(self, *, model_id: str, unit: str) -> Decimal:
        raise KeyError(f"pricing table 'test' has no entry for model {model_id!r}")


def run_router(
    providers: dict[str, Any], chain: tuple[str, ...], budget: BudgetContext
) -> RouterOutcome:
    router = CreativeRouter(providers, NullPricing(), FakeResolver())
    return router.run(
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        chain=chain,
        request=make_request(),
        budget=budget,
    )


def test_failure_falls_to_next_provider_with_hop_recorded() -> None:
    first = FakeProvider("first", error=RuntimeError("boom"))
    second = FakeProvider("second", result=make_result("second"))

    outcome = run_router(
        {"first": first, "second": second},
        ("first", "second"),
        BudgetContext(remaining_usd=Decimal("5.00")),
    )

    assert outcome.succeeded
    assert outcome.result is not None
    assert outcome.result.provider == "second"
    assert [(h.provider, h.action) for h in outcome.hops] == [
        ("first", HopAction.FAILED),
        ("second", HopAction.SUCCEEDED),
    ]
    # The failed hop names its reason — a silent skip is a bug.
    assert outcome.hops[0].reason is not None
    assert "boom" in outcome.hops[0].reason
    # Each provider got its own resolved credential.
    assert first.generate_keys == ["key-first"]
    assert second.generate_keys == ["key-second"]


def test_budget_block_records_hop_and_hard_stops() -> None:
    pricey = FakeProvider("pricey", estimate=Decimal("10.00"), result=make_result("pricey"))
    backup = FakeProvider("backup", result=make_result("backup"))

    outcome = run_router(
        {"pricey": pricey, "backup": backup},
        ("pricey", "backup"),
        BudgetContext(remaining_usd=Decimal("1.00"), hard_stop=True),
    )

    assert not outcome.succeeded
    assert outcome.result is None
    assert [(h.provider, h.action) for h in outcome.hops] == [("pricey", HopAction.BUDGET_BLOCKED)]
    assert outcome.hops[0].reason is not None
    assert "10.00" in outcome.hops[0].reason
    # Hard stop: the estimate blocked BEFORE any vendor call, and the walk ended there.
    assert pricey.generate_keys == []
    assert backup.generate_keys == []
    assert backup.estimate_calls == 0


def test_budget_block_without_hard_stop_tries_next_link() -> None:
    pricey = FakeProvider("pricey", estimate=Decimal("10.00"), result=make_result("pricey"))
    cheap = FakeProvider("cheap", estimate=Decimal("0.01"), result=make_result("cheap"))

    outcome = run_router(
        {"pricey": pricey, "cheap": cheap},
        ("pricey", "cheap"),
        BudgetContext(remaining_usd=Decimal("1.00"), hard_stop=False),
    )

    assert outcome.succeeded
    assert outcome.result is not None
    assert outcome.result.provider == "cheap"
    assert [(h.provider, h.action) for h in outcome.hops] == [
        ("pricey", HopAction.BUDGET_BLOCKED),
        ("cheap", HopAction.SUCCEEDED),
    ]


def test_unregistered_provider_is_a_recorded_hop_not_a_silent_skip() -> None:
    real = FakeProvider("real", result=make_result("real"))

    outcome = run_router(
        {"real": real},
        ("ghost", "real"),
        BudgetContext(remaining_usd=Decimal("5.00")),
    )

    assert outcome.succeeded
    assert [(h.provider, h.action) for h in outcome.hops] == [
        ("ghost", HopAction.FAILED),
        ("real", HopAction.SUCCEEDED),
    ]
    assert outcome.hops[0].reason == "provider not registered"


def test_exhausted_chain_returns_no_result_with_full_hop_record() -> None:
    a = FakeProvider("a", error=RuntimeError("down"))
    b = FakeProvider("b", error=RuntimeError("also down"))

    outcome = run_router({"a": a, "b": b}, ("a", "b"), BudgetContext(remaining_usd=Decimal("5.00")))

    assert not outcome.succeeded
    assert outcome.result is None
    assert [h.action for h in outcome.hops] == [HopAction.FAILED, HopAction.FAILED]

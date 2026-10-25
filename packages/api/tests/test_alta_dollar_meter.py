"""m-24854322 (OL2-0): the Alta prefill's dollar meter, offline.

`claude_tools.DollarMeter` books every ScrapeCreators credit and every Claude turn of one
Alta attempt in ONE USD balance, and prices each turn BEFORE it is sent. Pinned here:

- the meter's arithmetic: a turn that fits goes as asked, one that fits only with less
  output goes with a lower `max_tokens`, one that does not fit is never sent;
- `turn_input_ceiling`'s rule, including the property test that a turn which
  under-reports its input never lowers the next turn's bound;
- the computed worst case of the Alta's limits (credits + every turn full) <= US$0.15;
- ~240 complete Alta runs through the real ports (`meegle.prefill.bounded_ports`) against
  an adversarial fake Claude (truncations, refusals, timeouts, runs that never choose,
  under-reported usage) at caps 0.15 / 0.06 / 0.02 / 0.008: what was billed and what was
  recorded never exceed the cap, there are no overruns, and every run ends `ok`;
- a cut or refused catalog run falls back to the account's own tags or the rubro run's;
- the web wizard's path is unchanged: no meter, 4,000 / 8 x 16,000 at medium, rule path.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

import httpx
import pytest

from qualify_api import claude_tools
from qualify_api.claude_tools import (
    FIRST_TURN_MARGIN_TOKENS,
    BudgetExhausted,
    ClaudeToolError,
    DollarMeter,
    Meter,
    ModelConfig,
    TurnBound,
    billed_usd,
    create_turn,
    request_bytes,
    turn_input_ceiling,
    worst_turn_usd,
)
from qualify_api.creative import brand_prefill
from qualify_api.creative.brand_prefill import PrefillOutcome
from qualify_api.hashtags import MemoryHashtagRepository, from_profile
from qualify_api.hashtags import ai as hashtag_ai
from qualify_api.hashtags import catalog as hashtag_catalog
from qualify_api.meegle import prefill as mod

from .test_brand_prefill import BRAND, TENANT, Cache, Claims, Pictures, Store, Vendor

SONNET = "claude-sonnet-5"
CAPS = (Decimal("0.15"), Decimal("0.06"), Decimal("0.02"), Decimal("0.008"))
SEEDS_PER_CAP = 60  # 4 caps x 60 = 240 complete Alta runs


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_prefill")
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(hashtag_catalog, "_seeded", False)
    monkeypatch.setattr(hashtag_catalog, "_choices", {})


# --------------------------------------------------------------------------------------
# A fake Anthropic client: adversarial, but never bills more than a real one could
# --------------------------------------------------------------------------------------


@dataclass
class _Usage:
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class _Block:
    type: str
    text: str = ""
    name: str = ""
    input: Any = None
    id: str = ""

    def model_dump(self) -> dict[str, Any]:
        return {"type": self.type, "text": self.text, "name": self.name, "input": self.input}


@dataclass
class _Response:
    content: list[_Block]
    stop_reason: str
    usage: _Usage
    model: str = SONNET


class Timeout(Exception):
    """The HTTP wait ran out: the vendor may still have billed the turn."""


class AdversarialClaude:
    """`client.messages.create`. Per turn it may truncate at `max_tokens`, refuse, time
    out after billing, answer without the tool, search instead of choosing, or report
    less input than it billed — each with a seeded probability. What it BILLS is what a
    real turn could: a prompt of at most the request's non-assistant bytes + the outputs
    it carries back + the framing margin, and at most `max_tokens` of output."""

    def __init__(self, rng: random.Random, *, mode: str = "random") -> None:
        self.rng = rng
        self.mode = mode
        self.requests: list[dict[str, Any]] = []
        #: The conversation as each request saw it (the caller mutates its list).
        self.seen: list[str] = []
        self.billed = Decimal(0)
        self._outputs: dict[int, int] = {}  # id(assistant content) -> its output tokens
        self.messages = self

    def __call__(self, api_key: str) -> AdversarialClaude:  # the client factory
        return self

    def _true_prompt(self, kwargs: dict[str, Any]) -> int:
        system = kwargs["system"][0]["text"]
        sent = request_bytes(system, kwargs["messages"], kwargs["tools"])
        carried = sum(
            self._outputs.get(id(m["content"]), 0)
            for m in kwargs["messages"]
            if m.get("role") == "assistant"
        )
        density = self.rng.uniform(0.25, 1.0)  # tokens per byte: never above 1
        framing = self.rng.randint(0, FIRST_TURN_MARGIN_TOKENS - 1)
        return int(sent * density) + carried + framing

    def _answer(self, kwargs: dict[str, Any]) -> list[_Block]:
        names = [t["name"] for t in kwargs["tools"]]
        roll = self.rng.random()
        if self.mode == "never_choose" or (self.mode == "random" and roll < 0.15):
            return [_Block("text", text="Lo pienso un poco más.")]
        if from_profile.TOOL in names:
            tags = [{"tag": t, "reason": "Lo dice la cuenta."} for t in ("helados", "yogur")]
            return [
                _Block(
                    "tool_use",
                    name=from_profile.TOOL,
                    input={"rubro": "heladería de yogur", "hashtags": tags},
                    id=f"tu_{len(self.requests)}",
                )
            ]
        if self.mode == "random" and roll < 0.55:
            return [
                _Block(
                    "tool_use",
                    name=hashtag_ai.SEARCH_TOOL,
                    input={"consulta": "helados"},
                    id=f"tu_{len(self.requests)}",
                )
            ]
        shown = re.findall(r"#?([a-z0-9áéíóúñ]{3,30})", _flat(kwargs["messages"]))
        picks = [{"tag": t, "fit": "alta", "reason": "Encaja."} for t in shown[:3]]
        return [
            _Block(
                "tool_use",
                name=hashtag_ai.CHOOSE_TOOL,
                input={"picks": picks},
                id=f"tu_{len(self.requests)}",
            )
        ]

    def create(self, **kwargs: Any) -> _Response:
        self.requests.append(kwargs)
        self.seen.append(_flat(kwargs["messages"]))
        max_tokens = kwargs["max_tokens"]
        prompt = self._true_prompt(kwargs)
        roll = self.rng.random()
        truncate = self.mode == "truncate" or (self.mode == "random" and roll < 0.2)
        output = max_tokens if truncate else self.rng.randint(1, max_tokens)
        # the prompt is billed as some mix of uncached, cache read and cache write
        written = self.rng.randint(0, prompt)
        read = self.rng.randint(0, prompt - written)
        billed = _Usage(prompt - written - read, output, read, written)
        self.billed += billed_usd(SONNET, billed) or Decimal(0)
        if self.mode == "random" and 0.2 <= roll < 0.27:
            raise Timeout("read timed out")  # billed, never answered
        stop = "max_tokens" if truncate else "end_turn"
        if self.mode == "random" and 0.27 <= roll < 0.3:
            stop = "refusal"
        content = [] if stop != "end_turn" else self._answer(kwargs)
        self._outputs[id(content)] = output
        reported = billed
        if self.rng.random() < 0.3:  # under-reports the prompt it billed
            reported = replace(billed, input_tokens=0, cache_read_input_tokens=0)
        return _Response(content, stop, reported)


def _flat(messages: list[dict[str, Any]]) -> str:
    out: list[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            out.append(content)
            continue
        for block in content or ():
            if isinstance(block, dict):
                out.append(str(block.get("content") or block.get("text") or ""))
    return " ".join(out).lower()


# --------------------------------------------------------------------------------------
# The meter's arithmetic
# --------------------------------------------------------------------------------------


def test_a_turn_that_fits_goes_as_asked_and_is_booked_as_billed() -> None:
    meter = DollarMeter(Decimal("0.15"))
    allowed, reserved = meter.fit_turn(SONNET, 4_000, 1_200)
    # 4,000 x $2.50/MTok (cache write) + 1,200 x $10/MTok
    assert (allowed, reserved) == (1_200, Decimal("0.022"))
    assert meter.remaining_usd == Decimal("0.128")
    booked = meter.settle_turn(SONNET, reserved, _Usage(1_000, 300, 2_000, 500))
    # 1,000 x 2 + 300 x 10 + 2,000 x 0.20 (read) + 500 x 2.50 (write), $ per MTok
    assert booked == Decimal("0.002") + Decimal("0.003") + Decimal("0.0004") + Decimal("0.00125")
    assert meter.spent_usd == booked and meter.reserved_usd == 0
    assert (meter.lowered_turns, meter.refused_turns, meter.overruns) == (0, 0, 0)


def test_a_turn_that_fits_only_with_less_output_goes_with_a_lower_max_tokens() -> None:
    meter = DollarMeter(Decimal("0.015"))
    allowed, reserved = meter.fit_turn(SONNET, 2_000, 1_500)  # 0.005 in + 0.015 out
    assert allowed == 1_000 and reserved == Decimal("0.015")
    assert meter.lowered_turns == 1 and meter.remaining_usd == 0


def test_a_turn_that_does_not_fit_is_refused_and_books_nothing() -> None:
    meter = DollarMeter(Decimal("0.009"))
    with pytest.raises(BudgetExhausted):
        meter.fit_turn(SONNET, 2_000, 1_500)  # 0.005 in leaves room for 400 < 512
    assert meter.refused_turns == 1
    assert meter.spent_usd == 0 and meter.reserved_usd == 0


def test_an_unpriced_model_is_never_sent() -> None:
    meter = DollarMeter(Decimal("10"))
    with pytest.raises(BudgetExhausted):
        meter.fit_turn("claude-unknown-9", 10, 10)


def test_a_turn_with_no_answer_keeps_its_whole_reservation() -> None:
    meter = DollarMeter(Decimal("0.15"))
    _, reserved = meter.fit_turn(SONNET, 4_000, 1_200)
    assert meter.settle_turn(SONNET, reserved, None) == reserved
    assert meter.spent_usd == reserved and meter.reserved_usd == 0


def test_a_charge_that_does_not_fit_books_nothing() -> None:
    meter = DollarMeter(Decimal("0.003"))
    meter.charge(Decimal("0.0019"), what="scrapecreators")
    with pytest.raises(BudgetExhausted):
        meter.charge(Decimal("0.0019"), what="scrapecreators")
    assert meter.spent_usd == Decimal("0.0019")


def test_a_billed_turn_above_its_reservation_is_an_overrun() -> None:
    meter = DollarMeter(Decimal("1"))
    _, reserved = meter.fit_turn(SONNET, 100, 100)
    meter.settle_turn(SONNET, reserved, _Usage(0, 10_000))
    assert meter.overruns == 1  # booked anyway: the books never lie low


def test_the_worst_turn_is_cache_write_input_plus_full_output() -> None:
    worst = worst_turn_usd(SONNET, 1_000_000, 1_000_000)
    assert worst == Decimal("2.5") + Decimal("10")
    assert worst_turn_usd("claude-unknown-9", 1, 1) is None


# --------------------------------------------------------------------------------------
# The input bound
# --------------------------------------------------------------------------------------

_TOOLS = [{"name": "t", "description": "d", "input_schema": {"type": "object"}}]


def test_the_first_turn_is_its_bytes_plus_the_margin() -> None:
    messages = [{"role": "user", "content": "Hola, ¿qué tal?"}]
    ceiling, sent = turn_input_ceiling("Sistema", messages, _TOOLS)
    assert sent == request_bytes("Sistema", messages, _TOOLS)
    assert ceiling == sent + FIRST_TURN_MARGIN_TOKENS


def test_assistant_messages_are_counted_as_the_previous_output_not_as_bytes() -> None:
    first = [{"role": "user", "content": "Hola"}]
    later = [*first, {"role": "assistant", "content": "x" * 50_000}]
    assert request_bytes("S", later, _TOOLS) == request_bytes("S", first, _TOOLS)


def test_a_later_turn_takes_the_larger_of_the_billed_prompt_and_its_bound() -> None:
    messages = [{"role": "user", "content": "uno"}, {"role": "user", "content": "dos dos"}]
    sent = request_bytes("S", messages, _TOOLS)
    under = TurnBound(ceiling=5_000, billed_prompt=0, output=700, sent_bytes=sent - 4)
    over = TurnBound(ceiling=5_000, billed_prompt=6_000, output=700, sent_bytes=sent - 4)
    assert turn_input_ceiling("S", messages, _TOOLS, under)[0] == 5_000 + 700 + 4
    assert turn_input_ceiling("S", messages, _TOOLS, over)[0] == 6_000 + 700 + 4


def test_property_an_under_reported_turn_never_lowers_the_next_bound() -> None:
    """Property test (seeded, 2,000 cases): whatever a turn reports, the next bound is at
    least the previous bound + its output + the new bytes — and never below what the turn
    really billed. Using only the billed prompt failed this: a turn reporting 0 input
    dragged the next bound under the true prompt."""
    rng = random.Random(24854322)
    for _ in range(2_000):
        messages: list[dict[str, Any]] = [{"role": "user", "content": "x" * rng.randint(1, 900)}]
        ceiling, sent = turn_input_ceiling("S", messages, _TOOLS)
        true_prompt = rng.randint(1, ceiling)  # what the API really billed
        for _turn in range(rng.randint(1, 6)):
            output = rng.randint(1, 1_200)
            reported = rng.choice([0, rng.randint(0, true_prompt), true_prompt])
            bound = TurnBound(ceiling, reported, output, sent)
            messages.append({"role": "assistant", "content": "y" * output})
            messages.append({"role": "user", "content": "z" * rng.randint(0, 800)})
            new_ceiling, new_sent = turn_input_ceiling("S", messages, _TOOLS, bound)
            added = new_sent - sent
            assert new_ceiling >= ceiling + output + added
            # the next turn's real prompt: the last one + its output + the new bytes
            true_prompt = true_prompt + output + int(added * rng.uniform(0.25, 1.0))
            assert new_ceiling >= true_prompt
            ceiling, sent = new_ceiling, new_sent


# --------------------------------------------------------------------------------------
# create_turn with a meter
# --------------------------------------------------------------------------------------


def _turn(client: AdversarialClaude, meter: DollarMeter | None, max_tokens: int = 1_200) -> Any:
    return create_turn(
        client,
        ModelConfig(SONNET, "low"),
        Meter(ModelConfig(SONNET, "low")),
        system="Sistema",
        messages=[{"role": "user", "content": "Elige etiquetas."}],
        tools=_TOOLS,
        tool_choice={"type": "auto"},
        max_tokens=max_tokens,
        budget=meter,
    )


def test_create_turn_sends_the_lowered_max_tokens() -> None:
    client = AdversarialClaude(random.Random(1), mode="choose")
    ceiling, _ = turn_input_ceiling(
        "Sistema", [{"role": "user", "content": "Elige etiquetas."}], _TOOLS
    )
    input_only = worst_turn_usd(SONNET, ceiling, 0)
    assert input_only is not None
    meter = DollarMeter(input_only + Decimal("0.006"))  # room for 600 output tokens
    _turn(client, meter)
    assert client.requests[0]["max_tokens"] == 600
    assert meter.lowered_turns == 1 and meter.spent_usd <= meter.limit_usd


def test_a_refused_turn_is_never_sent_and_carries_the_runs_stats() -> None:
    client = AdversarialClaude(random.Random(1))
    with pytest.raises(BudgetExhausted) as refused:
        _turn(client, DollarMeter(Decimal("0.001")))
    assert client.requests == []
    assert refused.value.stats is not None and refused.value.stats.turns == 0
    assert isinstance(refused.value, ClaudeToolError)


def test_a_turn_that_raises_is_charged_its_reservation() -> None:
    class Down:
        messages = None

        def create(self, **kwargs: Any) -> Any:
            raise Timeout("read timed out")

    down = Down()
    down.messages = down  # type: ignore[assignment]
    meter = DollarMeter(Decimal("0.15"))
    with pytest.raises(Timeout):
        _turn(down, meter)  # type: ignore[arg-type]
    assert meter.spent_usd > 0 and meter.reserved_usd == 0


def test_a_truncation_carries_the_runs_stats() -> None:
    client = AdversarialClaude(random.Random(1), mode="truncate")
    with pytest.raises(ClaudeToolError) as cut:
        _turn(client, DollarMeter(Decimal("0.15")))
    assert cut.value.stats is not None and cut.value.stats.turns == 1


# --------------------------------------------------------------------------------------
# The Alta's worst case
# --------------------------------------------------------------------------------------


def test_the_worst_case_of_an_alta_run_fits_the_cap() -> None:
    """Every credit + every rubro attempt and catalog turn with its `max_tokens` full,
    claude-sonnet-5 at (2, 10) $/MTok, input as cache writes (x1.25)."""
    worst = mod.worst_case()
    assert worst == mod.WorstCase(
        credits=Decimal("0.0038"),  # 2 x 0.0019 (profile + one post page; was 6 credits)
        # 2,500 in + 1,500 out, then 4,100 in + 1,500 out
        rubro=Decimal("0.0465"),
        # 5,200 / 7,200 / 9,200 in, 1,200 out each
        catalog=Decimal("0.0900"),
    )
    assert worst.total == Decimal("0.1403") <= Decimal("0.15")
    assert mod.minimum_run_usd() == Decimal("0.05005")
    # a fourth catalog turn (11,200 in + 1,200 out = 0.04) would break the cap
    fourth = worst_turn_usd(SONNET, 11_200, 1_200)
    assert fourth is not None and worst.total + fourth > Decimal("0.15")


def test_the_alta_limits() -> None:
    assert mod.ALTA_CAPS == brand_prefill.CallCaps(scrapecreators_requests=2, claude_calls=2)
    assert (mod.ALTA_RUBRO_MAX_TOKENS, mod.ALTA_RUBRO_ATTEMPTS) == (1_500, 2)
    assert (mod.ALTA_CATALOG_MAX_TURNS, mod.ALTA_CATALOG_MAX_TOKENS) == (3, 1_200)
    assert mod.ALTA_CATALOG_EFFORT == "low"
    assert mod.SCRAPECREATORS_USD_PER_CREDIT == Decimal("0.0019")
    ports = mod.bounded_ports(DollarMeter(Decimal("0.15")))
    assert ports.generate.keywords["max_tokens"] == 1_500
    assert ports.generate.keywords["attempts"] == 2
    selector = ports.catalog.selector.keywords
    assert (selector["max_turns"], selector["max_tokens"]) == (3, 1_200)
    assert selector["config"] == ModelConfig(hashtag_ai.SELECT_MODEL, "low")
    assert selector["last_turn_hint"] is True
    assert ports.catalog.rule_fallback is False
    assert ports.read_profile is mod.alta_read_profile


# --------------------------------------------------------------------------------------
# Complete Alta runs through the real ports
# --------------------------------------------------------------------------------------


class AltaWorld:
    """One Alta attempt as the worker runs it (`metered_prefill` over `bounded_ports`),
    with the fakes of `test_brand_prefill` for the vendor, the claim, the cache, the store
    and R2, and an in-memory hashtag catalog."""

    def __init__(self, claude: AdversarialClaude, *, posts_hashtags: bool = True) -> None:
        self.vendor = Vendor()
        if not posts_hashtags:
            for item in self.vendor.posts["items"]:
                item["caption"] = {"text": "Sin etiquetas"}
            user = self.vendor.profile["data"]["user"]
            for edge in (user.get("edge_owner_to_timeline_media") or {}).get("edges") or ():
                edge["node"]["edge_media_to_caption"] = {"edges": []}
        self.claude = claude
        self.store = Store()
        self.meters: list[DollarMeter] = []

    def ports(self, meter: DollarMeter) -> brand_prefill.PrefillPorts:
        self.meters.append(meter)
        real = mod.bounded_ports(meter)
        generate = real.generate
        selector = real.catalog.selector
        return replace(
            real,
            claims=Claims(),
            cache=Cache(),
            store=self.store,
            pictures=Pictures(),
            api_key=lambda: "sk-ant-test",
            transport=httpx.MockTransport(self.vendor.handler),
            generate=type(generate)(
                generate.func,
                *generate.args,
                **(generate.keywords | {"client_factory": self.claude}),
            ),
            catalog=replace(
                real.catalog,
                repository=MemoryHashtagRepository(),
                api_key="sk-ant-test",
                selector=type(selector)(
                    selector.func,
                    *selector.args,
                    **(selector.keywords | {"client_factory": self.claude}),
                ),
            ),
        )

    def run(self, cap: Decimal) -> brand_prefill.PrefillResult:
        return mod.metered_prefill(
            TENANT,
            BRAND,
            "instagram",
            "@Heladeria.Demo",
            source={"kind": "alta", "meegle_work_item_id": 24854322},
            caps=mod.ALTA_CAPS,
            propose=True,
            budget_usd=cap,
            ports=self.ports,
        )

    @property
    def meter(self) -> DollarMeter:
        (meter,) = self.meters
        return meter

    def hashtags(self) -> list[dict[str, str]]:
        prefill = self.store.rows[(TENANT, BRAND)].connect[brand_prefill.PREFILL_KEY]
        return prefill["proposal"]["connect"]["hashtags"]


@pytest.mark.parametrize("cap", CAPS, ids=[str(c) for c in CAPS])
def test_complete_alta_runs_never_spend_more_than_the_cap(cap: Decimal) -> None:
    outcomes: list[str] = []
    for seed in range(SEEDS_PER_CAP):
        hashtag_catalog._choices.clear()  # noqa: SLF001 — every run pays its own catalog run
        claude = AdversarialClaude(random.Random(f"{cap}-{seed}"))
        world = AltaWorld(claude, posts_hashtags=seed % 3 != 0)
        result = world.run(cap)
        meter = world.meter
        credits = len(world.vendor.vendor_requests) * mod.SCRAPECREATORS_USD_PER_CREDIT

        # what the vendors billed, what the meter booked, what the job will record
        assert claude.billed + credits <= cap, (seed, claude.billed, credits)
        assert meter.spent_usd <= cap and meter.reserved_usd == 0
        assert result.usage.metered_usd == meter.spent_usd
        assert mod.usage_cost(result.usage) <= cap
        assert meter.overruns == 0 and result.usage.overruns == 0
        assert len(world.vendor.vendor_requests) <= mod.ALTA_SCRAPECREATORS_CREDITS
        # no turn was ever sent above the Alta's limits
        for request in claude.requests:
            assert request["max_tokens"] <= max(mod.ALTA_RUBRO_MAX_TOKENS, 1_200)
        catalog_turns = [
            r for r in claude.requests if from_profile.TOOL not in [t["name"] for t in r["tools"]]
        ]
        assert len(catalog_turns) <= mod.ALTA_CATALOG_MAX_TURNS
        assert result.usage.claude_calls <= mod.ALTA_CLAUDE_CALLS
        outcomes.append(result.outcome.value)
    assert set(outcomes) == {PrefillOutcome.OK.value}, outcomes


def test_at_the_founders_cap_most_runs_are_neither_lowered_nor_refused() -> None:
    """The meter is a ceiling, not the usual path: with honest answers at US$0.15 no turn
    is lowered or refused."""
    lowered = refused = 0
    for seed in range(20):
        hashtag_catalog._choices.clear()  # noqa: SLF001
        world = AltaWorld(AdversarialClaude(random.Random(seed), mode="choose"))
        assert world.run(Decimal("0.15")).ok
        lowered += world.meter.lowered_turns
        refused += world.meter.refused_turns
    assert (lowered, refused) == (0, 0)


def test_at_a_tiny_cap_the_turns_are_refused_and_nothing_is_sent() -> None:
    claude = AdversarialClaude(random.Random(7), mode="choose")
    world = AltaWorld(claude)
    result = world.run(Decimal("0.008"))
    assert result.ok and claude.requests == []
    assert result.usage.refused_turns == 2  # the rubro's first turn, the catalog's first
    assert world.hashtags()  # the account's own tags still fill the proposal


# --------------------------------------------------------------------------------------
# A cut catalog run falls back — never to the rule path, never to a failed Alta
# --------------------------------------------------------------------------------------


class _Scripted(AdversarialClaude):
    """The rubro answers with its tags; the catalog run is cut by `max_tokens`."""

    def create(self, **kwargs: Any) -> _Response:
        names = [t["name"] for t in kwargs["tools"]]
        if from_profile.TOOL in names:
            self.mode = "choose"
        else:
            self.mode = "truncate"
        return super().create(**kwargs)


def test_a_cut_catalog_run_falls_back_to_the_accounts_own_tags() -> None:
    world = AltaWorld(_Scripted(random.Random(3)))
    result = world.run(Decimal("0.15"))
    assert result.ok and result.written
    tags = {p["tag"] for p in world.hashtags()}
    assert tags == {"cucuta", "helados", "postres", "yogurt"}  # the account's own
    runs = world.store.rows[(TENANT, BRAND)].connect[brand_prefill.PREFILL_KEY]["provenance"]
    steps = [r["step"] for r in runs["claude"]]
    assert steps == ["rubro", "hashtags_catalog"]
    assert result.usage.claude_tokens_complete is True  # the cut run's tokens are known


def test_without_own_tags_a_cut_catalog_run_falls_back_to_the_rubro_runs_tags() -> None:
    world = AltaWorld(_Scripted(random.Random(3)), posts_hashtags=False)
    result = world.run(Decimal("0.15"))
    assert result.ok and result.written
    assert [p["tag"] for p in world.hashtags()] == ["helados", "yogur"]
    assert {p["origin"] for p in world.hashtags()} == {"ai"}
    assert result.usage.claude_calls == 2  # no creation run


def test_a_catalog_run_the_meter_refuses_falls_back_too() -> None:
    class RubroOnly(AdversarialClaude):
        def create(self, **kwargs: Any) -> _Response:
            response = super().create(**kwargs)
            return response

    claude = RubroOnly(random.Random(5), mode="choose")
    world = AltaWorld(claude, posts_hashtags=False)
    # enough for the credits and the rubro's first turn, not for a catalog turn
    rubro_turn = worst_turn_usd(SONNET, 6_000, mod.ALTA_RUBRO_MAX_TOKENS)
    assert rubro_turn is not None
    result = world.run(Decimal("0.0038") + rubro_turn)
    assert result.ok
    assert result.usage.refused_turns >= 1
    assert [p["tag"] for p in world.hashtags()] == ["helados", "yogur"]
    assert all(from_profile.TOOL in [t["name"] for t in r["tools"]] for r in claude.requests)


def test_the_cut_never_reaches_the_invitation() -> None:
    """The worker's outcome of a cut run is OK: the Alta comments «propuesta» and the
    invitation, sent before the job was enqueued, is never retried."""
    world = AltaWorld(_Scripted(random.Random(3)))
    result = world.run(Decimal("0.15"))
    assert mod.comment_for(result.outcome.value) == mod.COMMENT_OK


# --------------------------------------------------------------------------------------
# The web wizard's path is unchanged
# --------------------------------------------------------------------------------------


def test_the_wizards_rubro_run_keeps_4000_tokens_and_two_attempts_without_a_meter() -> None:
    claude = AdversarialClaude(random.Random(1), mode="never_choose")
    account = from_profile.AccountText(handle="heladeria", bio="Helados de yogur en Cúcuta")
    with pytest.raises(ClaudeToolError):
        from_profile.generate(account, api_key="sk", max_tags=5, client_factory=claude)
    assert [r["max_tokens"] for r in claude.requests] == [4_000, 4_000]
    assert from_profile.MAX_TOKENS == 4_000 and from_profile.ATTEMPTS == 2


def test_the_wizards_catalog_run_keeps_8_turns_of_16000_at_medium() -> None:
    claude = AdversarialClaude(random.Random(1), mode="never_choose")

    class Catalog:
        def search(self, query: str) -> list[Any]:
            return []

        def niche(self, key: str) -> list[Any]:
            return []

    brand = hashtag_ai.BrandProfile(handle="heladeria", bio="", category="", rubro=("helados",))
    with pytest.raises(ClaudeToolError):
        hashtag_ai.select_hashtags(
            brand, Catalog(), {"food_drink": "Comida"}, api_key="sk", client_factory=claude
        )
    assert len(claude.requests) == 2  # a nudge, then it gives up: same as before
    assert {r["max_tokens"] for r in claude.requests} == {16_000}
    assert {r["output_config"]["effort"] for r in claude.requests} == {"medium"}
    assert hashtag_ai.MAX_TURNS == 8 and hashtag_ai.SELECT_MAX_TOKENS == 16_000
    assert all("último turno" not in seen for seen in claude.seen)


def test_the_wizards_catalog_failure_still_takes_the_rule_path() -> None:
    def failing(*args: Any, **kwargs: Any) -> Any:
        raise ClaudeToolError("cut", stats=None)

    seed = brand_prefill.discovery_seed.seed_from_profile(
        {"username": "heladeria", "category": "Heladería", "bio": "Helados"}
    )
    choice = hashtag_catalog.suggest_hashtags(
        TENANT,
        seed,
        repository=MemoryHashtagRepository(),
        api_key="sk",
        selector=failing,
    )
    assert choice.by == "rule" and choice.attempted
    alta = hashtag_catalog.suggest_hashtags(
        TENANT,
        seed,
        repository=MemoryHashtagRepository(),
        api_key="sk",
        selector=failing,
        rule_fallback=False,
    )
    assert alta.tags == () and alta.by == "ai" and alta.attempted


def test_the_wizards_ports_have_no_meter() -> None:
    ports = mod.bounded_ports()
    assert set(ports.generate.keywords) == {"client_factory"}
    assert set(ports.catalog.selector.keywords) == {"client_factory"}
    assert ports.catalog.rule_fallback is True
    assert claude_tools.create_turn.__kwdefaults__["budget"] is None


def test_the_last_turn_hint_goes_only_before_the_last_turn() -> None:
    class Catalog:
        def search(self, query: str) -> list[Any]:
            return [hashtag_ai.Candidate("helados", 10, "food_drink")]

        def niche(self, key: str) -> list[Any]:
            return []

    class Searcher(AdversarialClaude):
        def _answer(self, kwargs: dict[str, Any]) -> list[_Block]:
            return [
                _Block("tool_use", name=hashtag_ai.SEARCH_TOOL, input={"consulta": "x"}, id="t")
            ]

    searcher = Searcher(random.Random(2), mode="choose")
    brand = hashtag_ai.BrandProfile(handle="heladeria", bio="", category="", rubro=("helados",))
    with pytest.raises(ClaudeToolError):
        hashtag_ai.select_hashtags(
            brand,
            Catalog(),
            {"food_drink": "Comida"},
            api_key="sk",
            client_factory=searcher,
            max_turns=3,
            max_tokens=1_200,
            last_turn_hint=True,
        )
    hinted = ["último turno" in seen for seen in searcher.seen]
    assert hinted == [False, False, True]

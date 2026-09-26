"""`qualify_api.hashtags.ai` without the network: a scripted fake client stands in for
the SDK, so these pin what goes OUT (model, effort, tools, tool choice, explicit key),
how the agent loop answers each tool call, and what the module lets back IN (only tags a
tool showed, only valid kinds) — the guards that make a model answer safe to act on.
Model quality is measured separately, by hand, in `evals/hashtag_ai`."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from qualify_api.hashtags.ai import (
    CHOOSE_TOOL,
    CLASSIFY_MODEL,
    CLASSIFY_TOOL,
    NICHE_TOOL,
    SEARCH_TOOL,
    SELECT_EFFORT,
    SELECT_MODEL,
    BrandProfile,
    Candidate,
    HashtagAIError,
    MissingAPIKey,
    ModelConfig,
    api_key_from_env,
    classify_hashtags,
    select_hashtags,
)

NICHES = {"food_drink": "Comida y bebida", "technology": "Tecnología"}


def _use(name: str, arguments: dict[str, Any], call_id: str = "tu_1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input=arguments)


def _text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


class ScriptedClient:
    """Returns one scripted turn per `messages.create`, and records every request."""

    def __init__(self, *turns: list[Any], stop_reason: str | None = None) -> None:
        self.turns = list(turns)
        self.stop_reason = stop_reason
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        content = self.turns.pop(0) if self.turns else [_text("sin herramientas")]
        stop = self.stop_reason or (
            "tool_use" if any(b.type == "tool_use" for b in content) else "end_turn"
        )
        return SimpleNamespace(
            stop_reason=stop,
            content=[] if stop == "refusal" else content,
            model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0),
        )


def _factory(client: ScriptedClient, keys: list[str] | None = None) -> Any:
    def build(api_key: str) -> ScriptedClient:
        if keys is not None:
            keys.append(api_key)
        return client

    return build


class FakeCatalog:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.niches: list[str] = []

    def search(self, query: str) -> list[Candidate]:
        self.queries.append(query)
        if "burger" in query:
            return [Candidate("burger", 6), Candidate("burgers", 4)]
        return []

    def niche(self, key: str) -> list[Candidate]:
        self.niches.append(key)
        return [Candidate("foodie", 60, "food_drink")]


BRAND = BrandProfile(
    handle="smashclub.ccs",
    bio="Smash burgers",
    rubro=("hamburguesería",),
    own_hashtags=("smashburger",),
)
STARTING = [
    Candidate("hamburguesas", 21, "food_drink"),
    Candidate("hamburguesa", 15),
    Candidate("comidacallejera", 22),
    Candidate("smashburgers", 3),
]


def _choose(*picks: tuple[str, str], call_id: str = "tu_9") -> list[Any]:
    return [
        _use(
            CHOOSE_TOOL, {"picks": [{"tag": t, "fit": f, "reason": "r"} for t, f in picks]}, call_id
        )
    ]


def _select(client: ScriptedClient, catalog: FakeCatalog | None = None, **kw: Any) -> Any:
    return select_hashtags(
        BRAND,
        catalog or FakeCatalog(),
        NICHES,
        api_key=kw.pop("api_key", "k"),
        starting=kw.pop("starting", STARTING),
        client_factory=kw.pop("client_factory", _factory(client)),
        **kw,
    )


# -- select: the agent loop --------------------------------------------------------------


def test_select_sends_strict_tools_with_the_chosen_model_and_an_explicit_key() -> None:
    client = ScriptedClient(_choose())
    keys: list[str] = []
    _select(client, client_factory=_factory(client, keys))
    call = client.calls[0]
    assert keys == ["k"]
    assert call["model"] == SELECT_MODEL
    assert call["output_config"] == {"effort": SELECT_EFFORT}
    # a thinking model gets `auto`; the loop itself checks the final tool was called
    assert call["tool_choice"] == {"type": "auto"}
    names = [t["name"] for t in call["tools"]]
    assert names == [SEARCH_TOOL, NICHE_TOOL, CHOOSE_TOOL]
    assert all(t["strict"] for t in call["tools"])
    niche_enum = call["tools"][1]["input_schema"]["properties"]["nicho"]["enum"]
    assert niche_enum == list(NICHES)
    assert "temperature" not in call and "thinking" not in call
    assert "hamburguesas" in call["messages"][0]["content"]


def test_the_loop_runs_the_tools_and_feeds_every_result_back_at_once() -> None:
    catalog = FakeCatalog()
    client = ScriptedClient(
        [
            _text("busco variantes"),
            _use(SEARCH_TOOL, {"consulta": "burger"}, "tu_1"),
            _use(NICHE_TOOL, {"nicho": "food_drink"}, "tu_2"),
        ],
        _choose(("burger", "alta"), ("foodie", "media")),
    )
    picks, stats = _select(client, catalog)
    assert catalog.queries == ["burger"] and catalog.niches == ["food_drink"]
    second = client.calls[1]["messages"]
    assert second[1]["role"] == "assistant"  # the whole content, thinking included
    results = second[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["tu_1", "tu_2"]
    assert "burger (6 cuentas)" in results[0]["content"]
    assert [(p.tag, p.fit) for p in picks] == [("burger", "alta"), ("foodie", "media")]
    assert (stats.turns, stats.tool_calls, stats.input_tokens) == (2, 3, 2000)


def test_only_tags_a_tool_showed_can_be_chosen() -> None:
    client = ScriptedClient(
        _choose(
            ("burgerlovers", "alta"),  # never shown → invented
            ("smashburger", "alta"),  # the brand's own
            ("smashburgers", "alta"),  # a plural of the brand's own
            ("hamburguesas", "alta"),
            ("hamburguesa", "alta"),  # the same word as a pick
            ("comidacallejera", "rara"),  # invalid fit → media
        )
    )
    picks, _ = _select(client)
    assert [(p.tag, p.fit) for p in picks] == [
        ("hamburguesas", "alta"),
        ("comidacallejera", "media"),
    ]


@pytest.mark.parametrize(
    ("slug", "others", "same"),
    [
        ("hamburguesa", {"hamburguesas"}, True),
        ("programadores", {"programador"}, True),
        ("perrocaliente", {"perroscalientes"}, True),  # plural mid-tag, measured live
        ("postres", {"postre"}, True),
        ("pastel", {"pasteleria"}, False),
        ("burger", {"hamburguesa"}, False),
        ("moda", {"modafemenina"}, False),
    ],
)
def test_same_word_is_plural_blind(slug: str, others: set[str], same: bool) -> None:
    from qualify_api.hashtags.ai import _same_word

    assert _same_word(slug, others) is same


def test_select_respects_max_picks() -> None:
    client = ScriptedClient(_choose(("hamburguesas", "alta"), ("comidacallejera", "alta")))
    picks, _ = _select(client, max_picks=1)
    assert [p.tag for p in picks] == ["hamburguesas"]


def test_an_empty_choice_is_an_answer() -> None:
    picks, stats = _select(ScriptedClient(_choose()))
    assert picks == [] and stats.turns == 1


def test_a_model_that_stops_without_choosing_is_nudged_once_then_fails() -> None:
    client = ScriptedClient([_text("listo")], _choose(("hamburguesas", "alta")))
    picks, _ = _select(client)
    assert [p.tag for p in picks] == ["hamburguesas"]
    assert CHOOSE_TOOL in client.calls[1]["messages"][-1]["content"]

    with pytest.raises(HashtagAIError):
        _select(ScriptedClient([_text("listo")], [_text("de verdad listo")]))


def test_an_unknown_niche_is_a_tool_error_not_a_crash() -> None:
    client = ScriptedClient([_use(NICHE_TOOL, {"nicho": "mascotas"})], _choose())
    _select(client)
    result = client.calls[1]["messages"][2]["content"][0]
    assert result["is_error"] is True and "mascotas" in result["content"]


def test_a_run_that_never_ends_is_cut() -> None:
    searching = [[_use(SEARCH_TOOL, {"consulta": f"q{i}"}, f"tu_{i}")] for i in range(20)]
    with pytest.raises(HashtagAIError):
        _select(ScriptedClient(*searching), max_turns=3)


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_an_unusable_turn_raises(stop_reason: str) -> None:
    with pytest.raises(HashtagAIError):
        _select(ScriptedClient(_choose(), stop_reason=stop_reason))


# -- classify: one forced tool call -------------------------------------------------------


def _classified(*rows: tuple[str, str, str, str]) -> list[Any]:
    results = [{"tag": t, "kind": k, "niche": n, "country_code": c} for t, k, n, c in rows]
    return [_use(CLASSIFY_TOOL, {"results": results})]


def test_classify_forces_its_tool_on_haiku_and_drops_what_it_was_not_asked() -> None:
    client = ScriptedClient(
        _classified(
            ("hamburguesas", "topic", "food_drink", ""),
            ("cucutafood", "place", "food_drink", "co"),
            ("fyp", "generic", "none", "CO"),
            ("peluqueriacanina", "topic", "none", ""),
            ("nuncapreguntado", "topic", "none", ""),
            ("raro", "unknown", "none", ""),
        )
    )
    results, stats = classify_hashtags(
        ["#Hamburguesas", "cucutafood", "fyp", "peluqueriacanina", "raro"],
        NICHES,
        api_key="k",
        client_factory=_factory(client),
    )
    call = client.calls[0]
    assert call["model"] == CLASSIFY_MODEL
    assert call["tool_choice"] == {"type": "tool", "name": CLASSIFY_TOOL}
    assert "output_config" not in call
    assert call["tools"][0]["strict"] is True
    assert [(r.tag, r.kind, r.niche, r.country_code) for r in results] == [
        ("hamburguesas", "topic", "food_drink", None),
        ("cucutafood", "place", None, "CO"),
        ("fyp", "generic", None, None),
        ("peluqueriacanina", "topic", None, None),
    ]
    assert stats.tool_calls == 1


def test_classify_on_a_thinking_model_uses_auto_and_stays_under_the_ceiling() -> None:
    client = ScriptedClient(_classified(("a", "generic", "none", "")))
    classify_hashtags(
        ["a"],
        NICHES,
        api_key="k",
        config=ModelConfig("claude-sonnet-5", "medium"),
        client_factory=_factory(client),
    )
    call = client.calls[0]
    assert call["tool_choice"] == {"type": "auto"}
    assert call["max_tokens"] <= 16000


def test_classify_without_its_tool_call_raises() -> None:
    with pytest.raises(HashtagAIError):
        classify_hashtags(
            ["a"], NICHES, api_key="k", client_factory=_factory(ScriptedClient([_text("?")]))
        )


def test_classify_refuses_an_oversized_batch() -> None:
    with pytest.raises(ValueError):
        classify_hashtags([f"t{i}" for i in range(500)], NICHES, api_key="k")


def test_missing_key_is_its_own_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingAPIKey):
        api_key_from_env()
    monkeypatch.setenv("QUALIFY_ANTHROPIC_API_KEY", " sk-x ")
    assert api_key_from_env() == "sk-x"

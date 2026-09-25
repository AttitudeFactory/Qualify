"""`qualify_api.hashtags.ai` without the network: a fake client stands in for the SDK, so
these pin what goes OUT (model, effort, schema, explicit key) and what the module lets
back IN (only offered tags, only valid kinds) — the guards that make a model answer safe
to act on. Model quality is measured separately, by hand, in `evals/hashtag_ai`."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from qualify_api.hashtags.ai import (
    CLASSIFY_MODEL,
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


class FakeClient:
    def __init__(self, payload: Any, *, stop_reason: str = "end_turn") -> None:
        self.payload = payload
        self.stop_reason = stop_reason
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        content = [] if self.stop_reason == "refusal" else [SimpleNamespace(type="text", text=text)]
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=content,
            model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0),
        )


def _factory(client: FakeClient, keys: list[str] | None = None) -> Any:
    def build(api_key: str) -> FakeClient:
        if keys is not None:
            keys.append(api_key)
        return client

    return build


BRAND = BrandProfile(
    handle="smashclub.ccs",
    bio="Smash burgers",
    rubro=("hamburguesería",),
    own_hashtags=("smashburger",),
)
CANDIDATES = [
    Candidate("hamburguesas", 21, "food_drink"),
    Candidate("hamburguesa", 15),
    Candidate("comidacallejera", 22),
    Candidate("smashburger", 9),
]


def test_select_sends_the_chosen_model_with_an_explicit_key() -> None:
    client = FakeClient({"picks": []})
    keys: list[str] = []
    select_hashtags(BRAND, CANDIDATES, api_key="sk-test", client_factory=_factory(client, keys))
    call = client.calls[0]
    assert keys == ["sk-test"]
    assert call["model"] == SELECT_MODEL
    assert call["output_config"]["effort"] == SELECT_EFFORT
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in call and "thinking" not in call
    assert "smashburger" in call["messages"][0]["content"]


def test_select_keeps_only_offered_new_and_distinct_tags() -> None:
    client = FakeClient(
        {
            "picks": [
                {"tag": "#Hamburguesas", "fit": "alta", "reason": "mismo producto"},
                {"tag": "burgerlovers", "fit": "alta", "reason": "inventado"},
                {"tag": "smashburger", "fit": "alta", "reason": "ya lo usa"},
                {"tag": "hamburguesas", "fit": "media", "reason": "repetido"},
                {"tag": "comidacallejera", "fit": "rara", "reason": "fit inválido"},
            ]
        }
    )
    picks, stats = select_hashtags(BRAND, CANDIDATES, api_key="k", client_factory=_factory(client))
    assert [(p.tag, p.fit) for p in picks] == [
        ("hamburguesas", "alta"),
        ("comidacallejera", "media"),
    ]
    assert stats.model_revision == SELECT_MODEL
    assert stats.cost_usd > 0


def test_select_never_spends_two_searches_on_one_word() -> None:
    """Measured live: the model picked `hamburguesas` AND `hamburguesa`. A plural of a
    pick, or of a tag the brand already uses, is dropped in code."""
    client = FakeClient(
        {
            "picks": [
                {"tag": "hamburguesas", "fit": "alta", "reason": "x"},
                {"tag": "hamburguesa", "fit": "alta", "reason": "plural del anterior"},
                {"tag": "smashburgers", "fit": "alta", "reason": "plural de uno propio"},
                {"tag": "comidacallejera", "fit": "media", "reason": "otra palabra"},
            ]
        }
    )
    candidates = [*CANDIDATES, Candidate("smashburgers", 3)]
    picks, _ = select_hashtags(BRAND, candidates, api_key="k", client_factory=_factory(client))
    assert [p.tag for p in picks] == ["hamburguesas", "comidacallejera"]


def test_select_respects_max_picks() -> None:
    client = FakeClient(
        {"picks": [{"tag": t.tag, "fit": "alta", "reason": "x"} for t in CANDIDATES]}
    )
    picks, _ = select_hashtags(
        BRAND, CANDIDATES, api_key="k", max_picks=1, client_factory=_factory(client)
    )
    assert len(picks) == 1


def test_select_with_no_candidates_makes_no_call() -> None:
    client = FakeClient({"picks": []})
    picks, stats = select_hashtags(BRAND, [], api_key="k", client_factory=_factory(client))
    assert picks == [] and client.calls == [] and stats.cost_usd == 0


@pytest.mark.parametrize(
    ("payload", "stop_reason"),
    [({"picks": []}, "refusal"), ({"picks": []}, "max_tokens"), ("not json", "end_turn")],
)
def test_an_unusable_answer_raises(payload: Any, stop_reason: str) -> None:
    client = FakeClient(payload, stop_reason=stop_reason)
    with pytest.raises(HashtagAIError):
        select_hashtags(BRAND, CANDIDATES, api_key="k", client_factory=_factory(client))


def test_classify_uses_haiku_without_effort_and_drops_what_it_was_not_asked() -> None:
    client = FakeClient(
        {
            "results": [
                {"tag": "hamburguesas", "kind": "topic", "niche": "food_drink", "country_code": ""},
                {"tag": "cucutafood", "kind": "place", "niche": "food_drink", "country_code": "co"},
                {"tag": "fyp", "kind": "generic", "niche": "none", "country_code": "CO"},
                {"tag": "peluqueriacanina", "kind": "topic", "niche": "none", "country_code": ""},
                {"tag": "nuncapreguntado", "kind": "topic", "niche": "none", "country_code": ""},
                {"tag": "raro", "kind": "unknown", "niche": "none", "country_code": ""},
            ]
        }
    )
    results, _ = classify_hashtags(
        ["#Hamburguesas", "cucutafood", "fyp", "peluqueriacanina", "raro"],
        NICHES,
        api_key="k",
        client_factory=_factory(client),
    )
    call = client.calls[0]
    assert call["model"] == CLASSIFY_MODEL
    assert "effort" not in call["output_config"]
    assert [(r.tag, r.kind, r.niche, r.country_code) for r in results] == [
        ("hamburguesas", "topic", "food_drink", None),
        ("cucutafood", "place", None, "CO"),
        ("fyp", "generic", None, None),
        ("peluqueriacanina", "topic", None, None),
    ]


def test_classify_refuses_an_oversized_batch() -> None:
    with pytest.raises(ValueError):
        classify_hashtags([f"t{i}" for i in range(500)], NICHES, api_key="k")


def test_classify_with_effort_stays_within_the_non_streaming_ceiling() -> None:
    client = FakeClient({"results": []})
    classify_hashtags(
        ["a"],
        NICHES,
        api_key="k",
        config=ModelConfig("claude-sonnet-5", "medium"),
        client_factory=_factory(client),
    )
    assert client.calls[0]["max_tokens"] <= 16000


def test_missing_key_is_its_own_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingAPIKey):
        api_key_from_env()
    monkeypatch.setenv("QUALIFY_ANTHROPIC_API_KEY", " sk-x ")
    assert api_key_from_env() == "sk-x"

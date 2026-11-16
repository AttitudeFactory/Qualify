"""Hashtags for a whole caption (`qualify_api.hashtags.caption`) — no network: the
Anthropic client is a fake that answers the forced tool call."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

from qualify_api import claude_tools
from qualify_api.claude_tools import Attribution as _Attribution
from qualify_api.hashtags.caption import (
    CAPTION_MODEL,
    MAX_WATCHED,
    PROMPT_VERSION,
    PROMPT_VERSION_WITHOUT_WATCHED,
    SUGGEST_TOOL,
    SYSTEM,
    WATCHED_ADDENDUM,
    SeenTag,
    WatchedTag,
    suggest_for_caption,
)

#: m-24955649: who pays for the faked Claude calls of this module.
TEST_ATTRIBUTION = _Attribution.no_business("test")


class _FakeClient:
    def __init__(self, picks: list[dict[str, str]]) -> None:
        self.picks = picks
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        use = SimpleNamespace(type="tool_use", name=SUGGEST_TOOL, input={"hashtags": self.picks})
        return SimpleNamespace(
            content=[use],
            stop_reason="tool_use",
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=10,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )


def test_it_reads_the_whole_caption_and_keeps_clean_new_tags() -> None:
    fake = _FakeClient(
        [
            {"tag": "#HeladoArtesanal", "tipo": "nicho", "motivo": "Habla de helado hecho a mano"},
            {"tag": "postres", "tipo": "popular", "motivo": "Muy usado en comida dulce"},
            {"tag": "taro", "tipo": "nicho", "motivo": "Ya elegido"},
            {"tag": "ok", "tipo": "popular", "motivo": "Demasiado corto"},
            {"tag": "caracas", "tipo": "otro", "motivo": "Tipo inválido"},
            {"tag": "postres", "tipo": "popular", "motivo": "Repetido"},
        ]
    )
    caption = "Llegó el nuevo sabor de taro a nuestra heladería en Caracas. Solo este mes."
    picks = suggest_for_caption(
        caption,
        seen=[SeenTag("postres", 1200)],
        current=["taro"],
        api_key="test",
        client_factory=lambda _key: fake,
        attribution=TEST_ATTRIBUTION,
    )
    assert [(p.tag, p.kind) for p in picks] == [
        ("heladoartesanal", "nicho"),
        ("postres", "popular"),
    ]
    assert picks[1].seen_count == 1200 and picks[0].seen_count == 0
    sent = fake.calls[0]
    assert sent["model"] == CAPTION_MODEL.model_id
    assert caption in sent["messages"][0]["content"]  # the whole text, not keywords
    assert "postres (1200)" in sent["messages"][0]["content"]  # grounded in the catalog
    assert sent["tool_choice"] == {"type": "tool", "name": SUGGEST_TOOL}


def test_an_empty_caption_asks_nothing() -> None:
    def factory(_key: str) -> Any:
        raise AssertionError("no client for an empty caption")

    assert (
        suggest_for_caption(
            "   ", api_key="test", client_factory=factory, attribution=TEST_ATTRIBUTION
        )
        == []
    )


# -- m-25032581: the tags that accompany the rubro's own on the most watched videos ----


def _request(fake: _FakeClient) -> dict[str, Any]:
    """What reaches the model, the attribution aside (it never leaves the process)."""
    sent = fake.calls[0]
    return {k: sent[k] for k in ("system", "messages", "tools", "tool_choice", "max_tokens")}


def _system(request: dict[str, Any]) -> str:
    system = request["system"]
    if isinstance(system, str):
        return system
    return "".join(block["text"] for block in system)


def _ask(**extra: Any) -> tuple[_FakeClient, list[Any]]:
    fake = _FakeClient([])
    picks = suggest_for_caption(
        "Ensalada fresca en San Cristóbal",
        seen=[SeenTag("ensaladas", 7)],
        current=["shawarma"],
        api_key="test",
        client_factory=lambda _key: fake,
        attribution=TEST_ATTRIBUTION,
        **extra,
    )
    return fake, picks


#: sha256 of `_request` for `_ask()` as caption-hashtags/1 sent it (measured on main at
#: d6098140, before m-25032581): without watched tags the request must not move a byte.
_V1_REQUEST_SHA256 = "6505c49ff218059d106ea5ff9b0b25406e1cc405a565a76e1dfbb821425ba40e"


def _digest(request: dict[str, Any]) -> str:
    payload = json.dumps(request, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def test_without_watched_tags_the_request_is_the_previous_one_byte_for_byte() -> None:
    plain, _ = _ask()
    empty, _ = _ask(watched=())
    assert _request(plain) == _request(empty)
    assert _digest(_request(plain)) == _V1_REQUEST_SHA256
    assert _system(_request(plain)) == SYSTEM


def test_the_prompt_version_is_booked_with_the_call(monkeypatch: Any) -> None:
    booked: list[Any] = []
    monkeypatch.setattr(claude_tools, "_consumption_sink", booked.append)
    _ask()
    _ask(watched=[WatchedTag("comidasaludable", 2_400_000, 1)])
    versions = [record.attribution.prompt_version for record in booked]
    assert versions == [PROMPT_VERSION_WITHOUT_WATCHED, PROMPT_VERSION]
    assert PROMPT_VERSION == "caption-hashtags/2"


def test_watched_tags_add_the_addendum_and_a_block() -> None:
    plain, _ = _ask()
    fake, _ = _ask(
        watched=[
            WatchedTag("comidasaludable", 2_400_000, 1),
            WatchedTag("recetasfaciles", 12_500, 3),
            WatchedTag("ensaladasaludable", 850, 2),
        ]
    )
    sent, before = _request(fake), _request(plain)
    assert _system(sent) == f"{SYSTEM}\n\n{WATCHED_ADDENDUM}"
    message = sent["messages"][0]["content"]
    assert "- comidasaludable (2,4 M de vistas, 1 video)" in message
    assert "- recetasfaciles (12 mil vistas, 3 videos)" in message
    assert "- ensaladasaludable (850 vistas, 2 videos)" in message
    # the block is added, nothing of the previous message is changed or lost
    for line in before["messages"][0]["content"].splitlines():
        assert line in message
    assert message.index("ensaladas (7)") < message.index("comidasaludable")
    assert message.index("comidasaludable") < message.index("Ya elegidos")
    assert sent["tools"] == before["tools"] and sent["tool_choice"] == before["tool_choice"]


def test_at_most_twenty_watched_tags_reach_the_model() -> None:
    many = [WatchedTag(f"etiqueta{i:02d}", 1000 * (30 - i), 1) for i in range(30)]
    fake, _ = _ask(watched=many)
    message = _request(fake)["messages"][0]["content"]
    shown = [line for line in message.splitlines() if line.startswith("- etiqueta")]
    assert len(shown) == MAX_WATCHED == 20
    assert "etiqueta19" in message and "etiqueta20" not in message


def test_a_watched_pick_survives_the_cleaning() -> None:
    fake = _FakeClient(
        [
            {"tag": "#ComidaSaludable", "tipo": "popular", "motivo": "Acompaña a ensaladas"},
            {"tag": "ensaladas", "tipo": "nicho", "motivo": "Del catálogo"},
        ]
    )
    picks = suggest_for_caption(
        "Ensalada fresca",
        seen=[SeenTag("ensaladas", 7)],
        watched=[WatchedTag("comidasaludable", 2_400_000, 1)],
        api_key="test",
        client_factory=lambda _key: fake,
        attribution=TEST_ATTRIBUTION,
    )
    assert [(p.tag, p.seen_count) for p in picks] == [("comidasaludable", 0), ("ensaladas", 7)]

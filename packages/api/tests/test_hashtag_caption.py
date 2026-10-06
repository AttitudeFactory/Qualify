"""Hashtags for a whole caption (`qualify_api.hashtags.caption`) — no network: the
Anthropic client is a fake that answers the forced tool call."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from qualify_api.hashtags.caption import (
    CAPTION_MODEL,
    SUGGEST_TOOL,
    SeenTag,
    suggest_for_caption,
)


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

    assert suggest_for_caption("   ", api_key="test", client_factory=factory) == []

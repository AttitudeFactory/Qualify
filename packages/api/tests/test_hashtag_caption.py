"""Hashtags for a whole caption (`qualify_api.hashtags.caption`) — no network: the
Anthropic client is a fake that answers the forced tool call."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

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
    is_platform_tag,
    named_in_text,
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


# -- UX review of m-25032581: «Mejor», platform tags, the reason the owner reads ---------


def test_the_addendum_tells_the_model_how_to_write_the_reason() -> None:
    assert WATCHED_ADDENDUM.endswith(
        "- El motivo dice qué palabra o idea del texto nombra el hashtag. No menciones "
        "TikTok, videos, vistas, «virales», «audiencia» ni el rubro, y escribe sin palabras "
        "en inglés."
    )


_DIRECTIONS = "¿Cómo llegar? Estamos en la carrera 5 con calle 10, frente al parque."
_SHAWARMA = "Shawarma de pollo con salsa de ajo, recién salido del trompo."


@pytest.mark.parametrize(
    ("tag", "caption", "named"),
    [
        ("carne", _DIRECTIONS, False),  # measured: a directions text marked «Mejor»
        ("pollo", _DIRECTIONS, False),
        ("comidasaludable", _SHAWARMA, False),  # the text never says «saludable»
        ("pollo", _SHAWARMA, True),
        ("pollo", "Hoy: el POLLO jugoso de siempre", True),
        ("pollo", "Pollos asados", True),  # the end may run into the word
        ("pollo", "Ensalada de repollo", False),  # it must start a word
        ("ensalada", "Una ensalada fresca", True),
        ("ensaladas", "Una ensalada fresca", True),  # plural either way
        ("ensalada", "Tenemos ensaladas", True),
        ("ensaladasaludable", "Ensalada saludable, sin culpa.", True),
        ("ensaladasaludable", "Ensalada muy saludable", False),
        ("cafe", "Un café de especialidad", True),  # accents fold
        ("recetasfaciles", "Una receta fácil", False),  # nothing smarter on purpose
        ("sol", "Disfruta el sol", True),  # short: whole word only
        ("sol", "Soleado y rico", False),
        ("sol", "", False),
        ("#Pollo", _SHAWARMA, True),
    ],
)
def test_named_in_text(tag: str, caption: str, named: bool) -> None:
    assert named_in_text(tag, caption) is named


@pytest.mark.parametrize(
    ("tag", "platform"),
    [
        ("foodtok", True),
        ("booktok", True),
        ("FoodTok", True),
        ("tiktok", True),
        ("tiktokfood", True),
        ("comidatiktok", True),
        ("autoestok", True),  # merely ends in «tok»: dropped, on purpose (docstring)
        ("stock", False),
        ("tokio", False),
        ("tok", False),
        ("comidasaludable", False),
    ],
)
def test_platform_tags(tag: str, platform: bool) -> None:
    assert is_platform_tag(tag) is platform


def test_platform_tags_are_dropped_before_the_cap() -> None:
    platform = [WatchedTag(f"plato{i:02d}tok", 9_000_000, 9) for i in range(5)]
    useful = [WatchedTag(f"etiqueta{i:02d}", 1000, 1) for i in range(MAX_WATCHED)]
    fake, _ = _ask(watched=[*platform, WatchedTag("tiktokfood", 1, 1), *useful])
    message = _request(fake)["messages"][0]["content"]
    assert "tok" not in message.replace("TikTok", "")
    assert all(f"- etiqueta{i:02d} (" in message for i in range(MAX_WATCHED))


def test_only_platform_tags_send_the_previous_request() -> None:
    plain, _ = _ask()
    only_platform, _ = _ask(watched=[WatchedTag("foodtok", 2_000_000, 3)])
    assert _request(only_platform) == _request(plain)


def test_a_watched_pick_is_flagged_unless_the_catalog_has_it() -> None:
    fake = _FakeClient(
        [
            {"tag": "comidasaludable", "tipo": "popular", "motivo": "Habla de comida sana"},
            {"tag": "ensaladas", "tipo": "nicho", "motivo": "Del catálogo"},
            {"tag": "almuerzo", "tipo": "nicho", "motivo": "Lo dice el texto"},
        ]
    )
    picks = suggest_for_caption(
        "Ensalada fresca para el almuerzo",
        seen=[SeenTag("ensaladas", 7)],
        watched=[WatchedTag("comidasaludable", 2_400_000, 1), WatchedTag("ensaladas", 9, 1)],
        api_key="test",
        client_factory=lambda _key: fake,
        attribution=TEST_ATTRIBUTION,
    )
    assert [(p.tag, p.watched) for p in picks] == [
        ("comidasaludable", True),
        ("ensaladas", False),  # also a `seen` catalog tag
        ("almuerzo", False),
    ]
    assert all(not p.watched for p in _ask()[1])  # without watched tags nothing is flagged

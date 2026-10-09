"""`qualify_api.creative.trace` (§ request 2026-10-05: "imprime en consola el prompt que
va al generador y el gasto"): the readable prompt and spend blocks, and the off switch."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

import pytest

from qualify_api.creative import trace


@dataclass
class _Call:
    provider: str
    model_id: str
    unit: str
    cost_usd: Decimal
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    pieces: int = 0


def test_the_copy_prompt_is_printed_whole(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="qualify_api.creative.trace")
    trace.copy_prompt(
        draft_id=uuid4(),
        kind="avatar_video",
        chain=("anthropic",),
        variants=3,
        system="Eres la voz de Bianki.\nNunca digas barato.",
        user="Encargo: shawarma mixto, 2x1 el jueves.",
    )
    text = caplog.text
    assert "PROMPT → Claude (copy)" in text and "variantes=3" in text
    assert "Eres la voz de Bianki.\nNunca digas barato." in text
    assert "Encargo: shawarma mixto, 2x1 el jueves." in text


def test_the_preview_is_marked_as_not_sent(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="qualify_api.creative.trace")
    trace.copy_prompt(
        draft_id=None, kind="creator_script", chain=("anthropic",), variants=3, system="s", user="u"
    )
    assert "VISTA PREVIA DEL PROMPT → Claude (copy)" in caplog.text
    assert "aún no se envió nada" in caplog.text and "draft=" not in caplog.text


def test_the_spend_lists_every_call_the_total_and_the_budget(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="qualify_api.creative.trace")
    calls = [
        _Call("anthropic", "claude-sonnet-5", "token", Decimal("0.012345"), 1200, 300),
        _Call("heygen", "heygen_avatar_iv", "second", Decimal("0.833750"), pieces=13),
    ]
    trace.spend(
        draft_id=uuid4(),
        kind="avatar_video",
        calls=calls,
        total=Decimal("0.846095"),
        budget_remaining=Decimal("49.15"),
        outcome="ok",
    )
    text = caplog.text
    assert "GASTO" in text and "tokens in=1200 out=300" in text and "13 second(s)" in text
    assert "USD 0.012345" in text and "USD 0.833750" in text
    assert "TOTAL de este borrador: USD 0.846095" in text
    assert "Presupuesto mensual restante: USD 49.15" in text


def test_a_media_request_skips_empty_fields(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="qualify_api.creative.trace")
    trace.media_request(
        draft_id=uuid4(),
        provider="HeyGen",
        what="video con avatar",
        fields={"guion (lo que dice el avatar)": "Hola, pide tu shawarma.", "locale": None},
    )
    assert "PROMPT → HeyGen (video con avatar)" in caplog.text
    assert "Hola, pide tu shawarma." in caplog.text and "locale" not in caplog.text


def test_the_trace_can_be_switched_off(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.INFO, logger="qualify_api.creative.trace")
    monkeypatch.setenv(trace.ENV_FLAG, "0")
    trace.copy_prompt(draft_id=uuid4(), kind="x", chain=(), variants=1, system="s", user="u")
    assert caplog.text == ""

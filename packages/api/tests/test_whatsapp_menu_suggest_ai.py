"""«Sugerir con IA» on the WhatsApp menu (m-24936838), over a fake Claude client: what
the model is given, and every rule the post-processing enforces."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import EmojiPolicy
from qualify_creative.schemas import BrandKit, ToneAxes

from qualify_api.claude_tools import request_bytes, turn_input_ceiling, worst_turn_usd
from qualify_api.whatsapp.menus import suggest_ai
from qualify_api.whatsapp.menus.starter import HOURS_TEXT
from qualify_api.whatsapp.menus.suggest_ai import (
    MAX_TOKENS,
    MENU_CLOSING,
    SUGGEST_BUDGET_USD,
    SYSTEM_PROMPT,
    TOOL_NAME,
    SuggestInput,
    SuggestUnavailable,
    render_request,
    suggest_for_brand,
    suggest_text,
)


class FakeMessages:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[Any]) -> None:
        self.messages = FakeMessages(responses)

    def factory(self, key: str) -> FakeClient:
        return self


def _answer(
    text: str,
    *,
    missing: list[str] | None = None,
    filled: list[tuple[str, str]] | None = None,
    added: list[str] | None = None,
    stop: str = "tool_use",
) -> Any:
    return SimpleNamespace(
        model="claude-sonnet-5-5-20261001",
        stop_reason=stop,
        usage=SimpleNamespace(input_tokens=900, output_tokens=150, cache_read_input_tokens=0),
        content=[
            SimpleNamespace(
                type="tool_use",
                name=TOOL_NAME,
                input={
                    "text": text,
                    "missing": missing or [],
                    "filled_gaps": [{"gap": g, "fact": f} for g, f in filled or []],
                    "added_facts": added or [],
                },
            )
        ],
    )


def _kit(**overrides: Any) -> BrandKit:
    values: dict[str, Any] = {
        "brand_id": uuid4(),
        "positioning": "Shawarma y ensaladas en Cúcuta",
        "audience": "Vecinos que piden a domicilio",
        "regional_variant": "es-CO",
        "tone_axes": ToneAxes(
            formal_casual=75, sober_enthusiastic=60, technical_plain=90, brief_elaborate=20
        ),
        "banned_words": ("barato",),
        "forbidden_claims": ("el mejor de la ciudad",),
        "emoji_policy": EmojiPolicy.NONE,
    }
    values.update(overrides)
    return BrandKit(**values)


def _hours(**overrides: Any) -> SuggestInput:
    values: dict[str, Any] = {
        "kind": "answer",
        "answer_name": "Horario",
        "current_text": HOURS_TEXT,
        "facts": (("Nombre del negocio", "Bianki"), ("qué días", "lunes a sábado")),
        "other_answers": (("Domicilio", "Llevamos tu pedido a [barrios o zona]."),),
    }
    values.update(overrides)
    return SuggestInput(**values)


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_ANTHROPIC_API_KEY", "test-key")


def test_the_model_gets_the_facts_the_other_answers_the_brand_and_the_field() -> None:
    message = render_request(_hours(previous_text="Abrimos de lunes a sábado."), _kit())
    for expected in (
        "QUÉ ESCRIBIR: la RESPUESTA «Horario»",
        "LARGO MÁXIMO: 400 caracteres",
        "- qué días: lunes a sábado",
        "- Domicilio: Llevamos tu pedido a [barrios o zona].",
        "Posicionamiento: Shawarma y ensaladas en Cúcuta",
        "Variante del español: es-CO",
        "Palabras prohibidas: barato",
        "Emojis: ninguno",
        "[hora de abrir]",
        "VERSIÓN ANTERIOR (escribe una distinta):\nAbrimos de lunes a sábado.",
    ):
        assert expected in message, expected
    assert "(no hay)" in render_request(_hours(), None)
    assert MENU_CLOSING in SYSTEM_PROMPT and "NO inventes hechos" in SYSTEM_PROMPT


def test_greeting_happy_path() -> None:
    client = FakeClient([_answer("¡Hola! Gracias por escribirle a Bianki. ¿En qué te ayudamos?")])
    data = SuggestInput(
        kind="greeting",
        answer_name="",
        current_text="¡Hola! Gracias por escribir a [nombre de tu negocio].",
        facts=(("nombre de tu negocio", "Bianki"),),
    )
    # the model filled the name from the fact it names
    client.messages._responses[0].content[0].input["filled_gaps"] = [
        {"gap": "nombre de tu negocio", "fact": "nombre de tu negocio"}
    ]
    proposal = suggest_text(data, _kit(), client_factory=client.factory)

    assert proposal.text.startswith("¡Hola! Gracias por escribirle a Bianki")
    assert proposal.missing == () and proposal.warnings == ()
    assert proposal.neutral_voice is False
    (call,) = client.messages.calls
    assert call["model"] == "claude-sonnet-5-5"
    assert call["tools"][0]["name"] == TOOL_NAME and call["tools"][0]["strict"] is True
    assert "el SALUDO del menú" in call["messages"][0]["content"]


def test_answer_keeps_the_gaps_it_has_no_fact_for() -> None:
    text = "Abrimos de lunes a sábado, de [hora de abrir] a [hora de cerrar]. " + MENU_CLOSING
    client = FakeClient(
        [
            _answer(
                text, missing=["hora de abrir", "hora de cerrar"], filled=[("qué días", "qué días")]
            )
        ]
    )
    proposal = suggest_text(_hours(), _kit(), client_factory=client.factory)

    assert proposal.text == text
    assert proposal.missing == ("hora de abrir", "hora de cerrar")


def test_a_dropped_gap_comes_back_and_is_missing() -> None:
    # the model wrote a closing hour it was never given, and claims a fact that does not exist
    client = FakeClient(
        [
            _answer(
                "Abrimos de lunes a sábado desde las [hora de abrir]. " + MENU_CLOSING,
                filled=[("qué días", "qué días"), ("hora de cerrar", "Hora de cierre")],
            )
        ]
    )
    proposal = suggest_text(_hours(), _kit(), client_factory=client.factory)

    assert "[hora de cerrar]" in proposal.text
    assert proposal.missing == ("hora de abrir", "hora de cerrar")


def test_a_gap_filled_from_a_real_fact_may_go() -> None:
    client = FakeClient(
        [
            _answer(
                "Abrimos de lunes a sábado, de 11:00 a [hora de cerrar]. " + MENU_CLOSING,
                filled=[("qué días", "qué días"), ("hora de abrir", "Hora de abrir")],
            )
        ]
    )
    data = _hours(facts=(("qué días", "lunes a sábado"), ("Hora de abrir", "11:00")))
    proposal = suggest_text(data, _kit(), client_factory=client.factory)
    assert "[hora de abrir]" not in proposal.text and "[qué días]" not in proposal.text
    assert proposal.missing == ("hora de cerrar",)


def test_a_fact_that_is_itself_a_gap_does_not_fill_one() -> None:
    client = FakeClient(
        [_answer("Abrimos de lunes a sábado. " + MENU_CLOSING, filled=[("hora de abrir", "x")])]
    )
    data = _hours(facts=(("qué días", "lunes a sábado"), ("x", "[hora de abrir]")))
    proposal = suggest_text(data, _kit(), client_factory=client.factory)
    assert {"hora de abrir", "hora de cerrar"} <= set(proposal.missing)
    assert "[hora de abrir]" in proposal.text


def test_added_facts_get_one_retry_then_reach_the_owner_as_warnings() -> None:
    first = _answer("Abrimos de 8 a 22. " + MENU_CLOSING, added=["de 8 a 22"])
    second = _answer("Abrimos de 8 a [hora de cerrar]. " + MENU_CLOSING, added=["8"])
    client = FakeClient([first, second])
    proposal = suggest_text(_hours(), _kit(), client_factory=client.factory)

    assert len(client.messages.calls) == 2
    assert "Añadiste hechos" in client.messages.calls[1]["messages"][0]["content"]
    assert proposal.warnings == (
        "Revisa este dato: «8». Tú no lo escribiste; bórralo si no es cierto.",
    )


def test_a_banned_word_is_retried_then_refused() -> None:
    bad = _answer("Domicilio barato a toda la zona. " + MENU_CLOSING)
    still = _answer("Somos el mejor de la ciudad. " + MENU_CLOSING)
    client = FakeClient([bad, still])
    with pytest.raises(SuggestUnavailable):
        suggest_text(_hours(), _kit(), client_factory=client.factory)
    assert "barato" in client.messages.calls[1]["messages"][0]["content"]


def test_a_banned_word_fixed_on_the_retry_is_fine() -> None:
    client = FakeClient([_answer("Envío BARATO."), _answer("Envío a buen precio.")])
    proposal = suggest_text(_hours(current_text=""), _kit(), client_factory=client.factory)
    assert proposal.text == "Envío a buen precio."


def test_no_kit_is_neutral_voice_and_no_emoji() -> None:
    client = FakeClient([_answer("¡Hola! 😊 Gracias por escribirnos. **Bienvenido**")])
    data = SuggestInput(kind="greeting", answer_name="", current_text="")
    proposal = suggest_text(data, None, client_factory=client.factory)
    assert proposal.neutral_voice is True
    assert proposal.text == "¡Hola! Gracias por escribirnos. *Bienvenido*"


def test_emoji_stay_when_the_kit_allows_and_markdown_goes() -> None:
    client = FakeClient([_answer("# Horario\n- Abrimos ya 🙂 [mira aquí](https://x.co)")])
    kit = _kit(emoji_policy=EmojiPolicy.SPARSE)
    proposal = suggest_text(_hours(current_text=""), kit, client_factory=client.factory)
    assert proposal.text == "Horario\nAbrimos ya 🙂 mira aquí"


def test_otra_version_identical_is_retried_then_refused() -> None:
    previous = "Abrimos de lunes a sábado. " + MENU_CLOSING
    client = FakeClient(
        [_answer(previous), _answer("  abrimos de LUNES a sábado. " + MENU_CLOSING)]
    )
    with pytest.raises(SuggestUnavailable):
        suggest_text(
            _hours(current_text="", previous_text=previous), _kit(), client_factory=client.factory
        )
    assert "Repetiste la versión anterior" in client.messages.calls[1]["messages"][0]["content"]


def test_otra_version_different_on_retry_is_returned() -> None:
    previous = "Abrimos de lunes a sábado."
    client = FakeClient([_answer(previous), _answer("De lunes a sábado te esperamos.")])
    proposal = suggest_text(
        _hours(current_text="", previous_text=previous), _kit(), client_factory=client.factory
    )
    assert proposal.text == "De lunes a sábado te esperamos."


def test_too_long_is_cut_at_a_sentence_and_keeps_required_gaps() -> None:
    long = "Te esperamos con gusto todos los días. " * 20 + "Abrimos a las [hora de abrir]."
    client = FakeClient([_answer(long)])
    proposal = suggest_text(_hours(max_chars=200), _kit(), client_factory=client.factory)
    assert len(proposal.text) <= 200
    assert "[hora de abrir]" in proposal.text and "[hora de cerrar]" in proposal.text
    assert "Lo acortamos para que no pase de 200 letras." in proposal.warnings
    assert not proposal.text.split(" [")[0].endswith("con")  # cut at a sentence end


def test_refusal_no_tool_and_no_key_are_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    refused = FakeClient([_answer("", stop="refusal")])
    with pytest.raises(SuggestUnavailable):
        suggest_text(_hours(), _kit(), client_factory=refused.factory)
    no_tool = SimpleNamespace(
        model="m",
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        content=[SimpleNamespace(type="text", text="hola")],
    )
    with pytest.raises(SuggestUnavailable):
        suggest_text(_hours(), _kit(), client_factory=FakeClient([no_tool]).factory)
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY")
    with pytest.raises(SuggestUnavailable):
        suggest_text(_hours(), _kit(), client_factory=FakeClient([]).factory)


def test_an_exhausted_budget_is_unavailable_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(suggest_ai, "SUGGEST_BUDGET_USD", Decimal("0.0001"))
    client = FakeClient([_answer("Hola.")])
    with pytest.raises(SuggestUnavailable):
        suggest_text(_hours(), _kit(), client_factory=client.factory)
    assert client.messages.calls == []


def test_a_bad_kind_is_a_value_error() -> None:
    with pytest.raises(ValueError):
        suggest_text(_hours(kind="menu"), None, client_factory=FakeClient([]).factory)


def test_the_budget_pays_two_worst_turns_of_the_largest_input() -> None:
    big = "palabra " * 400
    data = SuggestInput(
        kind="answer",
        answer_name="x" * 200,
        current_text=big,
        facts=tuple((f"dato {i} " * 20, big) for i in range(40)),
        other_answers=tuple((f"respuesta {i} " * 20, big) for i in range(30)),
        previous_text=big,
        max_chars=5000,
    )
    long = "ejemplo largo " * 50
    kit = _kit(
        positioning=big,
        audience=big,
        do_examples=(long,) * 10,
        dont_examples=(long,) * 10,
        banned_words=(long,) * 10,
        forbidden_claims=(long,) * 10,
        cta_patterns=(long,) * 10,
    )
    correction = "- Añadiste hechos: " + " | ".join(["x" * 200] * 6)
    messages = [{"role": "user", "content": render_request(data, kit, correction=correction)}]
    tools = [suggest_ai._tool()]
    ceiling, _ = turn_input_ceiling(SYSTEM_PROMPT, messages, tools)
    worst = worst_turn_usd("claude-sonnet-5-5", ceiling, MAX_TOKENS)
    assert worst is not None and 2 * worst <= SUGGEST_BUDGET_USD
    assert request_bytes(SYSTEM_PROMPT, messages, tools) < 25_000


class FakeStore:
    def __init__(self, kit: BrandKit | None) -> None:
        self.kit = kit
        self.calls: list[tuple[UUID, UUID]] = []

    def get_kit(self, *, tenant_id: UUID, brand_id: UUID) -> BrandKit | None:
        self.calls.append((tenant_id, brand_id))
        return self.kit


def test_suggest_for_brand_reads_the_kit_through_the_store() -> None:
    tenant, brand = uuid4(), uuid4()
    store = FakeStore(None)
    client = FakeClient([_answer("¡Hola! Gracias por escribirnos.")])
    data = SuggestInput(kind="greeting", answer_name="", current_text="")
    proposal = suggest_for_brand(
        tenant, brand, data, client_factory=client.factory, kit_store=store
    )
    assert store.calls == [(tenant, brand)]
    assert proposal.neutral_voice is True


def test_suggest_for_brand_defaults_to_the_generator_kit_loader() -> None:
    from qualify_api.creative.brand_service import BrandKitService

    assert isinstance(suggest_ai._default_store(), BrandKitService)


def test_the_module_opens_no_db_door_of_its_own() -> None:
    import inspect

    imports = [
        line
        for line in inspect.getsource(suggest_ai).splitlines()
        if line.lstrip().startswith(("import ", "from "))
    ]
    assert not [line for line in imports if "qualify_shared.db" in line or "sqlalchemy" in line]
    assert "from qualify_api.creative.brand_service import BrandKitService" in "\n".join(imports)


def test_a_gap_claimed_from_an_unrelated_fact_comes_back() -> None:
    """Review C1 probe: invented hours «filled» from «qué días» must not erase the gaps."""
    client = FakeClient(
        [
            _answer(
                "Abrimos de lunes a sábado, de 7:00 a 23:00. " + MENU_CLOSING,
                filled=[
                    ("qué días", "qué días"),
                    ("hora de abrir", "qué días"),
                    ("hora de cerrar", "qué días"),
                ],
            )
        ]
    )
    proposal = suggest_text(_hours(), _kit(), client_factory=client.factory)
    assert proposal.missing == ("hora de abrir", "hora de cerrar")
    assert proposal.text.endswith("[hora de abrir] [hora de cerrar] " + MENU_CLOSING)
    assert "[qué días]" not in proposal.text


def test_a_named_fact_whose_value_is_not_in_the_text_keeps_the_gap() -> None:
    client = FakeClient(
        [
            _answer(
                "Abrimos de lunes a sábado desde las 7:00. " + MENU_CLOSING,
                filled=[("qué días", "qué días"), ("hora de abrir", "hora de abrir")],
            )
        ]
    )
    data = _hours(facts=(("qué días", "lunes a sábado"), ("hora de abrir", "11:00")))
    proposal = suggest_text(data, _kit(), client_factory=client.factory)
    assert "[hora de abrir]" in proposal.text and "hora de abrir" in proposal.missing


def test_a_rate_limit_is_unavailable() -> None:
    import anthropic
    import httpx

    class RateLimited:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kwargs: Any) -> Any:
                request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
                raise anthropic.RateLimitError(
                    "rate limited", response=httpx.Response(429, request=request), body=None
                )

    with pytest.raises(SuggestUnavailable, match="RateLimitError"):
        suggest_text(_hours(), _kit(), client_factory=lambda key: RateLimited())


def test_an_unavailable_message_carries_no_model_text() -> None:
    client = FakeClient([_answer("Envío barato."), _answer("Envío barato, de verdad.")])
    with pytest.raises(SuggestUnavailable) as caught:
        suggest_text(_hours(current_text=""), _kit(), client_factory=client.factory)
    assert "barato" not in str(caught.value) and "forbidden=1" in str(caught.value)


def test_the_address_form_follows_the_brand_examples() -> None:
    assert "«vos»" in SYSTEM_PROMPT and "«usted»" in SYSTEM_PROMPT
    assert "Tuteo" not in SYSTEM_PROMPT

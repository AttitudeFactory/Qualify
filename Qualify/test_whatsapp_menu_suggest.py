"""m-24936838: «Mejorar mi texto» / «Escribirlo por mí» on the WhatsApp menu's greeting
(step 1) and each answer's text (step 2). Spec: docs/ux-whatsapp-respuestas-de-siempre.md
§5–§6. The provider is faked: no Claude call, no database, nothing saved or published.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.whatsapp.menus.starter import StarterFacts, build_starter_menu

from . import whatsapp_menu_state as module
from .whatsapp_menu_provider import (
    MenuDetail,
    SuggestInput,
    SuggestProposal,
    SuggestUnavailable,
    suggest_text,
)
from .whatsapp_menu_state import WhatsAppMenuState
from .whatsapp_menu_vm import (
    SUGGEST_FAILED,
    SUGGEST_IMPROVE,
    SUGGEST_NO_DATA,
    SUGGEST_WRITE,
    AnswerVM,
    MenuSummaryVM,
    MenuVersionVM,
    suggest_context,
    suggest_has_input,
    suggest_label,
    suggest_missing_line,
    suggest_writing_line,
)

TENANT = uuid4()
BRAND = uuid4()


class _Proxy:
    """Reflex's StateProxy in a test: `async with self` is a no-op lock."""

    def __init__(self, state: WhatsAppMenuState) -> None:
        object.__setattr__(self, "_state", state)

    async def __aenter__(self) -> _Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __getattr__(self, name: str) -> object:
        return getattr(self._state, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._state, name, value)


class _FakeProvider:
    """Records every `SuggestInput`; answers with the queued proposals (or raises)."""

    def __init__(self, *answers: SuggestProposal | Exception) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[UUID, UUID | None, SuggestInput]] = []

    def __call__(
        self, tenant_id: UUID, brand_id: UUID | None, data: SuggestInput
    ) -> SuggestProposal:
        self.calls.append((tenant_id, brand_id, data))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _proposal(
    text: str,
    *,
    missing: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    neutral: bool = False,
) -> SuggestProposal:
    return SuggestProposal(text=text, missing=missing, warnings=warnings, neutral_voice=neutral)


def _state(
    monkeypatch: pytest.MonkeyPatch, provider: _FakeProvider, *, brand: bool = True
) -> WhatsAppMenuState:
    async def session(self: object) -> tuple[str, UUID | None, str]:
        return str(TENANT), TENANT, "duena@example.com"

    async def address(self: object) -> str:
        return "Av. 5 # 10-20"

    def facts(tenant_id: UUID, scope: object, *, address: str = "") -> StarterFacts:
        return StarterFacts(business_name="La Esquina", address=address, city="Cúcuta")

    monkeypatch.setattr(WhatsAppMenuState, "_session", session)
    monkeypatch.setattr(WhatsAppMenuState, "_profile_address", address)
    monkeypatch.setattr(module, "starter_facts", facts)
    monkeypatch.setattr(module, "suggest_text", provider)

    definition = build_starter_menu(StarterFacts(business_name="La Esquina", address="Av. 5"))
    menu_id, version_id = str(uuid4()), str(uuid4())
    summary = MenuSummaryVM(
        menu_id=menu_id,
        name="Menú principal",
        published_label="Sin publicar",
        is_published=False,
        is_paused=False,
        status_label="Sin publicar",
        status_tone="neutral",
        updated_at="hoy",
    )
    version = MenuVersionVM(
        version_id=version_id, label="Versión 1", created_at="hoy", published_at="", is_live=False
    )
    state = WhatsAppMenuState()
    state._scope = {
        "phone_row_id": str(uuid4()),
        "brand_id": str(BRAND) if brand else "",
        "brand_name": "La Esquina",
        "business_name": "La Esquina",
    }
    state.menus = [summary]
    state._show_detail(
        MenuDetail(
            summary=summary,
            versions=[version],
            latest=definition,
            payloads={version_id: definition.model_dump(mode="json")},
        ),
        load_form=True,
    )
    return state


async def _run(handler: Any, state: WhatsAppMenuState) -> None:
    await handler.fn(_Proxy(state))


def _horario(state: WhatsAppMenuState) -> int:
    return next(a.index for a in state.answers.buttons + state.answers.rows if a.label == "Horario")


# --- the greeting (step 1) ---------------------------------------------------------------


async def test_the_greeting_proposal_replaces_the_field_and_undo_brings_it_back_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeProvider(_proposal("¡Hola! Bienvenido a La Esquina. ¿En qué te ayudo?"))
    state = _state(monkeypatch, provider)
    mine = "  hola, somos La Esquina\nescríbenos  "
    state.set_guided_greeting(mine)
    assert state.greeting_suggest_label == SUGGEST_IMPROVE

    await _run(WhatsAppMenuState.suggest_greeting, state)

    tenant, brand, data = provider.calls[0]
    assert (tenant, brand) == (TENANT, BRAND)
    assert data.kind == "greeting" and data.answer_name == "" and data.current_text == mine
    assert data.previous_text == ""
    assert ("nombre de tu negocio", "La Esquina") in data.facts
    assert ("dirección y barrio", "Av. 5 # 10-20") in data.facts
    assert ("ciudad", "Cúcuta") in data.facts
    assert "Horario" in [name for name, _text in data.other_answers]
    assert state.welcome == "¡Hola! Bienvenido a La Esquina. ¿En qué te ayudo?"
    assert state.greeting_suggest.has_proposal and state.suggest_busy == ""
    assert state.dirty  # it is in the editor; only «Guardar»/«Publicar» store it

    state.undo_greeting_suggestion()
    assert state.welcome == mine  # whitespace and line breaks included
    assert not state.greeting_suggest.has_proposal


async def test_another_version_passes_the_last_proposal_and_undo_survives_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeProvider(_proposal("Primera versión."), _proposal("Segunda versión."))
    state = _state(monkeypatch, provider)
    state.set_guided_greeting("Mi saludo")
    await _run(WhatsAppMenuState.suggest_greeting, state)
    await _run(WhatsAppMenuState.suggest_greeting_again, state)

    second = provider.calls[1][2]
    assert second.previous_text == "Primera versión."
    assert second.current_text == "Primera versión."
    assert state.welcome == "Segunda versión."
    state.undo_greeting_suggestion()
    assert state.welcome == "Mi saludo"  # the owner's own text, not the first proposal


async def test_typing_after_a_proposal_ends_its_undo(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _FakeProvider(_proposal("Propuesta."))
    state = _state(monkeypatch, provider)
    state.set_guided_greeting("Mío")
    await _run(WhatsAppMenuState.suggest_greeting, state)
    state.set_guided_greeting("Propuesta. Y algo más")
    assert not state.greeting_suggest.has_proposal
    state.undo_greeting_suggestion()  # nothing to undo any more
    assert state.welcome == "Propuesta. Y algo más"


async def test_gaps_warnings_and_the_neutral_voice_reach_the_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeProvider(
        _proposal(
            "¡Hola! Abrimos a las [hora de abrir].",
            missing=("hora de abrir",),
            warnings=("Revisa este dato: «domicilio gratis». Tú no lo escribiste.",),
            neutral=True,
        )
    )
    state = _state(monkeypatch, provider, brand=False)
    await _run(WhatsAppMenuState.suggest_greeting, state)
    assert provider.calls[0][1] is None  # no brand on the number → neutral voice
    view = state.greeting_suggest
    assert view.neutral and view.has_proposal
    assert view.missing_line == (
        "Dejamos [hora de abrir] porque no escribiste ese dato. Complétalo antes de publicar."
    )
    assert view.warnings == ["Revisa este dato: «domicilio gratis». Tú no lo escribiste."]


async def test_a_failure_keeps_the_text_and_says_to_write_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeProvider(SuggestUnavailable("no key"))
    state = _state(monkeypatch, provider)
    state.set_guided_greeting("Mi saludo")
    await _run(WhatsAppMenuState.suggest_greeting, state)
    assert state.welcome == "Mi saludo"
    assert state.greeting_suggest.error == SUGGEST_FAILED
    assert "Tu texto sigue igual" in SUGGEST_FAILED
    assert not state.greeting_suggest.has_proposal and state.suggest_busy == ""


async def test_an_empty_field_with_no_data_asks_for_the_data_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeProvider()
    state = _state(monkeypatch, provider)
    monkeypatch.setattr(module, "starter_facts", lambda *a, **k: StarterFacts())
    state.set_guided_greeting("")
    assert state.greeting_suggest_label == SUGGEST_WRITE
    monkeypatch.setattr(module, "suggest_context", lambda *a, **k: ((), ()))
    await _run(WhatsAppMenuState.suggest_greeting, state)
    assert provider.calls == []
    assert state.greeting_suggest.error == SUGGEST_NO_DATA


async def test_a_text_changed_while_writing_keeps_the_newer_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_box: list[WhatsAppMenuState] = []

    def slow(tenant_id: UUID, brand_id: UUID | None, data: SuggestInput) -> SuggestProposal:
        state_box[0].welcome = "Lo escribí en Más opciones"  # the advanced editor
        return _proposal("Propuesta.")

    state = _state(monkeypatch, _FakeProvider())
    monkeypatch.setattr(module, "suggest_text", slow)
    state_box.append(state)
    state.set_guided_greeting("Mío")
    await _run(WhatsAppMenuState.suggest_greeting, state)
    assert state.welcome == "Lo escribí en Más opciones"
    assert state.greeting_suggest.error.startswith("Cambiaste el texto mientras tanto.")
    assert "«Mejorar mi texto»" in state.greeting_suggest.error


async def test_a_late_proposal_never_lands_in_another_menu_and_holds_the_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C2: switching menu / version / number while Claude writes discards the result,
    and no second paid call can start until the first one settles."""
    box: list[WhatsAppMenuState] = []
    second = _FakeProvider(_proposal("No debe salir."))

    async def reentrant_check() -> None:
        await _run(WhatsAppMenuState.suggest_answer, box[0])

    def slow(tenant_id: UUID, brand_id: UUID | None, data: SuggestInput) -> SuggestProposal:
        state = box[0]
        # Another menu loads meanwhile (same «greeting» key, maybe another brand).
        state._load_definition(None, "Otro menú")
        state.welcome = data.current_text  # even with the same text it must not land
        assert state.suggest_busy == "greeting"  # the slot is still held
        return _proposal("Propuesta del menú anterior.")

    state = _state(monkeypatch, _FakeProvider())
    monkeypatch.setattr(module, "suggest_text", slow)
    box.append(state)
    state.set_guided_greeting("Mío")
    await _run(WhatsAppMenuState.suggest_greeting, state)
    assert state.welcome == "Mío"
    assert not state.greeting_suggest.has_proposal and state._suggest_undo == {}
    assert state.suggest_busy == ""  # freed once the call settled

    # while busy, another tap is refused (no second paid call)
    monkeypatch.setattr(module, "suggest_text", second)
    state.suggest_busy = "greeting"
    state._drop_all_suggestions()  # a reload does not free the slot
    assert state.suggest_busy == "greeting"
    await reentrant_check()
    assert second.calls == []


async def test_go_to_brand_with_something_to_fix_says_so_next_to_the_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch, _FakeProvider())
    state.dirty, state.error_count = True, 1
    events = [e async for e in WhatsAppMenuState.save_and_open_brand.fn(_Proxy(state))]
    assert events == []
    assert state.suggest_notice.startswith("Corrige lo marcado en rojo")


# --- an answer (step 2) ------------------------------------------------------------------


async def test_an_answer_proposal_goes_to_the_open_answer_with_its_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeProvider(_proposal("Abrimos de lunes a sábado, de [hora de abrir]."))
    state = _state(monkeypatch, provider)
    index = _horario(state)
    state.open_answer_panel(index)
    before = state.open_answer.text
    assert state.answer_suggest_label == SUGGEST_IMPROVE

    await _run(WhatsAppMenuState.suggest_answer, state)

    data = provider.calls[0][2]
    assert data.kind == "answer" and data.answer_name == "Horario"
    assert data.current_text == before
    assert "Horario" not in [name for name, _t in data.other_answers]
    assert state.open_answer.text == "Abrimos de lunes a sábado, de [hora de abrir]."
    assert state.answer_suggest.has_proposal
    assert state.open_answer.gaps_line == "Falta: hora de abrir"
    assert not state.greeting_suggest.has_proposal  # the greeting is untouched

    state.undo_answer_suggestion()
    assert state.open_answer.text == before


async def test_an_answer_suggestion_is_dropped_when_the_panel_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeProvider(_proposal("Propuesta."))
    state = _state(monkeypatch, provider)
    state.open_answer_panel(_horario(state))
    await _run(WhatsAppMenuState.suggest_answer, state)
    state.close_answer_panel()
    assert not state.answer_suggest.has_proposal and state._suggest_undo == {}


async def test_a_busy_suggestion_refuses_a_second_one(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _FakeProvider(_proposal("x"))
    state = _state(monkeypatch, provider)
    state.suggest_busy = "greeting"
    await _run(WhatsAppMenuState.suggest_answer, state)
    assert provider.calls == []


# --- pure helpers --------------------------------------------------------------------------


def test_the_button_is_named_by_whether_the_field_has_text() -> None:
    assert suggest_label("") == "Escribirlo por mí"
    assert suggest_label("   \n") == "Escribirlo por mí"
    assert suggest_label("Hola") == "Mejorar mi texto"


def test_the_missing_line_names_each_gap_once() -> None:
    assert suggest_missing_line(()) == ""
    assert suggest_missing_line(("hora de abrir", "[hora de abrir]", "hora de cerrar")) == (
        "Dejamos [hora de abrir] y [hora de cerrar] porque no escribiste esos datos. "
        "Complétalos antes de publicar."
    )
    # neutral while writing: whether the brand has an identity is known only afterwards
    assert suggest_writing_line() == "Escribiendo tu texto…"


def _answer(index: int, label: str, text: str, *, editable: bool = True) -> AnswerVM:
    return AnswerVM(
        index=index,
        label=label,
        does="",
        preview=text if not editable else "",
        text=text if editable else "",
        text_editable=editable,
        is_products=not editable,
        status_label="",
        status_tone="neutral",
        gaps_line="",
        has_gaps=False,
        label_count="",
        label_error="",
        text_error="",
        is_button=True,
        can_up=False,
        can_down=False,
    )


def test_facts_are_only_what_the_owner_gave() -> None:
    answers = [
        _answer(0, "Ver menú y pedir", "Muestra tus productos", editable=False),
        _answer(1, "Horario", "Abrimos de [qué días]"),
        _answer(2, "Formas de pago", "Efectivo y transferencia."),
        _answer(3, "Domicilio", "Sí, llevamos."),
    ]
    facts, others = suggest_context(
        StarterFacts(business_name="Bianki", city="Cúcuta"), answers, exclude_index=3
    )
    assert facts == (
        ("nombre de tu negocio", "Bianki"),
        ("ciudad", "Cúcuta"),
        ("Formas de pago", "Efectivo y transferencia."),  # a gap is never a fact
    )
    assert [n for n, _t in others] == ["Ver menú y pedir", "Horario", "Formas de pago"]
    assert not suggest_has_input("", ())
    assert suggest_has_input("algo", ())
    assert suggest_has_input("", facts)


# --- the provider seam ---------------------------------------------------------------------


def test_the_provider_uses_the_brand_kit_or_the_neutral_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import whatsapp_menu_provider as provider

    seen: list[object] = []

    def with_brand(tenant_id: UUID, brand_id: UUID, data: SuggestInput, **kw: object) -> str:
        seen.append(("brand", brand_id, kw.get("kit_store")))
        return "ok-brand"

    def without_brand(data: SuggestInput, kit: object, **kw: object) -> str:
        seen.append(("neutral", kit))
        return "ok-neutral"

    monkeypatch.setattr(provider, "suggest_for_brand", with_brand)
    monkeypatch.setattr(provider, "_suggest_without_brand", without_brand)
    data = SuggestInput(kind="greeting", answer_name="", current_text="Hola")
    store = object()
    assert suggest_text(TENANT, BRAND, data, kit_store=store) == "ok-brand"  # type: ignore[arg-type]
    assert suggest_text(TENANT, None, data) == "ok-neutral"
    assert seen == [("brand", BRAND, store), ("neutral", None)]


# --- the screen ------------------------------------------------------------------------------


def test_both_steps_render_the_suggestion_controls() -> None:
    from . import whatsapp_tab_menu

    rendered = str(whatsapp_tab_menu.menu_tab().render())

    def present(text: str) -> bool:
        escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
        return text in rendered or escaped in rendered

    for text in (
        "Deshacer",
        "Otra versión",
        "Lo escribimos con tu forma de hablar. Revísalo.",
        "Ir a Tu marca",
        "Revísalo y completa lo que falta antes de publicar.",
        "Guardamos este texto.",
        "Deshacer: volver a tu texto",
        "Otra versión de la sugerencia",
    ):
        assert present(text), text
    # one control under the greeting and one under the open answer's text
    assert rendered.count("suggest_greeting") >= 1 and rendered.count("suggest_answer") >= 1
    assert "greeting_suggest_label" in rendered and "answer_suggest_label" in rendered


def test_the_suggestion_never_saves_or_publishes() -> None:
    """No provider write is reachable from the suggestion handlers."""
    import inspect

    source = inspect.getsource(WhatsAppMenuState._suggest)
    for write in ("save_version", "publish_version", "_save_now", "create_menu"):
        assert write not in source, write

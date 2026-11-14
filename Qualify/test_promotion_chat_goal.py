"""«Que te escriban» (m-24828980): goal, chat, greeting, then the same budget and review."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.ads import messaging_destinations as backend_destinations
from qualify_api.ads.messaging import MessagingTarget
from qualify_api.ads.messaging_destinations import (
    LINK_GUIDE,
    PENDING,
    READY,
    MessagingDestination,
)
from qualify_api.ads.messaging_greeting import CHANGED_WHILE_EDITING, GreetingUnavailable
from qualify_api.ads.wizard import PIECE_BUTTON_UNSUPPORTED

from . import promotion_provider as provider
from . import promotion_state as state_module
from .ad_enhancements_vm import BrandEnhancementsVM
from .promotion_state import PromotionState
from .promotion_vm import (
    CHAT_STEPS,
    GREETING_RELOAD,
    GreetingVM,
    MessagingDestinationVM,
    PromotionDraftVM,
    PromotionSourceVM,
    first_problem,
    greeting_buttons_label,
    greeting_from_saved,
    greeting_problem,
    preselect_channel,
    questions_shown,
    step_keys,
    step_problem,
)

TENANT, LOGIN, USER = uuid4(), uuid4(), uuid4()
BRAND, CONNECTION, SOURCE = uuid4(), uuid4(), uuid4()
ZONE = "America/Bogota"
WHATSAPP_OK = MessagingDestinationVM("whatsapp", "WhatsApp", "x", available=True)
WHATSAPP_UNLINKED = MessagingDestinationVM(
    "whatsapp", "WhatsApp", LINK_GUIDE, reason_code="unlinked", action="Unir mi WhatsApp"
)
INSTAGRAM_OK = MessagingDestinationVM(
    "instagram_direct", "Mensajes de Instagram", "x", available=True
)


def chat_form(**changes: Any) -> PromotionDraftVM:
    return replace(
        PromotionDraftVM(
            source_id=str(SOURCE),
            goal="chat",
            channel="whatsapp",
            welcome_text="¡Hola! ¿En qué te ayudamos?",
            questions=["¿Hacen domicilios?", "¿Cuál es el horario?", "", ""],
            greeting_id=str(uuid4()),
            greeting_version=2,
            city_name="Cúcuta",
            location_key="123",
            budget="25000",
            start_local="2027-01-10T09:00",
            end_local="2027-01-17T09:00",
            enhancements=BrandEnhancementsVM(str(BRAND), loaded=True),
        ),
        **changes,
    )


class Context:
    """The parts of PromotionState these events touch, without a Reflex app."""

    _invalidate_review = PromotionState._invalidate_review

    def __init__(self, destinations: list[MessagingDestinationVM], **form: Any) -> None:
        self.auth = (str(TENANT), str(LOGIN), str(USER))
        self._loaded_context = self.auth
        self.sources = [
            PromotionSourceVM(
                str(SOURCE),
                "@negocio",
                "Oferta",
                connection_id=str(CONNECTION),
                brand_id=str(BRAND),
                messaging_destinations=destinations,
                chat_goal=True,
            )
        ]
        self.question_boxes = 1
        self.form = chat_form(**form)
        self.review = None
        self.result = SimpleNamespace(status="")
        self.checks = []
        self.step = 4
        self.busy = self.loading = self.reviewed = self.confirm_charge = False
        self.video_waiting = self.needs_help = False
        self.error = self.success = ""
        self._request_key = ""

    @property
    def selected_source(self) -> PromotionSourceVM:
        return self.sources[0]

    async def _session(self) -> tuple[str, str, str]:
        return self.auth

    async def __aenter__(self) -> Context:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


# --- Goal and chat ---


def test_the_chat_goal_adds_the_chat_and_greeting_steps_before_the_same_budget() -> None:
    assert step_keys(PromotionDraftVM()) == ("source", "destination", "audience", "budget")
    assert step_keys(PromotionDraftVM(goal="chat")) == CHAT_STEPS
    assert CHAT_STEPS[-2:] == ("audience", "budget")
    form = chat_form()
    assert first_problem(form, ZONE) == ""
    assert step_problem(replace(form, channel=""), 3) == "Elige por dónde quieres que te escriban."


def test_choosing_the_chat_goal_preselects_the_only_possible_chat_and_still_lists_both() -> None:
    context = Context([WHATSAPP_UNLINKED, INSTAGRAM_OK], goal="visit", channel="")
    PromotionState.choose_goal.fn(context, "chat")
    assert context.form.goal == "chat"
    assert context.form.channel == "instagram_direct"
    assert len(context.selected_source.messaging_destinations) == 2


def test_two_possible_chats_wait_for_the_owner_to_choose() -> None:
    context = Context([WHATSAPP_OK, INSTAGRAM_OK], goal="visit", channel="")
    PromotionState.choose_goal.fn(context, "chat")
    assert context.form.channel == ""
    PromotionState.choose_channel.fn(context, "whatsapp")
    assert context.form.channel == "whatsapp"


def test_an_unlinked_whatsapp_cannot_be_chosen() -> None:
    context = Context([WHATSAPP_UNLINKED, INSTAGRAM_OK], channel="instagram_direct")
    PromotionState.choose_channel.fn(context, "whatsapp")
    assert context.form.channel == "instagram_direct"
    PromotionState.choose_channel.fn(context, "telegram")
    assert context.form.channel == "instagram_direct"


def test_a_recheck_drops_a_chat_that_is_no_longer_available() -> None:
    form = chat_form(channel="whatsapp")
    assert preselect_channel(form, [WHATSAPP_UNLINKED, INSTAGRAM_OK]).channel == "instagram_direct"
    assert preselect_channel(form, [WHATSAPP_UNLINKED]).channel == ""
    assert preselect_channel(form, [WHATSAPP_OK, INSTAGRAM_OK]) == form


def test_the_unlinked_whatsapp_card_links_to_tus_redes() -> None:
    from .promotion_page import _channel

    rendered = str(_channel())  # the foreach body, as compiled
    assert "/connections" in rendered and "action" in rendered
    assert "choose_channel" in rendered and "available" in rendered


def test_the_piece_button_refusal_does_not_block_a_chat_ad() -> None:
    context = Context([WHATSAPP_OK])
    context.sources = [replace(context.sources[0], unavailable_reason=PIECE_BUTTON_UNSUPPORTED)]
    context.form = replace(context.form, enhancements=BrandEnhancementsVM(str(BRAND), loaded=True))
    assert PromotionState.execution_reason.fget(context) == ""
    context.form = replace(context.form, goal="visit")
    assert PromotionState.execution_reason.fget(context) == PIECE_BUTTON_UNSUPPORTED


# --- Greeting ---


@pytest.mark.parametrize(
    "welcome, questions, problem",
    [
        ("", ["¿Hay domicilios?"], "Escribe tu mensaje de bienvenida."),
        (
            "a" * 301,
            ["¿Hay?"],
            "Tu mensaje de bienvenida pasa de 300 caracteres. Acórtalo un poco.",
        ),
        ("Hola", ["", "", "", ""], "Escribe entre 1 y 4 preguntas sugeridas."),
        ("Hola", ["b" * 81], "Cada pregunta puede tener hasta 80 caracteres."),
        ("Hola", ["¿Hay?", "¿Hay?"], "Hay preguntas repetidas. Deja una sola de cada una."),
        ("Hola", ["¿Hay?", "", "", ""], ""),
    ],
)
def test_greeting_rules_and_words_are_the_backends(
    welcome: str, questions: list[str], problem: str
) -> None:
    assert greeting_problem(chat_form(welcome_text=welcome, questions=questions)) == problem


def test_the_greeting_step_asks_to_save_an_edited_greeting() -> None:
    assert step_problem(chat_form(greeting_id=""), 4) == "Guarda el saludo antes de continuar."
    assert step_problem(chat_form(), 4) == ""


def test_the_greeting_is_prefilled_from_the_brands_last_saved_version() -> None:
    saved = GreetingVM("g-1", 3, "¡Hola!", ["¿Precio?", "¿Horario?"])
    form = greeting_from_saved(PromotionDraftVM(), saved)
    assert form.welcome_text == "¡Hola!"
    assert form.questions == ["¿Precio?", "¿Horario?", "", ""]
    assert (form.greeting_id, form.greeting_version) == ("g-1", 3)
    assert greeting_from_saved(PromotionDraftVM(), GreetingVM()).questions == ["", "", "", ""]


def test_choosing_a_publication_prefills_its_brands_greeting() -> None:
    context = Context([INSTAGRAM_OK])
    saved = GreetingVM("g-1", 1, "¡Bienvenido!", ["¿Domicilios?"])
    context.sources = [replace(context.sources[0], greeting=saved)]
    context.form = PromotionDraftVM()
    context.timezone_name = context._tenant_timezone = ZONE
    for name in (
        "_invalidate_destinations",
        "_invalidate_enhancements",
        "_invalidate_audience",
    ):
        setattr(context, name, lambda: None)
    context._reset_custom_audiences = lambda: None
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(PromotionState, "_reset_custom_audiences", lambda self: None)
        PromotionState.choose_source.fn(context, str(SOURCE))
    assert context.form.welcome_text == "¡Bienvenido!"
    assert context.form.greeting_id == "g-1"


def test_editing_the_greeting_forgets_the_saved_version() -> None:
    context = Context([INSTAGRAM_OK])
    PromotionState.edit_question.fn(context, 2, "¿Tienen parqueadero?")
    assert context.form.questions[2] == "¿Tienen parqueadero?"
    assert context.form.greeting_id == ""
    context.form = chat_form()
    PromotionState.edit_welcome.fn(context, "Hola de nuevo")
    assert context.form.greeting_id == ""
    PromotionState.edit_question.fn(context, 9, "fuera")
    assert len(context.form.questions) == 4


def test_next_on_an_edited_greeting_saves_it_first() -> None:
    context = Context([INSTAGRAM_OK], greeting_id="")
    context.preparation_blocked = False
    event = PromotionState.next_step.fn(context)
    assert "save_greeting" in str(event)
    assert context.step == 4


async def _drain(context: Context) -> list[object]:
    return [event async for event in PromotionState.save_greeting.fn(context)]


@pytest.mark.asyncio
async def test_saving_uses_the_versioned_save_and_moves_on(monkeypatch: pytest.MonkeyPatch) -> None:
    context = Context([INSTAGRAM_OK], greeting_id="", greeting_version=2)
    calls = []

    def store(tenant: UUID, brand: UUID, form: PromotionDraftVM) -> GreetingVM:
        calls.append((tenant, brand, form.greeting_version, form.welcome_text))
        return GreetingVM("g-3", 3, form.welcome_text, [q for q in form.questions if q])

    monkeypatch.setattr(state_module, "store_greeting", store)
    events = await _drain(context)
    assert calls == [(TENANT, BRAND, 2, "¡Hola! ¿En qué te ayudamos?")]
    assert (context.form.greeting_id, context.form.greeting_version) == ("g-3", 3)
    assert context.error == "" and context.busy is False
    assert "next_step" in str(events)


@pytest.mark.asyncio
async def test_a_save_conflict_shows_its_message_and_the_latest_greeting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context([INSTAGRAM_OK], greeting_id="", greeting_version=1)

    def store(*args: object) -> GreetingVM:
        raise GreetingUnavailable(CHANGED_WHILE_EDITING)

    latest = GreetingVM("g-2", 2, "Saludo de otra persona", ["¿Precio?"])
    monkeypatch.setattr(state_module, "store_greeting", store)
    monkeypatch.setattr(state_module, "latest_greeting", lambda *args: latest)
    events = await _drain(context)
    assert context.error == CHANGED_WHILE_EDITING
    assert context.form.welcome_text == "Saludo de otra persona"
    assert (context.form.greeting_id, context.form.greeting_version) == ("g-2", 2)
    assert events == []


@pytest.mark.asyncio
async def test_a_refused_greeting_shows_the_backend_words(monkeypatch: pytest.MonkeyPatch) -> None:
    context = Context([INSTAGRAM_OK], greeting_id="")

    def store(*args: object) -> GreetingVM:
        raise GreetingUnavailable("Esta marca ya no está disponible en este negocio.")

    monkeypatch.setattr(state_module, "store_greeting", store)
    assert await _drain(context) == []
    assert context.error == "Esta marca ya no está disponible en este negocio."
    assert context.form.greeting_id == ""


@pytest.mark.asyncio
async def test_a_conflict_whose_latest_cannot_be_read_asks_to_reopen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context([INSTAGRAM_OK], greeting_id="", greeting_version=1)

    def store(*args: object) -> GreetingVM:
        raise GreetingUnavailable(CHANGED_WHILE_EDITING)

    def unreadable(*args: object) -> GreetingVM:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(state_module, "store_greeting", store)
    monkeypatch.setattr(state_module, "latest_greeting", unreadable)
    assert await _drain(context) == []
    assert context.error == GREETING_RELOAD
    assert "Vuelve a abrir la promoción" in context.error


def test_review_lists_the_chat_buttons_and_new_boxes_open_one_by_one() -> None:
    form = chat_form(questions=["¿Domicilios?", "", "¿Horario?", ""])
    assert greeting_buttons_label(form) == "¿Domicilios? · ¿Horario?"
    assert greeting_buttons_label(chat_form(questions=["", "", "", ""])) == "Por escribir"
    assert questions_shown(chat_form(questions=["", "", "", ""]), 1) == 1
    assert questions_shown(form, 1) == 3
    assert questions_shown(chat_form(questions=["a", "", "", ""]), 2) == 2
    assert questions_shown(form, 9) == 4
    context = Context([INSTAGRAM_OK], questions=["a", "", "", ""])
    PromotionState.add_question.fn(context)
    assert context.question_boxes == 2


@pytest.mark.parametrize("goal", ["visit", "lead"])
def test_leaving_the_chat_goal_sends_no_chat_or_greeting_and_keeps_the_link(
    monkeypatch: pytest.MonkeyPatch, goal: str
) -> None:
    context = Context([INSTAGRAM_OK], link_url="https://negocio.example/oferta")
    PromotionState.choose_goal.fn(context, goal)
    assert context.form.goal == goal
    monkeypatch.setattr(
        provider,
        "load_messaging_destinations",
        lambda **kwargs: pytest.fail("no chat is read for a link or form ad"),
    )
    monkeypatch.setattr(
        provider, "published_lead_form", lambda tenant, form_id: SimpleNamespace(id=form_id)
    )
    captured = {}

    async def prepare(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        raise RuntimeError("stop after capturing the form")

    monkeypatch.setattr(provider, "prepare_promotion_preview", prepare)
    monkeypatch.setattr(provider, "audience_from_form", lambda form: None)
    form = replace(context.form, lead_form_id=str(uuid4()))
    with pytest.raises(RuntimeError, match="stop after"):
        provider.prepare_preview(TENANT, uuid4(), USER, form, ZONE, "key", str(CONNECTION))
    sent = captured["form"]
    assert sent.messaging is None and sent.greeting is None
    assert sent.link_url == ("https://negocio.example/oferta" if goal == "visit" else "")


def test_the_lead_goal_keeps_the_backends_form_refusal() -> None:
    from qualify_api.ads.wizard import PIECE_BUTTON_LEAD

    context = Context([WHATSAPP_OK], goal="lead")
    context.sources = [replace(context.sources[0], unavailable_reason=PIECE_BUTTON_UNSUPPORTED)]
    assert PromotionState.execution_reason.fget(context) == PIECE_BUTTON_LEAD


def test_the_saved_greeting_and_the_exact_chat_reach_the_backend_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = MessagingTarget("INSTAGRAM_DIRECT", CONNECTION, CONNECTION, "77", 1, 1)
    monkeypatch.setattr(
        provider,
        "load_messaging_destinations",
        lambda **kwargs: (
            MessagingDestination(
                "instagram_direct", "Mensajes de Instagram", True, READY, CONNECTION, target=target
            ),
        ),
    )
    captured = {}

    async def prepare(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            preview_html='<iframe src="https://www.facebook.com/ads/api/preview_iframe.php?d=t">'
            "</iframe>",
            promotion_id=uuid4(),
            review_id=uuid4(),
            charge_notice="",
            expires_at=datetime(2027, 1, 1, tzinfo=UTC),
        )

    monkeypatch.setattr(provider, "prepare_promotion_preview", prepare)
    monkeypatch.setattr(provider, "audience_from_form", lambda form: None)
    form = chat_form(channel="instagram_direct", link_url="https://ignored.example")
    provider.prepare_preview(TENANT, uuid4(), USER, form, ZONE, "key", str(CONNECTION))
    sent = captured["form"]
    assert sent.messaging == target
    assert sent.link_url == "" and sent.lead_form is None and sent.cta_type == "LEARN_MORE"
    assert sent.greeting.welcome_text == "¡Hola! ¿En qué te ayudamos?"
    assert sent.greeting.questions == ("¿Hacen domicilios?", "¿Cuál es el horario?")
    assert (str(sent.greeting.greeting_id), sent.greeting.version) == (form.greeting_id, 2)
    assert sent.greeting.brand_id == BRAND
    sent.validate()


def test_an_unavailable_chat_never_reaches_the_backend_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.ads.wizard import WizardUnavailable

    monkeypatch.setattr(
        provider,
        "load_messaging_destinations",
        lambda **kwargs: (
            MessagingDestination(
                "whatsapp", "WhatsApp", False, LINK_GUIDE, None, False, reason_code="unlinked"
            ),
        ),
    )
    monkeypatch.setattr(
        provider, "prepare_promotion_preview", lambda **kwargs: pytest.fail("never prepared")
    )
    monkeypatch.setattr(provider, "audience_from_form", lambda form: None)
    with pytest.raises(WizardUnavailable, match="aún no está unido"):
        provider.prepare_preview(TENANT, uuid4(), USER, chat_form(), ZONE, "key", str(CONNECTION))


# --- Flag and story ---


@pytest.mark.parametrize(
    "value, on",
    [(None, False), ("", False), ("0", False), ("yes", False), ("1", True), (" TRUE ", True)],
)
def test_the_chat_goal_switch_is_off_unless_the_env_says_1_or_true(
    monkeypatch: pytest.MonkeyPatch, value: str | None, on: bool
) -> None:
    if value is None:
        monkeypatch.delenv("QUALIFY_ADS_CHAT_GOAL", raising=False)
    else:
        monkeypatch.setenv("QUALIFY_ADS_CHAT_GOAL", value)
    assert backend_destinations.chat_goal_on_screen() is on
    assert backend_destinations._offer() == ((True, READY) if on else (False, PENDING))


@pytest.mark.parametrize("on", [True, False])
def test_published_sources_carry_the_switch(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    from qualify_api.ads.wizard import PromotionSource

    source = PromotionSource(uuid4(), uuid4(), uuid4(), uuid4(), "1", "2", "Oferta", "@negocio")
    monkeypatch.setattr(provider, "list_promotion_sources", lambda **kwargs: [source])
    monkeypatch.setattr(provider, "read_business_locale", lambda tenant: None)
    monkeypatch.setattr(provider, "chat_goal_on_screen", lambda: on)
    rows, _ = provider.load_sources(uuid4(), source.content_draft_id)
    assert rows[0].chat_goal is on


def test_with_the_switch_off_the_old_notice_shows_and_chat_is_not_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from .promotion_page import _destination, _link_destination

    monkeypatch.delenv("QUALIFY_ADS_CHAT_GOAL", raising=False)
    row = MessagingDestination(
        "instagram_direct",
        "Mensajes de Instagram",
        *backend_destinations._offer(),
        CONNECTION,
        reason_code="ready",
    )
    monkeypatch.setattr(provider, "load_messaging_destinations", lambda **kwargs: (row,))
    [option] = provider.messaging_destinations(uuid4(), uuid4())
    assert option.notice == PENDING and not option.available
    assert not option.action and not option.status
    context = Context([option], goal="visit", channel="")
    context.sources = [replace(context.sources[0], chat_goal=False)]
    PromotionState.choose_goal.fn(context, "chat")
    assert context.form.goal == "visit"
    # The screen still renders: the goal option only behind the switch, the old
    # diagnosis under the website form.
    assert "chat_goal" in str(_destination())
    website = str(_link_destination())
    assert "Anuncios que abren un chat" in website and "messaging_destinations" in website


def test_the_goal_step_offers_the_chat_goal_without_the_old_notice() -> None:
    from .promotion_page import _destination

    rendered = str(_destination().render())
    assert "Que te escriban" in rendered
    assert "todavía no está habilitada" not in rendered


def test_a_story_never_offers_the_chat_goal() -> None:
    context = Context([WHATSAPP_OK, INSTAGRAM_OK], goal="visit", channel="")
    context.form = replace(context.form, story=True)
    PromotionState.choose_goal.fn(context, "chat")
    assert context.form.goal == "visit"
    assert "channel" not in step_keys(replace(context.form, goal="chat"))
    context.form = replace(context.form, story=False, media_kind="images")
    PromotionState.choose_goal.fn(context, "chat")
    assert context.form.goal == "visit"

    from .promotion_story_ui import story_audience, story_link, story_media

    for view in (story_media, story_link, story_audience):
        assert "Que te escriban" not in str(view().render())

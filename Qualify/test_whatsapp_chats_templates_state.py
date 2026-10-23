"""m-24848535 — the expired chat's approved-message picker in `WhatsAppChatsState`.

Only the synchronous parts (applying the service's options, picking, typing values,
«Pedirle que acepte»); the background events need a live Reflex `EventContext`
(`get_state(AuthState)`), the same pre-existing gap `test_connections_state.py` notes.
The service rules themselves are pinned offline in
`packages/api/tests/test_whatsapp_template_reply.py`.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from qualify_api.whatsapp.template_reply import (
    Permission,
    TemplateOption,
    TemplateReplyOptions,
    TemplateVariable,
)

from .whatsapp_chats_state import WhatsAppChatsState
from .whatsapp_chats_vm import TEMPLATE_FILL_HINT, TEMPLATE_PICK_HINT

FOLLOWUP = uuid4()
ASK = uuid4()


def _option(template_id: UUID, name: str, *, consent: bool = False) -> TemplateOption:
    variables = [TemplateVariable("body", "1", False)]
    return TemplateOption(
        template_id=template_id,
        name=name,
        language="es",
        category="utility",
        preview="Hola Ana",
        variables=variables,
        prefill={"body:1": "Ana"},
        is_consent_request=consent,
        components=[{"type": "BODY", "text": "Hola {{1}}"}],
    )


def _options(*, with_ask: bool) -> TemplateReplyOptions:
    followup = _option(FOLLOWUP, "seguimiento_pedido")
    ask = _option(ASK, "pedir_permiso_promos", consent=True)
    listed = [followup, ask] if with_ask else [followup]
    return TemplateReplyOptions(
        thread_id=uuid4(),
        permission=Permission.CHAT,
        options=listed,
        promotions_blocked=True,
        consent_request=ask if with_ask else None,
        has_followups=True,
    )


def test_options_render_choices_and_the_consent_button_only_when_it_exists() -> None:
    state = WhatsAppChatsState()
    state._apply_template_options(_options(with_ask=False))
    assert [c.title for c in state.tpl_choices] == ["Seguimiento pedido"]
    assert state.tpl_promotions_blocked is True
    assert state.tpl_consent_id == ""  # no approved message to ask: no button

    state._apply_template_options(_options(with_ask=True))
    assert state.tpl_consent_id == str(ASK)


def test_picking_prefills_and_typing_rerenders_the_preview() -> None:
    state = WhatsAppChatsState()
    state._apply_template_options(_options(with_ask=False))
    assert state.tpl_hint == TEMPLATE_PICK_HINT

    state._choose(str(FOLLOWUP))
    assert state.tpl_selected == str(FOLLOWUP)
    assert state.tpl_preview == "Hola Ana"
    assert state._tpl_request_key != ""
    assert state.can_send_template is True

    state._tpl_values = {"body:1": ""}
    state._render_template_choice()
    assert state.can_send_template is False
    assert state.tpl_hint == TEMPLATE_FILL_HINT
    assert state.tpl_preview == "Hola [Dato 1 del mensaje]"


def test_an_id_the_list_does_not_hold_is_ignored() -> None:
    state = WhatsAppChatsState()
    state._apply_template_options(_options(with_ask=False))
    state._choose(str(uuid4()))
    assert state.tpl_selected == ""
    assert state.can_send_template is False


def test_a_new_pick_is_a_new_send_intent() -> None:
    state = WhatsAppChatsState()
    state._apply_template_options(_options(with_ask=True))
    state._choose(str(FOLLOWUP))
    first_key = state._tpl_request_key
    state._choose(str(ASK))  # «Pedirle que acepte» picks it; «Enviar» still sends it
    assert state.tpl_selected == str(ASK)
    assert state._tpl_request_key not in ("", first_key)


def test_choice_cards_show_label_gaps_not_placeholders() -> None:
    option = TemplateOption(
        template_id=FOLLOWUP,
        name="seguimiento_pedido",
        language="es",
        category="utility",
        preview="Hola {{1}}, tu {{2}}",
        variables=[TemplateVariable("body", "1", False), TemplateVariable("body", "2", False)],
        prefill={"body:1": "Ana"},
        is_consent_request=False,
        components=[
            {
                "type": "BODY",
                "text": "Hola {{1}}, tu {{2}}",
                "example": {"body_text": [["Pablo", "pedido 12"]]},
            }
        ],
    )
    state = WhatsAppChatsState()
    state._apply_template_options(
        TemplateReplyOptions(
            thread_id=uuid4(),
            permission=Permission.CHAT,
            options=[option],
            promotions_blocked=True,
            consent_request=None,
            has_followups=True,
        )
    )
    assert state.tpl_choices[0].preview == "Hola Ana, tu [Dato 2 del mensaje]"
    state._choose(str(FOLLOWUP))
    assert "{{" not in state.tpl_preview
    assert [f.example for f in state.tpl_fields] == ["Ejemplo: Pablo", "Ejemplo: pedido 12"]


def test_two_steps_back_keeps_the_choice_and_the_values() -> None:
    state = WhatsAppChatsState()
    state._apply_template_options(_options(with_ask=False))
    assert state.tpl_reviewing is False
    state._choose(str(FOLLOWUP))  # picking moves to step 2 on its own
    assert state.tpl_reviewing is True
    state.set_template_value("body:1", "Luisa")
    key = state._tpl_request_key

    state.back_to_templates()
    assert state.tpl_reviewing is False
    assert state.can_send_template is False  # «Enviar» lives in step 2 only
    assert state.tpl_hint == TEMPLATE_PICK_HINT

    state._choose(str(FOLLOWUP))  # the same message again: values and key intact
    assert state.tpl_reviewing is True
    assert state._tpl_values == {"body:1": "Luisa"}
    assert state._tpl_request_key == key


def test_ask_consent_goes_straight_to_step_two() -> None:
    state = WhatsAppChatsState()
    state._apply_template_options(_options(with_ask=True))
    state.ask_consent()
    assert (state.tpl_selected, state.tpl_reviewing) == (str(ASK), True)


def test_no_permission_hides_the_hint() -> None:
    state = WhatsAppChatsState()
    state._apply_template_options(
        TemplateReplyOptions(
            thread_id=uuid4(),
            permission=Permission.NONE,
            options=[],
            promotions_blocked=False,
            consent_request=None,
            has_followups=False,
        )
    )
    assert state.tpl_no_permission is True
    assert state.tpl_hint == ""
    assert state.can_send_template is False

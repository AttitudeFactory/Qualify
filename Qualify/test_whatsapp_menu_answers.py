"""m-24936836: step 2 «¿Qué te preguntan siempre?» — one ordered list of answers, the
WhatsApp limits always visible, and a gap never published. Pure tests over the VM."""

from __future__ import annotations

from dataclasses import replace

from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.menus.schema import ButtonsNode, ListNode, MenuDefinition
from qualify_api.whatsapp.menus.starter import (
    PAYMENT_TEXT,
    StarterFacts,
    build_starter_menu,
    definition_gaps,
)

from .whatsapp_menu_vm import (
    ANSWER_NAME_TOO_LONG,
    ANSWER_TEXT_MISSING,
    SUGGESTION_CUSTOM,
    SUGGESTION_PRODUCTS,
    MenuForm,
    answer_set_label,
    answer_set_text,
    answers_add,
    answers_move,
    answers_remove,
    answers_summary,
    answers_view,
    answers_without_gaps,
    button_limit_text,
    definition_to_form,
    empty_form,
    guided_view,
    move_hits_button_limit,
    publish_gaps,
    read_answers,
    template_definition,
    validate_form,
)


def _starter(**facts: str) -> MenuForm:
    return definition_to_form(build_starter_menu(StarterFacts(business_name="Bianki", **facts)))


def _valid(form: MenuForm) -> MenuDefinition:
    result = validate_form(form)
    assert result.definition is not None, result.form
    return result.definition


def _view(form: MenuForm, catalog: int = 3):  # type: ignore[no-untyped-def]
    return answers_view(validate_form(form).form, catalog)


def _labels(form: MenuForm) -> list[str]:
    return [a.label for a in read_answers(form)]


def _layout(definition: MenuDefinition) -> tuple[list[str], list[str]]:
    start = definition.nodes[definition.start_node]
    assert isinstance(start, ButtonsNode)
    buttons = [o.label for o in start.options]
    rows: list[str] = []
    for o in start.options:
        target = definition.nodes[o.next]
        if isinstance(target, ListNode):
            rows = [r.title for s in target.sections for r in s.rows]
    return buttons, rows


# --- a new menu ------------------------------------------------------------------------


def test_a_new_menu_never_starts_from_the_invented_example() -> None:
    definition = template_definition("fast_food", StarterFacts(business_name="Bianki"))
    assert definition is not None and definition != BIANKI_DEMO_MENU
    assert "Calle 10" not in definition.model_dump_json()
    assert template_definition("empty") is None


def test_step_two_reads_the_starter_as_one_ordered_list() -> None:
    view = _view(_starter())
    assert [a.label for a in view.buttons] == ["Ver menú y pedir", "Horario"]
    assert [a.label for a in view.rows] == [
        "Domicilio",
        "Dónde estamos",
        "Formas de pago",
        "Reservas",
        "Hablar con alguien",
    ]
    assert view.has_more and view.rows_count == "5 de 10" and view.count == 7
    by_name = {a.label: a for a in [*view.buttons, *view.rows]}
    assert by_name["Ver menú y pedir"].status_label == "Lista"
    assert by_name["Horario"].status_label == "Falta completar"
    assert by_name["Horario"].gaps_line == "Falta: qué días · hora de abrir · hora de cerrar"
    assert by_name["Formas de pago"].status_label == "Sugerida"
    assert by_name["Reservas"].status_label == "Sugerida"
    assert by_name["Reservas"].does == "Responde y te pasa el chat"
    assert by_name["Hablar con alguien"].does == "Te pasa el chat"
    assert by_name["Hablar con alguien"].status_label == "Lista"
    assert by_name["Horario"].label_count == "7 de 20"
    assert not view.blocking


def test_an_empty_catalog_marks_the_products_answer_missing() -> None:
    view = _view(_starter(), catalog=0)
    assert view.buttons[0].is_products and view.buttons[0].status_label == "Falta completar"
    assert not view.buttons[0].has_gaps  # not a gap: the customer gets the empty text


# --- order and the button limit -------------------------------------------------------


def test_moving_an_answer_keeps_its_id_and_re_lays_out_the_buttons() -> None:
    form = _starter()
    ids = {a.label: a.option_id for a in read_answers(form)}
    moved = answers_move(form, 2, -1)  # Domicilio up: swaps with Horario
    assert _labels(moved)[:3] == ["Ver menú y pedir", "Domicilio", "Horario"]
    assert {a.label: a.option_id for a in read_answers(moved)} == ids
    buttons, rows = _layout(_valid(moved))
    assert buttons == ["Ver menú y pedir", "Domicilio", "Más preguntas"]
    assert rows[0] == "Horario"
    assert answers_move(form, 0, -1) == form and answers_move(form, 6, 1) == form
    assert answers_move(form, 1, 5) == form


def test_up_on_the_first_row_explains_the_limit_instead_of_moving() -> None:
    assert move_hits_button_limit(7, 2, -1)
    assert not move_hits_button_limit(3, 2, -1)
    assert not move_hits_button_limit(7, 3, -1) and not move_hits_button_limit(7, 2, 1)
    assert "Ya usas los 3 botones que deja WhatsApp" in button_limit_text("Domicilio")
    assert "Para que «Domicilio» sea botón, baja otra respuesta." in button_limit_text("Domicilio")


def test_three_answers_are_three_buttons_and_more_brings_the_list_back() -> None:
    form = _starter()
    for _ in range(4):
        form = answers_remove(form, 2)
    assert _labels(form) == ["Ver menú y pedir", "Horario", "Hablar con alguien"]
    definition = _valid(form)
    assert _layout(definition) == (["Ver menú y pedir", "Horario", "Hablar con alguien"], [])
    assert "mas_preguntas" not in definition.nodes  # the list nothing opens is gone
    view = _view(form)
    assert not view.has_more and len(view.buttons) == 3
    form, index = answers_add(form, "promociones")
    assert index == 3
    buttons, rows = _layout(_valid(form))
    assert buttons == ["Ver menú y pedir", "Horario", "Más preguntas"]
    assert rows == ["Hablar con alguien", "Promociones"]


def test_the_list_holds_twelve_answers_at_most_and_says_why() -> None:
    form = _starter()
    for _ in range(5):
        form, _index = answers_add(form, SUGGESTION_CUSTOM)
    assert len(read_answers(form)) == 12
    view = _view(form)
    assert view.full and view.rows_count == "10 de 10"
    full, index = answers_add(form, "promociones")
    assert index == -1 and full == form


# --- edit, remove, add ---------------------------------------------------------------


def test_editing_an_answer_fills_its_gaps_and_keeps_its_step() -> None:
    form = _starter()
    form = answer_set_text(
        form, 1, "Abrimos de lunes a sábado, de 11:00 a. m. a 9:00 p. m. Escribe *menú*."
    )
    form = answer_set_label(form, 1, "Horario de hoy")
    view = _view(form)
    hours = view.buttons[1]
    assert hours.status_label == "Lista" and not hours.has_gaps and hours.gaps_line == ""
    definition = _valid(form)
    assert definition.nodes["horario"].title == "Horario de hoy"
    assert "horario" not in {g.node_id for g in definition_gaps(definition)}


def test_name_and_text_errors_say_what_to_do() -> None:
    form = answer_set_label(_starter(), 1, "Horario de atención al cliente")
    assert _view(form).buttons[1].label_error == ANSWER_NAME_TOO_LONG
    form = answer_set_label(_starter(), 2, "Horario")
    assert _view(form).rows[0].label_error == (
        "Ya tienes una respuesta llamada «Horario». Ponle otro nombre."
    )
    assert _view(form).blocking
    form = answer_set_text(_starter(), 1, "")
    assert _view(form).buttons[1].text_error == ANSWER_TEXT_MISSING


def test_removing_an_answer_removes_its_message_but_never_the_fallback() -> None:
    form = _starter()
    reservas = _labels(form).index("Reservas")
    form = answers_remove(form, reservas)
    definition = _valid(form)
    assert "reservas" not in definition.nodes and "Reservas" not in _labels(form)
    person = _labels(form).index("Hablar con alguien")
    form = answers_remove(form, person)
    definition = _valid(form)
    assert "persona" in definition.nodes and definition.entry.fallback_node == "persona"


def test_removing_every_answer_leaves_a_valid_greeting_and_adding_brings_buttons() -> None:
    form = _starter()
    while read_answers(form):
        form = answers_remove(form, 0)
    _valid(form)
    view = _view(form)
    assert view.count == 0
    assert answers_summary(view, has_fallback=True).startswith("Tu cliente solo verá tu saludo.")
    assert SUGGESTION_PRODUCTS in {s.key for s in view.suggestions}  # it can come back
    form, index = answers_add(form, SUGGESTION_PRODUCTS)
    assert index == 0
    buttons, _rows = _layout(_valid(form))
    assert buttons == ["Ver menú y pedir"]


def test_an_empty_menu_grows_its_first_answer() -> None:
    form, index = answers_add(empty_form(), "ingredientes")
    assert index == 0
    form = answer_set_text(form, 0, "Usamos pollo, pan árabe y vegetales frescos.")
    definition = _valid(form)
    assert _layout(definition) == (["Ingredientes"], [])


def test_the_suggestions_are_the_three_of_the_spec() -> None:
    labels = [s.label for s in _view(_starter()).suggestions]
    assert labels == ["Promociones", "Pedidos para eventos", "Ingredientes"]


# --- a gap never reaches a customer ----------------------------------------------------


def _gaps_vm(form: MenuForm):  # type: ignore[no-untyped-def]
    definition = _valid(form)
    stripped = validate_form(answers_without_gaps(form)).definition
    leaves = stripped is None or bool(definition_gaps(stripped))
    return publish_gaps(form, definition_gaps(definition), strip_leaves_gaps=leaves)


def test_step_four_names_the_answers_with_gaps_and_can_strip_them() -> None:
    form = _starter(address="Av. 5 #12-30")
    gaps = _gaps_vm(form)
    assert gaps.any and gaps.greeting == "" and not gaps.elsewhere
    assert gaps.answers_text == (
        "4 respuestas tienen datos por completar: Horario, Domicilio, Formas de pago y "
        "Reservas. Así no se las mostramos a tus clientes."
    )
    assert gaps.can_strip
    stripped = answers_without_gaps(form)
    assert _labels(stripped) == ["Ver menú y pedir", "Dónde estamos", "Hablar con alguien"]
    assert definition_gaps(_valid(stripped)) == []
    assert not _gaps_vm(stripped).any


def test_a_greeting_gap_cannot_be_stripped_away() -> None:
    form = definition_to_form(build_starter_menu(StarterFacts()))
    gaps = _gaps_vm(form)
    assert gaps.greeting == ("Tu saludo tiene datos por completar. Falta: nombre de tu negocio.")
    assert not gaps.can_strip


def test_one_gap_reads_in_the_singular() -> None:
    form = _starter(address="Av. 5")
    for label in ("Horario", "Domicilio", "Reservas"):
        form = answers_remove(form, _labels(form).index(label))
    assert _gaps_vm(form).answers_text == (
        "1 respuesta tiene datos por completar: Formas de pago. Así no se las mostramos a "
        "tus clientes."
    )


def test_a_suggested_answer_edited_is_no_longer_suggested() -> None:
    form = _starter()
    index = _labels(form).index("Formas de pago")
    form = answer_set_text(form, index, PAYMENT_TEXT.replace("Te confirmamos", "Confirmamos"))
    row = next(a for a in _view(form).rows if a.label == "Formas de pago")
    assert row.status_label == "Falta completar"


def test_summary_in_words() -> None:
    view = _view(_starter())
    assert answers_summary(view, has_fallback=True) == (
        "Tu cliente verá tu saludo, 2 botones y «Más preguntas» con 5 respuestas. Si escribe "
        "algo que el menú no entiende, te pasa el chat."
    )


def test_the_old_example_still_reads_with_its_sub_menu() -> None:
    form = definition_to_form(BIANKI_DEMO_MENU)
    view = _view(form)
    assert [a.label for a in view.buttons] == [
        "Ver menú y pedir",
        "Horario y ubicación",
        "Hablar con alguien",
    ]
    assert view.buttons[1].does == "Muestra otros botones"
    result = validate_form(form)
    assert guided_view(result.form, result.error_count).hidden_issues == 0


def test_guided_view_counts_row_errors_as_shown() -> None:
    form = _starter()
    form = answer_set_text(form, 3, "")  # «Dónde estamos», a row
    result = validate_form(form)
    view = guided_view(result.form, result.error_count)
    assert view.buttons_issue and view.hidden_issues == 0
    assert replace(view, buttons_issue=False) != view


def test_the_step_renders_the_list_the_panel_and_the_gap_exits() -> None:
    import json

    from . import whatsapp_tab_menu

    rendered = str(whatsapp_tab_menu.menu_tab().render())

    def present(text: str) -> bool:
        escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
        return text in rendered or escaped in rendered

    for text in (
        "Botones (WhatsApp muestra hasta 3)",
        "Más preguntas (lo pone Qualify)",
        "Abre la lista de abajo",
        "Agregar otra respuesta",
        "Escribir la mía",
        "Subir",
        "Bajar",
        "Editar",
        "Volver a tus respuestas",
        "Nombre (lo que ve tu cliente)",
        "Lo que le respondes",
        "Quitar esta respuesta",
        "Dejarla",
        "Dejar así",
        "Completarlas",
        "Quitar las que faltan y publicar",
        "Agregar una respuesta",
    ):
        assert present(text), text
    for gone in ("Agregar un botón", "Mostrar más botones", "ejemplo de comida rápida"):
        assert not present(gone), gone


# --- the state: step 2 handlers and the publish gate ------------------------------------


def _state():  # type: ignore[no-untyped-def]
    from uuid import uuid4

    from .whatsapp_menu_provider import MenuDetail
    from .whatsapp_menu_state import WhatsAppMenuState
    from .whatsapp_menu_vm import MenuSummaryVM, MenuVersionVM

    definition = build_starter_menu(StarterFacts(business_name="Bianki", address="Av. 5"))
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
    state._scope = {"phone_row_id": str(uuid4()), "brand_id": "", "brand_name": "Bianki"}
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


def test_a_gap_keeps_the_publish_button_off_until_it_is_completed_or_removed() -> None:
    state = _state()
    assert state.error_count == 0 and state.gap_count == 4
    assert not state.can_publish
    assert state.publish_gaps.can_strip
    state.strip_gaps_and_publish()
    assert state.gap_count == 0 and state.can_publish and state.publish_confirm_open
    assert [a.label for a in state.answers.buttons] == [
        "Ver menú y pedir",
        "Dónde estamos",
        "Hablar con alguien",
    ]


def test_the_panel_edits_the_answer_and_removing_asks_first() -> None:
    state = _state()
    state.open_answer_panel(1)
    assert state.open_answer.label == "Horario" and state.has_open_answer
    state.set_answer_text("Abrimos todos los días, de 11:00 a. m. a 10:00 p. m.")
    assert state.open_answer.status_label == "Lista" and state.dirty
    state.remove_answer()  # not confirmed: nothing happens
    assert state.answers.count == 7
    state.ask_remove_answer()
    assert state.remove_confirm_text.startswith("¿Quitar «Horario»?")
    state.remove_answer()
    assert state.answers.count == 6 and not state.has_open_answer
    state.open_answer_panel(99)  # over the wire: ignored
    assert not state.has_open_answer


def test_up_on_the_first_row_shows_the_limit_and_offers_the_way_out() -> None:
    state = _state()
    state.move_answer(2, -1)
    assert state.limit_notice == 2
    assert "«Domicilio» y las demás" in state.limit_notice_text
    assert state.limit_move_label == "Bajar «Horario»"
    assert [a.label for a in state.answers.buttons] == ["Ver menú y pedir", "Horario"]
    state.limit_move_down()
    assert [a.label for a in state.answers.buttons] == ["Ver menú y pedir", "Domicilio"]
    assert state.limit_notice == -1
    state.move_answer(3, -1)  # inside the list: just moves
    assert state.answers.rows[0].label == "Dónde estamos"


def test_adding_a_suggestion_opens_its_panel() -> None:
    state = _state()
    state.toggle_add_answer()
    assert state.add_open
    state.add_answer("promociones")
    assert not state.add_open and state.open_answer.label == "Promociones"
    assert state.open_answer.gaps_line == "Falta: tu promoción"
    state.add_answer("nope")
    assert state.answers.count == 8

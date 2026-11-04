"""m-24936836: a new menu is born with the usual answers, gaps in brackets, never an
invented datum — and a gap never reaches a customer. Pure, offline."""

from __future__ import annotations

from qualify_api.whatsapp.menus.engine import (
    Handoff,
    Inbound,
    SendButtons,
    SendList,
    SendText,
    ThreadMenuState,
    step,
)
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.menus.schema import (
    BUTTON_TITLE_MAX_LEN,
    LIST_ROW_TITLE_MAX_LEN,
    MAX_BUTTONS,
    ButtonsNode,
    ListNode,
)
from qualify_api.whatsapp.menus.starter import (
    MAX_ANSWERS,
    MORE_LABEL,
    NAME_GAP,
    Gap,
    StarterFacts,
    build_starter_menu,
    definition_gaps,
    find_gaps,
    lay_out,
    reachable_nodes,
)


def _labels(definition):  # type: ignore[no-untyped-def]
    start = definition.nodes[definition.start_node]
    assert isinstance(start, ButtonsNode)
    more = definition.nodes["mas_preguntas"]
    assert isinstance(more, ListNode)
    return [o.label for o in start.options], [r.title for s in more.sections for r in s.rows]


def test_the_food_menu_is_born_with_the_usual_answers_in_order() -> None:
    menu = build_starter_menu(StarterFacts(business_name="Bianki"))
    buttons, rows = _labels(menu)
    assert buttons == ["Ver menú y pedir", "Horario", MORE_LABEL]
    assert rows == [
        "Domicilio",
        "Dónde estamos",
        "Formas de pago",
        "Reservas",
        "Hablar con alguien",
    ]
    assert all(len(b) <= BUTTON_TITLE_MAX_LEN for b in buttons)
    assert all(len(r) <= LIST_ROW_TITLE_MAX_LEN for r in rows)
    assert "Precios" not in buttons + rows  # prices come with «Ver menú y pedir»
    assert menu.entry.welcome == (
        "¡Hola! Gracias por escribir a Bianki. Aquí ves el menú, haces tu pedido y resuelves "
        "tus dudas."
    )
    assert menu.entry.fallback_node == "persona"


def test_no_invented_datum_from_the_example_ever_reaches_a_new_menu() -> None:
    dumped = build_starter_menu(StarterFacts()).model_dump_json()
    for invented in ("Calle 10", "5-20", "12:00", "22:00", "barrio Centro"):
        assert invented not in dumped, invented
    # the example stays for the engine tests, unchanged
    assert "Calle 10" in BIANKI_DEMO_MENU.model_dump_json()


def test_what_qualify_does_not_know_is_a_visible_gap() -> None:
    menu = build_starter_menu(StarterFacts())
    gaps = {g.node_id: g.names for g in definition_gaps(menu)}
    assert gaps[None] == ("nombre de tu negocio",)
    assert NAME_GAP in (menu.entry.welcome or "")
    assert gaps["horario"] == ("qué días", "hora de abrir", "hora de cerrar")
    assert gaps["domicilio"] == ("barrios o zona", "precio del envío", "minutos")
    assert gaps["ubicacion"] == ("dirección y barrio",)
    assert gaps["pagos"] == ("formas de pago: efectivo, transferencia…",)
    assert gaps["reservas"] == ("cuánto tardas en responder",)
    assert "persona" not in gaps and "productos" not in gaps


def test_known_facts_fill_the_greeting_and_the_location() -> None:
    menu = build_starter_menu(
        StarterFacts(business_name="Polette", address="Av. 5 #12-30, La Riviera.")
    )
    gaps = {g.node_id for g in definition_gaps(menu)}
    assert None not in gaps and "ubicacion" not in gaps
    assert menu.nodes["ubicacion"].body == "Estamos en Av. 5 #12-30, La Riviera. ¡Te esperamos!"  # type: ignore[union-attr]
    city_only = build_starter_menu(StarterFacts(business_name="Polette", city="Cúcuta"))
    assert city_only.nodes["ubicacion"].body == (  # type: ignore[union-attr]
        "Estamos en [dirección y barrio], Cúcuta. ¡Te esperamos!"
    )


def test_a_fact_with_brackets_never_reads_as_a_gap() -> None:
    menu = build_starter_menu(StarterFacts(business_name="Bianki [Centro]", address="Local [2]"))
    assert {g.node_id for g in definition_gaps(menu)} >= {"horario"}
    assert None not in {g.node_id for g in definition_gaps(menu)}
    assert "ubicacion" not in {g.node_id for g in definition_gaps(menu)}


def test_find_gaps_is_ordered_and_unique() -> None:
    assert find_gaps("De [a] a [b], otra vez [a].") == ["a", "b"]
    assert find_gaps("Sin huecos.") == []
    assert find_gaps("") == []


def test_only_steps_a_customer_can_reach_count_as_gaps() -> None:
    menu = build_starter_menu(StarterFacts(business_name="Bianki"))
    payload = menu.model_dump(mode="json")
    nodes = payload["nodes"]
    # drop «Horario» from the buttons: its step stays, but nothing leads there any more
    nodes["inicio"]["options"] = [o for o in nodes["inicio"]["options"] if o["id"] != "horario"]
    unreachable = type(menu).model_validate(payload)
    assert "horario" not in reachable_nodes(unreachable)
    assert "horario" not in {g.node_id for g in definition_gaps(unreachable)}


def test_the_layout_rule() -> None:
    def answers(n: int) -> list[dict[str, str]]:
        return [{"id": f"a{i}", "label": f"R{i}", "next": "x"} for i in range(n)]

    assert lay_out(answers(3)) == (answers(3), [])
    buttons, rows = lay_out(answers(4))
    assert len(buttons) == MAX_BUTTONS - 1 and len(rows) == 2
    buttons, rows = lay_out(answers(MAX_ANSWERS + 3))
    assert len(buttons) + len(rows) == MAX_ANSWERS == 12


def test_the_engine_walks_the_starter_menu() -> None:
    menu = build_starter_menu(StarterFacts(business_name="Bianki"))
    result = step(menu, ThreadMenuState(), Inbound(kind="welcome", first_message=True))
    assert isinstance(result.actions[0], SendText)
    buttons = next(a for a in result.actions if isinstance(a, SendButtons))
    assert [b.title for b in buttons.buttons] == ["Ver menú y pedir", "Horario", "Más preguntas"]
    more = step(menu, result.state, Inbound(kind="button_reply", value="mas_preguntas"))
    listing = next(a for a in more.actions if isinstance(a, SendList))
    assert [r.title for r in listing.rows][-1] == "Hablar con alguien"
    person = step(menu, more.state, Inbound(kind="list_reply", value="persona"))
    assert person.handed_off and any(isinstance(a, Handoff) for a in person.actions)


def test_gap_is_a_frozen_value() -> None:
    assert Gap(None, ("a",)) == Gap(None, ("a",))

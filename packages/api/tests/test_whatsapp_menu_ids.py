"""Generated menu identifiers and step names (m-24848536): the owner never types an id;
ids are slug + short random suffix, valid for the schema, unique, and a step's name
(`title`) is separate data the engine ignores."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.menus.ids import SLUG_MAX_LEN, new_node_id, new_option_id, slugify
from qualify_api.whatsapp.menus.schema import (
    _NODE_ID_RE,
    STEP_TITLE_MAX_LEN,
    MenuDefinition,
    TextNode,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("¿Horario y ubicación?", "horario-y-ubicacion"),
        ("  Ñandú  PARA  llevar!! ", "nandu-para-llevar"),
        ("Menú — 2×1", "menu-2-1"),
        ("🍔🍟", "paso"),
        ("", "paso"),
    ],
)
def test_slugify_drops_accents_symbols_and_case(text: str, expected: str) -> None:
    assert slugify(text) == expected


def test_slugify_is_capped_and_never_ends_on_a_separator() -> None:
    slug = slugify("a" * 39 + " bbbb")
    assert len(slug) <= SLUG_MAX_LEN
    assert not slug.endswith("-")


@pytest.mark.parametrize(
    "label", ["Horario", "¿Qué quieres hacer?", "", "9 de la noche", "x" * 200, "🍕"]
)
def test_new_node_id_always_passes_the_schema_rule(label: str) -> None:
    node_id = new_node_id(label, set())
    assert _NODE_ID_RE.match(node_id), node_id
    assert len(node_id) <= 64


def test_new_ids_are_slug_plus_suffix_and_unique() -> None:
    assert new_node_id("Horario", set(), token=lambda: "3fa9") == "horario-3fa9"
    assert new_option_id("Ver menú", set(), token=lambda: "0b1c") == "ver-menu-0b1c"
    assert new_option_id("", set(), token=lambda: "0b1c") == "boton-0b1c"
    taken = {"horario-3fa9"}
    # a constant token cannot loop forever: the suffix is widened until it is free
    again = new_node_id("Horario", taken, token=lambda: "3fa9")
    assert again not in taken and again.startswith("horario-3fa9")
    many: set[str] = set()
    for _ in range(200):
        many.add(new_node_id("Horario", many))
    assert len(many) == 200


def test_titles_are_optional_so_saved_menus_still_validate() -> None:
    payload = BIANKI_DEMO_MENU.model_dump(mode="json")
    for node in payload["nodes"].values():
        node.pop("title")
    old = MenuDefinition.model_validate(payload)  # a version saved before m-24848536
    assert all(n.title is None for n in old.nodes.values())
    assert old.nodes.keys() == BIANKI_DEMO_MENU.nodes.keys()


def test_template_steps_have_names_and_titles_are_capped() -> None:
    assert all(n.title for n in BIANKI_DEMO_MENU.nodes.values())
    with pytest.raises(ValidationError):
        TextNode(kind="text", body="Hola", title="x" * (STEP_TITLE_MAX_LEN + 1))

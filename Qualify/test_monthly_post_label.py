"""m-25120706: a «Publicación del mes» in «Por aprobar» says the date it was made for."""

from __future__ import annotations

from datetime import date
from uuid import UUID

import reflex as rx
from qualify_api.ads.month_plan import load_table
from qualify_api.planner.monthly_post import Occasion

from . import creative_pages, planner_provider
from .planner_vm import PostOptionVM, build_post_option, occasion_label_text

_PostVar = rx.Var(_js_expr="post", _var_type=PostOptionVM).guess_type()


#: Every name of the calendar (all countries) after «Te la preparamos para» — the decision
#: per name. A new calendar name fails `test_every_calendar_name_has_its_phrase`.
EXPECTED = {
    "Día de Reyes": "el Día de Reyes",
    "Día de la Madre": "el Día de la Madre",
    "Día de la Niñez": "el Día de la Niñez",
    "Día de las Madres": "el Día de las Madres",
    "Día de los Enamorados": "el Día de los Enamorados",
    "Día de los Hijos": "el Día de los Hijos",
    "Día del Niño": "el Día del Niño",
    "Día del Padre": "el Día del Padre",
    "Regreso a clases": "el regreso a clases",
    "Quincena": "la quincena",
    "Prima de servicios": "la prima de servicios",
    "Aguinaldo": "el aguinaldo",
    "Cobro del sueldo": "el cobro del sueldo",
    "Utilidades y aguinaldos": "las utilidades y aguinaldos",
    "Navidad": "Navidad",
    "Carnaval": "Carnaval",
    "Halloween": "Halloween",
    "San Valentín": "San Valentín",
    "Amor y Amistad": "Amor y Amistad",
    "Black Friday": "Black Friday",
    "Black Week": "Black Week",
    "Cyber Monday": "Cyber Monday",
    "CyberLunes": "CyberLunes",
    "Hot Sale": "Hot Sale",
}


def test_every_calendar_name_has_its_phrase() -> None:
    table = load_table()
    names = {e.name for entries in table.countries.values() for e in entries}
    assert names == set(EXPECTED)  # a new name needs its decision here and in the map
    day = date(2026, 5, 9)
    for name, phrase in EXPECTED.items():
        assert occasion_label_text(name, day) == f"Te la preparamos para {phrase} (9 de mayo)"


def test_the_label_names_the_date_and_its_day_in_spanish() -> None:
    assert occasion_label_text("Día de la Madre", date(2026, 5, 9)) == (
        "Te la preparamos para el Día de la Madre (9 de mayo)"
    )
    assert occasion_label_text("Navidad", date(2026, 12, 25)) == (
        "Te la preparamos para Navidad (25 de diciembre)"
    )
    assert occasion_label_text("Regreso a clases", date(2027, 1, 12)) == (
        "Te la preparamos para el regreso a clases (12 de enero)"
    )
    # an unknown name goes bare rather than with a wrong article
    assert occasion_label_text("Fiesta X", date(2026, 3, 1)) == (
        "Te la preparamos para Fiesta X (1 de marzo)"
    )


def test_the_card_view_model_carries_the_label_and_defaults_to_none() -> None:
    common = dict(
        post_id="p", title="t", caption_excerpt="", thumbnail_url="", category="galeria",
        approval="pending", detail_href="/drafts/p", is_publishable=False,
        unpublishable_reason="",
    )  # fmt: skip
    assert build_post_option(**common).occasion_label == ""  # type: ignore[arg-type]
    labelled = build_post_option(**common, occasion_label="x")  # type: ignore[arg-type]
    assert labelled.occasion_label == "x"


def test_the_gallery_reads_the_labels_once_and_survives_a_failed_read(monkeypatch) -> None:
    calls: list[list[UUID]] = []

    def fake(tenant_id: UUID, ids: list[UUID]) -> dict[UUID, Occasion]:
        calls.append(list(ids))
        return {UUID(int=1): Occasion("Día del Padre", date(2026, 6, 21))}

    monkeypatch.setattr(planner_provider, "occasions_of", fake)
    labels = planner_provider._occasion_labels(UUID(int=9), [UUID(int=1), UUID(int=2)])
    assert labels == {UUID(int=1): "Te la preparamos para el Día del Padre (21 de junio)"}
    assert calls == [[UUID(int=1), UUID(int=2)]]  # one read for the batch

    def broken(tenant_id: UUID, ids: list[UUID]) -> dict[UUID, Occasion]:
        raise RuntimeError("db down")

    monkeypatch.setattr(planner_provider, "occasions_of", broken)
    assert planner_provider._occasion_labels(UUID(int=9), [UUID(int=1)]) == {}


def test_the_gallery_card_shows_the_label() -> None:
    assert "occasion_label" in str(creative_pages._gallery_card(_PostVar))

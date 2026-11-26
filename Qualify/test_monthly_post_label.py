"""m-25120706: a «Publicación del mes» in «Por aprobar» says the date it was made for."""

from __future__ import annotations

from datetime import date
from uuid import UUID

import reflex as rx
from qualify_api.planner.monthly_post import Occasion

from . import creative_pages, planner_provider
from .planner_vm import PostOptionVM, build_post_option, occasion_label_text

_PostVar = rx.Var(_js_expr="post", _var_type=PostOptionVM).guess_type()


def test_the_label_names_the_date_and_its_day_in_spanish() -> None:
    assert occasion_label_text("Día de la Madre", date(2026, 5, 9)) == (
        "Para el Día de la Madre (9 de mayo)"
    )
    # «el» only before «Día …»; names in English stay as they are (proper names)
    assert occasion_label_text("Navidad", date(2026, 12, 25)) == "Para Navidad (25 de diciembre)"
    assert occasion_label_text("Black Friday", date(2026, 11, 27)) == (
        "Para Black Friday (27 de noviembre)"
    )


def test_the_card_view_model_carries_the_label_and_defaults_to_none() -> None:
    common = dict(
        post_id="p", title="t", caption_excerpt="", thumbnail_url="", category="galeria",
        approval="pending", detail_href="/drafts/p", is_publishable=False,
        unpublishable_reason="",
    )  # fmt: skip
    assert build_post_option(**common).occasion_label == ""  # type: ignore[arg-type]
    labelled = build_post_option(**common, occasion_label="Para Navidad (25 de diciembre)")  # type: ignore[arg-type]
    assert labelled.occasion_label == "Para Navidad (25 de diciembre)"


def test_the_gallery_reads_the_labels_once_and_survives_a_failed_read(monkeypatch) -> None:
    calls: list[list[UUID]] = []

    def fake(tenant_id: UUID, ids: list[UUID]) -> dict[UUID, Occasion]:
        calls.append(list(ids))
        return {UUID(int=1): Occasion("Día del Padre", date(2026, 6, 21))}

    monkeypatch.setattr(planner_provider, "occasions_of", fake)
    labels = planner_provider._occasion_labels(UUID(int=9), [UUID(int=1), UUID(int=2)])
    assert labels == {UUID(int=1): "Para el Día del Padre (21 de junio)"}
    assert calls == [[UUID(int=1), UUID(int=2)]]  # one read for the batch

    def broken(tenant_id: UUID, ids: list[UUID]) -> dict[UUID, Occasion]:
        raise RuntimeError("db down")

    monkeypatch.setattr(planner_provider, "occasions_of", broken)
    assert planner_provider._occasion_labels(UUID(int=9), [UUID(int=1)]) == {}


def test_the_gallery_card_shows_the_label() -> None:
    assert "occasion_label" in str(creative_pages._gallery_card(_PostVar))

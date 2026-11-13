"""UI-6 (m-24921081): «Revisa y crea» por partes — the pure part (`reel_parts_vm`):
the summary in words, the two actions' labels and why either is disabled (all or
nothing: a part the analysis could not see, the form, the month's counters)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from qualify_creative.schemas import VideoPartPlan

from . import reel_parts_vm as vm
from .ask_more_vm import PREVIEWS, VIDEOS
from .test_reel_parts_vm import MOCKUP, entries_of

REEL = UUID("00000000-0000-0000-0000-0000000000aa")


def entry(
    mode: str = "reference",
    seconds: int = 5,
    *,
    description: str = "el producto gira",
    notices: tuple[str, ...] = (),
    cut: int = 0,
) -> dict[str, Any]:
    plan = VideoPartPlan(
        mode=mode,  # type: ignore[arg-type]
        seconds=seconds,
        analysis_id=REEL,
        shot_indexes=(cut,),
        description=description,
        notices=notices,  # type: ignore[arg-type]
    )
    return {"key": f"k{mode}{seconds}", "plan": plan.model_dump(mode="json"), "person": False}


def parts(*modes: str, seconds: int = 4) -> list[dict[str, Any]]:
    return [entry(mode, seconds, cut=at) for at, mode in enumerate(modes)]


# -- the summary in words (§3d) ---------------------------------------------------------


def test_the_summary_of_the_spec() -> None:
    entries = parts("edit", "edit", "reference", "reference")
    entries[0] = entry("edit", 6)
    assert vm.review_summary_text(entries, "smash doble") == (
        "Un reel de 18 s en 4 partes, con tu smash doble. "
        "Dos conservan el original y dos se hacen nuevas."
    )


def test_one_part_says_parte_in_the_singular() -> None:
    assert vm.review_summary_text([entry("edit", 5)], "smash doble") == (
        "Un reel de 5 s en 1 parte, con tu smash doble. La parte conserva el original."
    )
    assert vm.review_summary_text([entry("reference", 5)]) == (
        "Un reel de 5 s en 1 parte. La parte se hace nueva."
    )


def test_two_parts_of_one_form() -> None:
    assert vm.review_summary_text(parts("reference", "reference"), "flan") == (
        "Un reel de 8 s en 2 partes, con tu flan. Las dos se hacen nuevas."
    )


def test_a_mix_of_three_forms_in_words_and_agreeing() -> None:
    text = vm.review_summary_text(parts("edit", "reference", "extend", "reference"))
    assert text == (
        "Un reel de 16 s en 4 partes. "
        "Una conserva el original, dos se hacen nuevas y una sigue a la anterior."
    )


def test_the_mockup_reel() -> None:
    text = vm.review_summary_text(entries_of(MOCKUP), "smash doble")
    assert text.startswith("Un reel de 21 s en 4 partes, con tu smash doble. ")
    assert "conserva" in text and "se hace nueva" in text


def test_without_product_and_without_parts() -> None:
    assert vm.review_summary_text(parts("edit", "edit"), "  ") == (
        "Un reel de 8 s en 2 partes. Las dos conservan el original."
    )
    assert vm.review_summary_text([]) == ""


def test_several_extend_parts_follow_each_their_own() -> None:
    text = vm.review_summary_text(parts("edit", "extend", "reference", "extend"))
    assert text.endswith(
        "Una conserva el original, una se hace nueva y dos siguen cada una a la anterior."
    )


def test_numbers_in_words_up_to_ten() -> None:
    text = vm.review_summary_text(parts(*(["edit"] * 6)))
    assert text.endswith("Las seis conservan el original.")


# -- the labels ------------------------------------------------------------------------


def test_create_all_label() -> None:
    assert vm.create_all_label(1) == "Crear la parte"
    assert vm.create_all_label(4) == "Crear las 4 partes"


# -- a part the analysis could not see (Deivid 2026-11-09: «Sí, bloquear») -------------


def test_a_part_without_description_blocks_both_buttons() -> None:
    entries = parts("edit", "reference", "reference")
    entries[2] = entry("reference", 4, description="", notices=("describe_it",))
    review = vm.review_actions(entries, previews_left=10, previews_quota=20)
    text = "Falta contar qué pasa en la parte 3. Escríbelo para crear tu video."
    assert vm.parts_blocked_text(entries) == text
    assert review.all_reason == review.first_reason == text
    assert review.back_to_parts and review.exhausted == ""


def test_a_described_part_does_not_block() -> None:
    entries = [entry("reference", 4, description="lo cuenta el dueño", notices=("describe_it",))]
    assert vm.blocked_parts(entries) == [] and vm.parts_blocked_text(entries) == ""


def test_several_parts_and_every_part_blocked() -> None:
    blind = entry("reference", 4, description="", notices=("describe_it",))
    entries = [blind, entry("edit"), blind]
    assert vm.parts_blocked_text(entries) == (
        "Falta contar qué pasa en las partes 1 y 3. Escríbelo para crear tu video."
    )
    review = vm.review_actions(entries, previews_left=10, previews_quota=20)
    assert review.back_to_parts and not review.to_ideas
    assert review.foot_reason == "Falta contar qué pasa en algunas partes."


@pytest.mark.parametrize("count", [1, 3])
def test_every_part_blocked_can_be_described(count: int) -> None:
    blind = entry("reference", 4, description="", notices=("describe_it",))
    entries = [blind] * count
    which = "la parte 1" if count == 1 else "las partes 1, 2 y 3"
    text = f"Falta contar qué pasa en {which}. Escríbelo para crear tu video."
    assert vm.parts_blocked_text(entries) == text
    review = vm.review_actions(entries, previews_left=10, previews_quota=20)
    assert review.all_reason == review.first_reason == text
    assert not review.to_ideas and review.back_to_parts


# -- the month (all or nothing) --------------------------------------------------------


def test_enough_vistas_previas_both_active() -> None:
    review = vm.review_actions(
        parts("edit", "reference", "reference", "edit"),
        product="smash doble",
        previews_left=4,
        previews_quota=20,
        seconds_left=40,
        seconds_quota=40,
    )
    assert review.all_label == "Crear las 4 partes" and review.try_first
    assert review.all_reason == review.first_reason == "" and not review.back_to_parts


def test_short_of_vistas_previas_only_part_1_can_be_tried() -> None:
    review = vm.review_actions(
        parts("edit", "reference", "reference", "edit"),
        previews_left=2,
        previews_quota=20,
        renews="1 de diciembre",
    )
    assert review.all_reason == (
        "Crear las 4 partes usa 4 vistas previas y este mes te quedan 2. Quita 2 partes en "
        "el paso 2, prueba solo la parte 1 o espera al 1 de diciembre, cuando vuelven tus 20 "
        "vistas previas."
    )
    assert review.first_reason == "" and review.back_to_parts


def test_one_vista_previa_left_singular() -> None:
    text = vm.parts_previews_short_text(3, 1, 20)
    assert "y este mes te queda 1." in text and "espera al próximo mes" in text
    assert "Quita 2 partes" in text
    assert "Quita 1 parte en el paso 2" in vm.parts_previews_short_text(3, 2, 20)
    assert vm.parts_previews_short_text(3, 0, 20) == ""  # at 0: the zero state, no «prueba»


def test_no_vista_previa_left_disables_both_and_offers_to_ask() -> None:
    review = vm.review_actions(parts("edit", "edit"), previews_left=0, previews_quota=20)
    assert review.exhausted == PREVIEWS
    assert review.all_reason == review.first_reason != ""
    assert "20 vistas previas" in review.all_reason


def test_no_second_of_video_left_disables_both() -> None:
    review = vm.review_actions(
        parts("edit", "edit"), previews_left=5, previews_quota=20, seconds_left=0, seconds_quota=40
    )
    assert review.exhausted == VIDEOS and review.first_reason != ""
    assert "40 segundos de video" in review.all_reason


def test_without_a_quota_nothing_blocks() -> None:
    review = vm.review_actions(parts("edit", "edit", "edit"))
    assert review.all_reason == review.first_reason == "" and review.exhausted == ""


def test_one_part_has_no_try_first() -> None:
    review = vm.review_actions([entry("edit")], previews_left=1, previews_quota=20)
    assert not review.try_first and review.all_label == "Crear la parte"
    assert review.all_reason == ""


def test_the_form_problem_holds_both() -> None:
    review = vm.review_actions(parts("edit", "edit"), problem="Falta algo.")
    assert review.all_reason == review.first_reason == "Falta algo."
    assert not review.back_to_parts


def test_no_parts_left() -> None:
    review = vm.review_actions([])
    assert review.all_reason == vm.NO_PARTS_TEXT and review.back_to_parts
    assert review.summary == "" and not review.try_first


@pytest.mark.parametrize(
    ("count", "foot"),
    [(1, "Falta contar qué pasa en una parte."), (2, "Falta contar qué pasa en algunas partes.")],
)
def test_parts_only_missing_a_description_are_not_said_unseen(count: int, foot: str) -> None:
    """Unseen in the reel, added by hand or planned without a reel: the foot always
    asks for the description, never says «no pudimos ver»."""
    manual = entry("reference", 4, description="", notices=("describe_it",))
    manual["plan"]["analysis_id"] = None
    entries = [entry("edit"), *[dict(manual, key=f"m{at}") for at in range(count)]]
    review = vm.review_actions(entries, previews_left=10, previews_quota=20)
    assert review.foot_reason == foot
    unseen = entry("reference", 4, description="", notices=("describe_it",))
    mixed = vm.review_actions([unseen, manual], previews_left=10, previews_quota=20)
    assert mixed.foot_reason == "Falta contar qué pasa en algunas partes."
    reel = vm.review_actions([unseen, entry("edit")], previews_left=10, previews_quota=20)
    assert reel.foot_reason == "Falta contar qué pasa en una parte."

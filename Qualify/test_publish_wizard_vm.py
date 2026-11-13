"""Tests for `publish_wizard_vm` — the pure rules and words of «Publicar ahora»
(spec `docs/mockups/publicar-varias-imagenes.md`, founder decisions 2026-11-12)."""

from __future__ import annotations

import inspect
import re

import pytest

from . import publish_wizard_vm as vm
from .publish_wizard_vm import (
    CAROUSEL_MAX,
    MODE_CAROUSEL,
    MODE_ONE_BY_ONE,
    MODE_POST,
    MODE_STORIES,
    MODE_STORY,
    ONE_BY_ONE_MAX,
    STEP_ACCOUNT,
    STEP_HOW,
    STEP_ORDER,
    STEP_REVIEW,
    STEP_WHAT,
    STORIES_MAX,
)

# -- limits -----------------------------------------------------------------------------


def test_limits_are_the_specs() -> None:
    assert (CAROUSEL_MAX, ONE_BY_ONE_MAX, STORIES_MAX) == (10, 9, 10)
    assert vm.GALLERY_MAX == 10


@pytest.mark.parametrize(
    ("mode", "count", "allowed"),
    [
        (MODE_POST, 1, True),
        (MODE_STORY, 1, True),
        (MODE_CAROUSEL, 1, False),
        (MODE_POST, 2, False),
        (MODE_CAROUSEL, 10, True),
        (MODE_CAROUSEL, 11, False),
        (MODE_ONE_BY_ONE, 9, True),
        (MODE_ONE_BY_ONE, 10, False),
        (MODE_STORIES, 3, True),
        (MODE_STORIES, 10, True),
        (MODE_STORIES, 11, False),
        (MODE_POST, 0, False),
    ],
)
def test_mode_allowed(mode: str, count: int, allowed: bool) -> None:
    assert vm.mode_allowed(mode, count) is allowed


def test_one_by_one_says_why_it_is_off_above_nine() -> None:
    assert vm.one_by_one_blocked_text(9) == ""
    assert vm.one_by_one_blocked_text(10) == (
        "Una por una llega hasta 9. Quita 1 en el paso anterior."
    )


def test_effective_mode_and_the_count_crossings() -> None:
    assert vm.effective_mode(MODE_STORY, MODE_CAROUSEL, 1) == MODE_STORY
    assert vm.effective_mode(MODE_STORY, MODE_ONE_BY_ONE, 3) == MODE_ONE_BY_ONE
    # «Una por una» chosen, then a 10th file: falls back to the carousel
    assert vm.effective_mode(MODE_POST, MODE_ONE_BY_ONE, 10) == MODE_CAROUSEL
    assert vm.single_for(MODE_CAROUSEL) == MODE_POST
    assert vm.single_for(MODE_ONE_BY_ONE) == MODE_POST
    assert vm.single_for(MODE_STORIES) == MODE_STORY
    assert vm.many_for(MODE_STORY) == MODE_STORIES
    assert vm.many_for(MODE_POST) == MODE_CAROUSEL


# -- steps ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("files", "accounts", "expected"),
    [
        (0, 1, [STEP_WHAT, STEP_HOW, STEP_REVIEW]),
        (1, 1, [STEP_WHAT, STEP_HOW, STEP_REVIEW]),
        (6, 1, [STEP_WHAT, STEP_HOW, STEP_ORDER, STEP_REVIEW]),
        (1, 2, [STEP_WHAT, STEP_HOW, STEP_ACCOUNT, STEP_REVIEW]),
        (3, 2, [STEP_WHAT, STEP_HOW, STEP_ORDER, STEP_ACCOUNT, STEP_REVIEW]),
    ],
)
def test_steps_are_only_the_ones_that_apply(files: int, accounts: int, expected: list) -> None:
    assert vm.step_ids(files, accounts) == expected


def test_m_is_live_and_a_vanished_step_falls_back() -> None:
    one = vm.step_ids(1, 1)
    two = vm.step_ids(2, 1)
    assert vm.step_counter(STEP_WHAT, one) == "Paso 1 de 3"
    assert vm.step_counter(STEP_WHAT, two) == "Paso 1 de 4"
    assert vm.step_counter(STEP_REVIEW, two) == "Paso 4 de 4"
    # removing a file on the order step: it no longer applies → «¿Cómo sale?»
    assert vm.resolve_step(STEP_ORDER, one) == STEP_HOW
    assert vm.step_number(STEP_ACCOUNT, one) == 2


def test_titles_per_step_and_mode() -> None:
    assert vm.step_title(STEP_WHAT, file_count=0, mode=MODE_POST) == "¿Qué vas a publicar?"
    assert vm.step_title(STEP_HOW, file_count=1, mode=MODE_POST) == "¿Cómo sale?"
    assert vm.step_title(STEP_HOW, file_count=2, mode=MODE_CAROUSEL) == "¿Cómo salen?"
    assert (
        vm.step_title(STEP_ORDER, file_count=3, mode=MODE_CAROUSEL) == "Elige el orden del carrusel"
    )
    assert vm.step_title(STEP_ORDER, file_count=3, mode=MODE_ONE_BY_ONE) == "Así se verá tu perfil"
    assert vm.step_title(STEP_ORDER, file_count=3, mode=MODE_STORIES) == "¿En qué orden se ven?"
    assert vm.step_title(STEP_ACCOUNT, file_count=1, mode=MODE_POST) == "¿En qué Instagram sale?"
    assert vm.step_title(STEP_REVIEW, file_count=1, mode=MODE_POST) == "Revisa y publica"


def test_can_advance_and_reasons() -> None:
    kw = {"mode": MODE_POST, "connection_id": "c"}
    assert vm.can_advance(STEP_WHAT, file_count=0, **kw) is False
    assert vm.step_reason(STEP_WHAT, file_count=0, **kw) == "Elige al menos una foto o un video."
    assert vm.can_advance(STEP_WHAT, file_count=1, **kw) is True
    assert vm.can_advance(STEP_HOW, file_count=10, mode=MODE_ONE_BY_ONE, connection_id="c") is False
    assert vm.step_reason(STEP_HOW, file_count=10, mode=MODE_ONE_BY_ONE, connection_id="c") == (
        "Una por una llega hasta 9. Quita 1 en el paso anterior."
    )
    assert vm.can_advance(STEP_ACCOUNT, file_count=1, mode=MODE_POST, connection_id="") is False
    assert vm.step_reason(STEP_ACCOUNT, file_count=1, mode=MODE_POST, connection_id="") == (
        "Elige la cuenta donde vas a publicar."
    )
    assert vm.can_advance(STEP_REVIEW, file_count=1, **kw) is False


def test_next_and_previous_step() -> None:
    steps = vm.step_ids(3, 1)
    assert vm.next_step(STEP_HOW, steps, can_go=True) == STEP_ORDER
    assert vm.next_step(STEP_HOW, steps, can_go=False) == STEP_HOW
    assert vm.previous_step(STEP_REVIEW, steps) == STEP_ORDER
    assert vm.previous_step(STEP_WHAT, steps) == STEP_WHAT


# -- order --------------------------------------------------------------------------------


def test_moved_is_remove_then_insert() -> None:
    assert vm.moved(["a", "b", "c", "d"], 0, 2) == ["b", "c", "a", "d"]
    assert vm.moved(["a", "b", "c"], 2, 0) == ["c", "a", "b"]
    assert vm.moved(["a", "b"], 0, 99) == ["b", "a"]
    assert vm.moved(["a"], 5, 0) == ["a"]


def test_a_mural_goes_out_from_the_last_to_the_first() -> None:
    assert vm.execution_order(MODE_ONE_BY_ONE, 4) == [3, 2, 1, 0]
    assert vm.execution_order(MODE_STORIES, 3) == [0, 1, 2]
    assert vm.execution_order(MODE_CAROUSEL, 3) == [0, 1, 2]


def test_rows_hint_and_before_tiles() -> None:
    assert vm.rows_hint(6) == ""
    assert vm.rows_hint(5) == (
        "Con 3, 6 o 9 tus filas quedan completas. Con 5, la última fila lleva una "
        "publicación que ya tenías."
    )
    assert "dos publicaciones que ya tenías" in vm.rows_hint(4)
    assert [vm.before_tiles(n) for n in (3, 4, 5, 6)] == [0, 2, 1, 0]


def test_crop_warning_only_when_known_forms_differ() -> None:
    assert vm.crop_warning(["cuadrada", "cuadrada"]) == ""
    assert vm.crop_warning(["", "vertical"]) == ""
    assert vm.crop_warning(["vertical"]) == ""
    assert vm.crop_warning(["vertical", "", "horizontal"]).startswith(
        "Instagram corta todas a la forma de la primera (vertical)."
    )
    assert vm.shape_word(1080, 1080) == "cuadrada"
    assert vm.shape_word(1080, 1920) == "vertical"
    assert vm.shape_word(1920, 1080) == "horizontal"


def test_labels_and_live_messages() -> None:
    assert vm.piece_label("image", 3) == "Foto 3"
    assert vm.piece_label("video", 2) == "Video 2"
    assert vm.moved_text("Foto 3", 1, 5) == "Foto 3, ahora en la posición 1 de 5."
    assert vm.removed_text("image", 2) == "Quitamos la foto 2."
    assert vm.copied_caption_text(3) == "Listo, lo pusimos en 3 descripciones vacías."
    assert vm.caption_label(4) == "Descripción de la publicación 4 (opcional)"
    assert vm.publication_title(2, 4) == "Publicación 2 de 4"
    assert vm.GALLERY_FULL == "Llegaste a 10, el máximo por vez."
    assert vm.PINNED_ACCOUNT_GONE.startswith("La cuenta de Instagram de esta publicación")


# -- review, button, progress, outcome ----------------------------------------------------


def test_review_sentences_per_mode() -> None:
    one = ["image"]
    assert vm.review_sentence(MODE_POST, username="bianki", kinds=one) == (
        "Sale ahora en Instagram @bianki como publicación."
    )
    assert vm.review_sentence(MODE_STORY, username="@bianki", kinds=one) == (
        "Sale ahora en Instagram @bianki como historia (se ve 24 horas)."
    )
    assert vm.review_sentence(MODE_CAROUSEL, username="bianki", kinds=["image"] * 3) == (
        "Sale ahora en Instagram @bianki: una publicación con 3 fotos que se deslizan."
    )
    assert "3 fotos y videos" in vm.review_sentence(
        MODE_CAROUSEL, username="b", kinds=["image", "video", "image"]
    )
    assert vm.review_sentence(MODE_ONE_BY_ONE, username="bianki", kinds=["image"] * 6) == (
        "Salen ahora en Instagram @bianki: 6 publicaciones, una tras otra, en el orden de "
        "tu mural. Tarda unos minutos."
    )
    assert vm.review_sentence(MODE_STORIES, username="bianki", kinds=["image"] * 3) == (
        "Salen ahora en Instagram @bianki: 3 historias, en este orden (se ven 24 horas)."
    )


def test_publish_button_labels() -> None:
    assert vm.publish_label(MODE_POST, 1) == "Publicar en Instagram"
    assert vm.publish_label(MODE_CAROUSEL, 4) == "Publicar en Instagram"
    assert vm.publish_label(MODE_STORY, 1) == "Publicar historia"
    assert vm.publish_label(MODE_ONE_BY_ONE, 6) == "Publicar las 6"
    assert vm.publish_label(MODE_STORIES, 3) == "Publicar las 3 historias"


def test_progress_and_outcome_copy() -> None:
    assert vm.progress_title(0, 6) == "Publicando 1 de 6…"
    assert vm.progress_title(6, 6) == "Publicando 6 de 6…"
    assert vm.progress_percent(3, 6) == 50
    assert vm.done_message(MODE_POST, 1) == "Listo, ya está en tu Instagram."
    assert vm.done_message(MODE_CAROUSEL, 1) == "Listo, tu carrusel ya está en Instagram."
    assert vm.done_message(MODE_ONE_BY_ONE, 6) == (
        "Listo, tus 6 publicaciones ya están en Instagram. Tu mural quedó armado."
    )
    assert vm.done_message(MODE_STORIES, 3) == (
        "Listo, tus 3 historias ya están en Instagram (se ven 24 horas)."
    )
    assert vm.partial_message(4, 6) == "Salieron 4 de 6. Las otras 2 no se publicaron."
    assert vm.failed_headline(2, 6, "image", 4) == "Salieron 2 de 6. La foto 4 no salió."
    assert vm.failed_headline(2, 6, "video", 4) == "Salieron 2 de 6. El video 4 no salió."
    assert vm.continue_label(MODE_ONE_BY_ONE, "image", 4) == "Continuar desde la foto 4"
    assert vm.continue_label(MODE_STORIES, "image", 2) == "Continuar desde la historia 2"
    assert vm.failed_followup(MODE_ONE_BY_ONE, "image", 4).endswith(
        "seguimos desde la foto 4 y tu mural queda en orden."
    )
    assert vm.leftover_text(MODE_ONE_BY_ONE, 3) == "Te quedaron 3 sin publicar de tu mural."
    assert vm.leftover_text(MODE_STORIES, 2) == "Te quedaron 2 sin publicar de tus historias."
    assert vm.leave_text(4) == (
        "Las que ya salieron se quedan en tu perfil. Las 4 que faltan no se publicarán."
    )


def test_names_and_handles() -> None:
    assert vm.platform_name("instagram") == "Instagram"
    assert vm.account_handle("@bianki") == "@bianki"
    assert vm.account_handle("") == ""
    assert vm.connection_label("bianki", "instagram") == "@bianki · Instagram"


def test_story_needs_one_file_is_retired() -> None:
    """Spec §3: a historia is never blocked by the count any more."""
    assert not hasattr(vm, "STORY_NEEDS_ONE_FILE")
    assert not hasattr(vm, "story_allowed")


_BANNED = re.compile(r"\b(post|posts|stories|story|feed|reel|reels|upload|link)\b", re.I)


def test_no_english_in_the_copy() -> None:
    """Every client-facing string in this module is Spanish (qualify-copy-es)."""
    strings = [
        value
        for name, value in vars(vm).items()
        if name.isupper() and isinstance(value, str) and " " in value
    ]
    for fn_name in (
        "review_sentence",
        "done_message",
        "publish_label",
        "failed_followup",
        "leftover_text",
    ):
        source = inspect.getsource(getattr(vm, fn_name))
        strings += re.findall(r'f?"([^"]*\s[^"]*)"', source)
    offenders = [s for s in strings if _BANNED.search(s.replace("{", " ").replace("}", " "))]
    # identifiers inside f-strings (e.g. `{mode}`) are fine; no client word may be English
    offenders = [s for s in offenders if "MODE_" not in s and "mode" not in s]
    assert offenders == []

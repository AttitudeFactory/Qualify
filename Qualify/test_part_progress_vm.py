"""m-24921082 (UI-7): the words, tones and buttons of a video by parts' result screen."""

from __future__ import annotations

from uuid import UUID

import pytest
from qualify_api.creative.part_progress import (
    PartAction,
    PartProgress,
    PartProgressRow,
    PartState,
)

from .part_progress_vm import (
    ANNOUNCE,
    DECIDE_MOVING_TEXT,
    DECIDE_TEXT,
    HOLD_DECIDE_TEXT,
    HOLD_PURGED_TEXT,
    LIVE_TEXT,
    PARTS_HEADING_TEXT,
    REFUSED_ORIGINAL_TEXT,
    REFUSED_PHOTO_NO_CHANGE_TEXT,
    REFUSED_PHOTO_TEXT,
    REMOVE_CONFIRM_NO,
    REMOVE_CONFIRM_YES,
    REVIEW_WAIT_TEXT,
    STATE_TONES,
    STATE_WORDS,
    STEP_DONE,
    STEP_PENDING,
    STEP_RUNNING,
    announcement,
    as_state,
    part_progress_vm,
    part_row_vm,
    removed_notice,
)

PARENT = UUID("7a7a0000-0000-4000-8000-000000000002")
ALL = frozenset(PartAction)


def row(index: int, state: PartState, **kw: object) -> PartProgressRow:
    base: dict[str, object] = {
        "index": index,
        "total": 4,
        "draft_id": None,
        "mode": "reference",
        "seconds": 4,
        "state": state,
    }
    base.update(kw)
    return PartProgressRow(**base)  # type: ignore[arg-type]


def test_nine_states_with_their_word_and_tone() -> None:
    assert {s: STATE_WORDS[s] for s in PartState} == {
        PartState.UNMADE: "Sin crear",
        PartState.QUEUED: "En fila",
        PartState.CREATING: "Creando",
        PartState.TO_REVIEW: "Para revisar",
        PartState.READY: "Lista",
        PartState.FAILED: "No salió",
        PartState.ORIGINAL_REFUSED: "No se pudo con el original",
        PartState.REDO: "Hay que rehacerla",
        PartState.EXPIRED: "Venció",
    }
    assert {s: STATE_TONES[s] for s in PartState} == {
        PartState.UNMADE: "neutral",
        PartState.QUEUED: "neutral",
        PartState.CREATING: "info",
        PartState.TO_REVIEW: "warn",
        PartState.READY: "ok",
        PartState.FAILED: "error",
        PartState.ORIGINAL_REFUSED: "warn",
        PartState.REDO: "warn",
        PartState.EXPIRED: "warn",
    }


def test_the_panel_counts_parts_with_a_preview() -> None:
    progress = PartProgress(
        parent_id=PARENT,
        parts=(
            row(1, PartState.TO_REVIEW),
            row(2, PartState.CREATING),
            row(3, PartState.QUEUED, mode="extend", waiting_for=2),
            row(4, PartState.READY),
        ),
    )
    vm = part_progress_vm(progress)
    assert (vm.title, vm.comment, vm.value) == ("Creando tus partes", "2 de 4 creadas", 50)
    assert vm.value_text == "2 de 4 partes creadas" and not vm.complete
    assert vm.live_text == LIVE_TEXT
    assert LIVE_TEXT == (
        "No tienes que esperar aquí: cuando tu video esté, aparecerá en Por aprobar."
    )
    assert vm.notice == ""
    assert vm.rows[2].detail == "Se crea cuando esté la parte 2."
    assert vm.rows[0].label == "Parte 1 · 4 s"
    assert vm.rows[0].aria_label == "Parte 1 de 4, 4 segundos, para revisar"


def test_an_empty_plan_is_zero_not_a_division() -> None:
    vm = part_progress_vm(PartProgress(parent_id=PARENT, parts=()))
    assert vm.value == 0 and vm.comment == "0 de 0 creadas" and not vm.complete


def _labels(r: PartProgressRow, available: frozenset[PartAction] = ALL) -> list[str]:
    return [b.label for b in part_row_vm(r, available=available).buttons]


def test_failed_buttons_and_line() -> None:
    failed = row(
        4,
        PartState.FAILED,
        actions=(PartAction.RETRY, PartAction.CHANGE, PartAction.REMOVE),
        failure_reason="timeout",
        failure_detail="Un texto genérico de otra pieza.",
    )
    assert _labels(failed) == ["Intentar de nuevo", "Cambiar", "Quitar parte"]
    vm = part_row_vm(failed)
    assert vm.detail == "No pudimos crear esta parte. No se descontó de tus vistas previas."
    assert [b.aria_label for b in part_row_vm(failed, available=ALL).buttons] == [
        "Intentar de nuevo la parte 4",
        "Cambiar la parte 4",
        "Quitar la parte 4",
    ]
    assert (vm.word, vm.tone) == ("No salió", "error")


def test_original_refused_buttons_and_the_ux_text() -> None:
    refused = row(
        2,
        PartState.ORIGINAL_REFUSED,
        mode="edit",
        actions=(PartAction.MAKE_NEW, PartAction.REMOVE),
        failure_reason="refused_face",
        failure_detail="…Usa otra foto.",
    )
    assert _labels(refused) == ["Hacerla nueva", "Quitar parte"]
    assert part_row_vm(refused).detail.startswith(
        "No pudimos usar el original en esta parte porque parece haber una persona."
    )


def test_a_window_refusal_has_its_own_text() -> None:
    refused = row(
        2,
        PartState.ORIGINAL_REFUSED,
        mode="edit",
        actions=(PartAction.MAKE_NEW, PartAction.REMOVE),
        failure_reason="source_purged",
        failure_detail="El video original de esta parte ya no está guardado.",
    )
    assert part_row_vm(refused).detail == (
        "El video original de esta parte ya no está guardado. Podemos hacerla nueva, "
        "inspirada en el original. No se descontó de tus vistas previas."
    )


def test_redo_and_expired_buttons() -> None:
    redo = row(3, PartState.REDO, actions=(PartAction.RECREATE,), changed_part=2)
    assert _labels(redo) == ["Crearla otra vez"]
    assert part_row_vm(redo).detail == (
        "La parte 2 cambió y esta empieza donde terminaba. Créala otra vez para que siga bien."
    )
    expired = row(3, PartState.EXPIRED, actions=(PartAction.RECREATE,))
    assert _labels(expired) == ["Crearla otra vez"]
    assert part_row_vm(expired).buttons[0].aria_label == "Crear otra vez la parte 3"
    assert part_row_vm(expired).detail == (
        "La vista previa de la parte 3 venció. Créala otra vez para tener el video final."
    )


def test_a_purged_video_says_it_once_on_top() -> None:
    progress = PartProgress(
        parent_id=PARENT,
        parts=(row(1, PartState.EXPIRED, purged=True), row(2, PartState.UNMADE)),
        purged=True,
    )
    vm = part_progress_vm(progress)
    assert vm.notice == (
        "Los archivos de este video ya se borraron. Crea un video nuevo para empezar otra vez."
    )
    assert vm.title == "Tu video por partes"
    assert all(r.detail == "" and r.buttons == () for r in vm.rows)


def test_remove_is_a_button_now_it_has_a_service() -> None:
    """m-24985192: «Quitar parte» has its service (`PartRecovery.remove_part`)."""
    failed = row(
        4, PartState.FAILED, actions=(PartAction.RETRY, PartAction.CHANGE, PartAction.REMOVE)
    )
    buttons = part_row_vm(failed).buttons
    assert [b.label for b in buttons] == ["Intentar de nuevo", "Cambiar", "Quitar parte"]
    assert buttons[2].action == "remove" and buttons[2].aria_label == "Quitar la parte 4"


def test_no_dead_button_without_a_service() -> None:
    failed = row(4, PartState.FAILED, actions=(PartAction.RETRY, PartAction.REMOVE))
    labels = [b.label for b in part_row_vm(failed, available=frozenset({PartAction.RETRY})).buttons]
    assert labels == ["Intentar de nuevo"]


def test_rows_after_a_removed_part_are_numbered_without_a_gap() -> None:
    """m-24985192: the plan's part 3 shows as «Parte 2 de 3» once part 2 was removed;
    the button still names the number on screen."""
    third = row(
        3, PartState.FAILED, total=3, number=2, actions=(PartAction.RETRY, PartAction.REMOVE)
    )
    vm = part_row_vm(third)
    assert vm.index == 3 and vm.label == "Parte 2 · 4 s"
    assert vm.aria_label.startswith("Parte 2 de 3,")
    assert [b.aria_label for b in vm.buttons] == [
        "Intentar de nuevo la parte 2",
        "Quitar la parte 2",
    ]


@pytest.mark.parametrize("state", list(PartState))
def test_no_english_and_no_banned_words_on_screen(state: PartState) -> None:
    vm = part_row_vm(row(2, state, actions=tuple(PartAction), changed_part=1, waiting_for=1))
    words = " ".join([vm.word, vm.detail, vm.label, vm.aria_label, *(b.label for b in vm.buttons)])
    for banned in ("plano", "clip", "render", "prompt", "edit", "extend", "preview", "draft"):
        assert banned not in words.lower()


def test_as_state_is_plain_values() -> None:
    progress = PartProgress(
        parent_id=PARENT,
        parts=(row(1, PartState.FAILED, actions=(PartAction.RETRY,)),),
    )
    data = as_state(part_progress_vm(progress))
    assert data["rows"][0]["buttons"] == [
        {
            "action": "retry",
            "label": "Intentar de nuevo",
            "aria_label": "Intentar de nuevo la parte 1",
            "primary": True,
        }
    ]
    assert data["rows"][0]["tone"] == "error" and data["value"] == 0


def test_the_notice_after_removing_uses_the_number_it_had() -> None:
    assert removed_notice(2, 3) == "Quitaste la parte 2. Tu video sigue con 3 partes."
    assert removed_notice(1, 1) == "Quitaste la parte 1. Tu video sigue con 1 parte."


def test_removing_asks_first_only_before_a_part_that_continues_it() -> None:
    failed = row(2, PartState.FAILED, actions=(PartAction.RETRY, PartAction.REMOVE))
    extend = row(3, PartState.TO_REVIEW, mode="extend")
    new = row(3, PartState.TO_REVIEW)
    progress = PartProgress(parent_id=PARENT, parts=(row(1, PartState.READY), failed, extend))
    vm = part_progress_vm(progress)
    assert vm.rows[1].remove_confirm == (
        "Si quitas la parte 2, la parte 3 ya no seguirá a la anterior: se hará nueva, "
        "inspirada en el original."
    )
    assert as_state(vm)["rows"][1]["remove_confirm"] == vm.rows[1].remove_confirm
    assert (REMOVE_CONFIRM_YES, REMOVE_CONFIRM_NO) == ("Quitar parte", "Dejarla")
    plain = part_progress_vm(PartProgress(parent_id=PARENT, parts=(failed, new)))
    assert plain.rows[0].remove_confirm == ""
    assert part_row_vm(failed).remove_confirm == ""  # the last row: nothing after it


def test_refused_photos_say_change_or_remove_it() -> None:
    """m-24985192: «quítala» is back — removing a part has its service."""
    refused = row(2, PartState.FAILED, actions=(PartAction.CHANGE,), failure_reason="refused_face")
    detail = part_row_vm(refused).detail
    assert detail.endswith("Cambia las fotos de esta parte o quítala.")


@pytest.mark.parametrize("state", list(PartState))
def test_no_line_says_we_gave_it_back(state: PartState) -> None:
    for reason in (None, "refused_face", "source_purged", "timeout"):
        vm = part_row_vm(row(2, state, failure_reason=reason, changed_part=1))
        assert "Te devolvimos" not in vm.detail
        if "quítala" in vm.detail:
            # only where «Quitar parte» is offered (a part that did not come out)
            assert state is PartState.FAILED


# -- UX review of UI-7: the title, the sentence and the live announcement by situation ---


def test_while_a_part_moves_the_panel_is_creating() -> None:
    for moving in (PartState.UNMADE, PartState.QUEUED, PartState.CREATING):
        vm = part_progress_vm(
            PartProgress(parent_id=PARENT, parts=(row(1, PartState.READY), row(2, moving)))
        )
        assert vm.title == "Creando tus partes" and vm.in_progress
        assert vm.step_status == STEP_RUNNING and vm.live_text == LIVE_TEXT


def test_parts_waiting_for_the_owner_ask_for_a_decision() -> None:
    one = part_progress_vm(
        PartProgress(parent_id=PARENT, parts=(row(1, PartState.READY), row(2, PartState.FAILED)))
    )
    assert one.title == "Falta que decidas qué hacer con una parte"
    assert one.live_text == "Cuando decidas, seguimos con tu video."
    assert one.step_status == STEP_PENDING and not one.in_progress
    many = part_progress_vm(
        PartProgress(
            parent_id=PARENT,
            parts=(
                row(1, PartState.REDO, mode="extend", changed_part=2),
                row(2, PartState.EXPIRED),
                row(3, PartState.ORIGINAL_REFUSED, mode="edit"),
            ),
        )
    )
    assert many.title == "Falta que decidas qué hacer con 3 partes"


def test_every_part_made_says_so() -> None:
    vm = part_progress_vm(
        PartProgress(parent_id=PARENT, parts=(row(1, PartState.READY), row(2, PartState.TO_REVIEW)))
    )
    assert vm.title == "Tus partes ya están creadas" and vm.complete
    assert vm.step_status == STEP_DONE
    assert as_state(vm)["step_status"] == STEP_DONE and as_state(vm)["in_progress"] is False


def test_the_announcement_is_the_last_change_never_the_first_read() -> None:
    before = PartProgress(
        parent_id=PARENT, parts=(row(1, PartState.CREATING), row(2, PartState.CREATING))
    )
    after = PartProgress(
        parent_id=PARENT, parts=(row(1, PartState.TO_REVIEW), row(2, PartState.FAILED))
    )
    states = {1: "creating", 2: "creating"}
    assert announcement({}, part_progress_vm(after), was_complete=False) == ""
    assert announcement(states, part_progress_vm(after), was_complete=False) == (
        "La parte 2 no salió."
    )
    assert announcement(states, part_progress_vm(before), was_complete=False) == ""
    done = PartProgress(parent_id=PARENT, parts=(row(1, PartState.READY), row(2, PartState.READY)))
    assert announcement(states, part_progress_vm(done), was_complete=False) == (
        "Las 2 partes están creadas."
    )
    assert announcement(
        {1: "ready", 2: "to_review"}, part_progress_vm(done), was_complete=True
    ) == ("La parte 2 está lista.")


@pytest.mark.parametrize("state", list(PartState))
def test_every_state_has_an_announcement(state: PartState) -> None:
    text = ANNOUNCE[state].format(n=2)
    assert "parte 2" in text and text.endswith(".")


def test_a_part_to_redo_is_a_decision_not_a_finished_video() -> None:
    # the backend counts `redo` as having a vista previa: `complete`, yet it waits
    vm = part_progress_vm(
        PartProgress(
            parent_id=PARENT,
            parts=(row(1, PartState.TO_REVIEW), row(2, PartState.REDO, changed_part=1)),
        )
    )
    assert vm.complete  # the backend's meaning, followed by UI-9's refresh
    assert vm.title == "Falta que decidas qué hacer con una parte"
    assert (
        vm.step_status == STEP_PENDING and vm.live_text == "Cuando decidas, seguimos con tu video."
    )
    states = {1: "creating", 2: "creating"}
    assert announcement(states, vm, was_complete=False) == "Hay que rehacer la parte 2."


def test_an_expired_part_next_to_a_ready_one_waits_for_the_owner() -> None:
    vm = part_progress_vm(
        PartProgress(parent_id=PARENT, parts=(row(1, PartState.READY), row(2, PartState.EXPIRED)))
    )
    assert not vm.complete
    assert vm.title == "Falta que decidas qué hacer con una parte"
    assert vm.step_status == STEP_PENDING
    assert announcement({1: "ready", 2: "to_review"}, vm, was_complete=False) == (
        "La vista previa de la parte 2 venció."
    )


# -- Deivid's review of UI-7 in the browser (2026-11-09) --------------------------------


def test_decisions_come_first_even_while_parts_move() -> None:
    for moving in (PartState.QUEUED, PartState.CREATING):
        vm = part_progress_vm(
            PartProgress(parent_id=PARENT, parts=(row(1, PartState.FAILED), row(2, moving)))
        )
        assert vm.title == "Falta que decidas qué hacer con una parte"
        assert vm.live_text == "Mientras decides, seguimos con las demás partes."
        # something still moves: the step keeps counting, the screen keeps reading
        assert vm.step_status == STEP_RUNNING and vm.in_progress
        assert not vm.ready_for_video


def test_parent_a_three_decisions_and_one_in_line() -> None:
    vm = part_progress_vm(
        PartProgress(
            parent_id=PARENT,
            parts=(
                row(1, PartState.TO_REVIEW, total=6),
                row(2, PartState.FAILED, total=6),
                row(3, PartState.FAILED, total=6),
                row(4, PartState.ORIGINAL_REFUSED, mode="edit", total=6),
                row(5, PartState.QUEUED, total=6),
                row(6, PartState.UNMADE, total=6),
            ),
        )
    )
    assert vm.title == "Falta que decidas qué hacer con 3 partes"
    assert vm.comment == "1 de 6 creadas" and vm.step_status == STEP_RUNNING


def test_a_person_in_the_photos_never_asks_for_a_hidden_button() -> None:
    refused = row(5, PartState.FAILED, failure_reason="refused_face")
    hidden = frozenset({PartAction.RETRY, PartAction.MAKE_NEW, PartAction.RECREATE})
    assert part_row_vm(refused, available=hidden).detail == REFUSED_PHOTO_NO_CHANGE_TEXT
    assert "Pronto podrás cambiar sus fotos aquí." in REFUSED_PHOTO_NO_CHANGE_TEXT
    assert part_row_vm(refused, available=ALL).detail == REFUSED_PHOTO_TEXT


@pytest.mark.parametrize(
    ("states", "ready"),
    [
        ((PartState.TO_REVIEW, PartState.READY), True),
        ((PartState.TO_REVIEW, PartState.REDO), False),  # `complete`, yet a decision
        ((PartState.READY, PartState.EXPIRED), False),
        ((PartState.READY, PartState.CREATING), False),
    ],
)
def test_ready_for_video_needs_every_part_and_no_decision(
    states: tuple[PartState, PartState], ready: bool
) -> None:
    vm = part_progress_vm(
        PartProgress(
            parent_id=PARENT,
            parts=tuple(row(i, st, changed_part=1) for i, st in enumerate(states, start=1)),
        )
    )
    assert vm.ready_for_video is ready
    assert as_state(vm)["ready_for_video"] is ready


def test_the_result_words_for_a_video_by_parts() -> None:
    from .creative_vm import _UNLISTED_KIND_LABELS
    from .part_progress_vm import PARTS_KIND_LABEL, REVIEW_WAIT_TEXT

    assert PARTS_KIND_LABEL == _UNLISTED_KIND_LABELS["shot_video"]
    assert REVIEW_WAIT_TEXT == "Podrás revisarlo cuando todas sus partes estén creadas."


# -- round 4 (review-agent + ux-designer) -----------------------------------------------


@pytest.mark.parametrize(
    ("parts", "purged", "reason"),
    [
        ((PartState.READY, PartState.CREATING), False, REVIEW_WAIT_TEXT),
        ((PartState.READY, PartState.FAILED), False, HOLD_DECIDE_TEXT),
        ((PartState.FAILED, PartState.CREATING), False, HOLD_DECIDE_TEXT),
        ((PartState.EXPIRED, PartState.EXPIRED), True, HOLD_PURGED_TEXT),
    ],
)
def test_the_hold_reason_says_what_the_video_waits_for(
    parts: tuple[PartState, PartState], purged: bool, reason: str
) -> None:
    vm = part_progress_vm(
        PartProgress(
            parent_id=PARENT,
            parts=tuple(row(i, st, purged=purged) for i, st in enumerate(parts, start=1)),
            purged=purged,
        )
    )
    assert vm.hold_reason == reason and as_state(vm)["hold_reason"] == reason


def test_the_decision_sentence_depends_on_whether_parts_still_move() -> None:
    moving = part_progress_vm(
        PartProgress(parent_id=PARENT, parts=(row(1, PartState.FAILED), row(2, PartState.QUEUED)))
    )
    still = part_progress_vm(
        PartProgress(parent_id=PARENT, parts=(row(1, PartState.FAILED), row(2, PartState.READY)))
    )
    assert moving.live_text == DECIDE_MOVING_TEXT
    assert still.live_text == DECIDE_TEXT


def test_no_text_says_aparece_una_persona() -> None:
    for text in (REFUSED_PHOTO_TEXT, REFUSED_PHOTO_NO_CHANGE_TEXT, REFUSED_ORIGINAL_TEXT):
        assert "parece haber una persona" in text and "aparece una persona" not in text
    assert PARTS_HEADING_TEXT == "Así va tu video: mira cómo van sus partes."

"""UI-2 (m-24921076): every row of the analysis wait's mapping — backend handoff §3, with
the brief's decisions (no «Intentar de nuevo», unknown codes fail closed)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from qualify_api.referentes.reel_analysis_types import AnalysisStatus

from . import reel_wait_vm as vm


def status(
    state: str,
    *,
    stage: str | None = None,
    error_code: str | None = None,
    retryable: bool = False,
    queued_for_s: float = 10.0,
    queue_ahead: int = 0,
    fleet_paused: bool = False,
) -> AnalysisStatus:
    return AnalysisStatus(
        analysis_id=uuid4(),
        status=state,
        stage=stage,
        error_code=error_code,
        retryable=retryable,
        queued_for_s=queued_for_s,
        queue_ahead=queue_ahead,
        shots_found=0,
        covered_to_s=None,
        source_seconds=None,
        source_available=True,
        fleet_paused=fleet_paused,
    )


def running_title(wait: vm.ReelWait) -> str:
    """The one comment over the bar (`progress_step_row` shows only the running one)."""
    shown = [s["title"] for s in wait.steps if s["status"] == "running"]
    assert len(shown) == 1
    return shown[0]


def test_queued_says_we_are_looking_and_blocks_next_with_a_creeping_bar() -> None:
    wait = vm.from_status(status("queued"))
    assert wait.phase == vm.PHASE_WAITING and not wait.terminal
    assert wait.stage == running_title(wait) == "Estamos mirando este reel…"
    assert wait.value == -1  # no stage informs it: the bar creeps
    assert wait.blocks_next and wait.reason == "Disponible cuando terminemos de mirar el reel."
    assert wait.queue_note == "" and not wait.slow and not wait.without


def test_queued_behind_others_says_so() -> None:
    wait = vm.from_status(status("queued", queue_ahead=2))
    assert wait.queue_note == "Hay otros reels antes que este."


def test_a_retrying_row_keeps_waiting_and_says_we_keep_looking() -> None:
    wait = vm.from_status(status("queued", error_code="model_failed", retryable=True))
    assert wait.phase == vm.PHASE_WAITING and wait.blocks_next
    assert running_title(wait) == "Seguimos mirando este reel"
    assert wait.error_title == ""


@pytest.mark.parametrize(
    ("stage", "label"),
    [
        ("downloading", "Bajando el video"),
        ("detecting", "Mirando qué pasa"),
        ("describing", "Revisando si aparece alguien"),
    ],
)
def test_each_running_stage_is_the_comment_over_a_real_bar(stage: str, label: str) -> None:
    wait = vm.from_status(status("running", stage=stage))
    assert wait.phase == vm.PHASE_WAITING and wait.blocks_next
    assert wait.stage == running_title(wait) == label
    assert 0 < wait.value < 100


def test_the_bar_only_moves_forward_through_the_stages() -> None:
    values = [
        vm.from_status(status("running", stage=s)).value
        for s in ("downloading", "detecting", "describing")
    ]
    assert values == sorted(values) and values[-1] < vm.planning().value < 100


def test_running_without_a_known_stage_still_waits() -> None:
    wait = vm.from_status(status("running", stage=None))
    assert wait.phase == vm.PHASE_WAITING and wait.value == -1 and wait.blocks_next


def test_stage_order_is_the_documented_one() -> None:
    titles = [s["title"] for s in vm.ready(4).steps]
    assert titles == [
        "Estamos mirando este reel…",
        "Bajando el video",
        "Mirando qué pasa",
        "Revisando si aparece alguien",
        "Armando tu propuesta",
        "Encontramos 4 partes",
    ]


def test_ok_is_planning_then_ready_with_the_plans_count() -> None:
    planning = vm.from_status(status("ok"))
    assert planning.phase == vm.PHASE_PLANNING and not planning.terminal
    assert running_title(planning) == "Armando tu propuesta" and planning.blocks_next
    ready = vm.ready(4)
    assert ready.phase == vm.PHASE_READY and ready.terminal
    assert ready.stage == running_title(ready) == "Encontramos 4 partes"
    assert ready.parts == 4 and not ready.single_part
    assert not ready.blocks_next and ready.reason == "" and ready.value == 100


def test_one_part_says_the_reel_does_not_change_scene_and_goes_on() -> None:
    wait = vm.ready(1)
    assert wait.single_part and wait.parts == 1 and not wait.blocks_next
    assert wait.stage == "Encontramos 1 parte"
    assert vm.SINGLE_PART_TITLE == "Este reel no cambia de escena."
    assert vm.SINGLE_PART_BODY == "Lo hacemos como una sola parte."


def test_an_ok_without_parts_fails_closed() -> None:
    assert vm.ready(0) == vm.failed_error()


@pytest.mark.parametrize("queued_for_s", [301.0, 900.0])
def test_a_long_wait_offers_to_go_without_the_reel_while_still_waiting(
    queued_for_s: float,
) -> None:
    wait = vm.from_status(status("queued", queued_for_s=queued_for_s))
    assert wait.phase == vm.PHASE_WAITING and wait.blocks_next and not wait.terminal
    assert wait.slow and wait.without and not wait.pick_other
    assert vm.SLOW_TEXT == (
        "Esto está tardando más de lo normal. Puedes armar tu video por partes sin el reel."
    )


def test_a_short_wait_is_not_slow() -> None:
    wait = vm.from_status(status("running", stage="detecting", queued_for_s=300.0))
    assert not wait.slow and wait.notice == "" and not wait.without


def test_a_long_wait_says_it_is_taking_longer() -> None:
    assert vm.from_status(status("queued", queued_for_s=301.0)).notice == vm.SLOW_TEXT


@pytest.mark.parametrize("queued_for_s", [10.0, 900.0])  # paused wins over a long wait
def test_a_paused_fleet_has_its_own_message_and_keeps_waiting(queued_for_s: float) -> None:
    wait = vm.from_status(status("queued", fleet_paused=True, queued_for_s=queued_for_s))
    assert (
        wait.notice
        == vm.PAUSED_TEXT
        == (
            "Hoy ya miramos muchos reels. Terminamos de mirar este mañana; mientras, puedes "
            "armar tu video por partes sin él."
        )
    )
    assert wait.phase == vm.PHASE_WAITING and not wait.terminal and wait.without
    assert wait.blocks_next and wait.reason == "Disponible cuando terminemos de mirar el reel."


@pytest.mark.parametrize(
    "wait",
    [
        vm.from_status(status("failed", error_code="source_unavailable")),
        vm.from_status(status("failed", error_code="source_expired")),
        vm.from_request("no_video"),
    ],
)
def test_a_video_we_could_not_download_offers_another_reel_or_going_without(
    wait: vm.ReelWait,
) -> None:
    assert wait.phase == vm.PHASE_ERROR and wait.terminal
    assert wait.error_title == "No pudimos bajar el video de este reel."
    assert wait.error_body == (
        "A veces la red lo retira. Elige otro o arma tu video por partes sin él."
    )
    assert wait.pick_other and wait.without


@pytest.mark.parametrize(
    "wait",
    [
        vm.from_status(status("failed", error_code="source_too_large")),
        vm.from_status(status("failed", error_code="source_unreadable")),
        vm.from_status(status("failed", error_code="model_failed")),
        vm.from_status(status("failed", error_code="model_output_cut")),  # m-24993025
        vm.from_status(status("failed", error_code="something_new")),  # unknown: fail closed
        vm.from_status(status("failed")),
        vm.from_status(status("weird")),
        vm.from_status(None),  # the row could not be read
        vm.from_request(vm.OUTCOME_UNASKED),  # `request_similar` answered None
        vm.from_request("weird"),
    ],
)
def test_a_reel_we_could_not_look_at_offers_another_reel_or_going_without(
    wait: vm.ReelWait,
) -> None:
    assert wait.phase == vm.PHASE_ERROR and wait.terminal
    assert wait.error_title == "No pudimos mirar este reel."
    assert wait.error_body == "Arma tu video por partes sin él."
    assert wait.without and wait.pick_other


def test_the_daily_limit_names_the_business_and_offers_going_without() -> None:
    wait = vm.from_request("daily_limit")
    assert wait.phase == vm.PHASE_ERROR and wait.without and not wait.pick_other
    assert wait.error_title == "Por hoy no podemos mirar más reels para tu negocio."
    assert wait.error_body == (
        "Mañana puedes mirar otro; mientras, arma tu video por partes sin reel."
    )


def test_every_error_has_a_way_forward() -> None:
    for wait in (vm.source_error(), vm.failed_error(), vm.daily_error()):
        assert wait.without  # «Armar sin el reel» is always there
        assert wait.blocks_next and wait.reason == "Para seguir, toca «Armar sin el reel»."


@pytest.mark.parametrize(
    ("outcome", "phase"),
    [
        ("", vm.PHASE_IDLE),
        ("queued", vm.PHASE_WAITING),
        ("running", vm.PHASE_WAITING),
        ("failed", vm.PHASE_WAITING),  # the first poll reads its code at once
        ("ok", vm.PHASE_PLANNING),
    ],
)
def test_the_request_outcome_before_the_first_poll(outcome: str, phase: str) -> None:
    assert vm.from_request(outcome).phase == phase


def test_no_analysis_is_idle_and_blocks_nothing() -> None:
    assert vm.from_request("") == vm.IDLE
    assert not vm.IDLE.blocks_next and vm.IDLE.terminal and vm.IDLE.steps == []


def test_the_wait_says_it_does_not_use_the_months_videos_and_shows_no_money() -> None:
    assert vm.WAIT_TITLE == "Mirando el reel"
    assert "Puedes salir: guardamos lo que encontremos." in vm.WAIT_DETAIL
    assert "No usa tus videos del mes" in vm.WAIT_DETAIL
    texts = [
        vm.WAIT_DETAIL,
        vm.SLOW_TEXT,
        *(w.error_title + w.error_body for w in (vm.source_error(), vm.failed_error())),
        vm.daily_error().error_body,
    ]
    assert not any(sign in text for text in texts for sign in ("$", "USD", "COP", "precio"))

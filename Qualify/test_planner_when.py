"""m-24842985 (PUBLICAR-3, UX epic m-24842956): Tu semana schedules with only the day and
the hour, or «Ahora».

- «Paso 2 de 3 · ¿Cuándo sale?» shows only Día and Hora (or «Ahora»); the rest sits
  behind «Más opciones», which opens on its own when what is missing is in there (N6).
- «Confirmar» says it in one sentence: «Sale el jueves 29 a las 7:00 p. m. en Instagram
  @cuenta» (N13).
- «Ahora» gets its instant only when «Programar» is tapped: the next minutes, so the
  calendar worker takes it on its next pass — and never before the tap.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from . import planner_drawer
from .planner_state import MODE_RESCHEDULE, PlannerState, rows_for_submit
from .planner_vm import (
    ASSIGN_STEPS,
    NOW_HINT,
    NOW_LABEL,
    PLAN_ACCOUNT_REQUIRED,
    PLAN_DATE_PAST,
    ConnectionChoiceVM,
    PlanItem,
    accounts_line,
    build_plan_row,
    build_post_option,
    now_slot,
    sale_line,
    scheduled_message,
)

_IG = ConnectionChoiceVM(id="c1", label="@bianki", platform="instagram")
_FB = ConnectionChoiceVM(id="c2", label="Bianki Shawarma", platform="facebook")
_CARACAS = "America/Caracas"


def _post(post_id: str = "p1"):
    return build_post_option(
        post_id=post_id,
        title="Promo",
        caption_excerpt="",
        thumbnail_url="https://cdn.example/p.jpg",
        category="galeria",
        approval="approved",
        detail_href="/drafts/" + post_id,
        is_publishable=True,
        unpublishable_reason="",
        media_types=("IMAGE",),
        image_size=(1080, 1350),
    )


def _state(*post_ids: str) -> PlannerState:
    state = PlannerState()
    state.connections = [_IG]
    state.monday_iso = "2026-10-19"
    state.today_iso = "2026-10-23"
    state.now_hhmm = "15:10"
    state.tz_name = _CARACAS
    state.schedulable = [_post(p) for p in (post_ids or ("p1",))]
    return state


# -- the sentences ---------------------------------------------------------------------


def test_the_confirmation_is_one_sentence_with_day_hour_and_account() -> None:
    assert (
        sale_line("2026-10-29", "19:00", [_IG], today_iso="2026-10-23")
        == "Sale el jueves 29 a las 7:00 p. m. en Instagram @bianki"
    )
    # «a la 1», and the month only when it is not this one.
    assert (
        sale_line("2026-11-03", "13:30", [_IG], today_iso="2026-10-23")
        == "Sale el martes 3 de noviembre a la 1:30 p. m. en Instagram @bianki"
    )
    assert (
        sale_line("2026-10-29", "08:00", [_IG, _FB], today_iso="2026-10-23")
        == "Sale el jueves 29 a las 8:00 a. m. en Instagram @bianki y Facebook Bianki Shawarma"
    )


def test_ahora_says_it_goes_out_in_the_next_minutes() -> None:
    assert sale_line("", "", [_IG], now=True) == "Sale en unos minutos en Instagram @bianki"
    assert "Programar" in NOW_HINT  # it still waits for the owner's tap
    assert (
        scheduled_message(created=1, day_iso="2026-10-23", at="15:12", reschedule=False, now=True)
        == "Publicación programada: sale en unos minutos"
    )


def test_where_it_goes_out_is_said_before_mas_opciones() -> None:
    assert accounts_line([_IG]) == "Sale en @bianki (Instagram)"
    assert accounts_line([_IG, _FB]) == "Sale en @bianki (Instagram) y Bianki Shawarma (Facebook)"
    assert accounts_line([]) == ""


# -- «Ahora»: the instant is the tap's ------------------------------------------------


def test_now_slot_is_always_in_the_future_and_rolls_over_midnight() -> None:
    tap = datetime(2026, 10, 23, 19, 3, 40, tzinfo=UTC)  # 15:03:40 in Caracas
    assert now_slot(_CARACAS, tap) == ("2026-10-23", "15:05")
    late = datetime(2026, 10, 24, 3, 59, 59, tzinfo=UTC)  # 23:59:59 in Caracas
    assert now_slot(_CARACAS, late) == ("2026-10-24", "00:01")
    assert now_slot("Not/AZone", tap) == now_slot(_CARACAS, tap)  # unknown → default zone
    day, at = now_slot(_CARACAS, tap)
    planned = datetime.fromisoformat(f"{day}T{at}").replace(tzinfo=ZoneInfo(_CARACAS))
    assert 60 <= (planned - tap).total_seconds() <= 120  # next worker pass, never before


def test_ahora_rows_get_their_instant_only_when_programar_is_tapped() -> None:
    state = _state("p1", "p2")
    state.open_assign_for_post("p1")
    state.toggle_plan_post("p2")
    state.set_item_date("p2", "2026-10-30")
    state.set_item_time("p2", "10:00")
    state.set_item_now("p1", True)
    # Nothing is resolved while the drawer is open: the item keeps no instant of its own.
    assert state.plan_rows[0].now and state.plan_rows[0].when_label == NOW_LABEL
    tap = datetime(2026, 10, 23, 19, 20, 5, tzinfo=UTC)
    rows = rows_for_submit(state.plan_rows, state.tz_name, tap)
    assert [(r.post_id, r.date, r.time) for r in rows] == [
        ("p1", "2026-10-23", "15:22"),
        ("p2", "2026-10-30", "10:00"),
    ]


def test_ahora_skips_the_date_checks_and_the_weekly_repetition() -> None:
    state = _state()
    state.open_assign_for_post("p1")
    state.set_item_date("p1", "2026-10-01")
    assert state.plan_rows[0].error == PLAN_DATE_PAST
    state.set_item_repeat("p1", True)
    state.set_item_now("p1", True)
    row = state.plan_rows[0]
    assert row.error == "" and not row.repeat and row.event_count == 1
    assert state.form_confirm_line == "Sale en unos minutos en Instagram @bianki"
    state.set_item_now("p1", False)
    assert state.plan_rows[0].error == PLAN_DATE_PAST


def test_publicar_ahora_link_opens_the_drawer_on_ahora() -> None:
    state = _state()
    state._open_assign(post_id="p1", now=True)
    assert state.form_open and state.form_step == 1
    assert state.plan_items[0].now is True
    assert state.form_submit_label == "Programar"  # the owner still taps it


# -- the step: only day and hour, the rest behind «Más opciones» ----------------------


def test_the_step_counts_its_real_steps() -> None:
    assert ASSIGN_STEPS[1] == "Cuándo sale"
    state = _state()
    state.open_assign_for_post("p1")
    assert state.form_step_counter == "Paso 2 de 3"
    state.form_mode = MODE_RESCHEDULE
    assert state.form_step_counter == "Paso 1 de 2"


def test_confirmation_line_is_the_pieces_sentence() -> None:
    state = _state()
    state.open_assign_for_post("p1")
    state.set_item_date("p1", "2026-10-29")
    state.set_item_time("p1", "19:00")
    assert state.form_confirm_line == "Sale el jueves 29 a las 7:00 p. m. en Instagram @bianki"


def test_mas_opciones_opens_on_its_own_only_for_what_it_holds() -> None:
    state = _state()
    state.open_assign_for_post("p1")
    assert state.plan_rows[0].needs_more is False
    state.set_item_date("p1", "2026-10-01")  # a day/hour problem is fixed in the step itself
    assert state.plan_rows[0].needs_more is False
    state.set_item_date("p1", "2026-10-29")
    state.toggle_item_connection("p1", "c1")  # no account left: that sits in «Más opciones»
    row = state.plan_rows[0]
    assert row.error == PLAN_ACCOUNT_REQUIRED and row.needs_more is True


def test_mas_opciones_remembers_who_opened_it() -> None:
    state = _state("p1", "p2")
    state.set_item_more("p1", "more")
    state.set_item_more("p2", ["more"])
    state.set_item_more("p1", "")
    assert state.more_open == ["p2"]


def test_the_card_shows_only_day_and_hour_before_mas_opciones() -> None:
    card = inspect.getsource(planner_drawer._plan_card)
    for hidden in ("Canales", "Etiquetas", "_plan_campaign", "_repeat(", "_destination_selector"):
        assert hidden not in card, hidden
    assert "_when_fields(row)" in card and "_more_options(row)" in card
    more = inspect.getsource(planner_drawer._more_options)
    for inside in (
        "Canales",
        "Etiquetas",
        "_plan_campaign",
        "_repeat(row)",
        "_destination_selector",
    ):
        assert inside in more, inside
    fields = inspect.getsource(planner_drawer._when_fields)
    assert '_label("Día")' in fields and '_label("Hora")' in fields and "NOW_LABEL" in fields
    assert planner_drawer.MORE_OPTIONS == "Más opciones"
    # the plan's goals moved behind «Más opciones» on «Confirmar»
    assert "MORE_OPTIONS_GOALS" in inspect.getsource(planner_drawer._step_confirm)


def test_a_row_without_ahora_reads_as_before() -> None:
    row = build_plan_row(
        PlanItem(post_id="p1", date="2026-10-29", time="19:00", connection_ids=["c1"]),
        post=_post(),
        connections=[_IG],
        today_iso="2026-10-23",
    )
    assert not row.now and row.when_label == "jue 29 oct · 7:00 p. m."
    assert row.accounts_line == "Sale en @bianki (Instagram)"

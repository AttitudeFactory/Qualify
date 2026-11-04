"""«Ideas para tus reels» (ADR 42 R7, m-24854854): what the screen says about the stored
ideas — every state, its words verbatim, and every date in the business's own zone.
Pure: no database, no network, a fixed clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_api.referentes.reel_runs import RunView
from qualify_api.referentes.reel_store import (
    STATUS_BUDGET_STOPPED,
    STATUS_CHECK_FAILED,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_QUEUED,
    STATUS_RUNNING,
    TRIGGER_MANUAL,
    TRIGGER_WEEKLY,
    Idea,
    PublicReel,
    RunRecord,
    StoredVerdict,
)

from . import reels_ideas_vm as vm

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
BRAND = UUID("b0000000-0000-4000-8000-000000000002")
BOGOTA = "America/Bogota"  # UTC-5, no daylight saving
#: Wednesday 4 November 2026, 10:00 in Bogotá.
NOW = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)


def _run(
    finished: datetime | None,
    *,
    status: str = STATUS_OK,
    trigger: str = TRIGGER_MANUAL,
    days: int = 30,
) -> RunRecord:
    queued = (finished or NOW) - timedelta(minutes=5)
    return RunRecord(
        id=uuid4(),
        tenant_id=TENANT,
        brand_id=BRAND,
        trigger=trigger,
        run_date=queued.date(),
        status=status,
        days=days,
        accounts_total=3,
        accounts_done=3,
        credits=0,
        cost_usd=Decimal("0"),
        brief_hash=None,
        pipeline_version="reels-run-1",
        queued_at=queued,
        started_at=queued if status != STATUS_QUEUED else None,
        finished_at=finished,
    )


def _reel(
    reel_id: str,
    *,
    handle: str = "heladosdonde",
    network: str = "instagram",
    views: int | None = 9_000,
    taken: datetime = NOW - timedelta(days=3),
    measured: datetime = NOW - timedelta(days=1),
    transcript: str | None = None,
    transcript_at: datetime | None = None,
) -> PublicReel:
    return PublicReel(
        network=network,
        reel_id=reel_id,
        handle=handle,
        taken_at=taken,
        metrics_at=measured,
        parser_version=1,
        caption="Probamos el nuevo helado de yogur con frutos rojos",
        duration_s=14.6,
        sound="Sonido original",
        views=views,
        likes=900,
        comments=40,
        video_url="https://scontent.cdninstagram.com/v.mp4",
        transcript=transcript,
        transcript_at=transcript_at,
    )


def _idea(rank: int, reel: PublicReel, *, affinity: str = "producto") -> Idea:
    verdict = StoredVerdict(
        network=reel.network,
        reel_id=reel.reel_id,
        brief_hash="b",
        input_hash=f"i{rank}",
        fits=affinity in ("producto", "categoria"),
        model_id="claude",
        prompt_version="p1",
        affinity=affinity,
        format="receta",
        hook="pregunta",
        reason="Es un helado de yogur como el tuyo.",
    )
    return Idea(rank=rank, window_days=7, reel=reel, verdict=verdict)


def _stored(
    *,
    latest: RunRecord | None = None,
    shown: RunRecord | None = None,
    ideas: list[Idea] | None = None,
    accounts: int = 4,
    has_brief: bool = True,
    timezone: str = BOGOTA,
    account_reels: tuple[PublicReel, ...] = (),
) -> vm.StoredIdeas:
    return vm.StoredIdeas(
        view=RunView(latest=latest or shown, shown=shown, ideas=ideas or []),
        accounts=accounts,
        has_brief=has_brief,
        timezone=timezone,
        account_reels=account_reels,
    )


def _with_ideas(run: RunRecord, **kwargs: object) -> vm.StoredIdeas:
    return _stored(shown=run, ideas=[_idea(1, _reel("A")), _idea(2, _reel("B"))], **kwargs)


# --------------------------------------------------------------------------------------
# the empty states
# --------------------------------------------------------------------------------------


def test_an_empty_database_without_accounts_asks_to_choose_them() -> None:
    screen = vm.ideas_screen(_stored(accounts=0), now=NOW)
    assert screen.screen == vm.SCREEN_NO_ACCOUNTS
    assert screen.title == "Aún no hay cuentas que te inspiren"
    assert screen.body == (
        "Elige 3 o más negocios como el tuyo que te gusten y aquí verás sus reels que más "
        "funcionan."
    )
    assert screen.action == "Elegir cuentas"
    assert screen.cards == [] and not screen.waiting and screen.data_iso == ""


def test_without_a_brief_it_asks_what_the_business_sells() -> None:
    screen = vm.ideas_screen(_stored(has_brief=False), now=NOW)
    assert (screen.screen, screen.title, screen.action) == (
        vm.SCREEN_NO_BRIEF,
        "Cuéntanos qué vendes",
        "Completar tu marca",
    )
    assert screen.body == "Así te mostramos solo reels de tu producto y no de otros negocios."


def test_a_failed_check_with_nothing_stored_waits_for_the_review() -> None:
    failed = _run(NOW - timedelta(hours=1), status=STATUS_CHECK_FAILED)
    screen = vm.ideas_screen(_stored(latest=failed), now=NOW)
    assert screen.screen == vm.SCREEN_CHECK_FAILED
    assert screen.title == "No pudimos revisar las ideas ahora"
    assert screen.body == (
        "Para no mostrarte reels de otros productos, esperamos a poder revisarlos. "
        "Inténtalo en unos minutos."
    )
    assert screen.action == "" and "Mientras tanto" not in screen.body


def test_a_run_that_kept_no_reel_of_the_product_says_so() -> None:
    run = _run(NOW - timedelta(days=2))
    screen = vm.ideas_screen(_stored(shown=run, ideas=[]), now=NOW)
    assert screen.screen == vm.SCREEN_NO_IDEAS
    assert screen.title == "Esta vez no encontramos reels de tu producto"
    assert screen.body == (
        "Las cuentas que te inspiran no publicaron reels de lo que vendes este mes. Suma "
        "otras cuentas para tener más ideas."
    )
    assert screen.action == "Sumar cuentas"


def test_a_run_whose_ideas_are_all_another_product_shows_none() -> None:
    run = _run(NOW - timedelta(days=2))
    stored = _stored(shown=run, ideas=[_idea(1, _reel("A"), affinity="otro")])
    assert vm.ideas_screen(stored, now=NOW).screen == vm.SCREEN_NO_IDEAS


# --------------------------------------------------------------------------------------
# decision 2(a): the first run
# --------------------------------------------------------------------------------------


def test_a_brand_that_never_had_a_run_wants_its_first_one() -> None:
    stored = _stored()
    assert vm.wants_first_run(stored)
    screen = vm.ideas_screen(stored, now=NOW)
    assert screen.screen == vm.SCREEN_PREPARING and not screen.waiting  # nothing queued yet
    assert (screen.title, screen.body) == (vm.PREPARING_TITLE, vm.PREPARING_BODY)
    # never without accounts or a brief: that run would read nothing or pay for nothing
    assert not vm.wants_first_run(_stored(accounts=0))
    assert not vm.wants_first_run(_stored(has_brief=False))


@pytest.mark.parametrize("status", [STATUS_QUEUED, STATUS_RUNNING])
def test_while_the_first_run_is_in_flight_the_screen_waits_for_it(status: str) -> None:
    stored = _stored(latest=_run(None, status=status))
    assert not vm.wants_first_run(stored)  # one is already there: never a second
    screen = vm.ideas_screen(stored, now=NOW)
    assert screen.screen == vm.SCREEN_PREPARING and screen.waiting
    assert screen.title == "Estamos preparando tus primeras ideas"
    assert screen.body == "En unos minutos aparecen aquí."


@pytest.mark.parametrize("status", [STATUS_BUDGET_STOPPED, STATUS_ERROR])
def test_a_first_run_that_stopped_says_when_it_tries_again(status: str) -> None:
    stored = _stored(latest=_run(NOW - timedelta(hours=2), status=status))
    screen = vm.ideas_screen(stored, now=NOW)
    assert screen.screen == vm.SCREEN_UNAVAILABLE and not screen.waiting
    assert screen.title == "Aún no pudimos preparar tus ideas"
    assert screen.body == "Lo intentamos de nuevo el lunes 9."  # Wednesday 4 → Monday 9


# --------------------------------------------------------------------------------------
# the header: the date of the data, in the business's zone
# --------------------------------------------------------------------------------------


def test_todays_ideas_say_at_what_time_they_were_found() -> None:
    run = _run(datetime(2026, 11, 4, 14, 5, tzinfo=UTC))  # 9:05 in Bogotá
    screen = vm.ideas_screen(_with_ideas(run), now=NOW)
    assert screen.screen == vm.SCREEN_IDEAS
    assert (screen.title, screen.body) == ("Ideas de hoy", "Buscadas hoy a las 9:05 a. m.")
    assert screen.data_iso == "2026-11-04T14:05:00+00:00"
    assert screen.notice_title == screen.notice_body == ""


def test_this_weeks_ideas_say_since_when_and_when_the_next_come() -> None:
    monday = _run(datetime(2026, 11, 2, 11, 5, tzinfo=UTC), trigger=TRIGGER_WEEKLY)
    screen = vm.ideas_screen(_with_ideas(monday), now=NOW)
    assert screen.title == "Ideas de esta semana"
    assert screen.body == "Listas desde el lunes 2. Las próximas llegan el lunes 9."
    # the weekly run of today is still «de esta semana»: it says when the next come
    today = vm.ideas_screen(_with_ideas(monday), now=datetime(2026, 11, 2, 12, tzinfo=UTC))
    assert today.title == "Ideas de esta semana"


def test_a_weekly_run_that_ran_late_names_its_own_day() -> None:
    tuesday = _run(datetime(2026, 11, 3, 13, 0, tzinfo=UTC), trigger=TRIGGER_WEEKLY)
    screen = vm.ideas_screen(_with_ideas(tuesday), now=NOW)
    assert screen.body == "Listas desde el martes 3. Las próximas llegan el lunes 9."


def test_older_ideas_say_how_old_they_are() -> None:
    last_week = _run(datetime(2026, 10, 26, 11, 5, tzinfo=UTC), trigger=TRIGGER_WEEKLY)
    screen = vm.ideas_screen(_with_ideas(last_week), now=NOW)
    assert (screen.title, screen.body) == (
        "Ideas de hace 9 días",
        "Pueden haber salido reels nuevos desde entonces.",
    )
    yesterday = _run(datetime(2026, 11, 3, 20, 0, tzinfo=UTC))
    assert vm.ideas_screen(_with_ideas(yesterday), now=NOW).title == "Ideas de ayer"


def test_the_day_is_the_businesss_not_the_servers() -> None:
    """23:30 of the 3rd in Bogotá is already the 4th in UTC: for the business it was
    yesterday."""
    late = _run(datetime(2026, 11, 4, 4, 30, tzinfo=UTC))
    assert vm.ideas_screen(_with_ideas(late), now=NOW).title == "Ideas de ayer"
    in_utc = vm.ideas_screen(_with_ideas(late, timezone="UTC"), now=NOW)
    assert (in_utc.title, in_utc.body) == ("Ideas de hoy", "Buscadas hoy a las 4:30 a. m.")
    # an unknown or empty zone falls back to UTC, never to the server's
    assert vm.business_zone("Marte/Olympus") is UTC and vm.business_zone("") is UTC


def test_the_clock_is_the_planners() -> None:
    def at(hour: int, minute: int) -> str:
        return vm.clock_12h(datetime(2026, 11, 4, hour, minute))

    assert at(0, 5) == "12:05 a. m."
    assert at(12, 0) == "12:00 p. m."
    assert at(15, 40) == "3:40 p. m."


def test_a_newer_failed_check_keeps_the_stored_ideas_with_a_notice() -> None:
    shown = _run(datetime(2026, 10, 26, 11, 5, tzinfo=UTC), trigger=TRIGGER_WEEKLY)
    failed = _run(datetime(2026, 11, 2, 11, 9, tzinfo=UTC), status=STATUS_CHECK_FAILED)
    stored = _stored(latest=failed, shown=shown, ideas=[_idea(1, _reel("A"))])
    screen = vm.ideas_screen(stored, now=NOW)
    assert screen.screen == vm.SCREEN_IDEAS and len(screen.cards) == 1
    assert screen.title == "Ideas de hace 9 días"
    assert screen.notice_title == "No pudimos revisar las ideas ahora"
    assert screen.notice_body == (
        "Para no mostrarte reels de otros productos, esperamos a poder revisarlos. "
        "Inténtalo en unos minutos. Mientras tanto, tienes las de hace 9 días."
    )
    same_day = _stored(
        latest=failed,
        shown=_run(datetime(2026, 11, 4, 12, tzinfo=UTC)),
        ideas=[_idea(1, _reel("A"))],
    )
    assert vm.ideas_screen(same_day, now=NOW).notice_body.endswith("tienes las de hoy.")


# --------------------------------------------------------------------------------------
# the cards
# --------------------------------------------------------------------------------------


def test_an_idea_becomes_the_card_the_view_renders() -> None:
    reel = _reel(
        "DecE2c8x7c_",
        views=12_000,
        taken=NOW - timedelta(days=5),
        measured=NOW - timedelta(days=1),
        transcript="Hoy probamos el helado de yogur",
        transcript_at=NOW - timedelta(days=1),
    )
    card = vm.idea_card(_idea(1, reel), now=NOW, lift=3.2)
    assert card["key"] == "instagram:DecE2c8x7c_" and card["handle"] == "@heladosdonde"
    assert card["url"] == "https://www.instagram.com/reel/DecE2c8x7c_/"
    assert card["embed"] == "https://www.instagram.com/reel/DecE2c8x7c_/embed/"
    assert card["views"] == "12K"
    assert card["per_day"] == "3K/día"  # 12 000 views over the 4 days it had when counted
    assert card["age"] == "hace 5 días"  # published, as of now
    assert (card["lift"], card["lift_tone"]) == ("x3.2 sobre su media", "ok")
    assert (card["affinity"], card["format"], card["hook"]) == ("producto", "receta", "pregunta")
    assert card["reason"] == "Es un helado de yogur como el tuyo."
    assert card["transcript"] == "Hoy probamos el helado de yogur"
    assert card["transcript_state"] == "said" and card["seconds"] == "15 s"
    assert card["cover"] == ""  # no cover is stored until R12: the card's placeholder
    tiktok = vm.idea_card(_idea(2, _reel("7681", network="tiktok", handle="polette")), now=NOW)
    assert tiktok["url"] == "https://www.tiktok.com/@polette/video/7681"


def test_the_transcript_is_the_stored_one_never_fetched() -> None:
    silent = _reel("S", transcript="", transcript_at=NOW - timedelta(days=1))
    never = _reel("N")  # never transcribed: the card says nothing about it
    assert vm.idea_card(_idea(1, silent), now=NOW)["transcript_state"] == "none"
    unknown = vm.idea_card(_idea(1, never), now=NOW)
    assert (unknown["transcript"], unknown["transcript_state"]) == ("", "")


def test_the_lift_is_measured_on_the_stored_reels_of_the_account() -> None:
    peers = tuple(_reel(f"P{n}", views=v) for n, v in enumerate((1_000, 1_000, 1_200)))
    star = _reel("A", views=4_400)
    run = _run(NOW - timedelta(hours=3))
    stored = _stored(shown=run, ideas=[_idea(1, star)], account_reels=(*peers, star))
    (card,) = vm.ideas_screen(stored, now=NOW).cards
    assert card["lift"] == "x4 sobre su media"  # 4 400 over the median of 1 000-4 400


def test_only_the_product_and_its_category_reach_the_cards() -> None:
    run = _run(NOW - timedelta(hours=3))
    ideas = [
        _idea(1, _reel("A")),
        _idea(2, _reel("B"), affinity="categoria"),
        _idea(3, _reel("C"), affinity="rubro"),
        Idea(rank=4, window_days=7, reel=_reel("D"), verdict=None),
    ]
    cards = vm.ideas_screen(_stored(shown=run, ideas=ideas), now=NOW).cards
    assert [c["key"] for c in cards] == ["instagram:A", "instagram:B"]


# --------------------------------------------------------------------------------------
# the words
# --------------------------------------------------------------------------------------

_SCREEN_COPY = (
    vm.TODAY_TITLE,
    vm.TODAY_BODY,
    vm.WEEK_TITLE,
    vm.WEEK_BODY,
    vm.OLD_TITLE,
    vm.YESTERDAY_TITLE,
    vm.OLD_BODY,
    vm.NO_ACCOUNTS_TITLE,
    vm.NO_ACCOUNTS_BODY,
    vm.NO_ACCOUNTS_ACTION,
    vm.NO_BRIEF_TITLE,
    vm.NO_BRIEF_BODY,
    vm.NO_BRIEF_ACTION,
    vm.CHECK_FAILED_TITLE,
    vm.CHECK_FAILED_BODY,
    vm.MEANWHILE,
    vm.NO_IDEAS_TITLE,
    vm.NO_IDEAS_BODY,
    vm.NO_IDEAS_ACTION,
    vm.PREPARING_TITLE,
    vm.PREPARING_BODY,
    vm.UNAVAILABLE_TITLE,
    vm.UNAVAILABLE_BODY,
    vm.LOAD_ERROR,
    vm.RETRY,
)


@pytest.mark.parametrize("text", _SCREEN_COPY)
def test_the_screen_never_names_credits_vendors_reads_or_errors(text: str) -> None:
    lowered = text.lower()
    for banned in ("crédito", "credito", "proveedor", "lectura", "scrapecreators", "error"):
        assert banned not in lowered
    for english in ("post", "feed", "insight", "brand kit", "refresh"):
        assert english not in lowered
    assert not set("()[]?¿") & set(text)

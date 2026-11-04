"""«Ideas para tus reels» (ADR 42 R7, m-24854854): what the screen says about the ideas
stored for a brand. Pure — no database, no network — so every state, every sentence and
every date is tested offline (`Qualify/test_reels_ideas_vm.py`).

Opening the screen never spends (ADR 42 §2.1, decision 1): the state reads what the
weekly run (R8) or the owner's search (R9) left in Postgres — `reel_runs.view`, gathered
by `reels_discovery.stored_ideas` — and this module turns it into the header, the cards
and the empty states. Dates and hours are the business's own (`tenants.timezone`).

The client-facing sentences are the ticket's, verbatim (UX analysis §3.4, m-24854854);
the few derived forms (`YESTERDAY_TITLE`, `_since`) say which literal they derive from,
and the ones the ticket does not have (`PREPARING_*`, `UNAVAILABLE_*`, `LOAD_ERROR`) are
marked as proposals for the ux-designer review.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

from qualify_api.referentes import reels, reels_ai
from qualify_api.referentes.reel_runs import RunView
from qualify_api.referentes.reel_store import (
    STATUS_BUDGET_STOPPED,
    STATUS_CHECK_FAILED,
    STATUS_ERROR,
    STATUS_QUEUED,
    STATUS_RUNNING,
    TRIGGER_WEEKLY,
    Idea,
    PublicReel,
    RunRecord,
)

# --------------------------------------------------------------------------------------
# what the screen can show
# --------------------------------------------------------------------------------------

#: The stored ideas of the latest `ok` run, under a header that dates them.
SCREEN_IDEAS = "ideas"
#: Nothing stored, and the brand follows no account the run can read.
SCREEN_NO_ACCOUNTS = "no_accounts"
#: Nothing stored, and nothing says what the brand sells (no brief: no run reads).
SCREEN_NO_BRIEF = "no_brief"
#: Nothing stored, and the latest run could not check its reels.
SCREEN_CHECK_FAILED = "check_failed"
#: The latest `ok` run kept no reel of the brand's product.
SCREEN_NO_IDEAS = "no_ideas"
#: Accounts and a brief, nothing stored, and the first run queued or running — every
#: brand starts here (decision 2(a), option A: opening queues it, `ensure_first_run`).
SCREEN_PREPARING = "preparing"
#: Accounts and a brief, nothing stored, and the latest run ended without ideas and
#: without a failed check (the gate stopped it, or it failed) — nothing is running.
SCREEN_UNAVAILABLE = "unavailable"

#: What a run in flight is; the «preparando» screen re-reads the view while it lasts.
IN_FLIGHT = frozenset({STATUS_QUEUED, STATUS_RUNNING})
#: How a run ends without ideas and without saying why the check failed.
STOPPED = frozenset({STATUS_BUDGET_STOPPED, STATUS_ERROR})

# --------------------------------------------------------------------------------------
# the copy (verbatim from the ticket, UX analysis §3.4)
# --------------------------------------------------------------------------------------

TODAY_TITLE = "Ideas de hoy"
TODAY_BODY = "Buscadas hoy a las {h}."
WEEK_TITLE = "Ideas de esta semana"
#: «Listas desde el lunes {d}. Las próximas llegan el lunes {d+7}.» — the weekday is the
#: day the weekly run finished: «lunes» unless it ran late.
WEEK_BODY = "Listas desde el {weekday} {d}. Las próximas llegan el lunes {next_d}."
OLD_TITLE = "Ideas de hace {n} días"
#: «Ideas de hace {N} días» for N = 1 (derived: «hace 1 días» is not Spanish).
YESTERDAY_TITLE = "Ideas de ayer"
OLD_BODY = "Pueden haber salido reels nuevos desde entonces."

NO_ACCOUNTS_TITLE = "Aún no hay cuentas que te inspiren"
NO_ACCOUNTS_BODY = (
    "Elige 3 o más negocios como el tuyo que te gusten y aquí verás sus reels que más funcionan."
)
NO_ACCOUNTS_ACTION = "Elegir cuentas"

NO_BRIEF_TITLE = "Cuéntanos qué vendes"
NO_BRIEF_BODY = "Así te mostramos solo reels de tu producto y no de otros negocios."
NO_BRIEF_ACTION = "Completar tu marca"

CHECK_FAILED_TITLE = "No pudimos revisar las ideas ahora"
CHECK_FAILED_BODY = (
    "Para no mostrarte reels de otros productos, esperamos a poder revisarlos. "
    "Inténtalo en unos minutos."
)
#: Added to `CHECK_FAILED_BODY` when older ideas are stored and still shown.
MEANWHILE = "Mientras tanto, tienes las de {since}."

NO_IDEAS_TITLE = "Esta vez no encontramos reels de tu producto"
NO_IDEAS_BODY = (
    "Las cuentas que te inspiran no publicaron reels de lo que vendes este mes. Suma otras "
    "cuentas para tener más ideas."
)
NO_IDEAS_ACTION = "Sumar cuentas"

#: PROPOSAL for the ux-designer review (decision 2(a), option A pending the founder's
#: signature): the first run is being prepared. The ONE place this copy lives: if the
#: founder picks option B (nothing is queued on open), only these two strings change, to
#: say the ideas arrive the next Monday — e.g. «Tus primeras ideas llegan el lunes {d}.».
PREPARING_TITLE = "Estamos preparando tus primeras ideas"
PREPARING_BODY = "En unos minutos aparecen aquí."

#: PROPOSAL for the ux-designer review (not in the ticket): nothing stored and the latest
#: run ended without ideas and without a failed check (the gate stopped it, or it failed).
#: The next weekly run tries again: opening the screen keeps the brand active.
UNAVAILABLE_TITLE = "Aún no pudimos preparar tus ideas"
UNAVAILABLE_BODY = "Lo intentamos de nuevo el lunes {d}."

#: PROPOSAL for the ux-designer review (not in the ticket): the screen could not read
#: what is stored (Postgres down) — plain, with the next step and its button.
LOAD_ERROR = "No pudimos abrir tus ideas ahora. Inténtalo de nuevo en unos minutos."
RETRY = "Intentar de nuevo"

_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


# --------------------------------------------------------------------------------------
# input and output
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredIdeas:
    """What the screen reads from Postgres (`reels_discovery.stored_ideas`) — never the
    vendor, never the model."""

    #: The latest run (whatever its state) and the latest `ok` one with its ideas.
    view: RunView
    #: The brand's accounts a run reads (`reels.brand_referentes`).
    accounts: int
    #: Whether something says what the brand sells (`brand_brief` is not None).
    has_brief: bool
    #: The business's IANA zone (`tenants.timezone`).
    timezone: str = "UTC"
    #: Every stored reel of the ideas' accounts in the shown run's window — what each
    #: idea's «x3 sobre su media» is measured against (`reels.account_lifts`).
    account_reels: Sequence[PublicReel] = ()


@dataclass(frozen=True)
class IdeasScreen:
    """What the view shows: one of the `SCREEN_*` and its words."""

    screen: str
    #: The header over the ideas, or the empty state's title and body.
    title: str = ""
    body: str = ""
    #: The empty state's one button ("" for none).
    action: str = ""
    #: A notice ABOVE stored ideas that are still true (a newer run failed its check).
    notice_title: str = ""
    notice_body: str = ""
    #: The ideas, best first, in the card shape the view renders (`reels.reel_card`).
    cards: list[dict[str, str]] = field(default_factory=list)
    #: When the shown run found its ideas (ISO, UTC) — "" when none is shown.
    data_iso: str = ""
    #: A run is in flight and nothing is stored yet: the screen re-reads the view (a
    #: database read, free) until it ends (`SCREEN_PREPARING`).
    waiting: bool = False


# --------------------------------------------------------------------------------------
# dates, in the business's zone
# --------------------------------------------------------------------------------------


def business_zone(name: str) -> tzinfo:
    """The business's zone; UTC when the stored name is empty or unknown."""
    try:
        return ZoneInfo(name) if name else UTC
    except (ValueError, KeyError):  # ZoneInfoNotFoundError is a KeyError
        return UTC


def clock_12h(moment: datetime) -> str:
    """«9:05 a. m.», «3:40 p. m.» — the planner's clock (`planner_vm.time_label_12h`)."""
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d} {'a. m.' if moment.hour < 12 else 'p. m.'}"


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def run_moment(run: RunRecord) -> datetime:
    """When a run found what it shows: it finished, else it started, else it was queued."""
    return run.finished_at or run.started_at or run.queued_at


def days_ago(moment: datetime, now: datetime, zone: tzinfo) -> int:
    """Calendar days between `moment` and `now` in the business's zone (0 = today)."""
    return max((now.astimezone(zone).date() - moment.astimezone(zone).date()).days, 0)


def next_monday(now: datetime, zone: tzinfo) -> date:
    """The first Monday after today, in the business's zone (the weekly run's day)."""
    today = now.astimezone(zone).date()
    return today + timedelta(days=7 - today.weekday())


def _since(days: int) -> str:
    """«hoy», «ayer», «hace 9 días» — `MEANWHILE`'s «hace {N} días», said right for 0 and 1."""
    if days == 0:
        return "hoy"
    if days == 1:
        return "ayer"
    return f"hace {days} días"


def header(run: RunRecord, now: datetime, zone: tzinfo) -> tuple[str, str]:
    """`(title, body)` over the ideas of `run`: this week's weekly run says when the next
    ones come; another run of today says at what time; anything older says how old."""
    found = run_moment(run).astimezone(zone)
    today = now.astimezone(zone).date()
    if run.trigger == TRIGGER_WEEKLY and _monday(found.date()) == _monday(today):
        following = _monday(found.date()) + timedelta(days=7)
        return WEEK_TITLE, WEEK_BODY.format(
            weekday=_WEEKDAYS[found.weekday()], d=found.day, next_d=following.day
        )
    age = days_ago(found, now, zone)
    if age == 0:
        # «a las 9:05 a. m.»: the abbreviation's period closes the sentence too (RAE)
        return TODAY_TITLE, TODAY_BODY.format(h=clock_12h(found)).replace("m..", "m.")
    return (YESTERDAY_TITLE if age == 1 else OLD_TITLE.format(n=age)), OLD_BODY


# --------------------------------------------------------------------------------------
# the cards
# --------------------------------------------------------------------------------------


def _reel_dict(reel: PublicReel) -> dict[str, object]:
    """A stored reel in the shape `reels.reel_card` reads."""
    return {
        "id": reel.reel_id,
        "network": reel.network,
        "handle": reel.handle,
        "url": reels.public_url(reel.network, reel.handle, reel.reel_id),
        "caption": reel.caption,
        "takenAt": reel.taken_at.timestamp(),
        "views": reel.views,
        "likes": reel.likes,
        "comments": reel.comments,
        "shares": reel.shares,
        "saves": reel.saves,
        "seconds": round(reel.duration_s) if reel.duration_s is not None else None,
        "sound": reel.sound,
        "video": reel.video_url or "",
        "transcript": reel.transcript or "",
    }


def idea_lifts(account_reels: Sequence[PublicReel]) -> dict[str, float]:
    """reel key → its views over its account's median (`reels.account_lifts`), measured
    on what is stored — free."""
    return reels.account_lifts(
        [
            {"id": r.reel_id, "network": r.network, "handle": r.handle, "views": r.views}
            for r in account_reels
        ]
    )


def idea_card(idea: Idea, *, now: datetime, lift: float | None = None) -> dict[str, str]:
    """One idea as the card «C» (`reels.reel_card`): its figures as of when they were
    counted (`metrics_at`), its age as of now, and its stored transcript — «Este video no
    tiene voz» when it was transcribed and says nothing; nothing when it never was (the
    screen never pays for one)."""
    reel = idea.reel
    verdict = idea.verdict
    review = (
        reels_ai.ReelReview(
            id=f"{reel.network}:{reel.reel_id}",
            fits=verdict.fits,
            reason=verdict.reason,
            format=verdict.format,
            hook=verdict.hook,
            affinity=verdict.affinity,
        )
        if verdict is not None
        else None
    )
    card = reels.reel_card(
        _reel_dict(reel), idea.rank, reel.metrics_at.timestamp(), lift=lift, review=review
    )
    card["age"] = reels.age_label(reel.taken_at.timestamp(), now.timestamp())
    if reel.transcript_at is not None and not reel.transcript:
        card["transcript_state"] = "none"
    return card


def idea_cards(stored: StoredIdeas, *, now: datetime) -> list[dict[str, str]]:
    """The shown run's ideas that the check kept for the product or its category (the
    run stores only those; checked again so another product never reaches the screen)."""
    lifts = idea_lifts(stored.account_reels)
    return [
        idea_card(idea, now=now, lift=lifts.get(f"{idea.reel.network}:{idea.reel.reel_id}"))
        for idea in stored.view.ideas
        if idea.verdict is not None and idea.verdict.fits and idea.verdict.affinity in reels_ai.FITS
    ]


# --------------------------------------------------------------------------------------
# the screen
# --------------------------------------------------------------------------------------


def wants_first_run(stored: StoredIdeas) -> bool:
    """Decision 2(a), option A: the brand could have ideas (accounts and a brief) but
    never had a run — opening the screen queues its first one (`ensure_first_run`)."""
    view = stored.view
    return view.latest is None and view.shown is None and stored.accounts > 0 and stored.has_brief


def ideas_screen(stored: StoredIdeas, *, now: datetime) -> IdeasScreen:
    """Which `SCREEN_*` and its words. Stored ideas always win — they are still true —
    with a notice above them when a newer run could not check its reels. Without ideas:
    no accounts, then no brief, then a failed check, then a run that kept none, then a
    run that stopped, then the first run being prepared."""
    zone = business_zone(stored.timezone)
    shown, latest = stored.view.shown, stored.view.latest
    failed = latest is not None and latest.status == STATUS_CHECK_FAILED
    cards = idea_cards(stored, now=now) if shown is not None else []
    if shown is not None and cards:
        title, body = header(shown, now, zone)
        notice_title = notice_body = ""
        if failed and stored.has_brief:
            since = _since(days_ago(run_moment(shown), now, zone))
            notice_title = CHECK_FAILED_TITLE
            notice_body = f"{CHECK_FAILED_BODY} {MEANWHILE.format(since=since)}"
        return IdeasScreen(
            SCREEN_IDEAS,
            title=title,
            body=body,
            notice_title=notice_title,
            notice_body=notice_body,
            cards=cards,
            data_iso=run_moment(shown).astimezone(UTC).isoformat(),
        )
    if stored.accounts == 0:
        return IdeasScreen(
            SCREEN_NO_ACCOUNTS, NO_ACCOUNTS_TITLE, NO_ACCOUNTS_BODY, NO_ACCOUNTS_ACTION
        )
    if not stored.has_brief:
        return IdeasScreen(SCREEN_NO_BRIEF, NO_BRIEF_TITLE, NO_BRIEF_BODY, NO_BRIEF_ACTION)
    if failed:
        return IdeasScreen(SCREEN_CHECK_FAILED, CHECK_FAILED_TITLE, CHECK_FAILED_BODY)
    if shown is not None:
        return IdeasScreen(
            SCREEN_NO_IDEAS,
            NO_IDEAS_TITLE,
            NO_IDEAS_BODY,
            NO_IDEAS_ACTION,
            data_iso=run_moment(shown).astimezone(UTC).isoformat(),
        )
    if latest is not None and latest.status in STOPPED:
        return IdeasScreen(
            SCREEN_UNAVAILABLE,
            UNAVAILABLE_TITLE,
            UNAVAILABLE_BODY.format(d=next_monday(now, zone).day),
        )
    return IdeasScreen(
        SCREEN_PREPARING,
        PREPARING_TITLE,
        PREPARING_BODY,
        waiting=latest is not None and latest.status in IN_FLIGHT,
    )


__all__ = [
    "CHECK_FAILED_BODY",
    "CHECK_FAILED_TITLE",
    "IN_FLIGHT",
    "LOAD_ERROR",
    "MEANWHILE",
    "NO_ACCOUNTS_ACTION",
    "NO_ACCOUNTS_BODY",
    "NO_ACCOUNTS_TITLE",
    "NO_BRIEF_ACTION",
    "NO_BRIEF_BODY",
    "NO_BRIEF_TITLE",
    "NO_IDEAS_ACTION",
    "NO_IDEAS_BODY",
    "NO_IDEAS_TITLE",
    "OLD_BODY",
    "OLD_TITLE",
    "PREPARING_BODY",
    "PREPARING_TITLE",
    "RETRY",
    "SCREEN_CHECK_FAILED",
    "SCREEN_IDEAS",
    "SCREEN_NO_ACCOUNTS",
    "SCREEN_NO_BRIEF",
    "SCREEN_NO_IDEAS",
    "SCREEN_PREPARING",
    "SCREEN_UNAVAILABLE",
    "STOPPED",
    "TODAY_BODY",
    "TODAY_TITLE",
    "UNAVAILABLE_BODY",
    "UNAVAILABLE_TITLE",
    "WEEK_BODY",
    "WEEK_TITLE",
    "YESTERDAY_TITLE",
    "IdeasScreen",
    "StoredIdeas",
    "business_zone",
    "clock_12h",
    "days_ago",
    "header",
    "idea_card",
    "idea_cards",
    "idea_lifts",
    "ideas_screen",
    "next_monday",
    "run_moment",
    "wants_first_run",
]

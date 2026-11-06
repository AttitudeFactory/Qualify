"""«Ideas para tus reels» (ADR 42 R7, m-24854854): what the screen says about the ideas
stored for a brand. Pure — no database, no network — so every state, every sentence and
every date is tested offline (`Qualify/test_reels_ideas_vm.py`).

Opening the screen never spends (ADR 42 §2.1, decision 1): the state reads what the
weekly run (R8) or the owner's search (R9) left in Postgres — `reel_runs.view`, gathered
by `reels_discovery.stored_ideas` — and this module turns it into the header, the cards
and the empty states. Dates and hours are the business's own (`tenants.timezone`).

The client-facing sentences are the ticket's (UX analysis §3.4, m-24854854), with the
changes of the UX review and the founder's decisions of 2026-11-04 (a failed check retries
by itself; a newer failed run over stored ideas says «No pudimos traer ideas nuevas»); the
derived forms (`YESTERDAY_TITLE`, `_since`) say which literal they derive from, and the
ones drafted here are marked as such for the ux-designer re-check.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

from qualify_api.referentes import reels, reels_ai
from qualify_api.referentes.reel_runs import RunView
from qualify_api.referentes.reel_schedule import WEEKLY_AT
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
#: brand starts here (option A, founder 2026-11-04: opening queues it, `ensure_first_run`).
SCREEN_PREPARING = "preparing"
#: The same, but the run has been in line longer than `PREPARING_LIMIT` — or nothing could
#: be queued: no spinner, and a button that looks again.
SCREEN_SLOW = "slow"
#: Accounts and a brief, nothing stored, and the latest run ended without ideas and
#: without a failed check (the gate stopped it, or it failed) — nothing is running.
SCREEN_UNAVAILABLE = "unavailable"

#: What a run in flight is; the «preparando» screen re-reads the view while it lasts.
IN_FLIGHT = frozenset({STATUS_QUEUED, STATUS_RUNNING})
#: How a run ends without ideas and without saying why the check failed.
STOPPED = frozenset({STATUS_BUDGET_STOPPED, STATUS_ERROR})
#: How long «Estamos preparando…» keeps its spinner, counted from when the run was queued
#: (the data, not the browser: a reload or a deploy never restarts it).
PREPARING_LIMIT = timedelta(minutes=10)

# --------------------------------------------------------------------------------------
# the copy (verbatim from the ticket, UX analysis §3.4)
# --------------------------------------------------------------------------------------

TODAY_TITLE = "Ideas de hoy"
TODAY_BODY = "Buscadas hoy a las {h}."
WEEK_TITLE = "Ideas de esta semana"
#: «Listas desde el lunes {d}. Las próximas llegan el lunes {d+7}.» — the weekday is the
#: day the weekly run finished: «lunes» unless it ran late; `NEXT_ONES` follows it.
WEEK_BODY = "Listas desde el {weekday} {d}."
OLD_TITLE = "Ideas de hace {n} días"
#: «Ideas de hace {N} días» for N = 1 (derived: «hace 1 días» is not Spanish).
YESTERDAY_TITLE = "Ideas de ayer"
OLD_BODY = "Pueden haber salido reels nuevos desde entonces."
#: After `WEEK_BODY` / `OLD_BODY` (UX review 7: opening the screen keeps the brand active,
#: so the weekly run comes) — left out when a notice above already names that Monday
#: (UX re-check 3: «el lunes 9» said twice).
NEXT_ONES = "Las próximas llegan el lunes {d}."

NO_ACCOUNTS_TITLE = "Aún no hay cuentas que te inspiren"
NO_ACCOUNTS_BODY = (
    "Elige 3 o más negocios como el tuyo que te gusten y aquí verás sus reels que más funcionan."
)
NO_ACCOUNTS_ACTION = "Elegir cuentas"

NO_BRIEF_TITLE = "Cuéntanos qué vendes"
NO_BRIEF_BODY = "Así te mostramos solo reels de tu producto y no de otros negocios."
NO_BRIEF_ACTION = "Completar tu marca"

CHECK_FAILED_TITLE = "No pudimos revisar las ideas ahora"
#: Founder, 2026-11-04: a failed check retries by itself (`RunView.next_retry_at`), so the
#: owner is told when — never asked to try (`{retry}`: `RETRY_SOON` / `RETRY_MONDAY`).
CHECK_FAILED_BODY = (
    "Para no mostrarte reels de otros productos, esperamos a poder revisarlos. {retry}"
)
#: While the worker will retry by itself, and once its retries are spent (the weekly run).
RETRY_SOON = "Lo intentamos de nuevo en unos minutos."
RETRY_MONDAY = "Lo intentamos de nuevo el lunes {d}."
#: Founder, 2026-11-04: over stored ideas — still true — a newer run that failed says
#: this, in the info tone (the owner has nothing to fix).
NEWS_FAILED_TITLE = "No pudimos traer ideas nuevas"
#: Added to the notice when older ideas are stored and still shown.
MEANWHILE = "Mientras tanto, tienes las de {since}."

NO_IDEAS_TITLE = "Esta vez no encontramos reels de tu producto"
NO_IDEAS_BODY = (
    "Las cuentas que te inspiran no publicaron reels de lo que vendes este mes. Suma otras "
    "cuentas para tener más ideas. Las próximas llegan el lunes {d}."
)
NO_IDEAS_ACTION = "Sumar cuentas"

#: The first run is being prepared (option A, founder 2026-11-04; the UX review's text):
#: the owner may leave — the ideas wait here.
PREPARING_TITLE = "Estamos preparando tus primeras ideas"
PREPARING_BODY = "Tardan unos minutos. Puedes seguir con otra cosa: quedan guardadas aquí."
#: Past `PREPARING_LIMIT` (UX review 3): no spinner, and «Ver si ya están» reads again.
SLOW_TITLE = "Están tardando más de lo normal"
SLOW_BODY = "Vuelve en un rato: quedan guardadas aquí."
SLOW_ACTION = "Ver si ya están"
#: UX re-check 1: a failure tried again only with the weekly run leaves a way to go on.
CREATE_ACTION = "Crear una publicación"

#: What an empty state's one button does (`IdeasScreen.action_to`): open «Negocios
#: parecidos al tuyo» on the brand page, read what is stored once more (free), or go back
#: to creating a publication.
ACTION_ACCOUNTS = "accounts"
ACTION_REREAD = "reread"
ACTION_CREATE = "create"

#: Nothing stored and the latest run ended without ideas and without a failed check (the
#: gate stopped it, or it failed); the body says when it is tried again (`RETRY_*`).
UNAVAILABLE_TITLE = "Aún no pudimos preparar tus ideas"

#: The screen could not read what is stored (Postgres down); its button reads again at
#: once (UX review: no «en unos minutos»).
LOAD_ERROR = "No pudimos abrir tus ideas ahora. Inténtalo de nuevo."
RETRY = "Intentar de nuevo"

#: A card whose video is not kept (its download failed, or the copy was purged after 30
#: days) shows this instead of «Hacer uno parecido» (UX re-check: it can still be
#: watched). UI-1 (m-24921075): no «replicar» in anything the owner reads.
CANNOT_REPLICATE = (
    "Este video ya no está disponible para hacer uno parecido. Puedes verlo para "
    "inspirarte o elegir otra idea."
)

# --------------------------------------------------------------------------------------
# «Hacer uno parecido» (ADR 44 UI-1, m-24921075; copy: `docs/ux-video-por-planos.md` §3a)
# --------------------------------------------------------------------------------------

#: The card's button (ADR 42 R14's name; R14 is replaced by UI-1) and its help, always
#: visible (a phone has no hover).
SIMILAR_LABEL = "Hacer uno parecido"
SIMILAR_BUSY = "Preparando…"
#: UX review: «parte por parte» returns when UI-3 shows the parts.
SIMILAR_HELP = "Lo hacemos con tu producto y tu marca. Lo revisas antes de crear nada."
#: Where «Hacer uno parecido» lands: the create flow's head says what «‹» goes back to.
IDEAS_BACK_LABEL = "Ideas para tus reels"

#: The card's analysis pill (`qualify_api.referentes.reel_analysis.analysis_badges`; the
#: words are the screen's, handoff §3): a person or a face SEEN in some cut; no `ok`
#: analysis of the current version; one queued or running. `none` (nothing seen, or
#: something the analysis could not tell) shows nothing: the screen never claims what
#: was not seen (D2) and never says «sin personas».
BADGE_PERSON = "person"
BADGE_NOT_ANALYZED = "not_analyzed"
BADGE_LOOKING = "looking"
BADGE_PERSON_TEXT = "Aparece una persona"
#: The UX review's words (2026-11-06), in place of «Sin analizar» / «Mirando el reel».
BADGE_NOT_ANALYZED_TEXT = "Aún no lo revisamos"
BADGE_LOOKING_TEXT = "Lo estamos revisando"
_SHOWN_BADGES = (BADGE_PERSON, BADGE_NOT_ANALYZED, BADGE_LOOKING)

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
    #: The empty state's one button ("" for none), and what it does (`ACTION_*`).
    action: str = ""
    action_to: str = ""
    #: A notice ABOVE stored ideas that are still true (a newer run failed its check).
    notice_title: str = ""
    notice_body: str = ""
    #: The ideas, best first, in the card shape the view renders (`reels.reel_card`).
    cards: list[dict[str, str]] = field(default_factory=list)
    #: When the shown run found its ideas (ISO, UTC) — "" when none is shown.
    data_iso: str = ""
    #: The browser re-reads the view (a database read, free) every few seconds: while the
    #: first run is in flight (`SCREEN_PREPARING`), and while a failed run waits for the
    #: worker to try it again (`RunView.next_retry_at`, for up to `PREPARING_LIMIT` past
    #: that moment).
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
    """The day the next weekly run comes, in the business's zone: today when it is Monday
    before `WEEKLY_AT` (06:00), else the first Monday after today."""
    local = now.astimezone(zone)
    today = local.date()
    if today.weekday() == 0 and local.time() < WEEKLY_AT:
        return today
    return today + timedelta(days=7 - today.weekday())


def retries_soon(view: RunView, now: datetime) -> bool:
    """The worker will try the failed run again by itself, and that moment is not more
    than `PREPARING_LIMIT` past: the screen keeps reading until it does."""
    return view.next_retry_at is not None and now <= view.next_retry_at + PREPARING_LIMIT


def retry_sentence(view: RunView, now: datetime, zone: tzinfo) -> str:
    """When a run that failed is tried again: in a few minutes while the worker will
    retry it by itself (`next_retry_at`), else with the next weekly run."""
    if view.next_retry_at is not None:
        return RETRY_SOON
    return RETRY_MONDAY.format(d=next_monday(now, zone).day)


def _since(days: int) -> str:
    """«hoy», «ayer», «hace 9 días» — `MEANWHILE`'s «hace {N} días», said right for 0 and 1."""
    if days == 0:
        return "hoy"
    if days == 1:
        return "ayer"
    return f"hace {days} días"


def header(
    run: RunRecord, now: datetime, zone: tzinfo, *, next_ones: bool = True
) -> tuple[str, str]:
    """`(title, body)` over the ideas of `run`: this week's weekly run says since when;
    another run of today says at what time; anything older says how old — and, unless
    `next_ones` is False (a notice above names that Monday already), when the next come."""
    found = run_moment(run).astimezone(zone)
    today = now.astimezone(zone).date()
    if run.trigger == TRIGGER_WEEKLY and _monday(found.date()) == _monday(today):
        following = _monday(found.date()) + timedelta(days=7)
        body = WEEK_BODY.format(weekday=_WEEKDAYS[found.weekday()], d=found.day)
        if next_ones:
            body = f"{body} {NEXT_ONES.format(d=following.day)}"
        return WEEK_TITLE, body
    age = days_ago(found, now, zone)
    if age == 0:
        # «a las 9:05 a. m.»: the abbreviation's period closes the sentence too (RAE)
        return TODAY_TITLE, TODAY_BODY.format(h=clock_12h(found)).replace("m..", "m.")
    title = YESTERDAY_TITLE if age == 1 else OLD_TITLE.format(n=age)
    if not next_ones:
        return title, OLD_BODY
    return title, f"{OLD_BODY} {NEXT_ONES.format(d=next_monday(now, zone).day)}"


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
    # «Hacer uno parecido» only when the run kept the reel's video (R2): the reference
    # is prepared from that copy on the server, never from a URL the browser hands in
    card["can_replicate"] = "1" if getattr(idea, "can_replicate", False) else ""
    # when the run read the video's CDN link (it lives ~24 h): «Hacer uno parecido» asks
    # for the analysis with it only while it is fresh (`reel_analysis.usable_video_url`)
    card["video_at"] = reel.video_url_at.isoformat() if reel.video_url_at else ""
    # filled by `with_analysis_badges` once the shared analyses are read ("" = no pill)
    card["analysis"] = ""
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


def with_analysis_badges(
    cards: Sequence[dict[str, str]], badges: dict[tuple[str, str], str]
) -> list[dict[str, str]]:
    """The cards with their analysis pill (`card["analysis"]`): one of `_SHOWN_BADGES`, or
    "" — nothing seen, something the analysis could not tell, or a card it does not
    know. Never drops a card: an idea is never hidden for what its analysis says."""
    out = []
    for card in cards:
        badge = badges.get((card.get("network", ""), card.get("id", "")), "")
        out.append({**card, "analysis": badge if badge in _SHOWN_BADGES else ""})
    return out


def card_video_read_at(card: dict[str, str]) -> datetime | None:
    """When the run read the card's video link (`card["video_at"]`); None when unknown
    or malformed (the analysis then judges the link by its own signed expiry only)."""
    raw = (card.get("video_at") or "").strip()
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


# --------------------------------------------------------------------------------------
# the screen
# --------------------------------------------------------------------------------------


def wants_first_run(stored: StoredIdeas) -> bool:
    """Option A (founder, 2026-11-04): the brand could have ideas (accounts and a brief) but
    never had a run — opening the screen queues its first one (`ensure_first_run`)."""
    view = stored.view
    return view.latest is None and view.shown is None and stored.accounts > 0 and stored.has_brief


def _notice(stored: StoredIdeas, now: datetime, zone: tzinfo) -> tuple[str, str]:
    """`(title, body)` of the notice over stored ideas when the newest run failed (founder,
    2026-11-04: «No pudimos traer ideas nuevas», info tone) — the ideas below are still
    true, and the body says when the run is tried again. `("", "")` otherwise."""
    view = stored.view
    shown, latest = view.shown, view.latest
    if shown is None or latest is None or latest.id == shown.id:
        return "", ""
    retry = retry_sentence(view, now, zone)
    if latest.status == STATUS_CHECK_FAILED and stored.has_brief:
        body = CHECK_FAILED_BODY.format(retry=retry)
    elif latest.status in STOPPED:
        body = retry
    else:
        return "", ""
    since = _since(days_ago(run_moment(shown), now, zone))
    return NEWS_FAILED_TITLE, f"{body} {MEANWHILE.format(since=since)}"


def _in_line_too_long(view: RunView, now: datetime) -> bool:
    """The run in flight has waited longer than `PREPARING_LIMIT` since it last went into
    the queue (`RunView.waiting_since`; its `queued_at` when the view does not say): a
    retried check keeps its first `queued_at`, and counting from it would say «tardando»
    the moment it is back in line."""
    since = getattr(view, "waiting_since", None)
    if since is None and view.latest is not None:
        since = view.latest.queued_at
    return since is not None and now - since > PREPARING_LIMIT


def ideas_screen(stored: StoredIdeas, *, now: datetime) -> IdeasScreen:
    """Which `SCREEN_*` and its words. Stored ideas always win — they are still true —
    with a notice above them when a newer run failed. Without ideas: no accounts, then no
    brief, then a failed check, then a run that kept none, then a run that stopped, then
    the first run being prepared (or taking longer than it should)."""
    zone = business_zone(stored.timezone)
    view = stored.view
    shown, latest = view.shown, view.latest
    cards = idea_cards(stored, now=now) if shown is not None else []
    if shown is not None and cards:
        notice_title, notice_body = _notice(stored, now, zone)
        title, body = header(shown, now, zone, next_ones=not notice_title)
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
            SCREEN_NO_ACCOUNTS,
            NO_ACCOUNTS_TITLE,
            NO_ACCOUNTS_BODY,
            NO_ACCOUNTS_ACTION,
            action_to=ACTION_ACCOUNTS,
        )
    if not stored.has_brief:
        return IdeasScreen(
            SCREEN_NO_BRIEF,
            NO_BRIEF_TITLE,
            NO_BRIEF_BODY,
            NO_BRIEF_ACTION,
            action_to=ACTION_ACCOUNTS,
        )
    if latest is not None and latest.status == STATUS_CHECK_FAILED:
        body = CHECK_FAILED_BODY.format(retry=retry_sentence(view, now, zone))
        return _failure(SCREEN_CHECK_FAILED, CHECK_FAILED_TITLE, body, view, now)
    if shown is not None:
        return IdeasScreen(
            SCREEN_NO_IDEAS,
            NO_IDEAS_TITLE,
            NO_IDEAS_BODY.format(d=next_monday(now, zone).day),
            NO_IDEAS_ACTION,
            action_to=ACTION_ACCOUNTS,
            data_iso=run_moment(shown).astimezone(UTC).isoformat(),
        )
    if latest is not None and latest.status in STOPPED:
        body = retry_sentence(view, now, zone)
        return _failure(SCREEN_UNAVAILABLE, UNAVAILABLE_TITLE, body, view, now)
    if latest is not None and latest.status in IN_FLIGHT and not _in_line_too_long(view, now):
        return IdeasScreen(SCREEN_PREPARING, PREPARING_TITLE, PREPARING_BODY, waiting=True)
    # in line too long — or no run could be queued: no spinner, a button that looks again
    return IdeasScreen(SCREEN_SLOW, SLOW_TITLE, SLOW_BODY, SLOW_ACTION, action_to=ACTION_REREAD)


def _failure(screen: str, title: str, body: str, view: RunView, now: datetime) -> IdeasScreen:
    """A failed run with nothing stored (UX re-check 1): while the worker will try it
    again, the screen keeps reading and offers «Ver si ya están»; once it waits for the
    weekly run, «Crear una publicación» — a way to go on instead of a dead end."""
    if view.next_retry_at is not None:
        return IdeasScreen(
            screen,
            title,
            body,
            SLOW_ACTION,
            action_to=ACTION_REREAD,
            waiting=retries_soon(view, now),
        )
    return IdeasScreen(screen, title, body, CREATE_ACTION, action_to=ACTION_CREATE)


__all__ = [
    "ACTION_ACCOUNTS",
    "ACTION_CREATE",
    "ACTION_REREAD",
    "BADGE_LOOKING",
    "BADGE_LOOKING_TEXT",
    "BADGE_NOT_ANALYZED",
    "BADGE_NOT_ANALYZED_TEXT",
    "BADGE_PERSON",
    "BADGE_PERSON_TEXT",
    "CANNOT_REPLICATE",
    "CREATE_ACTION",
    "IDEAS_BACK_LABEL",
    "SIMILAR_BUSY",
    "SIMILAR_HELP",
    "SIMILAR_LABEL",
    "NEXT_ONES",
    "CHECK_FAILED_BODY",
    "CHECK_FAILED_TITLE",
    "IN_FLIGHT",
    "LOAD_ERROR",
    "MEANWHILE",
    "NEWS_FAILED_TITLE",
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
    "PREPARING_LIMIT",
    "PREPARING_TITLE",
    "RETRY",
    "RETRY_MONDAY",
    "RETRY_SOON",
    "SCREEN_CHECK_FAILED",
    "SCREEN_IDEAS",
    "SCREEN_NO_ACCOUNTS",
    "SCREEN_NO_BRIEF",
    "SCREEN_NO_IDEAS",
    "SCREEN_PREPARING",
    "SCREEN_SLOW",
    "SCREEN_UNAVAILABLE",
    "SLOW_ACTION",
    "SLOW_BODY",
    "SLOW_TITLE",
    "STOPPED",
    "TODAY_BODY",
    "TODAY_TITLE",
    "UNAVAILABLE_TITLE",
    "WEEK_BODY",
    "WEEK_TITLE",
    "YESTERDAY_TITLE",
    "IdeasScreen",
    "StoredIdeas",
    "business_zone",
    "card_video_read_at",
    "clock_12h",
    "days_ago",
    "header",
    "idea_card",
    "idea_cards",
    "idea_lifts",
    "ideas_screen",
    "next_monday",
    "retries_soon",
    "retry_sentence",
    "run_moment",
    "wants_first_run",
    "with_analysis_badges",
]

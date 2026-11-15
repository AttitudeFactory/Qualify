"""The weekly TikTok read per hashtag of a business's rubro (m-25026378, epic m-25026375,
`docs/epica-etiquetas-publicaciones.md` entrega 3; founder decision D1, 2026-11-13).

Once a week per business, up to `MAX_TAGS` hashtags of its rubro are read on TikTok
(`/v1/tiktok/search/hashtag`, 20 videos per read, 1 credit) and the views and date of
every Spanish video of the last `WINDOW_DAYS` land in the shared catalog
(`hashtag_post_sightings`, 0162) — so «popular» in «Sugerir con IA» also knows what the
rubro's videos carry this week. The worker CLI is `qualify_api.hashtags.worker`.

**Where the hashtags come from.** The ones the owner keeps on «Tu rubro y ubicación»
(`brand_kit_details.connect.hashtags`, the pills of the Brand Kit's connect flow — the
same ones the referentes search runs with), in the order they were chosen, the first
five the catalog would accept (`readable_tag`; a pill it would refuse is skipped and does
not take a slot). A business without pills is not read: Qualify never guesses a rubro to
pay for. During the pilot (D3) production reads only the businesses listed in
`QUALIFY_HASHTAG_WEEKLY_TENANTS` (`hashtags.pilot`), for the reels worker and the CLI's
`--all-tenants` alike. `run_tick(None)` — unused while the pilot lasts — would read the
businesses the reels worker treats as active (`reel_schedule.is_active` over
`PostgresReelQueue.opened_brands`, ADR 42 §2.6). **Known limitation, for the founder to
decide before opening it to everyone (D3):** that
gate means exactly «a brand of the business opened the «Ideas para tus reels» screen in
the last 14 days» — not «the business is a paying, active client». A business that
publishes every day but never opens that screen is not read; one that opened it once and
churned is read for two more weeks.

**Who pays, and how often** (ADR 42). Every read goes through the metered gate
(`vendors.scrapecreators.metered_get`), charged to the business it was read for under
the feature `hashtag_weekly` — its 150/600 caps, the 500-credit floor, the kill switch
and the 402 stop all apply. The rules, checked in this order under a per-business claim
(`Claims`: a non-blocking advisory lock, so two passes never read for the same business
at once):

1. **The week is a kept answer.** A hashtag whose answer is in `vendor_payloads` (0036)
   from the last `REREAD_AFTER` — for any region and whoever asked: this read for
   another business, a referentes search page — is not read again. A clean «nothing
   indexed» (HTTP 404) is kept as an answer too. A booking alone never counts as read.
2. **An unexplained attempt holds the day.** A business with a `hashtag_weekly` booking
   of UNKNOWN outcome (below) in the last `RETRY_AFTER` (24 h) is not attempted again:
   that booking was a refusal (401/402/429, any other 4xx but 404, a body without
   success), an answer that was paid but not kept, or a pass that died mid-call.
3. **Five billed a week.** A business's BILLED `hashtag_weekly` credits in any rolling 7
   days never exceed `MAX_TAGS` — every booking counts except the first credit of a call
   marked unbilled (below); `:extra` rows always count. It is a sum over the ledger, never
   over the current pills: an owner who changes them every day still pays at most 5 a
   week. The bound rests on one measured fact: the vendor does not bill a 503 (2026-11-14:
   7 of 14 reads answered 503, none billed). Any other failure is counted as billed.
4. **A vendor outage costs a retry, not the day nor the week** (m-25031643, D3 of
   2026-11-15). Unbilled is ONLY what was measured as not billed or what never left:
   an HTTP status in `UNBILLED_STATUSES` (503) or a request that was never sent
   (`httpx.ConnectError`, `ConnectTimeout`, `PoolTimeout`) — `_transient`. Any other
   5xx (500, 502, 504, 520-524), a read/write timeout or error, a protocol error or
   anything unknown may have been billed: no marker, unknown outcome (rule 2). An
   unbilled call is marked, does not count in rule 3 and does not hold the day;
   instead two brakes keep restarts from hammering the vendor: no new attempt until
   `MIN_RETRY_WAIT` (3 h) after the last unbilled failure — so the 6-hourly check of the
   reels worker always qualifies and a burst of deploys does not — and at most
   `MAX_UNBILLED_A_DAY` (4) unbilled failures per business in any rolling 24 h.
5. **Headroom for the owner.** A business (not exempt from the cap) that already spent
   more than `DAILY_HEADROOM` of its daily cap or `MONTHLY_HEADROOM` of its monthly one
   is skipped for now, booking nothing: what is left is for the searches it asks for.
6. **One reader per hashtag.** Each read is taken under a claim on the hashtag itself
   (`Claims.claim_tag`) and re-checked inside it, so two businesses sharing a hashtag at
   the same moment never both pay: the second finds the claim taken (and leaves it for a
   later pass) or the first one's kept answer.
7. **Stop at the first failure.** A pass stops on its first error that is not a clean
   «no results» answer; the remaining tags wait for the next allowed attempt.

**How the ledger tells billed from unbilled** (no migration, the gate untouched). The gate
books every call as one `hashtag_weekly` row, `request_key = hashtag_weekly:<uuid>`,
before it leaves; `vendor_usage_events` is append-only, so this module never changes that
row. After the call it APPENDS a marker for it: a row of the same feature with `credits =
0` and `request_key = <that key>:kept` (the answer was kept: a 200 or a 404) or `<that
key>:unbilled` (a failure `_transient` says was not billed). A marker adds nothing to any
sum, so the gate's daily/monthly caps and the headroom keep counting every booked call —
an unbilled one included — as conservatively as before. A call with no marker is of
UNKNOWN outcome: it counts as billed (rule 3) and holds the day (rule 2), exactly what
every booking did before this rule. So a marker that could not be written, a crash between
the call and its marker, and every booking made before 2026-11-15's change all fall back
to the old, stricter behaviour — never to a free retry. A marker is written under the
business's claim with the call's own key + suffix, `ON CONFLICT DO NOTHING`: re-running it
writes nothing.

Bounds per business. **Billed:** at most `MAX_TAGS` (5) credits in any 7 days, so at most
25 in any 31-day month (22 on average when healthy). A call is booked one credit before
it leaves and the rest (`credits_charged`, measured at 1) after its answer, so a vendor
charging N per call can overshoot a 7-day window by at most N−1 — its last call — in
every window (5×(N−1) extra in a 31-day month). **Booked in our ledger** (what the caps
and the headroom see): those 5 plus at most `MAX_UNBILLED_A_DAY` unbilled calls in any
24 h, i.e. at most 5 + 4×7 = 33 credits in any 7 days if the vendor failed every allowed
retry (4 × 31 + 25 = 149 in a 31-day month, under the 500 of `MONTHLY_HEADROOM`). Failures
that are not unbilled count among the 5 and hold the day, so they change neither number.

**Switches.** `QUALIFY_HASHTAG_WEEKLY_READ` is OFF unless set to 1/true/on/yes; with it
off — or with the gate's `QUALIFY_SCRAPECREATORS_PAID` off, or no
`SCRAPECREATORS_API_KEY` — a tick reads nothing and books nothing, before it looks at any
business.

**What is kept.** The vendor's raw answer, whole, in `vendor_payloads`, upserted on path +
parameters (the rule of 0036): each week's read replaces the previous one for the same
hashtag and region, and it shares that row with the referentes search's cache of the
same first page. So only the LATEST read can be re-parsed (`parse_videos`); the sightings
of earlier weeks stay in `hashtag_post_sightings` but cannot be rebuilt from a stored
answer. The sightings carry `source='hashtag_weekly'`, `source_ref='tiktok:hashtag_weekly'`
(the kind of read, never the hashtag nor the business) and `parser_version`; the post id
is the source id.

**Filter.** A video counts only when TikTok says it is in Spanish (`desc_language`),
it was posted in the last `WINDOW_DAYS` (`create_time`), and it is not an ad (its views
are bought). Its tags are the read hashtag plus every `#tag` of its caption and its
`text_extra` — co-occurring tags arrive here `unknown`, with no search count, and stay
out of the paid classification queue (`repository.UNQUEUED_SIGHTING_SOURCES`).
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

import httpx
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creators.repository import (
    VENDOR as POOL_VENDOR,
)
from qualify_api.creators.repository import (
    PostgresCreatorPoolRepository,
    params_key,
)
from qualify_api.hashtags.repository import (
    POPULAR_WINDOW_DAYS,
    HashtagRepository,
    NewPostSighting,
    PostgresHashtagRepository,
    fold,
    normalize_tag,
)
from qualify_api.referentes.reel_schedule import ScheduledBrand, is_active
from qualify_api.vendors import uncapped, usage
from qualify_api.vendors.scrapecreators import (
    _TIMEOUT_SECONDS,
    FEATURE_HASHTAG_WEEKLY,
    ScrapeCreatorsBlocked,
    ScrapeCreatorsError,
    last_request_key,
    metered_get,
    paid_switch_on,
)

logger = logging.getLogger(__name__)

#: The switch: OFF unless one of `_SWITCH_ON` (D1: «todo se apaga con un interruptor»).
SWITCH_ENV = "QUALIFY_HASHTAG_WEEKLY_READ"
_SWITCH_ON = frozenset({"1", "true", "on", "yes"})
#: Without the vendor's key the gate would book a credit and then fail: checked first.
API_KEY_ENV = "SCRAPECREATORS_API_KEY"

PATH = "/v1/tiktok/search/hashtag"
#: At most this many of a business's rubro hashtags per week (D1: 5 × 1 × 4.3 ≈ 22 credits
#: a month per business).
MAX_TAGS = 5
#: A hashtag with a kept answer inside this window is not read again.
REREAD_AFTER = timedelta(days=7)
#: A business with a weekly booking of unknown outcome (a refusal, an answer not kept, a
#: pass that died mid-call) inside this window is not attempted again.
RETRY_AFTER = timedelta(hours=24)
#: HTTP statuses the vendor was MEASURED not to bill (503: 2026-11-14, 7 of 14 manual
#: reads answered 503, none billed; 2026-11-15 in production). This set only grows with
#: a measured vendor test documented in `docs/epica-etiquetas-publicaciones.md` (D3).
UNBILLED_STATUSES = frozenset({503})
#: Request errors where the request was never sent, so nothing could be billed.
_NEVER_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
#: After an unbilled failure (503, a request never sent) the business waits this long: less
#: than the reels worker's 6-hour check (`reel_worker.HASHTAGS_EVERY`), so the next check
#: always qualifies; more than a burst of deploys, so restarts do not hammer the vendor.
MIN_RETRY_WAIT = timedelta(hours=3)
#: At most this many unbilled failures per business in any rolling `UNBILLED_WINDOW`.
MAX_UNBILLED_A_DAY = 4
UNBILLED_WINDOW = timedelta(hours=24)
#: The markers appended after a call to its booking's `request_key` (0-credit rows).
KEPT_SUFFIX = ":kept"
UNBILLED_SUFFIX = ":unbilled"
#: The gate's own suffix for the credits charged beyond the first.
EXTRA_SUFFIX = ":extra"
#: `BusinessOutcome.reason` of a pass stopped by an unbilled failure.
UNBILLED = "unbilled"
#: Headroom left for what the owner asks for himself (UX review): above these shares of
#: the business's caps the weekly read waits. 2/3 of 150 = 100; 5/6 of 600 = 500.
DAILY_HEADROOM = usage.DAILY_CAP * 2 // 3
MONTHLY_HEADROOM = usage.MONTHLY_CAP * 5 // 6
#: Only videos posted inside this window count — the same 90 days «popular» sums.
WINDOW_DAYS = POPULAR_WINDOW_DAYS
LANGUAGE = "es"
#: A hashtag longer than this is not a rubro pill anyone types; it is not read.
MAX_TAG_LENGTH = 50

SOURCE = "hashtag_weekly"
SOURCE_REF = "tiktok:hashtag_weekly"
#: Bump when `parse_videos` changes what a sighting means.
PARSER_VERSION = "tiktok-hashtag-weekly/1"

_HASHTAG_IN_TEXT = re.compile(r"#(\w+)")
_WORD = re.compile(r"\w+")
_COUNTRY = re.compile(r"[A-Z]{2}")
#: A gate refusal that holds for every business (the switch, the floor, a 402): the tick
#: stops. A cap refusal (`usage.CAP_REASONS`) only stops that business.
_GLOBAL_BLOCKS = frozenset({"switch_off", "halted", "below_floor", "balance_unreadable"})


def switch_on(env: Mapping[str, str] | None = None) -> bool:
    return (env if env is not None else os.environ).get(SWITCH_ENV, "").strip().lower() in (
        _SWITCH_ON
    )


# --------------------------------------------------------------------------------------
# what a business reads: its rubro
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BusinessRubro:
    """What the weekly read needs of one business: its rubro hashtags (readable, in the
    owner's order, at most `MAX_TAGS`), the country sent as the proxy `region`, and the
    brand the credits are booked under."""

    tenant_id: UUID
    tags: tuple[str, ...]
    country_code: str | None = None
    brand_id: UUID | None = None


def readable_tag(raw: object) -> str | None:
    """The tag as the catalog stores it, or None when the catalog would refuse its
    sightings or it is not a hashtag at all: one token (`normalize_tag`), letters or digits
    in it (`fold`), only word characters — what the catalog reads as a `#tag` in a caption
    (`#(\\w+)`) — and at most `MAX_TAG_LENGTH` long. `🍔`, `c++`, `...` and a 300-character
    pill are None."""
    if not isinstance(raw, str):
        return None
    try:
        tag = normalize_tag(raw)
    except ValueError:
        return None
    if len(tag) > MAX_TAG_LENGTH or not _WORD.fullmatch(tag) or not fold(tag):
        return None
    return tag


def rubro_tags(connect: Mapping[str, Any] | None, *, limit: int = MAX_TAGS) -> tuple[str, ...]:
    """The pills of «Tu rubro y ubicación» (`connect.hashtags`: `[{"tag": ..., ...}]`) the
    catalog would accept (`readable_tag`), deduplicated in order; any other pill is
    skipped without taking one of the `limit` slots."""
    out: list[str] = []
    pills = (connect or {}).get("hashtags")
    for pill in pills if isinstance(pills, list) else ():
        tag = readable_tag(pill.get("tag") if isinstance(pill, Mapping) else None)
        if tag is None or tag in out:
            continue
        out.append(tag)
        if len(out) >= limit:
            break
    return tuple(out)


def country_or_none(value: object) -> str | None:
    code = str(value or "").strip().upper()
    return code if _COUNTRY.fullmatch(code) else None


def business_rubro(
    tenant_id: UUID,
    details: Sequence[tuple[UUID, Mapping[str, Any] | None]],
    tenant_country: object = None,
) -> BusinessRubro:
    """A business's rubro from its brands' connect documents (oldest brand first): the
    tags of every brand in order, the first `MAX_TAGS`; the country of the first brand
    that chose one, else the business's own; the brand of the first tag."""
    tags: list[str] = []
    country: str | None = None
    brand: UUID | None = None
    for brand_id, connect in details:
        own = rubro_tags(connect, limit=MAX_TAGS)
        if own and brand is None:
            brand = brand_id
        tags.extend(t for t in own if t not in tags)
        country = country or country_or_none((connect or {}).get("country_code"))
    return BusinessRubro(
        tenant_id=tenant_id,
        tags=tuple(tags[:MAX_TAGS]),
        country_code=country or country_or_none(tenant_country),
        brand_id=brand,
    )


# --------------------------------------------------------------------------------------
# the parser: a raw answer -> sightings (pure, re-runnable over a stored answer)
# --------------------------------------------------------------------------------------


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _video_tags(read_tag: str, item: Mapping[str, Any]) -> list[str]:
    raw = [read_tag, *_HASHTAG_IN_TEXT.findall(str(item.get("desc") or ""))]
    for extra in item.get("text_extra") or ():
        name = extra.get("hashtag_name") if isinstance(extra, Mapping) else None
        if isinstance(name, str) and name:
            raw.append(name)
    out: list[str] = []
    for value in raw:
        try:
            tag = normalize_tag(value)
        except ValueError:
            continue
        if tag not in out:
            out.append(tag)
    return out


def parse_videos(
    read_tag: str,
    payload: Mapping[str, Any],
    *,
    now: datetime | None = None,
    window_days: int = WINDOW_DAYS,
) -> list[NewPostSighting]:
    """Every (tag, video) of a `search/hashtag` answer that counts: Spanish, not an ad,
    posted in the last `window_days` before `now` (and not in the future). Views are
    `statistics.play_count` (None when absent — never zero). A tag the catalog would
    refuse is skipped, never raised."""
    moment = now or datetime.now(UTC)
    cutoff = moment - timedelta(days=window_days)
    found: dict[tuple[str, str], NewPostSighting] = {}
    for item in payload.get("aweme_list") or ():
        if not isinstance(item, Mapping):
            continue
        post_id = str(item.get("aweme_id") or "").strip()
        if not post_id or item.get("is_ad") is True:
            continue
        if str(item.get("desc_language") or "").strip().lower() != LANGUAGE:
            continue
        created = _int(item.get("create_time"))
        if created is None or created <= 0:
            continue
        try:
            posted_at = datetime.fromtimestamp(created, UTC)
        except (OverflowError, OSError, ValueError):
            continue
        if posted_at < cutoff or posted_at > moment + timedelta(days=1):
            continue
        stats = item.get("statistics")
        views = _int(stats.get("play_count")) if isinstance(stats, Mapping) else None
        if views is not None and views < 0:
            views = None
        for tag in _video_tags(read_tag, item):
            try:
                sighting = NewPostSighting(
                    tag=tag,
                    network="tiktok",
                    post_id=post_id,
                    source=SOURCE,
                    source_ref=SOURCE_REF,
                    parser_version=PARSER_VERSION,
                    posted_at=posted_at,
                    views=views,
                )
            except ValueError:
                continue
            found.setdefault((sighting.tag, post_id), sighting)
    return list(found.values())


# --------------------------------------------------------------------------------------
# ports: where the rubro is read, what was already read, where the answer is kept
# --------------------------------------------------------------------------------------


class RubroSource(Protocol):
    def businesses(self, tenant_ids: Sequence[UUID] | None, *, now: datetime) -> list[UUID]:
        """`tenant_ids` as given (deduplicated), or every ACTIVE business when None."""
        ...

    def rubro(self, tenant_id: UUID) -> BusinessRubro: ...


@dataclass(frozen=True)
class Booking:
    """One `hashtag_weekly` row of `vendor_usage_events`: a call's booking, its `:extra`
    credits or one of this module's 0-credit markers."""

    request_key: str
    credits: int
    at: datetime


_MARKERS = (KEPT_SUFFIX, UNBILLED_SUFFIX)


@dataclass(frozen=True)
class WeeklyLedger:
    """What a business's weekly bookings say (module docstring, «How the ledger tells
    billed from unbilled»): the billed credits, when the latest call of UNKNOWN outcome
    was booked, and when each unbilled failure was marked."""

    billed: int = 0
    unknown_at: datetime | None = None
    unbilled_at: tuple[datetime, ...] = ()

    def unbilled_since(self, since: datetime) -> int:
        return sum(1 for at in self.unbilled_at if at >= since)

    @property
    def last_unbilled(self) -> datetime | None:
        return max(self.unbilled_at, default=None)


def summarize(bookings: Sequence[Booking]) -> WeeklyLedger:
    """Every credit counts as billed except the booked credit of a call marked unbilled;
    a call (a row whose key carries no suffix) with neither marker is of unknown outcome.
    A call marked both ways counts as kept (billed). Pure: the same rule for the
    Postgres ledger and the offline fake."""
    keys = {b.request_key for b in bookings}
    billed = sum(b.credits for b in bookings)
    unknown: list[datetime] = []
    for b in bookings:
        if b.request_key.endswith((*_MARKERS, EXTRA_SUFFIX)):
            continue
        if b.request_key + KEPT_SUFFIX in keys:
            continue
        if b.request_key + UNBILLED_SUFFIX in keys:
            billed -= b.credits
            continue
        unknown.append(b.at)
    return WeeklyLedger(
        billed=billed,
        unknown_at=max(unknown, default=None),
        unbilled_at=tuple(
            sorted(b.at for b in bookings if b.request_key.endswith(UNBILLED_SUFFIX))
        ),
    )


def marker_event(
    tenant_id: UUID, brand_id: UUID | None, request_key: str, suffix: str
) -> usage.UsageEvent:
    """The 0-credit row that says how the call booked as `request_key` ended."""
    if suffix not in _MARKERS:
        raise ValueError(f"unknown marker: {suffix!r}")
    return usage.UsageEvent(
        tenant_id=tenant_id,
        brand_id=brand_id,
        vendor=usage.SCRAPECREATORS,
        feature=FEATURE_HASHTAG_WEEKLY,
        credits=0,
        usd_estimate=Decimal(0),
        pricing_table_version=usage.PRICING_TABLE_VERSION,
        request_key=f"{request_key}{suffix}",
    )


class ReadLog(Protocol):
    def bookings_since(self, tenant_id: UUID, since: datetime) -> list[Booking]:
        """This business's `hashtag_weekly` rows booked at or after `since` — calls,
        `:extra` rows and markers alike."""
        ...

    def mark(self, tenant_id: UUID, brand_id: UUID | None, request_key: str, suffix: str) -> None:
        """Append the marker `suffix` for the call booked as `request_key` (idempotent:
        the ledger's UNIQUE (tenant_id, request_key))."""
        ...

    def tag_read_since(self, tenant_id: UUID, tag: str, since: datetime) -> bool:
        """Whether an answer for `tag` (any region, any caller) was kept at or after
        `since`. `tenant_id` is only the key to the DB door: the table has no tenant."""
        ...

    def keep(
        self,
        tenant_id: UUID,
        params: Mapping[str, str],
        payload: Mapping[str, Any],
        *,
        status: int,
        credits: int,
        now: datetime,
    ) -> None:
        """Store the vendor's raw answer (shared, no tenant)."""
        ...


class Claims(Protocol):
    def claim(self, tenant_id: UUID) -> AbstractContextManager[bool]:
        """Hold this business for one pass: yields True when taken, False when another
        pass holds it (never waits)."""
        ...

    def claim_tag(self, tenant_id: UUID, tag: str) -> AbstractContextManager[bool]:
        """Hold this hashtag around «kept this week? → read», whoever reads it: yields
        False when another pass (for any business) holds it (never waits). A pass holds
        at most one hashtag at a time, always inside its business's claim. `tenant_id`
        is only the key to the DB door."""
        ...


class OpenedBrands(Protocol):
    """`referentes.reel_queue.ReelQueue.opened_brands` — the reels worker's activity read."""

    def opened_brands(self, *, since: datetime) -> list[ScheduledBrand]: ...


def active_tenants(queue: OpenedBrands, now: datetime) -> list[UUID]:
    """The businesses with a brand the reels worker would treat as active at `now`
    (`reel_schedule.is_active`: opened in the last 14 days), in id order."""
    from qualify_api.referentes.reel_schedule import INACTIVE_AFTER  # noqa: PLC0415

    brands = queue.opened_brands(since=now - INACTIVE_AFTER)
    return sorted({b.tenant_id for b in brands if is_active(b, now)}, key=str)


@dataclass
class MemoryRubroSource:
    rubros: dict[UUID, BusinessRubro] = field(default_factory=dict)
    #: How many times a business's rubro was read (the switch-off test counts on 0).
    reads: int = 0

    def businesses(self, tenant_ids: Sequence[UUID] | None, *, now: datetime) -> list[UUID]:
        self.reads += 1
        if tenant_ids is not None:
            return list(dict.fromkeys(tenant_ids))
        return sorted(self.rubros, key=str)

    def rubro(self, tenant_id: UUID) -> BusinessRubro:
        self.reads += 1
        return self.rubros.get(tenant_id, BusinessRubro(tenant_id, ()))


@dataclass
class KeptAnswer:
    params: dict[str, str]
    payload: dict[str, Any]
    status: int
    credits: int
    fetched_at: datetime


@dataclass
class MemoryReadLog:
    """Offline fake. The business side reads the bookings of an `InMemoryUsageStore` (the
    gate's ledger in tests), so «already attempted» is asked of the same rows the gate
    wrote; the hashtag side is the pool of kept answers, keyed like `vendor_payloads` (one
    row per path + parameters, newest wins)."""

    usage_store: usage.InMemoryUsageStore
    answers: dict[str, KeptAnswer] = field(default_factory=dict)

    def bookings_since(self, tenant_id: UUID, since: datetime) -> list[Booking]:
        return [
            Booking(e.request_key, e.credits, e.created_at)
            for e in self.usage_store.of(tenant_id)
            if e.feature == FEATURE_HASHTAG_WEEKLY
            and e.created_at is not None
            and e.created_at >= since
        ]

    def mark(self, tenant_id: UUID, brand_id: UUID | None, request_key: str, suffix: str) -> None:
        self.usage_store.book(marker_event(tenant_id, brand_id, request_key, suffix), capped=False)

    def tag_read_since(self, tenant_id: UUID, tag: str, since: datetime) -> bool:
        return any(
            a.params.get("hashtag", "").lower() == tag and a.fetched_at >= since
            for a in self.answers.values()
        )

    def keep(
        self,
        tenant_id: UUID,
        params: Mapping[str, str],
        payload: Mapping[str, Any],
        *,
        status: int,
        credits: int,
        now: datetime,
    ) -> None:
        self.answers[params_key(params)] = KeptAnswer(
            dict(params), dict(payload), status, credits, now
        )


class MemoryClaims:
    """One non-blocking lock per business and one per hashtag, in this process."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[object, threading.Lock] = {}

    @contextmanager
    def _try(self, key: object) -> Iterator[bool]:
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        got = lock.acquire(blocking=False)
        try:
            yield got
        finally:
            if got:
                lock.release()

    def claim(self, tenant_id: UUID) -> AbstractContextManager[bool]:
        return self._try(("business", tenant_id))

    def claim_tag(self, tenant_id: UUID, tag: str) -> AbstractContextManager[bool]:
        return self._try(("tag", tag))


#: The claims' keys are their own — `hashtag_weekly:<tenant>` for a business,
#: `hashtag_weekly_tag:<tag>` for a hashtag — never the gate's (`vendor_usage:`), and they
#: are only TRIED, never waited on. A pass takes its business, then at most one hashtag at
#: a time, then books through the gate (whose short transaction takes `vendor_usage:`): one
#: order, and nothing in it waits, so none of them can deadlock.
_CLAIM = text("SELECT pg_try_advisory_xact_lock(hashtextextended('hashtag_weekly:' || :k, 0))")
_CLAIM_TAG = text(
    "SELECT pg_try_advisory_xact_lock(hashtextextended('hashtag_weekly_tag:' || :k, 0))"
)


class PostgresClaims:
    """Transaction-scoped advisory locks, each on its own connection (`tenant_session`,
    `independent=True`), released by their commit — across processes, like the gate's
    per-tenant lock (`usage.PostgresUsageStore`). The business's is held for its whole
    pass, a hashtag's around «kept this week? → read»."""

    @contextmanager
    def _try(self, tenant_id: UUID, statement: Any, key: str) -> Iterator[bool]:
        with tenant_session(tenant_id, independent=True) as session:
            yield bool(session.execute(statement, {"k": key}).scalar_one())

    def claim(self, tenant_id: UUID) -> AbstractContextManager[bool]:
        return self._try(tenant_id, _CLAIM, str(tenant_id))

    def claim_tag(self, tenant_id: UUID, tag: str) -> AbstractContextManager[bool]:
        return self._try(tenant_id, _CLAIM_TAG, tag)


_BOOKINGS = text(
    """
    SELECT request_key, credits, created_at FROM vendor_usage_events
    WHERE tenant_id = :tenant AND vendor = :vendor AND feature = :feature
      AND created_at >= :since
    """
)

# Any region, any caller: the referentes search keeps the same path with
# `{"hashtag", "region"[, "cursor"]}` (`Qualify/creator_discovery`), this read with
# `{"hashtag"[, "region"]}`; `params_key` is always a JSON object.
_TAG_READ = text(
    """
    SELECT EXISTS (
        SELECT 1 FROM vendor_payloads
        WHERE vendor = :vendor AND path = :path AND fetched_at >= :since
          AND lower(CAST(params_key AS jsonb) ->> 'hashtag') = :tag
    )
    """
)

_DETAILS = text(
    """
    SELECT d.brand_id, d.connect FROM brand_kit_details d
    WHERE d.tenant_id = :tenant
    ORDER BY d.created_at, d.brand_id
    """
)
_TENANT_COUNTRY = text("SELECT country FROM tenants WHERE id = :tenant")


class PostgresReadLog:
    """`vendor_usage_events` (tenant RLS) for the business side, `vendor_payloads` (global,
    0036) for the hashtag side and the raw answers — all through `tenant_session`."""

    def bookings_since(self, tenant_id: UUID, since: datetime) -> list[Booking]:
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                _BOOKINGS,
                {
                    "tenant": tenant_id,
                    "vendor": usage.SCRAPECREATORS,
                    "feature": FEATURE_HASHTAG_WEEKLY,
                    "since": since,
                },
            ).all()
        return [Booking(r.request_key, int(r.credits), r.created_at) for r in rows]

    def mark(self, tenant_id: UUID, brand_id: UUID | None, request_key: str, suffix: str) -> None:
        # the gate's own door to the ledger (`tenant_session(independent=True)`, its
        # per-tenant lock, `ON CONFLICT (tenant_id, request_key) DO NOTHING`); uncapped:
        # a 0-credit row could never cross a cap anyway
        usage.store().book(marker_event(tenant_id, brand_id, request_key, suffix), capped=False)

    def tag_read_since(self, tenant_id: UUID, tag: str, since: datetime) -> bool:
        with tenant_session(tenant_id) as session:
            return bool(
                session.execute(
                    _TAG_READ, {"vendor": POOL_VENDOR, "path": PATH, "since": since, "tag": tag}
                ).scalar_one()
            )

    def keep(
        self,
        tenant_id: UUID,
        params: Mapping[str, str],
        payload: Mapping[str, Any],
        *,
        status: int,
        credits: int,
        now: datetime,
    ) -> None:
        PostgresCreatorPoolRepository(tenant_id).put_payload(
            PATH, params, payload, status=status, credits_charged=credits, now=now
        )


class PostgresRubroSource:
    """Production: the active businesses through the reels worker's own read
    (`PostgresReelQueue.opened_brands`, its door and its 14-day rule), everything about
    a business through `tenant_session`."""

    def __init__(self, queue: OpenedBrands | None = None) -> None:
        self._queue = queue

    def businesses(self, tenant_ids: Sequence[UUID] | None, *, now: datetime) -> list[UUID]:
        if tenant_ids is not None:
            return list(dict.fromkeys(tenant_ids))
        queue = self._queue
        if queue is None:
            from qualify_api.referentes.reel_queue import PostgresReelQueue  # noqa: PLC0415

            queue = PostgresReelQueue()
        return active_tenants(queue, now)

    def rubro(self, tenant_id: UUID) -> BusinessRubro:
        with tenant_session(tenant_id) as session:
            rows = session.execute(_DETAILS, {"tenant": tenant_id}).all()
            country = session.execute(_TENANT_COUNTRY, {"tenant": tenant_id}).scalar_one_or_none()
        return business_rubro(tenant_id, [(r.brand_id, r.connect) for r in rows], country)


def has_headroom(tenant_id: UUID, now: datetime) -> bool:
    """False when the business already spent more than `DAILY_HEADROOM` credits today or
    `MONTHLY_HEADROOM` this month (its local day and month); always True for a business
    exempt from the cap (`vendors.uncapped`)."""
    if uncapped.is_uncapped(tenant_id):
        return True
    spent = usage.store().spent(tenant_id, usage.SCRAPECREATORS, now)
    return spent.day <= DAILY_HEADROOM and spent.month <= MONTHLY_HEADROOM


# --------------------------------------------------------------------------------------
# the tick
# --------------------------------------------------------------------------------------

#: `BusinessOutcome.status`
NO_TAGS = "no_tags"
UP_TO_DATE = "up_to_date"  # every tag has a kept answer from this week
TRIED_TODAY = "tried_today"  # a booking of unknown outcome in the last 24 h
NO_HEADROOM = "no_headroom"
WEEK_SPENT = "week_spent"  # `MAX_TAGS` billed weekly credits in the last 7 days
RETRY_WAIT = "retry_wait"  # an unbilled failure less than `MIN_RETRY_WAIT` ago
FAILURES_TODAY = "failures_today"  # `MAX_UNBILLED_A_DAY` unbilled failures in 24 h
BUSY = "busy"  # another pass holds the business
DONE = "done"
FAILED = "failed"
CAPPED = "capped"
BLOCKED = "blocked"
#: `TickReport.stopped` / `BusinessOutcome.reason` when the caller's `should_stop` asked
#: the pass to end early (the reels worker's SIGTERM, `hashtags.pilot`).
STOPPING = "stopping"


@dataclass
class BusinessOutcome:
    tenant_id: UUID
    status: str
    #: Hashtags read now (paid), hashtags with a kept answer this week (free), and
    #: hashtags another pass was reading at that moment (left for a later pass).
    read: list[str] = field(default_factory=list)
    fresh: list[str] = field(default_factory=list)
    busy: list[str] = field(default_factory=list)
    sightings: int = 0
    errors: int = 0
    reason: str | None = None


@dataclass
class TickReport:
    outcomes: list[BusinessOutcome] = field(default_factory=list)
    #: Why the tick read nothing or stopped early (`switch_off`, `paid_off`, `no_key`, a
    #: global gate refusal).
    stopped: str | None = None

    @property
    def errors(self) -> int:
        return sum(o.errors for o in self.outcomes)


ClientFactory = Callable[[], httpx.Client]


def _default_client() -> httpx.Client:
    return httpx.Client(timeout=_TIMEOUT_SECONDS)


def _read_tags(
    outcome: BusinessOutcome,
    rubro: BusinessRubro,
    pending: Sequence[str],
    *,
    log: ReadLog,
    repository: HashtagRepository,
    claims: Claims,
    client: httpx.Client,
    now: datetime,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Read `pending` until `MAX_TAGS` billed credits are in the last 7 days: each
    hashtag under its own claim (`claim_tag`), re-checked inside it — a pass for another
    business may have kept it in the meantime — so two businesses sharing a hashtag never
    both pay for it. `should_stop` is asked before each hashtag: when it says so, the
    rest wait for a later pass (`reason=STOPPING`).

    What counts is what the gate BOOKED and was not marked unbilled — its first credit and
    the `:extra` row of what the vendor reports beyond it (`credits_charged`) — re-read
    from the ledger before each read, never a count of calls: with an N-credit call the
    week overshoots `MAX_TAGS` by at most N−1."""
    tenant = rubro.tenant_id
    usage.bind(client, usage.UsageCharge(tenant, rubro.brand_id))
    week = now - REREAD_AFTER
    for tag in pending:
        if should_stop is not None and should_stop():
            outcome.reason = STOPPING
            return
        if summarize(log.bookings_since(tenant, week)).billed >= MAX_TAGS:
            return
        with claims.claim_tag(tenant, tag) as taken:
            if not taken:
                outcome.busy.append(tag)
                continue
            if log.tag_read_since(tenant, tag, week):
                outcome.fresh.append(tag)
                continue
            ok = _read_one(
                outcome, rubro, tag, log=log, repository=repository, client=client, now=now
            )
            if not ok:
                return


def _transient(exc: ScrapeCreatorsError) -> bool:
    """A failure the vendor does not bill: a status in `UNBILLED_STATUSES` (measured), or
    a request that was never sent (`metered_get` chains the `httpx` error as the cause).
    Anything else — another 5xx, a read/write timeout or error, a protocol error, any
    4xx, a body without success, the unknown — may have been billed: not transient."""
    if exc.status_code is not None:
        return exc.status_code in UNBILLED_STATUSES
    return isinstance(exc.__cause__, _NEVER_SENT)


def _booked_key(before: str | None) -> str | None:
    """The request key the gate booked for the call just made, or None when it booked
    none (the context's last key did not change)."""
    key = last_request_key()
    return key if key is not None and key != before else None


def _mark(log: ReadLog, rubro: BusinessRubro, request_key: str | None, suffix: str) -> None:
    """Append the call's marker. Never raises: without it the call is of unknown outcome
    — counted as billed and holding the day — the stricter side."""
    if request_key is None:
        logger.warning("hashtags.weekly no booking to mark tenant=%s", rubro.tenant_id)
        return
    try:
        log.mark(rubro.tenant_id, rubro.brand_id, request_key, suffix)
    except Exception as exc:  # noqa: BLE001 - the stricter rule then applies
        logger.warning(
            "hashtags.weekly marker %s not written tenant=%s: %s",
            suffix,
            rubro.tenant_id,
            type(exc).__name__,
        )


def _read_one(
    outcome: BusinessOutcome,
    rubro: BusinessRubro,
    tag: str,
    *,
    log: ReadLog,
    repository: HashtagRepository,
    client: httpx.Client,
    now: datetime,
) -> bool:
    """One paid read of `tag`; False when the pass must stop (a refusal, a failure).

    After the call its booking gets its marker (`_mark`): `:unbilled` for a transient
    failure, `:kept` once the answer is kept. A refusal and an answer not kept get none:
    their credit counts and holds the day (`RETRY_AFTER`), as before m-25031643."""
    tenant = rubro.tenant_id
    params = {"hashtag": tag}
    if rubro.country_code:
        params["region"] = rubro.country_code
    status = 200
    # `_booked_key(before)` rests on: the gate raises `ScrapeCreatorsError` only after it
    # booked and set the key (before it, only `ScrapeCreatorsBlocked`), and the ContextVar
    # is per thread/task while this pass is synchronous — so a changed key is this call's.
    before = last_request_key()
    try:
        payload: dict[str, Any] = metered_get(client, PATH, params, feature=FEATURE_HASHTAG_WEEKLY)
    except ScrapeCreatorsBlocked as exc:
        outcome.reason = exc.reason
        outcome.status = CAPPED if exc.reason in usage.CAP_REASONS else BLOCKED
        return False
    except ScrapeCreatorsError as exc:
        if exc.status_code != 404:  # 404 = nothing indexed: an answer, kept as one
            logger.warning("hashtags.weekly read failed tenant=%s: %s", tenant, exc)
            outcome.errors += 1
            outcome.status = FAILED
            if _transient(exc):
                outcome.reason = UNBILLED
                _mark(log, rubro, _booked_key(before), UNBILLED_SUFFIX)
            return False
        payload, status = {}, 404
    booked = _booked_key(before)
    credits = _int(payload.get("credits_charged")) or (1 if status == 200 else 0)
    try:
        log.keep(tenant, params, payload, status=status, credits=credits, now=now)
    except Exception as exc:  # noqa: BLE001 - the credit is spent; retried tomorrow
        logger.warning("hashtags.weekly answer not kept tenant=%s: %s", tenant, exc)
        outcome.errors += 1
        outcome.status = FAILED
        return False
    _mark(log, rubro, booked, KEPT_SUFFIX)
    outcome.read.append(tag)
    sightings = parse_videos(tag, payload, now=now)
    if sightings:
        try:
            outcome.sightings += repository.record_post_sightings(tenant, sightings)
        except Exception as exc:  # noqa: BLE001 - the raw answer is kept for a re-parse
            logger.warning("hashtags.weekly sightings not stored tenant=%s: %s", tenant, exc)
            outcome.errors += 1
    return True


def read_business(
    rubro: BusinessRubro,
    *,
    log: ReadLog,
    repository: HashtagRepository,
    client: httpx.Client,
    now: datetime,
    claims: Claims,
    should_stop: Callable[[], bool] | None = None,
) -> BusinessOutcome:
    """One business's weekly read, under its claim (the switches are the caller's). The
    rules of the module docstring, in order; raises nothing a vendor or the catalog
    does — every failure is counted on the outcome."""
    tenant = rubro.tenant_id
    if not rubro.tags:
        return BusinessOutcome(tenant, NO_TAGS)
    with claims.claim(tenant) as taken:
        if not taken:
            return BusinessOutcome(tenant, BUSY)
        outcome = BusinessOutcome(tenant, DONE)
        week = now - REREAD_AFTER
        pending = []
        for tag in rubro.tags:
            (outcome.fresh if log.tag_read_since(tenant, tag, week) else pending).append(tag)
        if not pending:
            outcome.status = UP_TO_DATE
            return outcome
        ledger = summarize(log.bookings_since(tenant, week))
        if ledger.unknown_at is not None and ledger.unknown_at >= now - RETRY_AFTER:
            outcome.status = TRIED_TODAY
            return outcome
        if ledger.billed >= MAX_TAGS:
            outcome.status = WEEK_SPENT
            return outcome
        if ledger.unbilled_since(now - UNBILLED_WINDOW) >= MAX_UNBILLED_A_DAY:
            outcome.status = FAILURES_TODAY
            return outcome
        last = ledger.last_unbilled
        if last is not None and now - last < MIN_RETRY_WAIT:
            outcome.status = RETRY_WAIT
            return outcome
        if not has_headroom(tenant, now):
            outcome.status = NO_HEADROOM
            return outcome
        _read_tags(
            outcome,
            rubro,
            pending,
            log=log,
            repository=repository,
            claims=claims,
            client=client,
            now=now,
            should_stop=should_stop,
        )
        return outcome


def _not_ready(env: Mapping[str, str] | None) -> str | None:
    """Why no business may be looked at: the weekly switch, the gate's kill switch, the
    vendor's key. Checked before any database read, so nothing is ever booked for a
    call that could not leave."""
    if not switch_on(env):
        return "switch_off"
    if not paid_switch_on():
        return "paid_off"
    if not os.environ.get(API_KEY_ENV, "").strip():
        return "no_key"
    return None


def run_tick(
    tenant_ids: Sequence[UUID] | None,
    *,
    source: RubroSource | None = None,
    log: ReadLog | None = None,
    repository: HashtagRepository | None = None,
    claims: Claims | None = None,
    client_factory: ClientFactory = _default_client,
    now: datetime | None = None,
    env: Mapping[str, str] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> TickReport:
    """One pass over `tenant_ids` (None = every active business: production only). With a
    switch off or no vendor key it returns at once — no database read, no booking, no
    vendor call. `env` is where the weekly switch is read (default: the environment);
    the gate's switch and the key are always read from the environment. `should_stop`
    (optional) is asked before each business and each hashtag: when it says so the pass
    ends with `stopped=STOPPING`, after the read in flight at most."""
    reason = _not_ready(env)
    if reason is not None:
        logger.info("hashtags.weekly not run: %s", reason)
        return TickReport(stopped=reason)
    if tenant_ids is not None and not tenant_ids:
        raise ValueError("an explicit scope needs at least one tenant")
    source = source or PostgresRubroSource()
    log = log or PostgresReadLog()
    repository = repository or PostgresHashtagRepository()
    claims = claims or PostgresClaims()
    moment = now or datetime.now(UTC)
    report = TickReport()
    for tenant in source.businesses(tenant_ids, now=moment):
        if should_stop is not None and should_stop():
            report.stopped = STOPPING
            break
        try:
            rubro = source.rubro(tenant)
        except Exception as exc:  # noqa: BLE001 - one business never stops the others
            # the type only: a database error's text can carry its parameters (a tag)
            logger.warning(
                "hashtags.weekly rubro unreadable tenant=%s: %s", tenant, type(exc).__name__
            )
            report.outcomes.append(BusinessOutcome(tenant, FAILED, errors=1))
            continue
        client = client_factory()
        try:
            outcome = read_business(
                rubro,
                log=log,
                repository=repository,
                client=client,
                now=moment,
                claims=claims,
                should_stop=should_stop,
            )
        except Exception as exc:  # noqa: BLE001 - e.g. the ledger is unreadable
            logger.warning(
                "hashtags.weekly business failed tenant=%s: %s", tenant, type(exc).__name__
            )
            outcome = BusinessOutcome(tenant, FAILED, errors=1)
        finally:
            client.close()
        report.outcomes.append(outcome)
        logger.info(
            "hashtags.weekly tenant=%s status=%s read=%d fresh=%d sightings=%d errors=%d reason=%s",
            tenant,
            outcome.status,
            len(outcome.read),
            len(outcome.fresh),
            outcome.sightings,
            outcome.errors,
            outcome.reason,
        )
        if outcome.status == BLOCKED and outcome.reason in _GLOBAL_BLOCKS:
            report.stopped = outcome.reason
            break
        if outcome.reason == STOPPING:
            report.stopped = STOPPING
            break
    return report


__all__ = [
    "DAILY_HEADROOM",
    "EXTRA_SUFFIX",
    "FAILURES_TODAY",
    "KEPT_SUFFIX",
    "MAX_UNBILLED_A_DAY",
    "MIN_RETRY_WAIT",
    "RETRY_WAIT",
    "UNBILLED",
    "UNBILLED_STATUSES",
    "UNBILLED_SUFFIX",
    "UNBILLED_WINDOW",
    "LANGUAGE",
    "MAX_TAGS",
    "MAX_TAG_LENGTH",
    "MONTHLY_HEADROOM",
    "PARSER_VERSION",
    "PATH",
    "REREAD_AFTER",
    "RETRY_AFTER",
    "SOURCE",
    "SOURCE_REF",
    "STOPPING",
    "SWITCH_ENV",
    "WINDOW_DAYS",
    "Booking",
    "BusinessOutcome",
    "BusinessRubro",
    "Claims",
    "MemoryClaims",
    "MemoryReadLog",
    "MemoryRubroSource",
    "PostgresClaims",
    "PostgresReadLog",
    "PostgresRubroSource",
    "ReadLog",
    "RubroSource",
    "TickReport",
    "WeeklyLedger",
    "active_tenants",
    "business_rubro",
    "has_headroom",
    "marker_event",
    "parse_videos",
    "read_business",
    "readable_tag",
    "rubro_tags",
    "run_tick",
    "summarize",
    "switch_on",
]

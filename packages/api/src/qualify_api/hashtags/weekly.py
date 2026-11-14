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
2. **One attempt a day.** A business with a `hashtag_weekly` booking in the last
   `RETRY_AFTER` (24 h) is not attempted again: that booking was a pass that failed, was
   capped or was cut short. It is how a failure is remembered without a new table — the
   gate books before the request leaves, so every attempt leaves its row.
3. **Five a week, hard.** A business's `hashtag_weekly` credits in any rolling 7 days
   never exceed `MAX_TAGS`, counting every booking — kept answers and failures alike —
   whatever its pills do (an owner who changes them every day still pays at most 5 a
   week).
4. **Headroom for the owner.** A business (not exempt from the cap) that already spent
   more than `DAILY_HEADROOM` of its daily cap or `MONTHLY_HEADROOM` of its monthly one
   is skipped for now, booking nothing: what is left is for the searches it asks for.
5. **One reader per hashtag.** Each read is taken under a claim on the hashtag itself
   (`Claims.claim_tag`) and re-checked inside it, so two businesses sharing a hashtag at
   the same moment never both pay: the second finds the claim taken (and leaves it for a
   later pass) or the first one's kept answer.
6. **Stop at the first failure.** A pass stops on its first error that is not a clean
   «no results» answer; the remaining tags wait for the next day's attempt.

Hard bound per business: 5 credits in any 7 days, so at most 25 in any 31-day month,
for any mix of successes and failures (22 on average when healthy). The budget counts the
credits the gate booked, not calls. A call is booked one credit before it leaves and
the rest (`credits_charged`, measured at 1) after its answer, so a vendor charging N per
call can overshoot a 7-day window by at most N−1 — its last call. That overshoot is NOT
paid back the following week: the window and the kept answers both expire after 7 days,
so a healthy business can overshoot in every window — at most 5 windows, i.e. 5×(N−1)
extra in a 31-day month.

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
#: A business with a weekly booking inside this window is not attempted again.
RETRY_AFTER = timedelta(hours=24)
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


class ReadLog(Protocol):
    def attempted_since(self, tenant_id: UUID, since: datetime) -> bool:
        """Whether this business booked a weekly read at or after `since` (any attempt,
        failed or not: the gate books before the request leaves)."""
        ...

    def credits_since(self, tenant_id: UUID, since: datetime) -> int:
        """The `hashtag_weekly` credits this business booked at or after `since` — every
        booking, kept answer or failure, `:extra` rows included."""
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

    def attempted_since(self, tenant_id: UUID, since: datetime) -> bool:
        return any(
            e.feature == FEATURE_HASHTAG_WEEKLY
            and e.created_at is not None
            and e.created_at >= since
            for e in self.usage_store.of(tenant_id)
        )

    def credits_since(self, tenant_id: UUID, since: datetime) -> int:
        return sum(
            e.credits
            for e in self.usage_store.of(tenant_id)
            if e.feature == FEATURE_HASHTAG_WEEKLY
            and e.created_at is not None
            and e.created_at >= since
        )

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


_ATTEMPTED = text(
    """
    SELECT EXISTS (
        SELECT 1 FROM vendor_usage_events
        WHERE tenant_id = :tenant AND vendor = :vendor AND feature = :feature
          AND created_at >= :since
    )
    """
)
_CREDITS = text(
    """
    SELECT COALESCE(SUM(credits), 0) FROM vendor_usage_events
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

    def attempted_since(self, tenant_id: UUID, since: datetime) -> bool:
        with tenant_session(tenant_id) as session:
            return bool(
                session.execute(
                    _ATTEMPTED,
                    {
                        "tenant": tenant_id,
                        "vendor": usage.SCRAPECREATORS,
                        "feature": FEATURE_HASHTAG_WEEKLY,
                        "since": since,
                    },
                ).scalar_one()
            )

    def credits_since(self, tenant_id: UUID, since: datetime) -> int:
        with tenant_session(tenant_id) as session:
            return int(
                session.execute(
                    _CREDITS,
                    {
                        "tenant": tenant_id,
                        "vendor": usage.SCRAPECREATORS,
                        "feature": FEATURE_HASHTAG_WEEKLY,
                        "since": since,
                    },
                ).scalar_one()
            )

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
TRIED_TODAY = "tried_today"  # a weekly booking in the last 24 h
NO_HEADROOM = "no_headroom"
WEEK_SPENT = "week_spent"  # `MAX_TAGS` weekly credits booked in the last 7 days
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
    """Read `pending` until `MAX_TAGS` credits are booked in the last 7 days: each
    hashtag under its own claim (`claim_tag`), re-checked inside it — a pass for another
    business may have kept it in the meantime — so two businesses sharing a hashtag never
    both pay for it. `should_stop` is asked before each hashtag: when it says so, the
    rest wait for a later pass (`reason=STOPPING`).

    What counts is what the gate BOOKED — its first credit and the `:extra` row of what
    the vendor reports beyond it (`credits_charged`) — re-read from the ledger before
    each read, never a count of calls: with an N-credit call the week overshoots
    `MAX_TAGS` by at most N−1."""
    tenant = rubro.tenant_id
    usage.bind(client, usage.UsageCharge(tenant, rubro.brand_id))
    week = now - REREAD_AFTER
    for tag in pending:
        if should_stop is not None and should_stop():
            outcome.reason = STOPPING
            return
        if log.credits_since(tenant, week) >= MAX_TAGS:
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
    """One paid read of `tag`; False when the pass must stop (a refusal, a failure)."""
    tenant = rubro.tenant_id
    params = {"hashtag": tag}
    if rubro.country_code:
        params["region"] = rubro.country_code
    status = 200
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
            return False
        payload, status = {}, 404
    credits = _int(payload.get("credits_charged")) or (1 if status == 200 else 0)
    try:
        log.keep(tenant, params, payload, status=status, credits=credits, now=now)
    except Exception as exc:  # noqa: BLE001 - the credit is spent; retried tomorrow
        logger.warning("hashtags.weekly answer not kept tenant=%s: %s", tenant, exc)
        outcome.errors += 1
        outcome.status = FAILED
        return False
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
        if log.attempted_since(tenant, now - RETRY_AFTER):
            outcome.status = TRIED_TODAY
            return outcome
        if log.credits_since(tenant, week) >= MAX_TAGS:
            outcome.status = WEEK_SPENT
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
            logger.warning("hashtags.weekly rubro unreadable tenant=%s: %s", tenant, exc)
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
            logger.warning("hashtags.weekly business failed tenant=%s: %s", tenant, exc)
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
    "active_tenants",
    "business_rubro",
    "has_headroom",
    "parse_videos",
    "read_business",
    "readable_tag",
    "rubro_tags",
    "run_tick",
    "switch_on",
]

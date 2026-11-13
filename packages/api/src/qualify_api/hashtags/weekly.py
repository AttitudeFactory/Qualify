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
five. A business without pills is not read: Qualify never guesses a rubro to pay for.

**Who pays, and how often** (ADR 42). Every read goes through the metered gate
(`vendors.scrapecreators.metered_get`), charged to the business it was read for under
the feature `hashtag_weekly` — its 150/600 caps, the 500-credit floor, the kill switch
and the 402 stop all apply. Two rules keep it to «once a week, never twice»:

- **per business:** a business with a `hashtag_weekly` booking in the last
  `REREAD_AFTER` is skipped whole. The booking is written before the request leaves, so
  a re-run — or a run after a crash mid-way — charges nothing again that week (the price
  of a crash is the rest of that week's tags, never a second charge);
- **per hashtag, across businesses:** a hashtag whose answer is already in
  `vendor_payloads` (0036) from the last `REREAD_AFTER`, for any region and whoever
  asked — another business's weekly read or a referentes search page — is not read
  again. That table holds no tenant, so the shared answer never says who triggered it.

**Switch.** `QUALIFY_HASHTAG_WEEKLY_READ` is OFF unless set to 1/true/on/yes: with it
off a tick reads nothing at all — no database, no vendor. The gate's own
`QUALIFY_SCRAPECREATORS_PAID` still stops every paid read when it is off.

**What is kept.** The vendor's raw answer, whole, in `vendor_payloads` (keyed by path and
the call's parameters, upserted: the newest read of the same parameters replaces the
older one) — `parse_videos` re-reads it at any time without paying. The sightings carry
`source='hashtag_weekly'`, `source_ref='tiktok:hashtag_weekly'` (the kind of read, never
the hashtag nor the business) and `parser_version=PARSER_VERSION`; the post id is the
source id.

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
from collections.abc import Callable, Mapping, Sequence
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
    normalize_tag,
)
from qualify_api.vendors import usage
from qualify_api.vendors.scrapecreators import (
    _TIMEOUT_SECONDS,
    FEATURE_HASHTAG_WEEKLY,
    ScrapeCreatorsBlocked,
    ScrapeCreatorsError,
    metered_get,
)

logger = logging.getLogger(__name__)

#: The switch: OFF unless one of `_SWITCH_ON` (D1: «todo se apaga con un interruptor»).
SWITCH_ENV = "QUALIFY_HASHTAG_WEEKLY_READ"
_SWITCH_ON = frozenset({"1", "true", "on", "yes"})

PATH = "/v1/tiktok/search/hashtag"
#: At most this many of a business's rubro hashtags per week (D1: 5 × 1 × 4.3 ≈ 22 credits
#: a month per business).
MAX_TAGS = 5
#: A business, or a hashtag, read inside this window is not read again.
REREAD_AFTER = timedelta(days=7)
#: Only videos posted inside this window count — the same 90 days «popular» sums.
WINDOW_DAYS = POPULAR_WINDOW_DAYS
LANGUAGE = "es"

SOURCE = "hashtag_weekly"
SOURCE_REF = "tiktok:hashtag_weekly"
#: Bump when `parse_videos` changes what a sighting means.
PARSER_VERSION = "tiktok-hashtag-weekly/1"

_HASHTAG_IN_TEXT = re.compile(r"#(\w+)")
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
    """What the weekly read needs of one business: its rubro hashtags (normalized, in the
    owner's order, at most `MAX_TAGS`), the country sent as the proxy `region`, and the
    brand the credits are booked under."""

    tenant_id: UUID
    tags: tuple[str, ...]
    country_code: str | None = None
    brand_id: UUID | None = None


def rubro_tags(connect: Mapping[str, Any] | None, *, limit: int = MAX_TAGS) -> tuple[str, ...]:
    """The pills of «Tu rubro y ubicación» (`connect.hashtags`: `[{"tag": ..., ...}]`),
    normalized and deduplicated in order; a malformed pill is skipped."""
    out: list[str] = []
    pills = (connect or {}).get("hashtags")
    for pill in pills if isinstance(pills, list) else ():
        raw = pill.get("tag") if isinstance(pill, Mapping) else None
        if not isinstance(raw, str):
            continue
        try:
            tag = normalize_tag(raw)
        except ValueError:
            continue
        if tag not in out:
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
    def businesses(self, tenant_ids: Sequence[UUID] | None) -> list[UUID]:
        """`tenant_ids` as given (deduplicated), or every business when None."""
        ...

    def rubro(self, tenant_id: UUID) -> BusinessRubro: ...


class ReadLog(Protocol):
    def business_read_since(self, tenant_id: UUID, since: datetime) -> bool:
        """Whether this business booked a weekly read at or after `since`."""
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


@dataclass
class MemoryRubroSource:
    rubros: dict[UUID, BusinessRubro] = field(default_factory=dict)
    #: How many times a business's rubro was read (the switch-off test counts on 0).
    reads: int = 0

    def businesses(self, tenant_ids: Sequence[UUID] | None) -> list[UUID]:
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
    gate's ledger in tests), so «already read this week» is asked of the same rows the
    gate wrote; the hashtag side is the pool of kept answers, keyed like
    `vendor_payloads` (one row per path + parameters, newest wins)."""

    usage_store: usage.InMemoryUsageStore
    answers: dict[str, KeptAnswer] = field(default_factory=dict)

    def business_read_since(self, tenant_id: UUID, since: datetime) -> bool:
        return any(
            e.feature == FEATURE_HASHTAG_WEEKLY
            and e.created_at is not None
            and e.created_at >= since
            for e in self.usage_store.of(tenant_id)
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


_BUSINESS_READ = text(
    """
    SELECT EXISTS (
        SELECT 1 FROM vendor_usage_events
        WHERE tenant_id = :tenant AND vendor = :vendor AND feature = :feature
          AND created_at >= :since
    )
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

    def business_read_since(self, tenant_id: UUID, since: datetime) -> bool:
        with tenant_session(tenant_id) as session:
            return bool(
                session.execute(
                    _BUSINESS_READ,
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
    """Production: the business ids through `admin_session` (ids only, the media
    worker's discovery), everything about a business through `tenant_session`."""

    def businesses(self, tenant_ids: Sequence[UUID] | None) -> list[UUID]:
        if tenant_ids is not None:
            return list(dict.fromkeys(tenant_ids))
        from qualify_shared.db.admin import admin_session  # noqa: PLC0415 - production only

        with admin_session() as session:
            return list(session.scalars(text("SELECT id FROM tenants ORDER BY id")))

    def rubro(self, tenant_id: UUID) -> BusinessRubro:
        with tenant_session(tenant_id) as session:
            rows = session.execute(_DETAILS, {"tenant": tenant_id}).all()
            country = session.execute(_TENANT_COUNTRY, {"tenant": tenant_id}).scalar_one_or_none()
        return business_rubro(tenant_id, [(r.brand_id, r.connect) for r in rows], country)


# --------------------------------------------------------------------------------------
# the tick
# --------------------------------------------------------------------------------------

#: `BusinessOutcome.status`
NO_TAGS = "no_tags"
READ_THIS_WEEK = "read_this_week"
DONE = "done"
CAPPED = "capped"
BLOCKED = "blocked"


@dataclass
class BusinessOutcome:
    tenant_id: UUID
    status: str
    #: Hashtags read (paid) and skipped because someone read them this week (free).
    read: list[str] = field(default_factory=list)
    shared: list[str] = field(default_factory=list)
    sightings: int = 0
    errors: int = 0
    reason: str | None = None


@dataclass
class TickReport:
    outcomes: list[BusinessOutcome] = field(default_factory=list)
    #: Why the tick read nothing or stopped early (`switch_off`, a global gate refusal).
    stopped: str | None = None

    @property
    def errors(self) -> int:
        return sum(o.errors for o in self.outcomes)


ClientFactory = Callable[[], httpx.Client]


def _default_client() -> httpx.Client:
    return httpx.Client(timeout=_TIMEOUT_SECONDS)


def read_business(
    rubro: BusinessRubro,
    *,
    log: ReadLog,
    repository: HashtagRepository,
    client: httpx.Client,
    now: datetime,
) -> BusinessOutcome:
    """One business's weekly read (the switch is the caller's). Raises nothing: every
    failure is counted on the outcome."""
    tenant = rubro.tenant_id
    if not rubro.tags:
        return BusinessOutcome(tenant, NO_TAGS)
    since = now - REREAD_AFTER
    if log.business_read_since(tenant, since):
        return BusinessOutcome(tenant, READ_THIS_WEEK)
    outcome = BusinessOutcome(tenant, DONE)
    usage.bind(client, usage.UsageCharge(tenant, rubro.brand_id))
    for tag in rubro.tags:
        if log.tag_read_since(tenant, tag, since):
            outcome.shared.append(tag)
            continue
        params = {"hashtag": tag}
        if rubro.country_code:
            params["region"] = rubro.country_code
        status = 200
        try:
            payload: dict[str, Any] = metered_get(
                client, PATH, params, feature=FEATURE_HASHTAG_WEEKLY
            )
        except ScrapeCreatorsBlocked as exc:
            outcome.reason = exc.reason
            outcome.status = CAPPED if exc.reason in usage.CAP_REASONS else BLOCKED
            break
        except ScrapeCreatorsError as exc:
            if exc.status_code != 404:  # 404 = nothing indexed: an answer, kept as one
                logger.warning("hashtags.weekly read failed tenant=%s: %s", tenant, exc)
                outcome.errors += 1
                continue
            payload, status = {}, 404
        outcome.read.append(tag)
        credits = _int(payload.get("credits_charged")) or (1 if status == 200 else 0)
        try:
            log.keep(tenant, params, payload, status=status, credits=credits, now=now)
        except Exception as exc:  # noqa: BLE001 - the credit is spent; the rest still runs
            logger.warning("hashtags.weekly answer not kept tenant=%s: %s", tenant, exc)
            outcome.errors += 1
        sightings = parse_videos(tag, payload, now=now)
        if not sightings:
            continue
        try:
            outcome.sightings += repository.record_post_sightings(tenant, sightings)
        except Exception as exc:  # noqa: BLE001 - the raw answer is kept for a re-parse
            logger.warning("hashtags.weekly sightings not stored tenant=%s: %s", tenant, exc)
            outcome.errors += 1
    return outcome


def run_tick(
    tenant_ids: Sequence[UUID] | None,
    *,
    source: RubroSource | None = None,
    log: ReadLog | None = None,
    repository: HashtagRepository | None = None,
    client_factory: ClientFactory = _default_client,
    now: datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> TickReport:
    """One pass over `tenant_ids` (None = every business: production only). With the
    switch off it returns at once — no database read, no vendor call."""
    if not switch_on(env):
        logger.info("hashtags.weekly off (%s is not set)", SWITCH_ENV)
        return TickReport(stopped="switch_off")
    if tenant_ids is not None and not tenant_ids:
        raise ValueError("an explicit scope needs at least one tenant")
    source = source or PostgresRubroSource()
    log = log or PostgresReadLog()
    repository = repository or PostgresHashtagRepository()
    moment = now or datetime.now(UTC)
    report = TickReport()
    for tenant in source.businesses(tenant_ids):
        try:
            rubro = source.rubro(tenant)
        except Exception as exc:  # noqa: BLE001 - one business never stops the others
            logger.warning("hashtags.weekly rubro unreadable tenant=%s: %s", tenant, exc)
            report.outcomes.append(BusinessOutcome(tenant, DONE, errors=1))
            continue
        client = client_factory()
        try:
            outcome = read_business(
                rubro, log=log, repository=repository, client=client, now=moment
            )
        except Exception as exc:  # noqa: BLE001 - e.g. the ledger is unreadable
            logger.warning("hashtags.weekly business failed tenant=%s: %s", tenant, exc)
            outcome = BusinessOutcome(tenant, DONE, errors=1)
        finally:
            client.close()
        report.outcomes.append(outcome)
        logger.info(
            "hashtags.weekly tenant=%s status=%s read=%d shared=%d sightings=%d errors=%d "
            "reason=%s",
            tenant,
            outcome.status,
            len(outcome.read),
            len(outcome.shared),
            outcome.sightings,
            outcome.errors,
            outcome.reason,
        )
        if outcome.status == BLOCKED and outcome.reason in _GLOBAL_BLOCKS:
            report.stopped = outcome.reason
            break
    return report


__all__ = [
    "LANGUAGE",
    "MAX_TAGS",
    "PARSER_VERSION",
    "PATH",
    "REREAD_AFTER",
    "SOURCE",
    "SOURCE_REF",
    "SWITCH_ENV",
    "WINDOW_DAYS",
    "BusinessOutcome",
    "BusinessRubro",
    "MemoryReadLog",
    "MemoryRubroSource",
    "PostgresReadLog",
    "PostgresRubroSource",
    "ReadLog",
    "RubroSource",
    "TickReport",
    "business_rubro",
    "parse_videos",
    "read_business",
    "rubro_tags",
    "run_tick",
    "switch_on",
]

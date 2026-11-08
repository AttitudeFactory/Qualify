"""The one paid read of the Creators module: «Actualizar» a creator (m-24946121,
`docs/diseno-modulo-creadores.md` §8.3).

`refresh_creator` reads the creator's profile and latest `REELS_TARGET` reels through the
metered gate (`vendors.scrapecreators`, ≤ `SNAPSHOT_MAX_CREDITS` credits) and keeps the
read as a global `creator_snapshots` row with its `public_reel_reads`. Guarantees:

- **Shared 24 h freshness (0 credits):** a read of the same account younger than
  `FRESH_FOR`, by any business, is linked instead of paid again.
- **Per-business caps:** every paid call is booked by the metered gate itself, charged to
  this business (`usage.charge_to`, ADR 42 R5: 150 credits a day / 600 a month over all
  its ScrapeCreators reads, in its own zone). Inside that, the Creators module keeps its
  own budget: `CREATOR_DAY_CAP` / `CREATOR_MONTH_CAP` over `creator_profile` +
  `creator_reels` (`usage.store().spent(features=...)`). Under `SNAPSHOT_MAX_CREDITS`
  left — or the gate refusing for the business's cap — = `cap_reached`.
- **Uncapped businesses** (founder decision, 2026-11-05, m-24956180): a business whose
  Meegle Alta says «Lecturas sin límite: Sí» (`vendors.uncapped`) skips the Creators
  budget here and the business cap in the gate; every credit is still booked in
  `vendor_usage_events`.
- **One read per account at a time:** the `reel_accounts` lock «Ideas para tus reels»
  uses too; a second caller waits up to `LOCK_WAIT_SECONDS`, then re-checks freshness.
- **Every paid answer is kept:** its raw body goes to `vendor_payloads` right after the
  call, before the next one — the provenance of the snapshot and of each reel read.
- **A failed read never replaces the last good one:** `last_snapshot_id` moves only when
  the read is saved (one transaction, `TrackedCreatorStore.save_read`).

No worker: the screen calls this from a Reflex background event (founder's decision for
delivery 1: manual «Actualizar»).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

import httpx

from qualify_api.creators.repository import CachedPayload, CreatorFacts
from qualify_api.creators.tracking import (
    REFRESH_FAILED,
    REFRESH_OK,
    REFRESH_READING,
    REFRESH_STUCK_AFTER,
    SNAPSHOT_ERROR,
    SNAPSHOT_MISSING,
    SNAPSHOT_OK,
    SNAPSHOT_PARTIAL,
    SNAPSHOT_PRIVATE,
    SNAPSHOT_SETTLED,
    SNAPSHOT_WITH_DATA,
    TRACKED_ACTIVE,
    NewReelRead,
    NewSnapshot,
    TrackedCreator,
    TrackedCreatorStore,
)
from qualify_api.referentes.reel_store import (
    ACCOUNT_ERROR,
    ACCOUNT_MISSING,
    ACCOUNT_OK,
    ACCOUNT_PRIVATE,
    PublicReel,
)
from qualify_api.vendors import scrapecreators, uncapped, usage

logger = logging.getLogger(__name__)

#: Reels one read keeps (4 Instagram pages of 12).
REELS_TARGET = 48
#: 1 profile + 4 pages: the most one read can cost.
SNAPSHOT_MAX_CREDITS = 5
#: Per-business caps over the creators' two features (design §8.4; founder question §17.1).
CREATOR_DAY_CAP = 50
CREATOR_MONTH_CAP = 300
CREATOR_FEATURES = (
    scrapecreators.FEATURE_CREATOR_PROFILE,
    scrapecreators.FEATURE_CREATOR_REELS,
)
#: A read younger than this serves every business for free.
FRESH_FOR = timedelta(hours=24)
#: How long a read holds the account's lock (`reel_accounts.refresh_lock_until`): five
#: calls of at most ~20 s each, with room to spare. A crashed read frees it by itself.
LOCK_SECONDS = int(REFRESH_STUCK_AFTER.total_seconds())
LOCK_WAIT_SECONDS = 30.0
LOCK_POLL_SECONDS = 2.0

RefreshStatus = Literal[
    "read",  # read now (credits > 0)
    "fresh",  # a read younger than 24 h existed: 0 credits
    "busy",  # another read of the same account is running: retry in a few seconds
    "cap_reached",  # the business's cap: «Mañana puedes actualizar otra vez»
    "blocked",  # the gate did not call (switch, global floor, 402)
    "missing",  # the account does not exist
    "private",  # the account is private: its reels are not read
    "error",  # the network or the vendor failed; the last good read stays
]


@dataclass(frozen=True)
class RefreshOutcome:
    status: RefreshStatus
    snapshot_id: UUID | None  # the creator's current read after the call
    credits: int  # for the log and the tests; the screen NEVER shows it
    partial: bool  # fewer pages were read than planned


class CreatorNotFound(LookupError):
    """No such creator for this brand (or it is archived, for a refresh)."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _credits_of(payload: dict[str, Any]) -> int:
    """What the vendor says the call cost (`credits_charged`); 1 when it does not say."""
    value = payload.get("credits_charged")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 1


def _utc(stamp: float) -> datetime:
    return datetime.fromtimestamp(float(stamp), tz=UTC)


@dataclass
class _Read:
    """What one read has gathered so far (the bookkeeping of the paid calls)."""

    snapshot_id: UUID
    credits: int = 0
    pages: int = 0
    http_status: int | None = None


def _should_link(
    store: TrackedCreatorStore, tenant_id: UUID, tracked: TrackedCreator, status: str
) -> bool:
    """A read with figures always becomes the current one; a private/missing one only
    replaces nothing, or another private/missing one — never the last good read."""
    if status == SNAPSHOT_ERROR:
        return False  # a read with no figures in it never becomes the current one
    if status in SNAPSHOT_WITH_DATA or tracked.last_snapshot_id is None:
        return True
    current = store.snapshots(tenant_id, [tracked.last_snapshot_id]).get(tracked.last_snapshot_id)
    return current is None or current.status not in SNAPSHOT_WITH_DATA


def _settled_outcome(
    status: str, snapshot_id: UUID, credits: int, *, fresh: bool
) -> RefreshOutcome:
    if status == SNAPSHOT_PRIVATE:
        return RefreshOutcome("private", snapshot_id, credits, False)
    if status == SNAPSHOT_MISSING:
        return RefreshOutcome("missing", snapshot_id, credits, False)
    return RefreshOutcome(
        "fresh" if fresh else "read", snapshot_id, credits, status == SNAPSHOT_PARTIAL
    )


def _use_fresh(
    store: TrackedCreatorStore,
    tenant_id: UUID,
    brand_id: UUID,
    tracked: TrackedCreator,
    snapshot_id: UUID,
    status: str,
    now: datetime,
) -> RefreshOutcome:
    link = _should_link(store, tenant_id, tracked, status)
    with_data = status in SNAPSHOT_WITH_DATA
    store.mark(
        tenant_id,
        brand_id,
        tracked.id,
        state=REFRESH_OK if with_data else REFRESH_FAILED,
        error=None if with_data else status,
        now=now,
        snapshot_id=snapshot_id if link else None,
    )
    current = snapshot_id if link else tracked.last_snapshot_id
    return _settled_outcome(status, current or snapshot_id, 0, fresh=True)


def _fail(
    store: TrackedCreatorStore,
    tenant_id: UUID,
    brand_id: UUID,
    tracked: TrackedCreator,
    status: RefreshStatus,
    now: datetime,
    credits: int = 0,
) -> RefreshOutcome:
    store.mark(tenant_id, brand_id, tracked.id, state=REFRESH_FAILED, error=status, now=now)
    return RefreshOutcome(status, tracked.last_snapshot_id, credits, False)


def refresh_creator(
    tenant_id: UUID,
    brand_id: UUID,
    tracked_id: UUID,
    *,
    store: TrackedCreatorStore,
    now: datetime | None = None,
    client: httpx.Client | None = None,
    clock: Callable[[], datetime] = _utc_now,
    sleep: Callable[[float], None] = time.sleep,
    snapshot_id: UUID | None = None,
    lock_wait_seconds: float = LOCK_WAIT_SECONDS,
    poll_seconds: float = LOCK_POLL_SECONDS,
) -> RefreshOutcome:
    """Read the creator now, or link a fresh read, or say why not (design §8.3). Every
    paid call of the read is charged to this business (R5: the gate books it)."""
    with usage.charge_to(tenant_id, brand_id):
        return _refresh(
            tenant_id,
            brand_id,
            tracked_id,
            store=store,
            now=now,
            client=client,
            clock=clock,
            sleep=sleep,
            snapshot_id=snapshot_id,
            lock_wait_seconds=lock_wait_seconds,
            poll_seconds=poll_seconds,
        )


def _refresh(
    tenant_id: UUID,
    brand_id: UUID,
    tracked_id: UUID,
    *,
    store: TrackedCreatorStore,
    now: datetime | None = None,
    client: httpx.Client | None = None,
    clock: Callable[[], datetime] = _utc_now,
    sleep: Callable[[float], None] = time.sleep,
    snapshot_id: UUID | None = None,
    lock_wait_seconds: float = LOCK_WAIT_SECONDS,
    poll_seconds: float = LOCK_POLL_SECONDS,
) -> RefreshOutcome:
    """Read the creator now, or link a fresh read, or say why not (design §8.3). The
    caller (`service.refresh_creator`) has checked the module switch. `snapshot_id` pins
    the read's id (tests); a new one by default.
    Raises `CreatorNotFound` when the creator is not this brand's or is archived."""
    started = now or clock()
    tracked = store.get(tenant_id, brand_id, tracked_id)
    if tracked is None or tracked.status != TRACKED_ACTIVE:
        raise CreatorNotFound(str(tracked_id))
    network, handle = tracked.network, tracked.handle

    def fresh_read(at: datetime) -> RefreshOutcome | None:
        found = store.latest_snapshot(
            tenant_id, network, handle, since=at - FRESH_FOR, statuses=SNAPSHOT_SETTLED
        )
        if found is None:
            return None
        return _use_fresh(store, tenant_id, brand_id, tracked, found.snapshot_id, found.status, at)

    # 2. freshness, shared by every business (0 credits)
    outcome = fresh_read(started)
    if outcome is not None:
        return outcome
    # 3. the module's budget inside the business's cap (the gate enforces the cap itself);
    # an uncapped business (m-24956180) has neither: the gate still books every credit
    if not uncapped.is_uncapped(tenant_id):
        try:
            spent = usage.store().spent(
                tenant_id, usage.SCRAPECREATORS, started, features=CREATOR_FEATURES
            )
        except Exception as exc:  # noqa: BLE001 - never pay for what cannot be accounted for
            logger.warning("creators: usage of %s unreadable: %s", tenant_id, type(exc).__name__)
            return _fail(store, tenant_id, brand_id, tracked, "blocked", started)
        left = min(CREATOR_DAY_CAP - spent.day, CREATOR_MONTH_CAP - spent.month)
        if left < SNAPSHOT_MAX_CREDITS:
            return _fail(store, tenant_id, brand_id, tracked, "cap_reached", started)
    # 4. the account's lock
    waited = 0.0
    while True:
        at = clock()
        until = at + timedelta(seconds=LOCK_SECONDS)
        if store.try_lock_account(tenant_id, network, handle, now=at, until=until):
            # re-check under the lock: another business may have just finished it
            outcome = fresh_read(at)
            if outcome is not None:
                store.release_account(tenant_id, network, handle, lock_until=until)
                return outcome
            break
        if waited >= lock_wait_seconds:
            # a read that held it this long: do not queue behind it, never read twice
            return RefreshOutcome("busy", tracked.last_snapshot_id, 0, False)
        sleep(poll_seconds)
        waited += poll_seconds
        outcome = fresh_read(clock())
        if outcome is not None:
            return outcome
    read = _Read(snapshot_id or uuid4())
    account_status: str | None = None
    newest: datetime | None = None
    try:
        account_status, newest, outcome = _read(
            store, tenant_id, brand_id, tracked, read, started, client, clock
        )
        return outcome
    except Exception:  # noqa: BLE001 - never leave the creator «reading» forever
        logger.exception("creators: read %s of %s/%s crashed", read.snapshot_id, network, handle)
        try:
            return _fail(store, tenant_id, brand_id, tracked, "error", clock(), read.credits)
        except Exception:  # noqa: BLE001 - the store is down too; `refresh_stuck` covers it
            logger.exception("creators: could not mark %s failed", tracked.id)
            return RefreshOutcome("error", tracked.last_snapshot_id, read.credits, False)
    finally:
        if account_status is None:
            # nothing was paid (the gate refused, or the read crashed first): free the
            # lock, change nothing about the account
            if read.credits:
                account_status = ACCOUNT_ERROR
            else:
                store.release_account(tenant_id, network, handle, lock_until=until)
        if account_status is not None:
            store.finish_account(
                tenant_id,
                network,
                handle,
                now=clock(),
                status=account_status,
                http_status=read.http_status,
                credits=read.credits,
                newest_taken_at=newest,
                lock_until=until,
            )


def _keep(
    store: TrackedCreatorStore,
    tenant_id: UUID,
    read: _Read,
    *,
    path: str,
    params: dict[str, str],
    payload: dict[str, Any],
    status: int,
    credits: int,
    at: datetime,
) -> CachedPayload:
    """Keep one paid answer (the read's provenance) right after the call. The credit was
    booked by the gate before the call left (R5)."""
    entry = store.put_payload(
        tenant_id, path, params, payload, status=status, credits=credits, now=at
    )
    read.credits += credits
    return entry


def _profile_facts(
    network: str, handle: str, profile: dict[str, Any] | None, at: datetime
) -> CreatorFacts:
    profile = profile or {}
    return CreatorFacts(
        network=network,
        handle=handle,
        full_name=str(profile.get("fullName") or ""),
        bio=str(profile.get("bio") or ""),
        external_url=str(profile.get("externalUrl") or ""),
        profile_url=f"https://www.instagram.com/{handle}/" if network == "instagram" else "",
        avatar_url=str(profile.get("profilePicUrl") or ""),
        category=str(profile.get("category") or ""),
        followers=profile.get("followers") if isinstance(profile.get("followers"), int) else None,
        is_private=profile.get("isPrivate") is True,
        is_verified=profile.get("isVerified") is True,
        missing=not profile,
        read_at=at,
        seen_at=at,
    )


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _read(
    store: TrackedCreatorStore,
    tenant_id: UUID,
    brand_id: UUID,
    tracked: TrackedCreator,
    read: _Read,
    read_at: datetime,
    client: httpx.Client | None,
    clock: Callable[[], datetime],
) -> tuple[str | None, datetime | None, RefreshOutcome]:
    """Steps 5-8, under the lock. Returns `(reel_accounts status or None when nothing
    was paid, newest reel, outcome)`."""
    network, handle = tracked.network, tracked.handle
    store.mark(
        tenant_id,
        brand_id,
        tracked.id,
        state=REFRESH_READING,
        error=None,
        now=read_at,
        started=True,
    )
    profile_path = scrapecreators.PROFILE_PATHS[network]
    profile_params = {"handle": handle}

    def save(
        snapshot: NewSnapshot,
        reads: list[NewReelRead],
        reels: list[PublicReel],
        profile: dict[str, Any] | None,
    ) -> UUID | None:
        """Write the read; the creator's current read afterwards, or None when the write
        failed (the credits are spent: say so, keep the last read)."""
        link = _should_link(store, tenant_id, tracked, snapshot.status)
        with_data = snapshot.status in SNAPSHOT_WITH_DATA
        try:
            store.save_read(
                tenant_id,
                brand_id,
                tracked.id,
                snapshot=snapshot,
                reads=reads,
                reels=reels,
                creator=_profile_facts(network, handle, profile, read_at),
                link=link,
                state=REFRESH_OK if with_data else REFRESH_FAILED,
                error=None if with_data else snapshot.status,
                now=clock(),
            )
        except Exception:  # noqa: BLE001 - the credits are spent; say so, keep the last read
            logger.exception(
                "creators: read %s of %s/%s not saved", read.snapshot_id, network, handle
            )
            return None
        return snapshot.id if link else tracked.last_snapshot_id

    base = {
        "id": read.snapshot_id,
        "network": network,
        "handle": handle,
        "read_at": read_at,
        "parser_version": scrapecreators.REEL_PARSER_VERSION,
        "reels_target": REELS_TARGET,
    }

    # 6. the profile (1 credit)
    try:
        raw, profile = scrapecreators.fetch_profile_raw(
            network, handle, feature=scrapecreators.FEATURE_CREATOR_PROFILE, client=client
        )
    except scrapecreators.ScrapeCreatorsBlocked as exc:
        logger.warning("creators: %s/%s refused by the gate: %s", network, handle, exc.reason)
        refused: RefreshStatus = "cap_reached" if exc.reason in usage.CAP_REASONS else "blocked"
        return None, None, _fail(store, tenant_id, brand_id, tracked, refused, clock())
    except scrapecreators.ScrapeCreatorsError as exc:
        read.http_status = exc.status_code
        if exc.status_code != 404:
            # the call left (the gate booked its credit): an unusable answer is still paid
            read.credits += 1
            logger.warning("creators: profile of %s/%s unreadable: %s", network, handle, exc)
            return (
                ACCOUNT_ERROR,
                None,
                _fail(store, tenant_id, brand_id, tracked, "error", clock(), read.credits),
            )
        entry = _keep(
            store,
            tenant_id,
            read,
            path=profile_path,
            params=profile_params,
            payload={},
            status=404,
            credits=1,
            at=clock(),
        )
        snapshot = NewSnapshot(
            **base,
            status=SNAPSHOT_MISSING,
            credits=read.credits,
            profile_payload_id=entry.id,
            profile_payload_fetched_at=entry.fetched_at,
        )
        current = save(snapshot, [], [], None)
        if current is None:
            return (
                ACCOUNT_MISSING,
                None,
                _fail(store, tenant_id, brand_id, tracked, "error", clock(), read.credits),
            )
        return (
            ACCOUNT_MISSING,
            None,
            _settled_outcome(SNAPSHOT_MISSING, current, read.credits, fresh=False),
        )
    except ValueError as exc:
        logger.warning("creators: profile of %s/%s unreadable: %s", network, handle, exc)
        return None, None, _fail(store, tenant_id, brand_id, tracked, "error", clock())
    profile_entry = _keep(
        store,
        tenant_id,
        read,
        path=profile_path,
        params=profile_params,
        payload=raw,
        status=200,
        credits=_credits_of(raw),
        at=clock(),
    )
    profile_fields = {
        "followers": _int(profile.get("followers")),
        "following": _int(profile.get("following")),
        "posts_count": _int(profile.get("postsCount")),
        "full_name": str(profile.get("fullName") or ""),
        "bio": str(profile.get("bio") or ""),
        "category": str(profile.get("category") or ""),
        "external_url": str(profile.get("externalUrl") or ""),
        "avatar_url": str(profile.get("profilePicUrl") or ""),
        "is_verified": profile.get("isVerified") is True,
        "is_private": profile.get("isPrivate") is True,
        "profile_payload_id": profile_entry.id,
        "profile_payload_fetched_at": profile_entry.fetched_at,
    }
    if profile_fields["is_private"]:
        snapshot = NewSnapshot(
            **base, **profile_fields, status=SNAPSHOT_PRIVATE, credits=read.credits
        )
        current = save(snapshot, [], [], profile)
        if current is None:
            return (
                ACCOUNT_PRIVATE,
                None,
                _fail(store, tenant_id, brand_id, tracked, "error", clock(), read.credits),
            )
        return (
            ACCOUNT_PRIVATE,
            None,
            _settled_outcome(SNAPSHOT_PRIVATE, current, read.credits, fresh=False),
        )

    # 7. the reels (up to 4 credits), each page kept before the next is asked for
    pages: list[tuple[scrapecreators.ReelPage, CachedPayload, datetime]] = []

    def on_page(page: scrapecreators.ReelPage) -> None:
        at = clock()
        read.pages += 1
        entry = _keep(
            store,
            tenant_id,
            read,
            path=page.path,
            params=page.params,
            payload=page.payload,
            status=200,
            credits=_credits_of(page.payload),
            at=at,
        )
        pages.append((page, entry, at))

    partial = False
    try:
        scrapecreators.fetch_reel_pages(
            network,
            handle,
            max_reels=REELS_TARGET,
            feature=scrapecreators.FEATURE_CREATOR_REELS,
            client=client,
            on_page=on_page,
        )
    except (scrapecreators.ScrapeCreatorsError, ValueError) as exc:
        # ScrapeCreatorsBlocked included: what was paid so far is kept
        partial = True
        if isinstance(exc, scrapecreators.ScrapeCreatorsError) and not isinstance(
            exc, scrapecreators.ScrapeCreatorsBlocked
        ):
            read.credits += 1  # the failed page left the process: the gate booked it
        logger.warning(
            "creators: reels of %s/%s stopped after %d page(s): %s",
            network,
            handle,
            read.pages,
            exc,
        )

    # 8. one transaction
    reads: list[NewReelRead] = []
    reels: list[PublicReel] = []
    for page, entry, at in pages:
        for reel in page.reels:
            taken_at = _utc(reel["takenAt"])
            seconds = reel.get("seconds")
            coauthors = reel.get("coauthors")
            reads.append(
                NewReelRead(
                    snapshot_id=read.snapshot_id,
                    network=network,
                    reel_id=str(reel["id"]),
                    position=len(reads) + 1,
                    taken_at=taken_at,
                    parser_version=scrapecreators.REEL_PARSER_VERSION,
                    views=reel.get("views"),
                    likes=reel.get("likes"),
                    comments=reel.get("comments"),
                    saves=reel.get("saves"),
                    shares=reel.get("shares"),
                    source_payload_id=entry.id,
                    source_payload_fetched_at=entry.fetched_at,
                )
            )
            reels.append(
                PublicReel(
                    network=network,
                    reel_id=str(reel["id"]),
                    handle=handle,
                    taken_at=taken_at,
                    metrics_at=at,
                    parser_version=scrapecreators.REEL_PARSER_VERSION,
                    caption=str(reel.get("caption") or ""),
                    duration_s=float(seconds) if isinstance(seconds, (int, float)) else None,
                    sound=str(reel.get("sound") or ""),
                    views=reel.get("views"),
                    likes=reel.get("likes"),
                    comments=reel.get("comments"),
                    saves=reel.get("saves"),
                    shares=reel.get("shares"),
                    video_url=str(reel.get("video") or "") or None,
                    # R12 (0127): the cover's URL too, upserted by the same rule
                    cover_url=str(reel.get("cover") or "") or None,
                    is_paid_partnership=reel.get("paidPartnership") is True,
                    coauthors=tuple(coauthors) if isinstance(coauthors, list) else None,
                    sound_id=str(reel["soundId"]) if reel.get("soundId") else None,
                    sound_is_original=reel.get("soundIsOriginal")
                    if isinstance(reel.get("soundIsOriginal"), bool)
                    else None,
                    counts_hidden=reel.get("countsHidden") is True,
                    source_payload_id=entry.id,
                    source_payload_fetched_at=entry.fetched_at,
                )
            )
    stamps = [r.taken_at for r in reads]
    newest = max(stamps) if stamps else None
    # A read whose reel list failed before any reel came back has no figures: it is
    # saved (the credits are spent, it is provenance) as `error` — never linked as the
    # current read, never served as fresh to anyone (review 2026-11-04).
    if partial and not reads:
        status = SNAPSHOT_ERROR
    else:
        status = SNAPSHOT_PARTIAL if partial else SNAPSHOT_OK
    snapshot = NewSnapshot(
        **base,
        **profile_fields,
        status=status,
        reels_read=len(reads),
        pages_read=read.pages,
        oldest_taken_at=min(stamps) if stamps else None,
        newest_taken_at=newest,
        credits=read.credits,
    )
    if status == SNAPSHOT_ERROR:
        save(snapshot, reads, reels, profile)  # not linked (`_should_link`)
        return (
            ACCOUNT_ERROR,
            None,
            _fail(store, tenant_id, brand_id, tracked, "error", clock(), read.credits),
        )
    if save(snapshot, reads, reels, profile) is None:
        return (
            ACCOUNT_ERROR,
            newest,
            _fail(store, tenant_id, brand_id, tracked, "error", clock(), read.credits),
        )
    return ACCOUNT_OK, newest, RefreshOutcome("read", read.snapshot_id, read.credits, partial)


__all__ = [
    "CREATOR_DAY_CAP",
    "CREATOR_FEATURES",
    "CREATOR_MONTH_CAP",
    "FRESH_FOR",
    "REELS_TARGET",
    "SNAPSHOT_MAX_CREDITS",
    "CreatorNotFound",
    "RefreshOutcome",
    "RefreshStatus",
    "refresh_creator",
]

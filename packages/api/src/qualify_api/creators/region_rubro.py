"""Region and rubro of each public account, free sources first (RF-04, m-25119461).

The Región and Nicho filters of the reel-filter epic (m-24872324,
`docs/epica-filtrado-reels.md`) need a country and a rubro per account. They live on the
GLOBAL `creators` row (0182: public data of the network, no tenant — see that revision's
docstring), each value with its provenance: source, source ref, version, time (and the
model, for the rubro).

## Region — FREE SOURCES ONLY, best first

Deivid, 2026-11-25: the country comes only from free sources. The account review's
`pais` was measured (REFERENTES-RUBRO-001, `docs/modelos-generativos/pruebas.md`) at a
precision of 0.815 / 0.827 against the 0.95 bar — the model writes the brand's country,
the language's or what it already knows — so it is never stored. A country by AI goes to
a new ticket (prompt `referentes-review-3`, with the evidence checked in code).

1. `profile` — the network's own country already on the row (`creators.country_code`:
   TikTok's `region` on a feed author, an Instagram business address).
2. `tiktok_region` — the `region` TikTok returns WITH EACH VIDEO in answers the pool
   already keeps (`vendor_payloads`: keyword and hashtag searches, the reel lists of
   `/v3/tiktok/profile/videos`, a `user.region` in a profile read if it ever comes). Measured
   on the local base 2026-11-25: 3 624 of 3 624 keyword-search videos carry it at
   `search_item_list[].aweme_info.region` — and 0 at `author.region`, which is where
   `Qualify/creator_discovery._tiktok_author` looks, so `creators.country_code` stays
   empty for TikTok (5 of 3 453 rows).
3. `reel_location` — the country of the place an Instagram reel was tagged at
   (`items[].media.location.address_json.country_code` of `/v1/instagram/user/reels`,
   the shape `creator_discovery._ig_location_country` reads). [UNVERIFIED LIVE]: no
   reel list is cached on the local base.
4. `sightings` — the country of the searches that surfaced the account
   (`creator_sightings.country_code`): the search's country, not the account's, so an
   approximation (RF-00: 58 of 59 labeled accounts have one) — kept last.

Within one source the most frequent country wins (ties: the latest evidence). Nothing
here calls a vendor or a model: `backfill` only reads what is already stored.

`creator_profile_cache` is NOT a source on purpose: it holds each business's OWN account
(per tenant, RLS), and copying a business's data into the shared pool would cross the
tenant line this module must never cross.

## Rubro

A key of the Brand Kit's rubro catalog (`referentes.discovery_seed.NICHE_LABELS`) or
`otro`, from the account review only (`ai`, prompt `referentes-review-2`, measured at 0.87
on test against a 0.85 bar): no free source carries it — the network's `category` is its
own taxonomy (RF-00), kept apart.

## Idempotency

`apply_region` / `apply_rubro` are single conditional UPDATEs: the same claim twice
changes nothing (not even `*_inferred_at`); a worse source never replaces a better one; an
AI rubro replaces an AI rubro only when the prompt version changed or a real rubro comes
for an account stored as `otro`. A re-run of the
backfill therefore writes zero rows, and never pays: it reads the pool and nothing else.

## Reading (RF-01, RF-02b, RF-07a)

`account_facts(session, keys)` → `AccountFacts` per `(network, handle)`; or, in SQL,
`LEFT JOIN creators c ON (c.network, c.handle) = (x.network, x.handle)` and filter on
`c.region_code` / `c.rubro` (indexed, `ix_creators_region_rubro`).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.orm import Session

from qualify_api.creators.repository import VENDOR, normalize_handle
from qualify_api.referentes.ai import RUBROS, normalize_country

logger = logging.getLogger(__name__)

NETWORKS = ("tiktok", "instagram")

#: Region sources, best first (the order `apply_region` ranks by). All free: no model
#: answer is ever a region source (Deivid, 2026-11-25).
SOURCE_PROFILE = "profile"
SOURCE_TIKTOK_REGION = "tiktok_region"
SOURCE_REEL_LOCATION = "reel_location"
SOURCE_SIGHTINGS = "sightings"
REGION_SOURCES: tuple[str, ...] = (
    SOURCE_PROFILE,
    SOURCE_TIKTOK_REGION,
    SOURCE_REEL_LOCATION,
    SOURCE_SIGHTINGS,
)

#: The pipeline version of a free value (`creators.region_version`). Bump when what a
#: free source reads, or the order, changes.
FREE_PIPELINE_VERSION = "region-free-1"

#: Cached answers that may carry a country: path → source.
REGION_PATHS: dict[str, str] = {
    "/v1/tiktok/search/keyword": SOURCE_TIKTOK_REGION,
    "/v1/tiktok/search/hashtag": SOURCE_TIKTOK_REGION,
    "/v3/tiktok/profile/videos": SOURCE_TIKTOK_REGION,
    "/v1/tiktok/profile": SOURCE_TIKTOK_REGION,
    "/v1/instagram/user/reels": SOURCE_REEL_LOCATION,
}

Key = tuple[str, str]


@dataclass(frozen=True)
class RegionClaim:
    """One account's country according to one free source, with its provenance."""

    network: str
    handle: str
    code: str
    source: str
    source_ref: str = ""
    version: str = FREE_PIPELINE_VERSION

    def __post_init__(self) -> None:
        if self.source not in REGION_SOURCES:
            raise ValueError(f"source must be one of {REGION_SOURCES}, got {self.source!r}")
        code = normalize_country(self.code)
        if not code:
            raise ValueError(f"not a country code: {self.code!r}")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "handle", normalize_handle(self.handle))

    @property
    def key(self) -> Key:
        return (self.network, self.handle)


@dataclass(frozen=True)
class RubroClaim:
    """One account's rubro according to the AI review, with its provenance."""

    network: str
    handle: str
    rubro: str
    model: str
    version: str
    source_ref: str = ""

    def __post_init__(self) -> None:
        if self.rubro not in RUBROS:
            raise ValueError(f"rubro must be one of {RUBROS}, got {self.rubro!r}")
        if not self.model or not self.version:
            raise ValueError("an AI rubro needs its model and prompt version")
        object.__setattr__(self, "handle", normalize_handle(self.handle))

    @property
    def key(self) -> Key:
        return (self.network, self.handle)


@dataclass(frozen=True)
class AccountFacts:
    """What the filters read about one account (RF-01 / RF-02b / RF-07a)."""

    network: str
    handle: str
    region_code: str
    region_source: str
    rubro: str
    rubro_source: str


@dataclass
class BackfillReport:
    accounts: int = 0
    resolved: int = 0
    updated: int = 0
    by_source: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True)
class Coverage:
    """How many of a business's `referente`/`competencia` accounts have each fact."""

    accounts: int
    with_region: int
    with_rubro: int

    def line(self) -> str:
        def pct(n: int) -> str:
            return f"{(100 * n / self.accounts):.0f} %" if self.accounts else "—"

        return (
            f"{self.accounts} cuentas · país {self.with_region} ({pct(self.with_region)}) · "
            f"rubro {self.with_rubro} ({pct(self.with_rubro)})"
        )


# --------------------------------------------------------------------------------------
# reading the free sources out of a cached answer (pure)
# --------------------------------------------------------------------------------------


def _dicts(value: object) -> list[Mapping[str, Any]]:
    return [v for v in value if isinstance(v, Mapping)] if isinstance(value, list) else []


def _params_handle(params_key: str) -> str:
    try:
        params = json.loads(params_key or "{}")
    except ValueError:
        return ""
    return normalize_handle(str(params.get("handle") or "")) if isinstance(params, dict) else ""


def _tiktok_video_claims(
    videos: Iterable[Mapping[str, Any]], *, fallback_handle: str, ref: str
) -> Iterator[RegionClaim]:
    for video in videos:
        author = video.get("author")
        handle = str(author.get("unique_id") or "") if isinstance(author, Mapping) else ""
        handle = normalize_handle(handle) or fallback_handle
        code = normalize_country(video.get("region"))
        if handle and code:
            yield RegionClaim("tiktok", handle, code, SOURCE_TIKTOK_REGION, ref)


def _ig_reel_country(item: Mapping[str, Any]) -> str:
    media = item.get("media") if isinstance(item.get("media"), Mapping) else item
    location = media.get("location") if isinstance(media, Mapping) else None
    if not isinstance(location, Mapping):
        return ""
    raw = location.get("address_json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    return normalize_country(raw.get("country_code")) if isinstance(raw, Mapping) else ""


def claims_from_payload(
    path: str, params_key: str, payload: Mapping[str, Any], *, payload_id: str = ""
) -> list[RegionClaim]:
    """Every country a cached vendor answer states about an account. Pure; an answer of
    an unknown path or shape gives nothing."""
    ref = f"vendor_payloads:{payload_id}" if payload_id else ""
    handle = _params_handle(params_key)
    if path == "/v1/tiktok/search/keyword":
        videos = [
            item["aweme_info"]
            for item in _dicts(payload.get("search_item_list"))
            if isinstance(item.get("aweme_info"), Mapping)
        ]
        return list(_tiktok_video_claims(videos, fallback_handle="", ref=ref))
    if path in ("/v1/tiktok/search/hashtag", "/v3/tiktok/profile/videos"):
        fallback = handle if path == "/v3/tiktok/profile/videos" else ""
        return list(
            _tiktok_video_claims(
                _dicts(payload.get("aweme_list")), fallback_handle=fallback, ref=ref
            )
        )
    if path == "/v1/tiktok/profile":
        user = payload.get("user")
        code = normalize_country(user.get("region")) if isinstance(user, Mapping) else ""
        found = normalize_handle(str(user.get("uniqueId") or "")) if code else ""
        if code and (found or handle):
            return [RegionClaim("tiktok", found or handle, code, SOURCE_TIKTOK_REGION, ref)]
        return []
    if path == "/v1/instagram/user/reels" and handle:
        return [
            RegionClaim("instagram", handle, code, SOURCE_REEL_LOCATION, ref)
            for item in _dicts(payload.get("items"))
            if (code := _ig_reel_country(item))
        ]
    return []


def best_claims(claims: Iterable[RegionClaim | tuple[RegionClaim, int]]) -> dict[Key, RegionClaim]:
    """Per account: the best source that answered; within it, the country with the most
    weight (a bare claim weighs 1; ties: the claim seen last — callers feed evidence
    oldest first)."""
    grouped: dict[Key, dict[str, list[tuple[RegionClaim, int]]]] = {}
    for entry in claims:
        claim, weight = entry if isinstance(entry, tuple) else (entry, 1)
        grouped.setdefault(claim.key, {}).setdefault(claim.source, []).append((claim, weight))
    out: dict[Key, RegionClaim] = {}
    for key, by_source in grouped.items():
        found = by_source[min(by_source, key=REGION_SOURCES.index)]
        weights: Counter[str] = Counter()
        for claim, weight in found:
            weights[claim.code] += max(1, weight)
        top = max(weights.values())
        out[key] = next(c for c, _ in reversed(found) if weights[c.code] == top)
    return out


# --------------------------------------------------------------------------------------
# the database: free evidence, conditional writes, reads
# --------------------------------------------------------------------------------------


#: `(network, handle)` in a list of keys, as a row comparison the `(network, handle)`
#: unique indexes of `creators` / `creator_sightings` can serve.
_KEYS_IN = (
    "(network, handle) IN (SELECT * FROM unnest(CAST(:nets AS text[]), CAST(:hands AS text[])))"
)


def _key_params(keys: Iterable[Key]) -> dict[str, Any]:
    pairs = list(keys)
    return {"nets": [n for n, _ in pairs], "hands": [h for _, h in pairs]}


def _key_filter(scope: set[Key] | None) -> tuple[str, dict[str, Any]]:
    if scope is None:
        return "", {}
    return f" AND {_KEYS_IN}", _key_params(scope)


def free_claims(
    session: Session, keys: Iterable[Key] | None = None, *, payloads: bool = True
) -> dict[Key, RegionClaim]:
    """The best free country per account, from what the pool already stores. `keys`
    narrows it to some accounts (None = the whole pool). `payloads=False` skips the
    scan of the cached vendor answers (the slow source: a JSON walk over every cached
    search) — the review path does, and the next backfill upgrades what it finds there.
    Reads only; no vendor, no model."""
    scope = {(n, normalize_handle(h)) for n, h in keys} if keys is not None else None
    if scope is not None and not scope:
        return {}
    where, params = _key_filter(scope)
    claims: list[RegionClaim | tuple[RegionClaim, int]] = []
    for network, handle, code in session.execute(
        text(f"SELECT network, handle, country_code FROM creators WHERE country_code <> ''{where}"),
        params,
    ):
        if normalize_country(code):
            claims.append(RegionClaim(network, handle, code, SOURCE_PROFILE, "creators"))
    if payloads:
        rows = session.execute(
            text(
                "SELECT id, path, params_key, payload FROM vendor_payloads "
                "WHERE vendor = :vendor AND status = 200 AND path = ANY(:paths) "
                "ORDER BY fetched_at"
            ),
            {"vendor": VENDOR, "paths": list(REGION_PATHS)},
            # a server-side cursor: the JSON of every cached search is never all in memory
            execution_options={"stream_results": True, "yield_per": 200},
        )
        for payload_id, path, params_key, payload in rows:
            if not isinstance(payload, Mapping):
                continue
            for claim in claims_from_payload(path, params_key, payload, payload_id=str(payload_id)):
                if claim.network in NETWORKS and (scope is None or claim.key in scope):
                    claims.append(claim)
    sightings = session.execute(
        text(
            "SELECT network, handle, country_code, sum(times), "
            "(array_agg(term ORDER BY seen_at DESC))[1] FROM creator_sightings "
            f"WHERE country_code <> ''{where} GROUP BY network, handle, country_code "
            "ORDER BY max(seen_at)"
        ),
        params,
    )
    for network, handle, code, times, term in sightings:
        if normalize_country(code):
            claim = RegionClaim(
                network, handle, code, SOURCE_SIGHTINGS, f"creator_sightings:{term}"
            )
            claims.append((claim, int(times or 1)))
    return best_claims(claims)


#: A claim lands when the row has no region; when its source ranks better; or when the
#: same source now says another country (or runs another pipeline version). The same
#: claim twice is a no-op.
_APPLY_REGION = text(
    """
    UPDATE creators SET region_code = :code, region_source = :source,
           region_source_ref = :ref, region_version = :version, region_inferred_at = :now
     WHERE network = :network AND handle = :handle
       AND (
            region_source = ''
         OR array_position(CAST(:ranks AS text[]), region_source) > :rank
         OR (region_source = :source
             AND (region_code <> :code OR region_version <> :version))
       )
    """
)

_APPLY_RUBRO = text(
    """
    UPDATE creators SET rubro = :rubro, rubro_source = 'ai', rubro_source_ref = :ref,
           rubro_model = :model, rubro_version = :version, rubro_inferred_at = :now
     WHERE network = :network AND handle = :handle
       AND (
            rubro_source = ''
         OR rubro_version <> :version
         -- `otro` often means «too little to tell»: a real rubro read later replaces it
         OR (rubro = 'otro' AND :rubro <> 'otro')
       )
    """
)


def _now(value: datetime | None) -> datetime:
    return value or datetime.now(UTC)


def apply_region(session: Session, claim: RegionClaim, *, now: datetime | None = None) -> bool:
    """Write one claim if it improves the row (see `_APPLY_REGION`). True when written;
    an account the pool does not have is skipped (False)."""
    result = session.execute(
        _APPLY_REGION,
        {
            "code": claim.code,
            "source": claim.source,
            "ref": claim.source_ref,
            "version": claim.version,
            "now": _now(now),
            "network": claim.network,
            "handle": claim.handle,
            "ranks": list(REGION_SOURCES),
            # array_position is 1-based
            "rank": REGION_SOURCES.index(claim.source) + 1,
        },
    )
    return bool(result.rowcount)


def apply_rubro(session: Session, claim: RubroClaim, *, now: datetime | None = None) -> bool:
    result = session.execute(
        _APPLY_RUBRO,
        {
            "rubro": claim.rubro,
            "ref": claim.source_ref,
            "model": claim.model,
            "version": claim.version,
            "now": _now(now),
            "network": claim.network,
            "handle": claim.handle,
        },
    )
    return bool(result.rowcount)


def backfill(
    session: Session, *, keys: Iterable[Key] | None = None, now: datetime | None = None
) -> BackfillReport:
    """Fill `region_*` from the free sources for `keys` (None = the whole pool). No
    vendor, no model: a re-run writes nothing new."""
    scope = list(keys) if keys is not None else None
    report = BackfillReport(accounts=len(scope) if scope is not None else 0)
    best = free_claims(session, scope)
    report.resolved = len(best)
    moment = _now(now)
    for claim in best.values():
        if apply_region(session, claim, now=moment):
            report.updated += 1
            report.by_source[claim.source] += 1
    return report


def account_facts(session: Session, keys: Iterable[Key]) -> dict[Key, AccountFacts]:
    """Region and rubro per `(network, handle)` — the read RF-01 / RF-02b / RF-07a filter
    with. An account the pool does not have is absent."""
    wanted = [(n, normalize_handle(h)) for n, h in keys]
    if not wanted:
        return {}
    rows = session.execute(
        text(
            "SELECT network, handle, region_code, region_source, rubro, rubro_source "
            f"FROM creators WHERE {_KEYS_IN}"
        ),
        _key_params(wanted),
    )
    return {(r[0], r[1]): AccountFacts(*r) for r in rows}


def labeled_accounts(session: Session) -> list[Key]:
    """The `referente`/`competencia` accounts of the session's business — read through
    `tenant_session`, so RLS hands back that business's labels and nobody else's
    (detractors are out of the epic, decision 3)."""
    rows = session.execute(
        text(
            "SELECT DISTINCT network, handle FROM brand_account_labels "
            "WHERE label IN ('referente', 'competencia') AND network = ANY(:networks)"
        ),
        {"networks": list(NETWORKS)},
    )
    return [(r[0], r[1]) for r in rows]


def coverage(session: Session) -> Coverage:
    """How many of the session's business's labeled accounts have a region / a rubro."""
    keys = labeled_accounts(session)
    facts = account_facts(session, keys)
    return Coverage(
        accounts=len(keys),
        with_region=sum(1 for f in facts.values() if f.region_code),
        with_rubro=sum(1 for f in facts.values() if f.rubro and f.rubro != "otro"),
    )


# --------------------------------------------------------------------------------------
# what the account review writes (`Qualify/referentes_review`)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewInference:
    """What one review answered about one account that is kept: its rubro. The review's
    `pais` has no field here on purpose — it is never stored (Deivid, 2026-11-25)."""

    network: str
    handle: str
    rubro: str
    model: str
    version: str
    source_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "handle", normalize_handle(self.handle))


def record_inferences_in(
    session: Session, inferences: Sequence[ReviewInference], *, now: datetime | None = None
) -> int:
    """Store the review's rubro, and fill the region of the same accounts from the free
    sources the pool already has (no payload scan: the backfill does that). Returns rows
    written. Accounts outside the pool (other networks, never seen) are skipped."""
    moment = _now(now)
    keep = [i for i in inferences if i.network in NETWORKS and normalize_handle(i.handle)]
    if not keep:
        return 0
    keys = [(i.network, normalize_handle(i.handle)) for i in keep]
    free = free_claims(session, keys, payloads=False)
    written = 0
    for item in keep:
        key = (item.network, normalize_handle(item.handle))
        changed = False
        if key in free:
            changed |= apply_region(session, free[key], now=moment)
        if item.rubro in RUBROS:
            rubro = RubroClaim(
                item.network, item.handle, item.rubro, item.model, item.version, item.source_ref
            )
            changed |= apply_rubro(session, rubro, now=moment)
        written += int(changed)
    return written


def record_inferences(tenant_id: UUID | None, inferences: Sequence[ReviewInference]) -> int:
    """`record_inferences_in` through `tenant_session` — the business whose review this
    was opens the door (its role and pool); the table itself is global. No business (a
    «sin negocio» review) → nothing is written."""
    if tenant_id is None or not inferences:
        return 0
    with tenant_session(tenant_id) as session:
        return record_inferences_in(session, inferences)


# --------------------------------------------------------------------------------------
# CLI: `just creators-region-backfill --tenant <uuid> [--pool]`
# --------------------------------------------------------------------------------------


def run_backfill(
    tenant_id: UUID, *, pool: bool = False
) -> tuple[Coverage, BackfillReport, Coverage]:
    """Coverage of the business's labeled accounts before, the backfill, coverage after.
    `pool` widens the backfill to every account of the shared pool (the coverage still
    counts only this business's labels)."""
    with tenant_session(tenant_id) as session:
        before = coverage(session)
        keys = None if pool else labeled_accounts(session)
        report = backfill(session, keys=keys)
        after = coverage(session)
    return before, report, after


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="creators-region-backfill",
        description=(
            "Fill the region of public accounts from FREE sources only (no vendor, no model). "
            "Idempotent: a re-run writes nothing new."
        ),
    )
    parser.add_argument("--tenant", required=True, type=UUID, help="the business whose door opens")
    parser.add_argument(
        "--pool", action="store_true", help="every account of the shared pool, not only its labels"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    before, report, after = run_backfill(args.tenant, pool=args.pool)
    print(f"antes:   {before.line()}")
    print(
        f"backfill: {report.resolved} con país gratis, {report.updated} escritas "
        f"({dict(report.by_source) or 'nada nuevo'})"
    )
    print(f"después: {after.line()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

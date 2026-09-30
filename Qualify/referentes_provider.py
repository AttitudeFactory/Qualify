"""The bridge between the referentes search (`creator_discovery`) and its Postgres store
(`qualify_api.referentes`, migration 0020) — what `BrandConnectState` calls instead of the
old `discovery_cache.json` for phases, and what persists the referente/competencia/
detractor sort that used to live only in the session.

Kept OUT of `creator_discovery.py` on purpose: that module's code is fingerprinted as
"the algorithm" (`test_creator_discovery_version.py`), and how a result is stored is not
part of which accounts it finds — putting this there would force a version bump, and a
recompute that spends credits, for a change that finds nothing new.

Every function here is a blocking DB call: callers on the event loop run them through
`asyncio.to_thread`. `REPOSITORY` is module-level so tests swap in
`MemoryReferentesRepository`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from qualify_api.referentes import (
    ORIGIN_AI,
    ORIGIN_CATALOG,
    ORIGIN_OPERATOR,
    ORIGIN_PROFILE,
    NewDiscoveredAccount,
    NewDiscoveryPhase,
    PostgresReferentesRepository,
    ReferentesRepository,
    StoredDiscoveryPhase,
    normalize_handle,
)

from . import creator_discovery, referentes_review
from .creator_discovery import Candidate, DiscoverySeed, PhaseResult

REPOSITORY: ReferentesRepository = PostgresReferentesRepository()

#: How long a stored phase is reused before the search runs again — the same week the
#: JSON cache kept (`creator_discovery._CACHE_TTL_SECONDS`).
PHASE_TTL_SECONDS = 7 * 24 * 3600


def seed_payload(
    seed: DiscoverySeed, picks: Mapping[str, Mapping[str, str]] | None = None
) -> dict[str, Any]:
    """The seed as stored: everything the phase read, with each hashtag's origin — the
    brand's own (`profile`, `seed_from_profile`), the shared catalog's (`catalog`,
    `hashtag_catalog.catalog_hashtags_for`) or a catalog tag Claude chose (`ai`,
    `hashtag_catalog.ai_hashtags_for`) or one the operator curated as a pill (`operator`,
    `DiscoverySeed.chosen_hashtags`). An `ai` or `operator` entry carries what `picks`
    says about it (`model`/`fit`/`reason`, or `suggested_by`/`reason` for a pill Claude
    suggested): a model's decision is stored with its provenance."""
    picks = picks or {}

    def chosen_item(tag: str) -> dict[str, str]:
        extra = {k: str(v) for k, v in (picks.get(tag) or {}).items() if k != "origin"}
        return {"tag": tag, "origin": ORIGIN_OPERATOR, **extra}

    def catalog_item(tag: str) -> dict[str, str]:
        pick = picks.get(tag)
        if pick is None:
            return {"tag": tag, "origin": ORIGIN_CATALOG}
        return {"tag": tag, "origin": ORIGIN_AI, **{k: str(v) for k, v in pick.items()}}

    return {
        "handle": seed.handle,
        "niches": list(seed.niches),
        "terms": list(seed.terms),
        "related": list(seed.related),
        "country_code": seed.country_code,
        "city": seed.city,
        "hashtags": [
            *({"tag": tag, "origin": ORIGIN_PROFILE} for tag in seed.hashtags),
            *(catalog_item(tag) for tag in seed.catalog_hashtags),
            *(chosen_item(tag) for tag in seed.chosen_hashtags),
        ],
    }


def card_identity(card: dict[str, str]) -> tuple[str, str] | None:
    """`(network, handle)` as stored, from a card (`creator_discovery.account_card`:
    network "TikTok"/"Instagram", handle "@user"; a manual referente's network label is
    mapped back to its id, `referentes_review.MANUAL_NETWORKS`). None for a card with
    no handle."""
    label = str(card.get("network") or "").strip().lower()
    network = referentes_review.NETWORK_BY_LABEL.get(label, label)
    try:
        handle = normalize_handle(str(card.get("handle") or ""))
    except ValueError:
        return None
    return (network, handle) if network else None


def key_identity(account_key: str) -> tuple[str, str] | None:
    """Same, from the wizard's bucket key (`"<network>:<handle>"`, `_account_key`)."""
    network, _, handle = account_key.partition(":")
    return card_identity({"network": network, "handle": handle})


def _stored_account(candidate: Candidate, card: dict[str, str]) -> NewDiscoveredAccount:
    return NewDiscoveredAccount(
        network=candidate.network,
        handle=candidate.username,
        card=card,
        full_name=candidate.full_name,
        followers=candidate.followers,
        profile_url=candidate.profile_url,
        avatar_url=candidate.avatar,
        found_by=tuple(candidate.sources),
    )


def to_phase_dict(stored: StoredDiscoveryPhase) -> dict[str, Any]:
    """A stored phase in the `creator_discovery.phase_to_dict` shape `_apply_phase`
    already takes — so a hit from the database renders exactly like a fresh run."""
    return {
        "key": stored.phase_key,
        "title": stored.title,
        "note": stored.note,
        "accounts": [dict(account.card) for account in stored.accounts],
        "credits": stored.credits,
        "errors": list(stored.errors),
        # what the AI review dropped is shown for a fresh run only; not stored
        "discarded": [],
    }


def find_phase(
    tenant_id: UUID, brand_id: UUID, key: str, seed: DiscoverySeed, *, now: float | None = None
) -> dict[str, Any] | None:
    """The stored result for this phase, seed and CURRENT algorithm version, if it is
    younger than `PHASE_TTL_SECONDS`. A hit that is no longer the brand's current phase
    (the operator went back to a city searched before) becomes current again."""
    computed_after = datetime.fromtimestamp((now or time.time()) - PHASE_TTL_SECONDS, UTC)
    stored = REPOSITORY.find_phase(
        tenant_id=tenant_id,
        brand_id=brand_id,
        phase_key=key,
        seed_signature=creator_discovery.phase_signature(key, seed),
        algorithm_version=creator_discovery.PHASED_PLAN_VERSION,
        computed_after=computed_after,
    )
    if stored is None:
        return None
    if not stored.is_current:
        stored = REPOSITORY.promote_phase(tenant_id=tenant_id, phase_id=stored.id)
    return to_phase_dict(stored)


def save_phase(
    tenant_id: UUID,
    brand_id: UUID,
    key: str,
    seed: DiscoverySeed,
    result: PhaseResult,
    phase: dict[str, Any],
    hashtag_picks: Mapping[str, Mapping[str, str]] | None = None,
) -> bool:
    """Store a finished phase as the brand's current one. `phase` is the dict the wizard
    rendered (`phase_to_dict(result)`), so the stored cards are the ones shown. Same rule
    the JSON cache had: a phase with errors AND nothing found is not stored, so the next
    walk retries it. Nor is a phase whose AI review failed (`PhaseResult.review_failed`):
    it fell back to the unreviewed pick, and keeping it would serve that for a week.
    `hashtag_picks` is the provenance of the seed's AI-chosen hashtags (`seed_payload`).
    Returns whether it was stored."""
    if result.errors and not result.accounts:
        return False
    if result.review_failed:
        return False
    cards = [c for c in phase.get("accounts") or [] if isinstance(c, dict)]
    accounts: list[NewDiscoveredAccount] = []
    seen: set[tuple[str, str]] = set()
    for candidate, card in zip(result.accounts, cards, strict=True):
        account = _stored_account(candidate, card)
        if (account.network, account.handle) in seen:
            continue
        seen.add((account.network, account.handle))
        accounts.append(account)
    REPOSITORY.save_phase(
        NewDiscoveryPhase(
            tenant_id=tenant_id,
            brand_id=brand_id,
            phase_key=key,
            algorithm_version=creator_discovery.PHASED_PLAN_VERSION,
            seed_signature=creator_discovery.phase_signature(key, seed),
            seed=seed_payload(seed, hashtag_picks),
            title=result.title,
            note=result.note,
            queries=tuple(result.queries),
            errors=tuple(result.errors),
            credits=result.credits,
            accounts=tuple(accounts),
        )
    )
    return True


#: The `reason` a kept card shows instead of the search that once surfaced it.
KEPT_REASON = "de una búsqueda anterior"


def _bucket_key(card: dict[str, Any]) -> str:
    return f"{card.get('network', '')}:{card.get('handle', '')}"


def load_sort(
    tenant_id: UUID, brand_id: UUID, cards: list[dict[str, str]]
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """The stored sort, ready for the wizard: `(buckets, kept)`.

    `buckets` is `account_buckets` for every labeled account — on screen or not. `kept`
    are the cards of labeled accounts the search did NOT put on screen (a newer
    algorithm stopped finding them): the operator decided about them, so they stay in
    their bucket, rebuilt from the newest stored phase that found them."""
    labels = {
        (label.network, label.handle): label.label
        for label in REPOSITORY.labels(tenant_id=tenant_id, brand_id=brand_id)
    }
    buckets: dict[str, str] = {}
    on_screen: set[tuple[str, str]] = set()
    for card in cards:
        identity = card_identity(card)
        if identity is None:
            continue
        on_screen.add(identity)
        if identity in labels:
            buckets[_bucket_key(card)] = labels[identity]
    missing = [identity for identity in labels if identity not in on_screen]
    kept: list[dict[str, str]] = []
    if missing:
        stored = REPOSITORY.latest_accounts(
            tenant_id=tenant_id, brand_id=brand_id, identities=missing
        )
        for identity in missing:
            account = stored.get(identity)
            if account is None:
                continue
            card = {str(k): str(v) for k, v in account.card.items()}
            if card.get("manual") != "1":
                card["reason"] = KEPT_REASON
            kept.append(card)
            buckets[_bucket_key(card)] = labels[identity]
    return buckets, kept


def label_changes(persisted: dict[str, str], current: dict[str, str]) -> dict[str, str]:
    """What changed between the last stored sort and the one on screen: key → new label,
    or "" for an account taken out of every bucket (Deshacer)."""
    changes = {key: label for key, label in current.items() if persisted.get(key) != label}
    changes.update({key: "" for key in persisted if key not in current})
    return changes


def write_labels(
    tenant_id: UUID, brand_id: UUID, user_id: UUID | None, changes: dict[str, str]
) -> None:
    for account_key, label in changes.items():
        identity = key_identity(account_key)
        if identity is None:
            continue
        network, handle = identity
        if label:
            REPOSITORY.set_label(
                tenant_id=tenant_id,
                brand_id=brand_id,
                network=network,
                handle=handle,
                label=label,
                labeled_by=user_id,
            )
        else:
            REPOSITORY.clear_label(
                tenant_id=tenant_id, brand_id=brand_id, network=network, handle=handle
            )


def load_order(tenant_id: UUID, brand_id: UUID, cards: list[dict[str, str]]) -> list[str]:
    """The stored influence order (§ request 2026-09-29) of these cards, as the wizard's
    bucket keys, most influential first. Only accounts the operator ordered are listed;
    the wizard ranks the rest after them, in the order the search found them."""
    positions = {
        (label.network, label.handle): label.position
        for label in REPOSITORY.labels(tenant_id=tenant_id, brand_id=brand_id)
        if label.position is not None
    }
    ranked: dict[str, int] = {}
    for card in cards:
        identity = card_identity(card)
        if identity is not None and identity in positions:
            ranked.setdefault(_bucket_key(card), positions[identity])
    return sorted(ranked, key=lambda key: ranked[key])


def write_order(tenant_id: UUID, brand_id: UUID, order: list[str]) -> None:
    """Store the influence order: each key's index in `order` is its position. `order`
    is one list per label concatenated — a position is only ever compared inside a
    label, so one running index serves them all."""
    positions: dict[tuple[str, str], int] = {}
    for index, account_key in enumerate(order):
        identity = key_identity(account_key)
        if identity is not None:
            positions.setdefault(identity, index)
    if positions:
        REPOSITORY.set_positions(tenant_id=tenant_id, brand_id=brand_id, positions=positions)


# --------------------------------------------------------------------------------------
# Referentes added by hand (`referentes_review.add_manual_account`)
# --------------------------------------------------------------------------------------

#: The phase key the manual referentes of a brand are stored under — a pseudo-phase
#: next to the search's (`creator_discovery.PHASES`), so a manual account is restored by
#: the same path as one a newer algorithm stopped finding (`load_sort`'s `kept`), with
#: no table of its own. Never recomputed (`plan_refresh` only reads `PHASES`).
MANUAL_PHASE = "manual"
MANUAL_TITLE = "Agregados a mano"


def save_manual_account(
    tenant_id: UUID,
    brand_id: UUID,
    candidate: Candidate,
    card: dict[str, str],
    *,
    brand_handle: str = "",
) -> None:
    """Add (or replace) one manual referente: the brand's manual pseudo-phase is stored
    again with every manual account it had plus this one. The label (referente /
    competencia / detractor) is written apart, by the wizard's `sync_labels`."""
    identity = card_identity(card)
    if identity is None:
        raise ValueError("the manual card has no handle")
    previous = next(
        (
            p
            for p in REPOSITORY.current_phases(tenant_id=tenant_id, brand_id=brand_id)
            if p.phase_key == MANUAL_PHASE
        ),
        None,
    )
    accounts = [
        NewDiscoveredAccount(
            network=identity[0],
            handle=identity[1],
            card=card,
            full_name=candidate.full_name,
            followers=candidate.followers,
            profile_url=card.get("url", ""),
            avatar_url=candidate.avatar,
            found_by=tuple(candidate.sources),
        )
    ]
    for stored in previous.accounts if previous else ():
        if (stored.network, stored.handle) == identity:
            continue
        accounts.append(
            NewDiscoveredAccount(
                network=stored.network,
                handle=stored.handle,
                card=stored.card,
                full_name=stored.full_name,
                followers=stored.followers,
                profile_url=stored.profile_url,
                avatar_url=stored.avatar_url,
                found_by=stored.found_by,
            )
        )
    REPOSITORY.save_phase(
        NewDiscoveryPhase(
            tenant_id=tenant_id,
            brand_id=brand_id,
            phase_key=MANUAL_PHASE,
            algorithm_version=creator_discovery.PHASED_PLAN_VERSION,
            seed_signature=MANUAL_PHASE,
            seed={"handle": brand_handle, "hashtags": []},
            title=MANUAL_TITLE,
            accounts=tuple(accounts),
            source="operator",
        )
    )


# --------------------------------------------------------------------------------------
# Recompute with a newer algorithm (`just refresh-referentes` → `refresh_referentes.py`)
# --------------------------------------------------------------------------------------


def rebuild_seed(payload: dict[str, Any]) -> DiscoverySeed:
    """The `DiscoverySeed` a stored phase ran on — same fields, same order, so its
    `phase_signature` matches what the wizard computes for the same answers and a
    recomputed phase is a hit the next time the operator walks the flow.

    Every stored hashtag is used, split back into its seed fields by origin: `catalog`
    and `ai` ones (both came from the shared catalog) into `catalog_hashtags`, the
    operator's pills (`operator`) into `chosen_hashtags` — so the signature matches — and
    the rest (the brand's own) into `hashtags`. The origin is stored exactly so a recompute can
    re-derive one set without touching the other — and a recompute reuses the stored AI
    choice rather than asking again."""
    items = [
        item for item in payload.get("hashtags") or [] if isinstance(item, dict) and item.get("tag")
    ]
    from_catalog = (ORIGIN_CATALOG, ORIGIN_AI)
    not_own = (*from_catalog, ORIGIN_OPERATOR)
    hashtags = tuple(str(i["tag"]) for i in items if i.get("origin") not in not_own)
    catalog = tuple(str(i["tag"]) for i in items if i.get("origin") in from_catalog)
    chosen = tuple(str(i["tag"]) for i in items if i.get("origin") == ORIGIN_OPERATOR)
    return DiscoverySeed(
        handle=str(payload.get("handle") or ""),
        niches=tuple(str(n) for n in payload.get("niches") or ()),
        hashtags=hashtags,
        catalog_hashtags=catalog,
        chosen_hashtags=chosen,
        country_code=str(payload.get("country_code") or ""),
        city=str(payload.get("city") or ""),
        related=tuple(str(r) for r in payload.get("related") or ()),
        terms=tuple(str(t) for t in payload.get("terms") or ()),
    )


@dataclass(frozen=True)
class BrandRefresh:
    """One brand whose stored referentes an older algorithm computed."""

    tenant_id: UUID
    brand_id: UUID
    #: Phase keys to recompute, in `creator_discovery.PHASES` order.
    keys: tuple[str, ...]
    #: The versions that computed the current phases (for the report).
    from_versions: tuple[int, ...]
    #: What the stored phases cost last time — the best estimate of the recompute.
    estimated_credits: int
    seed: DiscoverySeed


def plan_refresh(tenant_id: UUID, *, brand_id: UUID | None = None) -> list[BrandRefresh]:
    """The brands of a tenant with at least one current phase from an older algorithm
    version. ALL of such a brand's current phases are recomputed, not only the stale
    ones: phases share one account pool (an account the sector phase picked is not
    repeated by the local one), so recomputing one alone could repeat accounts across
    categories. The seed is the one of the brand's newest phase — the latest answers
    the operator gave."""
    stale = [
        # the manual pseudo-phase is the operator's, not the algorithm's: never stale
        p
        for p in REPOSITORY.stale_phases(
            tenant_id=tenant_id, algorithm_version=creator_discovery.PHASED_PLAN_VERSION
        )
        if p.phase_key in creator_discovery.PHASES
    ]
    brands = list(dict.fromkeys(p.brand_id for p in stale))
    if brand_id is not None:
        brands = [b for b in brands if b == brand_id]
    plans: list[BrandRefresh] = []
    for brand in brands:
        current = [
            p
            for p in REPOSITORY.current_phases(tenant_id=tenant_id, brand_id=brand)
            if p.phase_key in creator_discovery.PHASES
        ]
        if not current:
            continue
        newest = max(current, key=lambda p: p.computed_at)
        present = {p.phase_key for p in current}
        plans.append(
            BrandRefresh(
                tenant_id=tenant_id,
                brand_id=brand,
                keys=tuple(k for k in creator_discovery.PHASES if k in present),
                from_versions=tuple(sorted({p.algorithm_version for p in current})),
                estimated_credits=sum(p.credits for p in current),
                seed=rebuild_seed(newest.seed),
            )
        )
    return plans


PhaseRunner = Callable[[DiscoverySeed, list[str]], list[PhaseResult]]


def run_phases(seed: DiscoverySeed, keys: list[str]) -> list[PhaseResult]:
    """The real vendor run — one `PhasedDiscovery`, so the phases share their pool —
    reviewed by Claude like the wizard's run (`referentes_review.make_reviewer`) when an
    API key is set."""
    runner = creator_discovery.PhasedDiscovery(
        seed,
        profile_cache=creator_discovery.PROFILE_CACHE_PATH,
        reviewer=referentes_review.make_reviewer(referentes_review.brand_brief(seed)),
    )
    try:
        return [runner.run(key) for key in keys]
    finally:
        runner.close()


def execute_refresh(plan: BrandRefresh, run: PhaseRunner = run_phases) -> tuple[int, list[str]]:
    """Recompute one brand and store every phase that came back usable. Returns
    `(credits spent, keys NOT stored)` — a phase with errors and nothing found keeps the
    old result current, so the brand is in the next plan again and gets retried."""
    results = run(plan.seed, list(plan.keys))
    spent = 0
    not_stored: list[str] = []
    for key, result in zip(plan.keys, results, strict=True):
        spent += result.credits
        phase = creator_discovery.phase_to_dict(result)
        if not save_phase(plan.tenant_id, plan.brand_id, key, plan.seed, result, phase):
            not_stored.append(key)
    return spent, not_stored

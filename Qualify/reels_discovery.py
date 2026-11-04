"""«Descubrir reels» — the Reflex app's side of the pipeline (ADR 42 R1, m-24854844).

The pipeline itself (whose reels, the vendor read, the transcripts, the rubro check,
the cards and the per-brand memory) is the service `qualify_api.referentes.reels`; it
moved there unchanged so a `qualify_api` worker can run it, and nothing in this module
calls ScrapeCreators. What stays here is what only the app knows:

- the brand brief the rubro check reads (`brand_brief`): the referentes search seed
  (`referentes_provider`, `creator_discovery`), the Brand Kit and the catalog
  (`creative_provider`);
- the signed cover path a card shows (`cover_path`, `avatar_proxy.reel_cover_path`).

`discover` / `cached_discover` hand those two doors to the service; every other name is
the service's, re-exported for the state (`discover_reels.py`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any
from uuid import UUID

from qualify_api.referentes import ai as review_ai
from qualify_api.referentes import reels
from qualify_api.referentes.reels import (
    CACHE_TTL_SECONDS,
    CHECK_NO_BRIEF,
    CHECK_UNAVAILABLE,
    MONTH_DAYS,
    NETWORK_LABELS,
    QUARTER_DAYS,
    SHOWN_PER_WINDOW,
    WEEK_DAYS,
    DiscoveredReels,
    Referente,
    account_key,
    account_option,
    remembered,
    transcript_for_card,
)

from . import creator_discovery, referentes_provider, referentes_review
from .avatar_proxy import reel_cover_path

logger = logging.getLogger(__name__)

#: Hashtags the brief carries: the brand's own, the operator's pills and the catalog's,
#: in that order — all of them, not the search's three (§ request 2026-10-15).
BRIEF_HASHTAGS = 12
KitLoader = Callable[[UUID, UUID], Any]
ProductsLoader = Callable[[UUID, UUID], Sequence[dict[str, str]]]


def _kit_form(tenant_id: UUID, brand_id: UUID) -> Any:
    from .creative_provider import load_kit_form  # the Brand Kit's door; lazy: heavy

    return load_kit_form(tenant_id, brand_id)


def _products(tenant_id: UUID, brand_id: UUID) -> Sequence[dict[str, str]]:
    from .creative_provider import catalog_products

    return catalog_products(tenant_id, brand_id)


def brand_brief(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    repository: Any = None,
    kit_form: KitLoader | None = None,
    products: ProductsLoader | None = None,
) -> review_ai.BrandBrief | None:
    """What the rubro check reads about the brand (§ request 2026-10-15: «mejorar el
    filtrado con el Brand Kit, los hashtags y todo ello»): the seed the brand's search
    last ran on (rubro in the operator's words, niche, city, EVERY hashtag) plus the
    Brand Kit (positioning, audience, examples of what it publishes) and the catalog
    (product names). None when the brand never ran the search — then nothing says what
    its rubro is. A kit or catalog that cannot be read only thins the brief."""
    repo = repository or referentes_provider.REPOSITORY
    phases = {
        phase.phase_key: phase
        for phase in repo.current_phases(tenant_id=tenant_id, brand_id=brand_id)
    }
    seed = None
    for key in creator_discovery.PHASES:
        phase = phases.get(key)
        if phase is not None and phase.seed:
            candidate = referentes_provider.rebuild_seed(phase.seed)
            if (
                candidate.terms
                or candidate.niches
                or candidate.hashtags
                or candidate.catalog_hashtags
            ):
                seed = candidate
                break
    if seed is None:
        return None
    # resolved here, not in the signature, so a test can swap the module's doors
    kit_form = kit_form or _kit_form
    products = products or _products
    positioning = audience = ""
    publishes: tuple[str, ...] = ()
    try:
        kit = kit_form(tenant_id, brand_id)
    except Exception as exc:  # noqa: BLE001 — a kit that cannot be read only thins the brief
        logger.warning("brand kit unreadable for the reel brief: %s", type(exc).__name__)
        kit = None
    if kit is not None:
        positioning = str(getattr(kit, "positioning", "") or "")
        audience = str(getattr(kit, "audience", "") or "")
        publishes = tuple(
            line.strip()
            for line in str(getattr(kit, "do_examples", "") or "").splitlines()
            if line.strip()
        )
    try:
        names = tuple(str(p.get("name") or "").strip() for p in products(tenant_id, brand_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog unreadable for the reel brief: %s", type(exc).__name__)
        names = ()
    base = referentes_review.brand_brief(seed, positioning=positioning, audience=audience)
    hashtags = tuple(
        dict.fromkeys(
            t for t in (*seed.hashtags, *seed.chosen_hashtags, *seed.catalog_hashtags) if t
        )
    )[:BRIEF_HASHTAGS]
    return replace(
        base,
        hashtags=hashtags or base.hashtags,
        products=tuple(n for n in names if n),
        publishes=publishes,
    )


def cover_path(reel: dict[str, Any]) -> str:
    """The backend path the card shows the cover from (`avatar_proxy.reel_cover`),
    signed: the route serves only the covers this module handed out."""
    if not reel.get("cover"):
        return ""
    return reel_cover_path(reel["network"], str(reel["id"]), str(reel["cover"]))


def _doors(
    repository: Any, kit_form: KitLoader | None, products: ProductsLoader | None
) -> dict[str, Any]:
    """What the service needs from the app: the referentes store, the brief and the
    cover signer — resolved at call time, so a test can swap this module's doors."""
    repo = repository or referentes_provider.REPOSITORY

    def brief(tenant_id: UUID, brand_id: UUID) -> review_ai.BrandBrief | None:
        return brand_brief(
            tenant_id, brand_id, repository=repo, kit_form=kit_form, products=products
        )

    return {"repository": repo, "brief": brief, "cover": cover_path}


def discover(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    repository: Any = None,
    kit_form: KitLoader | None = None,
    products: ProductsLoader | None = None,
    **kwargs: Any,
) -> DiscoveredReels:
    """`reels.discover` with the app's brief and cover doors (see the module docstring)."""
    return reels.discover(tenant_id, brand_id, **_doors(repository, kit_form, products), **kwargs)


def cached_discover(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    refresh: bool = False,
    days: int = MONTH_DAYS,
    repository: Any = None,
    kit_form: KitLoader | None = None,
    products: ProductsLoader | None = None,
    **kwargs: Any,
) -> DiscoveredReels:
    """`reels.cached_discover` (remembered per brand and depth) with the app's doors."""
    return reels.cached_discover(
        tenant_id,
        brand_id,
        refresh=refresh,
        days=days,
        **_doors(repository, kit_form, products),
        **kwargs,
    )


__all__ = [
    "CACHE_TTL_SECONDS",
    "CHECK_NO_BRIEF",
    "CHECK_UNAVAILABLE",
    "MONTH_DAYS",
    "NETWORK_LABELS",
    "QUARTER_DAYS",
    "SHOWN_PER_WINDOW",
    "WEEK_DAYS",
    "DiscoveredReels",
    "Referente",
    "account_key",
    "account_option",
    "brand_brief",
    "cached_discover",
    "cover_path",
    "discover",
    "remembered",
    "transcript_for_card",
]

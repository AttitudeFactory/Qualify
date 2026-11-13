"""What the reel rubro check reads about a brand (ADR 42 R4, m-24854848).

Moved from `Qualify/reels_discovery.py` (and the seed half from
`Qualify/referentes_review.py` / `Qualify/referentes_provider.py`) so a `qualify_api`
worker can build the brief on its own: the persistent run (`reel_runs.run`) checks it
BEFORE any paid call, and the worker has no Reflex app to ask. Behaviour unchanged: the
app's modules are now thin adapters over this one.

The brief is the seed the brand's referentes search last ran on (rubro in the operator's
words, niches, city, every hashtag) plus the Brand Kit (positioning, audience, examples
of what it publishes) and the catalog (product names). None when the brand never ran the
search — then nothing says what it sells, and nothing is read.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any
from uuid import UUID

from qualify_api.referentes import ai as review_ai
from qualify_api.referentes.discovery_seed import NICHE_LABELS, DiscoverySeed, country_name
from qualify_api.referentes.repository import ORIGIN_AI, ORIGIN_CATALOG, ORIGIN_OPERATOR

logger = logging.getLogger(__name__)

#: The referentes search phases, in the order their seed is trusted (the same tuple as
#: `Qualify/creator_discovery.PHASES`; `Qualify/test_reels_discovery.py` pins they agree).
DISCOVERY_PHASES: tuple[str, ...] = ("sector", "national", "local")
#: Hashtags the brief carries: the brand's own, the operator's pills and the catalog's,
#: in that order — all of them, not the search's three (§ request 2026-10-15).
BRIEF_HASHTAGS = 12

#: `(tenant_id, brand_id) → the Brand Kit` (anything with `positioning`, `audience` and
#: `do_examples` — a newline-joined string or a sequence), None when there is none.
KitLoader = Callable[[UUID, UUID], Any]
#: `(tenant_id, brand_id) → the active products`, each a mapping with a `name`.
ProductsLoader = Callable[[UUID, UUID], Sequence[Mapping[str, Any]]]


def rebuild_seed(payload: Mapping[str, Any]) -> DiscoverySeed:
    """The `DiscoverySeed` a stored phase ran on — same fields, same order, so its
    `phase_signature` matches what the wizard computes for the same answers.

    Every stored hashtag is used, split back into its seed fields by origin: `catalog`
    and `ai` ones into `catalog_hashtags`, the operator's pills (`operator`) into
    `chosen_hashtags`, the rest (the brand's own) into `hashtags`."""
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


def seed_brief(
    seed: DiscoverySeed,
    *,
    bio: str = "",
    category: str = "",
    positioning: str = "",
    audience: str = "",
) -> review_ai.BrandBrief:
    """The brief of a search seed alone — what the referentes review reads."""
    return review_ai.BrandBrief(
        handle=seed.handle,
        bio=bio,
        category=category,
        rubro=seed.terms,
        niches=tuple(NICHE_LABELS.get(n, n) for n in seed.niches),
        hashtags=tuple(dict.fromkeys((*seed.hashtags[:3], *seed.steering_hashtags()))),
        city=seed.city,
        country=country_name(seed.country_code),
        positioning=positioning,
        audience=audience,
    )


def _default_repository() -> Any:
    from qualify_api.referentes.reels import default_repository

    return default_repository()


def load_kit(tenant_id: UUID, brand_id: UUID) -> Any:
    """The brand's stored Brand Kit (`BrandKitService`), None when it has none."""
    from qualify_api.creative.brand_service import BrandKitService  # heavy: lazy

    return BrandKitService().get_kit(tenant_id=tenant_id, brand_id=brand_id)


def load_products(tenant_id: UUID, brand_id: UUID) -> Sequence[Mapping[str, Any]]:
    """The brand's active products, in the catalog's order — only their names matter."""
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    from qualify_api.catalog.models import BrandProduct

    with tenant_session(tenant_id) as session:
        names = session.scalars(
            select(BrandProduct.name)
            .where(BrandProduct.brand_id == brand_id, BrandProduct.is_active.is_(True))
            .order_by(BrandProduct.position, BrandProduct.name)
        ).all()
    return tuple({"name": name} for name in names)


def _examples(value: object) -> tuple[str, ...]:
    lines = value.splitlines() if isinstance(value, str) else list(value or ())
    return tuple(str(line).strip() for line in lines if str(line).strip())


def brand_brief(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    repository: Any = None,
    kit_form: KitLoader | None = None,
    products: ProductsLoader | None = None,
) -> review_ai.BrandBrief | None:
    """What the rubro check reads about the brand (§ request 2026-10-15): the seed the
    brand's search last ran on plus the Brand Kit and the catalog. None when the brand
    never ran the search. A kit or catalog that cannot be read only thins the brief."""
    repo = repository or _default_repository()
    phases = {
        phase.phase_key: phase
        for phase in repo.current_phases(tenant_id=tenant_id, brand_id=brand_id)
    }
    seed = None
    for key in DISCOVERY_PHASES:
        phase = phases.get(key)
        if phase is not None and phase.seed:
            candidate = rebuild_seed(phase.seed)
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
    kit_form = kit_form or load_kit
    products = products or load_products
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
        publishes = _examples(getattr(kit, "do_examples", ""))
    try:
        names = tuple(str(p.get("name") or "").strip() for p in products(tenant_id, brand_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog unreadable for the reel brief: %s", type(exc).__name__)
        names = ()
    base = seed_brief(seed, positioning=positioning, audience=audience)
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


__all__ = [
    "BRIEF_HASHTAGS",
    "DISCOVERY_PHASES",
    "KitLoader",
    "ProductsLoader",
    "brand_brief",
    "load_kit",
    "load_products",
    "rebuild_seed",
    "seed_brief",
]

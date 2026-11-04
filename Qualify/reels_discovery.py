"""«Descubrir reels» — the Reflex app's side of the pipeline (ADR 42 R1, m-24854844).

The pipeline itself (whose reels, the vendor read, the transcripts, the rubro check,
the cards and the per-brand memory) is the service `qualify_api.referentes.reels`; it
moved there unchanged so a `qualify_api` worker can run it, and nothing in this module
calls ScrapeCreators. What stays here is what only the app knows:

- the doors of the brand brief the rubro check reads (`brand_brief`): the referentes
  store (`referentes_provider`), the Brand Kit form and the catalog rows
  (`creative_provider`) — the brief itself is built by `qualify_api.referentes.brand_brief`
  since ADR 42 R4 (m-24854848);
- the signed cover path a card shows (`cover_path`, `avatar_proxy.reel_cover_path`).

`discover` / `cached_discover` hand those two doors to the service; every other name is
the service's, re-exported for the state (`discover_reels.py`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from qualify_api.referentes import ai as review_ai
from qualify_api.referentes import brand_brief as shared_brief
from qualify_api.referentes import reels
from qualify_api.referentes.reels import (
    CACHE_TTL_SECONDS,
    CHECK_NO_BRIEF,
    CHECK_READ_UNAVAILABLE,
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

from . import referentes_provider
from .avatar_proxy import reel_cover_path

logger = logging.getLogger(__name__)

BRIEF_HASHTAGS = shared_brief.BRIEF_HASHTAGS
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
    """What the rubro check reads about the brand — built by the service
    (`qualify_api.referentes.brand_brief`, moved there by ADR 42 R4, m-24854848, so the
    `reels-worker` can build it alone), with the app's own doors: the referentes store,
    the Brand Kit form and the catalog rows. Unchanged for the screen."""
    return shared_brief.brand_brief(
        tenant_id,
        brand_id,
        repository=repository or referentes_provider.REPOSITORY,
        # resolved here, not in the signature, so a test can swap the module's doors
        kit_form=kit_form or _kit_form,
        products=products or _products,
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
    "CHECK_READ_UNAVAILABLE",
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

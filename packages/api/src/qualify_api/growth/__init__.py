"""The creator read history (migration 0034) and the organic growth estimate over it.

Scrape Creators answers with today's figures only (`docs/scrapecreators-crecimiento-
organico-y-contenido-ia.md`): a growth figure needs reads apart in time, so this package
keeps every profile and post read as a row (`repository`) and estimates, from the series,
how much of a creator's growth its own content explains (`organic`) — "organic" meaning
not bought: no ads, no boosts, no paid followers.
"""

from qualify_api.growth.organic import (
    OrganicEstimate,
    PostVerdict,
    Reference,
    estimate_organic_growth,
)
from qualify_api.growth.repository import (
    FollowerPoint,
    GrowthRepository,
    MemoryGrowthRepository,
    PostgresGrowthRepository,
    PostRead,
    ProfileRead,
    normalize_handle,
)

__all__ = [
    "FollowerPoint",
    "GrowthRepository",
    "MemoryGrowthRepository",
    "OrganicEstimate",
    "PostRead",
    "PostVerdict",
    "PostgresGrowthRepository",
    "ProfileRead",
    "Reference",
    "estimate_organic_growth",
    "normalize_handle",
]

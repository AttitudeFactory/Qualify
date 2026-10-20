"""Third-party stock (Pixabay; Pexels when it issues keys again) behind one `StockProvider`
seam — `docs/plan-integracion-stock-pexels-pixabay.md`. Pure HTTP clients and data: the
cache, the quota, the copy to R2 and the provenance row live in `qualify_api.stock`."""

from qualify_creative.stock.base import (
    Orientation,
    StockError,
    StockItem,
    StockMediaType,
    StockNotConfigured,
    StockPage,
    StockProvider,
    StockQuery,
    StockRateLimited,
    StockRendition,
)
from qualify_creative.stock.people import PEOPLE_FILTER_VERSION, names_a_person
from qualify_creative.stock.pixabay import PixabayProvider

__all__ = [
    "PEOPLE_FILTER_VERSION",
    "Orientation",
    "PixabayProvider",
    "StockError",
    "StockItem",
    "StockMediaType",
    "StockNotConfigured",
    "StockPage",
    "StockProvider",
    "StockQuery",
    "StockRateLimited",
    "StockRendition",
    "names_a_person",
]

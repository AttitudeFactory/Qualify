"""Third-party stock in the generator: search with a shared 24 h cache and per-tenant
quotas, and the import that copies a chosen file to R2 with its provenance
(`docs/plan-integracion-stock-pexels-pixabay.md`). The HTTP clients are
`qualify_creative.stock`; this package adds Redis, R2 and Postgres."""

from qualify_api.stock.keys import is_stock_key, stock_key_provider, stock_object_key
from qualify_api.stock.service import (
    ImportedStock,
    StockQuotaExceeded,
    StockSearchResult,
    StockService,
    StockUnavailable,
)

__all__ = [
    "ImportedStock",
    "StockQuotaExceeded",
    "StockSearchResult",
    "StockService",
    "StockUnavailable",
    "is_stock_key",
    "stock_key_provider",
    "stock_object_key",
]

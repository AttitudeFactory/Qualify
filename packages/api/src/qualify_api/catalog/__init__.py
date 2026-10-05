"""Product catalog (migration 0038): the ORM shapes for a brand's products and their
media. DDL/RLS/grants live in Alembic; sessions come from `qualify_shared.db`."""

from qualify_api.catalog.models import (
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_VIDEO,
    MEDIA_TYPES,
    BrandProduct,
    ProductMedia,
)

__all__ = [
    "MEDIA_TYPE_IMAGE",
    "MEDIA_TYPE_VIDEO",
    "MEDIA_TYPES",
    "BrandProduct",
    "ProductMedia",
]

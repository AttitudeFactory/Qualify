"""The font file a Brand Kit holds (m-24828920) — what the generator draws the brand's
words in. Read through the tenant door; the kit offers ONE typography tile since
2026-10-05 (slot `heading`), and a kit from before it may hold a `body` one too."""

from __future__ import annotations

from uuid import UUID

from qualify_api.creative.brand_kit_store import FONT, BrandKitStore

#: Which slot's file wins when a kit holds both.
_SLOT_ORDER = ("heading", "body")


class DbBrandFontFiles:
    def __init__(self, store: BrandKitStore | None = None) -> None:
        self._store = store or BrandKitStore()

    def __call__(self, *, tenant_id: UUID, brand_id: UUID) -> str | None:
        fonts = {
            asset.slot: asset.object_key
            for asset in self._store.list_assets(tenant_id=tenant_id, brand_id=brand_id)
            if asset.kind == FONT and asset.object_key
        }
        return next((fonts[slot] for slot in _SLOT_ORDER if slot in fonts), None)

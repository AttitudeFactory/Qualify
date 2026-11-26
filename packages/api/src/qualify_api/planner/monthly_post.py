"""«Publicación del mes» — the per-brand setting (m-25120704, epic m-25120477).

Each month Qualify may prepare one post for the brand, and every such post spends one of
the client's monthly creations. So it is opt-in: `enabled` is **off** until the owner turns
it on (founder, 2026-11-25), and `kind` is the piece type they want, one of the kinds
«Crear pieza» offers (`ContentKind.is_offered`) except the script to record (it is not a
ready-to-publish piece; founder, 2026-11-25), the advertising image by default.

Stored without a table, like the seasons' «Ahora no» (`whatsapp.seasons`): ONE reserved key
of the brand's `connect` details document, `brand_kit_details.connect.monthly_post =
{"enabled": bool, "kind": str, "product_id"?: str}` (RLS of `brand_kit_details`; carried
across the wizards' saves by `RESERVED_DETAIL_KEYS`). Written through
`BrandKitStore.set_document_key`, so the rest of the document stays exactly as it is in the
database at that moment. `product_id` is the catalog product a template is made from
(m-25121346, founder 2026-11-26: the owner picks it once), kept only with `template`; its
photos are re-read every month, never stored here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Final, Protocol
from uuid import UUID

from qualify_creative.enums import ContentKind
from qualify_creative.schemas import MAX_PRODUCT_IMAGES
from qualify_shared.db.session import tenant_session
from sqlalchemy import bindparam, text

from qualify_api.catalog.models import MEDIA_TYPE_IMAGE
from qualify_api.catalog.service import CatalogService, ProductRecord, UnknownProduct
from qualify_api.creative.brand_kit_store import BrandKitStore

MONTHLY_POST_DOCUMENT: Final = "connect"
MONTHLY_POST_KEY: Final = "monthly_post"
DEFAULT_KIND: Final = ContentKind.STATIC_FLYER
#: The kinds the owner can choose, in «¿Qué creamos?»'s order (m-25121346, founder
#: 2026-11-26): the chore fills what each needs — a carousel's slides from the date, the
#: avatars' character, presenter and voice from the Brand Kit at 10 s, a template's photos
#: from the ONE catalog product the owner picked (`product_id`).
MONTHLY_POST_KINDS: Final[tuple[ContentKind, ...]] = (
    ContentKind.STATIC_FLYER,
    ContentKind.CAROUSEL,
    ContentKind.TEMPLATE,
    ContentKind.CLIP,
    ContentKind.ANIMATED_AVATAR_VIDEO,
    ContentKind.AVATAR_VIDEO,
)


class ProductLookup(Protocol):
    def get_product(self, *, tenant_id: UUID, product_id: UUID) -> ProductRecord: ...


@dataclass(frozen=True)
class MonthlyPostSetting:
    enabled: bool = False
    kind: ContentKind = DEFAULT_KIND
    #: The template's catalog product (None for every other kind).
    product_id: UUID | None = None
    #: Read only (`get_monthly_post_setting`): the template's product is gone, inactive,
    #: of another brand or without photos — the card asks the owner to pick another.
    product_missing: bool = False


def parse_kind(kind: str | ContentKind) -> ContentKind:
    """The boundary check: one of `MONTHLY_POST_KINDS`, else `ValueError`."""
    try:
        parsed = ContentKind(kind)
    except ValueError:
        raise ValueError(f"unknown piece kind {kind!r}") from None
    if parsed not in MONTHLY_POST_KINDS:
        raise ValueError(f"piece kind {parsed.value!r} is not offered for the monthly post")
    return parsed


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def _from_document(value: Any) -> MonthlyPostSetting:
    """A stored value read back; anything malformed reads as the default (off). A kind not
    offered keeps the setting as saved and falls back to `DEFAULT_KIND` — and so does a
    template without its product (saved while #825 offered it, before `product_id`)."""
    if not isinstance(value, dict):
        return MonthlyPostSetting()
    try:
        kind = parse_kind(value.get("kind", DEFAULT_KIND))
    except ValueError:
        kind = DEFAULT_KIND
    product_id = _uuid(value.get("product_id")) if kind is ContentKind.TEMPLATE else None
    if kind is ContentKind.TEMPLATE and product_id is None:
        kind = DEFAULT_KIND
    return MonthlyPostSetting(value.get("enabled") is True, kind, product_id)


def product_photo_keys(product: ProductRecord) -> tuple[str, ...]:
    """The product's photos, the main one first, as many as a brief takes."""
    photos = sorted(
        (m for m in product.media if m.media_type == MEDIA_TYPE_IMAGE),
        key=lambda m: (not m.is_primary, m.position),
    )
    return tuple(m.object_key for m in photos)[:MAX_PRODUCT_IMAGES]


def usable_product(
    tenant_id: UUID, brand_id: UUID, product_id: UUID, *, catalog: ProductLookup | None = None
) -> ProductRecord | None:
    """The template's product while it can still make one — this brand's, active, with
    at least one photo; None otherwise (deleted included). Blocking."""
    try:
        product = (catalog or _catalog()).get_product(tenant_id=tenant_id, product_id=product_id)
    except UnknownProduct:
        return None
    if product.brand_id != brand_id or not product.is_active or not product_photo_keys(product):
        return None
    return product


def _catalog() -> ProductLookup:
    from qualify_api.creative.composition import media_root  # noqa: PLC0415
    from qualify_api.creative.media import LocalMediaStore  # noqa: PLC0415

    # `get_product` never touches the store; the Catálogo only needs one to exist
    return CatalogService(store=LocalMediaStore(media_root()))


def get_monthly_post_setting(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    store: BrandKitStore | None = None,
    catalog: ProductLookup | None = None,
) -> MonthlyPostSetting:
    """The setting, with `product_missing` for a template whose product can no longer
    make one (the card says so; the job skips the month uncharged)."""
    connect = (store or BrandKitStore()).load_details(tenant_id=tenant_id, brand_id=brand_id)
    setting = _from_document(connect.connect.get(MONTHLY_POST_KEY))
    if setting.product_id is None:
        return setting
    missing = usable_product(tenant_id, brand_id, setting.product_id, catalog=catalog) is None
    return replace(setting, product_missing=missing)


def set_monthly_post_setting(
    tenant_id: UUID,
    brand_id: UUID,
    enabled: bool,
    kind: str | ContentKind,
    product_id: UUID | str | None = None,
    *,
    store: BrandKitStore | None = None,
    catalog: ProductLookup | None = None,
) -> MonthlyPostSetting:
    """Validate and save; idempotent (the same call twice leaves the same row). A
    template needs `product_id`, one of this brand's active products with a photo
    (`ValueError` otherwise); any other kind drops it."""
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a bool")
    parsed = parse_kind(kind)
    product: UUID | None = None
    if parsed is ContentKind.TEMPLATE:
        product = _uuid(product_id)
        if product is None:
            raise ValueError("a template needs the catalog product it is made from")
        if usable_product(tenant_id, brand_id, product, catalog=catalog) is None:
            raise ValueError("the product is not an active product of this brand with a photo")
    value: dict[str, Any] = {"enabled": enabled, "kind": parsed.value}
    if product is not None:
        value["product_id"] = str(product)
    (store or BrandKitStore()).set_document_key(
        tenant_id=tenant_id,
        brand_id=brand_id,
        document=MONTHLY_POST_DOCUMENT,
        key=MONTHLY_POST_KEY,
        value=value,
    )
    return MonthlyPostSetting(enabled, parsed, product)


@dataclass(frozen=True)
class Occasion:
    """Why a monthly post is in «Por aprobar»: the date it was made for (m-25120706)."""

    name: str  # the brief's topic = the calendar's Spanish name for the tenant's country
    day: date


_OCCASIONS_SQL = text(
    "SELECT mp.draft_id, b.topic, mp.event_date FROM monthly_posts mp "
    "JOIN content_drafts d ON d.id = mp.draft_id AND d.tenant_id = mp.tenant_id "
    "JOIN content_briefs b ON b.id = d.brief_id "
    "WHERE mp.draft_id IN :ids AND mp.event_date IS NOT NULL"
).bindparams(bindparam("ids", expanding=True))


def occasions_of(tenant_id: UUID, draft_ids: Iterable[UUID]) -> dict[UUID, Occasion]:
    """The drafts among `draft_ids` that are monthly posts, with their date. One RLS-scoped
    read for the whole batch; a draft that is not a monthly post is left out. Blocking."""
    ids = list(set(draft_ids))
    if not ids:
        return {}
    with tenant_session(tenant_id) as session:
        rows = session.execute(_OCCASIONS_SQL, {"ids": ids}).all()
    return {row.draft_id: Occasion(row.topic, row.event_date) for row in rows}

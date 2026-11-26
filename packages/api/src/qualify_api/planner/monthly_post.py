"""«Publicación del mes» — the per-brand setting (m-25120704, epic m-25120477).

Each month Qualify may prepare one post for the brand, and every such post spends one of
the client's monthly creations. So it is opt-in: `enabled` is **off** until the owner turns
it on (founder, 2026-11-25), and `kind` is the piece type they want, one of the kinds
«Crear pieza» offers (`ContentKind.is_offered`), the advertising image by default.

Stored without a table, like the seasons' «Ahora no» (`whatsapp.seasons`): ONE reserved key
of the brand's `connect` details document, `brand_kit_details.connect.monthly_post =
{"enabled": bool, "kind": str}` (RLS of `brand_kit_details`; carried across the wizards'
saves by `RESERVED_DETAIL_KEYS`). Written through `BrandKitStore.set_document_key`, so the
rest of the document stays exactly as it is in the database at that moment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from qualify_creative.enums import ContentKind

from qualify_api.creative.brand_kit_store import BrandKitStore

MONTHLY_POST_DOCUMENT: Final = "connect"
MONTHLY_POST_KEY: Final = "monthly_post"
DEFAULT_KIND: Final = ContentKind.STATIC_FLYER
#: The kinds the owner can choose: exactly what «¿Qué creamos?» offers.
MONTHLY_POST_KINDS: Final[tuple[ContentKind, ...]] = tuple(
    kind for kind in ContentKind if kind.is_offered
)


@dataclass(frozen=True)
class MonthlyPostSetting:
    enabled: bool = False
    kind: ContentKind = DEFAULT_KIND


def parse_kind(kind: str | ContentKind) -> ContentKind:
    """The boundary check: a kind «Crear pieza» offers, else `ValueError`."""
    try:
        parsed = ContentKind(kind)
    except ValueError:
        raise ValueError(f"unknown piece kind {kind!r}") from None
    if not parsed.is_offered:
        raise ValueError(f"piece kind {parsed.value!r} is not offered for the monthly post")
    return parsed


def _from_document(value: Any) -> MonthlyPostSetting:
    """A stored value read back; anything malformed reads as the default (off)."""
    if not isinstance(value, dict):
        return MonthlyPostSetting()
    try:
        kind = parse_kind(value.get("kind", DEFAULT_KIND))
    except ValueError:
        kind = DEFAULT_KIND
    return MonthlyPostSetting(enabled=value.get("enabled") is True, kind=kind)


def get_monthly_post_setting(
    tenant_id: UUID, brand_id: UUID, *, store: BrandKitStore | None = None
) -> MonthlyPostSetting:
    connect = (store or BrandKitStore()).load_details(tenant_id=tenant_id, brand_id=brand_id)
    return _from_document(connect.connect.get(MONTHLY_POST_KEY))


def set_monthly_post_setting(
    tenant_id: UUID,
    brand_id: UUID,
    enabled: bool,
    kind: str | ContentKind,
    *,
    store: BrandKitStore | None = None,
) -> MonthlyPostSetting:
    """Validate and save; idempotent (the same call twice leaves the same row)."""
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a bool")
    setting = MonthlyPostSetting(enabled=enabled, kind=parse_kind(kind))
    (store or BrandKitStore()).set_document_key(
        tenant_id=tenant_id,
        brand_id=brand_id,
        document=MONTHLY_POST_DOCUMENT,
        key=MONTHLY_POST_KEY,
        value={"enabled": setting.enabled, "kind": setting.kind.value},
    )
    return setting

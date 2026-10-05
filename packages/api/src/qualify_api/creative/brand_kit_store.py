"""What finishing the Brand Kit keeps beyond `brand_kits` (§ request 2026-10-01; 0033):
the brandboard's files and the wizards' own answers.

- **Assets** (`brand_kit_assets`): the logo, its versions, the other elements and the
  font files (0038), each a file already in R2 under the tenant's prefix — this module
  stores only the record, the caller uploads. `replace_assets` makes the stored set equal
  to the one given (what the operator removed goes), and points
  `brand_kits.logo_asset_key` at the main logo.
- **Details** (`brand_kit_details`): `logo_brief`, `connect` and `profile`, each a JSON
  document. `save_details` writes only the documents it is given, so a screen that
  never saw the connect flow (the manual wizard) cannot erase what it saved."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from qualify_shared.objects.keys import require_tenant_prefix
from sqlalchemy import select

from qualify_api.creative.models import BrandKit as BrandKitRow
from qualify_api.creative.models import BrandKitAsset as AssetRow
from qualify_api.creative.models import BrandKitDetails as DetailsRow

LOGO = "logo"
LOGO_VERSION = "logo_version"
EXTRA = "extra"
#: A font file of Tu brandboard's typography tiles (slot `heading` / `body`, 0038).
FONT = "font"
ASSET_KINDS = frozenset({LOGO, LOGO_VERSION, EXTRA, FONT})
#: Which file is "the logo" of the brand (`brand_kits.logo_asset_key`, what a flyer
#: stamps): a standalone logo first, then the versions that carry the whole mark.
MAIN_LOGO_ORDER: tuple[tuple[str, str], ...] = (
    (LOGO, ""),
    (LOGO_VERSION, "imagotipo"),
    (LOGO_VERSION, "logotipo"),
    (LOGO_VERSION, "isologo"),
    (LOGO_VERSION, "isotipo"),
)
DETAIL_DOCUMENTS = ("logo_brief", "connect", "profile")


@dataclass(frozen=True)
class BrandAsset:
    kind: str
    slot: str
    object_key: str
    filename: str = ""
    content_type: str = ""
    label: str = ""
    context: str = ""
    position: int = 0


@dataclass(frozen=True)
class BrandKitDetails:
    logo_brief: dict[str, Any] = field(default_factory=dict)
    connect: dict[str, Any] = field(default_factory=dict)
    profile: dict[str, Any] = field(default_factory=dict)


def brand_asset_prefix(tenant_id: UUID, brand_id: UUID) -> str:
    """Where a brand's brandboard files live in R2 (inside the tenant's prefix)."""
    return f"t/{tenant_id}/brand/{brand_id}/"


def main_logo_key(assets: Iterable[BrandAsset]) -> str | None:
    by_slot = {(a.kind, a.slot): a.object_key for a in assets}
    for slot in MAIN_LOGO_ORDER:
        if slot in by_slot:
            return by_slot[slot]
    return None


def _asset(row: AssetRow) -> BrandAsset:
    return BrandAsset(
        kind=row.kind,
        slot=row.slot,
        object_key=row.object_key,
        filename=row.filename,
        content_type=row.content_type,
        label=row.label,
        context=row.context,
        position=row.position,
    )


class BrandKitStore:
    def list_assets(self, *, tenant_id: UUID, brand_id: UUID) -> list[BrandAsset]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(AssetRow)
                .where(AssetRow.brand_id == brand_id)
                .order_by(AssetRow.kind, AssetRow.position, AssetRow.slot)
            ).all()
            return [_asset(row) for row in rows]

    def replace_assets(
        self, *, tenant_id: UUID, brand_id: UUID, assets: Iterable[BrandAsset]
    ) -> str | None:
        """The brand's brandboard becomes exactly `assets`; returns the main logo's key
        (also written to `brand_kits.logo_asset_key` when the brand has a kit). Every
        key must already sit under this tenant's R2 prefix."""
        wanted: dict[tuple[str, str], BrandAsset] = {}
        for asset in assets:
            if asset.kind not in ASSET_KINDS:
                raise ValueError(f"unknown brand asset kind {asset.kind!r}")
            require_tenant_prefix(tenant_id, asset.object_key)
            wanted[(asset.kind, asset.slot)] = asset
        now = datetime.now(UTC)
        with tenant_session(tenant_id) as session:
            rows = {
                (row.kind, row.slot): row
                for row in session.scalars(
                    select(AssetRow).where(AssetRow.brand_id == brand_id)
                ).all()
            }
            for slot, row in rows.items():
                if slot not in wanted:
                    session.delete(row)
            for slot, asset in wanted.items():
                row = rows.get(slot)
                if row is None:
                    row = AssetRow(tenant_id=tenant_id, brand_id=brand_id, kind=asset.kind)
                    session.add(row)
                row.slot = asset.slot
                row.object_key = asset.object_key
                row.filename = asset.filename
                row.content_type = asset.content_type
                row.label = asset.label
                row.context = asset.context
                row.position = asset.position
                row.updated_at = now
            logo = main_logo_key(wanted.values())
            kit = session.scalar(select(BrandKitRow).where(BrandKitRow.brand_id == brand_id))
            if kit is not None:
                kit.logo_asset_key = logo
            session.flush()
            return logo

    def load_details(self, *, tenant_id: UUID, brand_id: UUID) -> BrandKitDetails:
        with tenant_session(tenant_id) as session:
            row = session.get(DetailsRow, brand_id)
            if row is None:
                return BrandKitDetails()
            return BrandKitDetails(
                logo_brief=dict(row.logo_brief or {}),
                connect=dict(row.connect or {}),
                profile=dict(row.profile or {}),
            )

    def save_details(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        user_id: UUID | None,
        documents: Mapping[str, Mapping[str, Any]],
    ) -> None:
        """Write the given documents (any of `logo_brief`/`connect`/`profile`); the
        others keep what they had."""
        unknown = set(documents) - set(DETAIL_DOCUMENTS)
        if unknown:
            raise ValueError(f"unknown brand kit documents {sorted(unknown)}")
        with tenant_session(tenant_id) as session:
            row = session.get(DetailsRow, brand_id)
            if row is None:
                row = DetailsRow(
                    brand_id=brand_id,
                    tenant_id=tenant_id,
                    logo_brief={},
                    connect={},
                    profile={},
                )
                session.add(row)
            for name, document in documents.items():
                setattr(row, name, dict(document))
            row.updated_by = user_id
            row.updated_at = datetime.now(UTC)
            session.flush()

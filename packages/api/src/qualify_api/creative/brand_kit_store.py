"""What finishing the Brand Kit keeps beyond `brand_kits` (§ request 2026-10-01; 0033):
the brandboard's files and the wizards' own answers.

- **Assets** (`brand_kit_assets`): the logo, its versions, the other elements and the
  font files (0043), each a file already in R2 under the tenant's prefix — this module
  stores only the record, the caller uploads. `replace_assets` makes the stored set equal
  to the one given (what the operator removed goes), and points
  `brand_kits.logo_asset_key` at the main logo.
- **Details** (`brand_kit_details`): `logo_brief`, `connect` and `profile`, each a JSON
  document. `save_details` writes only the documents it is given, so a screen that
  never saw the connect flow (the manual wizard) cannot erase what it saved.
- **Avatar** (`load_avatar` / `save_avatar`): the generated brand avatar's record, a
  reserved key inside `logo_brief` that the wizards' saves carry over untouched."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
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
#: A font file of Tu brandboard's typography tiles (slot `heading` / `body`, 0043).
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
#: The brand's generated avatar (`creative.brand_avatar`, docs/brand-kit-avatar-animado.md):
#: its record rides as ONE reserved key of the `logo_brief` document — the brand's image,
#: next to the logo it is drawn from — so no migration is needed. The wizards rewrite
#: `logo_brief` whole on every save, which is why `save_details` carries this key over.
AVATAR_DOCUMENT = "logo_brief"
AVATAR_KEY = "brand_avatar"
#: Keys a document keeps across `save_details` unless the caller writes them itself:
#: they are written by another path (a background generation), not by the wizards.
#: `connect.prefill` (m-24852197) is the Brand Kit proposed from the account
#: (`creative.brand_prefill`): written in the background and reviewed by the owner, so a
#: wizard's save of its own answers must not erase it.
PREFILL_DOCUMENT = "connect"
PREFILL_KEY = "prefill"
RESERVED_DETAIL_KEYS: dict[str, tuple[str, ...]] = {
    AVATAR_DOCUMENT: (AVATAR_KEY,),
    PREFILL_DOCUMENT: (PREFILL_KEY,),
}


def carry_reserved(
    name: str, stored: Mapping[str, Any] | None, document: Mapping[str, Any]
) -> dict[str, Any]:
    """`document` as it will be written over `stored`: every reserved key of `name` the
    caller did not send keeps its stored value."""
    out = dict(document)
    for key in RESERVED_DETAIL_KEYS.get(name, ()):
        if key not in out and stored and key in stored:
            out[key] = stored[key]
    return out


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
            # locked: a background write of one reserved key (`set_document_key`) must not
            # land between this read and this write and be carried away
            row = session.get(DetailsRow, brand_id, with_for_update=True)
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
                setattr(row, name, carry_reserved(name, getattr(row, name), document))
            row.updated_by = user_id
            row.updated_at = datetime.now(UTC)
            session.flush()

    def set_document_key(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        document: str,
        key: str,
        value: Any,
        keep_current: Callable[[Any], bool] | None = None,
    ) -> bool:
        """Write ONE key of one document (e.g. `connect.prefill`), the rest of it exactly
        as it is in the database at this moment: read under `FOR UPDATE` and written in
        the same transaction, so an owner's save in between is never overwritten with
        what a background job read earlier (m-24852197). `keep_current(stored value)`
        True keeps what is stored, under the same lock (m-24852199: a decided proposal
        is never put back to `proposed`). True when the value was written."""
        if document not in DETAIL_DOCUMENTS:
            raise ValueError(f"unknown brand kit document {document!r}")
        with tenant_session(tenant_id) as session:
            row = session.get(DetailsRow, brand_id, with_for_update=True)
            if row is None:
                row = DetailsRow(
                    brand_id=brand_id,
                    tenant_id=tenant_id,
                    logo_brief={},
                    connect={},
                    profile={},
                )
                session.add(row)
            current = (getattr(row, document) or {}).get(key)
            if keep_current is not None and keep_current(current):
                return False
            setattr(row, document, {**(getattr(row, document) or {}), key: value})
            row.updated_at = datetime.now(UTC)
            session.flush()
            return True

    def load_avatar(self, *, tenant_id: UUID, brand_id: UUID) -> dict[str, Any] | None:
        """The brand avatar's stored record (`creative.brand_avatar.BrandAvatar`), or None."""
        with tenant_session(tenant_id) as session:
            row = session.get(DetailsRow, brand_id)
            record = (getattr(row, AVATAR_DOCUMENT) or {}).get(AVATAR_KEY) if row else None
            return dict(record) if isinstance(record, dict) else None

    def save_avatar(
        self, *, tenant_id: UUID, brand_id: UUID, record: Mapping[str, Any] | None
    ) -> None:
        """Write (or, with None, drop) the avatar's record; the rest of its document stays."""
        if record is not None and record.get("object_key"):
            require_tenant_prefix(tenant_id, str(record["object_key"]))
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
            document = {
                k: v for k, v in (getattr(row, AVATAR_DOCUMENT) or {}).items() if k != AVATAR_KEY
            }
            if record is not None:
                document[AVATAR_KEY] = dict(record)
            setattr(row, AVATAR_DOCUMENT, document)
            row.updated_at = datetime.now(UTC)
            session.flush()

"""Brand kit persistence (MC-02, reduced scope; design §4.4).

`BrandKitService` is the write/read door for the single `brand_kits` row a brand owns.
The contract that matters is round-trip fidelity: a `qualify_creative.BrandKit` written
through `upsert_kit` and read back through `get_kit` must be equal field-for-field —
the pydantic model is the source of truth and the JSONB/array columns are storage, not
a second schema anyone reasons about.

Serialization is deterministic on purpose (sets are sorted before dumping): the same
kit always produces the same stored bytes, which keeps diffs of consecutive upserts
meaningful and keeps `render_prompt`'s cacheable-prefix promise intact downstream.

House rules mirrored from `connections/service.py` / `publishing/service.py`: identity
(`tenant_id`, `user_id`) is always an explicit keyword-only argument, never ambient,
and every row touched goes through the sanctioned `tenant_session` door.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from qualify_creative.schemas import BrandKit, ImagePolicy
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative.models import BrandKit as BrandKitRow


def _dump_image_policy(policy: ImagePolicy) -> dict:
    """JSONB shape for `ImagePolicy`. The frozenset is sorted so the same policy always
    serializes to the same bytes — frozenset iteration order is not deterministic."""
    return {
        "allowed_routes": sorted(route.value for route in policy.allowed_routes),
        "blocked_reason": {
            route.value: reason for route, reason in sorted(policy.blocked_reason.items())
        },
    }


def _apply_kit(row: BrandKitRow, kit: BrandKit) -> None:
    """Copy every pydantic field onto its column. `photo_recipe` is deliberately not
    touched: the pydantic `BrandKit` does not carry it (D17/D18 params are written by
    a different flow), and an upsert must not erase what it does not model."""
    row.positioning = kit.positioning
    row.audience = kit.audience
    row.language = kit.language
    row.regional_variant = kit.regional_variant
    row.tone_axes = kit.tone_axes.model_dump()
    row.do_examples = list(kit.do_examples)
    row.dont_examples = list(kit.dont_examples)
    row.banned_words = list(kit.banned_words)
    row.forbidden_claims = list(kit.forbidden_claims)
    row.emoji_policy = kit.emoji_policy.value
    row.hashtag_policy = kit.hashtag_policy.model_dump(mode="json")
    row.cta_patterns = list(kit.cta_patterns)
    row.length_targets = kit.length_targets.model_dump()
    row.palette_rgb = list(kit.palette_rgb)
    row.font_heading = kit.font_heading or None
    row.font_body = kit.font_body or None
    row.logo_asset_key = kit.logo_asset_key
    row.template_asset_key = kit.template_asset_key
    row.reference_image_keys = list(kit.reference_image_keys)
    row.image_policy = _dump_image_policy(kit.image_policy)


def kit_from_row(row: BrandKitRow) -> BrandKit:
    """Rehydrate the pydantic kit from a row `upsert_kit` wrote.

    Collections tolerate NULL (a row provisioned by other means), but the three fields
    the schema requires (`positioning`, `audience`, `tone_axes`) rehydrate strictly:
    a row missing them was not written by this service and pydantic's ValidationError
    is the honest answer, not a silently invented default.
    """
    data: dict[str, object] = {
        "brand_id": row.brand_id,
        "positioning": row.positioning if row.positioning is not None else "",
        "audience": row.audience if row.audience is not None else "",
        "language": row.language,
        "tone_axes": row.tone_axes,
        "do_examples": tuple(row.do_examples or ()),
        "dont_examples": tuple(row.dont_examples or ()),
        "banned_words": tuple(row.banned_words or ()),
        "forbidden_claims": tuple(row.forbidden_claims or ()),
        "cta_patterns": tuple(row.cta_patterns or ()),
        "palette_rgb": tuple(row.palette_rgb or ()),
        "font_heading": row.font_heading or "",
        "font_body": row.font_body or "",
        "logo_asset_key": row.logo_asset_key,
        "template_asset_key": row.template_asset_key,
        "reference_image_keys": tuple(row.reference_image_keys or ()),
    }
    # Optional-with-default fields: omit when NULL so the pydantic default applies
    # instead of feeding None into a non-optional field.
    if row.regional_variant is not None:
        data["regional_variant"] = row.regional_variant
    if row.emoji_policy is not None:
        data["emoji_policy"] = row.emoji_policy
    if row.hashtag_policy is not None:
        data["hashtag_policy"] = row.hashtag_policy
    if row.length_targets is not None:
        data["length_targets"] = row.length_targets
    if row.image_policy is not None:
        data["image_policy"] = row.image_policy
    return BrandKit.model_validate(data)


class BrandKitService:
    """CRUD-of-one for the brand kit. One row per brand (`uq_brand_kits_brand`); the
    upsert is insert-or-update, never a second row."""

    def upsert_kit(self, *, tenant_id: UUID, brand_id: UUID, kit: BrandKit, user_id: UUID) -> None:
        """Insert or update the brand's single kit row from the pydantic kit.

        `user_id` is part of the service contract (§4.4: every mutation names who did
        it) even though `brand_kits` carries no author column yet — when an audit
        column lands this signature does not change.
        """
        if kit.brand_id != brand_id:
            raise ValueError("kit.brand_id does not match the brand_id argument")
        with tenant_session(tenant_id) as session:
            row = session.scalar(select(BrandKitRow).where(BrandKitRow.brand_id == brand_id))
            if row is None:
                row = BrandKitRow(tenant_id=tenant_id, brand_id=brand_id, language=kit.language)
                session.add(row)
            _apply_kit(row, kit)
            row.updated_at = datetime.now(UTC)
            session.flush()

    def get_kit(self, *, tenant_id: UUID, brand_id: UUID) -> BrandKit | None:
        """The stored kit, rehydrated; None when the brand has none yet."""
        with tenant_session(tenant_id) as session:
            row = session.scalar(select(BrandKitRow).where(BrandKitRow.brand_id == brand_id))
            if row is None:
                return None
            return kit_from_row(row)

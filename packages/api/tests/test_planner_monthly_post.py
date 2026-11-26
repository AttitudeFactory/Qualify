"""«Publicación del mes» setting (m-25120704) — offline, with an in-memory store."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentKind

from qualify_api.creative.brand_kit_store import BrandKitDetails, carry_reserved
from qualify_api.planner.monthly_post import (
    MONTHLY_POST_KINDS,
    MonthlyPostSetting,
    get_monthly_post_setting,
    set_monthly_post_setting,
)


class FakeStore:
    def __init__(self) -> None:
        self.docs: dict[tuple[UUID, UUID], dict[str, Any]] = {}

    def load_details(self, *, tenant_id: UUID, brand_id: UUID) -> BrandKitDetails:
        return BrandKitDetails(connect=dict(self.docs.get((tenant_id, brand_id), {})))

    def set_document_key(self, *, tenant_id, brand_id, document, key, value) -> bool:  # noqa: ANN001
        assert document == "connect"
        self.docs.setdefault((tenant_id, brand_id), {})[key] = value
        return True


T, B = uuid4(), uuid4()


def test_default_is_off_with_the_advertising_image() -> None:
    assert get_monthly_post_setting(T, B, store=FakeStore()) == MonthlyPostSetting(
        enabled=False, kind=ContentKind.STATIC_FLYER
    )


def test_set_then_get_round_trips_per_brand() -> None:
    store = FakeStore()
    set_monthly_post_setting(T, B, True, "carousel", store=store)
    assert get_monthly_post_setting(T, B, store=store) == MonthlyPostSetting(
        True, ContentKind.CAROUSEL
    )
    assert get_monthly_post_setting(T, uuid4(), store=store).enabled is False


@pytest.mark.parametrize("kind", ["nope", "shot_video", "own_media", ""])
def test_kind_is_validated_at_the_boundary(kind: str) -> None:
    store = FakeStore()
    with pytest.raises(ValueError):
        set_monthly_post_setting(T, B, True, kind, store=store)
    assert store.docs == {}


def test_enabled_must_be_a_bool() -> None:
    with pytest.raises(ValueError):
        set_monthly_post_setting(T, B, "yes", "clip", store=FakeStore())  # type: ignore[arg-type]


def test_malformed_stored_value_reads_as_default() -> None:
    store = FakeStore()
    store.docs[(T, B)] = {"monthly_post": {"enabled": "true", "kind": "own_media"}}
    assert get_monthly_post_setting(T, B, store=store) == MonthlyPostSetting()


def test_kinds_are_what_crear_pieza_offers() -> None:
    assert ContentKind.STATIC_FLYER in MONTHLY_POST_KINDS
    assert ContentKind.SHOT_VIDEO not in MONTHLY_POST_KINDS
    assert ContentKind.OWN_MEDIA not in MONTHLY_POST_KINDS


def test_the_setting_survives_a_wizard_save() -> None:
    stored = {"city": "Bogotá", "monthly_post": {"enabled": True, "kind": "clip"}}
    written = carry_reserved("connect", stored, {"city": "Cúcuta"})
    assert written["monthly_post"] == {"enabled": True, "kind": "clip"}

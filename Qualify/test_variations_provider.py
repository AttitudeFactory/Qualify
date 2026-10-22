"""`variations_provider` (ticket 24803289, PR 4) against a scripted `AngleSetService`
— no DB, no network: catalog-only product ids, each wrapper delegating with typed ids
and returning view models, the render health check (cached, never hanging), and R2
preview URLs that degrade to "" instead of failing the page."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.catalog.service import UnknownProduct
from qualify_api.creative.angle_sets import (
    ANGLE_QUEUED,
    SET_GENERATING,
    AngleRecord,
    AngleSetDetail,
    AngleSetRecord,
    AngleView,
    GenerationOutcome,
)
from qualify_creative.angles import PRESETS, AngleProduct, AngleSetPlan
from qualify_creative.enums import DraftStatus

from . import variations_provider as provider

TENANT, BRAND, USER = uuid4(), uuid4(), uuid4()


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.set_id = uuid4()
        self.draft_key = f"generated/{TENANT}/x/slide-1.jpg"

    def _record(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))

    def product_presets(self, **kw: Any) -> Any:
        self._record("product_presets", **kw)
        facts = AngleProduct(product_id=kw["product_id"], name="Shawarma", photo_keys=())
        return facts, tuple(
            (p, "necesita una foto" if p.needs_render_service else None) for p in PRESETS
        )

    def plan(self, count: int) -> AngleSetPlan:
        self._record("plan", count=count)
        return AngleSetPlan(count=count, image_unit_usd=Decimal("0.035"))

    def create_set(self, **kw: Any) -> UUID:
        self._record("create_set", **kw)
        return self.set_id

    def list_sets(self, **kw: Any) -> tuple[AngleSetRecord, ...]:
        self._record("list_sets", **kw)
        return (self._set(),)

    def detail(self, **kw: Any) -> AngleSetDetail:
        self._record("detail", **kw)
        angle = AngleRecord(
            id=uuid4(),
            set_id=self.set_id,
            position=1,
            title="t",
            scene="s",
            composition="c",
            hook="h",
            cta="c",
            rationale="r",
            status=ANGLE_QUEUED,
            draft_id=uuid4(),
        )
        view = AngleView(
            angle=angle, draft_status=DraftStatus.DRAFTING.value, preview_key=self.draft_key
        )
        return AngleSetDetail(set=self._set(status=SET_GENERATING), angles=(view,))

    def discard_angle(self, **kw: Any) -> None:
        self._record("discard_angle", **kw)

    def restore_angle(self, **kw: Any) -> None:
        self._record("restore_angle", **kw)

    def edit_angle(self, **kw: Any) -> None:
        self._record("edit_angle", **kw)

    def regenerate_angle(self, **kw: Any) -> UUID:
        self._record("regenerate_angle", **kw)
        return uuid4()

    def generate_pieces(self, **kw: Any) -> GenerationOutcome:
        self._record("generate_pieces", **kw)
        return GenerationOutcome(queued=(uuid4(),))

    def retry_angle(self, **kw: Any) -> UUID:
        self._record("retry_angle", **kw)
        return uuid4()

    def approve_angle(self, **kw: Any) -> None:
        self._record("approve_angle", **kw)

    def _set(self, **fields: Any) -> AngleSetRecord:
        base: dict[str, Any] = {
            "id": self.set_id,
            "tenant_id": TENANT,
            "brand_id": BRAND,
            "product_id": uuid4(),
            "preset_key": "escena_producto",
            "requested_count": 10,
            "status": "angles_ready",
            "product_name": "Shawarma",
            "price_label": "",
            "price_missing": True,
            "created_at": datetime(2026, 10, 21, tzinfo=UTC),
        }
        base.update(fields)
        return AngleSetRecord(**base)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> FakeService:
    fake = FakeService()
    monkeypatch.setattr(provider, "_service", lambda: fake)
    monkeypatch.setattr(provider, "_render_health", None)
    return fake


@pytest.mark.parametrize("raw", ["", "  ", "stock:abc", f"t/{uuid4()}/stock/x/y.jpg", "nope"])
def test_only_catalog_product_ids_are_accepted(raw: str) -> None:
    with pytest.raises(UnknownProduct):
        provider.catalog_product_id(raw)
    product_id = uuid4()
    assert provider.catalog_product_id(f" {product_id} ") == product_id


def test_a_stock_pick_never_reaches_the_service(service: FakeService) -> None:
    with pytest.raises(UnknownProduct):
        provider.create_variation_set(TENANT, BRAND, USER, "stock:abc", "escena_producto")
    assert service.calls == []


def test_presets_combine_the_product_and_the_render_service(
    service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(provider, "render_ready", lambda **_kw: True)
    product_id = uuid4()
    check, presets = provider.variation_presets(TENANT, BRAND, str(product_id))
    assert service.calls[0] == (
        "product_presets",
        {"tenant_id": TENANT, "brand_id": BRAND, "product_id": product_id},
    )
    assert check.price_missing and check.photo_count == 0
    by_key = {p.key: p for p in presets}
    assert by_key["escena_producto"].available
    assert not by_key["plantilla_promo"].available and "foto" in by_key["plantilla_promo"].reason


def test_every_wrapper_delegates_with_typed_ids(service: FakeService) -> None:
    product_id, angle_id = uuid4(), uuid4()
    set_id = provider.create_variation_set(
        TENANT, BRAND, USER, str(product_id), "escena_producto", count=10
    )
    assert set_id == str(service.set_id)
    provider.discard_variation_angle(TENANT, str(angle_id), USER)
    provider.restore_variation_angle(TENANT, str(angle_id))
    provider.edit_variation_angle(TENANT, str(angle_id), "otra escena", "plano medio")
    outcome = provider.generate_variation_pieces(TENANT, set_id, USER, [str(angle_id)])
    provider.retry_variation_angle(TENANT, str(angle_id), USER)
    new_draft = provider.regenerate_variation_angle(TENANT, str(angle_id), USER)
    provider.approve_variation_angle(TENANT, str(angle_id), USER)
    names = [name for name, _ in service.calls]
    assert names == [
        "create_set",
        "discard_angle",
        "restore_angle",
        "edit_angle",
        "generate_pieces",
        "retry_angle",
        "regenerate_angle",
        "approve_angle",
    ]
    create = service.calls[0][1]
    assert create["product_id"] == product_id and create["preset_key"] == "escena_producto"
    assert service.calls[1][1]["user_id"] == USER
    assert service.calls[3][1]["scene"] == "otra escena"
    assert service.calls[4][1]["angle_ids"] == [angle_id]
    assert isinstance(new_draft, str) and UUID(new_draft)
    assert all(
        kw.get("angle_id", angle_id) == angle_id for _, kw in service.calls if "angle_id" in kw
    )
    assert outcome.queued == 1 and outcome.tone == "ok"


def test_the_set_detail_resolves_r2_previews_and_survives_a_token_failure(
    service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(provider, "is_r2_key", lambda key: True)
    monkeypatch.setattr(provider, "issue_view_path", lambda t, key, kind: f"/r2media/{key}")
    vm = provider.variation_set_detail(TENANT, str(service.set_id))
    assert vm.angles[0].preview_url == f"/r2media/{service.draft_key}"
    assert vm.price_missing and vm.status_label == "Generando piezas"

    def broken(*_args: Any) -> str:
        raise RuntimeError("redis down")

    monkeypatch.setattr(provider, "issue_view_path", broken)
    again = provider.variation_set_detail(TENANT, str(service.set_id))
    assert again.angles[0].preview_url == "" and again.angles[0].preview_key


def test_a_local_key_is_left_to_the_upload_url(
    service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(provider, "is_r2_key", lambda key: False)
    vm = provider.variation_set_detail(TENANT, str(service.set_id))
    assert vm.angles[0].preview_url == "" and vm.angles[0].preview_key == service.draft_key


def test_listing_and_plan_return_view_models(service: FakeService) -> None:
    (summary,) = provider.list_variation_sets(TENANT, BRAND)
    assert summary.id == str(service.set_id) and summary.product_name == "Shawarma"
    assert provider.variation_plan(10).count == 10


class _Health:
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.calls = 0

    def __call__(self) -> Any:
        self.calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return self

    def health(self) -> dict[str, Any]:
        return self.answer


def test_render_health_is_cached_and_an_unreachable_service_is_just_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider, "_render_health", None)
    now = [100.0]
    healthy = _Health({"ok": True})
    assert provider.render_ready(clock=lambda: now[0], client_factory=healthy)
    now[0] += 30
    assert provider.render_ready(clock=lambda: now[0], client_factory=healthy)
    assert healthy.calls == 1  # within the TTL: no second network call
    now[0] += provider.RENDER_HEALTH_TTL_SECONDS
    down = _Health(ConnectionError("refused"))
    assert not provider.render_ready(clock=lambda: now[0], client_factory=down)
    assert down.calls == 1

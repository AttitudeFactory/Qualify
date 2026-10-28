"""Tests for «Variaciones» (`variations_state`), the Crear pieza option of m-24803289.

No DB and no Claude: the provider functions the state calls are replaced with
stand-ins, and `_session_ids` is monkeypatched on the CLASS (see
`test_creative_state.py`'s module docstring for why it has to be the class).
Background handlers are driven through `.fn(state)`, like `test_catalog_state.py`.

Pins:
1. The picker only offers the catalog, and says so when the catalog is empty.
2. Choosing a product fills what the engine sees — photos, the price it will print, the
   «no price» note — and preselects the first preset that can actually be used.
3. A preset that cannot be used is never selected, and «Generar» stays off while the
   chosen one is unavailable: the screen never offers a paid call it cannot make.
4. The paid Claude call happens ONCE: a second click while it is in flight is ignored.
5. A failure of that call leaves the screen usable, with the service's own Spanish text.
6. Discarding an angle re-reads the set — the service decides the new state, not the
   screen — and a second action while one is in flight is ignored.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from qualify_api.catalog.service import UnknownProduct
from qualify_creative.angles import UnknownPreset

from . import variations_state as module
from .variations_state import VariationsState
from .variations_vm import AngleVM, PlanVM, PresetVM, ProductCheckVM, SetVM

_TENANT_ID = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND_ID = UUID("b0000000-0000-4000-8000-000000000001")
_USER_ID = UUID("c0000000-0000-4000-8000-000000000001")
_PRODUCT_ID = "d0000000-0000-4000-8000-000000000001"
_SET_ID = "e0000000-0000-4000-8000-000000000001"
_ANGLE_ID = "f0000000-0000-4000-8000-000000000001"

_ROWS = (
    {
        "id": _PRODUCT_ID,
        "name": "Shawarma mixto",
        "photo_key": "t/x/catalog/1.jpg",
        "photo_count": "2",
        "video_count": "0",
        "counts_label": "2 fotos",
        "photo_keys": "t/x/catalog/1.jpg",
        "video_keys": "",
    },
)


def _preset(key: str = "scene_feed", *, available: bool = True, reason: str = "") -> PresetVM:
    return PresetVM(
        key=key,
        name="Escena 4:5",
        description="Una foto publicitaria del producto.",
        format_label="4:5",
        icon="image",
        available=available,
        reason=reason,
    )


def _check(*, price_missing: bool = False) -> ProductCheckVM:
    return ProductCheckVM(
        name="Shawarma mixto",
        photo_count=2,
        price_label="" if price_missing else "$18.000",
        price_missing=price_missing,
        price_note="Este producto no tiene precio en el catálogo." if price_missing else "",
    )


def _angle(angle_id: str = _ANGLE_ID, **kw: Any) -> AngleVM:
    base: dict[str, Any] = {
        "id": angle_id,
        "position": 1,
        "title": "En la mesa del almuerzo",
        "scene": "Mesa de madera, luz natural",
        "composition": "Plano cenital",
        "hook": "Tu almuerzo, resuelto",
        "cta": "Pídelo hoy",
        "rationale": "El momento de consumo real",
        "status": "proposed",
        "status_label": "Propuesto",
        "status_tone": "neutral",
        "draft_id": "",
        "draft_status": "",
        "draft_label": "",
        "draft_tone": "",
        "preview_key": "",
        "preview_url": "",
        "copy_hook": "",
        "copy_caption": "",
        "price_conflicts": (),
        "warnings": (),
        "failure_text": "",
        "can_discard": True,
        "can_restore": False,
        "can_retry": False,
        "can_approve": False,
        "can_edit": True,
        "can_regenerate": False,
    }
    base.update(kw)
    return AngleVM(**base)


def _set_vm(*angles: AngleVM) -> SetVM:
    kept = angles or (_angle(),)
    return SetVM(
        id=_SET_ID,
        product_name="Shawarma mixto",
        preset_key="scene_feed",
        status="angles_ready",
        status_label="Ángulos listos",
        status_tone="ok",
        price_label="$18.000",
        price_missing=False,
        price_note="",
        failure_text="",
        campaign_id="",
        pending_count=len(kept),
        kept_count=len(kept),
        angles=tuple(kept),
    )


async def _fake_session_ids(self: VariationsState) -> tuple[UUID, UUID, UUID]:
    return (_TENANT_ID, _BRAND_ID, _USER_ID)


async def _drain(events):
    return [event async for event in events]


def _state(monkeypatch: pytest.MonkeyPatch) -> VariationsState:
    monkeypatch.setattr(VariationsState, "_session_ids", _fake_session_ids)
    return VariationsState()


# ---------------------------------------------------------------------------
# 1. the picker


async def test_load_fills_the_catalog_picker(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch)
    monkeypatch.setattr(module, "catalog_products", lambda *_: _ROWS)
    await VariationsState.load.fn(state)
    assert state.has_products and state.products[0]["name"] == "Shawarma mixto"
    assert state.error == "" and not state.products_loading
    assert state.products_loaded


async def test_an_empty_catalog_says_where_to_add_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    monkeypatch.setattr(module, "catalog_products", lambda *_: ())
    await VariationsState.load.fn(state)
    assert not state.has_products
    assert state.products_loaded
    assert "Tus productos" in state.error


async def test_loading_and_failed_reads_never_claim_the_catalog_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    assert not state.products_loaded

    def fail_read(*_args):
        assert state.products_loading
        assert not state.products_loaded
        raise RuntimeError("offline")

    monkeypatch.setattr(module, "catalog_products", fail_read)
    await VariationsState.load.fn(state)
    assert not state.products_loading and not state.products_loaded
    assert state.error == module._LOAD_FAILED


# ---------------------------------------------------------------------------
# 2. the product


async def test_choosing_a_product_shows_what_the_engine_sees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    blocked = _preset("template", available=False, reason="Sin fotos")
    monkeypatch.setattr(module, "variation_presets", lambda *_: (_check(), (blocked, _preset())))
    images = "10 publicaciones · usan hasta 10 de tus creaciones"
    monkeypatch.setattr(module, "variation_plan", lambda: PlanVM(10, images, "nota"))
    await VariationsState.choose_product.fn(state, _PRODUCT_ID)
    assert state.product_name == "Shawarma mixto" and state.product_photo_count == 2
    assert state.price_label == "$18.000" and not state.price_missing
    assert state.plan_count == 10 and state.plan_images_label == images
    # the unavailable preset is never the preselected one
    assert state.preset_key == "scene_feed"
    assert state.photo_count_label == "2 fotos" and state.plan_count_label == "10 ángulos"


async def test_a_product_without_price_carries_its_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    monkeypatch.setattr(
        module, "variation_presets", lambda *_: (_check(price_missing=True), (_preset(),))
    )
    monkeypatch.setattr(module, "variation_plan", lambda: PlanVM(10, "10 imágenes", "nota"))
    await VariationsState.choose_product.fn(state, _PRODUCT_ID)
    assert state.price_missing and state.price_note
    assert state.photo_count_label == "2 fotos"


async def test_a_product_outside_the_catalog_is_refused_in_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)

    def _raise(*_: Any) -> None:
        raise UnknownProduct("stock:123")

    monkeypatch.setattr(module, "variation_presets", _raise)
    await VariationsState.choose_product.fn(state, "stock:123")
    assert state.product_id == "" and not state.checking
    assert "catálogo" in state.error


# ---------------------------------------------------------------------------
# 3. the preset and the gate on «Generar»


async def test_an_unavailable_preset_is_never_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch)
    state.presets = [_preset("template", available=False, reason="Sin fotos")]
    state.preset_key = ""
    VariationsState.choose_preset.fn(state, "template")
    assert state.preset_key == ""


async def test_generar_is_off_until_product_and_available_preset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    assert not state.can_create
    state.product_id = _PRODUCT_ID
    state.presets = [_preset("template", available=False, reason="Sin fotos")]
    state.preset_key = "template"
    assert not state.can_create
    state.presets = [*state.presets, _preset()]
    state.preset_key = "scene_feed"
    assert state.can_create
    state.creating = True
    assert not state.can_create


# ---------------------------------------------------------------------------
# 4 and 5. the one paid call


async def test_the_claude_call_is_made_once_and_fills_the_angles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.product_id, state.preset_key = _PRODUCT_ID, "scene_feed"
    state.presets = [_preset()]
    calls: list[tuple[Any, ...]] = []

    def _create(*args: Any) -> str:
        calls.append(args)
        return _SET_ID

    monkeypatch.setattr(module, "create_variation_set", _create)
    monkeypatch.setattr(module, "variation_set_detail", lambda *_: _set_vm())
    await VariationsState.create_set.fn(state)
    assert calls == [(_TENANT_ID, _BRAND_ID, _USER_ID, _PRODUCT_ID, "scene_feed")]
    assert state.set_id == _SET_ID and state.has_set
    assert len(state.angles) == 1 and state.angles[0].title == "En la mesa del almuerzo"
    assert state.set_status_label == "Ángulos listos" and state.kept_label == "1 ángulo en pie"
    assert not state.creating


async def test_a_second_click_while_generating_is_not_paid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.product_id, state.preset_key = _PRODUCT_ID, "scene_feed"
    state.presets = [_preset()]
    state.creating = True
    calls: list[Any] = []
    monkeypatch.setattr(module, "create_variation_set", lambda *a: calls.append(a) or _SET_ID)
    await VariationsState.create_set.fn(state)
    assert calls == []


async def test_a_failed_call_leaves_the_screen_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch)
    state.product_id, state.preset_key = _PRODUCT_ID, "scene_feed"
    state.presets = [_preset()]

    def _raise(*_: Any) -> None:
        raise UnknownPreset("scene_feed")

    monkeypatch.setattr(module, "create_variation_set", _raise)
    await VariationsState.create_set.fn(state)
    assert not state.creating and not state.has_set
    assert state.error == "Ese estilo de variaciones no existe."


# ---------------------------------------------------------------------------
# 6. the review


async def test_discarding_an_angle_re_reads_the_set(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    state.angles = [_angle()]
    discarded: list[str] = []
    monkeypatch.setattr(
        module, "discard_variation_angle", lambda _t, angle_id, _u: discarded.append(angle_id)
    )
    monkeypatch.setattr(
        module,
        "variation_set_detail",
        lambda *_: _set_vm(_angle(status="discarded", can_discard=False, can_restore=True)),
    )
    await _drain(VariationsState.discard_angle.fn(state, _ANGLE_ID))
    assert discarded == [_ANGLE_ID]
    assert state.angles[0].can_restore and not state.angles[0].can_discard
    assert state.busy_angle_id == ""


async def test_an_action_while_one_is_in_flight_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.set_id, state.busy_angle_id = _SET_ID, _ANGLE_ID
    calls: list[str] = []
    monkeypatch.setattr(module, "discard_variation_angle", lambda _t, a, _u: calls.append(a))
    await _drain(VariationsState.discard_angle.fn(state, _ANGLE_ID))
    assert calls == []


async def test_start_over_clears_the_product_and_the_set(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch)
    state.product_id, state.set_id = _PRODUCT_ID, _SET_ID
    state.angles = [_angle()]
    state.presets = [_preset()]
    state.preset_key = "scene_feed"
    VariationsState.start_over.fn(state)
    assert not state.product_chosen and not state.has_set
    assert state.angles == [] and state.presets == [] and state.preset_key == ""


async def test_catalog_failure_is_not_a_loaded_empty_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    assert not state.products_loaded

    def fail(*_args: object) -> None:
        raise RuntimeError("offline")

    monkeypatch.setattr(module, "catalog_products", fail)
    await VariationsState.load.fn(state)
    assert state.error and not state.products_loading
    assert not state.products_loaded
    monkeypatch.setattr(module, "catalog_products", lambda *_: ())
    await VariationsState.load.fn(state)
    assert state.products_loaded and not state.has_products

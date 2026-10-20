"""Tests for the catalog screen's state (`catalog_state`) and its place in the rail.

No DB: the provider functions the state calls are replaced with stand-ins, and
`_session_ids` is monkeypatched on the CLASS (see `test_creative_state.py`'s module
docstring for why it has to be the class). Background handlers are driven through
`.fn(state)`, the same way `test_creative_state.py` drives `load_brand`.

Pins:
1. "Catálogo" sits in the Negocio block, next to "Brand Kit", before "Configuración".
2. Selecting a product fills the editor; selecting it again closes the editor.
3. The new-product form refuses an empty name BEFORE any provider call, never sends a
   price (the screen dropped it, founder 2026-10-19 — stored prices stay untouched), and
   on success closes, clears, re-reads the list and opens the new product. Saving an
   edit sends no price either.
4. The upload progress reads "Procesando N de M" and a percentage.
5. `ingest_pending` stores every parked file, collects the failures as text (the
   service's own Spanish message), and re-reads the product when done.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from qualify_api.catalog.service import CatalogError

from . import catalog_state as catalog_state_module
from .catalog_state import CatalogState
from .catalog_vm import ProductMediaVM, ProductVM
from .ui.layout import NAV_BUSINESS, NAV_ITEMS

_TENANT_ID = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND_ID = UUID("b0000000-0000-4000-8000-000000000001")
_USER_ID = UUID("c0000000-0000-4000-8000-000000000001")
_PRODUCT_ID = UUID("d0000000-0000-4000-8000-000000000001")


def _product(product_id: str = str(_PRODUCT_ID), **kw: Any) -> ProductVM:
    base: dict[str, Any] = {
        "product_id": product_id,
        "name": "Shawarma mixto",
        "slug": "shawarma-mixto",
        "description": "Pollo y carne",
        "category": "shawarmas",
        "primary_photo_key": "",
        "photo_count": 0,
        "video_count": 0,
        "counts_label": "Sin fotos",
        "media": (),
    }
    base.update(kw)
    return ProductVM(**base)


async def _fake_session_ids(self: CatalogState) -> tuple[UUID, UUID, UUID]:
    return (_TENANT_ID, _BRAND_ID, _USER_ID)


async def _drain(events: Any) -> list[Any]:
    """Run an event handler that is an async generator; what it yields."""
    return [event async for event in events]


def _state(monkeypatch) -> CatalogState:
    monkeypatch.setattr(CatalogState, "_session_ids", _fake_session_ids)
    return CatalogState()


# ---------------------------------------------------------------------------
# 1. the rail


def test_catalogo_is_in_the_business_block_next_to_the_brand_kit() -> None:
    labels = [label for label, _icon, _route, _enabled in NAV_BUSINESS]
    assert ("Catálogo", "package", "/catalog", True) in NAV_BUSINESS
    assert labels.index("Catálogo") == labels.index("Brand Kit") + 1
    assert labels.index("Catálogo") < labels.index("Configuración")
    assert "/catalog" in {route for _label, _icon, route, _enabled in NAV_ITEMS}


# ---------------------------------------------------------------------------
# 2. selection and the editor


def test_selecting_a_product_fills_the_editor_and_selecting_again_closes_it() -> None:
    state = CatalogState()
    state.products = [_product(), _product("p2", name="Helado")]

    state.select_product(str(_PRODUCT_ID))
    assert state.selected is not None and state.selected.name == "Shawarma mixto"
    assert (state.edit_name, state.edit_category, state.edit_description) == (
        "Shawarma mixto",
        "shawarmas",
        "Pollo y carne",
    )

    state.select_product("p2")
    assert state.edit_name == "Helado"

    state.select_product("p2")
    assert state.selected_id == "" and state.selected is None


# ---------------------------------------------------------------------------
# 3. the new-product form


async def test_the_form_refuses_an_empty_name_before_any_call(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_create(*args: Any, **kwargs: Any) -> UUID:
        calls.append(kwargs)
        return _PRODUCT_ID

    monkeypatch.setattr(catalog_state_module, "create_product", fake_create)
    state = _state(monkeypatch)

    state.new_name = "   "
    await _drain(CatalogState.submit_new_product.fn(state))
    assert "nombre" in state.form_error.lower()
    assert calls == []


async def test_creating_a_product_closes_the_form_and_opens_the_product(monkeypatch) -> None:
    created: list[dict[str, Any]] = []

    def fake_create(tenant_id: UUID, brand_id: UUID, user_id: UUID | None, **kwargs: Any) -> UUID:
        created.append({"tenant_id": tenant_id, "brand_id": brand_id, **kwargs})
        return _PRODUCT_ID

    def fake_list(tenant_id: UUID, brand_id: UUID) -> tuple[ProductVM, ...]:
        return (_product(),)

    monkeypatch.setattr(catalog_state_module, "create_product", fake_create)
    monkeypatch.setattr(catalog_state_module, "list_products", fake_list)
    state = _state(monkeypatch)
    state.form_open = True
    state.new_name = " Shawarma mixto "
    state.new_category = "shawarmas"

    await _drain(CatalogState.submit_new_product.fn(state))

    assert created and created[0]["tenant_id"] == _TENANT_ID
    # the screen has no price any more: none is sent, so none is written
    assert "price_amount" not in created[0] and "currency" not in created[0]
    assert state.form_open is False and state.saving is False
    assert state.new_name == "" and state.new_category == ""
    assert state.selected_id == str(_PRODUCT_ID)
    assert state.edit_name == "Shawarma mixto"
    assert "creado" in state.notice.lower()


async def test_files_dropped_in_the_form_follow_the_new_product(monkeypatch, tmp_path) -> None:
    """§ request 2026-10-19: «no me deja poner la imagen de una vez» — the files dropped
    in the form wait as chips and go to the ingest as soon as the product exists."""
    monkeypatch.setattr(catalog_state_module, "create_product", lambda *a, **k: _PRODUCT_ID)
    monkeypatch.setattr(catalog_state_module, "list_products", lambda *a: (_product(),))
    state = _state(monkeypatch)
    first, second = tmp_path / "a.jpg", tmp_path / "b.mp4"
    first.write_bytes(b"x")
    second.write_bytes(b"y")
    state._new_pending = [[str(first), "a.jpg"], [str(second), "b.mp4"]]
    state.new_files = ["a.jpg", "b.mp4"]
    state.remove_new_file(1)  # taken out before creating: its staged file goes too
    assert state.new_files == ["a.jpg"] and not second.exists()
    state.new_name = "Smash"

    events = await _drain(CatalogState.submit_new_product.fn(state))

    assert events == [CatalogState.ingest_pending]
    assert state._pending == [[str(first), "a.jpg", str(_PRODUCT_ID)]]
    assert state.upload_total == 1
    assert state.new_files == [] and state.selected_id == str(_PRODUCT_ID)


def test_closing_the_form_drops_the_staged_files(tmp_path) -> None:
    staged = tmp_path / "a.jpg"
    staged.write_bytes(b"x")
    state = CatalogState()
    state._new_pending = [[str(staged), "a.jpg"]]
    state.new_files = ["a.jpg"]
    state.close_form()
    assert state.new_files == [] and not staged.exists()


async def test_the_services_spanish_refusal_shows_as_the_form_error(monkeypatch) -> None:
    def fake_create(*args: Any, **kwargs: Any) -> UUID:
        raise CatalogError("a product needs a name")

    monkeypatch.setattr(catalog_state_module, "create_product", fake_create)
    state = _state(monkeypatch)
    state.new_name = "X"
    await _drain(CatalogState.submit_new_product.fn(state))
    assert state.form_error == "a product needs a name"
    assert state.saving is False


async def test_saving_a_product_never_sends_a_price(monkeypatch) -> None:
    """Editing name/category/description leaves a stored price untouched: the provider
    is called without price/currency, so the service keeps what is there."""
    updated: list[dict[str, Any]] = []

    def fake_update(tenant_id: UUID, product_id: UUID, **kwargs: Any) -> None:
        updated.append({"product_id": product_id, **kwargs})

    def fake_list(tenant_id: UUID, brand_id: UUID) -> tuple[ProductVM, ...]:
        return (_product(),)

    monkeypatch.setattr(catalog_state_module, "update_product", fake_update)
    monkeypatch.setattr(catalog_state_module, "list_products", fake_list)
    state = _state(monkeypatch)
    state.products = [_product()]
    state.select_product(str(_PRODUCT_ID))
    state.edit_name = "Shawarma XL"

    await CatalogState.save_product.fn(state)

    assert updated == [
        {
            "product_id": _PRODUCT_ID,
            "name": "Shawarma XL",
            "description": "Pollo y carne",
            "category": "shawarmas",
        }
    ]
    assert state.edit_saving is False and state.edit_error == ""


# ---------------------------------------------------------------------------
# 4. progress


def test_upload_progress_reads_as_n_of_m() -> None:
    state = CatalogState()
    assert state.upload_progress == 0
    state.upload_total = 4
    state.upload_done = 1
    assert state.upload_progress == 25
    assert state.upload_label == "Procesando 2 de 4"
    state.upload_done = 4
    assert state.upload_label == "Procesando 4 de 4"


# ---------------------------------------------------------------------------
# 5. the ingest


async def test_ingest_stores_each_parked_file_and_keeps_the_failures(
    monkeypatch, tmp_path: Path
) -> None:
    stored: list[tuple[UUID, UUID, bytes, str]] = []

    def fake_add_media(tenant_id: UUID, product_id: UUID, *, data: bytes, filename: str) -> None:
        if filename.endswith(".mov"):
            raise CatalogError("el video no se pudo procesar: ffmpeg")
        stored.append((tenant_id, product_id, data, filename))

    refreshed = {"n": 0}

    def fake_list(tenant_id: UUID, brand_id: UUID) -> tuple[ProductVM, ...]:
        refreshed["n"] += 1
        media = (
            ProductMediaVM(
                media_id="m1",
                media_type="image",
                key="uploads/t/catalog/p/1.jpg",
                filename="a.jpg",
                is_primary=True,
                position=0,
                meta_label="1080×1350",
            ),
        )
        return (_product(media=media, photo_count=1, counts_label="1 foto"),)

    monkeypatch.setattr(catalog_state_module, "add_media", fake_add_media)
    monkeypatch.setattr(catalog_state_module, "list_products", fake_list)
    state = _state(monkeypatch)
    state.products = [_product()]
    state.selected_id = str(_PRODUCT_ID)
    good = tmp_path / "x_a.jpg"
    good.write_bytes(b"jpg-bytes")
    bad = tmp_path / "y_clip.mov"
    bad.write_bytes(b"mov-bytes")
    state._pending = [
        [str(good), "a.jpg", str(_PRODUCT_ID)],
        [str(bad), "clip.mov", str(_PRODUCT_ID)],
    ]
    state.upload_total = 2

    async for _ in CatalogState.ingest_pending.fn(state):
        pass

    assert [(f, d) for _t, _p, d, f in stored] == [("a.jpg", b"jpg-bytes")]
    assert stored[0][0] == _TENANT_ID and stored[0][1] == _PRODUCT_ID
    assert "clip.mov" in state.upload_error and "ffmpeg" in state.upload_error
    assert not good.exists() and not bad.exists()  # staging is cleaned either way
    assert state.uploading is False and state._pending == []
    assert refreshed["n"] == 1
    assert state.selected is not None and state.selected.photo_count == 1


async def test_each_queued_file_lands_on_its_own_product(monkeypatch, tmp_path: Path) -> None:
    """Review 2026-10-19: a file queued for product A must not land on product B because
    the operator selected B before its turn came."""
    other = UUID("00000000-0000-0000-0000-0000000000b2")
    stored: list[UUID] = []

    def fake_add_media(tenant_id: UUID, product_id: UUID, *, data: bytes, filename: str) -> None:
        stored.append(product_id)

    monkeypatch.setattr(catalog_state_module, "add_media", fake_add_media)
    monkeypatch.setattr(catalog_state_module, "list_products", lambda *a: (_product(),))
    state = _state(monkeypatch)
    first, second = tmp_path / "a.jpg", tmp_path / "b.jpg"
    first.write_bytes(b"x")
    second.write_bytes(b"y")
    state.selected_id = str(other)  # the operator moved on to another product
    state._pending = [[str(first), "a.jpg", str(_PRODUCT_ID)], [str(second), "b.jpg", str(other)]]

    async for _ in CatalogState.ingest_pending.fn(state):
        pass

    assert stored == [_PRODUCT_ID, other]


def test_load_sweeps_orphaned_staging_files(monkeypatch, tmp_path: Path) -> None:
    """Review 2026-10-19: parked files a closed tab never ingested do not pile up."""
    import os

    monkeypatch.setattr(catalog_state_module, "_staging_dir", lambda _t: tmp_path)
    old, fresh = tmp_path / "old.jpg", tmp_path / "fresh.jpg"
    old.write_bytes(b"x")
    fresh.write_bytes(b"y")
    now = 1_000_000_000.0
    os.utime(old, (now - catalog_state_module._STAGING_TTL_S - 1,) * 2)
    os.utime(fresh, (now - 60,) * 2)
    catalog_state_module._sweep_staging(_PRODUCT_ID, now=now)
    assert not old.exists() and fresh.exists()

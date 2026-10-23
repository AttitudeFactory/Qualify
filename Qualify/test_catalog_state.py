"""Tests for the catalog screen's state (`catalog_state`) and its place in the rail.

No DB: the provider functions the state calls are replaced with stand-ins, and
`_session_ids` is monkeypatched on the CLASS (see `test_creative_state.py`'s module
docstring for why it has to be the class). Background handlers are driven through
`.fn(state)`, the same way `test_creative_state.py` drives `load_brand`.

Pins:
1. "Tus productos" sits in the Negocio block, next to "Tu marca", before "Configuración".
2. Selecting a product fills the editor; selecting it again keeps it open (m-24842976).
3. The new-product form refuses an empty name BEFORE any provider call, never sends a
   price (the screen dropped it, founder 2026-10-19 — stored prices stay untouched), and
   on success closes, clears, re-reads the list and opens the new product. Saving an
   edit sends no price either.
4. The upload progress reads "Procesando N de M" and a percentage.
5. `ingest_pending` stores every parked file, collects the failures as text (the
   service's own Spanish message), and re-reads the product when done.
7. m-24842974: «Agregar producto» in three steps — the photo first and never a gate,
   «Atrás» keeps what was typed (N6), «Listo» after saving with the way to Crear, the
   business's own currency as the start, refused files in the owner's words, and no
   «arrastra» / «haz clic» / format siglas on the main path.
9. m-24842977: «Principal» and «Quitar» in words at 44 px, «Quitar» asks first, no
   pixel sizes, and «3 productos · 1 sin foto» with a filter to the ones missing it.
"""

from __future__ import annotations

import json
from decimal import Decimal
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
        "price_label": "",
        "price_amount": "",
        "price_currency": "",
        "category": "shawarmas",
        "primary_photo_key": "",
        "photo_count": 0,
        "video_count": 0,
        "counts_label": "Falta la foto",
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
    assert ("Tus productos", "package", "/catalog", True) in NAV_BUSINESS
    assert labels.index("Tus productos") == labels.index("Tu marca") + 1
    assert labels.index("Tus productos") < labels.index("Configuración")
    assert "/catalog" in {route for _label, _icon, route, _enabled in NAV_ITEMS}


# ---------------------------------------------------------------------------
# 2. selection and the editor


def test_selecting_a_product_fills_the_editor_and_never_toggles_it() -> None:
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

    # m-24842976: tapping the open product keeps it open (the drawer closes itself)
    assert state.select_product("p2") is None
    assert state.selected_id == "p2"
    # an id the list does not hold (over the wire) opens nothing
    assert state.select_product("ajeno") is None and state.selected_id == "p2"


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


async def test_creating_a_product_lands_on_listo_and_leaves_the_editor_closed(
    monkeypatch,
) -> None:
    """m-24842974: after «Guardar producto» the drawer shows «Listo» (no toast on top of
    it); the editor still opens only when the owner taps the card (request 2026-10-22)."""
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

    events = await _drain(CatalogState.submit_new_product.fn(state))

    assert created and created[0]["tenant_id"] == _TENANT_ID
    # m-24803289: the price is an optional field again. Nothing was typed in this form,
    # so the product is created WITHOUT one and its pieces will print none.
    assert created[0]["price_amount"] is None and created[0]["price_currency"] == ""
    assert state.form_open is True and state.saving is False
    assert state.new_step == catalog_state_module.STEP_DONE
    assert state.new_step_counter == "Paso 3 de 3"
    assert state.created_name == "Shawarma mixto"
    assert state.created_product_id == str(_PRODUCT_ID)
    # no photo: «Crear publicación» waits for one, and the product says what it lacks
    assert state.created_has_media is False
    assert state.created_href == f"/create?producto={_PRODUCT_ID}"
    assert state.new_name == "" and state.new_category == ""
    assert state.selected_id == "" and state.selected is None
    assert events == []


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
    # the form draws what is left (request 2026-10-22: the picture, not the name)
    assert [row["name"] for row in state.new_previews] == ["a.jpg"]
    state.new_name = "Smash"

    events = await _drain(CatalogState.submit_new_product.fn(state))

    assert events == [CatalogState.ingest_pending]
    assert state.created_has_media is True
    assert state._pending == [[str(first), "a.jpg", str(_PRODUCT_ID)]]
    assert state.upload_total == 1
    assert state.new_files == [] and state.selected_id == ""


def _media(media_id: str, *, primary: bool = False, position: int = 0) -> ProductMediaVM:
    return ProductMediaVM(
        media_id=media_id,
        media_type="image",
        key=f"uploads/t/catalog/p/{media_id}.jpg",
        filename=f"{media_id}.jpg",
        is_primary=primary,
        position=position,
        meta_label="",
    )


def test_dropping_a_tile_on_another_moves_it_there_and_asks_for_the_sync() -> None:
    """Request 2026-10-22: order the photos by dragging; the first is the primary."""
    state = CatalogState()
    state.products = [
        _product(
            media=(_media("m1", primary=True), _media("m2", position=1), _media("m3", position=2))
        )
    ]
    state.selected_id = str(_PRODUCT_ID)
    state.media_pick("m3")
    assert state.media_dragging == "m3"
    spec = state.media_drop("m1")
    assert spec is not None and state.media_dragging == ""
    assert state._media_order == ["m3", "m1", "m2"]
    # «Hacer principal» is the same move, to the front
    assert state.make_primary("m2") is not None
    assert state._media_order == ["m2", "m1", "m3"]
    # a drop on itself, or of nothing, moves nothing
    state.media_pick("m1")
    assert state.media_drop("m1") is None and state.media_drop("m2") is None


async def test_the_sync_persists_the_order_and_says_so(monkeypatch) -> None:
    ordered: list[tuple[Any, ...]] = []
    monkeypatch.setattr(catalog_state_module, "reorder_media", lambda *a: ordered.append(a))
    monkeypatch.setattr(
        catalog_state_module,
        "list_products",
        lambda *_: (_product(media=(_media("m2", primary=True), _media("m1", position=1))),),
    )
    state = _state(monkeypatch)
    state.products = [_product(media=(_media("m1", primary=True), _media("m2", position=1)))]
    state.selected_id = str(_PRODUCT_ID)
    state._media_order = ["m2", "m1"]
    events = await _drain(CatalogState.sync_media_order.fn(state))
    assert ordered == [(_TENANT_ID, _PRODUCT_ID, ["m2", "m1"])]
    assert state.media_busy is False and state._media_order == []
    assert state.selected is not None and state.selected.media[0].media_id == "m2"
    assert len(events) == 1 and "success" in str(events[0])


def test_a_staged_file_previews_through_the_upload_store(monkeypatch, tmp_path: Path) -> None:
    """A JPG parked under the upload dir is drawn from its key; a HEIC or a clip gets the
    frame with a glyph instead (a browser cannot draw them before the ingest)."""
    import reflex as rx

    monkeypatch.setattr(rx, "get_upload_dir", lambda: tmp_path)
    staged = tmp_path / "uploads" / "t" / "catalog_staging"
    staged.mkdir(parents=True)
    jpg = catalog_state_module._preview_row(str(staged / "x_a.jpg"), "a.jpg")
    assert jpg == {"name": "a.jpg", "key": "uploads/t/catalog_staging/x_a.jpg", "kind": "image"}
    assert catalog_state_module._preview_row(str(staged / "y.HEIC"), "y.HEIC")["kind"] == "file"
    assert catalog_state_module._preview_row(str(staged / "z.mov"), "z.mov")["kind"] == "video"
    # parked outside the upload dir: nothing to preview, never a broken picture
    assert catalog_state_module._preview_row("C:/elsewhere/a.jpg", "a.jpg")["kind"] == "file"


async def test_deleting_the_open_product_closes_the_editor_and_says_so(monkeypatch) -> None:
    """Request 2026-10-22: «Eliminar» in the editor — the product leaves the list."""
    gone: list[tuple[Any, ...]] = []
    monkeypatch.setattr(catalog_state_module, "deactivate_product", lambda *a: gone.append(a))
    monkeypatch.setattr(catalog_state_module, "list_products", lambda *_: ())
    state = _state(monkeypatch)
    state.products = [_product()]
    state.select_product(str(_PRODUCT_ID))
    state.ask_delete_product()
    assert state.delete_product_name == "Shawarma mixto"
    events = await _drain(CatalogState.confirm_delete_product.fn(state))
    assert gone == [(_TENANT_ID, _PRODUCT_ID)]
    assert state.selected_id == "" and state.products == [] and state.delete_product_name == ""
    assert len(events) == 1 and "eliminado" in str(events[0])


def test_closing_midway_keeps_the_chosen_photos(tmp_path) -> None:
    """N6: the photos are the hardest part to repeat — closing halfway keeps them."""
    staged = tmp_path / "a.jpg"
    staged.write_bytes(b"x")
    state = CatalogState()
    state.open_form()
    state._new_pending = [[str(staged), "a.jpg"]]
    state.new_files = ["a.jpg"]
    state.close_form()
    assert state.new_files == ["a.jpg"] and staged.exists()
    assert state._new_pending == [[str(staged), "a.jpg"]]


def test_add_another_drops_the_staged_files(tmp_path) -> None:
    staged = tmp_path / "a.jpg"
    staged.write_bytes(b"x")
    state = CatalogState()
    state._new_pending = [[str(staged), "a.jpg"]]
    state.new_files = ["a.jpg"]
    state.add_another_product()
    assert state.new_files == [] and not staged.exists()


def test_listo_without_a_photo_leads_to_adding_one(monkeypatch) -> None:
    monkeypatch.setattr(catalog_state_module, "list_products", lambda *a: (_product(),))
    state = CatalogState()
    state.products = [_product()]
    state.form_open = True
    state.new_step = catalog_state_module.STEP_DONE
    state.created_product_id = str(_PRODUCT_ID)
    state.created_name = "Shawarma mixto"
    assert not state.created_ready and not state.created_preparing
    state.upload_photo_for_created()
    assert not state.form_open and state.created_product_id == ""
    assert state.selected_id == str(_PRODUCT_ID)


def test_crear_publicacion_waits_for_the_upload_to_finish() -> None:
    state = CatalogState()
    state.created_has_media = True
    state.upload_total = 1  # queued, ingest not started yet
    assert state.created_preparing and not state.created_ready
    state.uploading = True
    assert state.created_preparing and not state.created_ready
    state.uploading = False
    state.upload_total = 0
    state.upload_error = "a.jpg: no se pudo procesar"
    assert not state.created_preparing and not state.created_ready
    state.upload_error = ""
    assert state.created_ready


async def test_the_services_spanish_refusal_shows_as_the_form_error(monkeypatch) -> None:
    def fake_create(*args: Any, **kwargs: Any) -> UUID:
        raise CatalogError("a product needs a name")

    monkeypatch.setattr(catalog_state_module, "create_product", fake_create)
    state = _state(monkeypatch)
    state.new_name = "X"
    await _drain(CatalogState.submit_new_product.fn(state))
    assert state.form_error == "a product needs a name"
    assert state.saving is False


def _editor(monkeypatch, updated: list[dict[str, Any]], product: ProductVM) -> CatalogState:
    """A state with `product` open in the editor and its save captured."""

    def fake_update(tenant_id: UUID, product_id: UUID, **kwargs: Any) -> None:
        updated.append({"product_id": product_id, **kwargs})

    monkeypatch.setattr(catalog_state_module, "update_product", fake_update)
    monkeypatch.setattr(catalog_state_module, "list_products", lambda *_: (product,))
    state = _state(monkeypatch)
    state.products = [product]
    state.select_product(str(_PRODUCT_ID))
    return state


async def test_saving_a_product_sends_the_price_the_editor_shows(monkeypatch) -> None:
    """m-24803289: the price is an optional field again, and the editor opens on what
    is stored — so a save sends exactly that, and the product keeps its price."""
    updated: list[dict[str, Any]] = []
    priced = _product(price_label="$12.5", price_amount="12.5", price_currency="USD")
    state = _editor(monkeypatch, updated, priced)
    assert (state.edit_price, state.edit_currency) == ("12.5", "USD")
    state.edit_name = "Shawarma XL"

    await _drain(CatalogState.save_product.fn(state))

    assert updated == [
        {
            "product_id": _PRODUCT_ID,
            "name": "Shawarma XL",
            "description": "Pollo y carne",
            "category": "shawarmas",
            "price_amount": Decimal("12.50"),
            "price_currency": "USD",
        }
    ]
    assert state.edit_saving is False and state.edit_error == ""


async def test_saving_a_product_closes_the_editor(monkeypatch) -> None:
    """Request 2026-10-22: «Guardar cambios» closes the editor and leaves the card."""
    updated: list[dict[str, Any]] = []
    state = _editor(monkeypatch, updated, _product())
    assert state.selected_id == str(_PRODUCT_ID)

    events = await _drain(CatalogState.save_product.fn(state))

    assert updated and state.selected_id == "" and state.selected is None
    assert state.edit_saving is False and state.edit_error == ""
    assert len(events) == 1 and "guardados" in str(events[0])


async def test_a_refused_save_keeps_the_editor_open(monkeypatch) -> None:
    updated: list[dict[str, Any]] = []
    state = _editor(monkeypatch, updated, _product())
    state.edit_name = "   "

    await _drain(CatalogState.save_product.fn(state))

    assert updated == [] and state.selected_id == str(_PRODUCT_ID)
    assert "nombre" in state.edit_error.lower()


async def test_clearing_the_price_field_removes_the_price(monkeypatch) -> None:
    """Emptying the field is the one way the screen drops a price, and it is a
    deliberate act: the provider is told `None`, not "leave it as it was"."""
    updated: list[dict[str, Any]] = []
    priced = _product(price_label="$12.5", price_amount="12.5", price_currency="USD")
    state = _editor(monkeypatch, updated, priced)
    state.set_edit_price("")
    state.set_edit_currency("Sin moneda")

    await _drain(CatalogState.save_product.fn(state))

    assert updated[0]["price_amount"] is None and updated[0]["price_currency"] == ""


async def test_a_price_that_cannot_be_read_exactly_is_refused_before_saving(
    monkeypatch,
) -> None:
    """Never an invented price: an ambiguous amount stops the save with a message."""
    updated: list[dict[str, Any]] = []
    state = _editor(monkeypatch, updated, _product())
    state.set_edit_price("1.234.56")

    await _drain(CatalogState.save_product.fn(state))

    assert updated == [] and "no se entiende" in state.edit_error
    assert state.edit_saving is False


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
                meta_label="",
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


# ---------------------------------------------------------------------------
# 6. the owner's words (m-24842971)

_COPY_SOURCES = ("catalog_page.py", "catalog_state.py", "catalog_vm.py")
# Words from the team, not the owner (qualify-ux §3, docs/ux-auditoria-2026-10/m2 #5, #10).
_BANNED = ("plantilla", "feed", "pieza", "gancho", "provisionad", "story", "base de datos")
#: Literals that are code, not copy: the browser's own API names (m-24842976).
_CODE_LITERALS = {"window.history.back()"}


def _visible_strings(source: str) -> list[str]:
    """Every string literal in the module except docstrings — what can reach the screen."""
    import ast

    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_the_catalog_speaks_the_owners_words() -> None:
    here = Path(catalog_state_module.__file__).parent
    for name in _COPY_SOURCES:
        for text in _visible_strings((here / name).read_text(encoding="utf-8")):
            if text in _CODE_LITERALS:
                continue
            lowered = text.lower()
            for word in _BANNED:
                assert word not in lowered, f"{name}: «{word}» in {text!r}"
            # «reel» only as «reel (video corto)» (founder decision 11).
            assert "reel" not in lowered.replace("reel (video corto)", ""), (name, text)


def test_a_missing_brand_shows_the_way_to_complete_it() -> None:
    state = CatalogState()
    assert not state.needs_brand
    state.error = catalog_state_module._NO_BRAND
    assert state.needs_brand
    assert state.error == (
        "Primero completa tu marca (logo y colores) y vuelve a subir tus productos."
    )
    state.error = catalog_state_module._DB_ERROR
    assert not state.needs_brand
    # Load and save share it: no «base de datos», no blame on the owner's connection.
    assert state.error == "Algo falló de nuestro lado. Inténtalo otra vez en un minuto."


# ---------------------------------------------------------------------------
# 7. «Agregar producto» in three steps (m-24842974)


def test_the_photo_comes_first_and_is_never_a_gate() -> None:
    state = CatalogState()
    state.open_form()
    assert state.form_open and state.new_step == catalog_state_module.STEP_PHOTO
    assert (
        state.new_step_counter == "Paso 1 de 3"
        and state.new_step_title == "Muestra cómo se ve tu producto"
    )
    state.next_new_step()  # «Sin foto por ahora»
    assert state.new_step == catalog_state_module.STEP_NAME
    assert state.new_step_title == "¿Cómo se llama?"
    assert state.new_steps_done == [True, False, False]


def test_going_back_keeps_everything_typed() -> None:
    state = CatalogState()
    state.open_form()
    state.next_new_step()
    state.set_new_name("Helado de yogur")
    state.set_new_price("12000")
    state.set_new_currency("COP")
    state.toggle_new_details()
    state.set_new_category("helados")
    state.back_new_step()  # «Atrás»
    assert state.new_step == catalog_state_module.STEP_PHOTO
    state.next_new_step()
    assert (state.new_name, state.new_price, state.new_currency, state.new_category) == (
        "Helado de yogur",
        "12000",
        "COP",
        "helados",
    )
    assert state.new_details_open is True


def test_the_stepper_never_reaches_listo_before_saving_nor_leaves_it_after() -> None:
    state = CatalogState()
    state.open_form()
    state.go_to_new_step(catalog_state_module.STEP_DONE)
    assert state.new_step == catalog_state_module.STEP_PHOTO
    state.new_step = catalog_state_module.STEP_DONE
    state.go_to_new_step(catalog_state_module.STEP_PHOTO)
    assert state.new_step == catalog_state_module.STEP_DONE


def test_the_form_starts_with_the_business_currency_and_agregar_otro_starts_clean() -> None:
    state = CatalogState()
    state._business_currency = "VES"
    state.open_form()
    assert state.new_currency == "VES"
    state.new_step = catalog_state_module.STEP_DONE
    state.created_product_id = str(_PRODUCT_ID)
    state.created_name = "Shawarma"
    state.new_currency = ""
    state.add_another_product()
    assert state.form_open and state.new_step == catalog_state_module.STEP_PHOTO
    assert state.created_product_id == "" and state.created_name == ""
    assert state.new_currency == "VES"


def test_closing_from_listo_resets_and_closing_midway_keeps_the_text() -> None:
    state = CatalogState()
    state.open_form()
    state.next_new_step()
    state.set_new_name("Combo")
    state.close_form()
    assert state.new_step == catalog_state_module.STEP_PHOTO and state.new_name == "Combo"
    state.set_form_open(True)
    state.new_step = catalog_state_module.STEP_DONE
    state.created_name = "Combo"
    state.set_form_open(False)
    assert not state.form_open and state.created_name == ""
    assert state.new_step == catalog_state_module.STEP_PHOTO


async def test_load_reads_the_business_currency(monkeypatch) -> None:
    monkeypatch.setattr(catalog_state_module, "list_products", lambda *a: ())
    monkeypatch.setattr(catalog_state_module, "business_currency", lambda _t: "UYU")
    monkeypatch.setattr(catalog_state_module, "_sweep_staging", lambda _t: None)
    state = _state(monkeypatch)
    assert await _drain(CatalogState.load_catalog.fn(state)) == []
    assert state._business_currency == "UYU" and state.new_currency == "UYU"


def test_refused_files_say_what_to_do_in_both_drop_zones() -> None:
    state = CatalogState()
    state.new_media_rejected([{"errors": [{"code": "file-invalid-type"}]}])
    assert state.new_media_error.startswith("Ese archivo no es una foto ni un video.")
    state.media_rejected([{"errors": [{"code": "too-many-files"}]}])
    assert "hasta 12" in state.upload_error


def test_the_main_path_has_no_drag_click_or_format_words() -> None:
    here = Path(catalog_state_module.__file__).parent
    texts = _visible_strings((here / "catalog_page.py").read_text(encoding="utf-8"))
    for text in texts:
        lowered = text.lower()
        assert "arrastra" not in lowered and "haz clic" not in lowered, text
        for sigla in ("JPG", "JPEG", "PNG", "HEIC", "MP4", "MOV"):
            assert sigla not in text, text


# ---------------------------------------------------------------------------
# 8. m-24842976: editing without losing changes, with its own address (N5)


def _nav(events: Any) -> list[tuple[str, Any, bool]]:
    """The navigations a handler asked for: ("redirect", path, replace) or
    ("script", code, False) — read from the EventSpecs, nothing else."""
    found: list[tuple[str, Any, bool]] = []
    for spec in events or []:
        fn = getattr(getattr(spec, "handler", None), "fn", None)
        if getattr(fn, "__qualname__", "") not in ("_redirect", "_call_script"):
            continue  # toasts and the like
        args = {name._js_expr: value._var_value for name, value in getattr(spec, "args", ())}
        if getattr(fn, "__qualname__", "") == "_redirect":
            found.append(("redirect", args["path"], bool(args["replace"])))
        elif getattr(fn, "__qualname__", "") == "_call_script":
            found.append(("script", args["javascript_code"], False))
    return found


def _at(monkeypatch, product: str = "") -> dict[str, str]:
    """Pin the address the state reads (`?producto=`); mutate the dict to «navigate»."""
    url = {"producto": product}
    monkeypatch.setattr(CatalogState, "_url_product", lambda self: url["producto"])
    return url


def _two_products() -> list[ProductVM]:
    return [_product(), _product("p2", name="Helado", category="helados", description="")]


def _offline_load(monkeypatch) -> None:
    monkeypatch.setattr(catalog_state_module, "list_products", lambda *_: tuple(_two_products()))
    monkeypatch.setattr(catalog_state_module, "business_currency", lambda _t: "COP")
    monkeypatch.setattr(catalog_state_module, "_sweep_staging", lambda _t: None)


def test_opening_from_the_list_gives_the_product_its_address(monkeypatch) -> None:
    _at(monkeypatch)
    state = CatalogState()
    state.products = _two_products()
    events = state.select_product(str(_PRODUCT_ID))
    assert _nav(events) == [("redirect", f"/catalog?producto={_PRODUCT_ID}", False)]
    assert state.editor_open and state._opened_in_app


def test_closing_a_clean_editor_steps_back_to_the_list(monkeypatch) -> None:
    """«atrás» semantics for the ×: the list comes back where it was (history back)."""
    url = _at(monkeypatch)
    state = CatalogState()
    state.products = _two_products()
    state.select_product(str(_PRODUCT_ID))
    url["producto"] = str(_PRODUCT_ID)
    assert not state.edit_dirty
    events = state.set_editor_open(False)
    assert _nav(events) == [("script", "window.history.back()", False)]
    assert not state.editor_open and not state.leave_open


def test_closing_an_editor_opened_from_a_link_replaces_the_address(monkeypatch) -> None:
    url = _at(monkeypatch, str(_PRODUCT_ID))
    state = CatalogState()
    state.products = _two_products()
    state._sync_url(final=True)  # the link opened it: no list entry behind it
    assert state.selected_id == str(_PRODUCT_ID) and not state._opened_in_app
    assert _nav(state.request_close()) == [("redirect", "/catalog", True)]
    url["producto"] = ""
    assert state.request_close() is None  # nothing open, nothing to do


def test_closing_with_changes_asks_first_and_volver_keeps_them(monkeypatch) -> None:
    url = _at(monkeypatch)
    state = CatalogState()
    state.products = _two_products()
    state.select_product(str(_PRODUCT_ID))
    url["producto"] = str(_PRODUCT_ID)
    state.set_edit_price("15000")
    assert state.edit_dirty
    assert state.request_close() is None
    assert state.leave_open and state.editor_open
    assert state.leave_text == "Los cambios de «Shawarma mixto» se van a perder."
    assert state.stay_in_editor() == []  # the address still names the product
    assert not state.leave_open and state.edit_price == "15000"
    # Esc on the dialog is «Volver» too
    state.request_close()
    state.set_leave_open(False)
    assert not state.leave_open and state.edit_price == "15000"


def test_salir_sin_guardar_drops_the_changes(monkeypatch) -> None:
    url = _at(monkeypatch)
    state = CatalogState()
    state.products = _two_products()
    state.select_product(str(_PRODUCT_ID))
    url["producto"] = str(_PRODUCT_ID)
    state.set_edit_name("Otro nombre")
    state.request_close()
    events = state.discard_and_leave()
    assert _nav(events) == [("script", "window.history.back()", False)]
    assert not state.editor_open and not state.leave_open


def test_moving_to_another_product_with_changes_asks_first(monkeypatch) -> None:
    url = _at(monkeypatch)
    state = CatalogState()
    state.products = _two_products()
    state.select_product(str(_PRODUCT_ID))
    url["producto"] = str(_PRODUCT_ID)
    state.set_edit_category("combos")
    assert state.select_product("p2") is None
    assert state.leave_open and state.selected_id == str(_PRODUCT_ID)
    events = state.discard_and_leave()
    # the address already names a product: the same history entry, the other product
    assert _nav(events) == [("redirect", "/catalog?producto=p2", True)]
    assert state.selected_id == "p2" and state.edit_name == "Helado"


async def test_guardar_y_salir_saves_then_goes_where_the_owner_was_going(monkeypatch) -> None:
    updated: list[dict[str, Any]] = []
    products = _two_products()
    monkeypatch.setattr(
        catalog_state_module,
        "update_product",
        lambda tenant_id, product_id, **kw: updated.append({"product_id": product_id, **kw}),
    )
    monkeypatch.setattr(catalog_state_module, "list_products", lambda *_: tuple(products))
    url = _at(monkeypatch)
    state = _state(monkeypatch)
    state.products = list(products)
    state.select_product(str(_PRODUCT_ID))
    url["producto"] = str(_PRODUCT_ID)
    state.set_edit_price("15000")
    state.select_product("p2")
    assert state.save_and_leave() == CatalogState.save_product
    assert not state.leave_open

    events = await _drain(CatalogState.save_product.fn(state))

    assert updated and updated[0]["price_amount"] == Decimal("15000")
    assert "guardados" in str(events[0])
    assert _nav(events[1:]) == [("redirect", "/catalog?producto=p2", True)]
    assert state.selected_id == "p2" and state._leave_target == ""


async def test_a_refused_guardar_y_salir_stays_with_the_reason(monkeypatch) -> None:
    updated: list[dict[str, Any]] = []
    url = _at(monkeypatch)
    state = _editor(monkeypatch, updated, _product())
    url["producto"] = str(_PRODUCT_ID)
    state.set_edit_name("  ")
    state.request_close()
    state.save_and_leave()
    events = await _drain(CatalogState.save_product.fn(state))
    assert updated == [] and _nav(events) == []
    # the reason is also a toast: on the phone the line under the fields may be out of view
    assert len(events) == 1 and state.edit_error in str(events[0])
    assert state.editor_open and "nombre" in state.edit_error.lower()
    assert state._leave_target == "" and not state.leave_open


async def test_the_phones_back_with_changes_asks_and_volver_restores_the_address(
    monkeypatch,
) -> None:
    """N5: «atrás» drops `?producto=` before the app hears it; with changes pending the
    editor stays and asks, and «Volver» puts the address back for the next «atrás»."""
    _offline_load(monkeypatch)
    url = _at(monkeypatch)
    state = _state(monkeypatch)
    state.products = _two_products()
    state.select_product(str(_PRODUCT_ID))
    state.set_edit_description("Con papas")
    url["producto"] = ""  # the phone's «atrás»

    assert await _drain(CatalogState.load_catalog.fn(state)) == []

    assert state.editor_open and state.leave_open and state._leave_target == ""
    assert state.loading is False  # the list never swapped for the skeleton
    assert _nav(state.stay_in_editor()) == [("redirect", f"/catalog?producto={_PRODUCT_ID}", False)]
    assert state.edit_description == "Con papas"


async def test_the_phones_back_without_changes_closes_the_editor(monkeypatch) -> None:
    _offline_load(monkeypatch)
    url = _at(monkeypatch)
    state = _state(monkeypatch)
    state.products = _two_products()
    state.select_product(str(_PRODUCT_ID))
    url["producto"] = ""
    assert await _drain(CatalogState.load_catalog.fn(state)) == []
    assert not state.editor_open and not state.leave_open


async def test_a_link_opens_the_product_and_a_stranger_id_falls_back_to_the_list(
    monkeypatch,
) -> None:
    """`/catalog?producto=<id>` opens that product after the first load; an id this
    business does not have (another tenant's, a deleted one) lands on the bare list."""
    _offline_load(monkeypatch)
    url = _at(monkeypatch, "p2")
    state = _state(monkeypatch)
    assert await _drain(CatalogState.load_catalog.fn(state)) == []
    assert state.selected_id == "p2" and state.edit_name == "Helado"

    url["producto"] = "e0000000-0000-4000-8000-00000000dead"
    fresh = _state(monkeypatch)
    events = await _drain(CatalogState.load_catalog.fn(fresh))
    assert _nav(events) == [("redirect", "/catalog", True)]
    assert "Aquí tienes los que sí están" in str(events[1])  # N3: say what happened
    assert not fresh.editor_open


async def test_a_photo_change_never_overwrites_a_price_being_corrected(
    monkeypatch, tmp_path: Path
) -> None:
    """UX review: correct the price, add a photo — the refresh after the upload keeps
    the typed price and «¿Salir sin guardar?» still guards it."""
    monkeypatch.setattr(catalog_state_module, "add_media", lambda *_a, **_k: None)
    updated: list[dict[str, Any]] = []
    state = _editor(monkeypatch, updated, _product(price_amount="12000"))
    state.set_edit_price("15000")
    photo = tmp_path / "foto.jpg"
    photo.write_bytes(b"x")
    state._pending = [(str(photo), "foto.jpg", str(_PRODUCT_ID))]

    await _drain(CatalogState.ingest_pending.fn(state))

    assert state.edit_price == "15000" and state.edit_dirty
    assert updated == []


def test_retyping_the_same_values_is_not_a_change(monkeypatch) -> None:
    _at(monkeypatch)
    state = CatalogState()
    state.products = [_product(price_amount="12.5", price_currency="USD")]
    state.select_product(str(_PRODUCT_ID))
    state.set_edit_name(" Shawarma mixto ")
    state.set_edit_price("12,50")
    assert not state.edit_dirty
    state.set_edit_currency("COP")
    assert state.edit_dirty


def test_the_card_is_a_button_that_says_editar() -> None:
    """m-24842976: a real <button> named «Editar {producto}», the word written on it, and
    no hover-only chip or tooltip; the leave dialog speaks the agreed words."""
    from . import catalog_page

    source = Path(catalog_page.__file__).read_text(encoding="utf-8")
    card = source[source.index("def _product_card") : source.index("def _grid")]
    assert "rx.el.button(" in card and 'type="button"' in card
    assert 'aria_label="Editar " + product.name' in card
    assert '"Editar"' in card and "tooltip" not in card and "q-catalog-edit" not in card
    assert 'role="button"' not in card  # a real button needs no borrowed role
    rendered = str(catalog_page.catalog_index())
    for words in ("¿Salir sin guardar?", "Volver", "Guardar y salir"):
        # the compiled page escapes non-ASCII the way JSON does («¿» → ¿)
        assert json.dumps(words)[1:-1] in rendered


# ---------------------------------------------------------------------------
# 9. m-24842977: the main photo and removing media without mistakes


def _with_media() -> CatalogState:
    state = CatalogState()
    state.products = [
        _product(
            media=(
                _media("m1", primary=True),
                _media("m2", position=1),
                ProductMediaVM(
                    media_id="v1",
                    media_type="video",
                    key="uploads/t/catalog/p/v1.mp4",
                    filename="v1.mp4",
                    is_primary=False,
                    position=2,
                    meta_label="7 s",
                ),
            ),
            photo_count=2,
            video_count=1,
        )
    ]
    state.selected_id = str(_PRODUCT_ID)
    return state


def test_quitar_asks_first_and_volver_removes_nothing() -> None:
    state = _with_media()
    assert not state.remove_media_open
    state.ask_remove_media("m2")
    assert state.remove_media_open
    assert state.remove_media_title_text == "¿Quitar esta foto?"
    assert "ya no se usará" in state.remove_media_text
    assert "principal" not in state.remove_media_text  # m2 is not the main one
    state.set_remove_media_open(False)  # «Volver» / Esc
    assert not state.remove_media_open and state.remove_media_id == ""


def test_quitar_the_main_photo_says_who_takes_its_place_and_a_video_is_a_video() -> None:
    state = _with_media()
    state.ask_remove_media("m1")
    assert "pasa a ser la principal" in state.remove_media_text
    state.ask_remove_media("v1")
    assert state.remove_media_title_text == "¿Quitar este video?"
    assert state.remove_media_text.startswith("Este video")


def test_quitar_the_only_photo_says_the_product_is_left_without_one() -> None:
    """UX review: Qualify knows whether another photo is left, so it says it outright."""
    state = _with_media()
    state.ask_remove_media("m1")
    assert state.remove_media_text.endswith("La siguiente foto pasa a ser la principal.")
    state.products = [_product(media=(_media("m1", primary=True),), photo_count=1)]
    state.ask_remove_media("m1")
    assert state.remove_media_text.endswith("Tu producto quedará sin foto hasta que subas otra.")


def test_si_quitar_closes_the_dialog_and_runs_the_removal() -> None:
    state = _with_media()
    state.ask_remove_media("m2")
    spec = state.confirm_remove_media()
    assert spec is not None and state.remove_media_id == ""
    assert not state.remove_media_open
    assert state.confirm_remove_media() is None  # a second tap removes nothing more


def test_quitar_waits_while_another_media_change_runs() -> None:
    state = _with_media()
    state.media_busy = True
    state.ask_remove_media("m2")
    assert not state.remove_media_open


def test_the_header_counts_the_products_without_a_photo_and_filters_them() -> None:
    state = CatalogState()
    state.products = [
        _product("p1", photo_count=1, counts_label="1 foto"),
        _product("p2", photo_count=0),
        _product("p3", photo_count=3, counts_label="3 fotos"),
    ]
    assert state.product_count_label == "3 productos · 1 sin foto"
    assert state.show_missing_filter
    assert state.missing_filter_label == "Ver el que no tiene foto"
    assert [p.product_id for p in state.visible_products] == ["p1", "p2", "p3"]
    state.toggle_missing_photo()
    assert [p.product_id for p in state.visible_products] == ["p2"]
    assert state.missing_filter_label == "Ver todos los productos"
    # the last one gets its photo: the whole list comes back on its own
    state.products = [_product("p1", photo_count=1), _product("p2", photo_count=1)]
    assert state.product_count_label == "2 productos"
    assert not state.missing_filter_on and not state.show_missing_filter
    assert len(state.visible_products) == 2


def test_the_tile_actions_are_words_at_44_px_and_quitar_opens_the_dialog() -> None:
    from . import catalog_page

    source = Path(catalog_page.__file__).read_text(encoding="utf-8")
    tile = source[source.index("def _media_tile") : source.index("def _upload_zone")]
    assert "MAKE_PRIMARY" in tile and "REMOVE_MEDIA" in tile
    assert "icon_button" not in tile and "tooltip" not in tile
    assert tile.count("min_height=_TOUCH_MIN") >= 2
    assert "CatalogState.ask_remove_media(item.media_id)" in tile
    assert "CatalogState.delete_media(" not in tile  # never a removal on the first tap
    rendered = str(catalog_page.catalog_index())
    for words in ("Principal", "Quitar", "Volver", "Sí, quitar"):
        assert json.dumps(words)[1:-1] in rendered
    assert "×" not in tile and "px" not in "".join(_visible_strings(tile))

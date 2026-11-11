"""Offline tests of the catalog's pure parts (slug, price label, record properties) and
of `add_media`'s normalization branch through a fake store, with the session door
patched — the roundtrip against Postgres is `test_catalog_service_db.py`."""

from __future__ import annotations

import io
from decimal import Decimal
from uuid import uuid4

import pytest
from PIL import Image

from qualify_api.catalog.read import price_label
from qualify_api.catalog.service import MediaRecord, ProductRecord, slugify


def test_slugify_is_ascii_lowercase_and_never_empty() -> None:
    assert slugify("Shawarma Mixto ¡Extra!") == "shawarma-mixto-extra"
    assert slugify("Helado de yogurt: fresa & mango") == "helado-de-yogurt-fresa-mango"
    assert slugify("   ") == "producto"


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        ("25000.00", "COP", "$25.000"),
        ("1234567.50", "COP", "$1.234.567,50"),
        ("1000000000", "COP", "$1.000.000.000"),
        ("9999999999.99", "COP", "$9.999.999.999,99"),
        ("10.00", "USD", "$10"),
        ("10.50", "USD", "$10,50"),
        ("1000.50", "USD", "$1000,50"),
        ("9999999999.99", "USD", "$9999999999,99"),
        ("90", "VES", "Bs. 90"),
        ("1234.05", "VES", "Bs. 1.234,05"),
        ("9999999999.99", "VES", "Bs. 9.999.999.999,99"),
        ("25000", "UYU", "$25.000"),
        ("1234.50", "UYU", "$1.234,50"),
        ("9999999999.99", "UYU", "$9.999.999.999,99"),
        ("4.50", "usd", "$4,50"),
        ("0", "COP", "$0"),
        ("0.05", "USD", "$0,05"),
        ("0.999", "USD", "$1"),
        ("12.50", "EUR", "€12.5"),
        ("1234.50", "GBP", "1234.5 GBP"),
        ("12", "", "12"),
        (None, "USD", ""),
    ],
)
def test_price_label_knows_the_pilots_currencies(
    amount: str | None, currency: str, expected: str
) -> None:
    value = Decimal(amount) if amount is not None else None
    assert price_label(value, currency) == expected


def test_product_record_derives_its_primary_photo_and_counts() -> None:
    def media(kind: str, key: str, primary: bool = False, position: int = 0) -> MediaRecord:
        return MediaRecord(uuid4(), kind, key, key, "", 1080, 1350, None, 10, primary, position)

    record = ProductRecord(
        id=uuid4(),
        brand_id=uuid4(),
        name="Mixto",
        slug="mixto",
        description="",
        price_amount=Decimal("5"),
        price_currency="USD",
        category="",
        tags=(),
        is_active=True,
        position=0,
        media=(
            media("video", "v.mp4", position=0),
            media("image", "a.jpg", position=1),
            media("image", "b.jpg", primary=True, position=2),
        ),
    )
    assert record.primary_photo_key == "b.jpg"
    assert record.photo_count == 2 and record.video_count == 1
    assert record.price_label == "$5"


def _jpeg(size: tuple[int, int] = (2400, 3200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 40, 40)).save(out, format="JPEG")
    return out.getvalue()


def test_add_media_normalizes_the_photo_before_storing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The store receives a 1080-wide JPEG (export_for_instagram), never the phone's
    original; the row carries the exported dimensions. The DB door is faked."""
    from qualify_api.catalog import service as mod

    class Store:
        def __init__(self) -> None:
            self.files: dict[str, bytes] = {}

        def read(self, key: str) -> bytes:
            return self.files[key]

        def write(self, key: str, data: bytes) -> None:
            self.files[key] = data

    class Product:
        def __init__(self, pid, brand_id):
            self.id, self.brand_id = pid, brand_id

    added: list[object] = []

    class Session:
        def __init__(self, product):
            self._product = product

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get(self, model, pid):
            return self._product if pid == self._product.id else None

        def scalars(self, stmt):
            return []

        def add(self, row):
            added.append(row)

        def flush(self):
            for row in added:
                if getattr(row, "id", None) is None:
                    row.id = uuid4()

    product = Product(uuid4(), uuid4())
    monkeypatch.setattr(mod, "tenant_session", lambda tenant_id: Session(product))
    store = Store()
    service = mod.CatalogService(store=store)
    tenant_id = uuid4()

    record = service.add_media(
        tenant_id=tenant_id, product_id=product.id, data=_jpeg(), filename="IMG_0001.JPG"
    )

    (key, data) = next(iter(store.files.items()))
    # CM-9 (m-24957283): an R2 key under the tenant's uploads, a fresh uuid4 per file
    assert key.startswith(f"t/{tenant_id}/uploads/catalog/{product.id}/") and key.endswith(".jpg")
    with Image.open(io.BytesIO(data)) as stored:
        assert stored.size == (1080, 1440)
    assert (record.width, record.height) == (1080, 1440)
    assert record.is_primary and record.media_type == "image" and record.position == 0
    assert added[0].normalized is True and added[0].bytes == len(data)


def test_add_media_refuses_an_unreadable_file_and_a_video_without_ffmpeg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.catalog import service as mod

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get(self, model, pid):
            return type("P", (), {"id": pid, "brand_id": uuid4()})()

        def scalars(self, stmt):
            return []

    monkeypatch.setattr(mod, "tenant_session", lambda tenant_id: Session())
    service = mod.CatalogService(
        store=type("S", (), {"write": lambda *a: None, "read": lambda *a: b""})()
    )
    with pytest.raises(mod.CatalogError, match="No pudimos abrir esta foto"):
        service.add_media(
            tenant_id=uuid4(), product_id=uuid4(), data=b"not an image", filename="x.jpg"
        )
    with pytest.raises(mod.CatalogError, match="Por ahora no podemos recibir videos"):
        service.add_media(tenant_id=uuid4(), product_id=uuid4(), data=b"\x00", filename="clip.mov")
    monkeypatch.setattr(mod, "MAX_JPEG_PIXELS", 100)
    with pytest.raises(mod.CatalogError, match=mod.PHOTO_DIMENSIONS_TEXT):
        service.add_media(
            tenant_id=uuid4(), product_id=uuid4(), data=_jpeg((20, 20)), filename="photo.jpg"
        )


def test_add_media_rejects_oversized_inputs_before_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.catalog import service as mod

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get(self, model, pid):
            return type("P", (), {"id": pid, "brand_id": uuid4()})()

        def scalars(self, stmt):
            return []

    monkeypatch.setattr(mod, "tenant_session", lambda tenant_id: Session())
    monkeypatch.setattr(mod, "MAX_PHOTO_BYTES", 2)
    monkeypatch.setattr(mod, "MAX_VIDEO_BYTES", 2)
    service = mod.CatalogService(store=type("S", (), {})())
    for filename, message in (("x.jpg", mod.PHOTO_SIZE_TEXT), ("x.mp4", mod.VIDEO_SIZE_TEXT)):
        with pytest.raises(mod.CatalogError, match=message):
            service.add_media(tenant_id=uuid4(), product_id=uuid4(), data=b"123", filename=filename)


def test_a_full_product_refuses_in_the_owners_words(monkeypatch: pytest.MonkeyPatch) -> None:
    """NAV-11 (m-24849129): the refusal the catalog screen shows as it is."""
    from qualify_api.catalog import service as mod

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get(self, model, pid):
            return type("P", (), {"id": pid, "brand_id": uuid4()})()

        def scalars(self, stmt):
            return [object()] * mod.MAX_MEDIA_PER_PRODUCT

    monkeypatch.setattr(mod, "tenant_session", lambda tenant_id: Session())
    service = mod.CatalogService(
        store=type("S", (), {"write": lambda *a: None, "read": lambda *a: b""})()
    )
    with pytest.raises(mod.CatalogError) as refused:
        service.add_media(tenant_id=uuid4(), product_id=uuid4(), data=b"x", filename="x.jpg")
    assert refused.value.args[0] == (
        "Cada producto puede tener hasta 12 fotos o videos. Quita alguno para subir otro."
    )


def test_every_catalog_refusal_is_spanish_and_carries_no_library_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.catalog import service as mod

    texts = (
        mod.NAME_REQUIRED_TEXT,
        mod.MEDIA_FULL_TEXT,
        mod.VIDEO_UNAVAILABLE_TEXT,
        mod.VIDEO_UNREADABLE_TEXT,
        mod.PHOTO_UNREADABLE_TEXT,
    )
    for text in texts:
        lowered = text.lower()
        assert not any(word in lowered for word in ("product ", "file", "upload", "at most"))
    # a library's own error never reaches the owner
    monkeypatch.setattr(
        mod, "load_normalized", lambda data: (_ for _ in ()).throw(OSError("cannot identify"))
    )

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get(self, model, pid):
            return type("P", (), {"id": pid, "brand_id": uuid4()})()

        def scalars(self, stmt):
            return []

    monkeypatch.setattr(mod, "tenant_session", lambda tenant_id: Session())
    service = mod.CatalogService(
        store=type("S", (), {"write": lambda *a: None, "read": lambda *a: b""})()
    )
    with pytest.raises(mod.CatalogError) as refused:
        service.add_media(tenant_id=uuid4(), product_id=uuid4(), data=b"x", filename="x.jpg")
    assert refused.value.args[0] == mod.PHOTO_UNREADABLE_TEXT
    with pytest.raises(mod.CatalogError) as unnamed:
        service.create_product(tenant_id=uuid4(), brand_id=uuid4(), user_id=uuid4(), name=" ")
    assert unnamed.value.args[0] == "El producto necesita un nombre."

"""`db`-marked tests for migration 0065 (`stock_assets`, `stock_asset_uses`) and the import
that writes it (plan STK-02/03): the provenance row, idempotency on the natural key, RLS
isolation (also with an empty `app.tenant_id` — the NULLIF), the CHECKs, and that the app
role cannot DELETE provenance. The R2 write and the download are fakes; the database is the
compose Postgres the root `conftest.py` migrates to head."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from PIL import Image
from qualify_creative.stock import StockItem, StockMediaType, StockRendition
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.stock.models import StockAsset
from qualify_api.stock.service import StockService
from qualify_api.stock.state import MemoryKeyValue
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

TENANT_A = UUID("a0000000-0000-4000-8000-0000000005a1")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000005b2")


@pytest.fixture
def brands() -> tuple[UUID, UUID]:
    with admin_session() as session:
        ids: dict[UUID, UUID] = {}
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"stock-t-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
            brand = session.scalar(select(Brand).where(Brand.tenant_id == tid))
            if brand is None:
                brand = Brand(tenant_id=tid, name=f"stock-brand-{name}")
                session.add(brand)
                session.flush()
            ids[tid] = brand.id
    return ids[TENANT_A], ids[TENANT_B]


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (600, 900), (200, 120, 40)).save(buf, "JPEG")
    return buf.getvalue()


class FakeGate:
    def __init__(self) -> None:
        self.puts: list[tuple[UUID, str, str]] = []

    def put_media(self, tenant_id, key, fileobj, content_type):  # noqa: ANN001
        self.puts.append((tenant_id, key, content_type))


class Provider:
    name = "pixabay"
    media_types = frozenset({StockMediaType.IMAGE})
    ai_input_allowed = True
    license_name = "Pixabay Content License"
    license_url = "https://pixabay.com/service/license-summary/"
    license_terms_date = "2024-11-18"

    def search(self, query, *, client=None):  # noqa: ANN001, ANN201
        raise AssertionError("not used")

    def resolve_download(self, item, *, client=None):  # noqa: ANN001, ANN201
        return item.best


def _item(media_id: str, *, no_ai: bool = False) -> StockItem:
    return StockItem(
        provider="pixabay",
        provider_media_id=media_id,
        media_type=StockMediaType.IMAGE,
        width=4000,
        height=6000,
        duration_sec=None,
        thumb_url="https://cdn.pixabay.com/x_150.jpg",
        author_name="Domihattenberger",
        author_url="https://pixabay.com/users/40104971/",
        page_url=f"https://pixabay.com/es/photos/x-{media_id}/",
        description="hamburguesa, comida",
        best=StockRendition(
            url=f"https://pixabay.com/get/{media_id}.jpg", width=853, height=1280, label="large"
        ),
        no_ai=no_ai,
        raw={"id": int(media_id), "tags": "hamburguesa, comida"},
    )


def _fresh_id() -> str:
    """Rows persist between local runs: a new id per test keeps the natural key fresh."""
    return str(uuid4().int % 10**12)


def _service(gate: FakeGate, downloads: list[str]) -> StockService:
    def download(url: str, max_bytes: int) -> tuple[bytes, str]:
        downloads.append(url)
        return _jpeg(), "image/jpeg"

    return StockService(
        providers=[Provider()],
        state=MemoryKeyValue(),
        gate=gate,
        download=download,
        searches_per_hour=30,
        imports_per_hour=20,
        clock=lambda: datetime(2026, 10, 16, 15, tzinfo=UTC),
    )


def test_import_writes_r2_then_a_full_provenance_row_once(brands: tuple[UUID, UUID]) -> None:
    brand_a, _ = brands
    gate, downloads = FakeGate(), []
    service = _service(gate, downloads)
    media_id = _fresh_id()
    first = service.import_item(
        tenant_id=TENANT_A,
        brand_id=brand_a,
        user_id=None,
        item=_item(media_id),
        search_query="  Hamburguesa  doble ",
        search_filters={"orientation": "portrait"},
    )
    assert first.object_key.startswith(f"t/{TENANT_A}/stock/pixabay/{media_id}/")
    assert first.object_key.endswith(".jpg")
    assert gate.puts == [(TENANT_A, first.object_key, "image/jpeg")]
    # export_for_instagram brings it to Meta's 1080 px width, same proportions
    assert (first.width, first.height) == (1080, 1620)
    assert first.ai_input_allowed is True

    again = service.import_item(
        tenant_id=TENANT_A, brand_id=brand_a, user_id=None, item=_item(media_id), search_query="x"
    )
    assert again.id == first.id
    assert len(downloads) == 1 and len(gate.puts) == 1  # no second download

    with tenant_session(TENANT_A) as session:
        row = session.get(StockAsset, first.id)
        assert row is not None
        assert row.search_query == "Hamburguesa doble"
        assert row.search_filters == {"orientation": "portrait"}
        assert row.license_name == "Pixabay Content License"
        assert str(row.license_terms_date) == "2024-11-18"
        assert row.source_page_url.startswith("https://pixabay.com/")
        assert row.author_name == "Domihattenberger"
        assert row.provider_payload["id"] == int(media_id)
        assert row.importer_version == "stock-import/1"
        assert row.people_filter is True and row.people_filter_version == "people-blocklist/1"
        assert len(row.sha256) == 64 and row.bytes > 0


def test_an_author_ai_opt_out_is_recorded(brands: tuple[UUID, UUID]) -> None:
    brand_a, _ = brands
    record = _service(FakeGate(), []).import_item(
        tenant_id=TENANT_A,
        brand_id=brand_a,
        user_id=None,
        item=_item(_fresh_id(), no_ai=True),
        search_query="x",
    )
    assert record.ai_input_allowed is False


def test_rls_isolates_tenants_and_an_empty_tenant_sees_nothing(brands: tuple[UUID, UUID]) -> None:
    brand_a, _ = brands
    record = _service(FakeGate(), []).import_item(
        tenant_id=TENANT_A,
        brand_id=brand_a,
        user_id=None,
        item=_item(_fresh_id()),
        search_query="x",
    )
    with tenant_session(TENANT_B) as session:
        assert session.get(StockAsset, record.id) is None
    with tenant_session(TENANT_A) as session:
        session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        count = session.scalar(text("SELECT count(*) FROM stock_assets"))
        assert count == 0


def test_the_app_role_cannot_delete_provenance(brands: tuple[UUID, UUID]) -> None:
    with pytest.raises(DBAPIError) as exc:
        with tenant_session(TENANT_A) as session:
            session.execute(text("DELETE FROM stock_assets WHERE false"))
    assert "permission denied" in str(exc.value).lower()


def test_checks_refuse_an_unknown_provider_and_slot(brands: tuple[UUID, UUID]) -> None:
    brand_a, _ = brands
    with pytest.raises(IntegrityError):
        with tenant_session(TENANT_A) as session:
            session.add(
                StockAsset(
                    tenant_id=TENANT_A,
                    brand_id=brand_a,
                    provider="unsplash",
                    provider_media_id="1",
                    media_type="image",
                    rendition="large",
                    object_key=f"t/{TENANT_A}/stock/unsplash/1/x.jpg",
                    content_type="image/jpeg",
                    width=1,
                    height=1,
                    bytes=1,
                    sha256="0" * 64,
                    source_page_url="https://x",
                    license_name="x",
                    license_url="https://x",
                    license_terms_date=datetime(2024, 1, 1).date(),
                    search_query="x",
                    provider_payload={},
                    ai_input_allowed=False,
                    people_filter=True,
                    importer_version="stock-import/1",
                    downloaded_at=datetime.now(UTC),
                )
            )
            session.flush()
    with pytest.raises(DBAPIError):
        with tenant_session(TENANT_A) as session:
            session.execute(
                text(
                    "INSERT INTO stock_asset_uses (tenant_id, stock_asset_id, draft_id, revision,"
                    " slot, sent_to_ai) SELECT :t, gen_random_uuid(), gen_random_uuid(), 1,"
                    " 'avatar', false"
                ),
                {"t": str(TENANT_A)},
            )


def test_a_stock_video_is_normalized_and_stored_with_its_poster(brands: tuple[UUID, UUID]) -> None:
    from qualify_api.stock.service import StockVideoFile

    brand_a, _ = brands
    gate, seen = FakeGate(), []

    def normalize(data: bytes, width: int, height: int) -> StockVideoFile:
        seen.append((data, width, height))
        return StockVideoFile(data=b"mp4", width=1080, height=1920, duration_sec=7.0, poster=b"jpg")

    service = StockService(
        providers=[Provider()],
        state=MemoryKeyValue(),
        gate=gate,
        download=lambda url, cap: (b"raw-video", "video/mp4"),
        video_normalizer=normalize,
        searches_per_hour=30,
        imports_per_hour=20,
    )
    media_id = _fresh_id()
    item = _item(media_id)
    video = StockItem(
        **{
            **item.__dict__,
            "media_type": StockMediaType.VIDEO,
            "duration_sec": 24.0,
            "best": StockRendition(
                url="https://cdn.pixabay.com/v.mp4", width=1080, height=1920, label="small"
            ),
        }
    )
    record = service.import_item(
        tenant_id=TENANT_A, brand_id=brand_a, user_id=None, item=video, search_query="parrilla"
    )
    assert seen == [(b"raw-video", 1080, 1920)]
    assert record.media_type == "video" and record.object_key.endswith(".mp4")
    assert f"/stock/pixabay/video-{media_id}/" in record.object_key
    assert record.poster_object_key and record.poster_object_key.endswith(".jpg")
    assert [(k.rsplit(".", 1)[1], ct) for _, k, ct in gate.puts] == [
        ("mp4", "video/mp4"),
        ("jpg", "image/jpeg"),
    ]
    assert record.duration_sec == 7.0
    with tenant_session(TENANT_A) as session:
        row = session.get(StockAsset, record.id)
        assert row.rendition == "video-small" and float(row.source_duration_sec) == 24.0

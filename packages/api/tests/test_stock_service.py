"""StockService.search offline — the shared 24 h cache, the per-tenant quota, the cool-down
after a 429 and the provider fallback (plan STK-03). No network, no Redis, no database:
a counting fake provider and the in-process key-value store."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from qualify_creative.stock import (
    StockError,
    StockItem,
    StockMediaType,
    StockNotConfigured,
    StockPage,
    StockQuery,
    StockRateLimited,
    StockRendition,
)

from qualify_api.stock import is_stock_key, stock_key_provider, stock_object_key
from qualify_api.stock.service import (
    BUSY_TEXT,
    CACHE_TTL_S,
    QUOTA_TEXT,
    UNAVAILABLE_TEXT,
    StockQuotaExceeded,
    StockService,
    StockUnavailable,
    http_download,
)
from qualify_api.stock.state import FallbackKeyValue, MemoryKeyValue

TENANT = UUID("11111111-1111-4111-8111-111111111111")
OTHER = UUID("22222222-2222-4222-8222-222222222222")


def _item(provider: str, n: int) -> StockItem:
    return StockItem(
        provider=provider,
        provider_media_id=str(n),
        media_type=StockMediaType.IMAGE,
        width=4000,
        height=6000,
        duration_sec=None,
        thumb_url=f"https://cdn.pixabay.com/{n}.jpg",
        author_name="autor",
        author_url=None,
        page_url=f"https://pixabay.com/photos/{n}/",
        description="hamburguesa",
        best=StockRendition(
            url=f"https://pixabay.com/get/{n}.jpg", width=853, height=1280, label="large"
        ),
        raw={"id": n},
    )


class FakeProvider:
    media_types = frozenset({StockMediaType.IMAGE})
    ai_input_allowed = True
    license_name = "Fake License"
    license_url = "https://example.com/license"
    license_terms_date = "2024-11-18"

    def __init__(self, name: str = "pixabay", *, results: int = 20, error: Exception | None = None):
        self.name = name
        self.results = results
        self.error = error
        self.calls: list[StockQuery] = []

    def search(self, query: StockQuery, *, client=None) -> StockPage:  # noqa: ANN001
        self.calls.append(query)
        if self.error is not None:
            raise self.error
        return StockPage(
            items=tuple(_item(self.name, i) for i in range(self.results)),
            page=query.page,
            has_more=True,
            total_hint=100,
            dropped={"people": 2},
        )

    def resolve_download(self, item: StockItem, *, client=None) -> StockRendition:  # noqa: ANN001
        return item.best


class SpyKeyValue(MemoryKeyValue):
    def __init__(self) -> None:
        super().__init__()
        self.ttls: list[int] = []

    def set_json(self, key, value, ttl_s):  # noqa: ANN001
        self.ttls.append(ttl_s)
        super().set_json(key, value, ttl_s)


def _service(*providers: FakeProvider, state=None, per_hour: int = 30) -> StockService:  # noqa: ANN001
    return StockService(
        providers=providers,
        state=state or MemoryKeyValue(),
        searches_per_hour=per_hour,
        imports_per_hour=20,
        clock=lambda: datetime(2026, 10, 16, 15, tzinfo=UTC),
    )


def test_a_cache_hit_spends_no_provider_call_and_no_quota() -> None:
    state = SpyKeyValue()
    provider = FakeProvider()
    service = _service(provider, state=state, per_hour=1)
    first = service.search(TENANT, "  Hamburguesa  ")
    assert first.cached is False and len(first.items) == 20
    assert state.ttls == [CACHE_TTL_S]
    # another tenant, same words (case and spaces aside): served from the shared cache,
    # and with a quota of 1 already spent by TENANT it would otherwise be refused
    again = service.search(TENANT, "hamburguesa")
    other = service.search(OTHER, "HAMBURGUESA")
    assert len(provider.calls) == 1
    assert again.cached and other.cached
    assert [i.provider_media_id for i in other.items] == [i.provider_media_id for i in first.items]
    assert other.dropped == {"people": 2}


def test_quota_exhausted_refuses_new_searches_but_the_cache_still_answers() -> None:
    provider = FakeProvider()
    service = _service(provider, per_hour=2)
    service.search(TENANT, "uno")
    service.search(TENANT, "dos")
    with pytest.raises(StockQuotaExceeded) as exc:
        service.search(TENANT, "tres")
    assert exc.value.args[0] == QUOTA_TEXT
    assert service.search(TENANT, "uno").cached
    service.search(OTHER, "tres")  # the quota is per tenant
    assert len(provider.calls) == 3


def test_a_429_cools_the_provider_down_and_is_not_retried() -> None:
    provider = FakeProvider(error=StockRateLimited("slow down", retry_after_s=40))
    state = MemoryKeyValue(clock=lambda: 1000.0)  # frozen: the TTL read is exact
    service = _service(provider, state=state)
    with pytest.raises(StockUnavailable) as exc:
        service.search(TENANT, "gimnasio")
    assert exc.value.args[0] == BUSY_TEXT
    assert state.ttl("stock:cooldown:pixabay") == 40
    with pytest.raises(StockUnavailable):
        service.search(TENANT, "otra cosa")
    assert len(provider.calls) == 1  # cooling down: not asked again


def test_fallback_only_when_the_first_provider_falls_short_or_fails() -> None:
    plenty, backup = FakeProvider("pexels", results=12), FakeProvider("pixabay")
    result = _service(plenty, backup).search(TENANT, "mesa de madera")
    assert result.providers == ("pexels",) and backup.calls == []

    short, backup = FakeProvider("pexels", results=5), FakeProvider("pixabay")
    result = _service(short, backup).search(TENANT, "mesa de madera")
    assert result.providers == ("pexels", "pixabay") and len(result.items) == 25

    broken, backup = (
        FakeProvider("pexels", error=StockError("down", status_code=503)),
        FakeProvider(),
    )
    result = _service(broken, backup).search(TENANT, "mesa de madera")
    assert result.providers == ("pixabay",)


def test_no_provider_or_a_bad_key_reads_unavailable() -> None:
    with pytest.raises(StockUnavailable) as exc:
        _service().search(TENANT, "x")
    assert exc.value.args[0] == UNAVAILABLE_TEXT
    with pytest.raises(StockUnavailable) as exc:
        _service(FakeProvider(error=StockNotConfigured("no key"))).search(TENANT, "x")
    assert exc.value.args[0] == UNAVAILABLE_TEXT


def test_a_zero_quota_turns_the_tab_off() -> None:
    service = _service(FakeProvider(), per_hour=0)
    assert service.available is False
    with pytest.raises(StockUnavailable):
        service.search(TENANT, "x")


def test_an_empty_query_is_refused_without_spending() -> None:
    provider = FakeProvider()
    with pytest.raises(StockUnavailable):
        _service(provider).search(TENANT, "   ")
    assert provider.calls == []


def test_redis_down_degrades_to_the_in_process_store() -> None:
    class Down:
        def __getattr__(self, name):  # noqa: ANN001, ANN204
            def fail(*a, **k):  # noqa: ANN002, ANN003, ANN202
                raise ConnectionError("redis down")

            return fail

    provider = FakeProvider()
    service = _service(provider, state=FallbackKeyValue(Down()), per_hour=1)
    service.search(TENANT, "x")
    with pytest.raises(StockQuotaExceeded):  # still limited, never unlimited
        service.search(TENANT, "y")


def test_stock_key_shape_and_recognition() -> None:
    key = stock_object_key(TENANT, "pixabay", "8434113", "ab" * 32, "jpg")
    assert key == f"t/{TENANT}/stock/pixabay/8434113/{'ab' * 8}.jpg"
    assert is_stock_key(key) and stock_key_provider(key) == "pixabay"
    assert not is_stock_key(f"t/{TENANT}/generated/d/r1/x.jpg")
    assert not is_stock_key(f"uploads/{TENANT}/stock/x/y/z.jpg")
    with pytest.raises(ValueError):
        stock_object_key(TENANT, "pixabay", "../x", "ab" * 32, "jpg")


def test_download_refuses_a_host_outside_the_list_before_the_network() -> None:
    for url in (
        "https://evil.example.com/x.jpg",
        "http://pixabay.com/get/x.jpg",
        "https://pixabay.com.evil.io/x.jpg",
        "https://169.254.169.254/latest",
    ):
        with pytest.raises(StockError):
            http_download(url, 1024)


# -- the Brand Kit's search (§ request 2026-10-16) -----------------------------------------


def test_kit_queries_are_the_rubro_then_the_hashtags_and_the_niche_last() -> None:
    from qualify_api.stock.queries import MAX_CANDIDATES, kit_queries

    queries = kit_queries(
        rubro=("smashburguer",),
        hashtags=("#Hamburguesas", "burger", "hamburguesas", "x"),
        niches=("Comida y bebida",),
    )
    assert queries == ["smashburguer", "hamburguesas", "burger"]  # the niche is not needed
    assert kit_queries(niches=("Comida y bebida",)) == ["comida y bebida"]
    assert len(kit_queries(hashtags=[f"tag{i}" for i in range(20)])) == MAX_CANDIDATES
    assert kit_queries() == []


class ByQuery(FakeProvider):
    def __init__(self, counts: dict[str, int], *, fail: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.counts = counts
        self.fail = fail

    def search(self, query: StockQuery, *, client=None) -> StockPage:  # noqa: ANN001
        if query.text in self.fail:
            raise StockError("down", status_code=503)
        page = StockPage(
            items=tuple(
                _item(self.name, f"{query.text}-{i}") for i in range(self.counts.get(query.text, 0))
            ),
            page=query.page,
            has_more=False,
            total_hint=None,
        )
        self.calls.append(query)
        return page


def test_search_many_runs_every_word_mixes_them_and_charges_once() -> None:
    provider = ByQuery({"smashburguer": 0, "hamburguesas": 3, "burger": 2, "comida": 1})
    service = _service(provider, per_hour=1)  # one search left: the whole click fits in it
    used, result = service.search_many(
        TENANT, ["smashburguer", "hamburguesas", "burger", "comida", "never"]
    )
    # «smashburguer» brought nothing, so «never» got its place in a second wave
    assert sorted(q.text for q in provider.calls) == [
        "burger",
        "comida",
        "hamburguesas",
        "never",
        "smashburguer",
    ]
    assert used == ("hamburguesas", "burger", "comida")  # words that brought images
    # round-robin: the page alternates the words instead of listing one after the other
    assert [i.provider_media_id for i in result.items] == [
        "hamburguesas-0", "burger-0", "comida-0", "hamburguesas-1", "burger-1", "hamburguesas-2",
    ]  # fmt: skip
    with pytest.raises(StockQuotaExceeded):  # the click spent the hour's one search
        service.search(TENANT, "otra")


def test_search_many_leaves_a_failing_word_out() -> None:
    provider = ByQuery({"a b c": 2}, fail=("d e f",))
    used, result = _service(provider).search_many(TENANT, ["a b c", "d e f"])
    assert used == ("a b c",) and len(result.items) == 2


def test_search_many_raises_when_every_word_fails_or_there_is_none() -> None:
    with pytest.raises(StockUnavailable):
        _service(ByQuery({}, fail=("x y z",))).search_many(TENANT, ["x y z"])
    with pytest.raises(StockUnavailable):
        _service(FakeProvider()).search_many(TENANT, ["  ", ""])


def test_a_stock_video_keeps_its_proportions_within_1080x1920() -> None:
    from qualify_api.stock.service import video_target_size

    assert video_target_size(2160, 3840) == (1080, 1920)  # 4K vertical, scaled down
    assert video_target_size(3840, 2160) == (1920, 1080)  # 4K horizontal
    assert video_target_size(720, 1280) == (720, 1280)  # never scaled up
    assert video_target_size(1081, 1921) == (1080, 1918)  # even sides for H.264

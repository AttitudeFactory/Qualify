"""PixabayProvider against `httpx.MockTransport` — the request it sends, the shape it
returns, and that the key never leaks (plan STK-01). Hits are trimmed copies of what the
real API answered on 2026-10-16."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from qualify_creative.stock import (
    Orientation,
    PixabayProvider,
    StockError,
    StockMediaType,
    StockNotConfigured,
    StockQuery,
    StockRateLimited,
    names_a_person,
)

KEY = "test-key-0000"


def _image_hit(media_id: int = 8434113, **over: Any) -> dict[str, Any]:
    hit = {
        "id": media_id,
        "pageURL": f"https://pixabay.com/es/photos/hamburguesa-{media_id}/",
        "type": "photo",
        "tags": "hamburguesa, comida rápida, queso",
        "previewURL": f"https://cdn.pixabay.com/photo/2023/12/06/x-{media_id}_150.jpg",
        "webformatURL": f"https://pixabay.com/get/gWEB{media_id}_640.jpg",
        "largeImageURL": f"https://pixabay.com/get/gLARGE{media_id}_1280.jpg",
        "imageWidth": 4000,
        "imageHeight": 6000,
        "user_id": 40104971,
        "user": "Domihattenberger",
        "userURL": "https://pixabay.com/users/40104971/",
        "noAiTraining": False,
        "isAiGenerated": False,
    }
    hit.update(over)
    return hit


def _video_hit(media_id: int = 199545, *, vertical: bool = True, **over: Any) -> dict[str, Any]:
    def size(w: int, h: int, name: str) -> dict[str, Any]:
        w, h = (h, w) if vertical else (w, h)
        return {
            "url": f"https://cdn.pixabay.com/video/x/{media_id}_{name}.mp4",
            "width": w,
            "height": h,
            "size": 1,
            "thumbnail": f"https://cdn.pixabay.com/video/x/{media_id}_{name}.jpg",
        }

    hit = {
        "id": media_id,
        "pageURL": f"https://pixabay.com/videos/id-{media_id}/",
        "tags": "hamburguesa, parrilla",
        "duration": 7,
        "videos": {
            "large": size(3840, 2160, "large"),
            "medium": size(2560, 1440, "medium"),
            "small": size(1920, 1080, "small"),
            "tiny": size(1280, 720, "tiny"),
        },
        "user_id": 19168820,
        "user": "Kaffeesüchtig",
        "userURL": "https://pixabay.com/users/19168820/",
        "noAiTraining": False,
    }
    hit.update(over)
    return hit


def _client(
    hits: list[dict[str, Any]], *, total: int = 106, seen: list[httpx.Request] | None = None
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        body = {"total": total, "totalHits": total, "hits": hits}
        return httpx.Response(200, json=body, headers={"X-RateLimit-Remaining": "99"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _status(code: int, text: str = "", headers: dict[str, str] | None = None) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(code, text=text, headers=headers))
    )


def test_image_search_sends_spanish_safe_vertical_photo_query() -> None:
    seen: list[httpx.Request] = []
    PixabayProvider(KEY).search(
        StockQuery(text="  hamburguesa   doble ", orientation=Orientation.PORTRAIT, per_page=24),
        client=_client([_image_hit()], seen=seen),
    )
    (request,) = seen
    assert request.url.host == "pixabay.com" and request.url.path == "/api/"
    params = dict(request.url.params)
    assert params == {
        "key": KEY,
        "q": "hamburguesa doble",
        "lang": "es",
        "safesearch": "true",
        "page": "1",
        "per_page": "24",
        "image_type": "photo",
        "orientation": "vertical",
    }


def test_image_hit_normalizes_and_drops_expiring_urls_from_raw() -> None:
    page = PixabayProvider(KEY).search(
        StockQuery(text="hamburguesa"), client=_client([_image_hit()])
    )
    (item,) = page.items
    assert item.provider == "pixabay" and item.provider_media_id == "8434113"
    assert item.media_type is StockMediaType.IMAGE
    assert (item.width, item.height) == (4000, 6000)
    # largeImageURL is ≤1280 px on its longer side
    assert (item.best.width, item.best.height, item.best.label) == (853, 1280, "large")
    assert item.thumb_url.endswith("_640.jpg")
    assert item.author_name == "Domihattenberger"
    assert item.author_url == "https://pixabay.com/users/40104971/"
    assert item.page_url.startswith("https://pixabay.com/es/photos/")
    assert "webformatURL" not in item.raw and "largeImageURL" not in item.raw
    assert item.raw["previewURL"].startswith("https://cdn.pixabay.com/")
    assert page.has_more is True and page.total_hint == 106


def test_people_and_no_ai_hits_are_dropped_and_counted() -> None:
    hits = [
        _image_hit(1),
        _image_hit(2, tags="mujer, retrato, maquillaje"),
        _image_hit(3, noAiTraining=True),
        _image_hit(4, tags="manos, uñas, esmalte"),
    ]
    page = PixabayProvider(KEY).search(StockQuery(text="uñas"), client=_client(hits))
    assert [i.provider_media_id for i in page.items] == ["1", "4"]
    assert page.dropped == {"people": 1, "no_ai": 1}


def test_people_filter_can_be_turned_off() -> None:
    hits = [_image_hit(2, tags="mujer, retrato")]
    page = PixabayProvider(KEY).search(
        StockQuery(text="x", exclude_people=False), client=_client(hits)
    )
    assert len(page.items) == 1


def test_category_people_is_never_sent() -> None:
    seen: list[httpx.Request] = []
    provider = PixabayProvider(KEY)
    provider.search(StockQuery(text="x", category="people"), client=_client([], seen=seen))
    provider.search(StockQuery(text="x", category="food"), client=_client([], seen=seen))
    assert "category" not in seen[0].url.params
    assert seen[1].url.params["category"] == "food"


def test_has_more_stops_at_the_500_hit_ceiling() -> None:
    page = PixabayProvider(KEY).search(
        StockQuery(text="casa", page=21, per_page=24), client=_client([], total=5268)
    )
    assert page.has_more is False  # 21 × 24 = 504 > 500


def test_video_search_filters_horizontal_and_picks_1080_rendition() -> None:
    seen: list[httpx.Request] = []
    hits = [_video_hit(1, vertical=True), _video_hit(2, vertical=False)]
    page = PixabayProvider(KEY).search(
        StockQuery(
            text="gimnasio", media_type=StockMediaType.VIDEO, orientation=Orientation.PORTRAIT
        ),
        client=_client(hits, seen=seen),
    )
    assert seen[0].url.path == "/api/videos/"
    assert "orientation" not in seen[0].url.params  # Pixabay video has no such filter
    (item,) = page.items
    assert (item.best.width, item.best.height, item.best.label) == (1080, 1920, "small")
    assert item.duration_sec == 7.0
    assert page.dropped == {"orientation": 1}


def test_resolve_download_asks_again_by_id() -> None:
    seen: list[httpx.Request] = []
    provider = PixabayProvider(KEY)
    (item,) = provider.search(StockQuery(text="x"), client=_client([_image_hit()])).items
    fresh = _image_hit(largeImageURL="https://pixabay.com/get/gFRESH_1280.jpg")
    rendition = provider.resolve_download(item, client=_client([fresh], seen=seen))
    assert seen[0].url.params["id"] == "8434113"
    assert rendition.url == "https://pixabay.com/get/gFRESH_1280.jpg"


def test_resolve_download_of_a_withdrawn_item_raises_404() -> None:
    provider = PixabayProvider(KEY)
    (item,) = provider.search(StockQuery(text="x"), client=_client([_image_hit()])).items
    with pytest.raises(StockError) as exc:
        provider.resolve_download(item, client=_client([]))
    assert exc.value.status_code == 404


def test_missing_key_is_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUALIFY_PIXABAY_API_KEY", raising=False)
    with pytest.raises(StockNotConfigured):
        PixabayProvider().search(StockQuery(text="x"), client=_client([]))


def test_key_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_PIXABAY_API_KEY", "env-key")
    seen: list[httpx.Request] = []
    PixabayProvider().search(StockQuery(text="x"), client=_client([], seen=seen))
    assert seen[0].url.params["key"] == "env-key"


def test_bad_key_answers_400_and_maps_to_not_configured() -> None:
    client = _status(400, "[ERROR 400] Invalid or missing API key")
    with pytest.raises(StockNotConfigured) as exc:
        PixabayProvider(KEY).search(StockQuery(text="x"), client=client)
    assert KEY not in str(exc.value)


def test_429_is_rate_limited_with_reset() -> None:
    with pytest.raises(StockRateLimited) as exc:
        PixabayProvider(KEY).search(
            StockQuery(text="x"), client=_status(429, headers={"X-RateLimit-Reset": "42"})
        )
    assert exc.value.retry_after_s == 42


def test_429_without_headers() -> None:
    with pytest.raises(StockRateLimited) as exc:
        PixabayProvider(KEY).search(StockQuery(text="x"), client=_status(429))
    assert exc.value.retry_after_s is None


def test_server_error_and_broken_json() -> None:
    with pytest.raises(StockError) as exc:
        PixabayProvider(KEY).search(StockQuery(text="x"), client=_status(503, "down"))
    assert exc.value.status_code == 503
    with pytest.raises(StockError):
        PixabayProvider(KEY).search(StockQuery(text="x"), client=_status(200, "<html>"))


def test_network_error_never_carries_the_url_with_the_key() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    client = httpx.Client(transport=httpx.MockTransport(boom))
    with pytest.raises(StockError) as exc:
        PixabayProvider(KEY).search(StockQuery(text="x"), client=client)
    assert KEY not in str(exc.value)
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


def test_empty_query_is_refused_before_the_network() -> None:
    with pytest.raises(StockError):
        PixabayProvider(KEY).search(StockQuery(text="   "), client=_status(500))


def test_the_key_never_lands_in_raw() -> None:
    page = PixabayProvider(KEY).search(StockQuery(text="x"), client=_client([_image_hit()]))
    assert KEY not in json.dumps(page.items[0].raw)


@pytest.mark.parametrize(
    ("words", "person"),
    [
        ("woman holding coffee", True),
        ("hand holding coffee", False),
        ("mesa de madera", False),
        ("mujer, retrato, maquillaje", True),
        ("sosteniendo las manos, uñas, esmalte", False),
        ("Niño en el parque", True),
        ("bebé, cuna", True),
        ("modelado 3d, render", False),
        ("parrilla, filete, cocinero", True),
        ("hamburguesa, papas a la francesa", False),
    ],
)
def test_people_blocklist(words: str, person: bool) -> None:
    assert names_a_person(words) is person


def test_a_video_carries_its_smallest_rendition_for_the_preview() -> None:
    (item,) = (
        PixabayProvider(KEY)
        .search(
            StockQuery(text="parrilla", media_type=StockMediaType.VIDEO),
            client=_client([_video_hit(1)]),
        )
        .items
    )
    assert item.preview_url == "https://cdn.pixabay.com/video/x/1_tiny.mp4"
    assert item.best.label == "small"  # the preview is never what gets imported

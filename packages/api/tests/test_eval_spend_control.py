"""Spend control for paid-vendor evals (m-24849234, PR 1A), offline: pricing quotes,
the spend ledger and its transport, reference encoding, path safety and the network
guard. No request leaves; nothing here imports a specific eval."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import socket
import threading
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image
from qualify_creative.adapters.byteplus_ark import DEFAULT_SEEDREAM_MODEL, SeedreamImageAdapter
from qualify_creative.enums import GenerationTask
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationRequest, RenderedPrompt

from qualify_api.evals import spend_control as sc

REPO_ROOT = Path(__file__).resolve().parents[3]


V6 = JsonPricingTable("v6")


PRO = sc.SEEDREAM_PRO


LITE = "seedream-5-0-lite-260128"


FLASH = "dola-seedream-5-0-flash-260915"


def _jpeg_b64() -> str:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(out, format="JPEG")
    return base64.b64encode(out.getvalue()).decode()


def _ok(generated: int = 1) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": PRO,
            "data": [{"b64_json": _jpeg_b64(), "size": "1024x1024"}],
            "usage": {"generated_images": generated, "output_tokens": 1},
        },
    )


def _adapter(handler: Any, ledger: sc.SpendLedger, q: sc.PriceQuote) -> SeedreamImageAdapter:
    transport = sc.LedgerTransport(httpx.MockTransport(handler), ledger, q, label="x")
    return SeedreamImageAdapter(model=PRO, transport=transport, sleep=lambda _s: None)


def _request(images: int = 2) -> GenerationRequest:
    return GenerationRequest(
        task=GenerationTask.PRODUCT_IMAGE,
        rendered_prompt=RenderedPrompt("", "", ""),
        params={
            "prompt": "p",
            "model": PRO,
            "size": "1K",
            "images": ["data:image/jpeg;base64,AA"] * images,
        },
    )


def _bytes(image: Image.Image, fmt: str) -> bytes:
    out = io.BytesIO()
    image.save(out, format=fmt)
    return out.getvalue()


def _decode(url: str) -> tuple[str, Image.Image]:
    head, data = url.split(",", 1)
    return head, Image.open(io.BytesIO(base64.b64decode(data)))


def _snap(ledger: sc.SpendLedger) -> dict[str, object]:
    """The snapshot with money as Decimals, so 0.000 == 0."""
    return {k: Decimal(v) if isinstance(v, str) else v for k, v in ledger.snapshot().items()}


class _FailingStream(httpx.SyncByteStream):
    def __iter__(self) -> Iterator[bytes]:
        yield b'{"data": ['
        raise httpx.ReadError("connection lost while reading the body")


class _StreamingInner(httpx.BaseTransport):
    def __init__(self) -> None:
        self.calls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(200, stream=_FailingStream())


def test_production_defaults_are_untouched() -> None:
    from qualify_api.creative.composition import PRICING_VERSION

    # v6 is the eval's table; production moved from v5 to v7 (Seedance 2.5 with-video
    # rates, m-24820142) and still never prices Seedream 5.0 pro.
    assert PRICING_VERSION == "v7"
    assert DEFAULT_SEEDREAM_MODEL == LITE


@pytest.mark.parametrize(
    ("size", "refs", "total"),
    [
        ("1K", 0, "0.045"),
        ("1K", 1, "0.045"),  # the first input image is free
        ("1K", 2, "0.048"),
        ("1.5K", 2, "0.048"),  # priced as 1K
        ("2K", 2, "0.093"),
        ("2K", 3, "0.096"),
        ("1536x1536", 2, "0.048"),  # 2.36 MP, under 2.61
        ("2048x2048", 1, "0.09"),
    ],
)
def test_pro_quote_by_tier_and_references(size: str, refs: int, total: str) -> None:
    q = sc.quote(V6, model_id=PRO, size=size, references=refs)
    assert q.total_usd == Decimal(total) == q.max_usd
    assert q.pricing_version == "v6"


def test_only_pro_bills_extra_references() -> None:
    lite = sc.quote(V6, model_id=LITE, size="2K", references=3)
    flash = sc.quote(V6, model_id=FLASH, size="2K", references=3)
    assert lite.total_usd == Decimal("0.035") and lite.references_usd == 0
    assert flash.total_usd == Decimal("0.018")


@pytest.mark.parametrize("size", ["3K", "4K", "100x100", "3000x3000", "big"])
def test_pro_rejects_sizes_it_cannot_make(size: str) -> None:
    with pytest.raises(ValueError):
        sc.quote(V6, model_id=PRO, size=size, references=1)


def test_layer_decomposition_estimate_and_worst_case() -> None:
    q = sc.quote(V6, model_id=PRO, size="1K", references=1, layer_decomposition=True)
    assert q.expected_images == 1 + sc.DEFAULT_EXPECTED_LAYERS == 9
    assert q.total_usd == Decimal("0.0225") * 9
    assert q.max_usd == Decimal("0.0225") * 17
    assert q.actual_usd(5) == Decimal("0.0225") * 5
    q2 = sc.quote(
        V6, model_id=PRO, size="2K", references=1, layer_decomposition=True, expected_layers=3
    )
    assert q2.total_usd == Decimal("0.045") * 4
    with pytest.raises(ValueError, match="exactly one"):
        sc.quote(V6, model_id=PRO, size="1K", references=2, layer_decomposition=True)


@pytest.mark.parametrize(
    ("model_id", "refs", "layers"),
    [
        (LITE, 1, True),  # lite has no layer decomposition price
        (FLASH, 1, True),  # flash offers it, but it is not priced in v6
        ("seedream_v4", 2, False),  # no row for extra references
        ("no-such-model", 1, False),
    ],
)
def test_missing_component_price_raises(model_id: str, refs: int, layers: bool) -> None:
    with pytest.raises(sc.MissingPriceError):
        sc.quote(V6, model_id=model_id, size="2K", references=refs, layer_decomposition=layers)


def test_unpriced_pro_in_v5_raises() -> None:
    with pytest.raises(sc.MissingPriceError):
        sc.quote(JsonPricingTable("v5"), model_id=PRO, size="1K", references=2)


def test_ledger_reserve_settle_release() -> None:
    ledger = sc.SpendLedger(Decimal("0.10"))
    a = ledger.reserve(Decimal("0.048"), label="a")
    b = ledger.reserve(Decimal("0.048"), label="b")
    assert ledger.remaining_usd == Decimal("0.004")
    with pytest.raises(sc.CeilingExceededError):
        ledger.reserve(Decimal("0.048"), label="c")
    ledger.release(a)
    ledger.settle(b, Decimal("0.045"))
    assert ledger.spent_usd == Decimal("0.045") and ledger.held_usd == 0
    with pytest.raises(ValueError):
        ledger.settle(b)  # already closed
    assert ledger.reservations == 2


@pytest.mark.parametrize("ceiling", ["10.01", "11", "0", "-1", "NaN"])
def test_ledger_rejects_bad_ceilings(ceiling: str) -> None:
    with pytest.raises(ValueError):
        sc.SpendLedger(Decimal(ceiling))


def test_ledger_never_overruns_under_threads() -> None:
    ledger = sc.SpendLedger(Decimal("10"))
    granted: list[sc.Reservation] = []
    refused: list[Exception] = []
    barrier = threading.Barrier(32)

    def worker() -> None:
        barrier.wait()
        for _ in range(10):
            try:
                granted.append(ledger.reserve(Decimal("0.15"), label="t"))
            except sc.CeilingExceededError as exc:
                refused.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(granted) == 66  # 66 x 0.15 = 9.90; a 67th would pass 10
    assert len(refused) == 320 - 66
    assert ledger.held_usd == Decimal("9.90") <= ledger.ceiling_usd


def test_retries_are_new_reservations_and_failures_are_released() -> None:
    q = sc.quote(V6, model_id=PRO, size="1K", references=2)
    ledger = sc.SpendLedger(Decimal("1"))
    answers = iter([httpx.Response(429, json={}), _ok()])
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(answers)

    _adapter(handler, ledger, q).generate(_request(), api_key="dummy")
    assert len(seen) == 2 and ledger.reservations == 2
    assert ledger.spent_usd == Decimal("0.048") and ledger.held_usd == 0
    body = json.loads(seen[-1].content)
    assert body["model"] == PRO and body["size"] == "1K"


def test_ceiling_stops_the_retry_before_it_is_sent() -> None:
    q = sc.quote(V6, model_id=PRO, size="1K", references=2)
    ledger = sc.SpendLedger(Decimal("0.05"))  # room for one attempt only
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.RemoteProtocolError("dropped")  # retried; settled at the worst case

    with pytest.raises(sc.CeilingExceededError):
        _adapter(handler, ledger, q).generate(_request(), api_key="dummy")
    assert len(seen) == 1 and ledger.spent_usd == Decimal("0.048")


def test_settles_at_generated_images_for_layers() -> None:
    q = sc.quote(V6, model_id=PRO, size="1K", references=1, layer_decomposition=True)
    ledger = sc.SpendLedger(Decimal("1"))
    _adapter(lambda _r: _ok(generated=6), ledger, q).generate(_request(1), api_key="dummy")
    assert ledger.spent_usd == Decimal("0.0225") * 6


def test_png_with_alpha_stays_png_with_alpha() -> None:
    logo = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
    logo.paste((200, 30, 30, 255), (50, 50, 250, 150))
    head, out = _decode(sc.reference_data_url(_bytes(logo, "PNG")))
    assert head == "data:image/png;base64"
    assert out.mode == "RGBA" and out.getchannel("A").getextrema() == (0, 255)
    assert out.getpixel((0, 0))[3] == 0 and out.getpixel((100, 100))[3] == 255


def test_palette_png_with_transparency_stays_png() -> None:
    logo = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    logo.paste((0, 120, 255, 255), (16, 16, 48, 48))
    head, out = _decode(sc.reference_data_url(_bytes(logo.convert("P"), "PNG")))
    assert head == "data:image/png;base64" and out.mode == "RGBA"


def test_repo_icon_keeps_alpha_and_opaque_mark_goes_jpeg() -> None:
    icon = (REPO_ROOT / "assets" / "qualify-icon-email.png").read_bytes()
    mark = (REPO_ROOT / "assets" / "qualify-mark-email.png").read_bytes()  # RGBA, opaque
    assert sc.encode_reference(icon)[0] == "image/png"
    assert sc.encode_reference(mark)[0] == "image/jpeg"


def test_opaque_images_go_jpeg_within_the_reference_size() -> None:
    photo = Image.new("RGB", (4000, 1000), (240, 200, 10))
    head, out = _decode(sc.reference_data_url(_bytes(photo, "PNG")))
    assert head == "data:image/jpeg;base64"
    assert max(out.size) == 2048


def test_large_alpha_png_is_downscaled_not_flattened() -> None:
    logo = Image.new("RGBA", (5000, 2500), (0, 0, 0, 0))
    logo.paste((1, 2, 3, 255), (100, 100, 4000, 2000))
    media, data = sc.encode_reference(_bytes(logo, "PNG"))
    out = Image.open(io.BytesIO(data))
    assert media == "image/png" and out.mode == "RGBA" and max(out.size) == 2048


def test_network_guard_blocks_and_counts() -> None:
    with sc.network_guard() as stats:
        with pytest.raises(RuntimeError, match="dry run"):
            socket.getaddrinfo("ark.ap-southeast.bytepluses.com", 443)
        with pytest.raises(RuntimeError, match="dry run"):
            socket.gethostbyname("ark.ap-southeast.bytepluses.com")
    assert stats["blocked"] == 2


def test_connect_error_releases_and_retries_reserve_again() -> None:
    q = sc.quote(V6, model_id=PRO, size="1K", references=2)
    ledger = sc.SpendLedger(Decimal("0.05"))  # room for one attempt at a time
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.ConnectError("refused")  # never reached the vendor

    with pytest.raises(httpx.ConnectError):
        _adapter(handler, ledger, q).generate(_request(), api_key="dummy")
    assert len(seen) == 3 and ledger.reservations == 3  # every retry reserved
    assert ledger.spent_usd == 0 and ledger.held_usd == 0


def test_dropped_connection_settles_the_worst_case() -> None:
    q = sc.quote(V6, model_id=PRO, size="1K", references=2)
    ledger = sc.SpendLedger(Decimal("1"))

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")  # the vendor may be working on it; not retried

    with pytest.raises(httpx.ReadTimeout):
        _adapter(handler, ledger, q).generate(_request(), api_key="dummy")
    assert ledger.spent_usd == Decimal("0.048")


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"code": "InputImageSensitiveContentDetected", "message": "no"}},
        {"data": [{"error": {"code": "OutputImageSensitiveContentDetected", "message": "no"}}]},
    ],
)
def test_moderated_answer_settles_at_zero(body: dict[str, Any]) -> None:
    q = sc.quote(V6, model_id=PRO, size="1K", references=2)
    ledger = sc.SpendLedger(Decimal("1"))
    with pytest.raises(Exception):  # noqa: B017 - the adapter raises its own error type
        _adapter(lambda _r: httpx.Response(200, json=body), ledger, q).generate(
            _request(), api_key="dummy"
        )
    assert ledger.spent_usd == 0 and ledger.held_usd == 0


def test_unreadable_answer_settles_the_worst_case() -> None:
    q = sc.quote(V6, model_id=PRO, size="1K", references=2)
    ledger = sc.SpendLedger(Decimal("1"))
    with pytest.raises(Exception):  # noqa: B017
        _adapter(lambda _r: httpx.Response(200, content=b"<html>"), ledger, q).generate(
            _request(), api_key="dummy"
        )
    assert ledger.spent_usd == Decimal("0.048")


def test_ledger_transport_closes_its_inner_transport() -> None:
    closed: list[bool] = []

    class Inner(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return _ok()

        def close(self) -> None:
            closed.append(True)

    q = sc.quote(V6, model_id=PRO, size="1K", references=2)
    ledger = sc.SpendLedger(Decimal("1"))
    sc.LedgerTransport(Inner(), ledger, q, label="x").close()
    assert closed == []  # borrowed (the default): its owner closes it
    sc.LedgerTransport(Inner(), ledger, q, label="x", owns_inner=True).close()
    assert closed == [True]


def test_5xx_releases_and_each_retry_reserves_again() -> None:
    q = sc.quote(V6, model_id=PRO, size="1K", references=2)
    ledger = sc.SpendLedger(Decimal("1"))
    answers = iter([httpx.Response(503, json={}), httpx.Response(503, json={}), _ok()])
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(answers)

    _adapter(handler, ledger, q).generate(_request(), api_key="dummy")
    snap = _snap(ledger)
    assert len(seen) == 3
    assert snap["reservations"] == 3 and snap["releases"] == 2 and snap["settlements"] == 1
    assert snap["spent_usd"] == Decimal("0.048") and snap["reserved_usd"] == Decimal("0.144")
    assert snap["held_usd"] == Decimal("0") and snap["open_reservations"] == 0


def test_500_is_released_and_not_retried() -> None:
    q = sc.quote(V6, model_id=PRO, size="1K", references=2)
    ledger = sc.SpendLedger(Decimal("1"))
    with pytest.raises(Exception):  # noqa: B017 - ArkAPIError
        _adapter(lambda _r: httpx.Response(500, json={}), ledger, q).generate(
            _request(), api_key="dummy"
        )
    snap = _snap(ledger)
    assert snap["reservations"] == 1 and snap["releases"] == 1 and snap["settlements"] == 0
    assert snap["spent_usd"] == Decimal("0") and snap["open_reservations"] == 0


def test_200_without_usage_or_error_settles_the_worst_case() -> None:
    q = sc.quote(V6, model_id=PRO, size="1K", references=2)
    ledger = sc.SpendLedger(Decimal("1"))
    body = {"model": PRO, "data": [{"b64_json": _jpeg_b64(), "size": "1024x1024"}]}
    _adapter(lambda _r: httpx.Response(200, json=body), ledger, q).generate(
        _request(), api_key="dummy"
    )
    snap = _snap(ledger)
    assert snap["spent_usd"] == Decimal("0.048") and snap["settlements"] == 1
    assert snap["open_reservations"] == 0


@pytest.mark.parametrize("generated", ["abc", 2.5, None, True, [1]])
def test_non_integer_generated_images_settles_the_worst_case(generated: object) -> None:
    q = sc.quote(V6, model_id=PRO, size="1K", references=2)
    ledger = sc.SpendLedger(Decimal("1"))
    body = {
        "data": [{"b64_json": _jpeg_b64()}],
        "usage": {"generated_images": generated},
    }
    # the adapter may then fail on the same field; the ledger has already settled
    with contextlib.suppress(ValueError, TypeError):
        _adapter(lambda _r: httpx.Response(200, json=body), ledger, q).generate(
            _request(), api_key="dummy"
        )
    snap = _snap(ledger)
    assert snap["spent_usd"] == Decimal("0.048") and snap["overage_usd"] == Decimal("0")
    assert snap["settlements"] == 1 and snap["open_reservations"] == 0


def test_body_read_failure_closes_the_reservation_exactly_once() -> None:
    q = sc.quote(V6, model_id=PRO, size="1K", references=2)
    ledger = sc.SpendLedger(Decimal("1"))
    inner = _StreamingInner()
    transport = sc.LedgerTransport(inner, ledger, q, label="x")
    adapter = SeedreamImageAdapter(model=PRO, transport=transport, sleep=lambda _s: None)
    with pytest.raises(httpx.ReadError):
        adapter.generate(_request(), api_key="dummy")
    snap = _snap(ledger)
    assert inner.calls == 1  # a read error is not retried by the adapter
    assert snap["reservations"] == 1 and snap["settlements"] == 1 and snap["releases"] == 0
    assert snap["spent_usd"] == Decimal("0.048") and snap["held_usd"] == Decimal("0")
    assert snap["open_reservations"] == 0


def test_settle_records_overage_without_clamping() -> None:
    ledger = sc.SpendLedger(Decimal("0.10"))
    r = ledger.reserve(Decimal("0.048"), label="a")
    assert ledger.settle(r, Decimal("0.138")) == Decimal("0.138")
    assert ledger.spent_usd == Decimal("0.138")
    assert ledger.overage_usd == Decimal("0.090")
    assert ledger.over_ceiling_usd == Decimal("0.038")
    with pytest.raises(sc.CeilingExceededError):
        ledger.reserve(Decimal("0"), label="b")
    with pytest.raises(sc.CeilingExceededError):
        ledger.reserve(Decimal("0.001"), label="b")


def test_connect_timeout_is_released_and_a_new_attempt_reserves_again() -> None:
    q = sc.quote(V6, model_id=PRO, size="1K", references=2)
    ledger = sc.SpendLedger(Decimal("1"))
    answers = iter([httpx.ConnectTimeout("no route"), None])
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        exc = next(answers)
        if exc:
            raise exc
        return _ok()

    adapter = _adapter(handler, ledger, q)
    # the adapter does not retry a ConnectTimeout itself (only ConnectError and a dropped
    # connection), so the next attempt is the caller's
    with pytest.raises(httpx.ConnectTimeout):
        adapter.generate(_request(), api_key="dummy")
    snap = _snap(ledger)
    assert snap["releases"] == 1 and snap["settlements"] == 0
    assert snap["spent_usd"] == Decimal(0) and snap["open_reservations"] == 0
    adapter.generate(_request(), api_key="dummy")
    snap = _snap(ledger)
    assert len(seen) == 2 and snap["reservations"] == 2
    assert snap["spent_usd"] == Decimal("0.048")


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("slow"),
        httpx.WriteTimeout("slow"),
        httpx.PoolTimeout("busy"),
    ],
)
def test_other_timeouts_settle_the_worst_case(error: Exception) -> None:
    q = sc.quote(V6, model_id=PRO, size="1K", references=2)
    ledger = sc.SpendLedger(Decimal("1"))

    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(type(error)):
        _adapter(handler, ledger, q).generate(_request(), api_key="dummy")
    snap = _snap(ledger)
    assert snap["settlements"] == 1 and snap["spent_usd"] == Decimal("0.048")


# --- 1A additions: 3xx, path safety ----------------------------------------------------


def test_3xx_is_not_a_generation_and_is_released() -> None:
    q = sc.quote(V6, model_id=PRO, size="1K", references=2)
    ledger = sc.SpendLedger(Decimal("1"))
    redirect = httpx.Response(302, headers={"Location": "https://example.invalid/"})
    with pytest.raises(Exception):  # noqa: B017 - the adapter cannot read a redirect
        _adapter(lambda _r: redirect, ledger, q).generate(_request(), api_key="dummy")
    snap = _snap(ledger)
    assert snap["releases"] == 1 and snap["settlements"] == 0
    assert snap["spent_usd"] == Decimal(0) and snap["open_reservations"] == 0


@pytest.mark.parametrize(
    "path",
    ["/abs/x.jpg", r"\abs\x.jpg", r"\Users\x\p.jpg", "C:x.jpg", r"C:\x.jpg", "../x", r"a\..\..\x"],
)
def test_unsafe_relative_paths_are_detected(path: str) -> None:
    assert sc.unsafe_relative_path(path)


@pytest.mark.parametrize("path", ["a.jpg", "sub/a.png", r"sub\a.png", "a..b.png"])
def test_safe_relative_paths_pass(path: str) -> None:
    assert not sc.unsafe_relative_path(path)


def test_resolve_within_refuses_escapes(tmp_path: Path) -> None:
    assert sc.resolve_within(tmp_path, "a/b.png") == (tmp_path / "a" / "b.png").resolve()
    with pytest.raises(ValueError, match="outside"):
        sc.resolve_within(tmp_path, "../x.png", what="image")


class _TableStub:
    """A pricing table with chosen rows, raising `KeyError` like `JsonPricingTable`."""

    version = "stub"

    def __init__(self, rows: dict[str, dict[str, Decimal]]) -> None:
        self._rows = rows

    def unit_price(self, *, model_id: str, unit: str) -> Decimal:
        return self._rows[model_id][unit]


def test_a_tiered_model_never_falls_back_to_per_piece() -> None:
    table: Any = _TableStub(
        {"tiered": {"per_image_1k": Decimal("0.04"), "per_piece": Decimal("0.01")}}
    )
    assert sc.quote(table, model_id="tiered", size="1K", references=1).unit_usd == Decimal("0.04")
    with pytest.raises(sc.MissingPriceError, match="per_image_2k"):
        sc.quote(table, model_id="tiered", size="2K", references=1)


def test_a_model_without_tiers_is_priced_per_piece() -> None:
    table: Any = _TableStub({"flat": {"per_piece": Decimal("0.01")}})
    assert sc.quote(table, model_id="flat", size="2K", references=1).unit_usd == Decimal("0.01")


@pytest.mark.parametrize(
    ("size", "tier"), [(" 1536x1536", "1k"), (" 2K", "2k"), ("2048X2048 ", "2k")]
)
def test_size_tier_normalizes_levels_and_wxh_alike(size: str, tier: str) -> None:
    assert sc.size_tier(size) == tier


def test_missing_price_message_is_plain() -> None:
    with pytest.raises(sc.MissingPriceError) as excinfo:
        sc.quote(V6, model_id="no-such-model", size="1K", references=1)
    message = str(excinfo.value)
    # KeyError would print the message wrapped in quotes: "\"pricing table ...\""
    assert message == "pricing table 'v6' has no entry for model 'no-such-model'"
    assert not isinstance(excinfo.value, KeyError)

"""EF-20 phase 1 (m-25026599): the vision placement of a video's text and logo, offline.

Every model call goes to a fake client factory: nothing here reaches Anthropic."""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image

from qualify_api import claude_tools
from qualify_api.creative import placement_ai as pa

TENANT = UUID("7e7e0000-0000-4000-8000-000000000020")
REVISION = "claude-haiku-5-5-test"


def _jpeg(
    width: int = 720, height: int = 1280, color: tuple[int, int, int] = (200, 80, 40)
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="JPEG")
    return buffer.getvalue()


def _frames(n: int = 3) -> list[pa.PlacementFrame]:
    return [
        pa.PlacementFrame(jpeg=_jpeg(), width=720, height=1280, at_s=float(i)) for i in range(n)
    ]


def _answer(**overrides: Any) -> dict[str, Any]:
    return {
        "subject": "Una dona de fresa",
        "subject_bands": ["middle", "bottom"],
        "text_place": "top",
        "logo_place": "top",
        "reason": "La dona ocupa el centro y la parte de abajo; el texto va arriba.",
        **overrides,
    }


@dataclass
class FakeClaude:
    """A `client_factory`: records every request, answers with `answer`."""

    answer: Callable[[], Any] = _answer
    stop_reason: str = "tool_use"
    tool_name: str | None = pa.TOOL_NAME
    error: Exception | None = None
    requests: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, api_key: str) -> SimpleNamespace:
        return SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        content = []
        if self.tool_name:
            content.append(
                SimpleNamespace(type="tool_use", name=self.tool_name, input=self.answer())
            )
        return SimpleNamespace(
            model=REVISION,
            stop_reason=self.stop_reason,
            content=content,
            usage=SimpleNamespace(
                input_tokens=5_200,
                output_tokens=400,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )


def _placer(fake: FakeClaude, guard: pa.CallGuard | None = None) -> pa.VisionPlacer:
    return pa.VisionPlacer(
        guard=guard or pa.InMemoryCallGuard(fleet_cap=100),
        api_key="test-key",
        client_factory=fake,
    )


def _place(placer: pa.VisionPlacer, frames: list[pa.PlacementFrame] | None = None, **kw: Any):
    return placer.place(
        frames if frames is not None else _frames(),
        tenant_id=TENANT,
        piece_id=kw.pop("piece", uuid4()),
        **kw,
    )


# --- the pinned prompt and bound -------------------------------------------------------


def test_the_prompt_is_pinned_to_its_version() -> None:
    # Changing what the model reads changes this hash: bump PLACEMENT_PROMPT_VERSION too.
    assert pa.PLACEMENT_PROMPT_VERSION == "placement-prompt-1"
    assert pa.prompt_fingerprint() == "32791ca8788229b0"


def test_the_worst_request_is_pinned() -> None:
    messages = pa.build_messages(_frames(pa.MAX_FRAMES))
    worst = pa.worst_request_usd(messages)
    assert worst == Decimal("0.001943")
    assert worst <= pa.MAX_REQUEST_USD


def test_the_model_and_its_price_come_from_the_versioned_table() -> None:
    from qualify_creative.pricing import JsonPricingTable

    assert pa.MODEL_ID == "claude-haiku-5-5"
    assert claude_tools.PRICES[pa.MODEL_ID] == (0.10, 0.50)
    from qualify_api.creative.composition import PRICING_VERSION

    table = JsonPricingTable(PRICING_VERSION)  # the table in force
    assert table.unit_price(model_id=pa.MODEL_ID, unit="per_mtok_in") == Decimal("0.10")
    assert table.unit_price(model_id=pa.MODEL_ID, unit="per_mtok_out") == Decimal("0.50")


def test_the_places_are_the_text_catalog() -> None:
    from qualify_creative.schemas import VIDEO_TEXT_PLACES

    tool = pa.placement_tool()
    props = tool["input_schema"]["properties"]
    assert props["text_place"]["enum"] == list(VIDEO_TEXT_PLACES)
    assert props["logo_place"]["enum"] == list(VIDEO_TEXT_PLACES)
    assert tool["strict"] is True
    assert pa.FALLBACK_TEXT_PLACE in VIDEO_TEXT_PLACES
    assert pa.FALLBACK_LOGO_PLACE in VIDEO_TEXT_PLACES


# --- a good answer ---------------------------------------------------------------------


def test_a_good_answer_places_the_layers_with_provenance() -> None:
    fake = FakeClaude()
    decision = _place(_placer(fake))
    assert decision.source == "model"
    assert decision.text_place == "top"
    # both layers in the top band: middle and bottom are the subject's, so they share it
    assert decision.logo_place == "top"
    assert decision.subject_bands == ("middle", "bottom")
    assert decision.reason.startswith("La dona")
    assert decision.cost_usd == Decimal("0.000720")  # 5,200 x 0.10 + 400 x 0.50 per M
    prov = decision.provenance
    assert prov["model_id"] == "claude-haiku-5-5"
    assert prov["model_revision"] == REVISION
    assert prov["effort"] == "low"
    assert prov["prompt_version"] == pa.PLACEMENT_PROMPT_VERSION
    assert [f["at_s"] for f in prov["frames"]] == [0.0, 1.0, 2.0]
    assert all(len(f["sha256"]) == 16 for f in prov["frames"])
    assert prov["pricing_table_version"] == claude_tools.PRICING_TABLE_VERSION
    # one request: the frames as images, Haiku at low effort, tool choice auto (it thinks)
    (request,) = fake.requests
    assert request["model"] == "claude-haiku-5-5"
    assert request["output_config"] == {"effort": "low"}
    assert request["tool_choice"] == {"type": "auto"}
    assert request["max_tokens"] == pa.MAX_OUTPUT_TOKENS
    images = [b for b in request["messages"][0]["content"] if b["type"] == "image"]
    assert len(images) == 3


def test_the_call_is_booked_to_the_business(monkeypatch: pytest.MonkeyPatch) -> None:
    booked: list[Any] = []
    monkeypatch.setattr(claude_tools, "_consumption_sink", booked.append)
    _place(_placer(FakeClaude()))
    (record,) = booked
    assert record.attribution.tenant_id == TENANT
    assert record.attribution.feature == pa.FEATURE
    assert record.attribution.prompt_version == pa.PLACEMENT_PROMPT_VERSION


@pytest.mark.parametrize(
    ("text", "logo", "bands", "want_text", "want_logo"),
    [
        ("bottom", "top", ["middle"], "bottom", "top"),  # the model's answer stands
        ("bottom", "top", ["bottom"], "top", "middle"),  # text on the subject: moved
        ("middle", "middle", ["top"], "middle", "bottom"),  # logo off the text's band
        ("top", "bottom", ["top", "middle", "bottom"], "top", "bottom"),  # all covered
        ("top", "top", ["middle", "bottom"], "top", "top"),  # nowhere else: shares
    ],
)
def test_resolve_places_checks_the_model_against_itself(
    text: str, logo: str, bands: list[str], want_text: str, want_logo: str
) -> None:
    got_text, got_logo, _moves = pa.resolve_places(text, logo, bands)
    assert (got_text, got_logo) == (want_text, want_logo)


def test_a_moved_band_is_recorded() -> None:
    fake = FakeClaude(answer=lambda: _answer(subject_bands=["bottom"], text_place="bottom"))
    decision = _place(_placer(fake))
    assert decision.text_place == "top"
    assert decision.logo_place == "middle"
    assert ("text", "bottom", "top") in decision.adjustments
    assert decision.provenance["model_places"] == {"text": "bottom", "logo": "top"}


def test_one_frame_is_enough() -> None:
    fake = FakeClaude()
    decision = _place(_placer(fake), _frames(1))
    assert decision.source == "model"


# --- every failure keeps today's places ------------------------------------------------


def _assert_fallback(decision: pa.PlacementDecision, code: str) -> None:
    assert decision.source == "fallback"
    assert decision.fallback_reason == code
    assert decision.text_place == "bottom"
    assert decision.logo_place == "top"


@pytest.mark.parametrize(
    "frames",
    [
        [],
        _frames(4),
        [pa.PlacementFrame(jpeg=_jpeg(1080, 1920), width=1080, height=1920)],
        [pa.PlacementFrame(jpeg=b"not a jpeg", width=720, height=1280)],
    ],
)
def test_frames_that_do_not_fit_are_never_sent(frames: list[pa.PlacementFrame]) -> None:
    fake = FakeClaude()
    _assert_fallback(_place(_placer(fake), frames), pa.FALLBACK_BAD_FRAMES)
    assert fake.requests == []


def test_no_key_falls_back_without_a_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(claude_tools.API_KEY_ENV, raising=False)
    fake = FakeClaude()
    guard = pa.InMemoryCallGuard(fleet_cap=10)
    placer = pa.VisionPlacer(guard=guard, client_factory=fake)
    _assert_fallback(_place(placer), pa.FALLBACK_NO_KEY)
    assert fake.requests == []


def test_the_piece_cap_is_counted_before_the_call() -> None:
    fake = FakeClaude()
    placer = _placer(fake, pa.InMemoryCallGuard(per_piece=2, fleet_cap=100))
    piece = uuid4()
    assert _place(placer, piece=piece).source == "model"
    assert _place(placer, piece=piece).source == "model"
    third = _place(placer, piece=piece)
    _assert_fallback(third, pa.FALLBACK_GUARD)
    assert "piece_cap" in third.provenance["detail"]
    assert len(fake.requests) == 2


def test_the_fleet_cap_holds_for_a_day() -> None:
    now = [datetime(2026, 11, 23, 12, tzinfo=UTC)]
    guard = pa.InMemoryCallGuard(per_piece=5, fleet_cap=2, clock=lambda: now[0])
    fake = FakeClaude()
    placer = _placer(fake, guard)
    assert _place(placer).source == "model"
    assert _place(placer).source == "model"
    refused = _place(placer)
    _assert_fallback(refused, pa.FALLBACK_GUARD)
    assert "fleet_cap" in refused.provenance["detail"]
    now[0] += timedelta(hours=24, seconds=1)
    assert _place(placer).source == "model"
    assert len(fake.requests) == 3


def test_a_broken_guard_lets_no_call_through() -> None:
    class Broken:
        def charge(self, piece_id: UUID) -> None:
            raise OSError("database down")

    fake = FakeClaude()
    _assert_fallback(_place(_placer(fake, Broken())), pa.FALLBACK_GUARD)
    assert fake.requests == []


def test_the_fleet_cap_reads_its_env() -> None:
    assert pa.fleet_daily({}) == pa.DEFAULT_FLEET_DAILY
    assert pa.fleet_daily({pa.FLEET_DAILY_ENV: "40"}) == 40
    assert pa.fleet_daily({pa.FLEET_DAILY_ENV: "x"}) == pa.DEFAULT_FLEET_DAILY


def test_the_switch_is_off_by_default() -> None:
    assert pa.placement_enabled({}) is False
    assert pa.placement_enabled({pa.PLACEMENT_SWITCH: "on"}) is True


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_a_refusal_or_a_cut_answer_falls_back_with_its_cost(stop: str) -> None:
    decision = _place(_placer(FakeClaude(stop_reason=stop)))
    _assert_fallback(decision, pa.FALLBACK_MODEL_ERROR)
    assert decision.cost_usd == Decimal("0.000720")  # billed anyway: recorded


def test_a_network_error_falls_back() -> None:
    fake = FakeClaude(error=ConnectionError("reset"))
    decision = _place(_placer(fake))
    _assert_fallback(decision, pa.FALLBACK_REQUEST_ERROR)
    assert decision.cost_usd == Decimal(0)


def test_no_tool_call_falls_back() -> None:
    _assert_fallback(_place(_placer(FakeClaude(tool_name=None))), pa.FALLBACK_NO_TOOL)


@pytest.mark.parametrize(
    "answer",
    [
        {"text_place": "left"},
        {"logo_place": None},
        {"subject_bands": ["arriba"]},
        {"subject_bands": "middle"},
        {"reason": "  "},
    ],
)
def test_a_malformed_answer_falls_back(answer: dict[str, Any]) -> None:
    fake = FakeClaude(answer=lambda: _answer(**answer))
    _assert_fallback(_place(_placer(fake)), pa.FALLBACK_BAD_ANSWER)


def test_a_budget_that_cannot_pay_sends_nothing() -> None:
    fake = FakeClaude()
    decision = _place(_placer(fake), budget=claude_tools.DollarMeter(Decimal("0.0001")))
    _assert_fallback(decision, pa.FALLBACK_BUDGET)
    assert fake.requests == []


def test_a_budget_reserves_the_worst_and_settles_the_bill() -> None:
    meter = claude_tools.DollarMeter(Decimal("2"))
    decision = _place(_placer(FakeClaude()), budget=meter)
    assert decision.source == "model"
    assert meter.spent_usd == Decimal("0.000720000")
    assert meter.reserved_usd == 0
    assert meter.overruns == 0


# --- frames ---------------------------------------------------------------------------


def test_frame_from_image_fits_the_box() -> None:
    frame = pa.frame_from_image(Image.new("RGB", (1080, 1920), (10, 20, 30)), at_s=2.5)
    assert (frame.width, frame.height) == (720, 1280)
    assert frame.at_s == 2.5
    assert pa.frame_problems([frame]) == []
    small = pa.frame_from_image(Image.new("RGBA", (300, 400)))
    assert (small.width, small.height) == (300, 400)  # never upscaled


def test_sample_placement_frames_reads_a_prepared_video(tmp_path: Any) -> None:
    av = pytest.importorskip("av")
    path = tmp_path / "prepared.mp4"
    with av.open(str(path), "w") as container:
        stream = container.add_stream("mpeg4", rate=10)
        stream.width, stream.height, stream.pix_fmt = 360, 640, "yuv420p"
        for i in range(30):
            image = Image.new("RGB", (360, 640), (i * 8, 0, 0))
            for packet in stream.encode(av.VideoFrame.from_image(image)):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    frames = pa.sample_placement_frames(path, 3.0)
    assert len(frames) == 3
    assert [round(f.at_s or 0, 1) for f in frames] == [0.6, 1.5, 2.4]
    assert pa.frame_problems(frames) == []

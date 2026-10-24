"""Seedance 2.5 with video input in the media producer (m-24820142, pricing v7): a clip
with a reference video is priced at the with-video rate, its draft records that (and the
video's length) for the final, the final is priced by its draft, and the usage row keeps
the billed tokens. Measured live 2026-10-23 (docs/modelos-generativos/seedance-2-5.md)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.adapters import SeedanceVideoAdapter
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationRequest, GenerationResult, Usage
from qualify_creative.router import CreativeRouter

from qualify_api.creative import media as media_module
from qualify_api.creative.media import MediaProducer, MediaUsage
from qualify_api.creative.service import ContentService

from .test_creative_media_byteplus import BUDGET, COPY, TENANT_ID, FakeSeedream, KeysByProvider
from .test_creative_media_byteplus import _kit as kit
from .test_creative_seedance_draft import (
    DRAFT_MODEL,
    DraftSeedance,
    RecordingFitter,
    _clip,
    _finalize,
    _record,
    _store,
)

REF = f"uploads/{TENANT_ID}/ref.mp4"
#: what the live drafts billed (cgt-20261024063856-4djtl) and a 1080p final
DRAFT_TOKENS, FINAL_TOKENS = 115_690, 243_000


class VideoInputSeedance(DraftSeedance):
    """The draft fake, answering `video_input` / `reference_video_seconds` the way the
    real adapter does — from its own validated spec."""

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        result = super().generate(request, api_key=api_key)
        spec = SeedanceVideoAdapter(model=DRAFT_MODEL).spec(request.params)
        final = "draft_task_id" in request.params
        return GenerationResult(
            payload={
                **result.payload,
                "video_input": spec.video_input,
                "reference_video_seconds": spec.reference_video_seconds,
            },
            model_id=result.model_id,
            provider=result.provider,
            usage=Usage(
                pieces=1,
                media_seconds=Decimal(5),
                output_tokens=FINAL_TOKENS if final else DRAFT_TOKENS,
            ),
            model_revision=result.model_revision,
            media_url=result.media_url,
            media_expires_at_seconds=result.media_expires_at_seconds,
        )


def _producer(seedance: DraftSeedance) -> MediaProducer:
    from .test_creative_clip import RecordingLinks

    pricing = JsonPricingTable("v7")
    store = _store()
    store.files[REF] = b"mp4-reference"
    router = CreativeRouter(
        {"seedance": seedance, "seedream": FakeSeedream()}, pricing, KeysByProvider()
    )
    producer = MediaProducer(
        store=store,
        router=router,
        credentials=KeysByProvider(),
        pricing=pricing,
        download=lambda url: b"hevc-bytes",
        generated_ad_images=True,
        fitter=RecordingFitter(),
        seedance_model=DRAFT_MODEL,
        seedance_reference_model=DRAFT_MODEL,
        seedance_resolution="720p",
    )
    producer._reference_links = RecordingLinks()
    return producer


def _measured(monkeypatch: pytest.MonkeyPatch, seconds: float | None) -> None:
    monkeypatch.setattr(media_module, "_media_seconds", lambda data: seconds)


def test_a_clip_with_a_reference_video_is_priced_with_video_and_its_draft_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _measured(monkeypatch, 7.33)
    seedance, draft_id = VideoInputSeedance(), uuid4()
    outcome = _producer(seedance).produce(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        brief=_clip(clip_video_keys=(REF,)),
        kit=kit(),
        copy=COPY,
        budget=BUDGET,
    )

    assert outcome.failure is None, outcome.detail
    (request,) = seedance.requests
    # the input video's length rides along for the estimate
    assert request.params["reference_video_seconds"] == 7.33
    (video,) = outcome.media
    block = video.params["draft"]
    assert block["video_input"] is True and block["reference_video_seconds"] == 7.33
    # 115,690 tokens at 6.40/M — not 10.70/M (1.237883)
    assert Decimal(block["cost_usd"]) == Decimal("0.740416")
    (usage,) = outcome.usage
    assert usage.cost_usd == Decimal("0.740416")
    assert usage.unit == "second" and usage.quantity == 5
    assert usage.output_tokens == DRAFT_TOKENS


def test_the_final_takes_the_drafts_video_input(monkeypatch: pytest.MonkeyPatch) -> None:
    _measured(monkeypatch, 7.33)
    seedance, draft_id = VideoInputSeedance(), uuid4()
    producer = _producer(seedance)
    brief = _clip(clip_video_keys=(REF,))
    (draft,) = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=brief, kit=kit(), copy=COPY, budget=BUDGET
    ).media

    outcome = _finalize(producer, brief, _record(draft), draft_id)

    assert outcome.failure is None, outcome.detail
    final = seedance.requests[-1].params
    assert final["video_input"] is True and final["reference_video_seconds"] == 7.33
    # and the real adapter takes that final as is, sending neither
    body = SeedanceVideoAdapter(model=DRAFT_MODEL).spec(final).body()
    assert "video_input" not in body and "reference_video_seconds" not in body
    # 243,000 tokens at 7.00/M (1080p with video), not 11.7/M (2.843100)
    assert outcome.spent_usd == Decimal("1.701000")
    assert outcome.media is not None
    assert Decimal(outcome.media.params["draft"]["final_cost_usd"]) == Decimal("1.701000")


def test_a_clip_without_video_keeps_the_plain_rate_and_so_does_its_final() -> None:
    seedance, draft_id = VideoInputSeedance(), uuid4()
    producer = _producer(seedance)
    brief = _clip()
    (draft,) = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=brief, kit=kit(), copy=COPY, budget=BUDGET
    ).media
    assert draft.params["draft"]["video_input"] is False
    assert "reference_video_seconds" not in seedance.requests[0].params
    assert Decimal(draft.params["draft"]["cost_usd"]) == Decimal("1.237883")

    outcome = _finalize(producer, brief, _record(draft), draft_id)

    assert seedance.requests[-1].params["video_input"] is False
    assert outcome.spent_usd == Decimal("2.843100")


def test_an_unreadable_reference_video_leaves_its_length_to_the_adapters_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _measured(monkeypatch, None)
    seedance = VideoInputSeedance()
    _producer(seedance).produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_clip(clip_video_keys=(REF,)),
        kit=kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert seedance.requests[0].params["reference_video_seconds"] is None


def test_the_usage_row_keeps_the_billed_tokens() -> None:
    service: Any = SimpleNamespace(_pricing=SimpleNamespace(version="v7"))
    (row,) = ContentService._media_usage(
        service,
        [
            MediaUsage(
                provider="seedance",
                model_id=DRAFT_MODEL,
                unit="second",
                quantity=5,
                cost_usd=Decimal("0.740416"),
                output_tokens=DRAFT_TOKENS,
            )
        ],
    )
    assert row.output_tokens == DRAFT_TOKENS and row.pieces == 5
    assert row.pricing_table_version == "v7"

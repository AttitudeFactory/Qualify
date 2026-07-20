from datetime import date
from pathlib import Path

from qualify_models.cascade import CascadeResult
from qualify_models.eval.cost import estimate_cost
from qualify_models.eval.harness import evaluate
from qualify_models.eval.schema import GoldenItem, GoldenSet
from qualify_models.schemas import FilterResult, SentimentResult, TranscriptionResult, VisionResult

FIXTURES = Path(__file__).parent / "fixtures"
FRAME = FIXTURES / "sample_frame.jpg"
AUDIO = FIXTURES / "sample_audio.wav"


def _item(post_id: str, **overrides: object) -> GoldenItem:
    data = {
        "post_id": post_id,
        "platform": "tiktok",
        "image_path": FRAME,
        "audio_path": AUDIO,
        "caption": "caption",
        "filter_relevant": True,
        "reference_transcript": "hola que tal",
        "sentiment_label": "POS",
        "labeler": "datasci",
        "labeled_at": date(2026, 7, 19),
    }
    data.update(overrides)
    return GoldenItem(**data)


def _canned(post_id: str, *, passed: bool, transcript: str, sentiment: str) -> CascadeResult:
    return CascadeResult(
        filter=FilterResult(
            source_id=post_id,
            detector_version="siglip2-base-patch16-224-v1",
            pipeline_version="0.1.0",
            labels=["brand logo"],
            scores=[0.9],
            passed=passed,
            threshold=0.22,
        ),
        vision=VisionResult(
            source_id=post_id,
            detector_version="vision-v1",
            pipeline_version="0.1.0",
            description="a promo frame",
            model_id="Qwen/Qwen3-VL-4B-Instruct",
        )
        if passed
        else None,
        transcription=TranscriptionResult(
            source_id=post_id,
            detector_version="transcription-v1",
            pipeline_version="0.1.0",
            text=transcript,
            language=None,
            model_id="openai/whisper-large-v3-turbo",
        ),
        sentiment=SentimentResult(
            source_id=post_id,
            detector_version="robertuito-sentiment-v1",
            pipeline_version="0.1.0",
            label=sentiment,
            score=0.8,
        ),
    )


def test_evaluate_with_fake_runner_offline() -> None:
    golden_set = GoldenSet(
        items=[
            _item("a", filter_relevant=True, reference_transcript="hola que tal"),
            _item(
                "b",
                filter_relevant=False,
                reference_transcript="adios amigo",
                sentiment_label="NEG",
            ),
        ]
    )
    canned = {
        "a": _canned("a", passed=True, transcript="hola que tal", sentiment="POS"),
        "b": _canned("b", passed=True, transcript="adios amigos", sentiment="NEU"),
    }

    report = evaluate(
        golden_set,
        runner=lambda item: canned[item.post_id],
        revision_resolver=lambda _model_id: None,
        cost_estimate=estimate_cost(),
    )

    assert report.n_items == 2
    assert report.pipeline_version == "0.1.0"
    assert report.harness_version == "0.1.0"

    # filter: pred [T,T] vs truth [T,F] -> TP=1, FP=1, FN=0
    assert report.metrics.filter is not None
    assert report.metrics.filter.precision == 0.5
    assert report.metrics.filter.recall == 1.0

    # sentiment: [POS, NEU] vs [POS, NEG] -> 1/2
    assert report.metrics.sentiment is not None
    assert report.metrics.sentiment.accuracy == 0.5

    # WER: 1 edit over 5 reference words -> 0.2
    assert report.metrics.transcription is not None
    assert abs(report.metrics.transcription.wer - 0.2) < 1e-9

    stages = {p.stage: p for p in report.provenance}
    assert set(stages) == {"filter", "vision", "transcription", "sentiment"}
    assert stages["filter"].model_id == "google/siglip2-base-patch16-224"
    assert stages["transcription"].model_id == "openai/whisper-large-v3-turbo"
    assert stages["vision"].model_id == "Qwen/Qwen3-VL-4B-Instruct"
    # offline resolver -> revisions unresolved, never fabricated
    assert all(p.revision is None for p in report.provenance)

    # cost estimate present with total unresolved (VLM/ASR rates undocumented)
    assert report.cost_estimate is not None
    assert report.cost_estimate.total_usd_per_video is None
    assert report.cost_estimate.caveats


def test_report_carries_manifest_provenance() -> None:
    golden_set = GoldenSet(
        manifest_path=Path("eval_data/golden_set_v1.jsonl"),
        manifest_version="1",
        manifest_sha256="deadbeef",
        items=[_item("a")],
    )
    canned = {"a": _canned("a", passed=True, transcript="hola que tal", sentiment="POS")}

    report = evaluate(
        golden_set,
        runner=lambda item: canned[item.post_id],
        revision_resolver=lambda _model_id: None,
    )

    assert report.manifest_id == "golden_set_v1"
    assert report.manifest_version == "1"
    assert report.manifest_sha256 == "deadbeef"


def test_evaluate_skips_vision_provenance_when_filter_rejects() -> None:
    golden_set = GoldenSet(items=[_item("a", filter_relevant=False)])
    canned = {"a": _canned("a", passed=False, transcript="hola que tal", sentiment="POS")}

    report = evaluate(
        golden_set,
        runner=lambda item: canned[item.post_id],
        revision_resolver=lambda _model_id: None,
    )

    stages = {p.stage for p in report.provenance}
    assert "vision" not in stages
    assert {"filter", "transcription", "sentiment"} <= stages

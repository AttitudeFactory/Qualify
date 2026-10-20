"""The ad-image scene experiment's cases, task and evaluators, offline (no image model)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from qualify_creative.enums import AdImageMode, ContentFormat
from qualify_creative.providers import GenerationRequest, GenerationResult, Usage
from qualify_creative.schemas import BrandKit

from qualify_api.evals.ad_scenes import (
    CONFIGS,
    build_brief,
    generate,
    load_cases,
    run_summary,
    scene_scores,
)

EVALS = Path(__file__).resolve().parents[1] / "evals"
CASES = EVALS / "scenes_ai" / "cases.json"
BRANDS = EVALS / "copy_ai" / "cases.json"


@pytest.fixture(scope="module")
def items() -> list[dict[str, Any]]:
    return load_cases(CASES, BRANDS)


def test_every_scene_is_an_ad_brief_production_accepts(items: list[dict[str, Any]]) -> None:
    assert len(items) == 10 and len({i["id"] for i in items}) == 10
    formats = set()
    for item in items:
        case = item["input"]
        brief = build_brief(case, BrandKit.model_validate(case["kit"]))
        assert brief.media.ad_mode is AdImageMode.SCENE  # no photo in the dataset yet
        assert len(case["hook"]) <= 50 and len(case["cta"]) <= 32  # the printed limits
        formats.add(brief.format)
    assert formats == set(ContentFormat)  # every format the ad image is offered in


def _png(size: tuple[int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 120, 40)).save(out, format="PNG")
    return out.getvalue()


class FakeSeedream:
    name = "seedream"

    def __init__(self, fail: bool = False) -> None:
        self.requests: list[GenerationRequest] = []
        self.fail = fail

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("HTTP 503")
        width, height = (int(v) for v in str(request.params["size"]).split("x"))
        return GenerationResult(
            payload={"images": [_png((width, height))]},
            model_id="seedream-5-0-lite-260128",
            provider="seedream",
            usage=Usage(pieces=1),
        )


def test_the_task_makes_the_finished_ad_image_at_the_formats_size(
    items: list[dict[str, Any]],
) -> None:
    case = next(i["input"] for i in items if i["id"] == "hel-cono-doble")  # story 9:16
    seedream = FakeSeedream()
    attached: list[tuple[int, str]] = []

    output = generate(
        case,
        CONFIGS["seedream-5.0-lite"],
        api_key="k",
        provider=seedream,
        review_queue=None,
        attach=lambda data, kind: attached.append((len(data), kind)) or f"<{kind}>",
    )

    (request,) = seedream.requests
    assert request.params["size"] == "1440x2560" and request.params["images"] == []
    assert "no reference images" in str(request.params["prompt"])
    assert (output["ancho"], output["alto"]) == (1080, 1920)
    assert output["modo"] == "scene" and output["costo_usd"] == 0.035
    assert output["imagen"] == "<image/jpeg>" and len(attached) == 2  # final + raw scene
    scores = {s.name: s.value for s in scene_scores(case, output, None, {})}
    assert scores == {
        "errores": 0.0,
        "tamano_ok": True,
        "costo_usd": 0.035,
        "segundos": scores["segundos"],
    }


def test_a_vendor_failure_is_scored_not_raised(items: list[dict[str, Any]]) -> None:
    case = items[0]["input"]
    output = generate(case, "m", api_key="k", provider=FakeSeedream(fail=True), review_queue=None)
    assert output == {"error": "RuntimeError: HTTP 503"}
    assert {s.name: s.value for s in scene_scores(case, output, None, {})} == {"errores": 1.0}


def test_a_case_with_photos_sends_them_as_references(
    items: list[dict[str, Any]], tmp_path: Path
) -> None:
    photo = tmp_path / "vaso.jpg"
    Image.new("RGB", (50, 50), (1, 2, 3)).save(photo, format="JPEG")
    case = {**items[0]["input"], "product_photo": str(photo)}
    seedream = FakeSeedream()
    output = generate(
        case, "m", api_key="k", provider=seedream, review_queue=None, attach=lambda *_: None
    )
    (request,) = seedream.requests
    assert output["modo"] == "product" and len(request.params["images"]) == 1
    assert str(request.params["images"][0]).startswith("data:image/jpeg;base64,")


def test_the_run_summary_totals_cost_and_sizes() -> None:
    from qualify_shared.observability import ItemOutcome

    outcomes = [
        ItemOutcome(
            None, None, {"errores": 0.0, "tamano_ok": True, "costo_usd": 0.035, "segundos": 20.0}
        ),
        ItemOutcome(None, None, {"errores": 1.0}),
    ]
    summary = {s.name: s.value for s in run_summary(outcomes)}
    assert summary == {
        "errores_total": 1.0,
        "tamano_ok_tasa": 1.0,
        "costo_total_usd": 0.035,
        "segundos_p50": 20.0,
    }

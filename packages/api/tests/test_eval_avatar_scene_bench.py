"""m-25112921: the avatar-in-its-scene bench (path A, Seedance 2.5) — offline.

Covers the matrix, prompts, cost from the versioned table, the spend ceiling, the
authorization flag, the off-hours window and the judgment sheet. The paid phases run
against fake adapters: nothing here reaches a vendor.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationResult, Usage

from qualify_api.evals import avatar_scene_bench as bench
from qualify_api.evals import byteplus_eval_guard

RUNNER = Path(__file__).resolve().parents[1] / "evals" / "avatar_escena" / "run_experiment.py"
PRICING = JsonPricingTable(bench.PRICING_VERSION)


def _runner() -> Any:
    spec = importlib.util.spec_from_file_location("avatar_escena_runner", RUNNER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _jpeg(path: Path) -> Path:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 120, 40)).save(buffer, "JPEG")
    path.write_bytes(buffer.getvalue())
    return path


def _material(tmp_path: Path, *, local: bool = False) -> Path:
    _jpeg(tmp_path / "producto.jpg")
    if local:
        _jpeg(tmp_path / "local.jpg")
    file = tmp_path / "material.json"
    file.write_text(
        json.dumps(
            {
                "producto": {"nombre": "super smash", "photo": "producto.jpg"},
                "local": {"photo": "local.jpg" if local else None},
            }
        ),
        encoding="utf-8",
    )
    return file


# -- matrix and prompts ----------------------------------------------------------------


def test_matrix_without_the_place_photo_is_characters_by_scenes() -> None:
    cases = bench.case_matrix(local_photo=False)
    assert [c.label for c in cases] == [
        "realista/dibujado/e1",
        "realista/dibujado/e2",
        "realista/dibujado/e3",
        "animado/dibujado/e1",
        "animado/dibujado/e2",
        "animado/dibujado/e3",
    ]


def test_matrix_with_the_place_photo_adds_scene_one_per_character() -> None:
    labels = [c.label for c in bench.case_matrix(local_photo=True)]
    assert len(labels) == 8
    assert "realista/local/e1" in labels and "animado/local/e1" in labels
    assert not any(label.startswith(("realista/local/e2", "animado/local/e3")) for label in labels)


def test_matrix_filters_characters_and_refuses_unknown_ones() -> None:
    assert {
        c.character.id for c in bench.case_matrix(local_photo=False, characters=["animado"])
    } == {"animado"}
    with pytest.raises(ValueError):
        bench.case_matrix(local_photo=False, characters=["presentador"])


def test_scenes_last_five_to_ten_seconds_and_speak_short_spanish() -> None:
    for sc in bench.SCENES:
        assert 5 <= sc.seconds <= 10
        assert '"' not in sc.line
        assert len(sc.line.split()) <= sc.seconds * 2.5


def test_scene_prompt_names_the_three_images_and_the_brand() -> None:
    case = bench.case_matrix(local_photo=False)[0]
    prompt = bench.scene_prompt(case)
    for needle in ("Image 1", "Image 2", "Image 3", "super smash", "Baloo 2", "#305046"):
        assert needle in prompt
    assert case.scene.line not in prompt  # the line travels as the adapter's dialogue


def test_scene_params_are_an_omni_reference_draft_with_sound() -> None:
    case = bench.case_matrix(local_photo=False)[1]
    params = bench.scene_params(
        case, character_url="data:a", product_url="data:b", background_url="data:c"
    )
    assert params["reference_images"] == ["data:a", "data:b", "data:c"]
    assert params["omni_reference_task_type"] == "reference"
    assert params["draft"] is True and params["resolution"] == "480p"
    assert params["generate_audio"] is True
    assert params["dialogue"] == case.scene.line
    assert params["duration_seconds"] == 8
    hd = bench.scene_params(
        case,
        character_url="data:a",
        product_url="data:b",
        background_url="data:c",
        resolution_mode="720p",
    )
    assert "draft" not in hd and hd["resolution"] == "720p"
    with pytest.raises(ValueError):
        bench.scene_params(
            case, character_url="a", product_url="b", background_url="c", resolution_mode="4k"
        )


def test_the_real_adapter_accepts_and_prices_every_scene_like_the_bench() -> None:
    runner = _runner()
    lines = runner._validate_scene_requests(
        bench.case_matrix(local_photo=True), PRICING, "borrador"
    )
    assert len(lines) == 8


# -- cost ------------------------------------------------------------------------------


def test_cost_comes_from_the_versioned_table() -> None:
    assert bench.image_quote(PRICING) == Decimal("0.045")  # Seedream 5.0 pro, 1K tier
    e1 = bench.case_matrix(local_photo=False)[0]
    # 480x854 x 24 fps x 5 s / 1024 = 48,038 tokens at USD 10.70/M
    assert bench.scene_quote(e1, PRICING, "borrador") == Decimal("0.514007")


def test_plan_totals_split_drawings_and_scenes() -> None:
    items = bench.drawing_items(PRICING) + bench.scene_items(
        bench.case_matrix(local_photo=False), PRICING, "borrador"
    )
    totals = bench.plan_totals(items)
    assert totals["dibujar"]["items"] == 6
    assert Decimal(totals["dibujar"]["quote_usd"]) == Decimal("0.270")
    assert totals["escenas"]["items"] == 6
    assert Decimal(totals["total_quote_usd"]) == Decimal("4.998822")
    assert Decimal(totals["total_reserved_usd"]) < bench.PROPOSED_MAX_USD


def test_drawing_options_are_one_to_three() -> None:
    assert len(bench.drawing_items(PRICING, options=3)) == 9
    with pytest.raises(ValueError):
        bench.drawing_items(PRICING, options=4)


# -- guards ----------------------------------------------------------------------------


def test_max_usd_is_positive_and_capped() -> None:
    assert bench.validate_max_usd("8") == Decimal("8")
    for bad in ("0", "-1", "10.01", "NaN"):
        with pytest.raises(bench.SpendRefused):
            bench.validate_max_usd(bad)


def test_the_whole_phase_must_fit_with_its_margin() -> None:
    items = bench.scene_items(bench.case_matrix(local_photo=False), PRICING, "borrador")
    assert bench.fits_ceiling(items, max_usd=Decimal("8"), spent_before=Decimal("0")) is None
    assert bench.fits_ceiling(items, max_usd=Decimal("8"), spent_before=Decimal("3")) is not None
    assert bench.fits_ceiling(items, max_usd=Decimal("5"), spent_before=Decimal("0")) is not None


def test_exactly_one_of_dry_run_and_authorization() -> None:
    assert bench.mode_refusal(paid=False, dry_run=True) is None
    assert bench.mode_refusal(paid=True, dry_run=False) is None
    assert bench.mode_refusal(paid=False, dry_run=False) is not None
    assert bench.mode_refusal(paid=True, dry_run=True) is not None


def test_refusal_kinds() -> None:
    assert bench.refusal_kind(None) is None
    face = "HTTP 400 InputImageSensitiveContentDetected.PrivacyInformation: real person"
    assert bench.refusal_kind(face) == "rostro"
    assert bench.refusal_kind("HTTP 400 OutputVideoSensitiveContentDetected: x") == "moderacion"
    assert bench.refusal_kind("ReadTimeout") == "otro"


# -- the judgment sheet ----------------------------------------------------------------


def test_sheet_fills_the_automatic_columns_and_summarizes() -> None:
    results = [
        {
            "character": "realista",
            "background": "dibujado",
            "scene": "e1",
            "error": "HTTP 400 InputImageSensitiveContentDetected.PrivacyInformation",
            "cost_usd": "0",
            "seconds_taken": 2.0,
        },
        {
            "character": "animado",
            "background": "dibujado",
            "scene": "e2",
            "video": "videos/animado__dibujado__e2.mp4",
            "cost_usd": "0.83",
            "seconds_taken": 95.1,
        },
    ]
    rows = bench.sheet_rows(results)
    assert rows[0]["acepto_referencia"] == "no"
    assert rows[1]["acepto_referencia"] == "si"
    assert rows[1]["linea"] == bench.scene("e2").line
    rows[1].update(personaje_igual="si", producto_reconocible="si", labios_sincronizados="dudoso")
    summary = bench.summarize_sheet(bench.sheet_csv(rows))
    assert summary["realista"] == {**summary["realista"], "tareas": 1, "aceptadas": 0}
    assert summary["animado"]["juzgadas"] == 1
    assert summary["animado"]["personaje_igual"] == 1
    assert summary["animado"]["labios_sincronizados"] == 0  # dudoso counts as no


# -- the runner ------------------------------------------------------------------------


def test_material_must_live_outside_the_repo(tmp_path: Path) -> None:
    runner = _runner()
    material = runner.load_material(str(_material(tmp_path)))
    assert material["local"] is None and not material["sample"]
    inside = tmp_path / "dentro.json"
    inside.write_text(
        json.dumps({"producto": {"photo": str(runner.SAMPLE_PRODUCT)}}), encoding="utf-8"
    )
    with pytest.raises(runner.MaterialError):
        runner.load_material(str(inside))
    assert runner.load_material(None)["sample"] is True


def test_dry_run_sends_nothing_and_writes_the_quote(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = _runner()
    out = tmp_path / "out"
    code = runner.main(
        ["plan", "--material", str(_material(tmp_path, local=True)), "--out", str(out)]
    )
    assert code == 0
    text = capsys.readouterr().out
    assert "bloqueadas durante la prueba en seco: 0" in text
    quote = json.loads(next(out.glob("cotizacion-plan-*.json")).read_text(encoding="utf-8"))
    assert len(quote["cases"]) == 8
    assert quote["network_blocked"] == 0


def test_paid_steps_need_the_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runner = _runner()
    assert runner.main(["dibujar", "--out", str(tmp_path)]) == 2
    assert runner.main(["escenas", "--dry-run", "--i-have-spend-authorization"]) == 2
    assert runner.main(["plan", "--i-have-spend-authorization"]) == 2


def test_paid_scenes_refuse_outside_the_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(byteplus_eval_guard, "in_off_hours", lambda now: False)
    run = tmp_path / "run"
    run.mkdir()
    with pytest.raises(SystemExit, match="23:00"):
        runner.main(
            [
                "escenas",
                "--i-have-spend-authorization",
                "--material",
                str(_material(tmp_path)),
                "--run",
                str(run),
            ]
        )


class FakeSeedream:
    def __init__(self, **_: Any) -> None:
        self.calls = 0

    def generate(self, request: Any, *, api_key: str) -> GenerationResult:
        buffer = io.BytesIO()
        Image.new("RGB", (32, 56), (10, 80, 70)).save(buffer, "JPEG")
        return GenerationResult(
            payload={"images": [buffer.getvalue()]},
            model_id=bench.SEEDREAM_MODEL,
            provider="seedream",
            usage=Usage(pieces=1),
        )


class FakeSeedance:
    """Refuses the realistic face, makes the cartoon; tokens as the formula."""

    sent: list[dict[str, Any]] = []

    def __init__(self, **_: Any) -> None:
        pass

    def generate(self, request: Any, *, api_key: str) -> GenerationResult:
        from qualify_creative.adapters.byteplus_ark import ArkAPIError, estimate_video_tokens

        params = dict(request.params)
        FakeSeedance.sent.append(params)
        if params["reference_images"][0] == "data:realista":
            raise ArkAPIError(400, "InputImageSensitiveContentDetected.PrivacyInformation", "x")
        tokens = estimate_video_tokens(
            bench.SEEDANCE_MODEL, "480p", "9:16", int(params["duration_seconds"])
        )
        return GenerationResult(
            payload={"task_id": f"cgt-{len(FakeSeedance.sent)}"},
            model_id=bench.SEEDANCE_MODEL,
            provider="seedance",
            usage=Usage(output_tokens=tokens),
        )


def test_paid_run_with_fakes_records_refusals_cost_and_the_sheet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_creative.adapters import byteplus_ark

    runner = _runner()
    monkeypatch.setenv("QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY", "fake-key")
    monkeypatch.delenv("QUALIFY_BYTEPLUS_ARK_PROD_KEY_FINGERPRINT", raising=False)
    monkeypatch.setattr(byteplus_ark, "SeedreamImageAdapter", FakeSeedream)
    monkeypatch.setattr(byteplus_ark, "SeedanceVideoAdapter", FakeSeedance)
    monkeypatch.setattr(byteplus_eval_guard, "in_off_hours", lambda now: True)
    material = str(_material(tmp_path))
    out = tmp_path / "out"
    assert (
        runner.main(
            ["dibujar", "--i-have-spend-authorization", "--max-usd", "8", "--out", str(out)]
        )
        == 0
    )
    run = next(p for p in out.iterdir() if p.is_dir())
    drawings = json.loads((run / "dibujos.json").read_text(encoding="utf-8"))
    assert len(drawings) == 6 and all(d["cost_usd"] == "0.045" for d in drawings.values())

    # the fake refuses the realistic drawing as a face (as 2.x does with real faces)
    original = runner._raw_data_url
    monkeypatch.setattr(
        runner,
        "_raw_data_url",
        lambda path: "data:realista" if "realista" in path.name else original(path),
    )
    FakeSeedance.sent = []
    assert (
        runner.main(
            [
                "escenas",
                "--i-have-spend-authorization",
                "--max-usd",
                "8",
                "--material",
                material,
                "--run",
                str(run),
            ]
        )
        == 0
    )
    results = json.loads((run / "resultados.json").read_text(encoding="utf-8"))
    assert len(results) == 6
    refused = [r for r in results.values() if r.get("refusal") == "rostro"]
    assert len(refused) == 3 and all(r["cost_usd"] == "0" for r in refused)
    made = [r for r in results.values() if r.get("billed_tokens")]
    assert {r["model"] for r in made} == {bench.SEEDANCE_MODEL}
    spend = json.loads((run / "gasto.json").read_text(encoding="utf-8"))
    expected = Decimal("0.270") + sum((Decimal(r["cost_usd"]) for r in made), Decimal(0))
    assert Decimal(spend["spent_usd"]) == expected
    assert Decimal(spend["spent_usd"]) < Decimal("8")

    assert runner.main(["planilla", "--run", str(run)]) == 0
    sheet = (run / "juicio-deivid.csv").read_text(encoding="utf-8")
    assert "PrivacyInformation" in sheet and (run / "juicio-herwin.csv").is_file()


def test_the_ceiling_stops_a_paid_run_before_crossing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_creative.adapters import byteplus_ark

    runner = _runner()
    monkeypatch.setenv("QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY", "fake-key")
    monkeypatch.setattr(byteplus_ark, "SeedreamImageAdapter", FakeSeedream)
    out = tmp_path / "out"
    # the drawings (US$0.297 with margin) do not fit under US$0.2: refused whole
    with pytest.raises(SystemExit, match="No se manda nada"):
        runner.main(
            ["dibujar", "--i-have-spend-authorization", "--max-usd", "0.2", "--out", str(out)]
        )


class FakeSeedanceWithVideo:
    """Makes every scene and hands back a 24 h link, like ModelArk."""

    sent: list[str] = []

    def __init__(self, **_: Any) -> None:
        pass

    def generate(self, request: Any, *, api_key: str) -> GenerationResult:
        from qualify_creative.adapters.byteplus_ark import estimate_video_tokens

        seconds = int(request.params["duration_seconds"])
        FakeSeedanceWithVideo.sent.append(str(seconds))
        return GenerationResult(
            payload={"task_id": f"cgt-{len(FakeSeedanceWithVideo.sent)}"},
            model_id=bench.SEEDANCE_MODEL,
            provider="seedance",
            usage=Usage(
                output_tokens=estimate_video_tokens(bench.SEEDANCE_MODEL, "480p", "9:16", seconds)
            ),
            media_url=f"https://example.invalid/{seconds}.mp4",
        )


def test_a_phase_cut_after_a_charge_keeps_it_and_never_pays_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_creative.adapters import byteplus_ark

    runner = _runner()
    monkeypatch.setenv("QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY", "fake-key")
    monkeypatch.delenv("QUALIFY_BYTEPLUS_ARK_PROD_KEY_FINGERPRINT", raising=False)
    monkeypatch.setattr(byteplus_ark, "SeedreamImageAdapter", FakeSeedream)
    monkeypatch.setattr(byteplus_ark, "SeedanceVideoAdapter", FakeSeedanceWithVideo)
    monkeypatch.setattr(byteplus_eval_guard, "in_off_hours", lambda now: True)
    material = str(_material(tmp_path))
    out = tmp_path / "out"
    common = ["--i-have-spend-authorization", "--max-usd", "8", "--personaje", "animado"]
    assert runner.main(["dibujar", *common, "--out", str(out)]) == 0
    run = next(p for p in out.iterdir() if p.is_dir())
    after_drawings = Decimal(json.loads((run / "gasto.json").read_text("utf-8"))["spent_usd"])
    assert after_drawings == Decimal("0.180")  # 2 options of the character + 2 of the place

    # the process dies while downloading the SECOND scene, after it was paid
    downloads: list[str] = []

    def dying_download(url: str, target: Path) -> str | None:
        downloads.append(url)
        if len(downloads) == 2:
            raise KeyboardInterrupt
        target.write_bytes(b"mp4")
        return None

    monkeypatch.setattr(runner, "_download_video", dying_download)
    FakeSeedanceWithVideo.sent = []
    scenes = ["escenas", *common, "--material", material, "--run", str(run)]
    with pytest.raises(KeyboardInterrupt):
        runner.main(scenes)
    assert FakeSeedanceWithVideo.sent == ["5", "8"]
    spend = json.loads((run / "gasto.json").read_text("utf-8"))
    paid = [c for c in spend["calls"] if c["phase"] == "escenas"]
    assert list(dict.fromkeys(c["label"] for c in paid)) == [
        "animado/dibujado/e1",
        "animado/dibujado/e2",
    ]
    results = json.loads((run / "resultados.json").read_text("utf-8"))
    assert Decimal(spend["spent_usd"]) == after_drawings + sum(
        (Decimal(r["cost_usd"]) for r in results.values()), Decimal(0)
    )
    cut = results["animado/dibujado/e2"]
    assert cut["task_id"] == "cgt-2" and "video" not in cut

    # resumed: e2 is fetched again, NOT sent again; only e3 is new
    monkeypatch.setattr(
        runner, "_download_video", lambda url, target: target.write_bytes(b"mp4") and None
    )
    assert runner.main(scenes) == 0
    assert FakeSeedanceWithVideo.sent == ["5", "8", "10"]
    results = json.loads((run / "resultados.json").read_text("utf-8"))
    assert all(r.get("video") for r in results.values())
    spend = json.loads((run / "gasto.json").read_text("utf-8"))
    assert list(dict.fromkeys(c["label"] for c in spend["calls"] if c["phase"] == "escenas")) == [
        "animado/dibujado/e1",
        "animado/dibujado/e2",
        "animado/dibujado/e3",
    ]
    assert Decimal(spend["spent_usd"]) == after_drawings + sum(
        (Decimal(r["cost_usd"]) for r in results.values()), Decimal(0)
    )


class FakeSeedanceDiesWhilePolling:
    """Accepts the task (tells the observer its id), then the process dies while polling
    — the first time only. Asked again with `resume_task_id`, it answers that task."""

    created: list[str] = []
    resumed: list[str] = []
    die_on: str | None = "8"
    announce = True

    def __init__(self, **_: Any) -> None:
        pass

    def generate(self, request: Any, *, api_key: str) -> GenerationResult:
        from qualify_creative.adapters.byteplus_ark import estimate_video_tokens

        cls = FakeSeedanceDiesWhilePolling
        seconds = str(request.params["duration_seconds"])
        resume = request.params.get("resume_task_id")
        if resume:
            cls.resumed.append(str(resume))
            task_id = str(resume)
        else:
            task_id = f"cgt-{seconds}s"
            cls.created.append(task_id)
            if seconds == cls.die_on:
                if cls.announce and request.observer is not None:
                    request.observer.created(task_id)
                raise KeyboardInterrupt
        return GenerationResult(
            payload={"task_id": task_id},
            model_id=bench.SEEDANCE_MODEL,
            provider="seedance",
            usage=Usage(
                output_tokens=estimate_video_tokens(
                    bench.SEEDANCE_MODEL, "480p", "9:16", int(seconds)
                )
            ),
            media_url=f"https://example.invalid/{task_id}.mp4",
        )


def _drawn_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: Any) -> Path:
    from qualify_creative.adapters import byteplus_ark

    monkeypatch.setenv("QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY", "fake-key")
    monkeypatch.delenv("QUALIFY_BYTEPLUS_ARK_PROD_KEY_FINGERPRINT", raising=False)
    monkeypatch.setattr(byteplus_ark, "SeedreamImageAdapter", FakeSeedream)
    monkeypatch.setattr(byteplus_ark, "SeedanceVideoAdapter", FakeSeedanceDiesWhilePolling)
    monkeypatch.setattr(byteplus_eval_guard, "in_off_hours", lambda now: True)
    monkeypatch.setattr(
        runner, "_download_video", lambda url, target: target.write_bytes(b"mp4") and None
    )
    out = tmp_path / "out"
    args = ["dibujar", "--i-have-spend-authorization", "--max-usd", "8"]
    assert runner.main([*args, "--personaje", "animado", "--out", str(out)]) == 0
    return next(p for p in out.iterdir() if p.is_dir())


def _spent(run: Path) -> Decimal:
    return Decimal(json.loads((run / "gasto.json").read_text("utf-8"))["spent_usd"])


def test_killed_while_polling_is_recovered_by_task_id_and_counted_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    run = _drawn_run(tmp_path, monkeypatch, runner)
    fake = FakeSeedanceDiesWhilePolling
    fake.created, fake.resumed, fake.die_on, fake.announce = [], [], "8", True
    scenes = [
        "escenas",
        "--i-have-spend-authorization",
        "--max-usd",
        "8",
        "--personaje",
        "animado",
        "--material",
        str(_material(tmp_path)),
        "--run",
        str(run),
    ]
    with pytest.raises(KeyboardInterrupt):
        runner.main(scenes)
    results = json.loads((run / "resultados.json").read_text("utf-8"))
    cut = results["animado/dibujado/e2"]
    assert cut["status"] == "enviada" and cut["task_id"] == "cgt-8s"
    # its reservation is already counted although generate never returned
    reserved_e2 = Decimal(cut["cost_usd"])
    assert reserved_e2 > 0
    assert (
        _spent(run)
        == Decimal("0.180") + Decimal(results["animado/dibujado/e1"]["cost_usd"]) + reserved_e2
    )

    assert runner.main(scenes) == 0
    assert fake.created == ["cgt-5s", "cgt-8s", "cgt-10s"]  # e2 created ONCE
    assert fake.resumed == ["cgt-8s"]  # and waited for by id
    results = json.loads((run / "resultados.json").read_text("utf-8"))
    assert all(r["status"] == "pagada" and r.get("video") for r in results.values())
    assert Decimal(results["animado/dibujado/e2"]["cost_usd"]) < reserved_e2  # settled
    assert _spent(run) == Decimal("0.180") + sum(
        (Decimal(r["cost_usd"]) for r in results.values()), Decimal(0)
    )


def test_killed_before_the_task_id_is_never_resent_and_stays_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    run = _drawn_run(tmp_path, monkeypatch, runner)
    fake = FakeSeedanceDiesWhilePolling
    fake.created, fake.resumed, fake.die_on, fake.announce = [], [], "8", False
    scenes = [
        "escenas",
        "--i-have-spend-authorization",
        "--max-usd",
        "8",
        "--personaje",
        "animado",
        "--material",
        str(_material(tmp_path)),
        "--run",
        str(run),
    ]
    with pytest.raises(KeyboardInterrupt):
        runner.main(scenes)
    assert runner.main(scenes) == 0
    assert fake.created == ["cgt-5s", "cgt-8s", "cgt-10s"] and fake.resumed == []
    results = json.loads((run / "resultados.json").read_text("utf-8"))
    cut = results["animado/dibujado/e2"]
    assert cut["status"] == "enviada" and not cut.get("task_id")
    assert _spent(run) == Decimal("0.180") + sum(
        (Decimal(r["cost_usd"]) for r in results.values()), Decimal(0)
    )


def test_a_resumed_phase_quotes_only_what_is_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    run = _drawn_run(tmp_path, monkeypatch, runner)
    fake = FakeSeedanceDiesWhilePolling
    fake.created, fake.resumed, fake.die_on, fake.announce = [], [], "10", False
    base = [
        "escenas",
        "--i-have-spend-authorization",
        "--personaje",
        "animado",
        "--material",
        str(_material(tmp_path)),
        "--run",
        str(run),
    ]
    with pytest.raises(KeyboardInterrupt):
        runner.main([*base, "--max-usd", "8"])
    spent = _spent(run)  # drawings + e1 + e2 + e3's reservation (e3 not resent)
    # the whole phase (US$2.6 with margin) no longer fits under spent + 0.5 ...
    whole = bench.scene_items(
        bench.case_matrix(local_photo=False, characters=["animado"]),
        JsonPricingTable(bench.PRICING_VERSION),
        "borrador",
    )
    assert sum((i.reserved_usd for i in whole), Decimal(0)) > Decimal("0.5")
    # ... but nothing is left to pay, so the resumed run is not refused
    assert runner.main([*base, "--max-usd", str(spent + Decimal("0.5"))]) == 0
    assert fake.created == ["cgt-5s", "cgt-8s", "cgt-10s"]


class _Answer:
    def __init__(self, status: int, kind: str, body: bytes) -> None:
        self.status_code = status
        self.headers = {"content-type": kind}
        self.content = body

    def raise_for_status(self) -> None:
        import httpx

        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.invalid/v.mp4")
            raise httpx.HTTPStatusError(
                "error", request=request, response=httpx.Response(self.status_code)
            )


@pytest.mark.parametrize(
    ("answer", "saved"),
    [
        (_Answer(200, "video/mp4", b"mp4"), True),
        (_Answer(200, "application/octet-stream", b"mp4"), True),
        (_Answer(403, "application/xml", b"<Error/>"), False),
        (_Answer(200, "text/html; charset=utf-8", b"<html>"), False),
        (_Answer(200, "video/mp4", b""), False),
    ],
)
def test_download_never_saves_an_error_as_a_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: _Answer, saved: bool
) -> None:
    import httpx

    runner = _runner()
    monkeypatch.setattr(httpx, "get", lambda *a, **k: answer)
    target = tmp_path / "v.mp4"
    failure = runner._download_video("https://example.invalid/v.mp4", target)
    assert (failure is None) is saved
    assert target.exists() is saved


def test_the_dry_run_quote_never_lands_in_the_repo(tmp_path: Path) -> None:
    runner = _runner()
    with pytest.raises(SystemExit, match="fuera del repositorio"):
        runner.main(["plan", "--out", str(runner.REPO / "packages" / "api" / "evals")])

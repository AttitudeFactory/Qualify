"""Preparing the Seedream 5.0 pro run of the plantillas_ai eval (m-24849234 PR 4), offline:
latency per call, the versioned v2 prompts, the Lite vs Pro comparison, the readiness
check and the sample matrix. No vendor and no network: fake transports and clocks."""

from __future__ import annotations

import base64
import copy
import importlib.util
import io
import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from PIL import Image
from qualify_creative.pricing import JsonPricingTable

from qualify_api.evals import image_metrics as im
from qualify_api.evals import spend_control as sc
from qualify_api.evals import template_transfer as tt

EVAL_DIR = Path(__file__).resolve().parents[1] / "evals" / "plantillas_ai"
LITE_PILOT = EVAL_DIR / "results" / "20261023-192557-350988.json"
V6 = JsonPricingTable("v6")
PRO = sc.SEEDREAM_PRO
LITE = "seedream-5-0-lite-260128"


def _load(name: str, file: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, EVAL_DIR / file)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runner() -> ModuleType:
    return _load("plantillas_runner_prep", "run_experiment.py")


class _Clock:
    """A fake wall clock: every reading advances by `step` seconds."""

    def __init__(self, step: float = 0.5) -> None:
        self.now, self.step = 0.0, step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


@pytest.fixture
def no_http(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def refuse(self: Any, request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise AssertionError(f"unexpected HTTP request to {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    yield seen


def _ok() -> httpx.Response:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(out, format="JPEG")
    return httpx.Response(
        200,
        json={
            "model": PRO,
            "data": [{"b64_json": base64.b64encode(out.getvalue()).decode(), "size": "8x8"}],
            "usage": {"generated_images": 1, "output_tokens": 1},
        },
    )


def _run(
    runner: ModuleType,
    tmp_path: Path,
    blocks: list[str],
    handler: Any,
    flags: list[str] | None = None,
    reader: Any = None,
) -> dict[str, Any]:
    args = runner.build_parser().parse_args(
        ["--results-dir", str(tmp_path / "res"), *(flags or [])]
    )
    choice = runner.prompt_choice(args, tt)
    cases = tt.load_cases(EVAL_DIR / "cases.json")
    planned = tt.plan_calls(
        tt.build_matrix(cases, blocks=blocks, limit=1), V6, model_ids=[PRO], size="1K"
    )
    assert choice is not None
    return runner.run_paid(
        planned,
        tt,
        ledger=sc.SpendLedger(Decimal("1")),
        api_key="dummy",
        args=args,
        inner_transport=httpx.MockTransport(handler),
        reader=reader,
    )


# --- 1. latency ------------------------------------------------------------------


def test_latency_is_recorded_per_item_and_averaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    monkeypatch.setattr(runner, "_clock", _Clock(0.5))
    report = _run(runner, tmp_path, ["texture", "flat"], lambda _r: _ok())
    texture = report["items"][f"texture:fix-luma+textura-rayas-cobre@{PRO}"]
    flat = report["items"][f"flat:fix-luma+textura-rayas-cobre@{tt.FLAT_PROVIDER}"]
    assert texture["latencia_s"] == 0.5 and flat["latencia_s"] == 0.5
    assert report["totales"]["latencia_media_s"] == {"texture": 0.5, "flat": 0.5, "total": 0.5}
    saved = json.loads(next((tmp_path / "res").glob("*.json")).read_text(encoding="utf-8"))
    assert saved["totales"]["latencia_media_s"]["total"] == 0.5


def test_latency_is_recorded_when_the_call_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    monkeypatch.setattr(runner, "_clock", _Clock(1.25))

    def broken(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer")

    report = _run(runner, tmp_path, ["texture"], broken)
    (record,) = report["items"].values()
    assert record["estado"] == "error" and "ReadTimeout" in record["error"]
    assert record["latencia_s"] == 1.25
    assert report["totales"]["latencia_media_s"] == {"texture": 1.25, "total": 1.25}


def test_each_reading_has_its_latency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    monkeypatch.setattr(runner, "_clock", _Clock(0.25))
    reader = im.FakeReader(answers=["LUMO", "LUMA"])
    report = _run(runner, tmp_path, ["texture"], lambda _r: _ok(), reader=reader)
    (record,) = report["items"].values()
    legibility = record["legibilidad"]
    assert legibility["reintento"] is True and legibility["latencias_s"] == [0.25, 0.25]
    assert legibility["latencia_s"] == 0.5


def test_mean_latencies_skip_items_without_a_time() -> None:
    runner = _runner()
    items = {
        "a": {"block": "color", "latencia_s": 1.0},
        "b": {"block": "color", "latencia_s": 2.0},
        "c": {"block": "texture", "estado": "omitido"},
        "d": {"block": "flat", "latencia_s": 0.1},
    }
    assert runner.mean_latencies(items) == {"color": 1.5, "flat": 0.1, "total": 1.033}
    assert runner.mean_latencies({}) == {}


def test_the_dry_run_measures_nothing(
    no_http: list[httpx.Request], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    runner = _runner()
    assert runner.main(["--dry-run", "--limit", "2"]) == 0
    out = capsys.readouterr().out
    assert "latencia" not in out and "estimado USD 0.1920" in out
    assert "Solicitudes de red: 0" in out and no_http == []


# --- 2. prompts v2 ----------------------------------------------------------------

V1_TEXTURE_LUMA = (
    'Image 1 is a logo with the text "LUMA". Image 2 is a material texture. Apply the '
    "material of Image 2 to the letters and shapes of the logo in Image 1. Keep the exact "
    'text "LUMA", the letter shapes, the layout and the background of Image 1 unchanged.'
)
V1_COLOR = (
    "Image 1 is a product photo. Image 2 is a color reference. Recolor the object in Image 1 "
    "with the color palette of Image 2. Keep the object's shape, material, printed text, "
    "lighting, shadows and the background of Image 1 unchanged."
)


def _items() -> dict[str, tt.MatrixItem]:
    items = tt.build_matrix(tt.load_cases(EVAL_DIR / "cases.json"), limit=1)
    return {item.block: item for item in items}


def test_v1_stays_the_default_and_byte_identical() -> None:
    items = _items()
    assert tt.DEFAULT_PROMPTS == tt.PromptChoice("v1", "plano")
    assert tt.prompt_for(items["texture"]) == V1_TEXTURE_LUMA
    assert tt.prompt_for(items["color"]) == V1_COLOR
    params = tt.request_params(items["texture"], model_id=PRO, size="1K", images=["a", "b"])
    assert params == {"prompt": V1_TEXTURE_LUMA, "model": PRO, "size": "1K", "images": ["a", "b"]}
    assert tt.PROMPTS_V2["texture_plano"] == tt.PROMPTS["texture"]


def test_v2_prompts_name_the_colors_and_pick_the_finish() -> None:
    items = _items()
    v2 = tt.PromptChoice("v2")
    color = tt.prompt_for(items["color"], v2, palette_hex=["#3EB489", "#FF7F50"])
    assert "#3EB489, #FF7F50" in color and "Do NOT reproduce the layout" in color
    with pytest.raises(ValueError, match="palette_hex"):
        tt.prompt_for(items["color"], v2)
    assert tt.prompt_for(items["texture"], v2) == V1_TEXTURE_LUMA  # plano == today's
    volume = tt.prompt_for(items["texture"], tt.PromptChoice("v2", "volumen"))
    assert "3D letters made of the material in Image 2" in volume and '"LUMA"' in volume
    for bad in (("v3", "plano"), ("v2", "relieve"), ("v1", "volumen")):
        with pytest.raises(ValueError):
            tt.PromptChoice(*bad)


def test_provenance_records_the_prompt_version_and_the_finish() -> None:
    planned = tt.plan_calls(list(_items().values()), V6, model_ids=[PRO], size="1K")
    by_block = {p.item.block: p for p in planned}
    v1 = tt.provenance(by_block["texture"])
    assert v1["prompt_version"] == "plantillas-ai-v1" and v1["texture_finish"] == "plano"
    v2 = tt.provenance(by_block["texture"], tt.PromptChoice("v2", "volumen"))
    assert v2["prompt_version"] == "plantillas-ai-v2" and v2["texture_finish"] == "volumen"
    assert "texture_finish" not in tt.provenance(by_block["color"], tt.PromptChoice("v2"))
    assert tt.provenance(by_block["flat"])["prompt_version"] == tt.FLAT_VERSION


def test_the_v2_run_sends_the_hex_colors_and_records_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return _ok()

    report = _run(runner, tmp_path, ["color"], handler, ["--prompts", "v2"])
    (record,) = report["items"].values()
    assert record["prompt_version"] == "plantillas-ai-v2"
    assert record["paleta_hex"] == ["#B87333", "#FF7F50", "#3EB489"]
    assert "#B87333, #FF7F50, #3EB489" in sent[0]["prompt"]
    assert report["prompt_version"] == "plantillas-ai-v2" and report["texture_finish"] == "plano"


def test_the_volumen_finish_needs_the_v2_prompts(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        _runner().main(["--dry-run", "--texture-finish", "volumen"])
    assert exc.value.code == 2 and "needs --prompts v2" in capsys.readouterr().err


def test_dominant_hex_reads_the_three_bands() -> None:
    palette = (EVAL_DIR / "fixtures" / "paleta-azul-arena-terracota.png").read_bytes()
    assert sorted(im.dominant_hex(palette)) == ["#204E8C", "#B05232", "#DEC8A0"]


# --- 3. comparison ----------------------------------------------------------------


def _compare() -> ModuleType:
    return _load("plantillas_compare", "compare_runs.py")


def test_compare_works_with_the_lite_report_alone() -> None:
    compare = _compare()
    report = compare.load_report(LITE_PILOT)
    table = compare.compare([report]).splitlines()
    assert table[0] == compare.HEADER and len(table) == 2 + 6 + 2  # totals per model
    disc = next(line for line in table if "fix-objeto-disco" in line)
    assert "| 9.03 | 24.78 |" in disc and f"| {LITE} | hecho |" in disc
    totals = [line for line in table if line.startswith("| **Total**")]
    assert f"| {LITE} | 4/4 hechos | 0.140 |" in totals[0]
    assert "| pillow-flat-texture | 2/2 hechos |" in totals[1]


def test_compare_lines_up_lite_and_a_second_run(tmp_path: Path) -> None:
    compare = _compare()
    lite = compare.load_report(LITE_PILOT)
    pro = copy.deepcopy(lite)
    pro["stamp"], pro["size"] = "20991231-000000-000000", "1K"
    pro["items"] = {
        key.replace("seedream-5-0-lite-260128", PRO): {
            **value,
            "model_id": PRO
            if value.get("provider") != "pillow-flat-texture"
            else value["model_id"],
            "latencia_s": 2.0,
        }
        for key, value in lite["items"].items()
        if "rombo" not in key  # a case only the first run has
    }
    path = tmp_path / "pro.json"
    path.write_text(json.dumps(pro), encoding="utf-8")
    table = compare.compare([lite, compare.load_report(path)])
    assert "20991231-000000-000000 · 1K" in table
    rhombus = [line for line in table.splitlines() if "fix-objeto-rombo" in line]
    assert len(rhombus) == 2 and "sin dato" in rhombus[1]
    assert table.count("**Total**") == 4 and "2.000 (media)" in table


def test_compare_cli_reads_files_only(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    compare = _compare()
    assert compare.main([]) == 2
    assert compare.main([str(tmp_path / "missing.json")]) == 2
    assert compare.main([str(LITE_PILOT)]) == 0
    assert "| **Total** |" in capsys.readouterr().out


# --- 5. readiness -----------------------------------------------------------------


def test_readiness_reports_without_any_call(
    no_http: list[httpx.Request],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "sk-this-value-must-never-print"
    monkeypatch.setenv("QUALIFY_BYTEPLUS_ARK_API_KEY", secret)
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("QUALIFY_ANTHROPIC_API_KEY=another-secret\n", encoding="utf-8")
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)  # deterministic: no photo on disk
    assert runner.main(["--check-readiness", "--env-file", str(env)]) == 0
    out = capsys.readouterr().out
    assert "Matriz cases.json: 110 ítems (68 pagados) · estimado USD 3.264" in out
    assert f"{PRO} a 1K (tramo 1k): imagen USD 0.045 + entradas USD 0.003 = USD 0.048" in out
    assert "--block texture --limit 1 --max-usd 0.05 --i-have-spend-authorization" in out
    assert "QUALIFY_BYTEPLUS_ARK_API_KEY: entorno" in out
    assert "QUALIFY_ANTHROPIC_API_KEY: .env" in out
    assert secret not in out and "another-secret" not in out
    assert "--max-reads 50 (máximo 50)" in out and "USD 0.03048" in out
    assert "objetos (8):" in out and "Fotos propias pendientes: 8." in out
    assert "Solicitudes de red: 0" in out and no_http == []


def test_readiness_says_when_a_key_is_absent(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in ("QUALIFY_BYTEPLUS_ARK_API_KEY", "QUALIFY_ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text('QUALIFY_BYTEPLUS_ARK_API_KEY=""\nQUALIFY_ANTHROPIC_API_KEY=  \n', "utf-8")
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    assert runner.main(["--check-readiness", "--env-file", str(env)]) == 0
    out = capsys.readouterr().out
    assert "QUALIFY_BYTEPLUS_ARK_API_KEY: ausente" in out
    assert "QUALIFY_ANTHROPIC_API_KEY: ausente" in out


# --- 3b / 6. the sample matrix ---------------------------------------------------------


def test_the_sample_matrix_prices_19_calls(tmp_path: Path) -> None:
    sample = tt.load_cases(EVAL_DIR / "cases-muestra.json")
    items = tt.build_matrix(sample)
    paid = [i for i in items if i.paid]
    assert len(paid) == 3 * 3 + 5 * 2 and len(items) - len(paid) == 5 * 2
    pro = tt.plan_calls(items, V6, model_ids=[PRO], size="1K")
    lite = tt.plan_calls(items, V6, model_ids=[LITE], size="2K")
    assert tt.total_usd(pro) == Decimal("0.912") and tt.total_usd(lite) == Decimal("0.665")
    missing = tt.missing_by_role(items, tmp_path, EVAL_DIR.parents[2].parent)
    assert list(missing) == ["objetos"] and len(missing["objetos"]) == 3


# --- final review round ----------------------------------------------------------------


def test_readiness_follows_the_chosen_matrix_and_models(
    no_http: list[httpx.Request],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    flags = ["--check-readiness", "--block", "texture", "--configs", LITE, "--size", "2K"]
    assert runner.main(flags) == 0
    out = capsys.readouterr().out
    assert "42 ítems (42 pagados)" in out and "objetos" not in out
    assert "Todas las imágenes de entrada están en disco." in out
    assert f"{LITE} a 2K (tramo 2k): imagen USD 0.035 + entradas USD 0 = USD 0.035" in out
    assert f"--max-usd 0.05 --configs {LITE} --size 2K --i-have-spend-authorization" in out
    assert PRO not in out.split("Tope de gasto")[0]


def test_readiness_rejects_a_bad_matrix_or_an_unpriced_model(
    no_http: list[httpx.Request], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    runner = _runner()
    assert runner.main(["--check-readiness", "--cases", str(tmp_path / "no-existe.json")]) == 2
    assert "Matriz inválida" in capsys.readouterr().out
    assert runner.main(["--check-readiness", "--configs", "seedream_v4", "--limit", "1"]) == 3
    assert "Sin precio en la tabla v6" in capsys.readouterr().out
    assert runner.main(["--dry-run", "--cases", str(tmp_path / "no-existe.json")]) == 2
    assert no_http == []


def test_env_file_quotes_and_empty_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _runner()
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nQUALIFY_BYTEPLUS_ARK_API_KEY=\"\"\nQUALIFY_ANTHROPIC_API_KEY='k'\nOTHER=1\n",
        encoding="utf-8",
    )
    assert runner._env_pairs(str(env)) == {
        "QUALIFY_BYTEPLUS_ARK_API_KEY": "",
        "QUALIFY_ANTHROPIC_API_KEY": "k",
        "OTHER": "1",
    }
    for name in runner.ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    assert runner._env_names(str(env)) == {
        "QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY": "ausente",
        "QUALIFY_BYTEPLUS_ARK_API_KEY": "ausente",
        "QUALIFY_ANTHROPIC_API_KEY": ".env",
    }
    monkeypatch.delenv("OTHER", raising=False)
    runner._load_env(str(env))
    import os

    assert os.environ["OTHER"] == "1" and os.environ["QUALIFY_ANTHROPIC_API_KEY"] == "k"


def test_a_pre_call_failure_records_its_latency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    monkeypatch.setattr(runner, "_clock", _Clock(0.75))
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(tmp_path / "vacia.png")  # no opaque pixel
    Image.new("RGB", (8, 8), (200, 10, 10)).save(tmp_path / "obj.png")
    raw = json.loads((EVAL_DIR / "cases.json").read_text(encoding="utf-8"))
    raw["blocks"]["color"] = {
        "references": [{"id": "vacia", "path": "vacia.png"}],
        "cases": [{"id": "obj", "path": "obj.png"}],
    }
    cases = tt.parse_cases(raw)
    planned = tt.plan_calls(
        tt.build_matrix(cases, blocks=["color"]), V6, model_ids=[PRO], size="1K"
    )
    seen: list[httpx.Request] = []
    report = runner.run_paid(
        planned,
        tt,
        ledger=sc.SpendLedger(Decimal("1")),
        api_key="dummy",
        args=runner.build_parser().parse_args(
            ["--results-dir", str(tmp_path / "res"), "--prompts", "v2"]
        ),
        inner_transport=httpx.MockTransport(lambda r: seen.append(r) or _ok()),
    )
    (record,) = report["items"].values()
    assert record["estado"] == "error" and "no opaque pixels" in record["error"]
    assert record["latencia_s"] == 0.75 and seen == []  # failed before the call
    assert runner.mean_latencies({"a": {"block": "color", "latencia_s": None}}) == {}


def test_prompt_provenance_is_per_block_with_a_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    v1 = _run(runner, tmp_path / "a", ["texture"], lambda _r: _ok())
    v2 = _run(runner, tmp_path / "b", ["color", "texture"], lambda _r: _ok(), ["--prompts", "v2"])
    key = f"texture:fix-luma+textura-rayas-cobre@{PRO}"
    assert v2["items"][key]["prompt_version"] == "plantillas-ai-v1"  # plano: v1's text
    assert v2["items"][key]["prompt_sha256"] == v1["items"][key]["prompt_sha256"]
    assert v1["items"][key]["prompt_sha256"] == tt.prompt_sha256(V1_TEXTURE_LUMA)
    color = v2["items"][f"color:fix-objeto-disco+paleta-menta-coral-cobre@{PRO}"]
    assert color["prompt_version"] == "plantillas-ai-v2" and len(color["prompt_sha256"]) == 64
    volume = tt.provenance(
        tt.plan_calls([_items()["texture"]], V6, model_ids=[PRO], size="1K")[0],
        tt.PromptChoice("v2", "volumen"),
    )
    assert volume["prompt_version"] == "plantillas-ai-v2"


def test_compare_keeps_each_model_of_a_report_apart(tmp_path: Path) -> None:
    compare = _compare()
    lite = compare.load_report(LITE_PILOT)
    both = copy.deepcopy(lite)
    for key, value in lite["items"].items():
        if value.get("provider") != "pillow-flat-texture":
            both["items"][key.replace(LITE, PRO)] = {
                **value,
                "model_id": PRO,
                "gastado_usd": "0.048",
            }
    table = compare.compare([both]).splitlines()
    disc = [line for line in table if "fix-objeto-disco" in line]
    assert len(disc) == 2 and f"| {LITE} |" in disc[0] and f"| {PRO} |" in disc[1]
    totals = [line for line in table if line.startswith("| **Total**")]
    assert len(totals) == 3 and any(f"| {PRO} | 4/4 hechos | 0.192 |" in t for t in totals)

"""The Seedream 5.0 pro color/texture eval (m-24849234), offline: pricing quotes, the
spend ledger, the matrix, reference encoding and the dry run. No request leaves."""

from __future__ import annotations

import base64
import importlib.util
import io
import json
import re
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from PIL import Image
from qualify_creative.pricing import JsonPricingTable

from qualify_api.evals import spend_control as sc
from qualify_api.evals import template_transfer as tt

EVAL_DIR = Path(__file__).resolve().parents[1] / "evals" / "plantillas_ai"


REPO_ROOT = Path(__file__).resolve().parents[3]


V6 = JsonPricingTable("v6")


PRO = sc.SEEDREAM_PRO


LITE = "seedream-5-0-lite-260128"


def _runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "plantillas_runner", EVAL_DIR / "run_experiment.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def no_http(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Any real HTTP transport use is recorded and fails the call."""
    seen: list[httpx.Request] = []

    def refuse(self: Any, request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise AssertionError(f"unexpected HTTP request to {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    monkeypatch.setenv("QUALIFY_BYTEPLUS_ARK_API_KEY", "dummy-not-a-key")
    return seen


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


@pytest.fixture(scope="module")
def cases() -> tt.CaseSet:
    return tt.load_cases(EVAL_DIR / "cases.json")


def _raw() -> dict[str, Any]:
    return json.loads((EVAL_DIR / "cases.json").read_text(encoding="utf-8"))


def _bytes(image: Image.Image, fmt: str) -> bytes:
    out = io.BytesIO()
    image.save(out, format=fmt)
    return out.getvalue()


class _CountingInner(httpx.BaseTransport):
    """A shared inner transport double: answers with `handler`, counts `close()`."""

    def __init__(self, handler: Any) -> None:
        self._mock = httpx.MockTransport(handler)
        self.requests = 0
        self.closes = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        return self._mock.handle_request(request)

    def close(self) -> None:
        self.closes += 1


def _texture_flat_cases(tmp_path: Path) -> tt.CaseSet:
    """Two non-fixture logos under `tmp_path`: a truncated PNG first, a valid one next."""
    raw = _raw()
    raw["blocks"]["texture"]["cases"] = [
        {"id": "logo-roto", "path": "roto.png", "expected_text": "ROTO"},
        {"id": "logo-sano", "path": "sano.png", "expected_text": "SANO"},
    ]
    raw["blocks"]["texture"]["references"] = [{"id": "tex", "path": "tex.png"}]
    (tmp_path / "tex.png").write_bytes(_bytes(Image.new("RGB", (8, 8), (200, 120, 40)), "PNG"))
    logo = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    logo.paste((9, 9, 9, 255), (10, 10, 30, 30))
    good = _bytes(logo, "PNG")
    (tmp_path / "roto.png").write_bytes(good[:30])  # truncated
    (tmp_path / "sano.png").write_bytes(good)
    return tt.parse_cases(raw)


def test_matrix_shape(cases: tt.CaseSet) -> None:
    items = tt.build_matrix(cases)
    by_block = {b: [i for i in items if i.block == b] for b in tt.BLOCKS}
    # 10 objects x 3 color references + 2 fixtures with their own reference
    assert len(by_block["color"]) == 10 * 3 + 2
    # 10 logos x 5 textures + 2 fixtures
    assert len(by_block["texture"]) == 10 * 5 + 2
    # the same logo x texture pairs as flat finishes
    assert len(by_block["flat"]) == 10 * 5 + 2
    assert len({i.id for i in items}) == len(items)
    assert all(i.expected_text for i in by_block["texture"] + by_block["flat"])
    assert sum(1 for c in cases.color if c.fixture) == 2
    assert sum(1 for c in cases.texture if c.fixture) == 2


def test_plan_totals_per_block_and_size(cases: tt.CaseSet) -> None:
    items = tt.build_matrix(cases)
    one_k = tt.plan_calls(items, V6, model_ids=[PRO], size="1K")
    two_k = tt.plan_calls(items, V6, model_ids=[PRO], size="2K")
    assert tt.total_usd(one_k) == Decimal("0.048") * 84
    assert tt.total_usd(two_k) == Decimal("0.093") * 84
    assert all(p.cost_usd == 0 for p in one_k if p.item.block == "flat")
    assert tt.total_usd(two_k) <= sc.MAX_USD_CEILING
    two_models = tt.plan_calls(items, V6, model_ids=[PRO, LITE], size="2K")
    assert len(two_models) == 84 * 2 + 52  # flat runs once, not per model


def test_limit_and_block_selection(cases: tt.CaseSet) -> None:
    items = tt.build_matrix(cases, blocks=["texture"], limit=2)
    assert [i.case_id for i in items] == ["fix-luma", "fix-qualify-icono"]
    assert tt.missing_files(items, EVAL_DIR / "imagenes", REPO_ROOT) == []
    with pytest.raises(ValueError):
        tt.build_matrix(cases, blocks=["sepia"])
    with pytest.raises(ValueError):
        tt.build_matrix(cases, limit=0)


def test_missing_files_are_listed_once(tmp_path: Path, cases: tt.CaseSet) -> None:
    items = tt.build_matrix(cases, blocks=["color"])
    missing = tt.missing_files(items, tmp_path, REPO_ROOT)
    assert len(missing) == 10 + 3  # objects + the shared references, each once
    assert all(str(p).startswith(str(tmp_path)) for p in missing)


@pytest.mark.parametrize(
    "breaker",
    [
        lambda r: r["blocks"]["color"]["cases"].append(dict(r["blocks"]["color"]["cases"][2])),
        lambda r: r["blocks"]["texture"]["cases"][3].pop("expected_text"),
        lambda r: r["blocks"]["color"]["cases"][2].update(path="/abs/x.jpg"),
        lambda r: r["blocks"]["color"]["cases"][2].update(path="../x.jpg"),
        lambda r: r["blocks"]["color"]["cases"][2].update(path=r"\abs\x.jpg"),
        lambda r: r["blocks"]["color"]["cases"][2].update(path=r"\Users\x\p.jpg"),
        lambda r: r["blocks"]["color"]["cases"][0].pop("references"),
        lambda r: r["blocks"]["flat"].update(source_block="color"),
        lambda r: r["blocks"]["flat"].update(fill="red"),
        lambda r: r["blocks"].pop("flat"),
        lambda r: r["blocks"].update(flat=[]),
        lambda r: r["blocks"].update(color="x"),
        lambda r: r["blocks"]["color"]["cases"][2].update(id="../../fuera"),
        lambda r: r["blocks"]["color"]["cases"][2].update(id="a/b"),
        lambda r: r["blocks"]["color"]["cases"][2].update(id="a\\b"),
        lambda r: r["blocks"]["color"]["cases"][2].update(id=".."),
        lambda r: r["blocks"]["texture"]["references"][0].update(id="c:x"),
        lambda r: r["blocks"]["texture"]["references"].append(
            {"id": "textura-neon-rosa", "path": "x"}
        ),
    ],
)
def test_invalid_cases_are_rejected(breaker: Any) -> None:
    raw = _raw()
    breaker(raw)
    with pytest.raises(tt.CasesError):
        tt.parse_cases(raw)


def test_dry_run_end_to_end_sends_nothing(
    no_http: list[httpx.Request],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)  # empty: every placeholder is missing
    assert runner.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Solicitudes de red: 0" in out
    assert "estimado USD 4.0320" in out  # 84 paid items x 0.048 at 1K
    assert "Faltan" in out  # placeholder files are reported, not fatal
    assert no_http == []


def test_dry_run_limit_resolves_only_fixtures(
    no_http: list[httpx.Request], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _runner().main(["--dry-run", "--limit", "2", "--size", "2K"]) == 0
    out = capsys.readouterr().out
    assert "Todas las imágenes de entrada están en disco." in out
    assert "estimado USD 0.3720" in out  # 4 x 0.093
    assert no_http == []


def test_ceiling_above_ten_is_rejected() -> None:
    with pytest.raises(SystemExit) as exc:
        _runner().main(["--dry-run", "--max-usd", "10.5"])
    assert exc.value.code == 2


def test_paid_run_needs_explicit_authorization(no_http: list[httpx.Request]) -> None:
    assert _runner().main(["--limit", "1"]) == 2
    assert no_http == []


def test_missing_price_stops_the_paid_run_before_any_call(
    no_http: list[httpx.Request], capsys: pytest.CaptureFixture[str]
) -> None:
    code = _runner().main(
        ["--limit", "1", "--configs", "seedream_v4", "--i-have-spend-authorization"]
    )
    assert code == 3 and "Sin precio" in capsys.readouterr().out
    assert no_http == []


def test_paid_path_with_a_test_double(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    cases = tt.load_cases(EVAL_DIR / "cases.json")
    items = tt.build_matrix(cases, blocks=["texture", "flat"], limit=1)
    planned = tt.plan_calls(items, V6, model_ids=[PRO], size="1K")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok()

    args = runner.build_parser().parse_args(["--size", "1K", "--results-dir", str(tmp_path)])
    report = runner.run_paid(
        planned,
        tt,
        ledger=sc.SpendLedger(Decimal("1")),
        api_key="dummy",
        args=args,
        inner_transport=httpx.MockTransport(handler),
    )
    assert len(seen) == 1 and report["spent_usd"] == "0.048"
    body = json.loads(seen[0].content)
    assert body["model"] == PRO
    assert body["image"][0].startswith("data:image/png;base64,")  # the logo keeps its alpha
    assert body["image"][1].startswith("data:image/jpeg;base64,")
    assert '"LUMA"' in body["prompt"]
    record = report["items"][f"texture:fix-luma+fix-textura-rayas-cobre@{PRO}"]
    assert record["prompt_version"] == tt.PROMPT_VERSION and record["pricing_version"] == "v6"
    assert record["legibilidad"]["estado"] == "pendiente"  # no reader configured
    assert record["legibilidad"]["metricas_version"] == "metricas-v1"
    flat = report["items"][f"flat:fix-luma+fix-textura-rayas-cobre@{tt.FLAT_PROVIDER}"]
    assert flat["prompt_version"] == tt.FLAT_VERSION
    assert flat["metricas"]["aprobado"] is True and flat["metricas"]["tamano"][0] == 1080
    assert len(list(tmp_path.rglob("*.png"))) == 1 and len(list(tmp_path.rglob("*.jpg"))) == 1


def test_ceiling_stop_records_the_whole_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    cases = tt.load_cases(EVAL_DIR / "cases.json")
    items = tt.build_matrix(cases, blocks=["color", "flat"], limit=2)
    planned = tt.plan_calls(items, V6, model_ids=[PRO], size="1K")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok()

    report = runner.run_paid(
        planned,
        tt,
        ledger=sc.SpendLedger(Decimal("0.05")),  # one paid item fits, the second does not
        api_key="dummy",
        args=runner.build_parser().parse_args(["--results-dir", str(tmp_path)]),
        inner_transport=httpx.MockTransport(handler),
    )
    assert len(seen) == 1 and report["stopped"]
    states = [r["estado"] for r in report["items"].values()]
    # finding 4: the free flat items still run after the ceiling stops the paid ones
    assert states == ["hecho", "rechazado por el tope", "hecho", "hecho"]
    assert len(report["items"]) == len(planned)


def test_paid_run_maps_an_invalid_matrix_to_exit_2(
    no_http: list[httpx.Request], capsys: pytest.CaptureFixture[str]
) -> None:
    code = _runner().main(["--size", "3K", "--i-have-spend-authorization"])
    assert code == 2 and "Matriz inválida" in capsys.readouterr().out
    assert no_http == []


def test_output_names_cannot_escape(tmp_path: Path) -> None:
    runner = _runner()
    assert runner._output(tmp_path, "ok.jpg").parent == tmp_path.resolve()
    with pytest.raises(ValueError):
        runner._output(tmp_path, "../fuera.jpg")


def test_vendor_spend_above_the_reservation_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    cases = tt.load_cases(EVAL_DIR / "cases.json")
    items = tt.build_matrix(cases, blocks=["color"], limit=2)
    planned = tt.plan_calls(items, V6, model_ids=[PRO], size="1K")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok(generated=3)  # 3 x 0.045 + 0.003 = 0.138, reserved 0.048

    report = runner.run_paid(
        planned,
        tt,
        ledger=sc.SpendLedger(Decimal("0.10")),
        api_key="dummy",
        args=runner.build_parser().parse_args(["--results-dir", str(tmp_path)]),
        inner_transport=httpx.MockTransport(handler),
    )
    assert len(seen) == 1  # the second item is refused: the run is already over its ceiling
    first, second = report["items"].values()
    assert first["exceso"] is True and first["estado"] == "hecho"
    assert Decimal(first["estimado_usd"]) == Decimal("0.048") and Decimal(
        first["reservado_usd"]
    ) == Decimal("0.048")
    assert Decimal(first["gastado_usd"]) == Decimal("0.138") and Decimal(
        first["exceso_sobre_reserva_usd"]
    ) == Decimal("0.090")
    assert Decimal(first["exceso_sobre_tope_usd"]) == Decimal("0.038") and Decimal(
        first["retenido_usd"]
    ) == Decimal("0")
    assert second["estado"] == "rechazado por el tope" and Decimal(
        second["gastado_usd"]
    ) == Decimal("0")
    totals = report["totales"]
    assert Decimal(totals["gastado_usd"]) == Decimal("0.138") and Decimal(
        totals["exceso_sobre_tope_usd"]
    ) == Decimal("0.038")
    assert Decimal(totals["retenido_usd"]) == Decimal("0") and totals["alerta"] is True
    assert report["ledger"]["open_reservations"] == 0
    assert "AVISO" in capsys.readouterr().out


def test_skip_fixtures_removes_exactly_the_fixture_items(cases: tt.CaseSet) -> None:
    full = tt.build_matrix(cases)
    kept = tt.build_matrix(cases, skip_fixtures=True)
    assert {i.id for i in full} - {i.id for i in kept} == {i.id for i in full if i.fixture}
    assert not any(i.fixture for i in kept)
    assert not any(img.fixture for i in kept for img in i.images)
    planned = tt.plan_calls(kept, V6, model_ids=[PRO], size="1K")
    by_block = {b: [p for p in planned if p.item.block == b] for b in tt.BLOCKS}
    assert len(by_block["color"]) == 30 and tt.total_usd(by_block["color"]) == Decimal("1.44")
    assert len(by_block["texture"]) == 50
    assert tt.total_usd(by_block["texture"]) == Decimal("2.40")
    assert len(by_block["flat"]) == 50 and tt.total_usd(by_block["flat"]) == 0
    assert tt.total_usd(planned) == Decimal("3.84")
    limited = tt.build_matrix(cases, blocks=["texture"], limit=1, skip_fixtures=True)
    assert {i.case_id for i in limited} == {"logo-brasa-norte"}


def test_dry_run_shows_included_and_excluded(
    no_http: list[httpx.Request], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _runner().main(["--dry-run", "--skip-fixtures"]) == 0
    out = capsys.readouterr().out
    assert "Incluidos 130 ítems, excluidos 6 (6 fixture, 0 reales)" in out
    assert "estimado USD 3.8400" in out and "(80 pagadas)" in out
    rows = [line for line in out.splitlines() if line.startswith(("color ", "texture ", "flat "))]
    fixture_rows = [r for r in rows if " fixture " in r]
    assert len(fixture_rows) == 6 and all(" no " in r for r in fixture_rows)
    assert all(" sí " in r for r in rows if " real " in r)
    assert no_http == []


def test_layer_decomposition_is_not_a_cli_option() -> None:
    with pytest.raises(SystemExit) as exc:
        _runner().main(["--dry-run", "--layer-decomposition"])
    assert exc.value.code == 2


def test_a_broken_flat_logo_is_an_item_error_and_the_json_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    cases = _texture_flat_cases(tmp_path)
    items = tt.build_matrix(cases, blocks=["flat"])
    planned = tt.plan_calls(items, V6, model_ids=[PRO], size="1K")
    inner = _CountingInner(lambda _r: _ok())
    report = runner.run_paid(
        planned,
        tt,
        ledger=sc.SpendLedger(Decimal("1")),
        api_key="dummy",
        args=runner.build_parser().parse_args(["--results-dir", str(tmp_path / "res")]),
        inner_transport=inner,
    )
    states = {k.split("@")[0]: v["estado"] for k, v in report["items"].items()}
    assert states["flat:logo-roto+tex"] == "error"
    assert states["flat:logo-sano+tex"] == "hecho"
    broken = report["items"][f"flat:logo-roto+tex@{tt.FLAT_PROVIDER}"]
    assert "UnidentifiedImageError" in broken["error"]
    (saved_path,) = (tmp_path / "res").glob("*.json")
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert len(saved["items"]) == len(planned)
    assert saved["ledger"]["open_reservations"] == 0
    assert "gastado_usd" in saved["totales"]


def test_the_json_is_written_even_when_the_run_blows_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    cases = tt.load_cases(EVAL_DIR / "cases.json")
    planned = tt.plan_calls(
        tt.build_matrix(cases, blocks=["color"], limit=2), V6, model_ids=[PRO], size="1K"
    )

    def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "_run_item", boom)
    with pytest.raises(KeyboardInterrupt):
        runner.run_paid(
            planned,
            tt,
            ledger=sc.SpendLedger(Decimal("1")),
            api_key="dummy",
            args=runner.build_parser().parse_args(["--results-dir", str(tmp_path / "res")]),
            inner_transport=_CountingInner(lambda _r: _ok()),
        )
    (saved_path,) = (tmp_path / "res").glob("*.json")
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved["error_inesperado"].startswith("KeyboardInterrupt")
    assert saved["totales"]["alerta"] is True
    assert {v["estado"] for v in saved["items"].values()} == {"omitido"}
    for row in saved["items"].values():  # the same keys as every other row
        assert row["exceso"] is False
        assert all(Decimal(row[name]) == 0 for name in runner._MONEY_FIELDS)


def test_all_401_exits_6_and_writes_the_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    monkeypatch.setenv("QUALIFY_BYTEPLUS_ARK_API_KEY", "dummy-not-a-key")
    inner = _CountingInner(lambda _r: httpx.Response(401, json={"error": {"code": "Auth"}}))
    monkeypatch.setattr(httpx, "HTTPTransport", lambda *a, **k: inner)
    code = runner.main(
        [
            "--block",
            "color",
            "--limit",
            "2",
            "--i-have-spend-authorization",
            "--results-dir",
            str(tmp_path / "res"),
            "--env-file",
            str(tmp_path / "no.env"),
        ]
    )
    assert code == 6
    (saved_path,) = (tmp_path / "res").glob("*.json")
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert {v["estado"] for v in saved["items"].values()} == {"error"}
    assert saved["spent_usd"] == "0" and saved["ledger"]["releases"] == 2
    assert inner.requests == 2 and inner.closes == 1


def test_one_shared_inner_transport_is_closed_once_after_all_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    inner = _CountingInner(lambda _r: _ok())
    created: list[_CountingInner] = []

    def factory(*_a: Any, **_k: Any) -> _CountingInner:
        created.append(inner)
        return inner

    monkeypatch.setattr(httpx, "HTTPTransport", factory)
    cases = tt.load_cases(EVAL_DIR / "cases.json")
    planned = tt.plan_calls(
        tt.build_matrix(cases, blocks=["color", "texture"], limit=2),
        V6,
        model_ids=[PRO],
        size="1K",
    )
    report = runner.run_paid(
        planned,
        tt,
        ledger=sc.SpendLedger(Decimal("1")),
        api_key="dummy",
        args=runner.build_parser().parse_args(["--results-dir", str(tmp_path / "res")]),
    )
    assert {v["estado"] for v in report["items"].values()} == {"hecho"}
    assert len(created) == 1 and inner.requests == 4 and inner.closes == 1
    assert runner.exit_code(report) == 0


def test_two_runs_in_the_same_instant_get_distinct_stamps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    monkeypatch.setattr(runner, "_now", lambda: "20261023-120000-000000")
    cases = tt.load_cases(EVAL_DIR / "cases.json")
    planned = tt.plan_calls(
        tt.build_matrix(cases, blocks=["flat"], limit=1), V6, model_ids=[PRO], size="1K"
    )
    args = runner.build_parser().parse_args(["--results-dir", str(tmp_path / "res")])
    first, second = (
        runner.run_paid(
            planned,
            tt,
            ledger=sc.SpendLedger(Decimal("1")),
            api_key="dummy",
            args=args,
            inner_transport=_CountingInner(lambda _r: _ok()),
        )
        for _ in range(2)
    )
    assert first["stamp"] != second["stamp"]
    assert first["results_path"] != second["results_path"]
    assert len(list((tmp_path / "res").glob("*.json"))) == 2
    assert len(list((tmp_path / "salidas").iterdir())) == 2


def test_resolve_refuses_paths_outside_their_base(tmp_path: Path) -> None:
    ok = tt.ImageRef("a", "sub/a.png")
    assert ok.resolve(tmp_path, REPO_ROOT).is_relative_to(tmp_path.resolve())
    with pytest.raises(ValueError, match="outside"):
        tt.ImageRef("b", "../fuera.png").resolve(tmp_path, REPO_ROOT)
    with pytest.raises(ValueError, match="outside"):
        tt.ImageRef("c", "../../x.png", fixture=True).resolve(tmp_path, REPO_ROOT)
    with pytest.raises(ValueError):
        tt.missing_files(
            [tt.MatrixItem("color", "c", None, (tt.ImageRef("d", "../x"),), None, False)],
            tmp_path,
            REPO_ROOT,
        )


def test_eval_selects_pricing_v6_explicitly() -> None:
    assert tt.PRICING_VERSION == "v6"


# --- 1B findings: dry-run wording, file names, ceiling stop, no machine paths ------------


def test_dry_run_over_the_ceiling_says_the_paid_run_will_refuse(
    no_http: list[httpx.Request], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _runner().main(["--dry-run", "--limit", "2", "--max-usd", "0.1"]) == 0
    out = capsys.readouterr().out
    assert "se negará a empezar (código 2)" in out and "--max-usd" in out
    assert no_http == []


def test_output_names_never_collide() -> None:
    runner = _runner()

    def call(case: str, ref: str) -> Any:
        item = tt.MatrixItem("texture", case, ref, (), "X", False)
        return tt.PlannedCall(item, PRO, None)

    assert runner.output_name(call("a__b", "c")) != runner.output_name(call("a", "b__c"))
    assert runner.output_name(call("a", "b")) == f"texture~a~b~{PRO}"
    weird = tt.PlannedCall(tt.MatrixItem("color", "a", "b", (), None, False), "x/../y", None)
    assert "/" not in runner.output_name(weird)


def test_report_has_no_absolute_machine_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    raw = _raw()
    raw["blocks"]["texture"]["cases"] = [
        {"id": "logo-falta", "path": "no/existe.png", "expected_text": "NO"}
    ]
    cases = tt.parse_cases(raw)
    planned = tt.plan_calls(
        tt.build_matrix(cases, blocks=["texture", "flat"]), V6, model_ids=[PRO], size="1K"
    )
    report = runner.run_paid(
        planned,
        tt,
        ledger=sc.SpendLedger(Decimal("1")),
        api_key="dummy",
        args=runner.build_parser().parse_args(["--results-dir", str(tmp_path / "res")]),
        inner_transport=_CountingInner(lambda _r: _ok()),
    )
    assert all(r["estado"] == "error" for r in report["items"].values())  # file missing
    (saved_path,) = (tmp_path / "res").glob("*.json")
    text = saved_path.read_text(encoding="utf-8")
    for absolute in (tmp_path, tmp_path.resolve(), REPO_ROOT):
        for form in (str(absolute), absolute.as_posix(), json.dumps(str(absolute))[1:-1]):
            assert form not in text
    assert not re.search(r"[A-Za-z]:(\\\\|\\|/)", text)  # no drive-letter path at all
    saved = json.loads(text)
    assert not Path(saved["results_path"]).is_absolute()
    assert not Path(saved["salidas"]).is_absolute()
    assert "<imagenes>" in json.dumps(saved["items"])  # the error names the base, not the disk


def test_ceiling_stop_skips_later_paid_items_but_runs_the_free_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    cases = tt.load_cases(EVAL_DIR / "cases.json")
    items = tt.build_matrix(cases, limit=2)  # color, texture, flat: paid items come first
    planned = tt.plan_calls(items, V6, model_ids=[PRO], size="1K")
    paid = [c for c in planned if c.quote is not None]
    assert len(paid) >= 3 and any(c.quote is None for c in planned)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok()

    report = runner.run_paid(
        planned,
        tt,
        ledger=sc.SpendLedger(Decimal("0.05")),  # one paid item fits, the second does not
        api_key="dummy",
        args=runner.build_parser().parse_args(["--results-dir", str(tmp_path)]),
        inner_transport=httpx.MockTransport(handler),
    )
    assert len(seen) == 1 and report["stopped"]
    by_key = {f"{c.item.id}@{c.model_id}": c for c in planned}
    for key, record in report["items"].items():
        if by_key[key].quote is None:
            assert record["estado"] == "hecho", key  # free: never touches the ledger
    paid_states = [report["items"][f"{c.item.id}@{c.model_id}"]["estado"] for c in paid]
    assert paid_states[:2] == ["hecho", "rechazado por el tope"]
    assert set(paid_states[2:]) == {"omitido"}
    assert runner.exit_code(report) == 5


UPLOAD = "uploaded_files/uploads/x/logo/logotipo"


def _fixture_case(raw: dict[str, Any]) -> dict[str, Any]:
    return raw["blocks"]["texture"]["cases"][0]  # fix-qualify-icono, a fixture case


@pytest.mark.parametrize(
    "breaker",
    [
        lambda r: _fixture_case(r).update(path=UPLOAD),
        lambda r: _fixture_case(r).update(path="Qualify/ui/logo.png"),
        lambda r: _fixture_case(r).update(path=".web/public/logo.png"),
        lambda r: _fixture_case(r).update(path="packages/render/public/otro.png"),
        lambda r: _fixture_case(r).update(path="assets"),
        lambda r: _fixture_case(r)["references"][0].update(path=UPLOAD),
        lambda r: _fixture_case(r)["references"][0].update(fixture=True),
        lambda r: _fixture_case(r)["references"][0].update(fixture=True, path=UPLOAD),
        lambda r: r["blocks"]["texture"]["references"][0].update(fixture=True, path=UPLOAD),
        lambda r: r["blocks"]["texture"]["references"][0].update(fixture=False),
        lambda r: _fixture_case(r).update(fixture="yes"),
    ],
)
def test_fixtures_are_allowlisted(breaker: Any) -> None:
    raw = _raw()
    breaker(raw)
    with pytest.raises(tt.CasesError):
        tt.parse_cases(raw)


def test_a_fixture_ref_outside_the_roots_is_refused_at_resolve() -> None:
    for path in (UPLOAD, "Qualify/ui/logo.png", ".web/x.png", "docs/index.md"):
        with pytest.raises(tt.CasesError, match="outside the fixture roots"):
            tt.ImageRef("x", path, fixture=True).resolve(REPO_ROOT / "nada", REPO_ROOT)


def test_shipped_fixtures_sit_under_the_roots(cases: tt.CaseSet) -> None:
    fixtures = [i for i in tt.build_matrix(cases) if i.fixture]
    assert fixtures
    for item in fixtures:
        for image in item.images:
            path = image.resolve(REPO_ROOT / "nada", REPO_ROOT)
            assert path.is_file()
            assert any(
                path.is_relative_to((REPO_ROOT / root).resolve()) for root in tt.FIXTURE_ROOTS
            )


def test_dry_run_prints_the_fixture_paths(
    no_http: list[httpx.Request], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _runner().main(["--dry-run", "--limit", "2"]) == 0
    out = capsys.readouterr().out
    assert "rutas: packages/render/public/sample/photo-1.jpg, " in out
    assert "rutas: assets/qualify-icon-email.png, packages/render/public/sample/photo-1.jpg" in out
    assert no_http == []


def test_duplicate_configs_exit_2_before_planning(
    no_http: list[httpx.Request],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()

    def no_plan(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("planned despite duplicate --configs")

    monkeypatch.setattr(runner, "_plan", no_plan)
    code = runner.main(["--dry-run", "--configs", f"{PRO}, {PRO} ,{LITE}"])
    out = capsys.readouterr().out
    assert code == 2
    assert f"--configs repite el modelo {PRO}" in out and "Solicitudes de red: 0" in out
    assert no_http == []


# --- PR 2: masks, the flat finish in the run, metrics only after generation ---------


def _color_case(raw: dict[str, Any], index: int = 0) -> dict[str, Any]:
    return raw["blocks"]["color"]["cases"][index]


def test_color_cases_take_an_optional_mask(cases: tt.CaseSet) -> None:
    disc = next(c for c in cases.color if c.id == "fix-objeto-disco")
    assert disc.mask == tt.ImageRef(
        "fix-objeto-disco.mask",
        "packages/api/evals/plantillas_ai/fixtures/objeto-disco-mascara.png",
        fixture=True,
    )
    assert all(c.mask is None for c in cases.color if c.id != "fix-objeto-disco")
    items = tt.build_matrix(cases, blocks=["color"], limit=1)
    assert items[0].mask == disc.mask
    assert tt.missing_files(items, EVAL_DIR / "imagenes", REPO_ROOT) == []
    raw = _raw()
    _color_case(raw, 2)["mask"] = "color/mascaras/taza.png"
    with_mask = tt.parse_cases(raw)
    assert with_mask.color[2].mask == tt.ImageRef(
        "taza-ceramica-blanca.mask", "color/mascaras/taza.png"
    )
    missing = tt.missing_files(
        tt.build_matrix(with_mask, blocks=["color"]), EVAL_DIR / "x", REPO_ROOT
    )
    assert (EVAL_DIR / "x" / "color" / "mascaras" / "taza.png").resolve() in missing


@pytest.mark.parametrize(
    "breaker",
    [
        lambda r: _color_case(r).update(mask="uploaded_files/uploads/x/mascara.png"),
        lambda r: _color_case(r).update(mask="Qualify/mascara.png"),
        lambda r: _color_case(r).update(mask="../fuera.png"),
        lambda r: _color_case(r).update(mask=7),
        lambda r: _color_case(r, 2).update(mask="/abs/m.png"),
        lambda r: r["blocks"]["texture"]["cases"][2].update(mask="m.png"),  # color only
        lambda r: r["blocks"]["flat"].update(fill="#C0392B"),  # the flat color is gone
    ],
)
def test_invalid_masks_are_rejected(breaker: Any) -> None:
    raw = _raw()
    breaker(raw)
    with pytest.raises(tt.CasesError):
        tt.parse_cases(raw)


def test_the_eval_fixtures_root_is_allowlisted() -> None:
    assert tt.FIXTURE_ROOTS[:2] == ("assets", "packages/render/public/sample")
    assert "packages/api/evals/plantillas_ai/fixtures" in tt.FIXTURE_ROOTS
    for name in ("make_fixtures.py", "luma-wordmark.png", "objeto-disco-mascara.png"):
        assert (EVAL_DIR / "fixtures" / name).is_file()
    for png in (EVAL_DIR / "fixtures").glob("*.png"):
        assert png.stat().st_size < 300_000
    with pytest.raises(tt.CasesError):
        tt.ImageRef("x", "packages/api/evals/plantillas_ai/cases.json.png", fixture=True).resolve(
            EVAL_DIR / "imagenes", REPO_ROOT
        )


def test_full_dry_run_counts_the_flat_finishes(
    no_http: list[httpx.Request],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.evals import image_metrics as im

    def never(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a dry run computes no image")

    monkeypatch.setattr(im, "flat_texture_fill", never)
    monkeypatch.setattr(im, "color_transfer_metrics", never)
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    assert runner.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Incluidos 136 ítems, excluidos 0" in out
    assert "flat      52 llamadas   estimado USD 0.0000" in out
    assert "(84 pagadas)   estimado USD 4.0320" in out
    assert "objeto-disco-mascara.png" in out  # the fixture row shows its mask path
    assert "Solicitudes de red: 0" in out and no_http == []


def test_paid_color_items_get_metrics_and_a_recomposed_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    cases = tt.load_cases(EVAL_DIR / "cases.json")
    planned = tt.plan_calls(
        tt.build_matrix(cases, blocks=["color"], limit=2), V6, model_ids=[PRO], size="1K"
    )
    report = runner.run_paid(
        planned,
        tt,
        ledger=sc.SpendLedger(Decimal("1")),
        api_key="dummy",
        args=runner.build_parser().parse_args(["--results-dir", str(tmp_path / "res")]),
        inner_transport=httpx.MockTransport(lambda _r: _ok()),
    )
    disc = report["items"][f"color:fix-objeto-disco+fix-paleta-menta-coral-cobre@{PRO}"]
    photo = report["items"][f"color:fix-muestra-1+fix-paleta-menta-coral-cobre@{PRO}"]
    assert disc["estado"] == photo["estado"] == "hecho"
    assert disc["metricas"]["origen_mascara"] == "mask"
    assert disc["metricas"]["metricas_version"] == "metricas-v1"
    assert disc["metricas"]["borde_recompuesto_psnr_db"] is None  # the fixture mask is hard
    assert disc["metricas"]["resultado_redimensionado"] is True  # the 8x8 double
    assert photo["metricas"]["origen_mascara"] == "none"  # PR 3 flags it
    assert len(list(tmp_path.rglob("*~recompuesto.png"))) == 1


def test_a_failed_metric_keeps_the_generated_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_api.evals import image_metrics as im

    def broken(*_a: Any, **_k: Any) -> Any:
        raise ValueError("no pixels to compare")

    monkeypatch.setattr(im, "color_transfer_metrics", broken)
    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    cases = tt.load_cases(EVAL_DIR / "cases.json")
    planned = tt.plan_calls(
        tt.build_matrix(cases, blocks=["color"], limit=1), V6, model_ids=[PRO], size="1K"
    )
    report = runner.run_paid(
        planned,
        tt,
        ledger=sc.SpendLedger(Decimal("1")),
        api_key="dummy",
        args=runner.build_parser().parse_args(["--results-dir", str(tmp_path / "res")]),
        inner_transport=httpx.MockTransport(lambda _r: _ok()),
    )
    (record,) = report["items"].values()
    assert record["estado"] == "hecho" and record["metricas_error"].startswith("ValueError")
    assert len(list(tmp_path.rglob("*.jpg"))) == 1


def test_a_configured_reader_checks_the_texture_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_api.evals.image_metrics import FakeReader

    runner = _runner()
    monkeypatch.setattr(runner, "IMAGES_DIR", tmp_path)
    cases = tt.load_cases(EVAL_DIR / "cases.json")
    planned = tt.plan_calls(
        tt.build_matrix(cases, blocks=["texture"], limit=1), V6, model_ids=[PRO], size="1K"
    )
    reader = FakeReader(default="luma")
    report = runner.run_paid(
        planned,
        tt,
        ledger=sc.SpendLedger(Decimal("1")),
        api_key="dummy",
        args=runner.build_parser().parse_args(["--results-dir", str(tmp_path / "res")]),
        inner_transport=httpx.MockTransport(lambda _r: _ok()),
        reader=reader,
    )
    (record,) = report["items"].values()
    assert record["legibilidad"] == {
        "metricas_version": "metricas-v1",
        "estado": "leido",
        "leido": "luma",
        "coincide": True,
    }
    assert len(reader.calls) == 1

"""m-25129385 (ADR 50 §12.12): the character drawn from a real person's photo — offline.

Covers the written-permission refusal, the matrix, the prompts, the cost from the
versioned table, the dry run and a paid run against fake adapters (nothing here reaches a
vendor), and the likeness sheet.
"""

from __future__ import annotations

import csv
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

from qualify_api.evals import avatar_photo_bench as bench
from qualify_api.evals import avatar_scene_bench as scene_bench
from qualify_api.evals import byteplus_eval_guard

RUNNER = Path(__file__).resolve().parents[1] / "evals" / "avatar_escena" / "personaje_foto.py"
PRICING = JsonPricingTable(bench.PRICING_VERSION)


def _runner() -> Any:
    spec = importlib.util.spec_from_file_location("avatar_foto_runner", RUNNER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _jpeg(path: Path, color: tuple[int, int, int] = (200, 120, 40)) -> Path:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buffer, "JPEG")
    path.write_bytes(buffer.getvalue())
    return path


def _material(tmp_path: Path, people: list[dict[str, Any]] | None = None) -> Path:
    _jpeg(tmp_path / "producto.jpg")
    _jpeg(tmp_path / "fondo.jpg", (40, 80, 70))
    (tmp_path / "fotos").mkdir(exist_ok=True)
    if people is None:
        people = [
            {"id": f"p{n}", "photo": f"fotos/p{n}.jpg", "permiso_escrito": True} for n in (1, 2, 3)
        ]
    for n, person in enumerate(people, start=1):
        if person.get("photo"):
            _jpeg(tmp_path / str(person["photo"]), (n * 60, 30, 30))
    file = tmp_path / "material.json"
    file.write_text(
        json.dumps(
            {
                "producto": {"nombre": "super smash", "photo": "producto.jpg"},
                "fondo": {"photo": "fondo.jpg"},
                "personas": people,
            }
        ),
        encoding="utf-8",
    )
    return file


# -- permission ------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, False, "true", "sí", 1])
def test_a_person_without_written_permission_refuses_the_whole_list(value: object) -> None:
    people = [{"id": "p1", "permiso_escrito": True}, {"id": "p2"}]
    if value is not None:
        people[1]["permiso_escrito"] = value
    with pytest.raises(bench.PermissionRefused, match="p2"):
        bench.check_people(people)


def test_people_with_permission_pass() -> None:
    people = bench.check_people([{"id": "p1", "permiso_escrito": True}])
    assert people == [bench.Person("p1", True)]


@pytest.mark.parametrize(
    "people",
    [
        [],
        None,
        [{"id": "Ana Pérez", "permiso_escrito": True}],
        [{"id": "p1", "permiso_escrito": True}, {"id": "p1", "permiso_escrito": True}],
        [{"id": f"p{n}", "permiso_escrito": True} for n in range(6)],
    ],
)
def test_people_list_is_short_with_opaque_unique_ids(people: object) -> None:
    with pytest.raises(bench.PermissionRefused):
        bench.check_people(people)


def test_material_without_permission_is_refused_before_opening_photos(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = _runner()
    material = _material(
        tmp_path,
        [
            {"id": "p1", "photo": "fotos/p1.jpg", "permiso_escrito": True},
            # its photo does not even exist: the permission refusal comes first
            {"id": "p2", "photo": "fotos/no-existe.jpg", "permiso_escrito": False},
        ],
    )
    with pytest.raises(bench.PermissionRefused):
        runner.load_material(str(material))
    assert runner.main(["plan", "--material", str(material), "--out", str(tmp_path)]) == 2
    assert "Sin permiso escrito: p2" in capsys.readouterr().err


def test_photos_must_live_outside_the_repo(tmp_path: Path) -> None:
    runner = _runner()
    material = _material(tmp_path)
    data = json.loads(material.read_text(encoding="utf-8"))
    data["personas"][0]["photo"] = str(runner.base.SAMPLE_PRODUCT)
    material.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(runner.MaterialError, match="fuera del repositorio"):
        runner.load_material(str(material))


# -- matrix, prompts, cost -------------------------------------------------------------


def test_matrix_is_two_drawings_and_one_scene_per_photo() -> None:
    people = [bench.Person(f"p{n}", True) for n in (1, 2, 3)]
    drawings = bench.drawing_items(PRICING, people)
    assert [d.label for d in drawings[:2]] == [
        "personaje-foto/p1/opcion-1",
        "personaje-foto/p1/opcion-2",
    ]
    assert len(drawings) == 6
    scenes = bench.scene_items(PRICING, people)
    assert [s.label for s in scenes] == [
        "foto-p1/dibujado/e1",
        "foto-p2/dibujado/e1",
        "foto-p3/dibujado/e1",
    ]
    case = bench.case_for(people[0])
    assert case.scene.seconds == 5 and case.background.kind == "dibujado"
    assert bench.person_of(case) == "p1"
    with pytest.raises(ValueError):
        bench.drawing_items(PRICING, people, options=4)


def test_drawing_prompt_asks_for_likeness_and_carries_the_brand() -> None:
    prompt = bench.drawing_prompt()
    assert "resembles this person" in prompt and "Image 1" in prompt
    for color in scene_bench.NIBBLES.palette:
        assert color in prompt
    assert "Baloo 2" in prompt and "Nunito" in prompt
    params = bench.drawing_params("data:image/jpeg;base64,AAAA")
    assert params["images"] == ["data:image/jpeg;base64,AAAA"]
    assert params["model"] == scene_bench.SEEDREAM_MODEL and params["size"] == "1080x1920"


def test_the_scene_sends_the_drawing_never_the_photo() -> None:
    case = bench.case_for(bench.Person("p1", True))
    params = scene_bench.scene_params(
        case, character_url="dibujo", product_url="producto", background_url="fondo"
    )
    assert params["reference_images"] == ["dibujo", "producto", "fondo"]
    assert params["draft"] is True and params["duration_seconds"] == 5


def test_cost_comes_from_the_v10_table() -> None:
    assert bench.PRICING_VERSION == "v10"
    # 1K tier (1080x1920 <= 2.36 MP), one input image: the first one is free on 5.0 pro
    assert bench.drawing_quote(PRICING) == Decimal("0.045")
    people = [bench.Person(f"p{n}", True) for n in (1, 2, 3)]
    items = bench.drawing_items(PRICING, people) + bench.scene_items(PRICING, people)
    totals = scene_bench.plan_totals(items)
    assert Decimal(totals["dibujar"]["quote_usd"]) == Decimal("0.270")
    scene = scene_bench.scene_quote(bench.case_for(people[0]), PRICING, "borrador")
    assert Decimal(totals["escenas"]["quote_usd"]) == scene * 3
    # the whole plan with its 10 % margin fits the proposed ceiling, with room to ask one
    # scene again (option 2 after a refusal)
    one_scene = scene_bench.reserved(scene)
    assert Decimal(totals["total_reserved_usd"]) + one_scene < bench.PROPOSED_MAX_USD


# -- dry run ---------------------------------------------------------------------------


def test_dry_run_sends_nothing_and_writes_the_quote(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = _runner()
    out = tmp_path / "out"
    assert runner.main(["plan", "--material", str(_material(tmp_path)), "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "bloqueadas durante la prueba en seco: 0" in text
    assert "personaje-desde-foto-v1" in text
    quote = json.loads(next(out.glob("cotizacion-plan-*.json")).read_text(encoding="utf-8"))
    assert quote["people"] == ["p1", "p2", "p3"] and len(quote["items"]) == 9
    # without a material the plan still quotes three placeholder people
    assert runner.main(["plan", "--out", str(out)]) == 0


def test_paid_steps_need_the_flag_and_the_material(tmp_path: Path) -> None:
    runner = _runner()
    assert runner.main(["dibujar", "--out", str(tmp_path)]) == 2
    assert runner.main(["escenas", "--dry-run", "--i-have-spend-authorization"]) == 2
    assert runner.main(["plan", "--i-have-spend-authorization"]) == 2
    with pytest.raises(SystemExit, match="--material"):
        runner.main(["dibujar", "--i-have-spend-authorization", "--out", str(tmp_path)])


def test_paid_scenes_refuse_outside_the_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    monkeypatch.setattr(byteplus_eval_guard, "in_off_hours", lambda now: False)
    run = tmp_path / "run"
    (run / "dibujos").mkdir(parents=True)
    _jpeg(run / "dibujos" / "personaje-foto__p1__opcion-1.jpg")
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


# -- a paid run against fakes ----------------------------------------------------------


class FakeSeedream:
    """Refuses p2's photo (as the public-figure filter would), draws the rest."""

    sent: list[dict[str, Any]] = []

    def __init__(self, **_: Any) -> None:
        pass

    def generate(self, request: Any, *, api_key: str) -> GenerationResult:
        from qualify_creative.adapters.byteplus_ark import ArkAPIError

        params = dict(request.params)
        FakeSeedream.sent.append(params)
        assert len(params["images"]) == 1  # the photo, and only it
        if params["images"][0] == "data:p2":
            raise ArkAPIError(400, "InputImageSensitiveContentDetected", "real person")
        buffer = io.BytesIO()
        Image.new("RGB", (32, 56), (10, 80, 70 + len(FakeSeedream.sent))).save(buffer, "JPEG")
        return GenerationResult(
            payload={"images": [buffer.getvalue()]},
            model_id=scene_bench.SEEDREAM_MODEL,
            provider="seedream",
            usage=Usage(pieces=1),
        )


class FakeSeedance:
    """Refuses p3's drawing as a real face, makes p1's."""

    sent: list[dict[str, Any]] = []
    refuse: str = ""

    def __init__(self, **_: Any) -> None:
        pass

    def generate(self, request: Any, *, api_key: str) -> GenerationResult:
        from qualify_creative.adapters.byteplus_ark import ArkAPIError, estimate_video_tokens

        params = dict(request.params)
        FakeSeedance.sent.append(params)
        if params["reference_images"][0] == FakeSeedance.refuse:
            raise ArkAPIError(400, "InputImageSensitiveContentDetected.PrivacyInformation", "x")
        tokens = estimate_video_tokens(
            scene_bench.SEEDANCE_MODEL, "480p", "9:16", int(params["duration_seconds"])
        )
        return GenerationResult(
            payload={"task_id": f"cgt-{len(FakeSeedance.sent)}"},
            model_id=scene_bench.SEEDANCE_MODEL,
            provider="seedance",
            usage=Usage(output_tokens=tokens),
            media_url="https://example.invalid/v.mp4",
        )


def test_paid_run_with_fakes_records_both_answers_cost_and_the_sheet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from qualify_creative.adapters import byteplus_ark

    from qualify_api.evals import spend_control

    runner = _runner()
    monkeypatch.setenv("QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY", "fake-key")
    monkeypatch.delenv("QUALIFY_BYTEPLUS_ARK_PROD_KEY_FINGERPRINT", raising=False)
    monkeypatch.setattr(byteplus_ark, "SeedreamImageAdapter", FakeSeedream)
    monkeypatch.setattr(byteplus_ark, "SeedanceVideoAdapter", FakeSeedance)
    monkeypatch.setattr(byteplus_eval_guard, "in_off_hours", lambda now: True)
    monkeypatch.setattr(
        runner.base, "_download_video", lambda url, target: target.write_bytes(b"mp4") and None
    )
    material = _material(tmp_path)
    photos = {f"p{n}": (tmp_path / "fotos" / f"p{n}.jpg").read_bytes() for n in (1, 2, 3)}
    real_encode = spend_control.reference_data_url

    def tagged(data: bytes, **limits: int) -> str:
        for pid, photo in photos.items():
            if data == photo:
                return f"data:{pid}"
        return real_encode(data, **limits)

    monkeypatch.setattr(spend_control, "reference_data_url", tagged)
    FakeSeedream.sent = []
    out = tmp_path / "out"
    paid = ["--i-have-spend-authorization", "--max-usd", "3", "--material", str(material)]
    assert runner.main(["dibujar", *paid, "--out", str(out)]) == 0
    run = next(p for p in out.iterdir() if p.is_dir())
    drawings = json.loads((run / "dibujos.json").read_text(encoding="utf-8"))
    assert len(drawings) == 6 and len(FakeSeedream.sent) == 6
    made = [d for d in drawings.values() if d.get("file")]
    assert len(made) == 4 and all(d["cost_usd"] == "0.045" for d in made)
    refused = [d for d in drawings.values() if d.get("error")]
    assert {d["person"] for d in refused} == {"p2"} and all(d["cost_usd"] == "0" for d in refused)
    assert all(d["permiso_escrito"] is True and d["photo_sha256"] for d in drawings.values())
    assert {d["prompt_version"] for d in drawings.values()} == {bench.PROMPT_VERSION}

    p3_drawing = run / "dibujos" / "personaje-foto__p3__opcion-1.jpg"
    FakeSeedance.refuse = runner.base._raw_data_url(p3_drawing)
    FakeSeedance.sent = []
    assert runner.main(["escenas", *paid, "--run", str(run)]) == 0
    assert "p2: no hay dibujo" in capsys.readouterr().out
    # p2 has no drawing: two scenes asked, and Seedance never saw a photo
    assert len(FakeSeedance.sent) == 2
    for params in FakeSeedance.sent:
        assert not any(ref.startswith("data:p") for ref in params["reference_images"])
    results = json.loads((run / "resultados.json").read_text(encoding="utf-8"))
    assert results["foto-p1/dibujado/e1"]["video"] == "videos/foto-p1__dibujado__e1.mp4"
    assert results["foto-p1/dibujado/e1"]["character_prompt_version"] == bench.PROMPT_VERSION
    assert results["foto-p3/dibujado/e1"]["refusal"] == "rostro"
    assert results["foto-p3/dibujado/e1"]["cost_usd"] == "0"
    spend = json.loads((run / "gasto.json").read_text(encoding="utf-8"))
    expected = Decimal("0.180") + Decimal(results["foto-p1/dibujado/e1"]["cost_usd"])
    assert Decimal(spend["spent_usd"]) == expected

    # resumed: nothing is paid twice
    FakeSeedance.sent = []
    assert runner.main(["escenas", *paid, "--run", str(run)]) == 0
    assert len(FakeSeedance.sent) == 1  # only p3: released, so it is asked again
    assert all(p["reference_images"][0] == FakeSeedance.refuse for p in FakeSeedance.sent)

    assert runner.main(["planilla", "--run", str(run)]) == 0
    sheet = (run / "juicio-deivid.csv").read_text(encoding="utf-8")
    rows = {r["persona"]: r for r in csv.DictReader(sheet.splitlines())}
    assert rows["p1"]["seedream_acepto_opcion_1"] == "si"
    assert rows["p1"]["seedance_acepto"] == "si"
    assert rows["p2"]["seedream_acepto_opcion_1"] == "no" and rows["p2"]["seedance_acepto"] == ""
    assert rows["p3"]["seedance_acepto"] == "no" and rows["p3"]["tipo_rechazo"] == "rostro"


def test_the_ceiling_refuses_the_drawings_before_sending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_creative.adapters import byteplus_ark

    runner = _runner()
    monkeypatch.setenv("QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY", "fake-key")
    monkeypatch.setattr(byteplus_ark, "SeedreamImageAdapter", FakeSeedream)
    FakeSeedream.sent = []
    with pytest.raises(SystemExit, match="No se manda nada"):
        runner.main(
            [
                "dibujar",
                "--i-have-spend-authorization",
                "--max-usd",
                "0.2",
                "--material",
                str(_material(tmp_path)),
                "--out",
                str(tmp_path / "out"),
            ]
        )
    assert FakeSeedream.sent == []


# -- the sheet -------------------------------------------------------------------------


def test_summary_counts_answers_and_likeness() -> None:
    rows = bench.sheet_rows(["p1", "p2"], {}, {})
    rows[0].update(
        seedream_acepto_opcion_1="si",
        seedream_acepto_opcion_2="si",
        seedance_acepto="si",
        parecido_opcion_1="3",
        parecido_opcion_2="2",
        parecido_video="2",
    )
    rows[1].update(
        seedream_acepto_opcion_1="si",
        seedream_acepto_opcion_2="no",
        seedance_acepto="no",
        tipo_rechazo="rostro",
        parecido_opcion_1="1",
        parecido_video="5",
    )
    summary = bench.summarize_sheet(bench.sheet_csv(rows))
    assert summary["seedream"] == {"pedidos": 4, "aceptados": 3}
    assert summary["seedance"] == {"pedidos": 2, "aceptados": 1, "rechazos": {"rostro": 1}}
    assert summary["parecido_opcion_1"]["media"] == "2.00"
    assert summary["parecido_video"]["juzgados"] == 1
    assert summary["invalidos"] == ["p2/parecido_video=5"]

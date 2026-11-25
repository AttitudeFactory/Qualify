"""EF-12 (m-25026587): the paid bench of the «Con IA» effects — offline.

The pure part (`qualify_api.evals.effects_bench`) and the runner's free paths: the dry
run compiles through the real producer and sends nothing, the paid run refuses without
its guards, and judge → score works on a fake run folder. No network, no key, no spend."""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from qualify_creative.effects import (
    Measured,
    effect_subject,
    load_effects,
    parse_library,
    seedance_effect_line,
)
from qualify_creative.schemas import EffectUse

from qualify_api.evals.effects_bench import (
    CONTROLS,
    Judgment,
    JudgmentError,
    bench_arms,
    bench_library,
    consensus,
    library_v6,
    object_vs_atmospheric,
    parse_judgments,
    plan_trials,
    preview_asset_path,
    score_arms,
    wilson,
)

REPO = Path(__file__).resolve().parents[3]
RUNNER = REPO / "packages" / "api" / "evals" / "banco_efectos" / "run_experiment.py"
SEEDANCE_IDS = [
    "fuego_lena_base",
    "quemadores_brillan",
    "vapor_sobre_comida",
    "humo_denso",
    "brasas",
]


def _runner() -> Any:
    spec = importlib.util.spec_from_file_location("banco_efectos_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up
    spec.loader.exec_module(module)
    return module


# -- arms ------------------------------------------------------------------------------


def test_arms_are_every_seedance_template_and_the_two_controls_in_order() -> None:
    arms = bench_arms(load_effects("v5"))
    ids = [arm.id for arm in arms]
    assert [i for i in ids if i not in CONTROLS] == SEEDANCE_IDS
    # each control right after the object arm it is compared with
    assert ids.index("vapor_atmosferico") == ids.index("vapor_sobre_comida") + 1
    assert ids.index("humo_atmosferico") == ids.index("humo_denso") + 1
    assert [a.id for a in bench_arms(load_effects("v5"), controls=False)] == SEEDANCE_IDS


def test_an_object_arm_fills_its_template_as_production_does() -> None:
    arm = next(a for a in bench_arms(load_effects("v5")) if a.id == "humo_denso")
    use = arm.use()
    assert use == EffectUse(effect_id="humo_denso", version=1, params={"zone": "top"})
    line = seedance_effect_line(arm.entry, use, subject=effect_subject("Shawarma mixto"))
    assert line.startswith('Dense grey smoke drifts through the upper third of the frame above "')
    assert arm.asked() == "Humo denso — arriba"


def test_a_control_names_no_zone_and_is_never_offered() -> None:
    arm = next(a for a in bench_arms(load_effects("v5")) if a.id == "vapor_atmosferico")
    assert arm.is_control and arm.compared_with == "vapor_sobre_comida"
    assert arm.zone() is None and arm.use().param_values == {}
    assert not arm.entry.offered and arm.entry.measured is None
    line = seedance_effect_line(arm.entry, arm.use(), subject='"Arepa"')
    assert "{" not in line and '"Arepa"' in line and "frame" not in line
    assert arm.asked().endswith("toda la escena")


def test_the_bench_library_adds_only_the_controls() -> None:
    base = load_effects("v5")
    arms = bench_arms(base)
    library = bench_library(base, arms)
    assert len(library.entries) == len(base.entries) + 2
    assert library.get("humo_atmosferico", 1) is not None
    assert library.offered() == base.offered()


def test_trials_go_effect_by_effect() -> None:
    arms = bench_arms(load_effects("v5"), only=["brasas", "humo_denso"])
    trials = plan_trials(arms, ["a", "b"], 2)
    assert len(trials) == 8
    assert [t.arm.id for t in trials[:4]] == ["humo_denso"] * 4
    assert trials[0].label == "humo_denso/a/1"
    with pytest.raises(ValueError):
        plan_trials(arms, ["a"], 0)


# -- statistics ------------------------------------------------------------------------


def test_wilson_interval() -> None:
    assert wilson(3, 4) == (0.3006, 0.9544)
    assert wilson(0, 4)[0] == 0.0
    assert wilson(4, 4)[1] == 1.0
    assert wilson(0, 0) == (0.0, 1.0)


def _j(video: str, ok: bool, *, zone: bool | None = True, credible: int = 2) -> Judgment:
    return Judgment(video, ok, zone, True, True, credible)


def test_judgments_parse_doubtful_as_no_and_skip_unjudged_rows() -> None:
    rows = [
        {
            "video": "v01",
            "visible": "sí",
            "en_zona": "si",
            "producto_igual": "si",
            "sin_letras": "si",
            "creible": "3",
        },
        {
            "video": "v02",
            "visible": "dudoso",
            "en_zona": "",
            "producto_igual": "si",
            "sin_letras": "si",
            "creible": "",
        },
        {"video": "v03", "visible": "", "en_zona": "", "producto_igual": "", "sin_letras": ""},
    ]
    found = parse_judgments(rows, ["v01", "v02", "v03"])
    assert [j.video for j in found] == ["v01", "v02"]
    assert found[0].success and found[0].creible == 3
    assert not found[1].visible and found[1].en_zona is None and not found[1].success
    with pytest.raises(JudgmentError):
        parse_judgments([{"video": "v99", "visible": "si"}], ["v01"])


def test_a_video_outside_its_zone_fails_but_counts_for_the_comparison() -> None:
    judgment = _j("v01", True, zone=False)
    assert not judgment.success and judgment.success_without_zone


def test_two_people_agree_only_when_both_say_it_worked() -> None:
    first = [_j("v01", True), _j("v02", True), _j("v03", False), _j("v04", True)]
    second = [_j("v01", True), _j("v02", False), _j("v03", False), _j("v04", True)]
    verdicts, report = consensus({"ana": first, "beto": second})
    assert [v for v, j in verdicts.items() if j.success] == ["v01", "v04"]
    assert report["double_judged"] == 4
    assert report["disagreements"] == ["v02"]
    assert report["kappa"] == 0.5 and report["kappa_ok"] is False


def test_one_person_has_no_kappa() -> None:
    verdicts, report = consensus({"ana": [_j("v01", True)]})
    assert verdicts["v01"].success and report["kappa"] is None


def _manifest() -> dict[str, dict[str, Any]]:
    manifest: dict[str, dict[str, Any]] = {}
    for at in range(1, 5):
        manifest[f"h{at}"] = {"arm": "humo_denso", "kind": "objeto", "compared_with": None}
        manifest[f"a{at}"] = {
            "arm": "humo_atmosferico",
            "kind": "atmosferico",
            "compared_with": "humo_denso",
        }
    return manifest


def test_scores_apply_d5_and_rank_winners_by_credibility() -> None:
    verdicts = {
        "h1": _j("h1", True, credible=1),
        "h2": _j("h2", True, credible=3),
        "h3": _j("h3", True, credible=2),
        "h4": _j("h4", False),
        "a1": _j("a1", False, zone=None),
        "a2": _j("a2", False, zone=None),
        "a3": _j("a3", False, zone=None),
        "a4": _j("a4", True, zone=None),
    }
    scores = score_arms(_manifest(), verdicts)
    smoke = scores["humo_denso"]
    assert (smoke.successes, smoke.n) == (3, 4) and smoke.passes()
    assert smoke.winners == ["h2", "h3", "h1"]
    measured = smoke.measured(model="dreamina-seedance-2-5-260628", on=date(2026, 11, 26))
    assert measured.passes and (measured.wilson_low, measured.wilson_high) == (0.3006, 0.9544)
    assert not scores["humo_atmosferico"].passes()
    comparison = object_vs_atmospheric(scores)
    assert comparison[0]["objeto_exitos"] == "3/4"
    assert comparison[0]["atmosferico_exitos"] == "1/4"
    assert comparison[0]["verdict"] == "no concluyente"  # n = 4: the intervals overlap


def test_two_of_three_is_not_enough_under_four_tries() -> None:
    scores = score_arms(
        {f"h{i}": {"arm": "humo_denso", "kind": "objeto"} for i in range(1, 4)},
        {f"h{i}": _j(f"h{i}", True) for i in range(1, 4)},
    )
    assert scores["humo_denso"].n == 3 and not scores["humo_denso"].passes()


# -- the library v6 --------------------------------------------------------------------


def test_library_v6_offers_only_what_passes_and_keeps_v5(tmp_path: Path) -> None:
    v5_path = REPO / "packages/creative/src/qualify_creative/effects_data/v5.json"
    base = json.loads(v5_path.read_text(encoding="utf-8"))
    before = json.dumps(base, sort_keys=True)
    model = "dreamina-seedance-2-5-260628"
    measured = {
        "humo_denso": Measured(
            successes=3,
            n=4,
            wilson_low=0.3006,
            wilson_high=0.9544,
            measured_on=date(2026, 11, 26),
            model=model,
        ),
        "brasas": Measured(
            successes=1,
            n=4,
            wilson_low=0.0456,
            wilson_high=0.6994,
            measured_on=date(2026, 11, 26),
            model=model,
        ),
    }
    document = library_v6(base, measured, notes="bench")
    assert json.dumps(base, sort_keys=True) == before  # v5 untouched
    assert document["version"] == 6
    smoke = next(e for e in document["entries"] if e["id"] == "humo_denso")
    embers = next(e for e in document["entries"] if e["id"] == "brasas")
    assert smoke["offered"] and smoke["version"] == 1
    assert smoke["preview_asset"] == preview_asset_path("humo_denso", 1)
    assert not embers["offered"] and embers["preview_asset"] is None
    assert embers["measured"]["successes"] == 1
    # the copied preview of every offered effect, under an assets root like the package's
    preview = tmp_path / "humo_denso" / "v1" / "preview.mp4"
    preview.parent.mkdir(parents=True)
    for entry in base["entries"]:
        if entry.get("preview_asset"):
            path = tmp_path.joinpath(*entry["preview_asset"].split("/")[1:])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
    preview.write_bytes(b"mp4")
    library = parse_library(document, assets_root=tmp_path)
    offered = library.offered(model=model)
    assert "humo_denso" in [e.id for e in offered]
    assert "brasas" not in [e.id for e in offered]
    assert library.offered(model="otro-modelo") != offered  # D5: tied to its model
    with pytest.raises(ValueError):
        library_v6(document, measured, notes="again")  # already measured: never edited


# -- the runner ------------------------------------------------------------------------


def test_dry_run_compiles_through_the_producer_and_sends_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("QUALIFY_SEEDANCE_EFFECTS", raising=False)
    runner = _runner()
    code = runner.main(
        [
            "drafts",
            "--env-file",
            str(tmp_path / "none.env"),
            "--out",
            str(tmp_path),
            "--effect",
            "humo_denso",
            "--effect",
            "humo_atmosferico",
            "--case",
            "muestra-fresa",
            "--reps",
            "1",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "2 borradores" in out and "nada enviado" in out
    quote = json.loads(next(tmp_path.glob("cotizacion-*.json")).read_text(encoding="utf-8"))
    assert quote["calls"] == 2 and quote["not_compiled"] == []
    smoke, control = quote["requests"]
    assert smoke["prompt"].endswith(
        'Dense grey smoke drifts through the upper third of the frame above "Dona glaseada de '
        'fresa", as from a grill, without hiding it. Everything else stays as it is.'
    )
    assert smoke["prompt_version"] == "efecto-humo_denso-v1" and smoke["fill_version"] == 1
    assert control["prompt_version"] == "control-atmosferico-v1"
    params = smoke["attempts"][0]["params"]
    assert params["draft"] is True and params["resolution"] == "480p"
    assert params["duration_seconds"] == 5 and "seed" not in params
    # the switch was on only inside the run
    assert "QUALIFY_SEEDANCE_EFFECTS" not in os.environ


def test_paid_run_needs_its_guards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _runner()
    none = str(tmp_path / "none.env")
    out = ["--env-file", none, "--out", str(tmp_path)]
    # no approved material
    assert runner.main(["drafts", *out, "--i-have-spend-authorization"]) == 2
    # over D6's ceiling
    assert runner.main(["drafts", *out, "--max-usd", "31"]) == 2
    # outputs inside the repository
    assert runner.main(["drafts", "--env-file", none, "--out", str(REPO / "tmp")]) == 2
    # outside the window, with material: refused before any key is read
    cases = tmp_path / "casos.json"
    cases.write_text(json.dumps({"cases": []}), encoding="utf-8")
    monkeypatch.setattr(runner, "_window_refusal", lambda args: "fuera de la ventana")
    assert runner.main(["drafts", *out, "--cases", str(cases), "--i-have-spend-authorization"]) == 3


def test_judge_then_score_on_a_fake_run(tmp_path: Path) -> None:
    runner = _runner()
    run = tmp_path / "run"
    (run / "videos").mkdir(parents=True)
    trials: dict[str, Any] = {}
    for arm, kind in (("humo_denso", "objeto"), ("humo_atmosferico", "atmosferico")):
        for case in ("a", "b"):
            for rep in (1, 2):
                label = f"{arm}/{case}/{rep}"
                name = f"videos/{label.replace('/', '__')}.mp4"
                (run / name).write_bytes(label.encode())
                trials[label] = {
                    "label": label,
                    "arm": arm,
                    "kind": kind,
                    "compared_with": "humo_denso" if kind == "atmosferico" else None,
                    "case": case,
                    "asked": "Humo",
                    "video": name,
                    "model_billed": "dreamina-seedance-2-5-260628",
                }
    (run / "pruebas.json").write_text(json.dumps({"trials": trials}), encoding="utf-8")
    assert runner.main(["judge", "--run", str(run)]) == 0
    assert runner.main(["judge", "--run", str(run)]) == 2  # never reshuffled
    key = json.loads((run / "juicio" / "clave.json").read_text(encoding="utf-8"))
    assert len(key) == 8 and (run / "juicio" / "juicio.html").is_file()
    sheet = run / "juicio-ana.csv"
    with sheet.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "video",
                "se_pidio",
                "visible",
                "en_zona",
                "producto_igual",
                "sin_letras",
                "creible",
                "nota",
            ]
        )
        for blind, info in key.items():
            ok = "si" if info["arm"] == "humo_denso" else "no"
            writer.writerow([blind, info["asked"], ok, "si", "si", "si", "2", ""])
    assert runner.main(["score", "--run", str(run), "--juicio", f"ana={sheet}"]) == 0
    results = json.loads((run / "resultados.json").read_text(encoding="utf-8"))
    assert results["arms"]["humo_denso"]["passes_d5"] is True
    assert results["measured"]["humo_denso"]["model"] == "dreamina-seedance-2-5-260628"
    assert "humo_atmosferico" not in results["measured"]
    assert len(results["winners"]["humo_denso"]) == 4

"""m-24854495: the sentiment golden set, its blind labelling kit and the Haiku-vs-robertuito
scorer — and the `atender4a.2` triage prompt with confidence. Offline, no network."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from qualify_api.evals import comment_sentiment as cs
from qualify_api.replies.triage import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_CONFIDENCE,
    TRIAGE_PROMPT_VERSION,
    TRIAGE_PROMPT_VERSION_CONFIDENCE,
    ClaudeCommentTriager,
    Sentiment,
    _triage_tool,
    parse_confidence,
    parse_triage,
)

EVAL_DIR = Path(__file__).resolve().parents[1] / "evals" / "replies_ai"
REPO = Path(__file__).resolve().parents[3]


def _module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"sentiment_{name}", EVAL_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _item(ident: str, sentiment: str | None = None, **kw: Any) -> cs.SentimentItem:
    return cs.SentimentItem(
        id=ident,
        text=kw.pop("text", f"comentario {ident}"),
        split=kw.pop("split", "test"),
        sentiment=sentiment,
        **kw,
    )


# --- atender4a.2 -----------------------------------------------------------------------


def test_v2_prompt_is_v1_plus_the_confidence_section_only() -> None:
    assert SYSTEM_PROMPT_CONFIDENCE != SYSTEM_PROMPT
    assert "4. confidence" in SYSTEM_PROMPT_CONFIDENCE
    assert "confidence" not in SYSTEM_PROMPT
    # Everything else word for word: the only change is the inserted section.
    head, _, tail = SYSTEM_PROMPT_CONFIDENCE.partition("4. confidence")
    assert SYSTEM_PROMPT.startswith(head.rstrip("\n"))
    assert tail.split("Reglas:", 1)[1] == SYSTEM_PROMPT.split("Reglas:", 1)[1]


def test_only_v2_tool_asks_for_a_confidence_and_it_is_required() -> None:
    v1 = _triage_tool()["input_schema"]["properties"]["results"]["items"]
    v2 = _triage_tool(with_confidence=True)["input_schema"]["properties"]["results"]["items"]
    assert "confidence" not in v1["properties"]
    assert v2["properties"]["confidence"]["type"] == "number"
    assert "confidence" in v2["required"]
    # Strict tools reject numeric bounds: none sent.
    assert "minimum" not in v2["properties"]["confidence"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.83, 0.83),
        (1, 1.0),
        (1.7, 1.0),
        (-0.2, 0.0),
        (True, None),
        ("0.9", None),
        (float("nan"), None),
        (None, None),
    ],
)
def test_parse_confidence(raw: Any, expected: float | None) -> None:
    assert parse_confidence(raw) == expected


def test_parse_triage_keeps_labels_when_the_confidence_is_malformed() -> None:
    item = {"sentiment": "pos", "kind": "praise", "needs_reply": False, "confidence": "alta"}
    triage = parse_triage(item, model_id="m", prompt_version="atender4a.2", with_confidence=True)
    assert triage is not None and triage.sentiment is Sentiment.POS
    assert triage.confidence is None
    v1 = parse_triage({**item, "confidence": 0.9}, model_id="m", prompt_version="atender4a.1")
    assert v1 is not None and v1.confidence is None  # v1 never carries a score


def test_unknown_prompt_version_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown triage prompt"):
        ClaudeCommentTriager(api_key="sk-test", prompt_version="atender4a.9")


class _Scripted:
    def __init__(self, *responses: SimpleNamespace) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _response(results: list[dict[str, Any]], cache_read: int) -> SimpleNamespace:
    tool = SimpleNamespace(
        type="tool_use", name="registrar_comentarios", input={"results": results}
    )
    return SimpleNamespace(
        content=[tool],
        stop_reason="tool_use",
        model="claude-haiku-5-5",
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=0 if cache_read else 1500,
        ),
    )


def test_v2_triager_sends_the_v2_prompt_and_returns_confidence_and_latency() -> None:
    row = {"id": 1, "sentiment": "neg", "kind": "complaint", "needs_reply": True}
    client = _Scripted(
        _response([{**row, "confidence": 0.92}], 0),
        _response([{**row, "confidence": 0.4}], 1500),
    )
    triager = ClaudeCommentTriager(
        api_key="sk-test",
        prompt_version=TRIAGE_PROMPT_VERSION_CONFIDENCE,
        batch_size=1,
        client_factory=lambda _: client,
    )
    first, second = triager.triage(["llegó frío", "excelente servicio, tres horas"])
    assert first is not None and first.confidence == 0.92
    assert second is not None and second.prompt_version == "atender4a.2"
    assert client.calls[0]["system"][0]["text"] == SYSTEM_PROMPT_CONFIDENCE
    assert len(triager.last_latencies_s) == 2
    report = cs.cache_report(
        [s.cache_read_tokens for s in triager.last_stats],
        [s.cache_creation_tokens for s in triager.last_stats],
    )
    assert report["ok"] and report["checkable"]


def test_default_triager_stays_on_v1() -> None:
    triager = ClaudeCommentTriager(api_key="sk-test")
    assert triager.prompt_version == TRIAGE_PROMPT_VERSION == "atender4a.1"


# --- anonymization and slices --------------------------------------------------------


def test_anonymize_masks_people_but_keeps_prices() -> None:
    text = "@maria.p escríbeme al +57 300 123 4567 o a ana@correo.com https://x.co/a vale 120.000"
    out = cs.anonymize(text)
    assert "@usuario" in out and "maria" not in out
    assert "[teléfono]" in out and "4567" not in out
    assert "[correo]" in out and "ana@" not in out
    assert "[enlace]" in out
    assert "120.000" in out


def test_emoji_only() -> None:
    assert cs.is_emoji_only("🔥🔥")
    assert cs.is_emoji_only("❤️ @usuario")
    assert not cs.is_emoji_only("qué rico 🔥")
    assert not cs.is_emoji_only("@usuario")


def test_normalize_label() -> None:
    assert cs.normalize_label("POS") == "pos"
    assert cs.normalize_label(" Negativo ") == "neg"
    assert cs.normalize_label("NEU") == "neu"
    assert cs.normalize_label("") is None and cs.normalize_label("x") is None


def test_parse_golden_allows_unlabelled_and_rejects_bad_rows() -> None:
    lines = [
        "# header",
        json.dumps({"id": "a", "text": "hola", "split": "dev"}),
        json.dumps(
            {"id": "b", "text": "rico", "split": "test", "sentiment": "POS", "country": "ve"}
        ),
    ]
    items = cs.parse_sentiment_golden(lines)
    assert [i.sentiment for i in items] == [None, "pos"] and items[1].country == "VE"
    with pytest.raises(ValueError, match="duplicate id"):
        cs.parse_sentiment_golden([lines[1], lines[1]])
    with pytest.raises(ValueError, match="unknown label"):
        cs.parse_sentiment_golden(
            [json.dumps({"id": "c", "text": "x", "split": "dev", "sentiment": "meh"})]
        )


# --- scoring -------------------------------------------------------------------------


def test_score_per_class_macro_f1_and_confusion() -> None:
    gold = ["pos"] * 10 + ["neg"] * 10 + ["neu"] * 10
    pred = ["pos"] * 10 + ["neg"] * 8 + ["neu", None] + ["neu"] * 9 + ["pos"]
    s = cs.score(gold, pred)
    assert s.confusion["neg"] == {"pos": 0, "neu": 1, "neg": 8, "none": 1}
    assert s.unanswered == 1
    assert s.per_class["neg"].recall == 0.8
    # neg recall 0.80 < its 0.90 bar → «no fiable» by name, even if the average looks fine.
    assert s.unreliable == ["neg"]
    assert 0.85 < s.macro_f1 < 0.95


def test_small_class_is_never_reliable() -> None:
    s = cs.score(["neg"] * 5 + ["pos"] * 10, ["neg"] * 5 + ["pos"] * 10)
    assert not s.per_class["neg"].reliable  # 5 < MIN_SUPPORT


def test_decision_needs_every_class_and_the_baseline() -> None:
    gold = ["pos"] * 10 + ["neg"] * 10 + ["neu"] * 10
    perfect = cs.score(gold, gold)
    worse = cs.score(gold, ["neu"] * 30)
    assert cs.decision(perfect, worse)["switch"] is True
    assert cs.decision(worse, perfect)["switch"] is False
    assert cs.decision(perfect, None)["switch"] is False  # no baseline, no switch


def test_slices_cover_sarcasm_emoji_country_and_origin() -> None:
    items = [
        _item("1", "neg", sarcasm=True, country="CO", source="real:bianki:comment"),
        _item("2", "pos", text="🔥🔥", country="VE", source="real:x:comment"),
        _item("3", "neu", source="public:instagram"),
    ]
    report = cs.sliced_scores(items, ["neg", "neu", "neu"])
    assert report["sarcasm"]["n"] == 1 and report["sarcasm"]["small"]
    assert report["emoji_only"]["accuracy"] == 0.0
    assert report["country:CO"]["n"] == 1 and report["country:desconocido"]["n"] == 1
    assert report["origin:real"]["n"] == 2 and report["origin:public"]["n"] == 1


def test_calibration_counts_missing_confidence_apart() -> None:
    report = cs.calibration(["pos", "neg", "neu"], ["pos", "pos", "neu"], [0.97, 0.96, None])
    assert report["with_confidence"] == 2 and report["without_confidence"] == 1
    top = report["bins"][-1]
    assert top["n"] == 2 and top["accuracy"] == 0.5
    assert report["ece"] == pytest.approx(0.465, abs=1e-3)


def test_percentile_and_latency() -> None:
    assert cs.percentile([], 50) is None
    assert cs.percentile([3.0, 1.0, 2.0], 50) == 2.0
    assert cs.percentile([float(i) for i in range(1, 21)], 95) == 19.0
    assert cs.latency_report([1.0, 2.0], 25)["p95_s"] == 2.0


def test_cache_report_flags_a_cache_that_is_never_read() -> None:
    assert cs.cache_report([0, 0, 0], [1500, 1500, 1500])["ok"] is False
    assert cs.cache_report([0], [1500])["checkable"] is False


# --- the kit -------------------------------------------------------------------------


def _items(n: int) -> list[cs.SentimentItem]:
    return [
        _item(f"pub-{i:04d}", split="test" if i % 2 else "dev", source="public:instagram")
        for i in range(n)
    ] + [
        _item(f"real-{i:04d}", split="test" if i % 2 else "dev", source="real:b:comment")
        for i in range(n // 2)
    ]


def test_plan_kit_overlap_is_shared_and_the_rest_is_split() -> None:
    items = _items(200)  # 300 items
    plan = cs.plan_kit(items, ("raul", "yesika"), overlap=100, seed=1)
    raul, yesika = (set(plan.assignments[n]) for n in ("raul", "yesika"))
    assert len(plan.overlap) == 100 and set(plan.overlap) <= raul & yesika
    assert raul & yesika == set(plan.overlap)
    assert raul | yesika == {it.id for it in items}
    assert len(raul) == len(yesika) == 200
    # the overlap is not only public, easy items
    assert any(i.startswith("real-") for i in plan.overlap)
    with pytest.raises(ValueError, match="overlap must be"):
        cs.plan_kit(items, ("raul", "yesika"), overlap=10, seed=1)


def test_sheet_is_blind_and_round_trips(tmp_path: Path) -> None:
    items = [_item("a", "pos", text="qué rico"), _item("b", text="¿precio?")]
    sheet = tmp_path / "s.csv"
    cs.write_sheet(sheet, items, seed=3)
    raw = sheet.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM: Excel reads the accents
    with sheet.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert tuple(rows[0]) == cs.SHEET_COLUMNS
    assert all(r[2] == "" for r in rows[1:])  # no label, no model output
    rows[1][2], rows[1][3], rows[2][2] = "POS", "si", "neu"
    with sheet.open("w", encoding="utf-8-sig", newline="") as fh:
        csv.writer(fh).writerows(rows)
    back = cs.read_sheet(sheet)
    assert {r.sentiment for r in back.values()} == {"pos", "neu"}
    assert any(r.sarcasm for r in back.values())


def test_read_sheet_refuses_a_typo(tmp_path: Path) -> None:
    sheet = tmp_path / "s.csv"
    sheet.write_text("id,comentario,sentimiento,sarcasmo,dudoso,nota\na,x,POSS,,,\n")
    with pytest.raises(ValueError, match="unknown sentimiento"):
        cs.read_sheet(sheet)


def _row(ident: str, label: str, *, sarcasm: bool = False) -> cs.SheetRow:
    return cs.SheetRow(id=ident, sentiment=label, sarcasm=sarcasm, doubtful=False, note="")


def test_merge_agreement_disagreement_and_adjudication() -> None:
    master = [_item(f"i{n}") for n in range(60)]
    raul = {f"i{n}": _row(f"i{n}", ["pos", "neg", "neu"][n % 3]) for n in range(60)}
    yesika = dict(raul)
    yesika["i0"] = _row("i0", "neu", sarcasm=True)
    result = cs.merge_labels(master, {"raul": raul, "yesika": yesika})
    by_id = {it.id: it for it in result.items}
    assert by_id["i0"].sentiment is None and by_id["i0"].sarcasm  # disagreement: empty
    assert by_id["i1"].sentiment == "neg"
    assert result.double_labeled == 60 and result.status == "passed"
    assert len(result.disagreements) == 1
    decided = cs.merge_labels(master, {"raul": raul, "yesika": yesika}, {"i0": "POS"})
    assert {it.id: it for it in decided.items}["i0"].sentiment == "pos"


def test_merge_is_pending_under_fifty_double_labels() -> None:
    master = [_item(f"i{n}") for n in range(10)]
    sheet = {f"i{n}": _row(f"i{n}", "pos" if n % 2 else "neg") for n in range(10)}
    assert cs.merge_labels(master, {"a": sheet, "b": sheet}).status == "pending"


def test_kit_public_set_matches_the_intent_set() -> None:
    kit = _module("sentiment_kit")
    intent = (REPO / "packages/api/eval_data/intent_golden_v1.jsonl").read_text().splitlines()
    items = kit.public_items(intent)
    assert len(items) == 408 and items[0].id == "pub-0001"
    assert all(it.sentiment is None for it in items)
    committed = cs.parse_sentiment_golden(
        (REPO / "packages/api/eval_data/sentiment_golden_v1.public.jsonl").read_text().splitlines()
    )
    assert [(i.id, i.text, i.split) for i in committed] == [(i.id, i.text, i.split) for i in items]


def test_kit_real_items_are_masked_deduplicated_and_split() -> None:
    kit = _module("sentiment_kit")
    rows = [
        {"business": "Bianki", "country": "VE", "kind": "comment", "text": "@ana qué rico"},
        {"business": "Bianki", "country": "VE", "kind": "comment", "text": "@luis qué rico"},
        {"business": "Bianki", "country": "VE", "kind": "comment", "text": "llegó frío"},
        {"business": "PuntoServis", "country": "CO", "kind": "comment", "text": "llegó frío"},
        {"business": "PuntoServis", "country": "CO", "kind": "comment", "text": "  "},
    ]
    items = kit.real_items(rows, target=200, max_per_business=80, seed=1)
    texts = sorted(it.text for it in items)
    assert texts == ["@usuario qué rico", "llegó frío", "llegó frío"]
    assert len({it.id for it in items}) == 3  # same text, two businesses: two ids
    assert {it.country for it in items} == {"VE", "CO"}
    assert all(it.split in ("dev", "test") for it in items)


def test_kit_refuses_to_write_real_comments_inside_the_repo() -> None:
    kit = _module("sentiment_kit")
    with pytest.raises(SystemExit, match="inside the repository"):
        kit._outside_repo(REPO / "packages" / "real.jsonl")
    assert kit._outside_repo(Path("/tmp/x.jsonl")).name == "x.jsonl"


def test_kit_build_and_merge_end_to_end(tmp_path: Path) -> None:
    kit = _module("sentiment_kit")
    out = tmp_path / "kit"
    assert kit.main(["build", "--public-only", "--dir", str(out)]) == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["items"] == 408 and manifest["overlap"] == 100
    assert manifest["sheets"]["raul"]["items"] == 100 + 154
    assert (out / "guia-etiquetado-sentimiento.md").exists()
    for name in ("raul", "yesika"):
        sheet = out / f"etiquetado_{name}.csv"
        with sheet.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        for r in rows[1:]:
            r[2] = "NEU"
        with sheet.open("w", encoding="utf-8-sig", newline="") as fh:
            csv.writer(fh).writerows(rows)
    code = kit.main(
        [
            "merge",
            "--dir",
            str(out),
            "--sheet",
            f"raul={out / 'etiquetado_raul.csv'}",
            "--sheet",
            f"yesika={out / 'etiquetado_yesika.csv'}",
        ]
    )
    report = json.loads((out / "acuerdo.json").read_text())
    # All-NEU from both: κ undefined (chance agreement 1) → not passed, exit 2.
    assert report["double_labeled"] == 100 and report["kappa_sentiment"] is None
    assert code == 2 and report["labelled"] == 408


def test_runner_sentiment_mode_scores_both_runs_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _module("run_experiment")
    labels = ["pos"] * 10 + ["neg"] * 10 + ["neu"] * 10
    golden = tmp_path / "golden.jsonl"
    rows = [
        json.dumps(
            {"id": f"r{i}", "text": f"t{i}", "split": "test", "sentiment": s, "country": "CO"}
        )
        for i, s in enumerate(labels)
    ]
    rows.append(json.dumps({"id": "u", "text": "sin etiqueta", "split": "test"}))
    golden.write_text("\n".join(rows) + "\n")

    def fake(predicted: list[str]) -> Any:
        def run(texts: list[str], *_: Any) -> dict[str, Any]:
            assert len(texts) == 30  # the unlabelled item is skipped
            return {
                "provenance": {"model_id": "fake"},
                "labels": predicted,
                "confidence": [0.9] * len(texts),
                "cost": {"usd": 0.0},
                "latency": cs.latency_report([1.0, 1.0], 25),
            }

        return run

    monkeypatch.setattr(runner, "_haiku_sentiment", fake(labels))
    monkeypatch.setattr(runner, "_robertuito_sentiment", fake(["neu"] * 30))
    monkeypatch.setenv("QUALIFY_ANTHROPIC_API_KEY", "sk-test")
    out = tmp_path / "results"
    code = runner.main(
        [
            "--env-file",
            str(tmp_path / "none.env"),
            "--sentiment",
            "--split",
            "test",
            "--golden-sentiment",
            str(golden),
            "--robertuito",
            "--out-dir",
            str(out),
        ]
    )
    assert code == 0
    report = json.loads(next(out.glob("*-sentiment-test.json")).read_text())
    assert report["items"] == 30 and report["unlabelled_skipped"] == 1
    assert report["decision"]["switch"] is True
    assert report["runs"]["robertuito"]["scores"]["macro_f1"] < 0.5
    assert report["runs"]["haiku"]["slices"]["country:CO"]["n"] == 30

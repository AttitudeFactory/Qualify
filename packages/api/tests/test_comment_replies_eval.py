"""ATENDER-4a (m-24848532): the measurement logic — κ, per-class bars, draft checks —
and the shape of the committed smoke set. Offline."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from qualify_api.assisted.grounding import GroundedProduct, Grounding
from qualify_api.evals.comment_replies import (
    MIN_SUPPORT,
    DraftResult,
    GoldenComment,
    Label,
    agreement,
    check_draft,
    cohen_kappa,
    evaluate_classifier,
    evaluate_drafts,
    evaluate_needs_reply_baseline,
    opening,
    parse_golden,
    parse_verdict,
    price_check,
    third_person_flags,
    top_opening,
)
from qualify_api.replies.triage import CommentKind, Sentiment, Triage

EVAL_DIR = Path(__file__).resolve().parents[1] / "evals" / "replies_ai"

POS_PRAISE = Label(Sentiment.POS, CommentKind.PRAISE, False)
NEG_COMPLAINT = Label(Sentiment.NEG, CommentKind.COMPLAINT, True)
NEU_QUESTION = Label(Sentiment.NEU, CommentKind.QUESTION, True)


def _g(label: Label, text: str = "x", **kw: object) -> GoldenComment:
    return GoldenComment(text=text, label=label, split="test", **kw)  # type: ignore[arg-type]


def _t(label: Label) -> Triage:
    return Triage(label.sentiment, label.kind, label.needs_reply)


# --- κ ---------------------------------------------------------------------------------


def test_kappa_known_values() -> None:
    assert cohen_kappa(list("aabb"), list("aabb")) == pytest.approx(1.0)
    # Classic 2x2: 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no → κ = 0.4.
    a = ["y"] * 25 + ["n"] * 25
    b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    assert cohen_kappa(a, b) == pytest.approx(0.4)
    assert cohen_kappa([], []) is None
    assert cohen_kappa(["a", "a"], ["a", "a"]) is None  # chance agreement is 1


def test_agreement_is_pending_until_enough_double_labels_then_judged() -> None:
    few = [_g(POS_PRAISE, second=POS_PRAISE)] * 10
    assert agreement(few).status == "pending"
    agreed = [_g(POS_PRAISE, second=POS_PRAISE), _g(NEG_COMPLAINT, second=NEG_COMPLAINT)] * 30
    assert agreement(agreed).status == "passed"
    split = [_g(POS_PRAISE, second=NEG_COMPLAINT), _g(NEG_COMPLAINT, second=POS_PRAISE)] * 30
    assert agreement(split).status == "failed"


# --- classifier bars -----------------------------------------------------------------


def _balanced() -> list[GoldenComment]:
    return [_g(lbl) for lbl in (POS_PRAISE, NEG_COMPLAINT, NEU_QUESTION) for _ in range(10)] + [
        _g(Label(Sentiment.NEU, CommentKind.OTHER, False)) for _ in range(10)
    ]


def test_perfect_predictions_pass_every_class() -> None:
    golden = _balanced()
    report = evaluate_classifier(
        golden, [_t(g.label) for g in golden], model_id="m", prompt_version="v"
    )
    assert report.status == "passed"
    assert report.unreliable == []
    assert report.to_json()["per_class"]["needs_reply"]["min_recall"] == 0.95


def test_missing_one_complaint_in_ten_fails_neg_and_needs_reply_bars() -> None:
    golden = _balanced()
    preds = [_t(g.label) for g in golden]
    # One complaint read as neutral «other»: neg recall 0.9 (bar 0.90, still ok) and
    # needs_reply recall 19/20 = 0.95 (ok); two of them break both bars.
    complaints = [i for i, g in enumerate(golden) if g.label is NEG_COMPLAINT]
    for i in complaints[:2]:
        preds[i] = Triage(Sentiment.NEU, CommentKind.OTHER, False)
    report = evaluate_classifier(golden, preds, model_id="m", prompt_version="v")
    assert "sentiment:neg" in report.unreliable
    assert "needs_reply" in report.unreliable
    assert report.status == "failed"


def test_a_class_with_too_few_examples_is_unreliable_even_when_perfect() -> None:
    golden = [_g(POS_PRAISE)] * (MIN_SUPPORT - 1)
    report = evaluate_classifier(
        golden, [_t(g.label) for g in golden], model_id="m", prompt_version="v"
    )
    assert "kind:praise" in report.unreliable


def test_unanswered_comment_counts_as_a_miss_and_fails() -> None:
    golden = _balanced()
    preds: list[Triage | None] = [_t(g.label) for g in golden]
    preds[0] = None
    report = evaluate_classifier(golden, preds, model_id="m", prompt_version="v")
    assert report.unanswered == 1 and report.status == "failed"


def test_baseline_scores_only_needs_reply() -> None:
    golden = _balanced()
    flags = [g.label is NEU_QUESTION for g in golden]  # intent misses every complaint
    report = evaluate_needs_reply_baseline(golden, flags, model_id="m", version="intent-v2")
    metrics = report.per_class["needs_reply"]
    assert metrics.recall == pytest.approx(0.5)
    assert report.status == "failed"


# --- draft checks --------------------------------------------------------------------

CATALOG = Grounding(
    business_name="La Arepera de Rosa",
    products=(
        GroundedProduct(
            "Arepa de queso", "$8.000 COP", price_amount=Decimal("8000"), currency="COP"
        ),
    ),
)


def test_price_check_catalog_declined_and_fail() -> None:
    assert price_check("La arepa de queso cuesta $8.000", grounding=CATALOG, asks_price=True) == (
        "catalog"
    )
    assert price_check("Cuesta $9.500", grounding=CATALOG, asks_price=True) == "fail"
    assert (
        price_check("Te escribimos por mensaje privado", grounding=CATALOG, asks_price=True)
        == "declined"
    )
    assert price_check("¡Está muy rica!", grounding=CATALOG, asks_price=True) == "fail"
    assert price_check("¡Gracias!", grounding=CATALOG, asks_price=False) == "n/a"


def test_third_person_flags() -> None:
    assert third_person_flags("El negocio te contactará pronto")
    assert third_person_flags("La Arepera de Rosa agradece tu visita", "La Arepera de Rosa")
    assert third_person_flags("¡Gracias! Te escribimos por mensaje privado") == []


def test_invented_data_is_flagged_for_the_reviewer() -> None:
    golden = _g(NEU_QUESTION, text="¿horario?")
    result = check_draft(
        text="Abrimos de 8 am a 6 pm, escríbenos al 300 123 4567",
        comment=golden,
        grounding=CATALOG,
        model_id="m",
        prompt_version="v",
        cost_usd=0.0001,
    )
    assert "hour" in result.invented_flags and "phone" in result.invented_flags


def _draft(label: Label, *, usable: bool | None, **kw: object) -> DraftResult:
    return DraftResult(
        text=str(kw.get("text", "¡Gracias!")),
        comment=_g(label),
        model_id="m",
        prompt_version="v",
        cost_usd=0.0001,
        price="n/a",
        usable=usable,
        invented=kw.get("invented", False if usable is not None else None),  # type: ignore[arg-type]
        third_person=False if usable is not None else None,
        promises_or_admits=kw.get(  # type: ignore[arg-type]
            "promises_or_admits", False if usable is not None else None
        ),
    )


def _varied(label: Label, n: int, *, usable: bool, **kw: object) -> list[DraftResult]:
    return [
        _draft(label, usable=usable, text=f"Respuesta distinta {i} {label.kind}", **kw)
        for i in range(n)
    ]


def test_drafts_pending_until_a_person_reviews_every_one() -> None:
    assert evaluate_drafts([_draft(POS_PRAISE, usable=None)]).status == "pending"


def test_drafts_pass_and_fail_on_the_usable_bars() -> None:
    good = (
        _varied(POS_PRAISE, 10, usable=True)
        + _varied(NEG_COMPLAINT, 4, usable=True)
        + _varied(NEG_COMPLAINT, 1, usable=False)
    )
    assert evaluate_drafts(good).status == "passed"  # neg 0.80 meets its bar
    bad = _varied(POS_PRAISE, 8, usable=True) + _varied(POS_PRAISE, 2, usable=False)
    assert evaluate_drafts(bad).status == "failed"  # pos 0.80 < 0.90


def test_one_invented_draft_fails_everything() -> None:
    drafts = _varied(POS_PRAISE, 9, usable=True) + [_draft(POS_PRAISE, usable=True, invented=True)]
    assert evaluate_drafts(drafts).status == "failed"


def test_one_draft_that_promises_or_admits_fails_everything() -> None:
    drafts = _varied(POS_PRAISE, 9, usable=True) + [
        _draft(NEG_COMPLAINT, usable=True, promises_or_admits=True, text="Tienes razón")
    ]
    report = evaluate_drafts(drafts)
    assert report.promises_or_admits == 1 and report.status == "failed"


def test_a_repeated_opening_fails_from_ten_drafts_on() -> None:
    same = [
        _draft(POS_PRAISE, usable=True, text=f"¡Gracias por escribirnos! Nota {i}")
        for i in range(3)
    ]
    drafts = _varied(POS_PRAISE, 7, usable=True) + same
    report = evaluate_drafts(drafts)
    assert report.top_opening == "gracias por escribirnos"
    assert report.top_opening_share == 0.3 and report.status == "failed"
    # Two of ten (20 %) is still within the bar; below ten drafts it is not checked.
    assert evaluate_drafts(_varied(POS_PRAISE, 8, usable=True) + same[:2]).status == "passed"
    assert evaluate_drafts(same).status == "passed"


def test_opening_ignores_case_punctuation_and_emoji() -> None:
    assert opening("¡Qué BUENO que te gustó! 🙏") == "qué bueno que"
    assert top_opening(["", "Hola a ti", "hola, a ti también"]) == ("hola a ti", 1.0)


def test_parse_verdict() -> None:
    assert parse_verdict("Sí") is True and parse_verdict("no") is False
    assert parse_verdict("") is None


# --- golden file contract ------------------------------------------------------------


def test_golden_rejects_a_complaint_without_reply_and_bad_split() -> None:
    line = {"text": "llegó frío", "sentiment": "neg", "kind": "complaint", "split": "test"}
    with pytest.raises(ValueError, match="always needs a reply"):
        parse_golden([json.dumps({**line, "needs_reply": False})])
    with pytest.raises(ValueError, match="split"):
        parse_golden([json.dumps({**line, "needs_reply": True, "split": "train"})])


def test_smoke_set_is_synthetic_balanced_and_has_catalogs() -> None:
    items = parse_golden(
        (EVAL_DIR / "synthetic_smoke.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert items and all(g.synthetic for g in items)
    catalogs = json.loads((EVAL_DIR / "catalogs.json").read_text(encoding="utf-8"))
    assert {g.business for g in items} <= set(catalogs)
    test = [g for g in items if g.split == "test"]
    for s in Sentiment:
        assert sum(1 for g in test if g.label.sentiment is s) >= MIN_SUPPORT
    for k in CommentKind:
        assert sum(1 for g in test if g.label.kind is k) >= MIN_SUPPORT
    # The three target markets are all present.
    assert {g.source for g in items} == {"synthetic:co", "synthetic:ve", "synthetic:uy"}

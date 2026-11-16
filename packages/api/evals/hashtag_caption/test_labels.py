"""Offline checks of the labeler (README «Reglas de etiquetado»). No API calls:

uv run --no-sync pytest packages/api/evals/hashtag_caption/test_labels.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_eval  # noqa: E402

DATA = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
LEX = json.loads((HERE / "lexicon.json").read_text(encoding="utf-8"))
LABELER = run_eval.Labeler(DATA["cases"], LEX)
WATCHED = {run_eval.clean(w["tag"]) for w in DATA["watched"]}


@pytest.mark.parametrize(
    ("case", "tag", "expected"),
    [
        ("c32", "yaalashawarma", "competidor"),  # another business, even on a shawarma text
        ("c32", "parati", "relleno"),
        ("c32", "viralvideo", "relleno"),
        ("c32", "barquisimeto", "otro_lugar"),
        ("c32", "shawarmabarquisimeto", "otro_lugar"),
        ("c34", "sancristobal", "otro_lugar"),  # the juice text is in Barquisimeto
        ("c34", "barquisimeto", "encaja"),
        ("c32", "recetasfaciles", "vigilada_no_encaja"),
        ("c32", "probandocomida", "encaja"),  # a first-bite reaction text
        ("c20", "ensalada", "vigilada_no_encaja"),  # no salad in that text
        ("c15", "ensaladasaludable", "encaja"),
        ("c32", "foodtok", "aceptable"),  # watched, broad
        ("c30", "comidasaludable", "vigilada_no_encaja"),  # the video-game control
        ("c30", "comidarapida", "no_encaja"),
        ("c30", "godotengine", "encaja"),
        ("c20", "cafedeespecialidad", "no_encaja"),  # no coffee in that text
        ("c00", "cafedeespecialidad", "encaja"),
        ("c26", "comidanocturna", "encaja"),
        ("c20", "shawarmasancristobal", "encaja"),
        ("c20", "tachira_venezuela", "encaja"),  # a place of the text, not a watched tag
    ],
)
def test_label(case: str, tag: str, expected: str) -> None:
    assert LABELER.label(case, tag, WATCHED) == expected


def test_split_is_fixed_and_balanced() -> None:
    splits = [c["split"] for c in DATA["cases"]]
    assert splits.count("dev") == 18
    assert splits.count("test") == 16
    assert len({c["id"] for c in DATA["cases"]}) == len(DATA["cases"])


def test_no_identifying_strings() -> None:
    raw = (HERE / "cases.json").read_text(encoding="utf-8").lower()
    for leaked in ("korner", "bianki", "agustinos", "machiri", "+58", "424"):
        assert leaked not in raw


def test_watched_is_the_products_top_20() -> None:
    watched = DATA["watched"]
    # readable_tag (m-25032581) keeps the flag-carrying spelling out of the model's list
    assert all(w["tag"].isascii() for w in watched)
    assert len(watched) == 20
    order = [(-w["posts"], -w["views"]) for w in watched]
    assert order == sorted(order)
    assert not {w["tag"] for w in watched} & set(DATA["rubro_tags"])


def test_broad_region_and_text_named_brands() -> None:
    assert LABELER.label("c16", "shawarmaenlatinoamerica", WATCHED) == "aceptable"
    assert LABELER.label("c16", "comidamedellin", WATCHED) == "otro_lugar"
    assert LABELER.label("c61", "bancolombia", WATCHED) == "aceptable"  # named in the text
    assert LABELER.label("c48", "pedidosya", WATCHED) == "competidor"
    assert LABELER.label("c32", "sancrystobal", WATCHED) == "mal_escrita"
    assert LABELER.label("c30", "almuerzo", WATCHED) == "no_encaja"  # the video-game control

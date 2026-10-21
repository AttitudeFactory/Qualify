"""The committed intent golden set (m-24789644) stays usable and anonymous: it parses,
every class has examples on both sides of the dev/test split, and no comment text keeps a
username (mentions are masked as @usuario at collection time)."""

from __future__ import annotations

import re
from pathlib import Path

from qualify_api.intent import IntentClass
from qualify_api.intent.eval import parse_golden

GOLDEN = Path(__file__).resolve().parents[1] / "eval_data" / "intent_golden_v1.jsonl"


def _items():  # type: ignore[no-untyped-def]
    return parse_golden(GOLDEN.read_text(encoding="utf-8").splitlines())


def test_the_golden_set_parses_and_only_uses_dev_and_test() -> None:
    items = _items()

    assert len(items) >= 400
    assert {item.split for item in items} == {"dev", "test"}


def test_every_class_appears_in_both_splits() -> None:
    for split in ("dev", "test"):
        present = {label for item in _items() if item.split == split for label in item.labels}
        assert present == set(IntentClass), split


def test_no_comment_text_keeps_a_username() -> None:
    leaked = [
        item.text
        for item in _items()
        if any(m != "@usuario" for m in re.findall(r"@[A-Za-z0-9._]+", item.text))
    ]

    assert leaked == []

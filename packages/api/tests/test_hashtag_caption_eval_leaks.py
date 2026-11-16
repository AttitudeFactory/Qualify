"""m-25032581 review: the caption-hashtags eval (`packages/api/evals/hashtag_caption`) is
outside pytest's `testpaths`, so its leak guard runs here — over the committed cases,
weekly snapshot, lexicon and results — and fails CI if any names the pilot business, its
venue or the people around it. The guarded words are digests only (`leak_guard`)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

EVAL = Path(__file__).resolve().parents[1] / "evals" / "hashtag_caption"


def _guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hashtag_caption_leak_guard", EVAL / "leak_guard.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARD = _guard()
FILES = GUARD.committed_files()


def test_the_guard_covers_every_committed_data_file() -> None:
    names = {path.name for path in FILES}
    assert {"cases.json", "weekly_snapshot.json", "lexicon.json"} <= names
    assert any(path.parent.name == "results" for path in FILES)
    assert all(path.is_file() for path in FILES)


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
def test_no_committed_eval_file_names_the_pilot(path: Path) -> None:
    assert GUARD.leaks(path.read_text(encoding="utf-8")) == set()


def test_the_guard_catches_a_word_inside_a_tag_and_across_two_tokens() -> None:
    # built from the digests' own lengths, without writing a guarded word: a clean text
    # never matches, and the matcher is the one the files are checked with
    assert GUARD.leaks("#shawarmasancristobal ensaladas frescas") == set()
    assert sorted({length for length, _ in GUARD.GUARDED}) == [6, 7, 9]

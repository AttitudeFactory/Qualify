"""The eval's leak guard: no committed file of this folder names the pilot business, its
venue or the people around it. The guarded words are kept only as sha256 digests of
their lowercase spelling, so the guard itself never writes them in clear.

How it matches, deterministically: the text is accent-folded and lowercased, split into
`[a-z0-9]+` tokens, and every token and every pair of adjacent tokens joined (`san
cristobal` → `sancristobal`) is scanned for every substring of a guarded length — so a
guarded word inside a hashtag (`#<word>shawarma`) is caught too.

Run by `test_labels.py` here and, in CI, by `packages/api/tests/test_hashtag_caption_eval_leaks.py`.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: (length, sha256 of the lowercase word): the business, the venue and two names.
GUARDED: frozenset[tuple[int, str]] = frozenset(
    {
        (6, "320e658730a3fe3936bb541e7ff09a614e453dee163e4be4c95a17665075c2ed"),
        (6, "d1db75a841960b759e46065e6c7c32242717b40cf97b96e18eb28fe52196daf1"),
        (9, "1c154ba6a9d4addff7d57c4ff92177377a113e693274878242f84376377f94a3"),
        (7, "ef4be68ef73f983145bd0385cef97c537a830a5a98dd340e73302ff28a8d1629"),
    }
)
_LENGTHS = sorted({length for length, _ in GUARDED})
_DIGESTS = {digest for _, digest in GUARDED}
_TOKEN = re.compile(r"[a-z0-9]+")


#: The folder's text files the guard reads; the guard itself (its digests) is not one.
_TEXT_SUFFIXES = frozenset({".json", ".md", ".py", ".txt", ".csv"})


def committed_files() -> list[Path]:
    """Every text file of this folder (cases, snapshot, lexicon, README, the scripts, the
    labeler test) and of `results/`, except this guard."""
    files = [
        path
        for path in [*HERE.iterdir(), *(HERE / "results").glob("*")]
        if path.is_file() and path.suffix in _TEXT_SUFFIXES and path.name != Path(__file__).name
    ]
    return sorted(files)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _candidates(tokens: list[str]) -> Iterable[str]:
    yield from tokens
    yield from (a + b for a, b in zip(tokens, tokens[1:], strict=False))


def leaks(text: str) -> set[str]:
    """The digests of the guarded words found in `text` (empty when clean)."""
    found: set[str] = set()
    for candidate in _candidates(_TOKEN.findall(_fold(text))):
        for length in _LENGTHS:
            for start in range(len(candidate) - length + 1):
                piece = candidate[start : start + length]
                digest = hashlib.sha256(piece.encode()).hexdigest()
                if digest in _DIGESTS:
                    found.add(digest)
    return found

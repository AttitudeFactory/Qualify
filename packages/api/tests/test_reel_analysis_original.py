"""The stored original of an analysed reel, read by byte range (m-24992893), offline:
`reel_analysis_original` rebuilds the key through the door's own builder, answers a
size and a range over an in-memory R2 behind the real public door, gives None for
anything it cannot read, and calls only `public_size` / `open_public_range`."""

from __future__ import annotations

import ast
import io
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from qualify_shared.objects.gate import ObjectNotFound
from qualify_shared.objects.public import PublicObjectGate, reel_source_key

from qualify_api.referentes import reel_analysis_original as ro

ANALYSIS_ID = UUID("0b9a1c2d-3e4f-4a5b-8c6d-7e8f9a0b1c2d")
POST = "DQx9abc_12"
KEY = reel_source_key("instagram", POST, ANALYSIS_ID)


class R2:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.sizes = 0

    def _get(self, key: str) -> bytes:
        if key not in self.objects:
            raise ObjectNotFound(key)
        return self.objects[key]

    def size(self, key: str) -> int:
        self.sizes += 1
        return len(self._get(key))

    def open_range(self, key: str, start: int, end: int) -> io.BytesIO:
        return io.BytesIO(self._get(key)[start : end + 1])


@pytest.fixture(autouse=True)
def _fresh_sizes() -> Iterator[None]:
    ro.clear_size_cache()
    yield
    ro.clear_size_cache()


def test_the_key_is_rebuilt_by_the_door_or_none() -> None:
    assert ro.source_key("instagram", POST, ANALYSIS_ID) == KEY
    assert ro.source_key("youtube", POST, ANALYSIS_ID) is None
    assert ro.source_key("instagram", "../x", ANALYSIS_ID) is None


def test_size_and_range_of_the_stored_copy() -> None:
    store = R2()
    store.objects[KEY] = b"0123456789"
    gate = PublicObjectGate(store)  # type: ignore[arg-type]
    assert ro.source_size("instagram", POST, ANALYSIS_ID, gate=gate) == 10
    assert ro.source_size("instagram", POST, ANALYSIS_ID, gate=gate) == 10
    assert store.sizes == 1  # the copy never changes under its key: remembered
    assert ro.read_source_range("instagram", POST, ANALYSIS_ID, 2, 5, gate=gate) == b"2345"


def test_a_missing_copy_or_a_bad_range_is_none_and_not_remembered() -> None:
    store = R2()
    gate = PublicObjectGate(store)  # type: ignore[arg-type]
    assert ro.source_size("instagram", POST, ANALYSIS_ID, gate=gate) is None
    assert ro.read_source_range("instagram", POST, ANALYSIS_ID, 0, 9, gate=gate) is None
    assert ro.read_source_range("instagram", POST, ANALYSIS_ID, 5, 2, gate=gate) is None
    store.objects[KEY] = b"abc"
    assert ro.source_size("instagram", POST, ANALYSIS_ID, gate=gate) == 3


def test_a_purged_copy_is_forgotten() -> None:
    store = R2()
    store.objects[KEY] = b"abc"
    gate = PublicObjectGate(store)  # type: ignore[arg-type]
    assert ro.source_size("instagram", POST, ANALYSIS_ID, gate=gate) == 3
    del store.objects[KEY]
    assert ro.read_source_range("instagram", POST, ANALYSIS_ID, 0, 2, gate=gate) is None
    assert ro.source_size("instagram", POST, ANALYSIS_ID, gate=gate) is None


def test_an_r2_failure_is_none_never_an_error() -> None:
    class Broken(R2):
        def size(self, key: str) -> int:
            raise TimeoutError("slow")

        def open_range(self, key: str, start: int, end: int) -> io.BytesIO:
            raise TimeoutError("slow")

    gate = PublicObjectGate(Broken())  # type: ignore[arg-type]
    assert ro.source_size("instagram", POST, ANALYSIS_ID, gate=gate) is None
    assert ro.read_source_range("instagram", POST, ANALYSIS_ID, 0, 1, gate=gate) is None


def test_the_module_only_reads_the_public_door_by_range() -> None:
    tree = ast.parse(Path(ro.__file__).read_text(encoding="utf-8"))
    door = {
        "put_public",
        "put_public_if_absent",
        "open_public",
        "public_size",
        "open_public_range",
        "delete_public_prefix",
        "delete_public_object",
    }
    calls = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in door}
    assert calls == {"public_size", "open_public_range"}

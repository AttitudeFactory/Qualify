"""The hand-made Lottie files (`assets/lottie/`) vs their generator (`ui/lottie_shapes.py`).

Pins:
1. Every committed file equals the generator's output byte for byte — the JSON can never
   drift from the code that explains it (regenerate with `python -m Qualify.ui.lottie_shapes`).
2. Budget: each file ≤ 50 KB (docs/ux-post-journey-termico.md §3); in practice < 10 KB.
3. Shape layers only (`ty: 4`), no external assets, no expressions — what the light
   build of the engine draws.
4. Every colour in a file is a design-token colour (Radix step 9 of a tone's scale).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from .ui.lottie_shapes import ANIMATIONS, ASSETS_DIR, TONE_HEX, render

BUDGET_BYTES = 50 * 1024


def _walk(node: Any):
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _token_rgb() -> set[tuple[float, float, float]]:
    out = set()
    for hex_colour in TONE_HEX.values():
        h = hex_colour.lstrip("#")
        out.add(tuple(round(int(h[i : i + 2], 16) / 255, 4) for i in (0, 2, 4)))
    return out


@pytest.mark.parametrize("name", sorted(ANIMATIONS))
def test_committed_file_matches_generator(name: str) -> None:
    path = ASSETS_DIR / f"{name}.json"
    assert path.is_file(), f"missing {path}; run python -m Qualify.ui.lottie_shapes"
    assert path.read_text(encoding="utf-8") == render(name), (
        f"{path.name} drifted from lottie_shapes.{name}(); regenerate it"
    )


@pytest.mark.parametrize("name", sorted(ANIMATIONS))
def test_file_is_within_budget(name: str) -> None:
    assert (ASSETS_DIR / f"{name}.json").stat().st_size <= BUDGET_BYTES


@pytest.mark.parametrize("name", sorted(ANIMATIONS))
def test_shape_layers_only_no_assets_no_expressions(name: str) -> None:
    data = ANIMATIONS[name]()
    assert data["assets"] == []
    assert data["layers"], name
    for layer in data["layers"]:
        assert layer["ty"] == 4, (name, layer.get("nm"))
    for node in _walk(data):
        if isinstance(node, dict):
            assert "x" not in node or not isinstance(node["x"], str), "expression found"


@pytest.mark.parametrize("name", sorted(ANIMATIONS))
def test_every_colour_is_a_token(name: str) -> None:
    allowed = _token_rgb()
    for node in _walk(ANIMATIONS[name]()):
        if isinstance(node, dict) and node.get("ty") in ("fl", "st"):
            r, g, b, a = node["c"]["k"]
            assert (r, g, b) in allowed, (name, node["c"]["k"])
            assert a == 1


def test_thaw_is_freeze_played_backwards() -> None:
    """Same length, same layers, same colours; the keyframes mirrored in time."""
    from .ui.lottie_shapes import freeze, thaw

    fwd, back = freeze(), thaw()
    assert back["op"] == fwd["op"] and len(back["layers"]) == len(fwd["layers"])

    def first_animated(node: Any):
        for n in _walk(node):
            if isinstance(n, dict) and n.get("a") == 1:
                return n["k"]
        raise AssertionError("no animated property")

    f_keys, b_keys = first_animated(fwd), first_animated(back)
    assert [k["t"] for k in b_keys] == [fwd["op"] - k["t"] for k in reversed(f_keys)]
    assert [k["s"] for k in b_keys] == [k["s"] for k in reversed(f_keys)]


def test_no_stray_files_in_assets_dir() -> None:
    names = {p.stem for p in ASSETS_DIR.glob("*.json")}
    assert names == set(ANIMATIONS), names
    assert (ASSETS_DIR / "LICENSES.md").is_file()


def test_generator_is_deterministic(tmp_path: Path) -> None:
    from .ui.lottie_shapes import write_all

    written = write_all(tmp_path)
    assert {p.name for p in written} == {f"{n}.json" for n in ANIMATIONS}
    for p in written:
        json.loads(p.read_text(encoding="utf-8"))
        assert p.read_text(encoding="utf-8") == render(p.stem)

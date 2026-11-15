"""m-25017292: the layer stage's catalog (`qualify_creative/layer_spec/catalog_v1.json`) and
the render's (`packages/render/templates/layer_still/manifest.json` `layer_catalog`) carry the
same numbers. Two copies of one table drift; a LayerSpec the Python schema accepts and the
render's `spec.mjs` refuses is that drift — this test is the one place that catches it.

The two keep different key names (the render adds geometry the stage never reads); the test
compares only what both decide: layouts, formats, anchors, which parameters a layout takes,
every text slot's character and line limit, the data blocks (kinds, counts, value limits,
fixed labels), the highlight icons and the catalog version."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from qualify_creative.layer_spec import catalog

MANIFEST = (
    Path(__file__).resolve().parents[2] / "render" / "templates" / "layer_still" / "manifest.json"
)


@pytest.fixture(scope="module")
def render() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text("utf-8"))["layer_catalog"]


def _slots(slots: dict[str, Any]) -> dict[str, dict[str, list[int]]]:
    """Slot → format → [chars, lines], without the formats a slot does not have."""
    return {
        slot: {fmt: list(limit) for fmt, limit in (by_format or {}).items() if limit}
        for slot, by_format in slots.items()
        if any(by_format.values() if by_format else ())
    }


def test_same_catalog_version(render: dict[str, Any]) -> None:
    assert catalog()["layout_version"] == render["layout_version"]


def test_same_layouts_formats_and_parameters(render: dict[str, Any]) -> None:
    ours, theirs = catalog()["layouts"], render["layouts"]
    assert set(ours) == set(theirs)
    for layout_id, layout in ours.items():
        other = theirs[layout_id]
        assert layout["formats"] == other["formats"], layout_id
        assert set(layout["anchors"]) == set(other["anchors"]), layout_id
        for flag in ("container_color", "accent_word", "price"):
            assert layout[flag] == other[flag], (layout_id, flag)


def test_same_text_limits(render: dict[str, Any]) -> None:
    for layout_id, layout in catalog()["layouts"].items():
        other = render["layouts"][layout_id]
        assert _slots(layout["slots"]) == _slots(other["slots"]), layout_id
        # a script title face (2026-11-15): both sides lower the same titles the same way
        assert layout.get("script_title") == other.get("script_title"), layout_id


def test_same_script_families(render: dict[str, Any]) -> None:
    assert catalog()["script_families"] == render["script_families"]


def test_same_data_blocks(render: dict[str, Any]) -> None:
    for layout_id, layout in catalog()["layouts"].items():
        other = render["layouts"][layout_id]
        assert layout["info_kinds"] == other.get("kinds", []), layout_id
        if not layout.get("info_blocks"):
            assert "blocks" not in other, layout_id
            continue
        for fmt, bounds in layout["info_blocks"].items():
            assert [bounds["min"], bounds["max"], bounds["max_with_photo"]] == other["blocks"][
                fmt
            ], (layout_id, fmt)
        assert {f: list(v) for f, v in layout["info_value"].items()} == other["value"], layout_id
    labels = {kind: block["label"] for kind, block in catalog()["info_blocks"].items()}
    assert labels == {kind: block["label"] for kind, block in render["info_kinds"].items()}


def test_same_highlight_icons(render: dict[str, Any]) -> None:
    assert catalog()["layouts"]["highlight_circle"]["icon_ids"] == render["highlight_icons"]
    assert (
        catalog()["layouts"]["highlight_circle"]["highlight_word"][0]
        == (render["layouts"]["highlight_circle"]["word_max"])
    )

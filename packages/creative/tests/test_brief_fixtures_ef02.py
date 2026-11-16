"""EF-02 (ADR 50 §1.6): briefs stored before the effects recipe keep reading.

`fixtures/briefs_f55f1d73/` holds one brief of each `ContentKind` (plus a reel replica,
a part's child clip and a video by parts with its plan) serialized by main `f55f1d73`
BEFORE the recipe fields existed. Each must validate unchanged, dump back to exactly the
same JSON plus the new fields at their «nothing» defaults, and keep
`effects_pipeline_version` at 0 — so it is produced byte for byte as before. Offline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from qualify_creative.enums import ContentKind
from qualify_creative.schemas import ContentBrief

FIXTURES = Path(__file__).parent / "fixtures" / "briefs_f55f1d73"

#: The recipe fields EF-02 added (ED-15: `text_layers` in place of `text_layer`), with the
#: default every older brief reads.
_RECIPE_DEFAULTS: dict[str, Any] = {
    "effects": [],
    "text_layers": [],
    "segments": [],
    "mode_rule_version": 0,
    "mode_reason": "",
    "mode_changed_by_owner": False,
}
_MEDIA_DEFAULTS = {**_RECIPE_DEFAULTS, "effects_pipeline_version": 0, "video_recipe": None}
_PLAN_DEFAULTS = {**_RECIPE_DEFAULTS, "transition_in": None}
#: Brief fields main added after the fixtures were taken (`awareness_level`, 94fa4556).
_LATER_BRIEF_DEFAULTS: dict[str, Any] = {"awareness_level": None}


def _without(fields: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    for name, default in fields.items():
        assert data.get(name) == default, name
    return {k: v for k, v in data.items() if k not in fields}


def _as_before(dumped: dict[str, Any]) -> dict[str, Any]:
    """`dumped` with the EF-02 fields taken out — each checked to be its default."""
    media = _without(_MEDIA_DEFAULTS, dumped["media"])
    media["parts"] = [_without(_PLAN_DEFAULTS, p) for p in media["parts"]]
    media["parts_removed"] = [_without(_PLAN_DEFAULTS, p) for p in media["parts_removed"]]
    if media["part"] is not None:
        media["part"] = _without(_RECIPE_DEFAULTS, media["part"])
    # fields main added after f55f1d73, outside the recipe, read at their defaults too
    later = _without(_LATER_BRIEF_DEFAULTS, dumped)
    return {**later, "media": media}


def _fixtures() -> list[Path]:
    return sorted(FIXTURES.glob("*.json"))


def test_there_is_a_fixture_of_every_kind() -> None:
    kinds = {json.loads(p.read_text(encoding="utf-8"))["kind"] for p in _fixtures()}
    assert kinds == {kind.value for kind in ContentKind}


@pytest.mark.parametrize("path", _fixtures(), ids=lambda p: p.stem)
def test_a_brief_from_before_the_recipe_reads_unchanged(path: Path) -> None:
    stored = json.loads(path.read_text(encoding="utf-8"))
    for context in (None, {"preserve_stored_logo_mode": True}):
        brief = ContentBrief.model_validate(stored, context=context)
        assert brief.media.effects_pipeline_version == 0
        assert _as_before(brief.model_dump(mode="json")) == stored

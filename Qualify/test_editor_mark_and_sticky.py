"""m-25026638, from the live test of ED-07 on 3140:

- the «Parte con IA 1 · se crea al tocar «Crear»» mark broke into 5–6 lines over the ▶
  button: anchored at `left: 50%` with no right edge, an absolute box can only be half
  its frame wide. Now a capsule in the frame's top-left corner (the signed mockup's
  `.preview__ai`), at most two lines cut with «…», its full words in its name;
- the editor's sticky preview hid behind the step's own sticky head at 1366×900: it is
  pinned under it now (`--q-sticky-header-height`, measured by `glass-nav.js`)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import reflex as rx

from . import ai_block_vm as ai_vm
from .ui import edit_preview

_ROOT = Path(__file__).resolve().parent.parent
_CSS = (_ROOT / "assets" / "qualify-creative.css").read_text(encoding="utf-8")
_JS = (_ROOT / "assets" / "edit-preview.js").read_text(encoding="utf-8")
_NAV = (_ROOT / "assets" / "glass-nav.js").read_text(encoding="utf-8")
_NODE = shutil.which("node")


def _rule(selector: str, css: str = _CSS) -> str:
    """The body of the first rule whose selector is exactly `selector`."""
    match = re.search(r"(?:^|\n)\s*" + re.escape(selector) + r" \{([^}]*)\}", css)
    assert match, selector
    return match.group(1)


def test_the_mark_is_a_corner_capsule_never_half_the_frame() -> None:
    rule = _rule(".q-edit-seq__ai")
    assert "left: 50%" not in rule and "translateX(-50%)" not in rule
    assert "top: 8px;" in rule and "left: 8px;" in rule
    assert "max-width: calc(100% - 16px);" in rule
    assert "pointer-events: none;" in rule  # the ▶ under it keeps its clicks
    words = _rule(".q-edit-seq__ai [data-edit-seq-ai-text]")
    assert "-webkit-line-clamp: 2;" in words and "overflow: hidden;" in words
    assert "min-width: 0;" in words
    # the shared look stays the signed one: the ring and the dark fill (§5.10.1)
    mark = _rule(".q-ai-mark")
    assert "box-shadow: inset 0 0 0 1px var(--q-ai-ring);" in mark
    # still hidden while the clock is not on an AI part
    assert ".q-edit-seq__ai:not([data-on]) { display: none; }" in _CSS


def test_a_narrow_frame_shows_the_mark_s_name_alone() -> None:
    """UX review: at ~81 px the frame said «✦ Parte…». Under 9rem the rest hides and
    «✦ Parte con IA 1» stays — the signed words cut at « · », never a new short form."""
    narrow = _CSS[_CSS.index("@container (max-width: 9rem) {") :]
    assert narrow.startswith(
        "@container (max-width: 9rem) {\n  .q-edit-seq__ai .q-edit-seq__ai-rest { display: none; }"
    )
    # the frame is the nearest size container (its base rule, not the wide override)
    frame = _CSS[_CSS.index(".q-edit-preview__frame {\n  position: relative;") :]
    assert "container-type: inline-size;" in frame[: frame.index("}")]
    assert "c.aiMarkParts(said)" in _JS


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_the_mark_splits_at_its_name() -> None:
    assert _NODE is not None
    said = ai_vm.PREVIEW_MARK.format(n=1)
    script = (
        f"const c = require({json.dumps(str(_ROOT / 'assets' / 'edit-sequence-core.js'))});"
        f"console.log(JSON.stringify([c.aiMarkParts({json.dumps(said)}),"
        " c.aiMarkParts(''), c.aiMarkParts('Parte con IA 2')]));"
    )
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    assert json.loads(out.stdout) == [
        {"name": "Parte con IA 1", "rest": " · se crea al tocar «Crear»"},
        {"name": "", "rest": ""},
        {"name": "Parte con IA 2", "rest": ""},
    ]


def test_with_a_field_focused_the_mark_hides_and_the_preview_stays_under_the_head() -> None:
    focus = _CSS[_CSS.index("@container edit-host (max-width: 45.99rem) {") :]
    focus = focus[: focus.index("\n}\n")]
    has = ".q-edit:has(.q-edit__main input:focus, .q-edit__main textarea:focus)"
    assert has + " .q-edit-seq__ai {\n    display: none;" in focus
    # no `top: 0` with the focus: that would put the preview back behind the step head
    assert "top: 0" not in focus


def test_the_mark_keeps_its_full_words_as_its_name() -> None:
    assert 'aiMark.setAttribute("aria-label", said)' in _JS
    assert 'aiMark.removeAttribute("aria-label")' in _JS
    # no tooltip: with `pointer-events: none` it would never show
    assert '"title"' not in _JS[_JS.index("ED-07 (m-25026638): a «parte con IA»") :][:1500]
    preview = str(
        edit_preview.edit_sequence_preview(
            sequence=rx.Var.create("{}"),
            texts=rx.Var.create([]).to(list[dict[str, str]]),
            effects=rx.Var.create([]).to(list[dict[str, str]]),
            slower=rx.Var.create(False),
            on_duration=lambda *a: rx.console_log("d"),
            on_time=lambda *a: rx.console_log("t"),
            note_text="",
            broken_text="",
            slower_text="",
            play_label="",
            pause_label="",
            sound_label="",
            mute_label="",
            region_label="",
            ai_mark=rx.Var.create(True),
        )
    )
    assert '"q-ai-mark q-edit-seq__ai","data-edit-seq-ai":"",role:"img"' in preview
    assert '"data-edit-seq-ai-name":""' in preview
    assert '"q-edit-seq__ai-rest","data-edit-seq-ai-rest":""' in preview


def test_the_preview_sticks_under_the_step_head() -> None:
    assert "--q-sticky-header-height" in _NAV  # the measured height it relies on
    narrow = _rule(".q-edit__preview")
    assert "position: sticky;" in narrow
    assert "top: var(--q-sticky-header-height, 0px);" in narrow
    assert "top: 0;" not in narrow
    wide = _CSS[_CSS.index("@container edit-host (min-width: 46rem) {") :]
    wide = _rule(".q-edit__preview", wide)
    assert "top: calc(var(--q-sticky-header-height, 0px) + var(--space-3));" in wide
    # under the head's sheet (z 5), never over it
    assert "z-index: 3;" in narrow

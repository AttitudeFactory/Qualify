"""ED-13 (m-25029108, Deivid 2026-11-24): «palabra demasiado larga para la pantalla» under
the text's field (`assets/text-fit.js`), run by `node` with a fixed-advance measure — the
final video's criterion (`word_too_wide`: wider than the 9:16 safe zone at the smallest
title size of the letter size). Its numbers are checked against the render's own manifest
and the contract's size scale. Skipped where `node` is not installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from . import clip_texts_vm as vm
from . import editor_preview_contract as contract

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "assets" / "text-fit.js"
_MANIFEST = _ROOT / "packages" / "render" / "templates" / "layer_still" / "manifest.json"
_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(_NODE is None, reason="node is not installed")

#: Deivid's text (2026-11-24), double space included: its lines ran past the right margin
#: in the preview and the render refuses it (`word_too_wide`, 1447 px at 76 px).
DEIVID = (
    "hola que hace  con 40 caracteres lorem ipsum alastre fjkaskjas asjkasjkjkd "
    "asdasdasdasdassdasdasdasdasdas asdasd"
)


def _run(body: str) -> object:
    script = (
        f"const fit = require({json.dumps(str(_SCRIPT))});\n"
        # Poppins bold is ~0.68 em per lowercase letter: 68 px each at 100 px
        "const measure = (w) => w.length * 68;\n"
        f"console.log(JSON.stringify((() => {{ {body} }})()));\n"
    )
    out = subprocess.run(
        [_NODE], input=script, capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(out.stdout)


def test_the_script_parses() -> None:
    subprocess.run([_NODE, "--check", str(_SCRIPT)], check=True, timeout=30)


def test_the_numbers_are_the_final_videos() -> None:
    # the render's 9:16 safe zone (x 64–1016) and title sizes (112 → 76 px), as written
    text = _MANIFEST.read_text(encoding="utf-8")
    assert '"safe": [64, 270, 1016, 1536]' in text and '"9:16": [112, 76]' in text
    got = _run("return {safe: fit.SAFE_WIDTH, min: fit.MIN_PX};")
    assert got["safe"] == 1016 - 64
    assert got["min"] == {
        size: round(76 * contract.VIDEO_TEXT_SIZE_SCALE[size]) for size in contract.VIDEO_TEXT_SIZES
    }


def test_deivids_text_names_its_long_word_at_every_size() -> None:
    got = _run(
        f"const t = {json.dumps(DEIVID)};"
        "return ['small', 'medium', 'large'].map((s) => fit.widest(t, s, measure));"
    )
    assert got == ["asdasdasdasdassdasdasdasdasdas"] * 3
    # without that word every other one fits, even at «Grande»
    short = DEIVID.replace("asdasdasdasdassdasdasdasdasdas ", "")
    assert _run(f"return fit.widest({json.dumps(short)}, 'large', measure);") == ""


def test_a_word_fits_or_not_by_the_letter_size() -> None:
    # 18 letters × 68 = 1224 px at 100 px → 698 · 930 · 1163 px at 57 · 76 · 95 px
    word = "a" * 18
    got = _run(
        f"return ['small', 'medium', 'large', 'nope'].map((s) => fit.widest({word!r}, s, measure));"
    )
    assert got == ["", "", word, ""]  # an unknown size measures as «Mediana»


def test_the_line_names_the_word_cut_when_long() -> None:
    shown = _run("return fit.shown('asdasdasdasdassdasdasdasdasdas');")
    assert shown == "asdasdasdasdassdasdasda…" and len(shown) == 24
    assert _run("return fit.shown('aaaa');") == "aaaa"
    line = vm.WIDE_WORD_LINE.replace("{word}", shown)
    assert line.startswith("Tu texto tiene una palabra demasiado larga para la pantalla: «")
    assert vm.WIDE_WORD_LINE.count("{word}") == 1


def test_the_panel_carries_the_line_and_mounts_the_script() -> None:
    from . import clip_editor_view
    from .ui import text_panel

    panel = str(clip_editor_view._text_panel().render())
    assert text_panel.WIDE_NOTE_ID in panel and "q-text-fit-note" in panel
    assert "data-text-fit" in panel and '"data-line"' in panel
    # mounted with the panel (`on_mount` scripts do not show in the render)
    assert text_panel.FIT_SCRIPT == _SCRIPT.name
    assert "asset_script(FIT_SCRIPT)" in Path(text_panel.__file__).read_text(encoding="utf-8")
    css = (_ROOT / "assets" / "qualify-creative.css").read_text(encoding="utf-8")
    assert ".q-text-fit-note:empty { display: none; }" in css
    # the preview's text never grows past the safe zone (the bug: an `auto` column)
    assert "grid-template-columns: minmax(0, max-content);" in css
    assert "overflow-wrap: anywhere;" in css

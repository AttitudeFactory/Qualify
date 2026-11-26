"""m-25026602: the AI part on the timeline («parte con IA»), signed by Deivid on 2026-11-26.

Offline: the role «hecho con IA» is the iris scale the system already loads (no new
colour); the CSS carries the block, every state, the narrow widths and the chosen edge in
the right order; `/design` mounts a static sample with every state, the narrow widths,
own blocks to compare, the panel's full badge and the preview's mark; the words are the
signed ones (and the states' come from `part_progress_vm`, never retyped); and
docs/design-system.md §5.10.1 records the pattern and the 9 answers.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

from Qualify import part_progress_vm as pp_vm
from Qualify import reel_parts_vm as rp_vm
from Qualify import styleguide_page as page
from Qualify.ui import ai_mode_tag
from Qualify.ui import tokens as T

_ROOT = Path(__file__).parent.parent
_BASE_CSS = (_ROOT / "assets" / "qualify.css").read_text(encoding="utf-8")
_CSS = (_ROOT / "assets" / "qualify-creative.css").read_text(encoding="utf-8")
_DOC = (_ROOT / "docs" / "design-system.md").read_text(encoding="utf-8")
_AI_CSS = _CSS[_CSS.index("── The AI part on the timeline") :]

_STATES = ("plan", "queued", "creating", "review", "ready", "failed", "refused", "redo", "expired")


def _has(rendered: str, text: str) -> bool:
    escaped = json.dumps(text)[1:-1]
    return any(form in rendered for form in (text, escaped, escaped.replace("\\", "\\\\")))


# ---------------------------------------------------------------------------------------
# The role «hecho con IA»
# ---------------------------------------------------------------------------------------


def test_the_role_is_the_iris_scale_already_loaded() -> None:
    assert T.AI_SCALE == "iris"
    assert T.ZONE_SCALE["publish"] == T.AI_SCALE  # no new scale: the «Publica» zone's
    assert T.AI_ICON == "sparkles"
    tokens = {
        "--q-ai-fill": "--iris-a4",
        "--q-ai-edge": "--iris-a7",
        "--q-ai-edge-plan": "--iris-a8",
        "--q-ai-ring": "--iris-a9",
        "--q-ai-ink": "--iris-12",
        "--q-ai-icon": "--iris-11",
    }
    for token, step in tokens.items():
        assert re.search(rf"{token}:\s*var\({step}\);", _BASE_CSS), token


# ---------------------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------------------


def test_css_has_the_block_its_parts_and_every_state() -> None:
    base = '.q-tl__block[data-tl-block="ai"] {'
    assert base in _AI_CSS
    rule = _AI_CSS[_AI_CSS.index(base) :]
    rule = rule[: rule.index("}")]
    assert "border: 1px solid var(--q-ai-edge);" in rule
    assert "background: var(--q-ai-fill);" in rule
    assert "flex-direction: column;" in rule  # two lines
    for cls in (".q-tl__mode", ".q-tl__state", ".q-tl__ai-name", ".q-tl__ai-line", ".q-ai-mark"):
        assert f"{cls} " in _AI_CSS or f"{cls}," in _AI_CSS, cls
    # every state the screen can set is drawn (plan + the PartState ones)
    for state in _STATES[1:]:
        if state in ("review", "ready"):
            continue  # same edge as created: drawn by the base rule
        assert f'[data-ai-state="{state}"]' in _AI_CSS, state
    plan = _AI_CSS[_AI_CSS.index('[data-ai-state="plan"] {') :]
    plan = plan[: plan.index("}")]
    assert "border-style: dashed;" in plan and "var(--q-ai-edge-plan)" in plan
    assert "opacity: 0.45;" in _AI_CSS and "saturate(0.4)" in _AI_CSS  # the dimmed poster
    for tone in ("info", "ok", "warn", "error"):
        assert f'.q-tl__state[data-tone="{tone}"]' in _AI_CSS


def test_chosen_edge_comes_last_and_keeps_the_dashes() -> None:
    chosen = '.q-tl__block[data-tl-block="ai"][aria-pressed="true"] {'
    assert chosen in _AI_CSS
    rule = _AI_CSS[_AI_CSS.index(chosen) :]
    rule = rule[: rule.index("}")]
    assert "border-color: var(--accent-9);" in rule and "border-width: 2px;" in rule
    assert "border-style" not in rule and "border:" not in rule  # a plan block stays dashed
    for earlier in ('[data-ai-state="plan"] {', '[data-ai-state="failed"]', '"expired"]) {'):
        assert _AI_CSS.index(earlier) < _AI_CSS.index(chosen), earlier


def test_lifted_edge_comes_after_the_ai_border_and_keeps_the_dashes() -> None:
    lifted = '.q-tl__item--lifted .q-tl__block[data-tl-block="ai"] {'
    assert lifted in _AI_CSS
    rule = _AI_CSS[_AI_CSS.index(lifted) :]
    rule = rule[: rule.index("}")]
    assert "border-color: var(--accent-9);" in rule and "border-width: 2px;" in rule
    assert "border-style" not in rule and "border:" not in rule
    for earlier in (
        '.q-tl__block[data-tl-block="ai"] {',
        '[data-ai-state="plan"] {',
        '"expired"]) {',
    ):
        assert _AI_CSS.index(earlier) < _AI_CSS.index(lifted), earlier
    # and the generic lift rule it restores sits before the AI section
    assert _CSS.index(".q-tl__item--lifted .q-tl__block {") < _CSS.index(_AI_CSS)


def test_narrow_blocks_measure_the_content_box() -> None:
    base = _AI_CSS[_AI_CSS.index('.q-tl__block[data-tl-block="ai"] {') :]
    assert "padding: 4px;" in base[: base.index("}")]  # room for 1 s and 2 s parts
    narrow = _AI_CSS[_AI_CSS.index("@container q-tl-block (max-width: 7.5rem) {") :]
    assert ".q-tl__mode-word, .q-tl__secs" in narrow[: narrow.index("}")]
    tiny = _AI_CSS[_AI_CSS.index("@container q-tl-block (max-width: 3.25rem) {") :]
    tiny = tiny[: tiny.index("\n}")]
    assert ".q-tl__state-word, .q-tl__ai-name" in tiny
    assert "padding-inline: 1px;" in tiny  # the ✦ and the mode's icon fit in 1 s
    assert "@container q-tl-block (max-width: 4.5rem)" not in _AI_CSS
    assert "@container q-tl-block (max-width: 1.5rem) {" in _AI_CSS  # then only the ✦


def test_ed11_picture_rule_never_empties_the_ai_name_chip() -> None:
    # the track marks every block with a picture; ED-11 hides its label under 4.5rem
    ed11 = _CSS[_CSS.index("@container q-tl-block (max-width: 4.5rem) {") :]
    assert '.q-tl__block[data-tl-pic="1"] .q-tl__label' in ed11[: ed11.index("}")]
    keep = '.q-tl__block[data-tl-block="ai"][data-tl-pic="1"] .q-tl__ai-name .q-tl__label'
    rule = _AI_CSS[_AI_CSS.index(keep) :]
    assert "display: revert;" in rule[: rule.index("}")]
    # outside any container query: it holds at every width; the name hides only with
    # the whole `.q-tl__ai-name` at the AI block's own cut
    before = _AI_CSS[: _AI_CSS.index(keep)]
    assert before.count("{") == before.count("}")
    # and the /design sample carries the attribute, as the real track does
    rendered = str(page._ai_part_section().render())
    assert rendered.count('"data-tl-pic":"1"') == rendered.count('"data-tl-block":"ai"')


def test_transition_in_keeps_the_ai_padding_after_the_overlap() -> None:
    generic = '.q-tl__item[data-tl-in="1"] .q-tl__block {'
    original = _CSS[_CSS.index(generic) :]
    original = original[: original.index("}")]
    assert "calc(var(--b-in) / var(--b-len) * 100% + var(--space-2))" in original
    ai = '.q-tl__item[data-tl-in="1"] .q-tl__block[data-tl-block="ai"] {'
    rule = _AI_CSS[_AI_CSS.index(ai) :]
    rule = rule[: rule.index("}")]
    # the same formula as the original, with the AI block's 4 px instead of --space-2
    assert "padding-left: calc(var(--b-in) / var(--b-len) * 100% + 4px);" in rule
    assert _CSS.index(generic) < _CSS.index(ai)


def test_veil_and_ring() -> None:
    assert "linear-gradient(90deg, var(--black-a6), transparent 80%)" in _AI_CSS
    assert re.search(r"--q-ai-ring:\s*var\(--iris-a9\);", _BASE_CSS)
    mode = _AI_CSS[_AI_CSS.index(".q-tl__mode {") :]
    assert "var(--q-ai-ring)" in mode[: mode.index("}")]


def test_error_and_warning_states_have_a_shaped_icon() -> None:
    assert page.AI_STATE_ICONS["failed"] == "circle-x"
    for state in ("refused", "redo", "expired"):
        assert page.AI_STATE_ICONS[state] == "triangle-alert", state
    rendered = str(page._ai_part_section().render())
    assert _has(rendered, "circle_x") or _has(rendered, "CircleX")
    assert _has(rendered, "triangle_alert") or _has(rendered, "TriangleAlert")


def test_only_theme_variables() -> None:
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", _AI_CSS)
    assert "rgba(" not in _AI_CSS


# ---------------------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------------------


def test_short_badges_are_the_signed_words() -> None:
    assert {mode: word for mode, (_, word) in page.AI_MODE_SHORT.items()} == {
        "reference": "Nueva",
        "edit": "Igual al original",
        "extend": "Sigue a la anterior",
    }
    # every full name of today is covered by one short word, and starts with it
    fulls = [full for _, full in page.AI_MODE_FULL]
    assert set(fulls) == {
        rp_vm.FORM_INSPIRED,
        rp_vm.FORM_NEW,
        rp_vm.FORM_NEW_BRAND,
        rp_vm.FORM_EDIT,
        rp_vm.FORM_EXTEND,
    }
    for mode, full in page.AI_MODE_FULL:
        assert full.startswith(page.AI_MODE_SHORT[mode][1]), full


def test_states_words_come_from_the_parts_view_model() -> None:
    assert set(page.AI_STATES) == set(_STATES[1:])
    assert set(page.AI_STATES.values()) == set(pp_vm.STATE_WORDS) - {pp_vm.PartState.UNMADE}
    assert pp_vm.STATE_TONES[page.AI_STATES["creating"]] == "info"
    assert pp_vm.STATE_TONES[page.AI_STATES["ready"]] == "ok"
    assert pp_vm.STATE_TONES[page.AI_STATES["failed"]] == "error"
    assert pp_vm.STATE_TONES[page.AI_STATES["queued"]] == "neutral"


def test_the_accessible_name_says_everything() -> None:
    assert page.AI_PART_NAME.format(n=1) == "Parte con IA 1"
    assert (
        page.ai_part_label("Parte con IA 1", "reference", 6, 5)
        == "Parte con IA 1, Nueva, de 0:06 a 0:11, sin crear"
    )
    assert (
        page.ai_part_label("Parte con IA 2", "extend", 11.5, 3, "creating")
        == "Parte con IA 2, Sigue a la anterior, de 0:11,5 a 0:14,5, creando"
    )
    # m-25129389: blocks sit to the tenth, off the ½ s magnet — the name says so
    assert (
        page.ai_part_label("Parte con IA 3", "edit", 4.7, 2, "failed")
        == "Parte con IA 3, Igual al original, de 0:04,7 a 0:06,7, no salió"
    )


# ---------------------------------------------------------------------------------------
# /design
# ---------------------------------------------------------------------------------------


def test_design_mounts_the_static_sample() -> None:
    rendered = str(page._ai_part_section().render())
    assert page.AI_PART_ANCHOR in rendered
    assert _has(rendered, "Parte con IA en la línea de tiempo")
    for state in _STATES:
        assert f'"data-ai-state":"{state}"' in rendered, state
    assert rendered.count('"data-tl-block":"ai"') >= len(_STATES) + 4
    assert rendered.count("q-ai-sample__box") >= len(_STATES) + 4  # every state + the widths
    assert _has(rendered, "q-tl__mode") and _has(rendered, "q-tl__state")
    for _, word in page.AI_MODE_SHORT.values():
        assert _has(rendered, word)
    for part_state in page.AI_STATES.values():
        assert _has(rendered, pp_vm.STATE_WORDS[part_state])
    # own blocks to compare, the panel's full badge and the preview's mark
    assert '"data-tl-block":"video"' in rendered and '"data-tl-block":"photo"' in rendered
    assert _has(rendered, "Video 1") and _has(rendered, "Foto 1")
    for _, full in page.AI_MODE_FULL:
        assert _has(rendered, full)
    assert _has(rendered, "Parte con IA 1 · se crea al tocar «Crear»")
    assert "q-ai-mark" in rendered
    # static: no event handler anywhere in the sample
    assert "addEvents" not in rendered


def test_design_page_includes_the_section_after_the_timeline() -> None:
    source = inspect.getsource(page.styleguide_index)
    assert source.index("_timeline_section()") < source.index("_ai_part_section()")


def test_full_badge_is_iris_surface() -> None:
    rendered = str(ai_mode_tag(rp_vm.FORM_INSPIRED, "wand-sparkles").render())
    assert "iris" in rendered and "surface" in rendered
    assert _has(rendered, rp_vm.FORM_INSPIRED)


# ---------------------------------------------------------------------------------------
# docs/design-system.md §5.10.1
# ---------------------------------------------------------------------------------------


def test_doc_records_the_signed_pattern() -> None:
    start = _DOC.index("### 5.10.1 Parte con IA en la línea de tiempo (m-25026602")
    section = _DOC[start : _DOC.index("\n## 6.", start)]
    assert "`docs/mockups/editor-unico/`" in section
    assert ".claude/mockups-editor-unico" not in section  # not in the repo
    mockups = _ROOT / "docs" / "mockups" / "editor-unico"
    cited = set(re.findall(r"`((?:0[1-6]-[a-z-]+|index)\.html|notas\.md)`", section))
    assert cited >= {
        "index.html",
        "01-pista.html",
        "02-panel-bloque-ia.html",
        "03-agregar.html",
        "04-crear.html",
        "05-resultado.html",
        "06-hacer-uno-parecido.html",
        "notas.md",
    }
    for name in cited | {"editor-unico.css", "mock.js"}:  # the pages load these two
        assert (mockups / name).is_file(), name
    for token in (
        "--q-ai-fill",
        "--q-ai-edge",
        "--q-ai-edge-plan",
        "--q-ai-ring",
        "--q-ai-ink",
        "--q-ai-icon",
    ):
        assert f"`{token}`" in section, token
    for state in _STATES:
        assert f"`{state}`" in section, state
    for text in (
        "«Probar esta parte»",
        "«Ahora, al crear»",
        "«Después, al aprobar»",
        "Una parte con IA va siempre a ×1",
        "«Sin crear · gratis hasta «Crear»»",
        "«Lo cambiaste tú.» / «Volver a lo que te propusimos»",
    ):
        assert text in section, text
    for _, word in page.AI_MODE_SHORT.values():
        assert f"«{word}»" in section
    # the 9 answers, one row each; the 9th confirmed: «Video o audio tuyo» only in «Nueva»
    answers = re.findall(r"^\| ([1-9]) \|", section, flags=re.MULTILINE)
    assert answers == [str(n) for n in range(1, 10)]
    assert "**Pendiente:**" not in section
    assert "**solo aparece en «Nueva»** (`reference`)" in section
    # v1: «Sigue a la anterior» only continues an AI part right before it
    assert "solo continúa una parte con IA que esté justo antes" in section

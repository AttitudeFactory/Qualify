"""Static guard: the design system is the only door to its own rules.

The sibling of `packages/shared/tests/test_object_store_sanctity.py`, for the UI. A rule
that lives only in `docs/design-system.md` is remembered until it is not; a rule that
fails `just test` is a rule. Pure AST — no Reflex import, no page import, so it runs in
the offline gate.

Rules (founder, 2026-10-08; docs/plan-migracion-liquid-glass.md §3 D9):

* **Waiting.** A skeleton is content loading, a spinner is work in progress, and both
  come from `Qualify/ui`: pages never call `rx.skeleton(...)` or `rx.spinner(...)`.
  (`rx.button(loading=...)` is a prop, not a call, and stays allowed.)
* **Colour.** A page names colours by role (`T.TEXT_MUTED`, `tone="error"`,
  `T.tone_color(...)`), never by value: no hex literal handed to a component (as a
  keyword or inside `style={...}`), no `rx.color(...)` outside `Qualify/ui`. Hex strings
  that are *data* (a palette read from a logo, a campaign's colour) are not style.
* **Elevation and material.** `box_shadow=`, `backdrop_filter=` and `text_shadow=` are
  the system's to set (`ui.card`, `.q-*` classes, the Radix skin), never a page's.
* **Uploads.** `rx.upload(...)` / `rx.upload.root(...)` only through `ui.dropzone` (the
  styled widget paints an inline dashed border no class can override).

Enforcement is per module: every page module is checked, except the ones still listed
in `_PENDING` — the files the Liquid Glass batches (lotes A–E) have not migrated yet. A
batch removes its files from `_PENDING` as part of its definition of done; a file can
never be added back. `test_pending_list_is_honest` keeps the list from rotting: a file
that is already clean must leave it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent

# The package that owns the rules: it may call whatever Radix primitive it wraps.
_SANCTIONED_DIR = _APP_ROOT / "ui"

# The living style guide renders the raw Radix scales on purpose (that is what it is
# for); it is the one page allowed to call `rx.color` directly.
_SANCTIONED_FILES = {"styleguide_page.py"}

# `rx.<name>(...)` calls a page may never make. The value is the door it must use instead.
_FORBIDDEN_RX_CALLS: dict[str, str] = {
    "skeleton": "ui.skeleton_card / ui.skeleton_rows (content loading)",
    "spinner": "ui.loading_spinner (work in progress)",
    "color": "ui.tokens (T.TEXT_MUTED, T.tone_color, T.platform_scale, ...)",
    "upload": "ui.dropzone (the styled rx.upload paints an inline border no class overrides)",
}

# Keyword arguments a page may never pass to a component.
_FORBIDDEN_KWARGS: dict[str, str] = {
    "box_shadow": "T.ELEV_* through ui.card / a .q-* class",
    "backdrop_filter": "the island/overlay materials of the system",
    "text_shadow": "no shadow on text in this system",
}

# A colour written as a value. Deliberately strict: a 3- to 8-digit hex after `#`.
_HEX = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")

# Page modules the migration batches have not reached yet (lote → files). Shrinks only.
# Every lote (A–E, 2026-10-08) has migrated: the guard now protects the whole app. The
# set stays so a future page can be parked here while it is being built.
_PENDING: set[str] = set()


def _page_modules() -> list[Path]:
    """Every app module outside `ui/`, tests excluded (they build no screens)."""
    return sorted(
        path
        for path in _APP_ROOT.glob("*.py")
        if not path.name.startswith("test_")
        and _SANCTIONED_DIR not in path.parents
        and path.name not in _SANCTIONED_FILES
    )


def _rx_call_name(node: ast.Call) -> str | None:
    """`rx.spinner(...)` -> "spinner", `rx.upload.root(...)` -> "upload"; else None."""
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Attribute):
        func = func.value  # `rx.upload.root(...)`: the namespace is what matters
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "rx"
    ):
        return func.attr
    return None


def _offences(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    where = path.relative_to(_APP_ROOT.parent)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _rx_call_name(node)
            if name in _FORBIDDEN_RX_CALLS:
                found.append(f"{where}:{node.lineno} rx.{name}(...) -> {_FORBIDDEN_RX_CALLS[name]}")
            for keyword in node.keywords:
                if keyword.arg in _FORBIDDEN_KWARGS:
                    found.append(
                        f"{where}:{node.lineno} {keyword.arg}= -> {_FORBIDDEN_KWARGS[keyword.arg]}"
                    )
                # A hex colour handed to a component (`color="#fff"`, `style={...}` is
                # caught below). Hex strings in data — a palette extracted from a logo, a
                # campaign's chosen colour — are values, not style, and pass.
                value = keyword.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    if _HEX.search(value.value):
                        found.append(
                            f"{where}:{node.lineno} {keyword.arg}={value.value!r} -> a T.* token"
                        )
                if keyword.arg == "style" and isinstance(value, ast.Dict):
                    for item in value.values:
                        if isinstance(item, ast.Constant) and isinstance(item.value, str):
                            if _HEX.search(item.value):
                                found.append(
                                    f"{where}:{node.lineno} style={{...{item.value!r}}}"
                                    " -> a T.* token"
                                )
    return found


def test_migrated_pages_use_the_design_system() -> None:
    offenders = [
        line for path in _page_modules() if path.name not in _PENDING for line in _offences(path)
    ]
    assert not offenders, "Style outside the design system:\n" + "\n".join(offenders)


def test_pending_list_is_honest() -> None:
    """A file that no longer offends must leave `_PENDING` (so the rule now protects it),
    and the list may only name files that exist."""
    names = {path.name for path in _page_modules()}
    unknown = sorted(_PENDING - names)
    assert not unknown, f"_PENDING names files that do not exist: {unknown}"
    clean = sorted(name for name in _PENDING if not _offences(_APP_ROOT / name))
    assert not clean, f"Already clean — remove from _PENDING: {clean}"


def test_guard_sees_the_app() -> None:
    """The guard is only as good as its file list: it must find real page modules and
    must not be looking at the sanctioned package."""
    modules = _page_modules()
    assert any(m.name == "inbox_page.py" for m in modules)
    assert all(_SANCTIONED_DIR not in m.parents for m in modules)

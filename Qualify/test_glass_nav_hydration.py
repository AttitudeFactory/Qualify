"""The sidebar's `assets/glass-nav.js` must not touch the rail before React hydrates it.

The script adds the capsule (`.q-glass-blob`) to the active row's island and marks the
nav with `data-glass`. Since the active row is known at prerender (m-24993451), a script
loaded straight from the prerendered `<head>` did that before hydration: React found a
node it never rendered (minified error #418), re-created the whole document, and the
re-appended `__reflex_global_styles` link landed after emotion's `<style>` tags, so
Radix's base `display` rules beat emotion's responsive ones (the phone's controls shown
on desktop). The script tag is therefore rendered only after the first client effect.

A browser test is what really proves the absence of #418; this pins the wiring.
"""

from __future__ import annotations

from typing import Any

from .ui import layout

_SRC = '"/glass-nav.js"'


def _walk(node: Any, conds: tuple[str, ...] = ()) -> list[tuple[dict, tuple[str, ...]]]:
    """Every rendered element dict with the `rx.cond` conditions it sits under."""
    found: list[tuple[dict, tuple[str, ...]]] = []
    if isinstance(node, dict):
        if "cond_state" in node:
            found += _walk(node["true_value"], (*conds, node["cond_state"]))
            found += _walk(node["false_value"], (*conds, f"!{node['cond_state']}"))
            return found
        found.append((node, conds))
        for child in node.get("children", []):
            found += _walk(child, conds)
    elif isinstance(node, list):
        for child in node:
            found += _walk(child, conds)
    return found


def _glass_scripts() -> list[tuple[dict, tuple[str, ...]]]:
    return [
        (el, conds)
        for el, conds in _walk(layout.sidebar().render())
        if el.get("name") == '"script"' and f"src:{_SRC}" in el.get("props", [])
    ]


def test_glass_nav_script_is_rendered_once_and_only_after_hydration() -> None:
    scripts = _glass_scripts()
    assert len(scripts) == 1, scripts
    _el, conds = scripts[0]
    assert conds == ("qHydrated",), conds


def test_sidebar_declares_the_hydrated_flag_as_state_set_in_an_effect() -> None:
    """The real sidebar carries the flag: false in the prerendered HTML and in the first
    client render (so both agree), true only from the first effect, which runs after
    hydration has committed."""
    sidebar = layout.sidebar()
    hooks = [hook for hook in sidebar._get_all_hooks() if "qHydrated" in hook]
    assert len(hooks) == 1, hooks
    assert "useState(false)" in hooks[0]
    assert "useEffect(() => setQHydrated(true), [])" in hooks[0]
    react = {getattr(i, "tag", i) for i in sidebar._get_all_imports().get("react", [])}
    assert {"useState", "useEffect"} <= react, react

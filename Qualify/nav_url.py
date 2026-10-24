"""Every tab, view and detail has its own address (N5, m-24842960 NAV-2).

A screen that switches a tab or opens a detail in place writes the new address with
`history.pushState` (`push_url`) instead of `rx.redirect`: a redirect is a React Router
navigation, which re-runs the route's whole `on_load` (and its reads) for a change the
state already made. Reflex reads the live `window.location` for `router_data`
(`withRouterData` in `state.js`), so the backend still sees the new query string.

The browser's «atrás» is a real navigation (React Router answers `popstate`), so the
route's `on_load` runs with the previous address and each screen's entry handler reads
its parameter back: «atrás» returns to the previous tab instead of leaving the module,
and reloading keeps the tab.

Pure string builders (no Reflex import, so `*_vm.py` modules can use them), tested in
`test_nav_url.py`.
"""

from __future__ import annotations

import json
from urllib.parse import urlencode


def with_query(path: str, **params: str) -> str:
    """`path` plus the non-empty `params` as a query string, in the given order."""
    kept = {key: value for key, value in params.items() if value}
    return f"{path}?{urlencode(kept)}" if kept else path


def _history_script(method: str, url: str) -> str:
    # The guard keeps a repeated click from stacking identical history entries;
    # `history.state` is carried over so React Router keeps its own bookkeeping.
    target = json.dumps(url)
    return (
        f"if (window.location.pathname + window.location.search !== {target}) "
        f"window.history.{method}(window.history.state, '', {target});"
    )


def push_url_script(url: str) -> str:
    """JS that adds `url` to the history (a new «atrás» step) without navigating."""
    return _history_script("pushState", url)


def replace_url_script(url: str) -> str:
    """JS that rewrites the current address to `url` without adding a history step."""
    return _history_script("replaceState", url)

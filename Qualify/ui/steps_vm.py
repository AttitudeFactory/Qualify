"""The step frame's arithmetic and its address (PASOS-2, m-24852241; docs/design-system.md §4.5).

Pure (no Reflex import), so a flow's `*_vm.py` and its tests can use it. The Reflex side
— the head, the foot and the scripts that run on a step change — is `ui/steps.py`.

**«Paso N de M» counts only the steps the owner will actually see.** A flow declares its
steps once, in order, by key, and says which ones it skips for this owner (no photo to
crop, a single product, …). `step_position` gives N and M over the visible ones, so a
skipped step never appears as a number nobody reaches.

**Each step has an address** (`?paso=N`, rule N6b): N is the 1-based position among the
visible steps, the same number the owner reads. The recipe, for a state that owns a flow:

1. Moving to a step: set the state, then return
   ``rx.call_script(go_to_step_script(path, n, direction, **params))`` (`ui/steps.py`):
   it writes the address with `history.pushState`, scrolls `main.q-panel` (never
   `window`) to the top and moves the focus to the new step's title.
2. The route's `on_load` reads it back: ``n = parse_step_param(params.get(STEP_PARAM),
   m)`` and shows step n. The browser's «atrás» is a React Router navigation that
   answers `popstate` by running `on_load` again with the previous address (see
   `Qualify/nav_url.py`), so «atrás» goes back one step without any listener of our own
   — the same pattern as `WhatsAppState.enter_page` (`?tab=`). But `pushState` is
   invisible to React Router, so «atrás» onto the entry the router last saw does NOT
   run `on_load` (measured 2026-10-25): pass the same handler as ``step_frame(...,
   on_pop=...)``, which answers `popstate` itself. The handler must be idempotent
   (both may run for one «atrás»). On step 1 there is no earlier step entry, so
   «atrás» leaves for wherever the owner came from.
3. Leaving never clears what was written (N6): the values stay in the state.

PASOS-3 generalises addresses for every flow; this module is the small piece the frame
needs today.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from ..nav_url import with_query

STEP_PARAM = "paso"
"""The query parameter that carries the step number (`?paso=2`)."""

DIR_NEXT = "next"
DIR_BACK = "back"
"""`data-dir` of the step body: the entrance slides in from the side the owner moves to."""

BACK_LABEL = "Atrás"
NEXT_LABEL = "Siguiente"
LATER_LABEL = "Seguir después"


def visible_steps(steps: Sequence[str], skipped: Collection[str] = ()) -> list[str]:
    """The flow's step keys, in order, without the ones skipped for this owner."""
    return [key for key in steps if key not in skipped]


def step_position(current: str, visible: Sequence[str]) -> tuple[int, int]:
    """(N, M): the 1-based position of ``current`` among the visible steps, and their
    count. A key that is not visible (skipped, or unknown) reads as step 1, never as 0."""
    total = max(len(visible), 1)
    if current not in visible:
        return 1, total
    return visible.index(current) + 1, total


def step_label(n: int, m: int) -> str:
    """«Paso N de M», clamped so it never reads «Paso 4 de 3» or «Paso 0 de 3»."""
    m = max(m, 1)
    return f"Paso {min(max(n, 1), m)} de {m}"


def step_percent(n: int, m: int) -> int:
    """Width of the progress bar, in whole percent: step N of M fills N/M."""
    m = max(m, 1)
    return round(100 * min(max(n, 1), m) / m)


def shows_back(n: int) -> bool:
    """«Atrás» is never on step 1: there the way out is «‹ destino» in the head."""
    return n > 1


def parse_step_param(raw: object, m: int) -> int:
    """The step number in ``?paso=`` (a string from the router, or a list when the
    parameter repeats), clamped to 1..M. Missing or garbage reads as 1."""
    if isinstance(raw, list | tuple):
        raw = raw[0] if raw else ""
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return 1
    return min(max(n, 1), max(m, 1))


def step_direction(old: int, new: int, current: str = DIR_NEXT) -> str:
    """`data-dir` for a move from step ``old`` to step ``new``. Staying on the same step
    (``on_load`` and the `popstate` trigger both answering one «atrás») keeps
    ``current``: flipping it would restart the entrance the other way."""
    if new == old:
        return current
    return DIR_BACK if new < old else DIR_NEXT


def step_url(path: str, n: int, **params: str) -> str:
    """``path`` with ``?paso=n`` after any other non-empty parameters (`?volver=…`)."""
    return with_query(path, **params, **{STEP_PARAM: str(max(n, 1))})

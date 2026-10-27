"""The step frame (PASOS-2, m-24852241; docs/design-system.md §4.5, §10.19; rule N6b).

Every flow of more than one step shows, without scrolling, **where the owner is, how
much is left, how to go back and how to go on**. It is the anatomy of `drawer()` (fixed
head, scrolling body, fixed foot) taken to full-page wizards:

    app_shell(
        step_frame(
            ...the step's blocks...,
            head=step_head("¿Qué quieres decir?", step=S.n, total=S.m,
                           back_label="Tus publicaciones", back_href="/publicaciones"),
            foot=step_foot("Siguiente", step=S.n, on_primary=S.next,
                           on_back=S.back, on_later=S.later),
            step=S.n,
            direction=S.direction,
        )
    )

* **The head replaces `page_header`** while the wizard lasts (it is the same
  `.q-page-header` sheet, so no new glass): «‹ destino» (a link, or an event), «Paso N
  de M» with M counted over the visible steps (`steps_vm.step_position`), a 4 px
  accent bar, and the step's name as the page's one ``h1``.
* **The foot** is the bottom bar's opaque island (§4.4): «Atrás» (soft gray, never on
  step 1), the primary solid button (≥ 44 px, the caller's verb), «Seguir después»
  (ghost, the caller's handler: save and go to Inicio). On a phone (≤ 640 px) the
  bottom bar hides while a frame is mounted and the foot takes its slot — pure CSS
  (`.q-ground:has(.q-step-frame)` in assets/qualify.css), no Python state — and steps
  aside while a text field has the focus, like the bar. On a desktop it sticks to the
  panel's bottom edge.
* **Inside a `drawer`** only the counter and the bar move into the drawer's fixed
  header (``drawer(..., step=step_progress(n, m))``); ``step_foot(..., in_drawer=True)``
  goes in its ``footer``. The exit is the drawer's ✕ «Cerrar».
* **On a step change** the state returns ``go_to_step(path, n)`` (address + top +
  focus) or ``settle_step()`` (top + focus only, e.g. from ``on_load``). The body slides
  8 px in from the side the owner moves to (``direction``, `data-dir`), not at all under
  `prefers-reduced-motion`. The address recipe (`?paso=N`, «atrás» of the browser) is in
  `ui/steps_vm.py`.
"""

from __future__ import annotations

import json
from typing import Any, Literal

import reflex as rx

from . import tokens as T
from .steps_vm import (
    BACK_LABEL,
    DIR_BACK,
    DIR_NEXT,
    LATER_LABEL,
    shows_back,
    step_label,
    step_percent,
    step_url,
)

Scope = Literal["page", "drawer"]

# What scrolls and what takes the focus, per scope. The panel is the scroll container of
# every page (`app_shell`), never `window`; inside a drawer it is the drawer's body.
_SCROLLER: dict[str, str] = {"page": "main.q-panel", "drawer": ".q-drawer .q-drawer-body"}
_TITLE: dict[str, str] = {"page": "main.q-panel .q-step-title", "drawer": ".q-drawer .q-step-title"}


def _is_static(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------------------------------
# Head
# ---------------------------------------------------------------------------------------


COUNT_ID_PAGE = "q-step-count-page"
COUNT_ID_DRAWER = "q-step-count-drawer"
"""Ids of the «Paso N de M» text: the step's title points at it with `aria-describedby`,
so the screen reader reads name and position ONCE, when the focus lands on the title.
No live region on purpose — it would announce the step a second time."""


def _progress_parts(
    step: rx.Var[int] | int, total: rx.Var[int] | int, count_id: str
) -> tuple[rx.Component, rx.Component]:
    """(the «Paso N de M» text, the 4 px accent bar) — text and shape at once, never
    colour alone (P1). ``total`` is the count of VISIBLE steps (`steps_vm`)."""
    if _is_static(step) and _is_static(total):
        label: rx.Var | str = step_label(step, total)
        width: rx.Var | str = f"{step_percent(step, total)}%"
    else:
        label = f"Paso {step} de {total}"
        width = f"{(rx.Var.create(step) * 100 / rx.Var.create(total))}%"
    count = rx.text(
        label, size="2", weight="medium", color=T.TEXT_MUTED, class_name="q-step-count", id=count_id
    )
    bar = rx.box(
        rx.box(class_name="q-step-bar-fill", width=width),
        class_name="q-step-bar",
        role="progressbar",
        aria_label="Avance",
        aria_valuemin=1,
        aria_valuemax=total,
        aria_valuenow=step,
        aria_valuetext=label,
        width="100%",
    )
    return count, bar


def step_progress(step: rx.Var[int] | int, total: rx.Var[int] | int) -> rx.Component:
    """«Paso N de M» over its full-width bar, for a drawer's fixed header
    (``drawer(..., step=step_progress(n, m))``), whose title it describes."""
    count, bar = _progress_parts(step, total, COUNT_ID_DRAWER)
    return rx.vstack(
        count, bar, spacing="1", align_items="end", width="100%", class_name="q-step-progress"
    )


def _exit(
    back_label: str | rx.Var, back_href: str | rx.Var | None, on_exit: Any | None
) -> rx.Component:
    content = [
        rx.icon("chevron-left", size=T.ICON_MD, aria_hidden="true"),
        rx.text(back_label, as_="span", size="2", weight="medium"),
    ]
    aria = f"Volver a {back_label}"
    if back_href is not None:
        return rx.link(
            *content, href=back_href, class_name="q-step-exit", aria_label=aria, underline="none"
        )
    return rx.el.button(
        *content, type="button", on_click=on_exit, class_name="q-step-exit", aria_label=aria
    )


def step_head(
    title: str | rx.Var,
    *,
    step: rx.Var[int] | int,
    total: rx.Var[int] | int,
    back_label: str | rx.Var,
    back_href: str | rx.Var | None = None,
    on_exit: Any | None = None,
    below: rx.Component | None = None,
    show_progress: bool | rx.Var[bool] = True,
) -> rx.Component:
    """The frame's fixed head, in place of `page_header`: «‹ ``back_label``» (to
    ``back_href``, or the ``on_exit`` event when leaving needs a handler — on every
    step, it is the way out), «Paso ``step`` de ``total``» with its bar, and ``title``
    — the step's name in the owner's words — as the page's one ``h1``. ``below`` is an
    optional desktop-only extra under the title (a `stepper()` when the steps can be
    walked out of order); on a phone the bar replaces it."""
    if (back_href is None) == (on_exit is None):
        raise ValueError("step_head needs exactly one of back_href or on_exit")
    count, bar = _progress_parts(step, total, COUNT_ID_PAGE)
    if show_progress is False:
        count, bar = rx.fragment(), rx.fragment()
    elif show_progress is not True:
        count, bar = rx.cond(show_progress, count), rx.cond(show_progress, bar)
    return rx.vstack(
        # «‹ destino» and «Paso N de M» share a row; the bar gets a line of its own, so
        # a long destination never squeezes it (§4.5 mockup).
        rx.hstack(
            _exit(back_label, back_href, on_exit),
            count,
            align="center",
            justify="between",
            spacing="3",
            width="100%",
        ),
        bar,
        rx.heading(
            title,
            as_="h1",
            size="6",
            # Focusable by script only: a step change moves the focus here, so a screen
            # reader announces the new step with its position (§8).
            tab_index=-1,
            custom_attrs={"aria-describedby": COUNT_ID_PAGE},
            class_name="q-step-title",
        ),
        *([rx.box(below, class_name="q-step-head-below", width="100%")] if below else []),
        spacing="2",
        width="100%",
        padding=T.PAD_HEADER,
        align_items="start",
        # Same sticky sheet as the page header it replaces (`.q-page-header`).
        class_name="q-page-header q-step-head",
    )


# ---------------------------------------------------------------------------------------
# Foot
# ---------------------------------------------------------------------------------------


def step_foot(
    primary_label: str | rx.Var | None,
    *,
    step: rx.Var[int] | int,
    on_primary: Any,
    on_back: Any | None = None,
    on_later: Any | None = None,
    primary_disabled: rx.Var[bool] | bool = False,
    primary_loading: rx.Var[bool] | bool = False,
    reason: str | rx.Var | None = None,
    in_drawer: bool = False,
) -> rx.Component:
    """The frame's fixed foot. «Atrás» (``on_back``: back one step, keeping what was
    written) is never rendered on step 1. The primary button carries the caller's verb
    («Siguiente»; on the last step who acts and what happens, N13). ``reason`` is why
    the step is not valid yet, read next to the button (§5.8) — pass "" or None when it
    is. «Seguir después» (``on_later``: save and go to Inicio, N2) is a ghost button.
    ``in_drawer`` renders it for a drawer's ``footer`` (the drawer's foot is already
    fixed) instead of the page's island.

    ``primary_label=None`` leaves the primary out, for a step whose way forward is in
    its body (Tu marca's «Tus redes»: the network buttons read the profile and move
    on); a step that can go on but is not valid yet keeps it, disabled, with
    ``reason``."""
    back_button = rx.button(
        BACK_LABEL,
        variant="soft",
        color_scheme="gray",
        size="3",
        on_click=on_back,
        class_name="q-step-back",
    )
    if on_back is None:
        back: rx.Component | None = None
    elif _is_static(step):
        back = back_button if shows_back(step) else None
    else:
        back = rx.cond(step > 1, back_button)
    primary = (
        None
        if primary_label is None
        else rx.button(
            primary_label,
            size="3",
            on_click=on_primary,
            disabled=primary_disabled,
            aria_disabled=primary_disabled,
            loading=primary_loading,
            class_name="q-step-primary",
        )
    )
    later = (
        rx.button(
            LATER_LABEL,
            variant="ghost",
            color_scheme="gray",
            size="2",
            on_click=on_later,
            class_name="q-step-later",
        )
        if on_later is not None
        else None
    )
    cells: list[rx.Component] = []
    if back is not None:
        cells.append(back)
    if reason is not None:
        why = rx.text(reason, size="1", color=T.TEXT_MUTED, class_name="q-step-reason")
        cells.append(rx.cond(reason, why) if isinstance(reason, rx.Var) else why)
    if later is not None:
        cells.append(later)
    if primary is not None:
        cells.append(primary)
    island = rx.box(
        *cells,
        class_name="q-step-foot q-step-foot--drawer" if in_drawer else "q-step-foot",
        width="100%",
    )
    if in_drawer:
        return island
    # The slot carries the position (sticky on a desktop, fixed on a phone); the island
    # inside carries the bottom bar's material.
    return rx.box(island, class_name="q-step-slot", width="100%")


# ---------------------------------------------------------------------------------------
# Frame
# ---------------------------------------------------------------------------------------


def step_frame(
    *children: rx.Component,
    head: rx.Component,
    foot: rx.Component,
    step: rx.Var[int] | int,
    direction: rx.Var[str] | str = DIR_NEXT,
    on_pop: Any | None = None,
    on_leave: Any | None = None,
    spacing: str = "4",
) -> rx.Component:
    """A full-page wizard: ``head`` (`step_head`) fixed on top, the step's ``children``
    in the body that scrolls, ``foot`` (`step_foot`) fixed at the bottom. Goes straight
    into `app_shell`, in place of `page_header` + `page_body`. The body is keyed by
    ``step``, so each step mounts fresh and plays its entrance in ``direction``.

    ``on_pop`` is the handler that reads ``?paso=`` back (usually the same one the
    route's ``on_load`` runs). It is needed because `history.pushState` is invisible to
    React Router: «atrás» onto the entry the router last saw changes nothing it can
    detect, so ``on_load`` does not run (measured 2026-10-25 on `/design/pasos`). The
    frame renders a hidden trigger for it and `step_settle_script` installs, once per
    tab, a `popstate` listener that presses it. The handler must be idempotent: when the
    router does notice the change, ``on_load`` runs too.

    ``on_leave`` runs when the frame unmounts (the owner left the route): the place to
    clear a `step_sync` readiness flag."""
    body = rx.vstack(
        *children,
        width="100%",
        max_width=T.CONTENT_MAX,
        spacing=spacing,
        align_items="start",
        padding=T.PAD_BODY,
        flex="1 0 auto",
        key=step,
        custom_attrs={"data-dir": direction},
        # `q-page-body`: the shell's phone rule reserves the foot's height at its end.
        class_name="q-step-body q-page-body",
    )
    pop = (
        [
            rx.el.button(
                on_click=on_pop,
                type="button",
                class_name="q-step-pop",
                hidden=True,
                tab_index=-1,
                aria_hidden="true",
            )
        ]
        if on_pop is not None
        else []
    )
    return rx.box(
        head,
        body,
        foot,
        *pop,
        class_name="q-step-frame",
        width="100%",
        flex="1 0 auto",
        display="flex",
        flex_direction="column",
        **({"on_unmount": on_leave} if on_leave is not None else {}),
    )


# ---------------------------------------------------------------------------------------
# Step change
# ---------------------------------------------------------------------------------------


def step_settle_script(scope: Scope = "page") -> str:
    """JS run after a step change: the scroll container back to the top (the panel,
    never `window` — H3) and the focus on the new step's title. Two animation frames
    let React paint the new step first."""
    scroller = json.dumps(_SCROLLER[scope])
    title = json.dumps(_TITLE[scope])
    return (
        # Once per tab: on «atrás»/«adelante», press the frame's hidden `on_pop` trigger
        # (see `step_frame`); a page without a frame has no trigger, so nothing happens.
        "if (!window.__qStepPop) { window.__qStepPop = true;"
        " window.addEventListener('popstate', () => window.setTimeout(() =>"
        " document.querySelector('.q-step-frame > .q-step-pop')?.click(), 0)); }"
        "window.requestAnimationFrame(() => window.requestAnimationFrame(() => {"
        f"const box = document.querySelector({scroller}); if (box) box.scrollTo({{top: 0}});"
        f"const h = document.querySelector({title}); if (h) h.focus({{preventScroll: true}});"
        "}));"
    )


#: Installed once per tab: how a step change writes the address (PASOS-4 UX review).
#: Forward → ``pushState``, remembering in ``history.state.qPrevPaso`` the step it
#: came from. «Atrás» → ``history.back()`` when the entry below IS that step, else
#: ``replaceState``: so «Atrás» never stacks entries, and after «Atrás» to step 1 the
#: browser's «atrás» leaves for where the owner came from — never to a later step. No
#: ``paso`` yet (the route's first write) → ``replaceState``; the same step (the
#: browser's «atrás» put it there) → nothing.
_STEP_GO_JS = (
    "if (!window.__qStepGo) window.__qStepGo = (target, back) => {"
    " const cur = new URL(window.location.href).searchParams.get('paso');"
    " const to = new URL(target, window.location.href);"
    " const n = to.searchParams.get('paso');"
    " const st = window.history.state || {}; const url = to.pathname + to.search + to.hash;"
    " const here = new URL(window.location.href);"
    " if (here.pathname.replace(/\\/$/, '') === to.pathname.replace(/\\/$/, '')"
    " && here.search === to.search && here.hash === to.hash) return;"
    " if (cur === null) { window.history.replaceState(st, '', url); return; }"
    " if (back) { if (st.qPrevPaso === n) {"
    " const pendingTarget = to.pathname.replace(/\\/$/, '') + to.search + to.hash;"
    " if (window.__qStepBackTarget === pendingTarget) return;"
    " window.__qStepBackTarget = pendingTarget;"
    " window.addEventListener('popstate', () => { window.__qStepBackTarget = null; }, {once:true});"
    " window.history.back(); } else window.history.replaceState(st, '', url); return; }"
    " window.history.pushState({ ...st, qPrevPaso: cur }, '', url); };"
)


def step_address_script(target: str, back: bool | str = False) -> str:
    """JS that moves the address to ``target`` (a JS expression for a URL with
    ``?paso=``) by the rule of `_STEP_GO_JS`. ``back`` is a bool, or a JS expression."""
    flag = ("true" if back else "false") if isinstance(back, bool) else back
    return _STEP_GO_JS + f"window.__qStepGo({target}, {flag});"


def step_sync_script(step: rx.Var[int] | int, direction: rx.Var[str] | str = DIR_NEXT) -> str:
    """JS that writes ``?paso=<step>`` for the step on screen (`step_address_script`;
    ``direction`` "back" is «Atrás»), then `step_settle_script`. Other parameters stay."""
    n = str(step) if _is_static(step) else f"{step}"
    if isinstance(direction, str):
        back: bool | str = direction == DIR_BACK
    else:
        # the Var's VALUE lands in the JS source, so it is quoted here ("next"/"back")
        back = f"('{direction}' === {json.dumps(DIR_BACK)})"
    target = (
        "(() => { const u = new URL(window.location.href);"
        f" u.searchParams.set('paso', String({n})); return u.href; }})()"
    )
    return step_address_script(target, back) + step_settle_script("page")


_STEP_SYNC_DOM_JS = (
    _STEP_GO_JS
    + r"""
(() => {
 if (!window.__qStepSync) {
  let pending = false;
  window.__qStepSync = () => {
   if (pending) return;
   pending = true;
   window.requestAnimationFrame(() => {
    pending = false;
    const mark = document.querySelector('main.q-panel .q-step-sync');
    if (!mark) return;
    const u = new URL(window.location.href);
    const n = String(Math.max(1, Number(mark.dataset.step) || 1));
    const entry = window.__qStepEntry;
    if (entry && u.pathname.replace(/\/$/, '') === entry.path) {
     if (String(mark.dataset.entry) !== String(entry.epoch)) return;
     u.searchParams.set('paso', String(entry.step));
     window.history.replaceState(window.history.state, '', u.pathname + u.search + u.hash);
     window.__qStepBoot = true; delete window.__qStepBootTarget; delete window.__qStepEntry;
    }

    if (!window.__qStepBoot) {
     window.__qStepBoot = true;
     // A cold document may briefly render the previous visit's server state.
     // Entry clears readiness, restores the requested step and remounts this marker.
     const requested = u.searchParams.get('paso');
     if (requested && requested !== n) { window.__qStepBootTarget = requested; return; }
    }
    u.searchParams.set('paso', n);
    if (window.__qStepBootTarget) {
     delete window.__qStepBootTarget;
     window.history.replaceState(window.history.state, '', u.pathname + u.search + u.hash);
    } else window.__qStepGo(u.href, mark.dataset.direction === 'back');
"""
    + step_settle_script("page")
    + r"""
   });
  };
  const carries = node => node?.nodeType === 1 &&
   (node.matches('.q-step-sync') || node.querySelector('.q-step-sync'));
  new MutationObserver(records => {
   if (records.some(record => record.type === 'attributes'
      ? record.target.matches('.q-step-sync')
      : [...record.addedNodes, ...record.removedNodes].some(carries))) window.__qStepSync();
  }).observe(document.body, {subtree: true, childList: true, attributes: true,
    attributeFilter: ['data-step', 'data-direction', 'data-entry']});
 }
 window.__qStepSync();
})();
"""
)


def step_entry_script(path: str, step: int, epoch: int, requested: str | None) -> str:
    """ACK a guarded entry only when its corresponding DOM epoch has painted."""
    payload = json.dumps({"path": path.rstrip("/"), "step": step, "epoch": epoch})
    return (
        "(() => { const u=new URL(window.location.href);"
        f" if (u.pathname.replace(/\\/$/, '') !== {json.dumps(path.rstrip('/'))}"
        f" || u.searchParams.get('paso') !== {json.dumps(requested)}) return;"
        f" window.__qStepEntry={payload}; window.__qStepSync?.(); }})();"
    )


def step_sync(
    step: rx.Var[int], direction: rx.Var[str] | str = DIR_NEXT, *, epoch: int | rx.Var[int] = 0
) -> rx.Component:
    """Observe marker data changes: Reflex can memoize the effect outside the DOM key."""
    return rx.box(
        key=step,
        custom_attrs={"data-step": step, "data-direction": direction, "data-entry": epoch},
        on_mount=rx.call_script(_STEP_SYNC_DOM_JS),
        display="none",
        class_name="q-step-sync",
    )


def settle_step(scope: Scope = "page") -> rx.event.EventSpec:
    """Event a handler returns after showing another step without a new address (from
    ``on_load`` when «atrás» brought the owner back, or inside a drawer)."""
    return rx.call_script(step_settle_script(scope))


def go_to_step(
    path: str, n: int, scope: Scope = "page", *, back: bool = False, **params: str
) -> rx.event.EventSpec:
    """Event a handler returns after moving to step ``n``: writes ``path?…&paso=n``
    (forward: a new history entry, so the browser's «atrás» goes back one step;
    ``back=True`` for «Atrás»: back through that entry instead of stacking one —
    `step_address_script`), then `settle_step`. ``params`` are kept before ``paso``
    (`volver=…`)."""
    target = json.dumps(step_url(path, n, **params))
    script = step_address_script(target, back) + step_settle_script(scope)
    return rx.call_script(script)

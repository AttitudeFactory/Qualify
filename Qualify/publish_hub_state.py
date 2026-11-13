"""Navigation of «Publicar ahora» (`/publish`): which step shows, the address, the
ideas panel and the «¿Salir mientras se publican?» guard.

The data — files, mode, order, descriptions, account, the run — lives in
`PublishState` (`publishing_state.py`), including the current step id (`step`), because
the number of steps changes live with the selection (spec
`docs/mockups/publicar-varias-imagenes.md` §1: «M cambia en vivo»). This state only
moves that cursor, keeps `?paso=N` (and `?flow=stories`) in step with it, and guards
leaving while pieces are still going out (spec §4.2).

What still holds from before (QUA-113, PUBLICAR-4):

- **The trending panel follows the chosen account** (`TrendingState.follow_connection`).
- **The address follows the kind** (`?flow=stories`) without a navigation;
  `/stories` redirects to `/publish?flow=stories`, which arrives with historia chosen.
- **Nothing moves while publishing**; entering the page then shows the review step.
"""

from __future__ import annotations

import reflex as rx

from .publish_wizard_vm import (
    FLOW_POSTS,
    FLOW_STORIES,
    MODE_POST,
    MODE_STORIES,
    MODE_STORY,
    STEP_REVIEW,
    STEP_WHAT,
    can_advance,
    is_series,
    is_story_mode,
    next_step,
    previous_step,
    step_number,
)
from .publishing_state import PublishState
from .trending_state import TrendingState
from .ui.steps import go_to_step, step_entry_script, step_settle_script
from .ui.steps_vm import DIR_BACK, DIR_NEXT, guard_step, parse_step_param, step_direction

_FLOW_URLS = {FLOW_POSTS: "/publish", FLOW_STORIES: "/publish?flow=stories"}
_LEAVE_TARGET = "window.__qPubLeaveHref || '/'"
# While pieces are going out, a click on any link outside the assistant (the menu,
# «‹ Inicio») asks first (spec §4.2). Installed once; it acts only while the hidden
# button `#q-pub-leave-ask` exists — it is rendered only during a run.
_LINK_GUARD = """
(function () {
  if (window.__qPubLinkGuard) return;
  window.__qPubLinkGuard = true;
  document.addEventListener('click', function (e) {
    var ask = document.getElementById('q-pub-leave-ask');
    if (!ask) return;
    var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (!a || a.target === '_blank') return;
    e.preventDefault();
    e.stopPropagation();
    window.__qPubLeaveHref = a.getAttribute('href');
    ask.click();
  }, true);
})();
"""


def resolve_flow(requested: str | None) -> str:
    """The kind a `?flow=` value asks for — anything but `stories` is a publication."""
    return FLOW_STORIES if (requested or "").strip().lower() == FLOW_STORIES else FLOW_POSTS


def _replace_url_script(flow: str) -> str:
    # `replaceState`, not a navigation: a navigation would re-run on_load for what is
    # only a change of kind. Keeps react-router's own `history.state` untouched.
    return (
        "window.history.replaceState(window.history.state, '', "
        f"'{_FLOW_URLS[flow]}'+"
        "(new URL(window.location.href).searchParams.has('paso') ? "
        f"'{('&' if flow == FLOW_STORIES else '?')}paso=' + "
        "new URL(window.location.href).searchParams.get('paso') : ''))"
    )


def link_guard_script() -> str:
    return _LINK_GUARD


class PublishHubState(rx.State):
    """The assistant's motion and its leave guard — see the module docstring. Never
    holds a file, an account or a description."""

    direction: str = DIR_NEXT
    entered: bool = False
    entry_epoch: int = 0
    resume_pending: bool = False
    show_ideas: bool = False
    #: «¿Salir mientras se publican?» (spec §4.2) and «¿Dejar el mural sin terminar?».
    leave_open: bool = False
    keep_open: bool = False

    def _flow(self, posts: PublishState) -> str:
        return FLOW_STORIES if is_story_mode(posts.mode) else FLOW_POSTS

    @rx.event
    async def enter_publish_page(self) -> list[rx.event.EventSpec]:
        """`/publish` on_load: the kind from `?flow=`, back to step 1 — or to the review
        while a run goes on, so its progress is not hidden — a lingering «listo»
        cleared, and the trending panel pointed at the chosen account. A run waiting
        for «Continuar» shows «Te quedaron…» above step 1."""
        posts = await self.get_state(PublishState)
        self.show_ideas = False
        self.leave_open = False
        self.keep_open = False
        events: list[rx.event.EventSpec] = []
        if posts.phase in ("success", "partial"):
            posts.reset_form()
        if posts.phase == "running":
            posts.step = STEP_REVIEW
        elif not self.resume_pending:
            posts.step = STEP_WHAT
            if posts.phase == "idle" and resolve_flow(self._requested_flow()) == FLOW_STORIES:
                posts.kind_single = MODE_STORY
                posts.kind_many = MODE_STORIES
            requested = self._requested_step()
            if requested is not None:
                posts.step = self._guarded_step(requested, posts)
        self.direction = DIR_NEXT
        self.entered = True
        self.resume_pending = False
        events.append(TrendingState.follow_connection(posts.selected_connection_id))
        events.append(self._entry_event(posts))
        return events

    @rx.event
    async def select_kind(self, kind: str) -> list[rx.event.EventSpec] | None:
        """Step 2's choice; the address follows it (`?flow=stories` for historias)."""
        posts = await self.get_state(PublishState)
        if not isinstance(kind, str) or posts.mode == kind or not posts.choose_kind(kind):
            return None
        return [
            TrendingState.follow_connection(posts.selected_connection_id),
            rx.call_script(_replace_url_script(self._flow(posts))),
        ]

    @rx.event
    async def go_next(self) -> rx.event.EventSpec | None:
        """«Siguiente»: one step forward when the current one is complete."""
        posts = await self.get_state(PublishState)
        if posts.phase == "running":
            return None
        current = posts.step_id
        posts.step = next_step(current, posts.steps, can_go=posts.can_go)
        self.direction = DIR_NEXT
        return self._step_event(posts)

    @rx.event
    async def go_back(self) -> rx.event.EventSpec | None:
        """«Atrás»: one step back, nothing chosen is lost. Not while publishing."""
        posts = await self.get_state(PublishState)
        if posts.phase == "running":
            return None
        posts.step = previous_step(posts.step_id, posts.steps)
        self.direction = DIR_BACK
        return self._step_event(posts, back=True)

    @rx.event
    async def go_to(self, step: str) -> rx.event.EventSpec | None:
        """Jump to `step` (only to one already reached — «Continuar» on «Te quedaron…»
        goes to the review)."""
        posts = await self.get_state(PublishState)
        if posts.phase == "running" or step not in posts.steps:
            return None
        self.direction = DIR_NEXT
        posts.step = step
        return self._step_event(posts)

    @rx.event
    async def continue_or_publish(self) -> list[rx.event.EventSpec] | rx.event.EventSpec | None:
        """The fixed primary: «Siguiente» before the review; on it, publish — or, for a
        run waiting to be continued, «Continuar»."""
        posts = await self.get_state(PublishState)
        if posts.step_id != STEP_REVIEW:
            return await PublishHubState.go_next.fn(self)
        if posts.phase == "running":
            return None
        if posts.resumable:
            return posts.continue_run()
        return posts.publish()

    @rx.event
    async def resume_leftover(self) -> list[rx.event.EventSpec] | None:
        """«Continuar» on «Te quedaron…»: straight to the progress, and on."""
        posts = await self.get_state(PublishState)
        if not posts.resumable:
            return None
        posts.step = STEP_REVIEW
        self.direction = DIR_NEXT
        started = posts.continue_run() or []
        return [*started, self._step_event(posts)]

    @rx.event
    async def start_over(self) -> list[rx.event.EventSpec]:
        """«Publicar otra» / «Descartar»: an empty step 1 again, as a publication."""
        posts = await self.get_state(PublishState)
        posts.reset_form()
        posts.kind_single = MODE_POST
        self.show_ideas = False
        self.direction = DIR_BACK
        self.entered = True
        self.resume_pending = False
        return [rx.call_script(_replace_url_script(FLOW_POSTS)), self._step_event(posts, back=True)]

    # -- leaving -------------------------------------------------------------------------

    @rx.event
    async def leave(self) -> rx.event.EventSpec | None:
        """«‹ Inicio» / «Seguir después». While pieces are going out, ask first."""
        posts = await self.get_state(PublishState)
        if posts.phase == "running":
            if is_series(posts.run_mode) and posts.run_total > 1:
                self.leave_open = True
            return None
        self.resume_pending = True
        return rx.redirect("/")

    @rx.event
    def ask_leave(self) -> None:
        """A link outside the assistant was clicked during a run (`_LINK_GUARD`)."""
        self.leave_open = True

    @rx.event
    def stay(self) -> None:
        """«Seguir aquí»."""
        self.leave_open = False

    @rx.event
    async def leave_anyway(self) -> rx.event.EventSpec:
        """«Salir igual»: the piece going out now finishes, the rest wait («Te
        quedaron…» when the owner comes back)."""
        posts = await self.get_state(PublishState)
        posts.request_stop()
        self.leave_open = False
        self.resume_pending = False
        return rx.call_script(_LEAVE_TARGET, callback=PublishHubState.go_away)

    @rx.event
    def go_away(self, href: str) -> rx.event.EventSpec:
        target = href if isinstance(href, str) and href.startswith("/") else "/"
        return rx.redirect(target)

    @rx.event
    async def ask_keep_as_is(self) -> rx.event.EventSpec | None:
        """«Dejar así» — a mural asks first (spec §4.3); historias end at once."""
        posts = await self.get_state(PublishState)
        if posts.run_mode == MODE_STORIES:
            return posts.keep_as_is()
        self.keep_open = True
        return None

    @rx.event
    async def confirm_keep_as_is(self) -> rx.event.EventSpec | None:
        posts = await self.get_state(PublishState)
        self.keep_open = False
        return posts.keep_as_is()

    @rx.event
    def cancel_keep_as_is(self) -> None:
        self.keep_open = False

    # -- the address -----------------------------------------------------------------------

    def _step_event(self, posts: PublishState, *, back: bool = False) -> rx.event.EventSpec:
        return go_to_step(
            "/publish",
            step_number(posts.step, posts.steps),
            back=back,
            flow=FLOW_STORIES if self._flow(posts) == FLOW_STORIES else "",
        )

    def _requested_step(self) -> object:
        try:
            return self.router.url.query_parameters.get("paso")
        except Exception:  # noqa: BLE001 — no router in offline state tests
            return None

    def _requested_flow(self) -> str | None:
        try:
            return self.router.url.query_parameters.get("flow")
        except Exception:  # noqa: BLE001 — no router in offline state tests
            return None

    def _guarded_step(self, requested: object, posts: PublishState) -> str:
        """A deep link (`?paso=N`) never skips a step the owner has not answered (N6b)."""
        steps = posts.steps
        complete = [
            can_advance(
                step,
                file_count=len(posts.pending_items),
                mode=posts.mode,
                connection_id=posts.selected_connection_id,
            )
            for step in steps
        ]
        number = guard_step(parse_step_param(requested, len(steps)), complete)
        return steps[number - 1]

    @rx.event
    async def read_step(self) -> rx.event.EventSpec | None:
        """The browser's «atrás» restores a guarded step without clearing anything; during
        a run it stays on the review and asks first (spec §4.2)."""
        posts = await self.get_state(PublishState)
        if posts.phase == "running":
            posts.step = STEP_REVIEW
            if is_series(posts.run_mode) and posts.run_total > 1:
                self.leave_open = True
            return self._step_event(posts)
        old = step_number(posts.step, posts.steps)
        posts.step = self._guarded_step(self._requested_step(), posts)
        self.direction = step_direction(old, step_number(posts.step, posts.steps), self.direction)
        return self._entry_event(posts)

    def _entry_event(self, posts: PublishState) -> rx.event.EventSpec:
        self.entry_epoch += 1
        raw = self._requested_step()
        return rx.call_script(
            step_entry_script(
                "/publish",
                step_number(posts.step, posts.steps),
                self.entry_epoch,
                str(raw) if raw is not None else None,
            )
            + step_settle_script()
        )

    @rx.event
    def leave_frame(self) -> None:
        self.entered = False

    @rx.event
    def toggle_ideas(self) -> None:
        self.show_ideas = not self.show_ideas

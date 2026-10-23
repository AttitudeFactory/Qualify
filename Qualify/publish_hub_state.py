"""Reflex state for «Publicar ahora» (`/publish`) — since PUBLICAR-4 (m-24842986) a
three-step assistant: ① ¿Qué vas a publicar? (files, buffered in `PublishState`
whatever they end up being) ② ¿Dónde sale? (publication or historia, and the account —
one picker, `PublishState`'s) ③ Revisa y publica. It ends with a persistent «listo» and
the next step (N3). This state owns the step, the kind chosen in step 2
(`active_flow`) and whether the ideas panel is open; the two publish machines stay
`PublishState` (publication, 1-10 files) and `StoriesState` (historia, one file). When
the owner publishes a historia, `publish_now` hands the one buffered file and the
account to `StoriesState` server-side, so nothing is picked twice.

Before PUBLICAR-4 (QUA-113, Fase 2) this was only a `Publicaciones | Stories` selector
over two independent forms; what still holds from then:

- **The trending panel follows the chosen account**
  (`TrendingState.follow_connection`) — Meta's `ig_audio` needs a credential. Since
  PUBLICAR-4 there is one account picker, so it is always `PublishState`'s.
- **The URL follows the flow** (`?flow=stories`) without a navigation, so a reload or
  a shared link lands on the same flow. `/stories` redirects to `/publish?flow=stories`.
- **No switch while a publish is in flight** (staging or waiting for Meta), so the
  status of a running publish is never hidden behind the other flow.
"""

from __future__ import annotations

import reflex as rx

from .publish_wizard_vm import (
    FLOW_POSTS,
    FLOW_STORIES,
    SCROLL_TO_ASSISTANT,
    STEP_REVIEW,
    STEP_WHAT,
    done_message,
    next_step,
    previous_step,
)
from .publishing_state import PublishState
from .stories_state import StoriesState
from .trending_state import TrendingState

__all__ = ["FLOW_POSTS", "FLOW_STORIES", "PublishHubState", "can_switch_flow", "resolve_flow"]

# The phases in which a flow has nothing in flight — same vocabulary both
# `PublishState.phase` and `StoriesState.phase` use.
_RESTING_PHASES = ("idle", "success", "failure")

_FLOW_URLS = {FLOW_POSTS: "/publish", FLOW_STORIES: "/publish?flow=stories"}


def resolve_flow(requested: str | None) -> str:
    """The flow a `?flow=` value asks for — anything but `stories` (missing, empty,
    misspelled) is the default, Publicaciones."""
    return FLOW_STORIES if (requested or "").strip().lower() == FLOW_STORIES else FLOW_POSTS


def can_switch_flow(posts_phase: str, stories_phase: str) -> bool:
    """False while either flow has a publish in flight."""
    return posts_phase in _RESTING_PHASES and stories_phase in _RESTING_PHASES


def _replace_url_script(flow: str) -> str:
    # `replaceState`, not a navigation: a navigation would re-run `/publish`'s on_load
    # (and reload accounts) for what is only a change of view. Keeps react-router's
    # own `history.state` so its back/forward bookkeeping is untouched.
    return f"window.history.replaceState(window.history.state, '', '{_FLOW_URLS[flow]}')"


class PublishHubState(rx.State):
    """The step, the kind chosen in step 2 and the ideas panel of `/publish` — see
    the module docstring. Never holds a file, an account or a caption."""

    active_flow: str = FLOW_POSTS
    step: int = STEP_WHAT
    #: «Ideas para tu próxima publicación» — the trending panel, outside the steps.
    show_ideas: bool = False
    #: The network the last publish went to, captured in `publish_now` (the flows
    #: clear their account on success) so the «listo» can name it.
    published_platform: str = "instagram"

    @rx.event
    async def enter_publish_page(self) -> list[rx.event.EventSpec]:
        """`/publish` on_load: the kind from `?flow=` (default publication), back to
        step 1 — or to step 3 when a publish is still running, so its progress is not
        hidden — a lingering «listo» from an earlier visit cleared, and the trending
        panel pointed at the chosen account."""
        flow = resolve_flow(self._requested_flow())
        self.active_flow = flow
        self.show_ideas = False
        posts = await self.get_state(PublishState)
        stories = await self.get_state(StoriesState)
        events: list[rx.event.EventSpec] = [StoriesState.invalidate_connections]
        if not can_switch_flow(posts.phase, stories.phase):
            self.step = STEP_REVIEW
        else:
            self.step = STEP_WHAT
            if posts.phase == "success":
                events.append(PublishState.reset_form)
            if stories.phase == "success":
                events.append(StoriesState.reset_form)
        events.append(TrendingState.follow_connection(posts.selected_connection_id))
        return events

    @rx.event
    async def select_flow(self, flow: str | list[str]) -> list[rx.event.EventSpec] | None:
        """Step 2's «Publicación en tu perfil» / «Historia (24 h)» was chosen. A no-op
        for an unknown value, for the kind already chosen, or while a publish is in
        flight in either flow. `flow` is typed `str | list[str]` because the old
        segmented control's `on_change` contract allowed a list; a list is never valid."""
        if not isinstance(flow, str) or flow not in _FLOW_URLS or flow == self.active_flow:
            return None
        posts = await self.get_state(PublishState)
        stories = await self.get_state(StoriesState)
        if not can_switch_flow(posts.phase, stories.phase):
            return None
        self.active_flow = flow
        return [
            TrendingState.follow_connection(posts.selected_connection_id),
            rx.call_script(_replace_url_script(flow)),
        ]

    @rx.event
    async def go_next(self) -> rx.event.EventSpec | None:
        """«Siguiente»: one step forward when the current one is complete (the button is
        also disabled otherwise — this is the server-side guard)."""
        posts = await self.get_state(PublishState)
        stories = await self.get_state(StoriesState)
        if not can_switch_flow(posts.phase, stories.phase):
            return None
        self.step = next_step(
            self.step,
            file_count=len(posts.pending_items),
            flow=self.active_flow,
            connection_id=posts.selected_connection_id,
        )
        return rx.call_script(SCROLL_TO_ASSISTANT)

    @rx.event
    async def go_back(self) -> rx.event.EventSpec | None:
        """«Atrás»: one step back, nothing chosen is lost (every step stays mounted and
        every choice lives in state). Not while a publish is in flight."""
        posts = await self.get_state(PublishState)
        stories = await self.get_state(StoriesState)
        if not can_switch_flow(posts.phase, stories.phase):
            return None
        self.step = previous_step(self.step)
        return rx.call_script(SCROLL_TO_ASSISTANT)

    @rx.event
    async def publish_now(self) -> rx.event.EventSpec | None:
        """Step 3's «Publicar»: a publication goes through `PublishState.publish`; a
        historia first hands the one buffered file and the account to `StoriesState`
        (server-side — the bytes never travel through the browser), then
        `StoriesState.publish`. Both keep their own double-submit guard."""
        posts = await self.get_state(PublishState)
        stories = await self.get_state(StoriesState)
        if self.step != STEP_REVIEW or not can_switch_flow(posts.phase, stories.phase):
            return None
        self.published_platform = posts.selected_platform or "instagram"
        if self.active_flow != FLOW_STORIES:
            return PublishState.publish
        if len(posts._pending_files) != 1 or not posts.selected_connection_id:
            return None
        pending = posts._pending_files[0]
        adopted = stories.adopt_file(
            filename=pending.filename,
            content_type=pending.content_type,
            data=pending.data,
            connection_id=posts.selected_connection_id,
        )
        return StoriesState.publish if adopted else None

    @rx.event
    def start_over(self) -> list[rx.event.EventSpec]:
        """«Publicar otra»: an empty step 1 again, as a publication."""
        self.step = STEP_WHAT
        self.show_ideas = False
        events: list[rx.event.EventSpec] = [PublishState.reset_form, StoriesState.reset_form]
        if self.active_flow != FLOW_POSTS:
            self.active_flow = FLOW_POSTS
            events.append(rx.call_script(_replace_url_script(FLOW_POSTS)))
        return events

    @rx.event
    def toggle_ideas(self) -> None:
        self.show_ideas = not self.show_ideas

    @rx.var
    def done_text(self) -> str:
        """The «listo» for the kind just published (N3) — see `publish_wizard_vm`."""
        return done_message(self.active_flow, platform=self.published_platform)

    def _requested_flow(self) -> str | None:
        return self.router.url.query_parameters.get("flow")

"""Reflex state for the `/publish` flow selector (QUA-113, Fase 2) — "Publicar" is the
one module for immediate publishing, with two INDEPENDENT flows inside it:
Publicaciones (`PublishState`) and Stories (`StoriesState`).

This state owns exactly one thing: which flow is active. It never holds a file, an
account, a caption or a publish attempt — each flow keeps its own, untouched by a
switch, so going Publicaciones → Stories → Publicaciones finds everything where the
operator left it. What a switch DOES do:

- **Stories accounts load on demand**: the first time the Stories flow is entered on
  a visit, `StoriesState.ensure_connections_loaded` queries them; later switches are
  free. Entering `/publish` itself only marks them stale (`invalidate_connections`).
- **The trending panel follows the active flow's account**
  (`TrendingState.follow_connection`) — Meta's `ig_audio` needs a credential, and it
  must be the one of the flow the operator is looking at.
- **The URL follows the flow** (`?flow=stories`) without a navigation, so a reload or
  a shared link lands on the same flow. `/stories` redirects to `/publish?flow=stories`.
- **No switch while a publish is in flight** (staging or waiting for Meta), so the
  status of a running publish is never hidden behind the other flow.
"""

from __future__ import annotations

import reflex as rx

from .publishing_state import PublishState
from .stories_state import StoriesState
from .trending_state import TrendingState

FLOW_POSTS = "posts"
FLOW_STORIES = "stories"

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
    """Which publish flow `/publish` is showing — nothing else. See module docstring."""

    active_flow: str = FLOW_POSTS

    @rx.event
    async def enter_publish_page(self) -> list[rx.event.EventSpec]:
        """`/publish` on_load: pick the flow from `?flow=` (default Publicaciones),
        mark the Stories accounts stale so this visit reloads them if Stories gets
        entered, load them right away only if the visit STARTS on Stories, and point
        the trending panel at the active flow's account."""
        flow = resolve_flow(self._requested_flow())
        self.active_flow = flow
        events: list[rx.event.EventSpec] = [StoriesState.invalidate_connections]
        if flow == FLOW_STORIES:
            events.append(StoriesState.ensure_connections_loaded)
        events.append(TrendingState.follow_connection(await self._flow_connection_id(flow)))
        return events

    @rx.event
    async def select_flow(self, flow: str | list[str]) -> list[rx.event.EventSpec] | None:
        """The selector was clicked. A no-op for an unknown value, for the flow that is
        already active, or while a publish is in flight in either flow — the selector
        is also visually disabled then, this is the server-side guard. `flow` is typed
        `str | list[str]` because that is the segmented control's `on_change` contract;
        this selector is single-choice, so a list is never a valid flow."""
        if not isinstance(flow, str) or flow not in _FLOW_URLS or flow == self.active_flow:
            return None
        posts = await self.get_state(PublishState)
        stories = await self.get_state(StoriesState)
        if not can_switch_flow(posts.phase, stories.phase):
            return None
        self.active_flow = flow
        events: list[rx.event.EventSpec] = []
        if flow == FLOW_STORIES:
            events.append(StoriesState.ensure_connections_loaded)
        connection_id = (
            stories.selected_connection_id if flow == FLOW_STORIES else posts.selected_connection_id
        )
        events.append(TrendingState.follow_connection(connection_id))
        events.append(rx.call_script(_replace_url_script(flow)))
        return events

    def _requested_flow(self) -> str | None:
        return self.router.url.query_parameters.get("flow")

    async def _flow_connection_id(self, flow: str) -> str:
        state_cls = StoriesState if flow == FLOW_STORIES else PublishState
        flow_state = await self.get_state(state_cls)
        return flow_state.selected_connection_id

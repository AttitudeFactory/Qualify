"""View-models for the publish screen (A5 vertical slice).

Same security boundary as `connections_vm.py`: every Reflex var is serialized to the
client. `PublishService` never sees or returns a token to begin with, so there is nothing
credential-bearing to keep off these dataclasses in the first place — the whitelist test
(`test_publishing_ui.py`) pins that this stays true as the module grows.

Kept free of Reflex and network imports so the whitelist can be asserted by a plain unit
test, same convention as `connections_vm.py`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionOptionVM:
    """The minimal projection of an active `ConnectionVM` the selector needs.

    Deliberately narrower than `ConnectionVM` — this screen has no use for capabilities,
    scopes or verification timestamps, only "which account can I publish to right now".
    """

    id: str
    external_username: str
    platform: str
    # PUBLICAR-4 UX review: «@cuenta · Instagram», the same words step 3's review
    # sentence uses. Computed by the provider (`rx.foreach` cannot call Python); empty
    # for callers that do not show a selector label.
    label: str = ""


@dataclass(frozen=True)
class PendingItemVM:
    """One file buffered locally, not yet published (gallery redesign, QUA-99 follow-up;
    `kind` added QUA-103).

    Deliberately NO bytes/content_type here — those stay on `_PendingFile`
    (`publishing_state.py`, backend-only, never reaches the client). This is the display
    projection `rx.foreach` renders in the grid: a filename, a `kind`, and nothing else.
    Position in the carousel is NOT a field here — it is the item's index in
    `PublishState.pending_items`, which `rx.foreach` already hands the renderer, so there
    is only one place order lives, never two that could drift apart.

    `kind` is `"image"` or `"video"` — the UI's own display vocabulary (lowercase,
    English words), deliberately NOT the same strings as `MediaItem.media_type`
    (`"IMAGE"`/`"VIDEO"`, Meta's vocabulary) — this field exists only so the gallery
    (`publishing_page.py`) knows which thumbnail strategy to use per tile, never reaches
    a Meta call, and reusing the backend's exact vocabulary here would blur that boundary.
    """

    filename: str
    kind: str


@dataclass(frozen=True)
class ChildStatusVM:
    """Display projection of one carousel child's progress (QUA-99 UX follow-up) — the
    Reflex-side counterpart of `qualify_api.publishing.service.ChildStatus`. Same two
    fields, copied rather than imported: this module stays free of `qualify_api` imports
    (`connections_vm.py`'s convention), and the whitelist test below pins it stays free of
    anything credential-bearing as the module grows.
    """

    position: int
    status: str


@dataclass(frozen=True)
class PublishAttemptVM:
    """Display-ready projection of a `PublishService` `PublishState`.

    `published_media_id`/`reason` are pre-coerced to `""` when absent (never `None`) —
    same "no raw nullable reaching the client" convention `ConnectionVM.last_verified_at`
    already uses.
    """

    attempt_id: str
    status: str
    settled: bool
    published_media_id: str
    reason: str
    awaiting_confirmation: bool
    poll_interval_seconds: int

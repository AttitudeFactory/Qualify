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
    # 2026-11-12 (founder): only Instagram can be chosen in «Publicar»; a Facebook
    # account is listed switched off with `note` (its reason, shown inside the card).
    selectable: bool = True
    note: str = ""
    #: «@cuenta», as the account card names it.
    handle: str = ""


@dataclass(frozen=True)
class PendingItemVM:
    """One file in the owner's list, not yet published — the ONE list every step
    renders (gallery, order, mural, descriptions, progress), in the owner's order.

    Deliberately NO bytes/content_type here — those stay on `_PendingFile`
    (`publishing_state.py`, backend-only, never reaches the client). `kind` is `"image"`
    or `"video"` (the UI's display vocabulary, not Meta's). `id` is stable across moves
    (what «⋯», the drag and the descriptions key on); `number` is the file's own number
    («Foto 3»), kept when it moves; `position` is where it sits now (1-based) of `total`.
    `status` is its publish state (`publish_wizard_vm.STATUS_*`) with its word and tone.
    """

    filename: str
    kind: str
    id: str = ""
    number: int = 0
    label: str = ""
    position: int = 0
    total: int = 0
    status: str = "waiting"
    status_label: str = ""
    status_tone: str = "neutral"
    handle_label: str = ""
    more_label: str = ""
    caption_label: str = ""
    #: «Publicación 2 de 4» (one by one, by position).
    publication_title: str = ""


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

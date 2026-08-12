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

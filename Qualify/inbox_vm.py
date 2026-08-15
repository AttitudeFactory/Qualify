"""View-models for the inbox content screen — Instagram Reels from the last 2 weeks,
with the monitoring toggle (Fase 1 Parte 4-B, B2 UI slice).

Same security boundary as `publishing_vm.py`/`connections_vm.py`: every Reflex var is
serialized to the client. `InboxService`/`qualify_api.inbox.composition` never see or
return a token, so nothing credential-bearing can reach this dataclass in the first
place — the whitelist test (`test_inbox_ui.py`) pins that this stays true as the module
grows.

Kept free of Reflex and network imports so the whitelist can be asserted by a plain unit
test, same convention as `publishing_vm.py`/`connections_vm.py`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateMediaVM:
    """Display-ready projection of one `qualify_api.inbox.service.CandidateMedia`.

    `caption`/`permalink`/`thumbnail_url` are pre-coerced to `""` when absent (never
    `None`) — same "no raw nullable reaching the client" convention `ConnectionVM.
    last_verified_at`/`PublishAttemptVM.reason` already use.
    """

    external_media_id: str
    posted_at: str  # PRE-FORMATTED server-side (never a raw datetime var)
    is_monitored: bool
    caption: str
    permalink: str
    thumbnail_url: str

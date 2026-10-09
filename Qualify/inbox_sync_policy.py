"""When a comment sync should run — pure decisions, no Reflex, no I/O.

`InboxState.sync_comments` gathers the facts (who triggered it, whether this tab still
believes a pass is in flight, whether that pass is still alive, how long ago the last
pass finished) and asks these functions what to do. Keeping them pure is what lets the
rules be tested directly; the handler itself cannot run outside a live Reflex app.

## Triggers

- `manual` — the "Sincronizar comentarios" button. Never subject to the cooldown.
- `poll` — the 5-minute client-side timer (QUA-89). Subject to the cooldown.
- `open` — the screen was opened, or another account was picked. Subject to the cooldown.
- `monitor` — monitoring was just turned ON for a media. Never subject to the cooldown:
  that media has never been synced, so the last pass says nothing about it.

Every trigger shares the same one-pass-per-connection lease (`qualify_api.inbox.
sync_guard`), so the cooldown only trims REDUNDANT automatic passes; it is not the guard
against concurrency, and the Meta call budget stays `InboxService`'s job.
"""

from __future__ import annotations

from typing import Final, Literal

SyncTrigger = Literal["manual", "poll", "open", "monitor"]

TRIGGERS: Final[tuple[SyncTrigger, ...]] = ("manual", "poll", "open", "monitor")

# Automatic triggers skip a pass when another finished this recently on the connection.
COOLDOWN_SECONDS: Final = 60.0
_COOLDOWN_TRIGGERS: Final = frozenset({"poll", "open"})

# A tab's `is_syncing` claim is never treated as stale while it is this young: between the
# claim and the backend taking the lease there is a short window in which the lease does
# not exist yet, and "no lease" must not be misread as "dead" during it.
CLAIM_GRACE_SECONDS: Final = 15.0


def normalize_trigger(raw: object) -> SyncTrigger:
    """Unknown values (an old client, a typo) count as `manual`: the one trigger that is
    never skipped for being redundant, so a bad label can only cost a pass, not lose one."""
    return raw if raw in TRIGGERS else "manual"  # type: ignore[return-value]


def claim_is_stale(*, run_id: str, run_alive: bool, claimed_at: float, now: float) -> bool:
    """Whether this tab's leftover `is_syncing` may be cleared. Only when the backend says
    the run no longer holds its lease (no process is executing it — the lease is renewed
    while a pass runs, see `sync_guard.py`) AND the claim is past the grace window. Age
    alone never releases it.

    A claim with NO run id is always stale: every run claims with its id, so an empty one
    can only be a flag persisted by code from before run ids existed — no lease can back
    it, and without this it would never clear (the button would stay disabled and every
    poll would skip)."""
    if not run_id:
        return True
    return not run_alive and (now - claimed_at) >= CLAIM_GRACE_SECONDS


def skip_for_cooldown(trigger: SyncTrigger, seconds_since_last: float | None) -> bool:
    """Whether an automatic trigger should skip because a pass just finished. Unknown age
    (`None`: nothing in the last hour, or Redis unreachable) never skips."""
    return (
        trigger in _COOLDOWN_TRIGGERS
        and seconds_since_last is not None
        and seconds_since_last < COOLDOWN_SECONDS
    )

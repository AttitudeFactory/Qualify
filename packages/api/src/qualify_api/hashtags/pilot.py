"""The weekly TikTok hashtag read as a ONE-BUSINESS PILOT inside the reels worker
(m-25026378, epic m-25026375; founder decision D3, 2026-11-14, «option C — inside the
reels worker, pilot with Bianki», `docs/epica-etiquetas-publicaciones.md`).

The `--all-tenants` reels worker (`qualify_api.referentes.worker`) calls `run_pilot` every
six hours, the way it runs its daily purge (`ReelsWorker.pass_once`, step 7); each
business is still read at most once a week. What it reads is
`weekly.run_tick` over an explicit list of businesses — every guard of that pass applies
unchanged (5 credits per business in any 7 days, a hashtag kept this week is not read
again, one attempt a day, the headroom rule, the claims, the gate's switches and floor).
The standalone CLI's `--all-tenants` (`qualify_api.hashtags.worker`) reads this same list.

**Who is read: an allowlist, failing closed.** `QUALIFY_HASHTAG_WEEKLY_TENANTS` holds the
pilot businesses' tenant UUIDs, separated by commas:

- only the listed businesses are read, and a listed business is read whether or not the
  reels worker treats it as active (the 14-day «Ideas para tus reels» gate does not apply,
  exactly like `python -m qualify_api.hashtags.worker --tenant`);
- unset or empty means NO business is read, even with `QUALIFY_HASHTAG_WEEKLY_READ` on;
- an entry that is not a UUID is skipped and logged (by count, never by value): a typo
  never reads anyone.

There is deliberately no «everyone» value. Opening the read to every business — and
deciding which businesses count as active for it — is a later decision of the founder
(D3), not this pilot's.

With `QUALIFY_HASHTAG_WEEKLY_READ` off the call returns before parsing the list: no
database read, no vendor call. `should_stop` (the reels worker's stop signal) is checked
between businesses and between hashtags, so a deploy's SIGTERM waits at most for the one
read in flight (bounded by the vendor client's timeout).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from qualify_api.hashtags import weekly

logger = logging.getLogger(__name__)

#: The pilot's allowlist: tenant UUIDs separated by commas. Empty or unset = nobody.
TENANTS_ENV = "QUALIFY_HASHTAG_WEEKLY_TENANTS"

#: `TickReport.stopped` when the switch is on but the allowlist names nobody.
NO_PILOT_TENANTS = "no_pilot_tenants"


class Tick(Protocol):
    def __call__(
        self,
        tenant_ids: Sequence[UUID] | None,
        *,
        now: datetime | None = None,
        env: Mapping[str, str] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> weekly.TickReport: ...


def pilot_tenants(env: Mapping[str, str] | None = None) -> list[UUID]:
    """The listed businesses, deduplicated in order. Anything that is not a UUID is
    skipped; how many were skipped is logged, never their values."""
    raw = (env if env is not None else os.environ).get(TENANTS_ENV, "")
    out: list[UUID] = []
    invalid = 0
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            tenant = UUID(piece)
        except ValueError:
            invalid += 1
            continue
        if tenant not in out:
            out.append(tenant)
    if invalid:
        logger.warning(
            "hashtags.pilot %s: ignored %d entries that are not UUIDs", TENANTS_ENV, invalid
        )
    return out


def run_pilot(
    now: datetime,
    *,
    should_stop: Callable[[], bool],
    env: Mapping[str, str] | None = None,
    tick: Tick | None = None,
) -> weekly.TickReport:
    """One weekly-read pass over the pilot businesses (see the module docstring). Returns
    `stopped="switch_off"` with the switch off and `stopped=NO_PILOT_TENANTS` with an
    empty allowlist — in both cases before anything is read."""
    if not weekly.switch_on(env):
        return weekly.TickReport(stopped="switch_off")
    tenants = pilot_tenants(env)
    if not tenants:
        logger.info("hashtags.pilot not run: %s names no business", TENANTS_ENV)
        return weekly.TickReport(stopped=NO_PILOT_TENANTS)
    return (tick or weekly.run_tick)(tenants, now=now, env=env, should_stop=should_stop)


__all__ = ["NO_PILOT_TENANTS", "TENANTS_ENV", "pilot_tenants", "run_pilot"]

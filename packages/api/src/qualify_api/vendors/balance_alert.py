"""Sends the ScrapeCreators balance alerts to the team in Lark (ADR 42 R2, m-24854847).

WHEN to alert is decided by the balance store, in the transaction that writes the balance
(`qualify_api.vendors.balance.next_alert`): `low` under 2,000 credits, `floor` under the
500-credit floor, `empty` on a 402 — each once per episode across every process, re-armed
by a top-up. This module only turns the claimed kind into a message and delivers it.

**Shipped switched off** (founder, 2026-11-04): delivery needs
`QUALIFY_SCRAPECREATORS_BALANCE_ALERTS=1` (or `true`/`on`/`yes`). Off, nothing is sent to
any channel, but the bookkeeping runs as usual: the store still claims each alert in
`alerts_sent` and the claim is logged at WARNING with its kind and credits. A claim made
while off is CONSUMED — it was logged, and turning the switch on later must not fire a
burst of stale alerts; the next alert is the next real crossing after a top-up.

Destination, in order:

1. `QUALIFY_DEVOPS_WEBHOOK_URL` (+ optional `QUALIFY_DEVOPS_WEBHOOK_SECRET`): the custom bot
   of the Lark group `Qualify-devs`, the same one the deploy notice uses
   (`.github/scripts/deploy_notify.py`). GitHub's `DEVOPS_WEBHOOK_*` secrets are not visible
   to the app, so the same values are set again in `.env.prod`.
2. Otherwise `QUALIFY_SUPPORT_WEBHOOK_URL` (+ `_SECRET`): the internal channel the app
   already uses for support requests and generation-queue alerts.
3. Neither: a warning in the log, nothing sent.

Sending never blocks or breaks the paid call: it runs on its own thread, through
`qualify_api.support.webhook.TextWebhook` (no retries; logs only the error type — the
webhook URL is a secret). A CLI that exits right after the write (`just sc-balance-refresh`)
would kill a plain daemon thread and lose the alert for good, since the claim is already
committed; so an `atexit` hook waits for pending sends, up to `EXIT_DEADLINE_SECONDS` in
total — a hard bound, unlike the client's per-phase timeouts. The messages name no client.
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Protocol

from qualify_api.support.webhook import TextWebhook
from qualify_api.vendors.balance import (
    ALERT_EMPTY,
    ALERT_FLOOR,
    ALERT_LOW,
    FLOOR_THRESHOLD,
    LOW_BALANCE_THRESHOLD,
    BalanceChange,
)

logger = logging.getLogger(__name__)

DEVOPS_WEBHOOK_URL_ENV = "QUALIFY_DEVOPS_WEBHOOK_URL"
DEVOPS_WEBHOOK_SECRET_ENV = "QUALIFY_DEVOPS_WEBHOOK_SECRET"
SUPPORT_WEBHOOK_URL_ENV = "QUALIFY_SUPPORT_WEBHOOK_URL"
SUPPORT_WEBHOOK_SECRET_ENV = "QUALIFY_SUPPORT_WEBHOOK_SECRET"
#: Delivery switch. Unset = OFF (founder, 2026-11-04: shipped off, enabling it is a
#: tech-debt ticket). Only `1`/`true`/`on`/`yes` turn it on.
ALERTS_SWITCH_ENV = "QUALIFY_SCRAPECREATORS_BALANCE_ALERTS"
_SWITCH_ON = frozenset({"1", "true", "on", "yes"})
_REFRESH = "«just sc-balance-refresh»"


class TeamNotifier(Protocol):
    def send(self, text: str) -> bool:
        """True when the channel accepted the message. Must not raise."""
        ...


class NullTeamNotifier:
    """No channel configured: the alert is logged, nothing is sent."""

    def send(self, text: str) -> bool:
        logger.warning(
            "scrapecreators balance alert not sent: no team channel configured (set %s)",
            DEVOPS_WEBHOOK_URL_ENV,
        )
        return False


def _thousands(value: int) -> str:
    """1999 → «1.999», the way the team writes numbers."""
    return f"{value:,}".replace(",", ".")


def alert_message(kind: str, credits_remaining: int) -> str:
    """Plain Spanish for the team, with the next step."""
    if kind == ALERT_EMPTY:
        return (
            "Se acabaron los créditos de ScrapeCreators: las búsquedas de referentes y "
            f"reels están frenadas. Recargar y luego correr {_REFRESH} para que vuelvan solas."
        )
    if kind == ALERT_FLOOR:
        return (
            f"Quedan {_thousands(credits_remaining)} créditos de ScrapeCreators: por debajo "
            f"de {_thousands(FLOOR_THRESHOLD)} Qualify deja de buscar referentes y reels. "
            f"Recargar y luego correr {_REFRESH}."
        )
    if kind == ALERT_LOW:
        return (
            f"Quedan {_thousands(credits_remaining)} créditos de ScrapeCreators (menos de "
            f"{_thousands(LOW_BALANCE_THRESHOLD)}). Recargar antes de llegar a "
            f"{_thousands(FLOOR_THRESHOLD)}, donde las búsquedas se frenan."
        )
    raise ValueError(f"unknown balance alert: {kind!r}")


#: The longest a process waits at exit, in total, for alerts still being sent.
EXIT_DEADLINE_SECONDS = 10.0
_pending: set[threading.Thread] = set()
_pending_lock = threading.Lock()


def _in_background(job: Callable[[], None]) -> None:
    """Run `job` on a daemon thread that `_drain_at_exit` waits for, up to a deadline."""

    def run() -> None:
        try:
            job()
        finally:
            with _pending_lock:
                _pending.discard(thread)

    thread = threading.Thread(target=run, name="scrapecreators-balance-alert", daemon=True)
    with _pending_lock:
        _pending.add(thread)
    try:
        thread.start()
    except BaseException:
        with _pending_lock:
            _pending.discard(thread)
        raise


def _drain_at_exit() -> None:
    """At interpreter exit (atexit runs before daemon threads are stopped), give pending
    sends until one overall deadline — however the webhook client's per-phase timeouts
    (and an unbounded DNS lookup) add up, exit never waits longer than this."""
    end = time.monotonic() + EXIT_DEADLINE_SECONDS
    with _pending_lock:
        pending = list(_pending)
    for thread in pending:
        thread.join(max(0.0, end - time.monotonic()))
    if any(thread.is_alive() for thread in pending):
        logger.error("scrapecreators balance alert still sending at exit: abandoned")


atexit.register(_drain_at_exit)


class LowBalanceAlert:
    """Delivers the alert a `BalanceChange` claimed.

    `dispatch` runs the send; the default is a separate thread so the vendor call returns
    at once. Tests pass a synchronous one."""

    def __init__(
        self,
        notifier: TeamNotifier,
        *,
        dispatch: Callable[[Callable[[], None]], None] = _in_background,
        enabled: bool = True,
    ) -> None:
        self._notifier = notifier
        self._dispatch = dispatch
        self._enabled = enabled

    def observe(self, change: BalanceChange | None) -> bool:
        """Dispatch the alert `change` claimed; True when one was dispatched. Never
        raises. Switched off (`enabled=False`), the claim is only logged."""
        if change is None or change.alert is None:
            return False
        try:
            text = alert_message(change.alert, change.after)
        except ValueError:
            logger.error("scrapecreators balance alert unknown: %s", change.alert)
            return False
        if not self._enabled:
            logger.warning(
                "scrapecreators balance alert %s at %s credits (not sent: %s is off)",
                change.alert,
                change.after,
                ALERTS_SWITCH_ENV,
            )
            return False
        logger.warning("scrapecreators balance alert %s at %s credits", change.alert, change.after)

        def send() -> None:
            try:
                if not self._notifier.send(text):
                    logger.error("scrapecreators balance alert not delivered")
            except Exception as exc:  # noqa: BLE001 - an alert must never break anything
                logger.error("scrapecreators balance alert failed: %s", type(exc).__name__)

        try:
            self._dispatch(send)
        except Exception as exc:  # noqa: BLE001 - e.g. no thread could be started
            logger.error("scrapecreators balance alert not dispatched: %s", type(exc).__name__)
            return False
        return True


def production_notifier() -> TeamNotifier:
    """The Qualify-devs bot when configured, else the app's internal channel, else none."""
    for url_env, secret_env in (
        (DEVOPS_WEBHOOK_URL_ENV, DEVOPS_WEBHOOK_SECRET_ENV),
        (SUPPORT_WEBHOOK_URL_ENV, SUPPORT_WEBHOOK_SECRET_ENV),
    ):
        url = os.environ.get(url_env, "").strip()
        if url:
            return TextWebhook(url, secret=os.environ.get(secret_env, "").strip())
    return NullTeamNotifier()


def alerts_switch_on() -> bool:
    """Only `1`/`true`/`on`/`yes` turn delivery on; unset or anything else is off."""
    return os.environ.get(ALERTS_SWITCH_ENV, "").strip().lower() in _SWITCH_ON


def production_alert() -> LowBalanceAlert:
    """Off by default (founder, 2026-11-04): then no webhook is even built — neither the
    devops bot nor the support fallback — and each claim is only logged."""
    if not alerts_switch_on():
        return LowBalanceAlert(NullTeamNotifier(), enabled=False)
    return LowBalanceAlert(production_notifier())


__all__ = [
    "ALERTS_SWITCH_ENV",
    "LowBalanceAlert",
    "NullTeamNotifier",
    "TeamNotifier",
    "alert_message",
    "alerts_switch_on",
    "production_alert",
    "production_notifier",
]

"""What happens to a signature-verified WhatsApp notification (WA-03: log it).

The route (`http/whatsapp_routes.py`) owns the HTTP/HMAC contract and nothing else;
*this* seam owns "what Qualify does with a genuine event". WA-07 replaces
`log_only_sink` with persistence (`threads`/`messages` by `wamid`, raw body to R2,
`whatsapp_webhook_events` ledger) behind the same callable type, so the route and
its tests do not change when that lands.

Logging discipline: only `WAChangeSummary` fields reach a log line — WABA id, the
business's own `phone_number_id`, message/status ids and enumerations. Never
message text, never a contact name, never the user's phone number. The raw body is
passed through (WA-07 archives it) but is never logged here.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from qualify_shared.social.wa_shapes import WANotification, summarize_notification

_LOGGER = logging.getLogger(__name__)

# `(notification=..., raw_body=...) -> None`. Keyword-only at the call site so a future
# implementation can grow parameters without breaking the fakes in the route tests.
WhatsAppEventSink = Callable[..., Awaitable[None]]


async def log_only_sink(*, notification: WANotification, raw_body: bytes) -> None:
    """WA-03's acceptance criterion made executable: a real event shows up in the
    production logs, identifiers only. `raw_body` is accepted and ignored on purpose —
    the signature is the only thing that has been asserted about it so far."""
    del raw_body
    for summary in summarize_notification(notification):
        _LOGGER.info(
            "whatsapp webhook: waba=%s field=%s phone_number_id=%s messages=%d types=%s "
            "statuses=%s errors=%s",
            summary.waba_id,
            summary.field,
            summary.phone_number_id,
            len(summary.message_ids),
            ",".join(summary.message_types) or "-",
            ",".join(summary.statuses) or "-",
            ",".join(str(c) for c in summary.error_codes) or "-",
        )

"""«Por responder»: the ONE rule of when a chat waits for the business (m-25017843, BU-A1).

**Not wired yet.** Nothing in production reads this module today: `attention.counts`
(the menu counters), `home.summary.people_waiting` (Inicio) and the per-channel screens
keep their own definitions. The unified-list story **m-25017859** switches the counters,
Inicio and the list together, so the number the owner taps and the list it opens change in
the same release; `count_awaiting_sql(channel)` is the drop-in it calls from
`attention.counts`.

**Open questions — founder's call, NOT decided here** (each pinned by a test in
`test_inbox_unified_db.py`, `test_pinned_*`, so changing it is a deliberate act):

- *Old Instagram chats.* Instagram has no «Cerrar chat» (slice C9 / story BU-A13) and
  refuses replies after the 24 h window, so under this rule an Instagram chat whose newest
  message is inbound (a «gracias», a story mention) counts forever once the counters are
  wired. Options: count only while the reply window is open; require «Cerrar chat» on
  Instagram first (BU-A13); or count forever. Today: counts forever.
- *A person's reply Meta later reports `failed`* still counts as an answer (only the
  menu's failed sends bring a chat back). Today: answered.
- *WhatsApp reactions and «STOP»* are inbound messages, so they count as «the customer
  wrote». Today: they do.

**The rule** — founder's decision (ii), 2026-11-13 («Solo si pasó a persona»). A chat
counts when the business owes a reply to a person:

1. the chat is not closed (`threads.status = 'open'`);
2. the customer wrote last as far as a PERSON is concerned — the newest visible inbound
   message is newer than the newest outbound message a person sent (the owner from Qualify
   or from the channel's own app: every outbound row that is not the automatic menu's);
3. and one of:
   a. the chat was handed to a person — the customer chose «Hablar con alguien» (the
      menu's `Handoff`) or the owner took it over; both leave
      `whatsapp_thread_state.automation_paused_at` set (a resumed chat clears it);
   b. an automatic send failed — a `kind = 'automation'` row of `whatsapp_outbox` created
      since that inbound ended `failed`/`dead`, or Meta reported its message `failed`;
   c. nobody answered — the newest visible inbound is newer than every outbound, and no
      menu reply created since it is still queued (`pending`/`sending`) and younger than
      the outbox's own `STALE_AFTER`: a fresh queued reply is the menu answering, a stuck
      one (worker down) no longer hides the chat.

So a chat only the menu answered, nobody handed to a person, does NOT count; a closed chat
never counts. Instagram Direct has no menu today, so for `dm` it reduces to «open, and the
customer wrote after our last reply»; reading a chat does not clear it.

**Hidden messages («Eliminar para mí», `messages.deleted_at`).** An outbound reply counts
as a reply whether or not the owner hid it — the customer received it, and Conversaciones
still shows the chat answered. A hidden INBOUND message is ignored: hiding a customer's
message is the owner saying it needs no answer, and a chat must never wait on a message
the owner can no longer see in it (the same reading `deleted_at` has for comments Meta
removed).

**Two forms, one rule.** `awaiting_reply_sql(alias)` is the canonical boolean SQL over a
`threads` row; `awaits_reply(snapshot, now)` is the same rule over the raw facts of one
chat, the executable specification the offline tests pin. `test_inbox_unified_db.py`
seeds each case on Postgres and checks that the SQL and this function agree.

**Cost.** The rule reads every message of a candidate chat (`ix_message_thread`): a
message's instant is `COALESCE(posted_at, ingested_at)`, which no index orders, so the
scan cannot be bounded to «after the last person's reply» without a denormalised column.
Proposed follow-up migration (not in this slice): `threads.last_person_reply_at`, kept by
both outbox senders and the echo/sync ingestion, which turns condition 2 into a column
comparison and lets the counters skip answered chats without touching `messages`.

Every statement using the fragment runs in `tenant_session`: RLS scopes `messages`,
`whatsapp_outbox` and `whatsapp_thread_state`; no tenant column is filtered by hand.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from qualify_api.inbox.channels import capabilities_for
from qualify_api.whatsapp.outbox import STALE_AFTER

# `whatsapp_outbox.kind` of what the automatic menu sends (`whatsapp.models.OUTBOX_KINDS`).
AUTOMATION_KIND: Final = "automation"
# Outbox statuses: still on its way, or terminal failure (`whatsapp.outbox`).
QUEUED_STATUSES: Final = ("pending", "sending")
FAILED_STATUSES: Final = ("failed", "dead")

_INSTANT: Final = "COALESCE({m}.posted_at, {m}.ingested_at)"
_NEVER: Final = "CAST('-infinity' AS timestamptz)"

_SQL: Final = """(
  {t}.status = 'open'
  AND {t}.last_inbound_at IS NOT NULL
  AND EXISTS (
    SELECT 1
      FROM (
        SELECT max({m_instant}) FILTER (
                 WHERE aw_m.direction = 'inbound' AND aw_m.deleted_at IS NULL) AS last_in,
               max({m_instant}) FILTER (
                 WHERE aw_m.direction = 'outbound' AND aw_ob.id IS NULL) AS last_person_out,
               max({m_instant}) FILTER (WHERE aw_m.direction = 'outbound') AS last_out
          FROM messages aw_m
          LEFT JOIN whatsapp_outbox aw_ob
                 ON aw_m.direction = 'outbound'
                AND aw_ob.thread_id = aw_m.thread_id
                AND aw_ob.wamid = aw_m.external_message_id
                AND aw_ob.kind = '{automation}'
         WHERE aw_m.thread_id = {t}.id
      ) aw_f
     WHERE aw_f.last_in IS NOT NULL
       AND aw_f.last_in > COALESCE(aw_f.last_person_out, {never})
       AND (
             EXISTS (
               SELECT 1 FROM whatsapp_thread_state aw_s
                WHERE aw_s.thread_id = {t}.id AND aw_s.automation_paused_at IS NOT NULL)
          OR EXISTS (
               SELECT 1
                 FROM whatsapp_outbox aw_x
                 LEFT JOIN messages aw_xm
                        ON aw_xm.connection_id = aw_x.connection_id
                       AND aw_xm.external_message_id = aw_x.wamid
                WHERE aw_x.thread_id = {t}.id AND aw_x.kind = '{automation}'
                  AND aw_x.created_at >= aw_f.last_in
                  AND (aw_x.status IN ({failed}) OR aw_xm.delivery_status = 'failed'))
          OR (
               aw_f.last_in > COALESCE(aw_f.last_out, {never})
               AND NOT EXISTS (
                 SELECT 1 FROM whatsapp_outbox aw_q
                  WHERE aw_q.thread_id = {t}.id AND aw_q.kind = '{automation}'
                    AND aw_q.status IN ({queued})
                    AND aw_q.created_at >= aw_f.last_in
                    AND aw_q.created_at > now() - CAST('{stale_seconds} seconds' AS interval)))
       )
  )
)"""


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def awaiting_reply_sql(alias: str = "t") -> str:
    """The rule as a boolean SQL expression over the `threads` row aliased `alias`.

    Correlated subqueries only (no parameters, no tenant filter: RLS scopes them), so it
    drops into a `WHERE`, a `count(*) … WHERE` or a `SELECT … AS awaiting_reply` as is.
    Its own aliases all start with `aw_`; do not reuse that prefix around it."""
    if not alias.isidentifier() or alias.startswith("aw_"):
        raise ValueError(f"alias must be a plain identifier not starting with 'aw_': {alias!r}")
    return _SQL.format(
        t=alias,
        m_instant=_INSTANT.format(m="aw_m"),
        never=_NEVER,
        automation=AUTOMATION_KIND,
        failed=_sql_list(FAILED_STATUSES),
        queued=_sql_list(QUEUED_STATUSES),
        stale_seconds=int(STALE_AFTER.total_seconds()),
    )


def count_awaiting_sql(channel: str) -> str:
    """A scalar subquery: how many chats of `channel` wait for a reply.

    The drop-in for `attention.counts` (story m-25017859): `(… ) AS messages` with
    `channel='dm'`, `(… ) AS whatsapp` with `channel='whatsapp'`. `channel` must be an
    inbox channel (`UnknownChannel` otherwise), so the literal is never user text."""
    allowed = capabilities_for(channel).channel
    return (
        f"(SELECT count(*) FROM threads t "
        f"WHERE t.channel = '{allowed}' AND {awaiting_reply_sql('t')})"
    )


# --------------------------------------------------------------------------------------
# The executable specification
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MessageFact:
    """One message of the chat. `at` is its instant (`COALESCE(posted_at, ingested_at)`);
    `hidden` = `deleted_at` set; `automatic` = an outbound the menu sent (it has a
    `kind='automation'` outbox row)."""

    direction: str
    at: datetime
    hidden: bool = False
    automatic: bool = False


@dataclass(frozen=True)
class AutomationSend:
    """One `kind='automation'` row of `whatsapp_outbox` for the chat; `delivery_failed` =
    Meta reported its message `failed`."""

    status: str
    created_at: datetime
    delivery_failed: bool = False


@dataclass(frozen=True)
class ThreadSnapshot:
    """What the rule reads of one chat. (The SQL also requires `threads.last_inbound_at`,
    which every inbound ingestion bumps — the 24 h window rests on it — as a cheap
    pre-filter; a chat with a visible inbound message always has it.)"""

    status: str
    messages: Sequence[MessageFact] = ()
    automation_sends: Sequence[AutomationSend] = ()
    handed_to_person: bool = False


def awaits_reply(chat: ThreadSnapshot, now: datetime) -> bool:
    """`awaiting_reply_sql`, over a snapshot already read. See the module docstring."""
    if chat.status != "open":
        return False
    inbound = [m.at for m in chat.messages if m.direction == "inbound" and not m.hidden]
    if not inbound:
        return False
    last_in = max(inbound)
    outbound = [m for m in chat.messages if m.direction == "outbound"]
    if any(not m.automatic and m.at >= last_in for m in outbound):
        return False
    if chat.handed_to_person:
        return True
    since = [s for s in chat.automation_sends if s.created_at >= last_in]
    if any(s.status in FAILED_STATUSES or s.delivery_failed for s in since):
        return True
    if any(m.at >= last_in for m in outbound):
        return False
    return not any(s.status in QUEUED_STATUSES and s.created_at > now - STALE_AFTER for s in since)

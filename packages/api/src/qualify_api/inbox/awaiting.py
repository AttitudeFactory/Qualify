"""«Por responder»: the ONE rule of when a chat waits for the business (m-25017843, BU-A1).

Founder's decision (ii), 2026-11-13 («Solo si pasó a persona»): a chat counts as «Por
responder» when the business owes a reply to a person:

1. the chat is not closed (`threads.status = 'open'`);
2. the customer wrote last as far as a PERSON is concerned — the newest inbound message is
   newer than the newest outbound message a person sent (the owner from Qualify, or from
   the channel's own app: every outbound row that is not the automatic menu's);
3. and one of:
   a. nobody answered it at all — the newest inbound is newer than every outbound, and the
      automatic menu has nothing queued for it (a menu reply waiting in `whatsapp_outbox`
      a few seconds is the menu answering, not a customer waiting);
   b. the chat was handed to a person — the customer chose «Hablar con alguien» (the menu's
      `Handoff`) or the owner took the chat over; both leave
      `whatsapp_thread_state.automation_paused_at` set;
   c. an automatic send failed — a `kind = 'automation'` row of `whatsapp_outbox` created
      since that inbound ended `failed`/`dead`, or Meta reported its message `failed`.

So a chat the menu answered, and nobody handed to a person, does NOT count; a closed chat
never counts. Instagram Direct has no automatic menu today, so for `dm` the rule reduces to
«open, and the customer wrote after our last reply» — reading a chat no longer clears it
(«Leídas» stops being a state of the count, `docs/arquitectura-bandeja-unica.md` §2.3).

Two forms, one rule:

- `awaiting_reply_sql(alias)` — the canonical form: a boolean SQL expression over the
  `threads` row `alias`, used verbatim by the inbox list (`inbox.unified`) and by
  `attention.counts`, so the number in the menu and the length of the list cannot differ.
- `awaits_reply(facts)` — the same rule over `ThreadReplyFacts`, the executable
  specification the offline tests pin; `test_inbox_awaiting_db.py` proves on Postgres
  that the SQL and this function agree on every case of the ticket.

A message's instant is `COALESCE(posted_at, ingested_at)` (Meta's timestamp, else when we
stored it), the expression `whatsapp.chats` and `attention.counts` already compare by.
Deleted messages (`deleted_at`) never count. Every statement using the fragment runs in
`tenant_session`: RLS scopes `messages`, `whatsapp_outbox` and `whatsapp_thread_state`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

# `whatsapp_outbox.kind` of what the automatic menu sends (`whatsapp.models.OUTBOX_KINDS`).
AUTOMATION_KIND: Final = "automation"
# Outbox statuses: still on its way, or terminal failure (`whatsapp.outbox`).
QUEUED_STATUSES: Final = ("pending", "sending")
FAILED_STATUSES: Final = ("failed", "dead")

_INSTANT: Final = "COALESCE({m}.posted_at, {m}.ingested_at)"
_NEVER: Final = "CAST('-infinity' AS timestamptz)"

_SQL: Final = """(
  {t}.status = 'open'
  AND EXISTS (
    SELECT 1
      FROM (
        SELECT max({m_instant}) FILTER (WHERE aw_m.direction = 'inbound') AS last_in,
               max({m_instant}) FILTER (
                 WHERE aw_m.direction = 'outbound' AND aw_ob.id IS NULL) AS last_person_out,
               max({m_instant}) FILTER (WHERE aw_m.direction = 'outbound') AS last_out
          FROM messages aw_m
          LEFT JOIN whatsapp_outbox aw_ob
                 ON aw_m.direction = 'outbound'
                AND aw_ob.thread_id = aw_m.thread_id
                AND aw_ob.wamid = aw_m.external_message_id
                AND aw_ob.kind = '{automation}'
         WHERE aw_m.thread_id = {t}.id AND aw_m.deleted_at IS NULL
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
                    AND aw_q.created_at >= aw_f.last_in))
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
    )


@dataclass(frozen=True)
class ThreadReplyFacts:
    """What the rule looks at, for one chat. Instants are message instants
    (`COALESCE(posted_at, ingested_at)`); `None` = no such message.

    - `last_person_outbound_at`: the newest outbound a person sent (not the menu's);
    - `last_outbound_at`: the newest outbound of anyone, the menu included;
    - `handed_to_person`: `whatsapp_thread_state.automation_paused_at` is set;
    - `automation_queued_since_inbound`: a menu send created since the newest inbound is
      still `pending`/`sending`;
    - `automation_failed_since_inbound`: a menu send created since the newest inbound
      ended `failed`/`dead`, or its message was reported `failed`.
    """

    status: str
    last_inbound_at: datetime | None
    last_person_outbound_at: datetime | None = None
    last_outbound_at: datetime | None = None
    handed_to_person: bool = False
    automation_queued_since_inbound: bool = False
    automation_failed_since_inbound: bool = False


def awaits_reply(facts: ThreadReplyFacts) -> bool:
    """`awaiting_reply_sql`, over facts already read. See the module docstring."""
    if facts.status != "open" or facts.last_inbound_at is None:
        return False
    last_in = facts.last_inbound_at
    if facts.last_person_outbound_at is not None and facts.last_person_outbound_at >= last_in:
        return False
    if facts.handed_to_person or facts.automation_failed_since_inbound:
        return True
    unanswered = facts.last_outbound_at is None or facts.last_outbound_at < last_in
    return unanswered and not facts.automation_queued_since_inbound

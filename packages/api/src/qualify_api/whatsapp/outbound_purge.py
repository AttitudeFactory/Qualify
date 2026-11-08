"""The chat picker's temporary R2 copies leave after use (m-24945889).

A chat send («Foto o menú»: a phone photo, a product or piece photo, a piece video, a
payment card) copies its bytes to `t/{tenant}/whatsapp/outbound/{connection}/{uuid}.ext`
when the owner taps «Enviar»; the sender uploads that copy to Meta (`upload_media`) and
records the media id. After that the copy serves nothing: the message is Meta's, and
the provenance stays in `whatsapp_outbox.attachment` (the key is kept as a record).

The pass, once a day with the piece purge (`creative.retention_job.daily_chore`):

- lists the tenant's chat outbound folder (`ObjectGate.list_chat_outbound` — nothing
  outside it is ever listed or deleted);
- keeps every copy a row may still upload: a `pending` or `sending` row that names it
  (the 24 h window and the retries make that short), and any copy younger than
  `OUTBOUND_TTL` (a row being written right now, an unknown date);
- deletes the rest by exact key (`ObjectGate.delete_chat_outbound`), or only reports them
  on a dry run (`execute=False`, the piece purge's own switch).

**The bucket lock.** Production keeps a lock rule on `t/` that refuses deletes
(m-24973446). A refused delete is logged and the pass stops for that tenant — nothing to
mark, nothing lost: the next run (or a manual one once deletes work) finishes it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final, Protocol
from uuid import UUID

logger = logging.getLogger("qualify_api.whatsapp.outbound_purge")

#: How long a copy is kept no matter what: far beyond a send's 24 h window and retries.
OUTBOUND_TTL: Final = timedelta(days=2)
#: The row statuses that may still upload a copy.
IN_FLIGHT: Final = ("pending", "sending")


class OutboundGate(Protocol):
    def list_chat_outbound(self, tenant_id: UUID) -> list: ...

    def delete_chat_outbound(self, tenant_id: UUID, object_keys: list[str]) -> None: ...


class InFlightKeys(Protocol):
    def __call__(self, tenant_id: UUID) -> set[str]:
        """The `attachment.object_key` of the tenant's `pending`/`sending` rows."""
        ...


@dataclass
class OutboundPurgeReport:
    tenant_id: UUID
    executed: bool
    found: int = 0
    kept: int = 0
    deleted: list[str] = field(default_factory=list)
    refused: bool = False


def purge_chat_outbound(
    *,
    tenant_id: UUID,
    gate: OutboundGate,
    in_flight: InFlightKeys,
    now: datetime,
    execute: bool,
) -> OutboundPurgeReport:
    report = OutboundPurgeReport(tenant_id=tenant_id, executed=execute)
    objects = gate.list_chat_outbound(tenant_id)
    report.found = len(objects)
    if not objects:
        return report
    needed = in_flight(tenant_id)
    expired = [
        o.key
        for o in objects
        if o.key not in needed
        and o.last_modified is not None
        and o.last_modified < now - OUTBOUND_TTL
    ]
    report.kept = report.found - len(expired)
    if not expired:
        return report
    if not execute:
        report.deleted = expired
        logger.info(
            "whatsapp.outbound_purge.dry_run tenant_id=%s would_delete=%d", tenant_id, len(expired)
        )
        return report
    from qualify_api.creative.retention import is_delete_refused  # noqa: PLC0415

    try:
        gate.delete_chat_outbound(tenant_id, expired)
    except Exception as exc:
        if not is_delete_refused(exc):
            raise
        report.refused = True
        logger.warning(
            "whatsapp.outbound_purge.refused tenant_id=%s keys=%d (bucket lock; kept)",
            tenant_id,
            len(expired),
        )
        return report
    report.deleted = expired
    logger.info("whatsapp.outbound_purge.deleted tenant_id=%s keys=%d", tenant_id, len(expired))
    return report


def in_flight_keys(tenant_id: UUID) -> set[str]:
    """Production `InFlightKeys`: read under RLS (`qualify_app`)."""
    from qualify_shared.db.session import tenant_session  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from qualify_api.whatsapp.models import WhatsAppOutboxItem as T  # noqa: PLC0415

    key = T.attachment["object_key"].astext
    with tenant_session(tenant_id) as session:
        rows = session.scalars(
            select(key).where(T.status.in_(IN_FLIGHT), T.attachment.has_key("object_key"))
        ).all()
    return {r for r in rows if r}


def tenants_with_whatsapp() -> list[UUID]:
    """PRODUCTION discovery: tenants with a WhatsApp number (`qualify_admin` SELECT on
    `whatsapp_phone_numbers`, 0057) — ids only; the rest runs under `tenant_session`."""
    from qualify_shared.db.admin import admin_session  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from qualify_api.whatsapp.models import WhatsAppPhoneNumber  # noqa: PLC0415

    with admin_session() as session:
        rows = session.scalars(select(WhatsAppPhoneNumber.tenant_id).distinct()).all()
    return sorted(set(rows), key=str)


def run_outbound_purge(
    tenant_ids: Iterable[UUID] | None,
    *,
    execute: bool,
    now: datetime,
    gate: OutboundGate | None = None,
    in_flight: InFlightKeys = in_flight_keys,
) -> list[OutboundPurgeReport]:
    """The daily pass over the given tenants (all WhatsApp tenants when None). One
    tenant failing never stops the others."""
    if gate is None:
        from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
        from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
        from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

        gate = ObjectGate(R2ObjectStore(R2Settings.from_env()))
    scope = list(tenant_ids) if tenant_ids is not None else tenants_with_whatsapp()
    reports: list[OutboundPurgeReport] = []
    for tenant_id in scope:
        try:
            report = purge_chat_outbound(
                tenant_id=tenant_id, gate=gate, in_flight=in_flight, now=now, execute=execute
            )
        except Exception:  # noqa: BLE001 — one tenant must not stop the rest
            logger.exception("whatsapp.outbound_purge.failed tenant_id=%s", tenant_id)
            continue
        reports.append(report)
        if report.refused:
            break  # the bucket refuses for everyone: no point asking again today
    return reports


__all__ = [
    "IN_FLIGHT",
    "OUTBOUND_TTL",
    "OutboundPurgeReport",
    "in_flight_keys",
    "purge_chat_outbound",
    "run_outbound_purge",
    "tenants_with_whatsapp",
]

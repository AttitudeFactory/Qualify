"""Running the piece purge (m-24828907): which tenants, which gate, real or dry run.

The rule and the per-tenant purge live in `creative.retention`; this module only wires
them for a process — the calendar worker's daily chore (`planner.worker`) and the manual
`--purge-pieces` command (`just piece-purge`).

- **Scope** is explicit, as in the calendar worker: the tenants it is given (locally,
  always), or `None` = the production discovery (`tenants_with_expired_pieces`).
- **Real by default**: the daily chore DELETES the files of expired pieces from R2 and
  marks them «Contenido eliminado» — the ticket's behaviour. `QUALIFY_PIECE_PURGE_EXECUTE`
  set to `0`/`false`/`no`/`off` is the kill switch: the chore then only logs what it
  would delete. The manual command (`just piece-purge`) stays a dry run unless
  `--execute`: a hand-typed run should never delete by accident.
- The R2 gate is built when the purge RUNS, not when the worker starts, so a worker
  without R2 configured keeps publishing and logs the purge failure once a day.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from uuid import UUID

from qualify_api.creative.retention import (
    PendingReport,
    PrefixDeleter,
    PurgeReport,
    purge_expired_pieces,
    purge_pending_objects,
    tenants_with_expired_pieces,
    tenants_with_pending_objects,
)

logger = logging.getLogger("qualify_api.creative.retention_job")

WARNING_ENV = "QUALIFY_PIECE_WARNING_EMAILS"
EXECUTE_ENV = "QUALIFY_PIECE_PURGE_EXECUTE"
#: The chore runs at worker start and then every 24 h.
PURGE_EVERY_SECONDS = 24 * 60 * 60


_OFF = ("0", "false", "no", "off")


def execute_from_env(env: Mapping[str, str] | None = None) -> bool:
    """True (really delete) unless `QUALIFY_PIECE_PURGE_EXECUTE` explicitly says off."""
    value = (env if env is not None else os.environ).get(EXECUTE_ENV, "")
    return value.strip().lower() not in _OFF


def production_gate() -> PrefixDeleter:
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    return ObjectGate(R2ObjectStore(R2Settings.from_env()))


def run_piece_purge(
    tenant_ids: Iterable[UUID] | None,
    *,
    execute: bool,
    now: datetime | None = None,
    gate: PrefixDeleter | None = None,
    discover: Callable[[datetime], list[UUID]] = tenants_with_expired_pieces,
) -> list[PurgeReport]:
    """One purge pass over the scope. One tenant failing never stops the others."""
    moment = now or datetime.now(UTC)
    scope = list(dict.fromkeys(tenant_ids)) if tenant_ids is not None else discover(moment)
    if not scope:
        logger.info("pieces.purge nothing to do execute=%s", execute)
        return []
    deleter = gate or production_gate()
    reports: list[PurgeReport] = []
    for tenant_id in scope:
        try:
            report = purge_expired_pieces(
                tenant_id=tenant_id, gate=deleter, now=moment, execute=execute
            )
        except Exception:  # noqa: BLE001 — one tenant must not stop the rest
            logger.exception("pieces.purge tenant failed tenant=%s", tenant_id)
            continue
        logger.info(
            # m-24921069: `candidates`/`errors` count pieces (a video by parts is one);
            # `folders`/`logical_only` count purged folders (the video and each part).
            "pieces.purge tenant=%s execute=%s candidates=%d folders=%d logical_only=%d "
            "objects=%d bytes=%d errors=%d",
            tenant_id,
            execute,
            report.candidates,
            report.folders,
            report.logical_only,
            report.objects,
            report.bytes,
            len(report.errors),
        )
        reports.append(report)
    return reports


def run_pending_purge(
    tenant_ids: Iterable[UUID] | None,
    *,
    execute: bool,
    now: datetime | None = None,
    gate: PrefixDeleter | None = None,
    discover: Callable[[], list[UUID]] = tenants_with_pending_objects,
) -> list[PendingReport]:
    """m-24973446: delete the objects R2 kept of pieces already purged for the app
    (`just piece-purge --pending [--execute]`; a dry run lists them). Not probing: it
    tries every pending piece of the scope."""
    moment = now or datetime.now(UTC)
    scope = list(dict.fromkeys(tenant_ids)) if tenant_ids is not None else discover()
    if not scope:
        logger.info("pieces.pending nothing to do execute=%s", execute)
        return []
    deleter = gate or production_gate()
    reports: list[PendingReport] = []
    for tenant_id in scope:
        try:
            reports.append(
                purge_pending_objects(
                    tenant_id=tenant_id, gate=deleter, now=moment, execute=execute
                )
            )
        except Exception:  # noqa: BLE001 — one tenant must not stop the rest
            logger.exception("pieces.pending tenant failed tenant=%s", tenant_id)
    return reports


def warning_emails_enabled() -> bool:
    return os.environ.get(WARNING_ENV, "").strip().lower() not in _OFF


def warning_retry_chore(tenant_ids: Iterable[UUID] | None) -> Callable[[], object]:
    """Every-minute drain of frozen batches only, with the same explicit worker scope."""
    scope = list(tenant_ids) if tenant_ids is not None else None

    def run() -> None:
        if not warning_emails_enabled():
            return
        try:
            from qualify_api.creative.retention_mail import run_warning_retries

            run_warning_retries(scope, datetime.now(UTC))
        except Exception:
            logger.exception("pieces.warning retry failed")

    return run


def daily_chore(tenant_ids: Iterable[UUID] | None) -> Callable[[], object]:
    """The calendar worker's chore: the same scope as its ticks; really deletes unless
    `QUALIFY_PIECE_PURGE_EXECUTE` says off (read on every run)."""
    scope = list(tenant_ids) if tenant_ids is not None else None

    def run() -> object:
        if warning_emails_enabled():
            try:
                from qualify_api.creative.retention_mail import run_piece_warnings

                run_piece_warnings(scope, datetime.now(UTC))
            except Exception:
                logger.exception("pieces.warning failed; purge continues")
        try:
            from qualify_api.creative.brand_prefill_media import run_cleanup

            run_cleanup(scope, execute=execute_from_env())
        except Exception:
            logger.exception("prefill media cleanup failed; piece purge continues")
        reports: list[PurgeReport] = []
        try:
            reports = run_piece_purge(scope, execute=execute_from_env())
        except Exception:
            logger.exception("piece purge failed; the reel windows purge still runs")
        run_reel_windows_purge(scope, execute=execute_from_env())
        run_chat_outbound_purge(scope, execute=execute_from_env())
        return reports

    return run


def run_reel_windows_purge(tenant_ids: Iterable[UUID] | None, *, execute: bool) -> None:
    """VE-12 RA5 (m-24921060): the 30-day purge of the reel cuts a part keeps in its
    piece folder (`referentes.reel_window_retention`), on the piece purge's scope and
    switch. Never raises: a failure here must not stop the piece purge, nor the other
    way round. The GLOBAL reel purge (`referentes.reel_retention`) is never called from
    here — only the `reels-worker` deletes under `public/`."""
    try:
        from qualify_api.referentes.reel_window_retention import run_window_purge  # noqa: PLC0415

        run_window_purge(tenant_ids, execute=execute)
    except Exception:
        logger.exception("reel windows purge failed")


def run_chat_outbound_purge(tenant_ids: Iterable[UUID] | None, *, execute: bool) -> None:
    """m-24945889: the WhatsApp chat picker's temporary copies
    (`whatsapp.outbound_purge`), on the piece purge's scope and switch. Never raises."""
    try:
        from qualify_api.whatsapp.outbound_purge import run_outbound_purge  # noqa: PLC0415

        run_outbound_purge(tenant_ids, execute=execute, now=datetime.now(UTC))
    except Exception:
        logger.exception("chat outbound purge failed")


__all__ = [
    "EXECUTE_ENV",
    "PURGE_EVERY_SECONDS",
    "daily_chore",
    "execute_from_env",
    "production_gate",
    "run_chat_outbound_purge",
    "run_pending_purge",
    "run_piece_purge",
    "run_reel_windows_purge",
]

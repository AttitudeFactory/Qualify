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
    PrefixDeleter,
    PurgeReport,
    purge_expired_pieces,
    tenants_with_expired_pieces,
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
            "pieces.purge tenant=%s execute=%s pieces=%d objects=%d bytes=%d errors=%d",
            tenant_id,
            execute,
            len(report.purged),
            report.objects,
            report.bytes,
            len(report.errors),
        )
        reports.append(report)
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
        return run_piece_purge(scope, execute=execute_from_env())

    return run


__all__ = [
    "EXECUTE_ENV",
    "PURGE_EVERY_SECONDS",
    "daily_chore",
    "execute_from_env",
    "production_gate",
    "run_piece_purge",
]

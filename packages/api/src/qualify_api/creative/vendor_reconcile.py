"""Reconcile our Seedance tasks with BytePlus's own list (m-24852492). READ-ONLY.

    python -m qualify_api.creative.vendor_reconcile --tenant <uuid> [--days 7] [--json]
    python -m qualify_api.creative.vendor_reconcile --all-tenants [--days 7] [--json]

(`just creative-tasks-report …`.) It reads `creative_vendor_tasks` (each tenant in its own
`tenant_session`) and the account's video tasks (`SeedanceVideoAdapter.list_tasks`, a GET)
for the last `--days`, and prints:

- **billed, not collected** — BytePlus says `succeeded` (it billed the video) while our
  row is still `pending` (the recovery pass should collect it within minutes — if it
  stays here, look) or `failed` (we gave the piece up: a paid video was lost);
- **tasks without a piece** — BytePlus lists a task no row of ours knows (only with
  `--all-tenants`: a scoped run cannot tell another business's task from a stray one).
  Manual tests on the same key (arkcli, the playground) land here too;
- **pieces without a task** — a row whose task BytePlus does not list in the window.

Nothing is written, sent or paid. Exit code 0 when the report is clean, 2 when it found
something, 1 when it could not run. The listing's shape follows BytePlus's docs and is
not yet verified live (docs/recuperar-videos-sin-pantalla.md).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger("qualify_api.creative.vendor_reconcile")

DEFAULT_DAYS = 7
#: A listing is read at most this many pages (x100 tasks) — far beyond a week today.
MAX_PAGES = 50


@dataclass(frozen=True)
class OurTask:
    tenant_id: UUID
    draft_id: UUID
    slot: str
    vendor_task_id: str
    status: str
    created_at: datetime


@dataclass(frozen=True)
class VendorTask:
    vendor_task_id: str
    status: str
    model: str
    created_at: datetime | None


@dataclass
class ReconcileReport:
    since: datetime
    scope: str
    ours: int = 0
    vendor: int = 0
    billed_not_collected: list[dict[str, str]] = field(default_factory=list)
    vendor_only: list[dict[str, str]] = field(default_factory=list)
    ours_only: list[dict[str, str]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.billed_not_collected or self.vendor_only or self.ours_only)


class TaskLister(Protocol):
    def list_tasks(self, *, api_key: str, page_num: int, page_size: int) -> Mapping[str, Any]: ...


# -- the comparison ---------------------------------------------------------------------------


def _when(value: object) -> datetime | None:
    """BytePlus's `created_at`: unix seconds per the docs; an ISO string tolerated."""
    if isinstance(value, int | float) and value > 0:
        return datetime.fromtimestamp(float(value), UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def vendor_tasks(
    lister: TaskLister, *, api_key: str, since: datetime, page_size: int = 100
) -> list[VendorTask]:
    """The account's tasks created since `since`, newest first, page by page until a
    page is empty, short, or entirely older than `since`."""
    found: list[VendorTask] = []
    for page in range(1, MAX_PAGES + 1):
        body = lister.list_tasks(api_key=api_key, page_num=page, page_size=page_size)
        items = body.get("items") if isinstance(body.get("items"), list) else []
        older = 0
        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            created = _when(item.get("created_at"))
            if created is not None and created < since:
                older += 1
                continue
            found.append(
                VendorTask(
                    vendor_task_id=str(item["id"]),
                    status=str(item.get("status") or "").lower(),
                    model=str(item.get("model") or ""),
                    created_at=created,
                )
            )
        if not items or len(items) < page_size or older == len(items):
            break
    return found


def reconcile(
    ours: Sequence[OurTask],
    theirs: Sequence[VendorTask],
    *,
    since: datetime,
    scope: str,
    judge_vendor_only: bool,
) -> ReconcileReport:
    report = ReconcileReport(since=since, scope=scope, ours=len(ours), vendor=len(theirs))
    by_id = {t.vendor_task_id: t for t in theirs}
    known = {t.vendor_task_id for t in ours}
    for task in ours:
        vendor = by_id.get(task.vendor_task_id)
        row = {
            "tenant_id": str(task.tenant_id),
            "draft_id": str(task.draft_id),
            "slot": task.slot,
            "vendor_task_id": task.vendor_task_id,
            "our_status": task.status,
        }
        if vendor is None:
            report.ours_only.append(row)
        elif vendor.status == "succeeded" and task.status != "succeeded":
            report.billed_not_collected.append({**row, "vendor_status": vendor.status})
    if judge_vendor_only:
        for vendor in theirs:
            if vendor.vendor_task_id not in known:
                report.vendor_only.append(
                    {
                        "vendor_task_id": vendor.vendor_task_id,
                        "vendor_status": vendor.status,
                        "model": vendor.model,
                        "created_at": vendor.created_at.isoformat() if vendor.created_at else "",
                    }
                )
    return report


def render(report: ReconcileReport) -> str:
    lines = [
        f"Seedance tasks since {report.since:%Y-%m-%d %H:%M} UTC — scope {report.scope}",
        f"  ours: {report.ours}   BytePlus: {report.vendor}",
    ]
    sections = (
        ("billed by BytePlus, not collected", report.billed_not_collected),
        ("tasks without a piece (BytePlus only)", report.vendor_only),
        ("pieces without a task (ours only)", report.ours_only),
    )
    for title, rows in sections:
        lines.append(f"- {title}: {len(rows)}")
        lines.extend("    " + " ".join(f"{k}={v}" for k, v in row.items()) for row in rows)
    lines.append("clean" if report.clean else "ATTENTION: see the sections above")
    return "\n".join(lines)


# -- production reads -------------------------------------------------------------------------


def our_tasks(tenant_ids: Iterable[UUID], *, since: datetime) -> list[OurTask]:
    """Every tenant's rows in its own `tenant_session` (RLS)."""
    from qualify_shared.db.session import tenant_session  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from qualify_api.creative.models import CreativeVendorTask  # noqa: PLC0415

    found: list[OurTask] = []
    for tenant_id in tenant_ids:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(CreativeVendorTask).where(
                    CreativeVendorTask.created_at >= since,
                    # ModelArk's list only holds Seedance: an OmniHuman render
                    # (m-24852495, BytePlus Vision AI) would read «ours only»
                    CreativeVendorTask.provider != "omnihuman",
                )
            ).all()
            found.extend(
                OurTask(
                    tenant_id=tenant_id,
                    draft_id=row.draft_id,
                    slot=row.slot,
                    vendor_task_id=row.vendor_task_id,
                    status=row.status,
                    created_at=row.created_at,
                )
                for row in rows
            )
    return found


def tenants_with_recent_drafts(since: datetime) -> list[UUID]:
    """PRODUCTION discovery: ids of tenants with a draft touched since `since` (a task's
    draft is stamped when it enters `drafting`, so it is always among them). Read-only,
    ids only, `qualify_admin` already reads `content_drafts` (0009)."""
    from qualify_shared.db.admin import admin_session  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from qualify_api.creative.models import ContentDraft  # noqa: PLC0415

    with admin_session() as session:
        rows = session.scalars(
            select(ContentDraft.tenant_id).where(ContentDraft.updated_at >= since).distinct()
        ).all()
    return sorted(set(rows), key=str)


def _platform_lister() -> tuple[TaskLister, str]:
    import os  # noqa: PLC0415

    from qualify_creative.adapters.byteplus_ark import SeedanceVideoAdapter  # noqa: PLC0415

    from qualify_api.creative.composition import (  # noqa: PLC0415
        ARK_BASE_URL,
        ARK_BASE_URL_ENV,
        PROVIDER_KEY_ENVS,
    )

    key = os.environ.get(PROVIDER_KEY_ENVS["seedance"], "").strip()
    if not key:
        raise RuntimeError(f"{PROVIDER_KEY_ENVS['seedance']} is not set")
    adapter = SeedanceVideoAdapter(base_url=os.environ.get(ARK_BASE_URL_ENV) or ARK_BASE_URL)
    return adapter, key


# -- CLI --------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qualify_api.creative.vendor_reconcile",
        description="Compare our Seedance tasks with BytePlus's list. Read-only.",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--tenant", dest="tenants", action="append", type=UUID, metavar="UUID")
    scope.add_argument("--all-tenants", action="store_true")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    ours: Callable[[Iterable[UUID], datetime], list[OurTask]] | None = None,
    discover: Callable[[datetime], list[UUID]] | None = None,
    lister: Callable[[], tuple[TaskLister, str]] | None = None,
    now: datetime | None = None,
    out: Callable[[str], object] = print,
) -> int:
    args = build_parser().parse_args(argv)
    if args.days < 1:
        build_parser().error("--days must be at least 1")
    _load_dotenv()
    since = (now or datetime.now(UTC)) - timedelta(days=args.days)
    try:
        if args.all_tenants:
            tenant_ids = (discover or tenants_with_recent_drafts)(since)
            scope = "all-tenants"
        else:
            tenant_ids = list(dict.fromkeys(args.tenants))
            scope = ",".join(str(t) for t in tenant_ids)
        read_ours = ours or (lambda ids, s: our_tasks(ids, since=s))
        mine = read_ours(tenant_ids, since)
        list_client, key = (lister or _platform_lister)()
        theirs = vendor_tasks(list_client, api_key=key, since=since)
    except Exception as exc:
        logger.exception("creative.reconcile.failed")
        out(f"reconcile could not run: {type(exc).__name__}: {exc}")
        return 1
    report = reconcile(
        mine, theirs, since=since, scope=scope, judge_vendor_only=bool(args.all_tenants)
    )
    if args.json:
        payload = asdict(report)
        payload["since"] = report.since.isoformat()
        payload["clean"] = report.clean
        out(json.dumps(payload, indent=2, sort_keys=True))
    else:
        out(render(report))
    return 0 if report.clean else 2


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv  # noqa: PLC0415
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parents[5] / ".env", override=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    raise SystemExit(main())

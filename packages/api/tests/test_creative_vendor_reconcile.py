"""m-24852492: the read-only reconciliation of our Seedance tasks with BytePlus's list.

Offline: our rows and BytePlus's pages are fakes. Pinned: what lands in each section,
that a scoped run never judges other businesses' tasks, paging, and the exit codes.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.creative import vendor_reconcile as vr
from qualify_api.creative.vendor_reconcile import OurTask, VendorTask

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
SINCE = NOW - timedelta(days=7)
TENANT = UUID("c0000000-0000-4000-8000-000000000001")


def _ours(task_id: str, status: str) -> OurTask:
    return OurTask(TENANT, uuid4(), "seedance-1", task_id, status, NOW - timedelta(hours=1))


def _theirs(task_id: str, status: str) -> VendorTask:
    return VendorTask(task_id, status, "dreamina-seedance-2-5", NOW - timedelta(hours=1))


def test_each_mismatch_lands_in_its_section() -> None:
    ours = [
        _ours("ok", "succeeded"),
        _ours("lost", "failed"),  # BytePlus billed it, we gave it up
        _ours("late", "pending"),  # billed, the recovery pass has not collected it
        _ours("ghost", "pending"),  # BytePlus never listed it
        _ours("refused", "failed"),
    ]
    theirs = [
        _theirs("ok", "succeeded"),
        _theirs("lost", "succeeded"),
        _theirs("late", "succeeded"),
        _theirs("refused", "failed"),
        _theirs("stray", "succeeded"),  # a manual test on the same key
    ]
    report = vr.reconcile(ours, theirs, since=SINCE, scope="all", judge_vendor_only=True)

    assert [r["vendor_task_id"] for r in report.billed_not_collected] == ["lost", "late"]
    assert [r["vendor_task_id"] for r in report.ours_only] == ["ghost"]
    assert [r["vendor_task_id"] for r in report.vendor_only] == ["stray"]
    assert not report.clean
    assert "ATTENTION" in vr.render(report)


def test_a_scoped_report_never_judges_tasks_it_cannot_see() -> None:
    report = vr.reconcile(
        [_ours("ok", "succeeded")],
        [_theirs("ok", "succeeded"), _theirs("other-business", "succeeded")],
        since=SINCE,
        scope=str(TENANT),
        judge_vendor_only=False,
    )
    assert report.vendor_only == [] and report.clean
    assert vr.render(report).endswith("clean")


class Pages:
    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        self.pages = pages
        self.asked: list[tuple[int, int, str]] = []

    def list_tasks(self, *, api_key: str, page_num: int, page_size: int) -> Mapping[str, Any]:
        self.asked.append((page_num, page_size, api_key))
        items = self.pages[page_num - 1] if page_num <= len(self.pages) else []
        return {"items": items, "total": sum(len(p) for p in self.pages)}


def _item(task_id: str, age: timedelta, status: str = "succeeded") -> dict[str, Any]:
    return {"id": task_id, "status": status, "created_at": int((NOW - age).timestamp())}


def test_the_listing_pages_until_it_reaches_older_tasks() -> None:
    lister = Pages(
        [
            [_item("a", timedelta(hours=1)), _item("b", timedelta(days=2))],
            [_item("c", timedelta(days=6)), _item("old", timedelta(days=9))],
            [_item("older", timedelta(days=10)), _item("oldest", timedelta(days=11))],
            [_item("never-read", timedelta(days=12))],
        ]
    )
    found = vr.vendor_tasks(lister, api_key="k", since=SINCE, page_size=2)
    assert [t.vendor_task_id for t in found] == ["a", "b", "c"]
    assert [a[0] for a in lister.asked] == [1, 2, 3]


def test_the_listing_stops_on_a_short_page_and_tolerates_iso_dates() -> None:
    lister = Pages([[{"id": "x", "status": "Running", "created_at": "2026-10-25T10:00:00Z"}]])
    (task,) = vr.vendor_tasks(lister, api_key="k", since=SINCE, page_size=100)
    assert task.status == "running" and task.created_at == datetime(2026, 10, 25, 10, tzinfo=UTC)
    assert len(lister.asked) == 1


def _main(
    argv: list[str], ours: list[OurTask], pages: Pages, tenants: list[UUID] | None = None
) -> tuple[int, list[str], list[list[UUID]]]:
    printed: list[str] = []
    asked: list[list[UUID]] = []

    def read_ours(ids: Iterable[UUID], since: datetime) -> list[OurTask]:
        asked.append(list(ids))
        assert since == SINCE
        return ours

    def discover(since: datetime) -> list[UUID]:
        return tenants or []

    code = vr.main(
        argv,
        ours=read_ours,
        discover=discover,
        lister=lambda: (pages, "ark-key"),
        now=NOW,
        out=printed.append,
    )
    return code, printed, asked


def test_cli_scoped_clean_exits_0_and_reads_only_that_tenant() -> None:
    pages = Pages([[_item("ok", timedelta(hours=1)), _item("theirs", timedelta(hours=2))]])
    code, printed, asked = _main(["--tenant", str(TENANT)], [_ours("ok", "succeeded")], pages)
    assert code == 0 and asked == [[TENANT]]
    assert printed[-1].endswith("clean")


def test_cli_all_tenants_with_findings_exits_2_and_prints_json() -> None:
    other = uuid4()
    pages = Pages([[_item("lost", timedelta(hours=1))]])
    code, printed, asked = _main(
        ["--all-tenants", "--json"], [_ours("lost", "failed")], pages, tenants=[TENANT, other]
    )
    assert code == 2 and asked == [[TENANT, other]]
    payload = json.loads(printed[-1])
    assert payload["clean"] is False
    assert payload["billed_not_collected"][0]["vendor_task_id"] == "lost"


def test_cli_exits_1_when_bytepluss_list_cannot_be_read() -> None:
    def broken() -> tuple[Any, str]:
        raise RuntimeError("QUALIFY_BYTEPLUS_ARK_API_KEY is not set")

    printed: list[str] = []
    code = vr.main(
        ["--tenant", str(TENANT)],
        ours=lambda ids, since: [],
        lister=broken,
        now=NOW,
        out=printed.append,
    )
    assert code == 1 and "could not run" in printed[-1]


def test_cli_scope_is_mandatory() -> None:
    with pytest.raises(SystemExit):
        vr.build_parser().parse_args([])

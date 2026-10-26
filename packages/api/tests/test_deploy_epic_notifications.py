"""Deploy routing contracts without GitHub, Meegle or Lark traffic."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / ".github" / "scripts"
TARGET = "a" * 40
BASE = "b" * 40


@pytest.fixture
def routing(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.syspath_prepend(str(SCRIPTS))
    module = importlib.import_module("deploy_epics")
    for name in (
        "DEPLOY_EPIC_NOTIFICATIONS",
        "DEPLOY_EPIC_DRY_RUN",
        "DEPLOY_MEEGLE_PLUGIN_ID",
        "DEPLOY_MEEGLE_PLUGIN_SECRET",
        "DEPLOY_MEEGLE_USER_KEY",
        "DEPLOY_LARK_APP_ID",
        "DEPLOY_LARK_APP_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    return module


@pytest.fixture
def ctx() -> dict[str, Any]:
    return {
        "repo": "org/repo",
        "sha": TARGET,
        "run_id": "10",
        "run_attempt": "1",
        "run_url": "https://github.com/org/repo/actions/runs/10",
        "results": {"deploy": "success"},
        "run": {"stages": {"deploy": {"started_at": "2026-10-26T13:00:00Z"}}},
        "commit": {"subject": "Merge PR #12"},
    }


def enable(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DEPLOY_MEEGLE_PLUGIN_ID",
        "DEPLOY_MEEGLE_PLUGIN_SECRET",
        "DEPLOY_MEEGLE_USER_KEY",
        "DEPLOY_LARK_APP_ID",
        "DEPLOY_LARK_APP_SECRET",
    ):
        monkeypatch.setenv(name, "fixture-only")
    monkeypatch.setenv("DEPLOY_EPIC_NOTIFICATIONS", "true")


def test_collects_pr_body_and_all_commits_since_actual_previous_target(
    routing: Any, ctx: Any
) -> None:
    calls: list[str] = []

    def github(path: str) -> Any:
        calls.append(path)
        if path.endswith(f"/commits/{TARGET}"):
            return {"commit": {"message": "Merge from feat/m-111-test"}}
        if "/pulls?" in path:
            return [{"title": "m-111", "body": "Resolves m-222"}]
        if "/runs?" in path:
            return {"workflow_runs": [{"id": 10}, {"id": 9, "head_sha": "c" * 40}]}
        if "/runs/9/jobs" in path:
            return {
                "jobs": [
                    {
                        "name": "deploy",
                        "completed_at": "2026-10-26T12:00:00Z",
                        "conclusion": "success",
                        "steps": [
                            {"name": f"Deploy {BASE} (server pulls, migrates, starts)"},
                        ],
                    }
                ]
            }
        if "/compare/" in path:
            assert f"{BASE}...{TARGET}" in path  # not the workflow's head_sha
            return {
                "status": "ahead",
                "total_commits": 2,
                "commits": [
                    {"commit": {"message": "feat: m-333"}},
                    {"commit": {"message": "fix: M-111"}},
                ],
            }
        raise AssertionError(path)

    assert routing.ticket_ids(ctx, github) == [111, 222, 333]
    assert not any("/runs/10/jobs" in path for path in calls)


def test_refuses_partial_compare_instead_of_silently_missing_epics(routing: Any, ctx: Any) -> None:
    def github(path: str) -> Any:
        if "/runs?" in path:
            return {"workflow_runs": [{"id": 9}]}
        if "/jobs?" in path:
            return {
                "jobs": [
                    {
                        "name": "deploy",
                        "completed_at": "2026-10-26T12:00:00Z",
                        "conclusion": "success",
                        "steps": [
                            {"name": f"Deploy {BASE} (server pulls, migrates, starts)"},
                        ],
                    }
                ]
            }
        if "/compare/" in path:
            return {"status": "ahead", "total_commits": 101, "commits": []}
        return {}

    with pytest.raises(routing.RoutingError, match="partial"):
        routing.ticket_ids(ctx, github)


def test_rollback_does_not_notify_tickets_removed_from_the_target(routing: Any, ctx: Any) -> None:
    ctx["commit"]["subject"] = "m-111"

    def github(path: str) -> Any:
        if "/runs?" in path:
            return {"workflow_runs": [{"id": 9}]}
        if "/jobs?" in path:
            return {
                "jobs": [
                    {
                        "name": "deploy",
                        "completed_at": "2026-10-26T12:00:00Z",
                        "conclusion": "success",
                        "steps": [
                            {"name": f"Deploy {BASE} (server pulls, migrates, starts)"},
                        ],
                    }
                ]
            }
        if "/compare/" in path:
            return {"status": "behind", "commits": [{"commit": {"message": "m-999"}}]}
        return {}

    assert routing.ticket_ids(ctx, github) == [111]


def test_groups_shared_chats_without_leaking_other_epics(
    routing: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DEPLOY_MEEGLE_USER_KEY", "user")

    def request(url: str, body: Any, headers: Any) -> Any:
        assert headers == {"X-Plugin-Token": "token", "X-User-Key": "user"}
        if "/issue/" in url:
            return {
                "err_code": 0,
                "data": [
                    {"id": 1, "fields": [{"field_key": "field_00304b", "field_value": 11}]},
                    {"id": 2, "fields": [{"field_key": "field_00304b", "field_value": {"id": 22}}]},
                    {"id": 3, "fields": []},
                ],
            }
        assert body["work_item_ids"] == [11, 22]
        return {
            "err_code": 0,
            "data": [
                {
                    "id": i,
                    "name": f"Epic {i}",
                    "fields": [
                        {"field_key": "group_type", "field_value": {"group_id": "oc_shared"}},
                    ],
                }
                for i in [11, 22]
            ],
        }

    monkeypatch.setattr(routing, "request_json", request)
    groups = routing.destinations([1, 2, 3], "token")
    assert list(groups) == ["oc_shared"]
    assert [e["id"] for e in groups["oc_shared"]] == [11, 22]
    assert "[3]" in capsys.readouterr().out


def test_disabled_mode_makes_no_network_requests(routing: Any, ctx: Any) -> None:
    def forbidden(*args: Any) -> Any:
        pytest.fail("network called while disabled")

    routing.notify_epics(ctx, forbidden)


def test_meegle_query_rejection_does_not_create_destinations(
    routing: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEPLOY_MEEGLE_USER_KEY", "user")
    monkeypatch.setattr(routing, "request_json", lambda *args: {"err_code": 20006, "data": []})
    with pytest.raises(routing.RoutingError, match="refused"):
        routing.destinations([1], "fixture")


@pytest.mark.parametrize("dry_run", [False, True])
def test_delivery_isolates_failures_and_dry_run_does_not_send(
    routing: Any,
    ctx: Any,
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    enable(monkeypatch)
    if dry_run:
        monkeypatch.setenv("DEPLOY_EPIC_DRY_RUN", "true")
    monkeypatch.setattr(routing, "ticket_ids", lambda *args: [1, 2])
    monkeypatch.setattr(
        routing,
        "destinations",
        lambda *args: {
            "oc_first": [{"id": 11, "name": "First", "issues": [{"id": 1, "name": "One"}]}],
            "oc_second": [{"id": 22, "name": "Second", "issues": [{"id": 2, "name": "Two"}]}],
        },
    )
    sent: list[dict[str, Any]] = []
    auth_urls: list[str] = []

    def request(url: str, body: Any, headers: Any) -> Any:
        if url.endswith("plugin_token"):
            return {"data": {"token": "meegle-token"}}
        if url.endswith("/internal"):
            auth_urls.append(url)
            return {"code": 0, "tenant_access_token": "lark-token"}
        sent.append(body)
        if body["receive_id"] == "oc_first":
            return {"code": 230002}  # bot missing from first chat
        return {"code": 0, "data": {"message_id": "om_ok"}}

    monkeypatch.setattr(routing, "request_json", request)
    routing.notify_epics(ctx, lambda path: {})
    if dry_run:
        assert not sent and not auth_urls
    else:
        assert [s["receive_id"] for s in sent] == ["oc_first", "oc_second"]
        assert len({s["uuid"] for s in sent}) == 2
        assert "m-2" in json.dumps(json.loads(sent[1]["content"]))
        assert "m-1" not in json.dumps(json.loads(sent[1]["content"]))
        uuids = [s["uuid"] for s in sent]
        routing.notify_epics(ctx, lambda path: {})
        assert uuids == [s["uuid"] for s in sent[2:]]
        assert "failed for oc_first" in capsys.readouterr().out


def test_main_keeps_general_notice_and_redacts_epic_failure(
    routing: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = importlib.import_module("deploy_notify")
    monkeypatch.setenv("DEVOPS_WEBHOOK_URL", "https://fixture.invalid/hook")
    monkeypatch.setattr(module, "commit_info", lambda *args: {})
    monkeypatch.setattr(module, "run_info", lambda *args: {"stages": {}, "total": None})
    posted: list[Any] = []
    monkeypatch.setattr(module, "post", lambda *args: posted.append(args))

    def fail(*args: Any) -> None:
        raise RuntimeError("credential-must-not-appear")

    monkeypatch.setattr(module, "notify_epics", fail)
    assert module.main() == 0
    assert len(posted) == 1
    output = capsys.readouterr().out
    assert "RuntimeError" in output
    assert "credential-must-not-appear" not in output

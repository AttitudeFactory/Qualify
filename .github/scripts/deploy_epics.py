"""Route deploy notices through Meegle Issue → Feature → Lark chat (m-24822994).

Stdlib only; opt-in from deploy_notify.py. Never log credentials or response bodies.
The general custom-bot notice remains independent of this application-bot delivery.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

TICKET = re.compile(r"\bm-(\d+)\b", re.IGNORECASE)
DEPLOY_STEP = re.compile(r"^Deploy ([0-9a-f]{40}) \(server pulls, migrates, starts\)$")
SHA = re.compile(r"^[0-9a-f]{40}$")
CHAT = re.compile(r"^oc_[a-zA-Z0-9]+$")
LARK = "https://open.larksuite.com/open-apis"
MEEGLE = "https://project.larksuite.com"
PROJECT = "6ad251e7ce655b7ed3a0e9b4"
SPACE = "5h2wsx"
GitHub = Callable[[str], Any]


class RoutingError(Exception):
    """A refused, malformed or unreachable upstream response; no response text."""


def request_json(url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:  # noqa: S310
            data = json.loads(response.read(2_000_000))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RoutingError("request failed") from exc
    if not isinstance(data, dict):
        raise RoutingError("invalid response")
    return data


def ticket_ids(ctx: dict[str, Any], github: GitHub) -> list[int]:
    """Read the target and, when available, the range since the last successful deploy.

    The previous target comes from the deploy step's name, not head_sha: manual runs
    may deploy an older ref. Look at most five prior successful workflow runs.
    """
    repo, sha = ctx["repo"], ctx["sha"]
    if not SHA.fullmatch(sha):
        return []
    texts = [ctx.get("commit", {}).get("subject", "")]
    target = github(f"/repos/{repo}/commits/{sha}") or {}
    texts.append((target.get("commit") or {}).get("message", ""))
    prs = github(f"/repos/{repo}/commits/{sha}/pulls?per_page=100") or []
    for pr in prs if isinstance(prs, list) else []:
        texts.extend([pr.get("title") or "", pr.get("body") or ""])

    previous, latest = "", ""
    started = ((ctx.get("run") or {}).get("stages", {}).get("deploy") or {}).get("started_at")
    # Concurrency serializes deploys without preserving run creation order. Select by
    # completion before this deploy started, not by run id or the workflow's head_sha.
    runs = (
        github(f"/repos/{repo}/actions/workflows/deploy.yml/runs?status=success&per_page=5")
        if started
        else {}
    )
    for run in (runs or {}).get("workflow_runs", []):
        # Re-runs of this run are not a previous deployment.
        if str(run.get("id")) == str(ctx["run_id"]):
            continue
        jobs = github(f"/repos/{repo}/actions/runs/{run['id']}/jobs?per_page=50")
        for job in (jobs or {}).get("jobs", []):
            if job.get("name") != "deploy" or job.get("conclusion") != "success":
                continue
            completed = job.get("completed_at", "")
            if not completed or completed > started or completed <= latest:
                continue
            for step in job.get("steps", []):
                match = DEPLOY_STEP.fullmatch(step.get("name", ""))
                if match:
                    previous = match[1]
                    latest = completed
    if previous and previous != sha:
        comparison = github(f"/repos/{repo}/compare/{previous}...{sha}?per_page=100") or {}
        if comparison.get("status") in {"ahead", "identical"}:
            commits = comparison.get("commits", [])
            if comparison.get("total_commits", 0) > len(commits):
                raise RoutingError("deploy range exceeds one page; no partial epic notices")
            texts.extend((c.get("commit") or {}).get("message", "") for c in commits)
        elif comparison.get("status") in {"behind", "diverged"}:
            print("::notice::Rollback/divergence: epic notice covers the target commit only.")
        else:
            raise RoutingError("cannot determine deploy range; no partial epic notices")
    elif not previous:
        print("::notice::No previous successful deploy found; routing the target commit only.")
    return sorted({int(match) for text in texts for match in TICKET.findall(text)})


def fields(item: dict[str, Any]) -> dict[str, Any]:
    return {f["field_key"]: f.get("field_value") for f in item.get("fields", [])}


def related_id(value: Any) -> int | None:
    if isinstance(value, dict):
        value = value.get("id")
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdecimal() and int(value) > 0:
        return int(value)
    return None


def destinations(ids: list[int], token: str) -> dict[str, list[dict[str, Any]]]:
    """Batch reads, bounded to 100 Issues; group only the matching Issues in each chat."""
    if len(ids) > 100:
        raise RoutingError("too many tickets")
    headers = {"X-Plugin-Token": token, "X-User-Key": os.environ["DEPLOY_MEEGLE_USER_KEY"]}

    def query(kind: str, item_ids: list[int]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for start in range(0, len(item_ids), 50):
            answer = request_json(
                f"{MEEGLE}/open_api/{PROJECT}/work_item/{kind}/query",
                {"work_item_ids": item_ids[start : start + 50]},
                headers,
            )
            if answer.get("err_code") != 0 or not isinstance(answer.get("data"), list):
                raise RoutingError("Meegle refused query")
            rows.extend(answer["data"])
        return rows

    issues = query("issue", ids)
    by_epic: dict[int, list[dict[str, Any]]] = {}
    for issue in issues:
        epic_id = related_id(fields(issue).get("field_00304b"))
        if epic_id:
            by_epic.setdefault(epic_id, []).append(issue)
    groups: dict[str, list[dict[str, Any]]] = {}
    for epic in query("story", sorted(by_epic)):
        values = fields(epic)
        group = values.get("group_type") or {}
        # The Open API also returns the legacy group_id field in older templates.
        chat = (group.get("group_id") if isinstance(group, dict) else None) or values.get(
            "group_id", ""
        )
        if isinstance(chat, str) and CHAT.fullmatch(chat):
            groups.setdefault(chat, []).append(
                {"id": epic["id"], "name": epic.get("name", ""), "issues": by_epic[epic["id"]]}
            )
    linked = {issue["id"] for epics in groups.values() for e in epics for issue in e["issues"]}
    if missing := set(ids) - linked:
        print(f"::notice::Tickets without a routable epic chat: {sorted(missing)}.")
    return groups


def message(ctx: dict[str, Any], epics: list[dict[str, Any]]) -> dict[str, Any]:
    outcome = "producción actualizada" if ctx["results"]["deploy"] == "success" else "revisar fallo"
    lines: list[list[dict[str, str]]] = [
        [{"tag": "text", "text": f"Deploy: {outcome}. Commit {ctx['sha'][:7]}."}],
    ]
    for epic in epics:
        lines.append(
            [
                {
                    "tag": "a",
                    "text": epic["name"],
                    "href": f"{MEEGLE}/{SPACE}/story/detail/{epic['id']}",
                }
            ]
        )
        for issue in epic["issues"]:
            lines.append(
                [
                    {
                        "tag": "a",
                        "text": f"m-{issue['id']} · {issue.get('name', '')}",
                        "href": f"{MEEGLE}/{SPACE}/issue/detail/{issue['id']}",
                    }
                ]
            )
    lines.append([{"tag": "a", "text": "Ver despliegue y logs", "href": ctx["run_url"]}])
    return {"en_us": {"title": "Deploy · seguimiento de la épica", "content": lines}}


def notify_epics(ctx: dict[str, Any], github: GitHub) -> None:
    """Optional best-effort routing; errors are contained by deploy_notify.main."""
    if os.getenv("DEPLOY_EPIC_NOTIFICATIONS", "").lower() != "true":
        return
    required = (
        "DEPLOY_MEEGLE_PLUGIN_ID",
        "DEPLOY_MEEGLE_PLUGIN_SECRET",
        "DEPLOY_MEEGLE_USER_KEY",
        "DEPLOY_LARK_APP_ID",
        "DEPLOY_LARK_APP_SECRET",
    )
    if missing := [name for name in required if not os.getenv(name, "").strip()]:
        print(f"::notice::Epic deploy notices not configured: {', '.join(missing)}.")
        return
    ids = ticket_ids(ctx, github)
    if not ids:
        print("::notice::No m- ticket in this deployment; general notice only.")
        return
    auth = request_json(
        f"{MEEGLE}/open_api/authen/plugin_token",
        {"plugin_id": os.environ[required[0]], "plugin_secret": os.environ[required[1]], "type": 0},
        {},
    )
    if auth.get("error", {}).get("code", 0) != 0:
        raise RoutingError("Meegle auth refused")
    token = (auth.get("data") or {}).get("token")
    if not isinstance(token, str) or not token:
        raise RoutingError("missing Meegle token")
    groups = destinations(ids, token)
    if os.getenv("DEPLOY_EPIC_DRY_RUN", "").lower() == "true":
        routes = {chat: [e["id"] for e in epics] for chat, epics in groups.items()}
        print(f"Epic notice dry run: {json.dumps(routes)}; no messages sent.")
        return
    if not groups:
        return
    auth = request_json(
        f"{LARK}/auth/v3/tenant_access_token/internal",
        {"app_id": os.environ[required[3]], "app_secret": os.environ[required[4]]},
        {},
    )
    token = auth.get("tenant_access_token")
    if auth.get("code") != 0 or not isinstance(token, str) or not token:
        raise RoutingError("Lark auth refused")
    for chat, epics in groups.items():
        # A rerun is a distinct attempt; retrying delivery within one attempt is deduplicated.
        key = f"{ctx['repo']}:{ctx['run_id']}:{ctx['run_attempt']}:{chat}"
        try:
            answer = request_json(
                f"{LARK}/im/v1/messages?receive_id_type=chat_id",
                {
                    "receive_id": chat,
                    "msg_type": "post",
                    "content": json.dumps(message(ctx, epics), ensure_ascii=False),
                    "uuid": hashlib.sha256(key.encode()).hexdigest()[:32],
                },
                {"Authorization": f"Bearer {token}"},
            )
            if answer.get("code") != 0 or not (answer.get("data") or {}).get("message_id"):
                raise RoutingError("Lark message refused")
            print(f"Epic deploy notice sent to {chat}.")
        except RoutingError:
            print(f"::warning::Epic deploy notice failed for {chat}; continuing other chats.")

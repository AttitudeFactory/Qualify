"""Post deploy outcomes to Qualify-devs and, optionally, the affected epic chats.

Used by the `notify` job of `.github/workflows/deploy.yml`. It builds ONE Lark interactive
card for the general Lark custom bot from the results
of the `resolve` → `images` → `deploy` jobs plus what the GitHub REST API knows about the
run (job durations, the failed step) and the commit (subject, author, pull request).
`deploy_epics` optionally resolves the changed tickets' Meegle Features and sends one
application-bot post per chat. It does not depend on the custom-bot webhook.

Pure stdlib. It never fails the workflow: a missing webhook is a notice, an unreachable
or rejecting Lark is a warning, the deploy result stands either way.

    DEVOPS_WEBHOOK_URL=https://open.larksuite.com/open-apis/bot/v2/hook/<token> \\
    RESULT_RESOLVE=success RESULT_IMAGES=success RESULT_DEPLOY=failure SHA=<sha> \\
    python3 .github/scripts/deploy_notify.py
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

from deploy_epics import notify_epics

STAGES = ("resolve", "images", "deploy")  # the jobs of deploy.yml, in order
_PR_IN_SUBJECT = re.compile(r"Merge pull request #(\d+)|\(#(\d+)\)\s*$")
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total = max(0, int(round(seconds)))
    minutes, secs = divmod(total, 60)
    return f"{minutes} min {secs:02d} s" if minutes else f"{secs} s"


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ----------------------------------------------------------------------------- GitHub REST
def _github(path: str) -> Any | None:
    """GET one GitHub REST resource with the job's token; `None` on any failure."""
    token = _env("GITHUB_TOKEN")
    base = _env("GITHUB_API_URL", "https://api.github.com")
    req = urllib.request.Request(
        f"{base}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - fixed host
            return json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        print(f"::notice::GitHub API {path} unavailable ({exc}); the notice will be thinner.")
        return None


def commit_info(repo: str, sha: str) -> dict[str, str]:
    """Subject, author and pull request of the deployed commit (best effort)."""
    info: dict[str, str] = {}
    if not _FULL_SHA.match(sha):
        return info
    data = _github(f"/repos/{repo}/commits/{sha}")
    if not data:
        return info
    message = (data.get("commit") or {}).get("message") or ""
    info["subject"] = message.splitlines()[0][:120] if message else ""
    author = data.get("author") or {}
    git_author = (data.get("commit") or {}).get("author") or {}
    login = author.get("login") or ""
    name = git_author.get("name") or login
    info["author"] = f"{name} (@{login})" if login and login != name else name
    match = _PR_IN_SUBJECT.search(info["subject"])
    if match:
        info["pr"] = match.group(1) or match.group(2)
    return info


def run_info(repo: str, run_id: str) -> dict[str, Any]:
    """Per-stage conclusion/duration/failed step and the run's total duration."""
    stages: dict[str, dict[str, Any]] = {name: {} for name in STAGES}
    out: dict[str, Any] = {"stages": stages, "total": None}
    run = _github(f"/repos/{repo}/actions/runs/{run_id}")
    started = _parse_ts((run or {}).get("run_started_at"))
    if started:
        out["total"] = (datetime.now(UTC) - started).total_seconds()
    jobs = _github(f"/repos/{repo}/actions/runs/{run_id}/jobs?per_page=50")
    for job in (jobs or {}).get("jobs") or []:
        name = job.get("name")
        if name not in stages:
            continue
        begin, end = _parse_ts(job.get("started_at")), _parse_ts(job.get("completed_at"))
        stage = stages[name]
        stage["conclusion"] = job.get("conclusion")
        stage["started_at"] = job.get("started_at")
        stage["duration"] = (end - begin).total_seconds() if begin and end else None
        failed = [s.get("name") for s in job.get("steps") or [] if s.get("conclusion") == "failure"]
        if failed:
            stage["failed_step"] = failed[0]
        stage["url"] = job.get("html_url")
    return out


# ----------------------------------------------------------------------------- the card
def headline(results: dict[str, str]) -> tuple[str, str]:
    """(title, header colour) from the three job results. Every title contains the word
    "Deploy" so a custom bot protected with that keyword accepts the card."""
    if results["deploy"] == "success":
        return "✅ Deploy OK · producción actualizada", "green"
    if results["resolve"] == "failure":
        return "❌ Deploy rechazado · el commit no está en main", "grey"
    if results["images"] != "success":
        return "❌ Deploy falló construyendo las imágenes · producción sin cambios", "red"
    return "❌ Deploy falló en el servidor o en el smoke test · revisar", "red"


def _stage_icon(result: str | None) -> str:
    return {"success": "✅", "failure": "❌", "cancelled": "🚫", "skipped": "⏭️"}.get(
        result or "", "⏳"
    )


def build_card(ctx: dict[str, Any]) -> dict[str, Any]:
    """The Lark interactive card. `ctx` is what `main()` gathers; pure, so it is testable."""
    results: dict[str, str] = ctx["results"]
    title, colour = headline(results)
    sha: str = ctx["sha"]
    short = sha[:7]
    commit: dict[str, str] = ctx.get("commit") or {}
    repo_url = f"{ctx['server_url']}/{ctx['repo']}"
    commit_md = f"[`{short}`]({repo_url}/commit/{sha})" if _FULL_SHA.match(sha) else f"`{sha}`"
    if commit.get("subject"):
        commit_md += f" {commit['subject']}"
    pr_md = f"[#{commit['pr']}]({repo_url}/pull/{commit['pr']})" if commit.get("pr") else "—"

    fields = [
        ("Commit", commit_md),
        ("PR", pr_md),
        ("Autor del commit", commit.get("author") or "—"),
        ("Disparado por", ctx["trigger"]),
        ("Acción", ctx["action"]),
        ("Duración total", _fmt_duration(ctx["run"].get("total"))),
    ]
    lines = []
    for name in STAGES:
        stage = ctx["run"]["stages"].get(name) or {}
        result = stage.get("conclusion") or results.get(name)
        line = f"{_stage_icon(result)} **{name}** · {_fmt_duration(stage.get('duration'))}"
        if stage.get("failed_step"):
            line += f" — falló el paso «{stage['failed_step']}»"
        if stage.get("url"):
            line += f" · [log]({stage['url']})"
        lines.append(line)

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**{k}**\n{v}"}}
                for k, v in fields
            ],
        },
        {"tag": "hr"},
        {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}},
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": f"run {ctx['run_id']} · intento {ctx['run_attempt']} · {now}",
                }
            ],
        },
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "Ver corrida"},
                    "url": ctx["run_url"],
                    "type": "primary" if results["deploy"] != "success" else "default",
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "Abrir Qualify"},
                    "url": ctx["public_url"],
                    "type": "default",
                },
            ],
        },
    ]
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title}, "template": colour},
        "elements": elements,
    }


def sign(secret: str, timestamp: int) -> str:
    """Lark custom-bot signature: HMAC-SHA256 keyed with "<timestamp>\\n<secret>" over an
    empty message, base64."""
    key = f"{timestamp}\n{secret}".encode()
    return base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode()


def payload(card: dict[str, Any], secret: str = "") -> dict[str, Any]:
    body: dict[str, Any] = {"msg_type": "interactive", "card": card}
    if secret:
        ts = int(time.time())
        body["timestamp"] = str(ts)
        body["sign"] = sign(secret, ts)
    return body


def post(webhook: str, body: dict[str, Any]) -> None:
    """Send the card. Lark answers HTTP 200 even when it rejects a message, so the JSON
    `code` (new) / `StatusCode` (old) is checked too. Never raises."""
    data = json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(
        webhook, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - the secret URL
            raw = resp.read().decode(errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"::warning::Could not post to Lark Qualify-devs ({exc}); the deploy result stands.")
        return
    try:
        answer = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        answer = {}
    code = answer.get("code", answer.get("StatusCode", 0))
    if code not in (0, "0"):
        msg = answer.get("msg") or answer.get("StatusMessage") or raw[:200]
        print(
            f"::warning::Lark rejected the deploy notice (code {code}: {msg}); "
            "the deploy result stands."
        )
    else:
        print("Deploy notice posted to Lark Qualify-devs.")


def trigger_text(event: str, actor: str) -> str:
    if event == "workflow_dispatch":
        return f"manual · {actor}"
    if event == "push":
        return f"automático · merge a main por {actor}"
    if event == "schedule":
        return "automático · tip de main del día"
    return f"{event} · {actor}"


def main() -> int:
    webhook = _env("DEVOPS_WEBHOOK_URL")
    if not webhook and _env("DEPLOY_EPIC_NOTIFICATIONS").lower() != "true":
        print("::notice::No deploy notification destination is enabled.")
        return 0
    repo = _env("GITHUB_REPOSITORY")
    run_id = _env("GITHUB_RUN_ID")
    sha = _env("SHA") or "main"
    ctx: dict[str, Any] = {
        "repo": repo,
        "server_url": _env("GITHUB_SERVER_URL", "https://github.com"),
        "run_id": run_id,
        "run_attempt": _env("GITHUB_RUN_ATTEMPT", "1"),
        "run_url": f"{_env('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{run_id}",
        "sha": sha,
        "action": _env("ACTION", "deploy"),
        "trigger": trigger_text(_env("GITHUB_EVENT_NAME"), _env("GITHUB_ACTOR")),
        "public_url": _env("PUBLIC_URL", "https://qualify.attitudefactory.co"),
        "results": {name: _env(f"RESULT_{name.upper()}") for name in STAGES},
        "commit": commit_info(repo, sha),
        "run": run_info(repo, run_id),
    }
    if webhook:
        post(webhook, payload(build_card(ctx), _env("DEVOPS_WEBHOOK_SECRET")))
    try:
        notify_epics(ctx, _github)
    except Exception as exc:
        # Notification failures must never change the deployment result. Only the type
        # is logged: upstream exceptions can contain tokens or request bodies.
        print(f"::warning::Epic deploy notices unavailable ({type(exc).__name__}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

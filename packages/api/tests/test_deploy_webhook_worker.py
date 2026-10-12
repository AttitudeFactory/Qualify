"""Static guards on `deploy/docker-compose.prod.yml` for the QUA-147 webhook processor.

The receiver only RECORDS Meta webhooks; without a running processor every mention stays
`pending`. These checks pin that production runs it by default, and that adding it did not
touch the `calendar-worker`, which publishes for real and must stay behind its profile.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE = yaml.safe_load(
    (REPO_ROOT / "deploy" / "docker-compose.prod.yml").read_text(encoding="utf-8")
)
SERVICES = COMPOSE["services"]


def test_webhook_worker_runs_by_default() -> None:
    worker = SERVICES["webhook-worker"]
    assert "profiles" not in worker  # no profile: it starts with every `up`
    assert worker["restart"] == "unless-stopped"
    command = worker["command"]
    assert command[:3] == ["python", "-m", "qualify_api.webhooks.worker"]
    assert "--interval" in command
    assert "--once" not in command  # a long-running loop, not a one-shot


def test_webhook_worker_publishes_nothing_and_exposes_nothing() -> None:
    worker = SERVICES["webhook-worker"]
    assert "ports" not in worker
    assert "volumes" not in worker
    assert not any("planner" in str(part) for part in worker["command"])
    assert worker["depends_on"]["postgres"]["condition"] == "service_healthy"


def test_calendar_worker_is_still_behind_its_profile() -> None:
    assert SERVICES["calendar-worker"]["profiles"] == ["calendar-worker"]

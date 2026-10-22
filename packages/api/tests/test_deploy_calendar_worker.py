"""Static guards on `deploy/docker-compose.prod.yml` for the QUA-111 calendar executor.

m-24828928: the executor sat behind an opt-in `calendar-worker` profile that was never
enabled on the server, while the worker embedded in `reflex` is forced off — so nothing
ran the tick and no scheduled post was ever published in production. These checks pin
that exactly one path is on in production: the dedicated service, started by every `up`.
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


def test_calendar_worker_runs_by_default() -> None:
    worker = SERVICES["calendar-worker"]
    assert "profiles" not in worker  # no profile: it starts with every `up`
    assert worker["restart"] == "unless-stopped"
    command = worker["command"]
    assert command[:3] == ["python", "-m", "qualify_api.planner.worker"]
    assert "--interval" in command
    assert "--once" not in command  # a long-running loop, not a one-shot


def test_calendar_worker_defaults_to_production_discovery() -> None:
    command = SERVICES["calendar-worker"]["command"]
    assert "${QUALIFY_CALENDAR_WORKER_SCOPE:---all-tenants}" in command


def test_calendar_worker_can_read_media_and_its_heartbeat_store() -> None:
    worker = SERVICES["calendar-worker"]
    assert "uploads:/data/uploaded_files" in worker["volumes"]
    assert worker["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert worker["depends_on"]["redis"]["condition"] == "service_healthy"
    assert "ports" not in worker


def test_the_piece_purge_is_a_dry_run_unless_switched_on() -> None:
    # m-24828907: the worker's daily purge deletes only when .env.prod says so.
    env = SERVICES["calendar-worker"]["environment"]
    assert env["QUALIFY_PIECE_PURGE_EXECUTE"] == "${QUALIFY_PIECE_PURGE_EXECUTE:-0}"


def test_embedded_worker_stays_off_in_reflex() -> None:
    # One path only: the dedicated service publishes, the UI process does not.
    assert SERVICES["reflex"]["environment"]["QUALIFY_CALENDAR_WORKER"] == "off"

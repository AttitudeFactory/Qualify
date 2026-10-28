"""Static guards on `deploy/docker-compose.prod.yml` for `creative-worker` (m-24852163).

- Always on (no profile): `calendar-worker` sat behind a profile nobody enabled and no
  scheduled post was ever published (m-24828928).
- Fits in 512 MiB with no swap (platform-engineer's verdict) and restarts on its own.
- Holds the queue door's DSN, assembled with `:-` so a missing password never blocks
  every deploy (compose interpolates the whole file).
- Exactly one service runs the recovery of billed BytePlus videos (m-24852492).
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_TEXT = (REPO_ROOT / "deploy" / "docker-compose.prod.yml").read_text(encoding="utf-8")
SERVICES = yaml.safe_load(COMPOSE_TEXT)["services"]
JUSTFILE = (REPO_ROOT / "justfile").read_text(encoding="utf-8")


def test_creative_worker_runs_by_default_and_restarts() -> None:
    worker = SERVICES["creative-worker"]
    assert "profiles" not in worker
    assert worker["restart"] == "unless-stopped"
    command = worker["command"]
    assert command[:3] == ["python", "-m", "qualify_api.creative.worker"]
    assert "--all-tenants" in command and "--once" not in command
    assert "ports" not in worker


def test_creative_worker_fits_in_512_mib_without_swap() -> None:
    worker = SERVICES["creative-worker"]
    assert worker["mem_limit"] == "512m"
    assert worker["memswap_limit"] == "512m"
    assert worker["environment"]["QUALIFY_CREATIVE_WORKER_DOWNLOADS"] == (
        "${QUALIFY_CREATIVE_WORKER_DOWNLOADS:-2}"
    )


def test_only_creative_worker_holds_the_queue_door() -> None:
    dsn = SERVICES["creative-worker"]["environment"]["QUALIFY_CREATIVE_WORKER_DSN"]
    assert "qualify_creative_worker:${QUALIFY_DB_CREATIVE_WORKER_PASSWORD:-}@postgres" in dsn
    assert "${QUALIFY_DB_CREATIVE_WORKER_PASSWORD:?" not in COMPOSE_TEXT
    for name, service in SERVICES.items():
        if name == "creative-worker":
            continue
        env = service.get("environment") or {}
        assert not env.get("QUALIFY_CREATIVE_WORKER_DSN"), name


def test_the_recovery_pass_runs_in_creative_worker_only() -> None:
    env = SERVICES["calendar-worker"]["environment"]
    assert env["QUALIFY_CALENDAR_VENDOR_RECOVERY"] == "off"
    assert "QUALIFY_CALENDAR_VENDOR_RECOVERY" not in SERVICES["creative-worker"]["environment"]


def test_creative_worker_waits_for_its_stores() -> None:
    depends = SERVICES["creative-worker"]["depends_on"]
    assert depends["postgres"]["condition"] == "service_healthy"
    assert depends["redis"]["condition"] == "service_healthy"


def test_just_has_the_local_recipes() -> None:
    assert "creative-worker *args:" in JUSTFILE
    assert "creative-tick *args:" in JUSTFILE
    assert "python -m qualify_api.creative.worker --once" in JUSTFILE

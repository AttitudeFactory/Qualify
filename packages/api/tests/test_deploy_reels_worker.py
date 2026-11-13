"""Static guards on `deploy/docker-compose.prod.yml` and the `justfile` for `reels-worker`
(ADR 42 R8, m-24854855).

- Always on (no profile) and no switch of its own: the screen reads only what the runs
  store, so a worker that is off leaves every screen empty (architect, 2026-11-04). The
  kill switch is the metered gate's `QUALIFY_SCRAPECREATORS_PAID`.
- A deploy's SIGTERM gets `stop_grace_period: 120s` to put the run in flight back in the
  queue before the SIGKILL, transcripts in flight (at most 2 x 45 s) included.
- Holds its door's DSN alone, assembled with `:-` so a missing password never blocks
  every deploy (compose interpolates the whole file).
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_TEXT = (REPO_ROOT / "deploy" / "docker-compose.prod.yml").read_text(encoding="utf-8")
SERVICES = yaml.safe_load(COMPOSE_TEXT)["services"]
JUSTFILE = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
ENV_EXAMPLE = (REPO_ROOT / "deploy" / ".env.prod.example").read_text(encoding="utf-8")


def test_reels_worker_runs_by_default_for_every_tenant_and_restarts() -> None:
    worker = SERVICES["reels-worker"]
    assert "profiles" not in worker and "ports" not in worker
    assert worker["restart"] == "unless-stopped"
    command = worker["command"]
    assert command[:3] == ["python", "-m", "qualify_api.referentes.worker"]
    assert "--all-tenants" in command and "--once" not in command
    assert "--dry-run" not in command
    assert "QUALIFY_REELS_WORKER_ENABLED" not in COMPOSE_TEXT  # no switch of its own


def test_a_deploy_gives_the_run_in_flight_two_minutes() -> None:
    assert SERVICES["reels-worker"]["stop_grace_period"] == "120s"


def test_reels_worker_has_a_memory_cap_without_swap() -> None:
    worker = SERVICES["reels-worker"]
    assert worker["mem_limit"] == worker["memswap_limit"] == "384m"


def test_only_reels_worker_holds_its_door() -> None:
    dsn = SERVICES["reels-worker"]["environment"]["QUALIFY_REELS_WORKER_DSN"]
    assert "qualify_reels_worker:${QUALIFY_DB_REELS_WORKER_PASSWORD:-}@postgres" in dsn
    assert "${QUALIFY_DB_REELS_WORKER_PASSWORD:?" not in COMPOSE_TEXT
    for name, service in SERVICES.items():
        if name == "reels-worker":
            continue
        env = service.get("environment") or {}
        assert not env.get("QUALIFY_REELS_WORKER_DSN"), name
    # the raw password reaches only `migrate` (bootstrap_db_roles.py), blanked elsewhere
    assert SERVICES["migrate"]["environment"]["QUALIFY_DB_REELS_WORKER_PASSWORD"] == (
        "${QUALIFY_DB_REELS_WORKER_PASSWORD:-}"
    )
    assert SERVICES["reels-worker"]["environment"]["QUALIFY_DB_REELS_WORKER_PASSWORD"] == ""


def test_reels_worker_waits_for_postgres() -> None:
    assert SERVICES["reels-worker"]["depends_on"]["postgres"]["condition"] == "service_healthy"


def test_the_password_is_in_the_env_example() -> None:
    assert "\nQUALIFY_DB_REELS_WORKER_PASSWORD=\n" in ENV_EXAMPLE


def test_just_has_the_local_recipes() -> None:
    assert "reels-worker *args:" in JUSTFILE
    assert "reels-tick *args:" in JUSTFILE
    assert "python -m qualify_api.referentes.worker --once" in JUSTFILE
    assert "reel-purge *args:" in JUSTFILE
    assert "python -m qualify_api.referentes.reel_retention {{args}}" in JUSTFILE


def test_the_copies_of_reel_videos_are_purged_for_real() -> None:
    """ADR 44 F9 (founder, 2026-11-04): the service deletes the copies after 30 days; the
    purge is a dry run anywhere this flag is not "1"."""
    assert SERVICES["reels-worker"]["environment"]["QUALIFY_REEL_PURGE_EXECUTE"] == "1"
    for name, service in SERVICES.items():
        if name != "reels-worker":
            assert "QUALIFY_REEL_PURGE_EXECUTE" not in (service.get("environment") or {}), name

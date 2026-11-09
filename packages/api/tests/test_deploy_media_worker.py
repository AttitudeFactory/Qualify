"""Static guards on the Galería's `media-worker` service and upload cap (m-24957794, ADR 47).

- Always on (no profile) and restarts like every worker; production scope is
  `--all-tenants`.
- 1 CPU and 768 MiB with no swap (founder's D8, 2026-11-05): a 60 s transcode cannot starve
  Postgres or the other products on the shared box.
- Reads the staged uploads from the same `uploads` volume Reflex writes to.
- Qualify's internal Caddy caps `/_upload*` bodies at 520 MB (the app's own 500 MB per file
  refusal, in Spanish, needs the multipart margin); the shared edge proxy is
  untouched (it sets no limit).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICES = yaml.safe_load(
    (REPO_ROOT / "deploy" / "docker-compose.prod.yml").read_text(encoding="utf-8")
)["services"]
CADDYFILE = (REPO_ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
EDGE_CADDYFILE = (REPO_ROOT / "deploy" / "edge" / "Caddyfile").read_text(encoding="utf-8")


def test_media_worker_runs_by_default_over_every_tenant() -> None:
    worker = SERVICES["media-worker"]
    assert "profiles" not in worker
    assert worker["restart"] == "unless-stopped"
    command = worker["command"]
    assert command[:3] == ["python", "-m", "qualify_api.catalog.media_worker"]
    assert "--all-tenants" in command
    assert "--once" not in command and "--reconcile" not in command
    assert "ports" not in worker


def test_media_worker_is_capped_at_one_cpu_and_768_mib_without_swap() -> None:
    worker = SERVICES["media-worker"]
    assert float(worker["cpus"]) == 1.0
    assert worker["mem_limit"] == "768m"
    assert worker["memswap_limit"] == "768m"


def test_media_worker_reads_the_uploads_volume_reflex_writes() -> None:
    worker = SERVICES["media-worker"]
    mount = "uploads:/data/uploaded_files"
    assert mount in worker["volumes"]
    assert mount in SERVICES["reflex"]["volumes"]
    assert worker["environment"]["REFLEX_UPLOADED_FILES_DIR"] == "/data/uploaded_files"
    assert worker["depends_on"]["postgres"]["condition"] == "service_healthy"


def test_media_worker_never_holds_another_workers_door() -> None:
    env = SERVICES["media-worker"]["environment"]
    for door in ("QUALIFY_CREATIVE_WORKER_DSN", "QUALIFY_CONNECTION_PURGE_DSN"):
        assert not env.get(door)


def test_uploads_are_capped_at_520_mb_in_qualifys_own_caddy_only() -> None:
    assert re.search(r"@upload path /_upload /_upload/\*", CADDYFILE)
    assert re.search(r"request_body @upload \{\s*max_size 520MB\s*\}", CADDYFILE)
    assert "request_body" not in EDGE_CADDYFILE

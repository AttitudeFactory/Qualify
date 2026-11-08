"""Static guards on the production `postgres` service's memory posture (m-24972741).

- Never capped: a `mem_limit` would make the kernel kill the one service every other cap
  protects (m-24852229).
- Behind every other container for the host OOM killer (`oom_score_adj: -400`), yet still
  ahead of dockerd (-500): no extreme negative value, per Docker docs «Resource
  constraints» › «Understand the risks of running out of memory»
  (https://docs.docker.com/engine/containers/resource_constraints/): "You shouldn't try to
  circumvent these safeguards by manually setting --oom-score-adj to an extreme negative
  number".
- A soft floor of 256 MiB (`mem_reservation`, cgroup v2 `memory.low`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICES = yaml.safe_load(
    (REPO_ROOT / "deploy" / "docker-compose.prod.yml").read_text(encoding="utf-8")
)["services"]


def test_postgres_has_no_hard_memory_cap() -> None:
    postgres = SERVICES["postgres"]
    assert "mem_limit" not in postgres
    assert "memswap_limit" not in postgres
    assert "oom_kill_disable" not in postgres


def test_postgres_goes_behind_every_other_container_for_the_oom_killer() -> None:
    postgres = SERVICES["postgres"]
    assert postgres["oom_score_adj"] == -400
    for name, service in SERVICES.items():
        if name != "postgres":
            assert service.get("oom_score_adj", 0) > postgres["oom_score_adj"], name


def test_postgres_keeps_a_256_mib_soft_floor() -> None:
    assert SERVICES["postgres"]["mem_reservation"] == "256m"

"""m-24852160 offline: pool configuration, the migration and the module agree, and the
worker door stays inside the worker (ADR 41, `docs/seguridad-creative-worker.md` §2).

Pure Python and AST — no database. The behaviour against Postgres (the cap under
concurrent claims, recovery, RLS, grants) is `test_creative_jobs_db.py`."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from qualify_api.creative import job_queue as q

_REPO = Path(__file__).resolve().parents[3]
_SRC = _REPO / "packages" / "api" / "src" / "qualify_api"
_MIGRATION = _REPO / "migrations" / "postgres" / "versions" / "0096_creative_jobs_vendor_slots.py"


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m0096", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- QUALIFY_VENDOR_POOLS ----------------------------------------------------------------


def test_default_pools_are_byteplus_caps() -> None:
    assert q.parse_vendor_pools(None) == {q.SEEDANCE_POOL: 10, q.OMNIHUMAN_POOL: 1}
    assert q.parse_vendor_pools("  ") == {q.SEEDANCE_POOL: 10, q.OMNIHUMAN_POOL: 1}


def test_configured_sizes_override_defaults_and_add_pools() -> None:
    sizes = q.parse_vendor_pools("byteplus:seedance-2-5=30, byteplus@acct2:seedance-2-5=10,")
    assert sizes[q.SEEDANCE_POOL] == 30
    assert sizes["byteplus@acct2:seedance-2-5"] == 10
    assert sizes[q.OMNIHUMAN_POOL] == 1


def test_zero_pauses_a_pool() -> None:
    assert q.parse_vendor_pools("byteplus:omnihuman-1-5=0")[q.OMNIHUMAN_POOL] == 0


@pytest.mark.parametrize(
    "raw", ["byteplus:seedance-2-5", "=3", "byteplus:seedance-2-5=diez", "x=-1"]
)
def test_malformed_config_fails_loudly(raw: str) -> None:
    with pytest.raises(q.VendorPoolsConfigError):
        q.parse_vendor_pools(raw)


def test_pool_size_reads_env_and_falls_back_to_ten() -> None:
    env = {q.POOLS_ENV: "byteplus:seedance-2-5=12"}
    assert q.pool_size(q.SEEDANCE_POOL, env) == 12
    assert q.pool_size(q.OMNIHUMAN_POOL, env) == 1
    assert q.pool_size("byteplus:seedream-5", env) == q.DEFAULT_POOL_SIZE == 10
    assert q.pool_size(q.SEEDANCE_POOL, {}) == 10


def test_defaults_fit_inside_the_seeded_slots() -> None:
    for pool, size in q.DEFAULT_POOL_SIZES.items():
        assert size <= q.SEEDED_SLOTS[pool]


# --- the migration and the module say the same thing -------------------------------------


def test_migration_vocabularies_match_the_module() -> None:
    m = _migration()
    assert set(m.KINDS) == q.KINDS
    assert set(m.LANES) == q.LANES
    assert set(m.STATUSES) == q.STATUSES
    assert m.SEEDED_SLOTS == dict(q.SEEDED_SLOTS)
    assert m.down_revision == "0095"


def test_worker_grants_are_the_security_review_list() -> None:
    """`docs/seguridad-creative-worker.md` §2, verbatim: widening it is an ADR change."""
    m = _migration()
    assert set(m.WORKER_SELECT_COLUMNS) == {
        "id",
        "tenant_id",
        "kind",
        "vendor_model",
        "lane",
        "status",
        "priority",
        "not_before",
        "deadline",
        "queued_at",
        "claimed_by",
        "claim_token",
        "lease_until",
        "attempts",
        "vendor_task_id",
    }
    assert set(m.WORKER_UPDATE_COLUMNS) == {
        "status",
        "claimed_by",
        "claim_token",
        "lease_until",
        "attempts",
    }
    assert "vendor_task_id" not in m.WORKER_UPDATE_COLUMNS


def test_bad_vocabulary_is_refused_before_sql() -> None:
    with pytest.raises(ValueError):
        q.enqueue_job(
            None,  # type: ignore[arg-type]  # never reached
            tenant_id=None,  # type: ignore[arg-type]
            draft_id=None,  # type: ignore[arg-type]
            kind="video",
            revision=1,
            vendor_model=q.SEEDANCE_POOL,
            lane=q.LANE_IMMEDIATE,
        )
    with pytest.raises(ValueError):
        q.settle_job(
            None,  # type: ignore[arg-type]
            job_id=None,  # type: ignore[arg-type]
            claim_token=1,
            status=q.CANCELLED,
            now=None,  # type: ignore[arg-type]
        )


# --- the worker door stays in the worker ---------------------------------------------------


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
            if node.module:
                names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def test_creative_worker_door_is_imported_only_by_the_worker() -> None:
    """Security review §2: no request path may take the cross-tenant door by accident.
    Allowed: `qualify_api/creative/worker.py` or the `qualify_api/creative/worker/`
    package (m-24852163)."""
    offenders = []
    for path in _SRC.rglob("*.py"):
        relative = path.relative_to(_SRC).as_posix()
        names = _imports(path)
        uses_door = "creative_worker_session" in names or any(
            name.endswith("db.creative_worker") for name in names
        )
        if uses_door and not (
            relative == "creative/worker.py" or relative.startswith("creative/worker/")
        ):
            offenders.append(relative)
    assert offenders == []


def test_the_repository_opens_no_session_itself() -> None:
    names = _imports(_SRC / "creative" / "job_queue.py")
    doors = {"tenant_session", "admin_session", "credential_session", "creative_worker_session"}
    assert names & doors == set()

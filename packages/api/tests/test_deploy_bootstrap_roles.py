"""`deploy/bootstrap_db_roles.py` (run by `migrate` on every deploy): each role is applied
on its own, so one bad password never takes LOGIN away from a role that works, and an
optional role without a valid password is always NOLOGIN (never the committed dev one).

Offline: a fake connection records the ALTER ROLE statements instead of a database.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from psycopg import sql

_SCRIPT = Path(__file__).resolve().parents[3] / "deploy" / "bootstrap_db_roles.py"
_GOOD = "x" * 24


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bootstrap_db_roles", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bootstrap = _load()


class _Row:
    def __init__(self, found: bool) -> None:
        self._found = found

    def fetchone(self) -> tuple[int] | None:
        return (1,) if self._found else None


class _FakeConn:
    """Every role exists; ALTERs are recorded as (role, action)."""

    def __init__(self) -> None:
        self.alters: dict[str, str] = {}

    def execute(self, query: object, params: tuple[str, ...] | None = None) -> _Row:
        if isinstance(query, str):
            return _Row(True)
        assert isinstance(query, sql.Composed)
        statement = query.as_string(None)  # e.g. ALTER ROLE "qualify_x" WITH NOLOGIN
        role = statement.split('"')[1]
        if "WITH NOLOGIN" in statement:
            self.alters[role] = "NOLOGIN"
        elif "WITH LOGIN PASSWORD" in statement:
            self.alters[role] = "LOGIN"
        else:
            self.alters[role] = "PASSWORD"
        return _Row(True)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for variable in bootstrap.ROLE_PASSWORD_ENVS.values():
        monkeypatch.setenv(variable, _GOOD)
    for variable in bootstrap.OPTIONAL_ROLE_PASSWORD_ENVS.values():
        monkeypatch.setenv(variable, _GOOD)
    return monkeypatch


def test_all_valid_sets_every_password_and_login(env: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    assert bootstrap.apply(conn) == []
    for role in bootstrap.ROLE_PASSWORD_ENVS:
        assert conn.alters[role] == "PASSWORD"
    for role in bootstrap.OPTIONAL_ROLE_PASSWORD_ENVS:
        assert conn.alters[role] == "LOGIN"


@pytest.mark.parametrize("value", ["reels_worker_dev", "  reels_worker_dev  ", "short"])
def test_bad_optional_password_touches_no_role_state(env: pytest.MonkeyPatch, value: str) -> None:
    env.setenv("QUALIFY_DB_REELS_WORKER_PASSWORD", value)
    conn = _FakeConn()
    problems = bootstrap.apply(conn)
    assert len(problems) == 1 and "QUALIFY_DB_REELS_WORKER_PASSWORD" in problems[0]
    assert "qualify_reels_worker" not in conn.alters, "a set-but-invalid value is never applied"
    assert conn.alters["qualify_creative_worker"] == "LOGIN"
    assert conn.alters["qualify_connection_purge"] == "LOGIN"
    assert conn.alters["qualify_app"] == "PASSWORD"


def test_padded_dev_password_is_refused() -> None:
    assert bootstrap._password_problem("V", "   app_dev          ") is not None
    assert bootstrap._password_problem("V", "  webhook_worker_dev  ") is not None
    assert bootstrap._password_problem("V", _GOOD) is None


def test_bad_required_password_leaves_optional_roles_working(env: pytest.MonkeyPatch) -> None:
    env.setenv("QUALIFY_DB_APP_PASSWORD", "app_dev")
    conn = _FakeConn()
    problems = bootstrap.apply(conn)
    assert len(problems) == 1 and "QUALIFY_DB_APP_PASSWORD" in problems[0]
    assert "qualify_app" not in conn.alters, "an invalid required password is never applied"
    for role in bootstrap.OPTIONAL_ROLE_PASSWORD_ENVS:
        assert conn.alters[role] == "LOGIN"


def test_unset_reels_password_means_nologin(env: pytest.MonkeyPatch) -> None:
    env.delenv("QUALIFY_DB_REELS_WORKER_PASSWORD")
    conn = _FakeConn()
    assert bootstrap.apply(conn) == []
    assert conn.alters["qualify_reels_worker"] == "NOLOGIN"


def test_main_raises_after_applying_everything(
    env: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.setenv("QUALIFY_DB_REELS_WORKER_PASSWORD", "short")
    env.setenv("QUALIFY_MIGRATION_DSN", "postgresql+psycopg://o:p@h/db")
    conn = _FakeConn()

    class _Ctx:
        def __enter__(self) -> _FakeConn:
            return conn

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(bootstrap.psycopg, "connect", lambda *a, **k: _Ctx())
    with pytest.raises(SystemExit, match="QUALIFY_DB_REELS_WORKER_PASSWORD"):
        bootstrap.main()
    assert "qualify_reels_worker" not in conn.alters
    assert conn.alters["qualify_creative_worker"] == "LOGIN"

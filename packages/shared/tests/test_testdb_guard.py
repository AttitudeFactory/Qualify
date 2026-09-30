"""The test-database guardrail (`testing/testdb.py`, wired by the root conftest.py).

Pure: no Postgres, no Redis. Pins that no configuration pointing at the development
database — or at Redis db 0 — can be used by a test run, and how in-place migration
edits are told apart from new migrations.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import testdb

DEV = {
    "QUALIFY_APP_DSN": "postgresql+psycopg://qualify_app:app_dev@localhost:5432/qualify",
    "QUALIFY_ADMIN_DSN": "postgresql+psycopg://qualify_admin:admin_dev@localhost:5432/qualify",
    "QUALIFY_CREDENTIAL_DSN": (
        "postgresql+psycopg://qualify_credential:credential_dev@localhost:5432/qualify"
    ),
    "QUALIFY_MIGRATION_DSN": "postgresql+psycopg://qualify_owner:dev_only@localhost:5432/qualify",
    "QUALIFY_REDIS_URL": "redis://localhost:6379/0",
}


def test_the_defaults_are_the_test_database_and_redis_15() -> None:
    env: dict[str, str] = {}
    testdb.apply_test_defaults(env)
    assert testdb.guard_problems(env) == []
    assert testdb.require_safe(env) == "qualify_test"
    assert env["QUALIFY_REDIS_URL"].endswith("/15")


def test_a_variable_already_set_is_kept_and_then_judged() -> None:
    env = {"QUALIFY_APP_DSN": DEV["QUALIFY_APP_DSN"]}
    testdb.apply_test_defaults(env)
    assert env["QUALIFY_APP_DSN"] == DEV["QUALIFY_APP_DSN"]  # never silently replaced
    problems = testdb.guard_problems(env)
    assert any("QUALIFY_APP_DSN" in p and "'qualify'" in p for p in problems)


def test_the_development_configuration_is_refused_entirely() -> None:
    problems = testdb.guard_problems(DEV)
    assert len([p for p in problems if "DSN points at" in p]) == 4
    assert any("Redis db 0" in p for p in problems)
    with pytest.raises(testdb.DbGuardError, match="Refusing"):
        testdb.require_safe(DEV)


@pytest.mark.parametrize(
    "database",
    ["qualify", "postgres", "qualify_testing", "test", "qualify-test", "Qualify_test", None],
)
def test_only_a_lowercase_star_test_name_is_a_test_database(database: str | None) -> None:
    assert not testdb.is_test_database(database)


def test_all_dsns_must_agree_on_one_test_database() -> None:
    env: dict[str, str] = {}
    testdb.apply_test_defaults(env)
    env["QUALIFY_ADMIN_DSN"] = env["QUALIFY_ADMIN_DSN"].replace("qualify_test", "other_test")
    assert any("disagree" in p for p in testdb.guard_problems(env))


@pytest.mark.parametrize("url", ["redis://localhost:6379/0", "redis://localhost:6379", "x"])
def test_redis_db_0_or_unknown_is_refused(url: str) -> None:
    env: dict[str, str] = {}
    testdb.apply_test_defaults(env)
    env["QUALIFY_REDIS_URL"] = url
    assert any("Redis db" in p for p in testdb.guard_problems(env))


def test_reset_refuses_the_development_database_before_any_connection(monkeypatch) -> None:
    for name, value in DEV.items():
        monkeypatch.setenv(name, value)

    def _no_connection(*_a, **_k):
        raise AssertionError("reset must refuse before opening any connection")

    monkeypatch.setattr(testdb, "_owner_engine", _no_connection)
    with pytest.raises(testdb.DbGuardError):
        testdb.reset()
    with pytest.raises(testdb.DbGuardError):
        testdb.ensure()


def test_the_cli_takes_no_database_name(capsys) -> None:
    assert testdb.main(["reset", "qualify"]) == 2
    assert "usage" in capsys.readouterr().err


# --- migration fingerprint ---------------------------------------------------------------


def test_an_in_place_edit_is_told_apart_from_a_new_migration() -> None:
    stored = {"versions/0001.py": "a", "versions/0002.py": "b", "env.py": "e"}
    added = {**stored, "versions/0003.py": "c"}
    edited = {**stored, "versions/0002.py": "B"}
    removed = {"versions/0001.py": "a", "env.py": "e"}

    assert testdb.diff_migrations(stored, added) == testdb.MigrationDiff(
        (), (), ("versions/0003.py",)
    )
    assert testdb.diff_migrations(stored, edited).changed == ("versions/0002.py",)
    assert testdb.diff_migrations(stored, removed).removed == ("versions/0002.py",)


def test_hashes_ignore_line_endings(tmp_path: Path) -> None:
    for sub, newline in (("crlf", b"\r\n"), ("lf", b"\n")):
        root = tmp_path / sub
        (root / "versions").mkdir(parents=True)
        (root / "versions" / "0001.py").write_bytes(b"x = 1" + newline + b"y = 2" + newline)
        (root / "env.py").write_bytes(b"env" + newline)
    assert testdb.migration_hashes(tmp_path / "crlf") == testdb.migration_hashes(tmp_path / "lf")


def test_the_real_migrations_are_all_fingerprinted() -> None:
    hashes = testdb.migration_hashes()
    assert "env.py" in hashes
    assert any(name.startswith("versions/0001") for name in hashes)

"""Repo-wide test isolation: every pytest run uses `qualify_test` + Redis db 15, never the
development `qualify` (see `testing/testdb.py` for why and how).

- Import time: unset DSNs / Redis URL are pointed at the test targets — before any
  engine exists (the sanctioned DB doors create theirs lazily, on first use).
- `pytest_configure`: the guardrail. A DSN naming a non-`*_test` database, or Redis db 0,
  aborts the run, whatever command was used.
- After collection, when `db` tests are selected: `qualify_test` is created / migrated
  forward (never emptied), and every sanctioned door is checked to really connect there.
- `--reset-test-db`: DROP + CREATE + migrate `qualify_test` BEFORE the run. Explicit only:
  without it, whatever a run leaves stays in `qualify_test` for inspection.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "testing"))

import testdb  # noqa: E402

testdb.apply_test_defaults()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--reset-test-db",
        action="store_true",
        default=False,
        help="Drop, recreate and migrate the TEST database (qualify_test) and flush the "
        "test Redis db before running. Never touches the development database.",
    )


def pytest_configure(config: pytest.Config) -> None:
    try:
        testdb.require_safe()
    except testdb.DbGuardError as exc:
        pytest.exit(str(exc), returncode=pytest.ExitCode.USAGE_ERROR)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    needs_db = any(item.get_closest_marker("db") for item in items)
    reset = config.getoption("--reset-test-db")
    if not (needs_db or reset):
        return  # no database work: unit-only runs never need Postgres up
    try:
        status = testdb.reset() if reset else testdb.ensure()
        if needs_db:
            testdb.verify_live_connections()
    except testdb.DbGuardError as exc:
        pytest.exit(str(exc), returncode=pytest.ExitCode.USAGE_ERROR)
    except Exception as exc:  # noqa: BLE001 — e.g. Postgres not running: say so plainly
        pytest.exit(
            f"The test database is not usable ({type(exc).__name__}: {exc}). "
            "Is Postgres up (`just up`)?",
            returncode=pytest.ExitCode.USAGE_ERROR,
        )
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(f"test database: {status}")

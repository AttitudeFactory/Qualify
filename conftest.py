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
- Every test: no export to a real Langfuse (`_no_langfuse_export`).
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "testing"))

import testdb  # noqa: E402

testdb.apply_test_defaults()

#: The business every offline test's paid reads are charged to (ADR 42 R5).
OFFLINE_TEST_TENANT = UUID("0ff11e00-0000-4000-8000-00000000c0de")


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


# `trylast`: pytest's own `-m` / `-k` deselection is ALSO a `pytest_collection_modifyitems`
# hook, and conftest hooks run before built-in plugins. Without `trylast` this saw every
# collected `db` test even under `-m "not db"`, tried to reach Postgres, and aborted the
# offline-only CI job (found 2026-10-05 by the first `ci` run of the `test` job).
@pytest.hookimpl(trylast=True)
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


@pytest.fixture(autouse=True)
def _no_langfuse_export(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No test traces to a real Langfuse. Since 2026-10-13 the app's .env carries the
    LANGFUSE_* keys, and modules that load it (`load_dotenv`) would make the suite export
    its spans to the local server — and make tracing state leak between tests. A test that
    needs tracing configures its own client (`observability.capture_spans`)."""
    from qualify_shared import observability

    for name in (observability.PUBLIC_KEY_ENV, observability.SECRET_KEY_ENV):
        monkeypatch.delenv(name, raising=False)
    observability.reset()
    yield
    observability.reset()


@pytest.fixture(autouse=True)
def _scrapecreators_gate_offline(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The ScrapeCreators gate (ADR 42 R2) reads and writes `vendor_balance` on every
    call. Offline tests get an empty in-memory balance (= no floor known yet), the switch
    on and no 402 stop carried over from another test; a test that exercises the gate
    installs its own store. Nothing here ever reaches the vendor: tests still pass a
    `MockTransport` client, as before."""
    try:
        from qualify_api.vendors import scrapecreators, uncapped, usage
        from qualify_api.vendors.balance import InMemoryBalanceStore
        from qualify_api.vendors.balance_alert import LowBalanceAlert, NullTeamNotifier
    except ImportError:  # a package suite that does not install qualify_api
        yield
        return
    monkeypatch.delenv(scrapecreators.PAID_SWITCH_ENV, raising=False)
    scrapecreators.configure_balance_store(InMemoryBalanceStore())
    # R5 (m-24854849): a charged call books its credit here, never in Postgres.
    usage.configure_store(usage.InMemoryUsageStore())
    # m-24956180: whether a business is uncapped is read here, never in Postgres.
    uncapped.configure_store(uncapped.InMemoryUncappedStore())
    # Never the production alert: a developer's .env may carry a real Lark webhook.
    scrapecreators.configure_balance_alert(
        LowBalanceAlert(NullTeamNotifier(), dispatch=lambda job: job())
    )
    scrapecreators.reset_halt()
    # R5: the gate refuses a read no business is charged for — and no business is in
    # scope by default, so a screen path that forgets `usage.charge_to` fails its test.
    # A test of the vendor module itself asks for `paid_reads_charged`.
    yield
    scrapecreators.configure_balance_store(None)
    usage.configure_store(None)
    uncapped.configure_store(None)
    scrapecreators.configure_balance_alert(None)
    scrapecreators.reset_halt()


@pytest.fixture
def paid_reads_charged() -> Iterator[UUID]:
    """Opt-in (ADR 42 R5): charge every paid read of the test to a placeholder business
    (in memory only) — for tests of the vendor module itself, where who pays is not
    the point. Screen paths must open their own `usage.charge_to`."""
    from qualify_api.vendors import usage

    with usage.charge_to(OFFLINE_TEST_TENANT):
        yield OFFLINE_TEST_TENANT

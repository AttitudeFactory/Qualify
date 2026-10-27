"""Offline checks for the shared health contract and notification ordering."""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from qualify_api.connections import runtime_health
from qualify_api.connections.events import DomainEvent, InMemoryEventPublisher
from qualify_api.connections.runtime_health import (
    ConnectionRuntimeState,
    mark_connection_unavailable,
)


@pytest.mark.parametrize("status", ["pending", "degraded", "revoked"])
def test_only_active_accounts_can_poll(status: str) -> None:
    state = ConnectionRuntimeState(status, "auth_expired", 3, False, 1)
    assert not state.can_poll
    assert not state.temporary_warning


def test_transient_warning_is_a_level_and_first_success_clears_it() -> None:
    assert not ConnectionRuntimeState("active", None, 2, False, 1).temporary_warning
    assert ConnectionRuntimeState("active", None, 3, False, 1).temporary_warning
    assert not ConnectionRuntimeState("active", None, 0, False, 1).temporary_warning


def test_unknown_cause_is_rejected_before_opening_a_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_session(*args: object, **kwargs: object) -> None:
        raise AssertionError("invalid causes must never touch the database")

    monkeypatch.setattr(runtime_health, "tenant_session", no_session)
    with pytest.raises(ValueError):
        mark_connection_unavailable(
            tenant_id=uuid4(), connection_id=uuid4(), cause="raw Meta error"
        )


@pytest.mark.parametrize("commit_fails", [False, True])
def test_outage_event_is_emitted_only_after_successful_commit(
    monkeypatch: pytest.MonkeyPatch, commit_fails: bool
) -> None:
    committed = False
    row = SimpleNamespace(
        status="active",
        current_credential_version=2,
        reconnect_reason=None,
        temporary_failure_count=2,
        recovery_refresh_pending=True,
    )
    session = SimpleNamespace(scalar=lambda query: row, add=lambda value: None)

    @contextmanager
    def fake_session(*args: object, **kwargs: object) -> Iterator[object]:
        nonlocal committed
        yield session
        if commit_fails:
            raise RuntimeError("transaction rollback")
        committed = True

    class Publisher(InMemoryEventPublisher):
        def publish(self, event: DomainEvent) -> None:
            assert committed
            super().publish(event)

    publisher = Publisher()
    monkeypatch.setattr(runtime_health, "tenant_session", fake_session)
    changed = mark_connection_unavailable(
        tenant_id=uuid4(), connection_id=uuid4(), cause="missing_credential", publisher=publisher
    )
    assert changed is (not commit_fails)
    assert len(publisher.events) == (0 if commit_fails else 1)


def test_old_provider_response_does_not_break_a_fresh_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = SimpleNamespace(status="active", current_credential_version=3)
    session = SimpleNamespace(scalar=lambda query: row)

    @contextmanager
    def fake_session(*args: object, **kwargs: object) -> Iterator[object]:
        yield session

    monkeypatch.setattr(runtime_health, "tenant_session", fake_session)
    publisher = InMemoryEventPublisher()
    assert not mark_connection_unavailable(
        tenant_id=uuid4(),
        connection_id=uuid4(),
        cause="auth_expired",
        expected_credential_version=2,
        publisher=publisher,
    )
    assert row.status == "active"
    assert publisher.events == []


@pytest.mark.parametrize("lookup_fails", [False, True])
def test_manual_health_check_records_missing_credential_without_masking_error(
    monkeypatch: pytest.MonkeyPatch, lookup_fails: bool
) -> None:
    from qualify_api.connections import composition
    from qualify_api.connections.credential_reader import CredentialNotFound

    original = CredentialNotFound("missing")
    reports: list[dict[str, object]] = []

    def fail_check(connection_id: object) -> None:
        raise original

    def lookup(**kwargs: object) -> ConnectionRuntimeState:
        if lookup_fails:
            raise RuntimeError("secondary read failed")
        return ConnectionRuntimeState("active", None, 0, False, 7)

    monkeypatch.setattr(composition.MetaOAuthSettings, "from_env", lambda: object())
    monkeypatch.setattr(composition, "DevEncryptor", lambda: object())
    monkeypatch.setattr(composition, "HttpMetaTokenHealthClient", lambda settings: object())
    monkeypatch.setattr(
        composition, "TokenHealthChecker", lambda **kw: SimpleNamespace(check=fail_check)
    )
    monkeypatch.setattr(composition, "get_connection_runtime_state", lookup)
    monkeypatch.setattr(composition, "mark_connection_unavailable", lambda **kw: reports.append(kw))
    with pytest.raises(CredentialNotFound) as error:
        composition.check_connection_health(tenant_id=uuid4(), connection_id=uuid4())
    assert error.value is original
    assert len(reports) == (0 if lookup_fails else 1)
    if reports:
        assert reports[0]["cause"] == "missing_credential"
        assert reports[0]["expected_credential_version"] == 7

"""Inline regeneration must see the committed revision, and never run after rollback."""

from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from qualify_shared.db import session as db

from qualify_api.creative.dispatch import InlineDispatcher
from qualify_api.creative.service import PostgresContentRepository, fenced_regeneration


@pytest.fixture
def transaction(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = SimpleNamespace(committed="generated", staged="generated", starts=[], fail_commit=False)
    connection = MagicMock()
    session = MagicMock()
    session.scalars.return_value.all.return_value = []

    @contextmanager
    def begin():
        yield connection
        if state.fail_commit:
            raise RuntimeError("commit failed")
        state.committed = state.staged

    monkeypatch.setattr(db, "_get_engine", lambda: SimpleNamespace(begin=begin))
    monkeypatch.setattr(db, "Session", lambda **kwargs: session)

    def start(target, name, tenant_id, draft_id):
        state.starts.append((name, state.committed, db._unit.get()))

    monkeypatch.setattr(InlineDispatcher, "_start", staticmethod(start))
    state.session = session
    return state


def test_fenced_regeneration_starts_only_after_the_revision_commits(transaction) -> None:
    tenant_id, draft_id = uuid4(), uuid4()
    dispatcher = InlineDispatcher(lambda **kwargs: None)
    service = SimpleNamespace(_repo=PostgresContentRepository())

    @fenced_regeneration
    def regenerate(self, **kwargs):
        transaction.staged = "drafting"
        dispatcher.dispatch_generation(tenant_id=tenant_id, draft_id=draft_id)
        assert transaction.starts == []
        assert transaction.committed == "generated"
        return "detail"

    assert regenerate(service, tenant_id=tenant_id, draft_id=draft_id, regenerate=True) == "detail"
    assert transaction.starts == [("creative-generation", "drafting", None)]


def test_rollback_never_launches_generation(transaction) -> None:
    tenant_id = uuid4()
    dispatcher = InlineDispatcher(lambda **kwargs: None)
    with pytest.raises(RuntimeError, match="rollback"):
        with db.tenant_unit_of_work(tenant_id):
            dispatcher.dispatch_generation(tenant_id=tenant_id, draft_id=uuid4())
            raise RuntimeError("rollback")
    assert transaction.starts == []
    assert transaction.committed == "generated"


def test_flush_failure_never_launches_generation(transaction) -> None:
    tenant_id = uuid4()
    transaction.session.flush.side_effect = RuntimeError("flush failed")
    with pytest.raises(RuntimeError, match="flush failed"):
        with db.tenant_unit_of_work(tenant_id):
            InlineDispatcher(lambda **kwargs: None).dispatch_generation(
                tenant_id=tenant_id, draft_id=uuid4()
            )
    assert transaction.starts == []


def test_nested_units_wait_for_the_outer_commit_for_generation_and_final(transaction) -> None:
    tenant_id = uuid4()
    dispatcher = InlineDispatcher(lambda **kwargs: None, lambda **kwargs: None)
    with db.tenant_unit_of_work(tenant_id):
        with db.tenant_unit_of_work(tenant_id):
            dispatcher.dispatch_generation(tenant_id=tenant_id, draft_id=uuid4())
            dispatcher.dispatch_finalize(tenant_id=tenant_id, draft_id=uuid4())
        assert transaction.starts == []
        transaction.staged = "drafting"
    assert transaction.starts == [
        ("creative-generation", "drafting", None),
        ("creative-final", "drafting", None),
    ]


def test_dispatch_cannot_cross_the_unit_tenant(transaction) -> None:
    with db.tenant_unit_of_work(uuid4()):
        with pytest.raises(ValueError, match="cannot change tenant"):
            InlineDispatcher(lambda **kwargs: None).dispatch_generation(
                tenant_id=uuid4(), draft_id=uuid4()
            )
    assert transaction.starts == []


def test_a_failed_unit_does_not_leak_callbacks_into_the_next_unit(transaction) -> None:
    tenant_id = uuid4()
    dispatcher = InlineDispatcher(lambda **kwargs: None)
    with pytest.raises(RuntimeError):
        with db.tenant_unit_of_work(tenant_id):
            dispatcher.dispatch_generation(tenant_id=tenant_id, draft_id=uuid4())
            raise RuntimeError("rollback")
    with db.tenant_unit_of_work(tenant_id):
        pass
    assert transaction.starts == []
    dispatcher.dispatch_generation(tenant_id=tenant_id, draft_id=uuid4())
    assert len(transaction.starts) == 1


def test_commit_failure_never_launches_generation(transaction) -> None:
    tenant_id = uuid4()
    transaction.fail_commit = True
    with pytest.raises(RuntimeError, match="commit failed"):
        with db.tenant_unit_of_work(tenant_id):
            InlineDispatcher(lambda **kwargs: None).dispatch_generation(
                tenant_id=tenant_id, draft_id=uuid4()
            )
    assert transaction.starts == []


@pytest.mark.db
def test_worker_reads_committed_state_from_its_own_postgres_connection(seeded_ab) -> None:
    from qualify_api.tenancy.models import Brand

    tenant_id, _ = seeded_ab
    brand_id = uuid4()
    with db.tenant_session(tenant_id) as session:
        session.add(Brand(id=brand_id, tenant_id=tenant_id, name="before commit"))
    done = Event()
    observed = []

    def run(**kwargs):
        try:
            with db.tenant_session(tenant_id) as session:
                observed.append(session.get(Brand, brand_id).name)
        finally:
            done.set()

    with db.tenant_unit_of_work(tenant_id) as session:
        session.get(Brand, brand_id).name = "after commit"
        session.flush()
        InlineDispatcher(run).dispatch_generation(tenant_id=tenant_id, draft_id=uuid4())
        assert not done.is_set()
    assert done.wait(5)
    assert observed == ["after commit"]

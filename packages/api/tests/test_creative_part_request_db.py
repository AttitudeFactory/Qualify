"""m-24921081 against Postgres: the owner's ask kept on the parent's brief (written in place
under the parent's lock, RLS-scoped), the worker's hook creating only the first part and
charging it once, the parts left created later, and the result screen reading the ask.

No vendor is called: the real router runs a fake copy adapter, the producer is a fake."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_creative.schemas import PartsRequest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative.fsm import GENERATED
from qualify_api.creative.part_progress import PartAction, PartState, read_part_progress
from qualify_api.creative.part_request import (
    PartsRequests,
    PostgresPartsRequestStore,
    parts_preview_use,
)
from qualify_api.creative.service import ContentService

from .test_creative_parts import FOUR_PARTS, parent_brief
from .test_creative_parts_db import _business, _scalar, _service, _use_previews

pytestmark = pytest.mark.db


def _parent(
    service: ContentService, tenant: UUID, brand: UUID, user: UUID, asked: PartsRequest
) -> UUID:
    brief = parent_brief(*FOUR_PARTS, parts_request=asked).model_copy(update={"brand_id": brand})
    parent = service.create_draft(tenant_id=tenant, brand_id=brand, brief=brief, user_id=user)
    service.run_generation(tenant_id=tenant, draft_id=parent)
    assert service.repository.get_draft(tenant_id=tenant, draft_id=parent).status == GENERATED
    return parent


def _stored(tenant: UUID, parent: UUID) -> object:
    return _scalar(
        tenant,
        """SELECT b.media->'parts_request' FROM content_drafts p
           JOIN content_briefs b ON b.id = p.brief_id WHERE p.id = :p""",
        p=parent,
    )


def _children(tenant: UUID, parent: UUID) -> list[int]:
    with tenant_session(tenant) as session:
        return list(
            session.execute(
                text(
                    "SELECT part_index FROM content_drafts WHERE parent_draft_id=:p "
                    "ORDER BY part_index"
                ),
                {"p": parent},
            ).scalars()
        )


def _previews_charged(tenant: UUID, brand: UUID) -> int:
    return int(
        _scalar(
            tenant,
            "SELECT COALESCE(sum(previews), 0) FROM creation_charges WHERE brand_id=:b",
            b=brand,
        )
        or 0
    )


def test_the_worker_makes_only_the_first_part_once_and_the_screen_reads_it_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, brand, user = _business(monkeypatch)
    service, parts, _ = _service()
    parent = _parent(service, tenant, brand, user, PartsRequest(scope="first"))
    asks = PartsRequests(service, parts=parts, analysis_of=lambda t, b: None)

    stored = asks.after_generation(tenant_id=tenant, parent_id=parent)
    assert stored is not None and stored.refused is None and stored.attempted_parts == (1,)
    assert _children(tenant, parent) == [1] and _previews_charged(tenant, brand) == 1
    assert _stored(tenant, parent)["scope"] == "first"  # type: ignore[index]
    jobs = _scalar(
        tenant,
        "SELECT count(*) FROM creative_jobs j JOIN content_drafts c ON c.id = j.draft_id "
        "WHERE c.parent_draft_id = :p",
        p=parent,
    )
    assert jobs == 1

    asks.after_generation(tenant_id=tenant, parent_id=parent)  # a retry: nothing more
    assert _children(tenant, parent) == [1] and _previews_charged(tenant, brand) == 1

    progress = read_part_progress(tenant_id=tenant, parent_id=parent)
    assert progress is not None and progress.request is not None
    assert progress.request.scope == "first" and progress.request.refused is None
    assert [row.state for row in progress.parts[1:]] == [PartState.UNMADE] * 3
    assert all(row.actions == (PartAction.CREATE,) for row in progress.parts[1:])

    # «Crear esta parte», then «Crear las que faltan»
    (third,) = asks.request_parts(
        tenant_id=tenant, parent_id=parent, user_id=user, part_indexes=(3,)
    )
    assert _children(tenant, parent) == [1, 3]
    every = asks.request_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    assert _children(tenant, parent) == [1, 2, 3, 4] and every[2] == third
    assert _previews_charged(tenant, brand) == 4


def test_a_refusal_is_kept_on_the_parent_for_the_result_screen_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, brand, user = _business(monkeypatch)
    service, parts, _ = _service()
    parent = _parent(service, tenant, brand, user, PartsRequest(scope="all"))
    _use_previews(tenant, brand, 17)  # 3 of the month's 20 left
    use = parts_preview_use(service, tenant_id=tenant, brand_id=brand, parts=4)
    assert use is not None and use.short and (use.uses, use.left, use.quota) == (4, 3, 20)
    assert use.renews_on is not None

    stored = PartsRequests(service, parts=parts, analysis_of=lambda t, b: None).after_generation(
        tenant_id=tenant, parent_id=parent
    )
    assert stored is not None and stored.refused == "not_enough_previews" and stored.missing == 1
    assert stored.attempted_parts == (1, 2, 3, 4)  # m-24993031: «all» spelled out
    assert _children(tenant, parent) == [] and _previews_charged(tenant, brand) == 17
    progress = read_part_progress(tenant_id=tenant, parent_id=parent)
    assert progress is not None and progress.request == stored


def test_another_business_cannot_read_nor_write_the_ask_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, brand, user = _business(monkeypatch)
    service, _, _ = _service()
    parent = _parent(service, tenant, brand, user, PartsRequest())
    other, _, _ = _business(monkeypatch)
    store = PostgresPartsRequestStore()
    assert store.requester(tenant_id=tenant, parent_id=parent) == user
    assert store.requester(tenant_id=other, parent_id=parent) is None
    assert store.begin(tenant_id=other, parent_id=parent) is None
    assert store.fail(tenant_id=other, parent_id=parent, attempt=0) is False
    refused = PartsRequest(refused="error", attempt=1)
    assert store.record(tenant_id=other, parent_id=parent, request=refused) is None
    assert _stored(tenant, parent)["refused"] is None  # type: ignore[index]
    assert store.begin(tenant_id=tenant, parent_id=parent) == 1
    kept = store.record(tenant_id=tenant, parent_id=parent, request=refused)
    assert kept is not None and kept.refused == "error" and kept.attempted_at is not None
    assert store.begin(tenant_id=tenant, parent_id=uuid4()) is None


def test_an_older_attempt_never_overwrites_a_newer_one_whatever_the_clocks_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review fix: one counter and the database's clock — equal or skewed process
    clocks can neither drop a later outcome nor keep a stale one."""
    from datetime import UTC, datetime

    tenant, brand, user = _business(monkeypatch)
    service, _, _ = _service()
    parent = _parent(service, tenant, brand, user, PartsRequest())
    store = PostgresPartsRequestStore()
    older = store.begin(tenant_id=tenant, parent_id=parent)
    newer = store.begin(tenant_id=tenant, parent_id=parent)
    assert (older, newer) == (1, 2)
    ahead = datetime(2099, 1, 1, tzinfo=UTC)  # whatever a process's clock says is ignored
    stale = PartsRequest(refused="plan_busy", attempt=1, attempted_at=ahead)
    fresh = PartsRequest(attempt=2, attempted_at=ahead)  # the same timestamp
    assert store.record(tenant_id=tenant, parent_id=parent, request=stale) is None
    kept = store.record(tenant_id=tenant, parent_id=parent, request=fresh)
    assert kept is not None and kept.refused is None and kept.attempt == 2
    assert kept.attempted_at is not None and kept.attempted_at.year < 2099  # the DB's clock
    assert store.record(tenant_id=tenant, parent_id=parent, request=stale) is None
    assert _stored(tenant, parent)["refused"] is None  # type: ignore[index]


def test_a_hook_that_breaks_keeps_an_error_on_the_parent_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, brand, user = _business(monkeypatch)
    service, parts, _ = _service()
    parent = _parent(service, tenant, brand, user, PartsRequest())
    plain = _parent(service, tenant, brand, user, PartsRequest())
    asks = PartsRequests(service, parts=parts, analysis_of=lambda t, b: None)
    assert asks.record_failure(tenant_id=tenant, parent_id=parent) is True
    stored = _stored(tenant, parent)
    assert stored["refused"] == "error" and stored["attempt"] == 1  # type: ignore[index]
    assert stored["attempted_at"] is not None  # type: ignore[index]
    # the hook then leaves it to the owner (first generation only), nothing created
    assert asks.after_generation(tenant_id=tenant, parent_id=parent) is None
    assert _children(tenant, parent) == []
    # a parent without an ask, or no parent: nothing written
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE content_briefs SET media = media - 'parts_request' "
                "WHERE id = (SELECT brief_id FROM content_drafts WHERE id = :p)"
            ),
            {"p": plain},
        )
    assert asks.record_failure(tenant_id=tenant, parent_id=plain) is False
    assert asks.record_failure(tenant_id=tenant, parent_id=uuid4()) is False


def test_a_hook_failure_never_overwrites_a_good_outcome_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, brand, user = _business(monkeypatch)
    service, parts, _ = _service()
    parent = _parent(service, tenant, brand, user, PartsRequest())
    store = PostgresPartsRequestStore()
    asks = PartsRequests(service, parts=parts, analysis_of=lambda t, b: None)
    good = asks.after_generation(tenant_id=tenant, parent_id=parent)
    assert good is not None and good.refused is None and _children(tenant, parent) == [1, 2, 3, 4]
    # a later hook that took no attempt cannot write «error» over it
    assert asks.record_failure(tenant_id=tenant, parent_id=parent) is False
    assert store.fail(tenant_id=tenant, parent_id=parent, attempt=0) is False
    assert _stored(tenant, parent)["refused"] is None  # type: ignore[index]
    # the hook's own attempt, still the last one: kept as «error»
    assert store.fail(tenant_id=tenant, parent_id=parent, attempt=good.attempt) is True
    assert _stored(tenant, parent)["refused"] == "error"  # type: ignore[index]

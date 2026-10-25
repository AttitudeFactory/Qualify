"""The dev-only Meta read simulator (m-24852203): exact opt-in, refused in production,
reads only, and enough of Meta's behaviour (window, pagination, missing node) for the
real `InboxService` to run end to end without a token."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from qualify_shared.social.ig_shapes import COMMENTS_EDGE_PERMISSIONS

from qualify_api.inbox import composition
from qualify_api.inbox import simulator as sim
from qualify_api.inbox.client import CommentsReadError
from qualify_api.inbox.media_client import MediaReadError
from qualify_api.inbox.repository import MemoryInboxRepository
from qualify_api.inbox.service import InboxService, _is_missing_media_error

TENANT = UUID("f0000000-0000-4000-8000-0000000000b1")
CONNECTION = UUID("f0000000-0000-4000-8000-0000000000b2")
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (sim.META_READS_ENV, sim.FIXTURE_PATH_ENV, sim.DEPLOY_ENV):
        monkeypatch.delenv(name, raising=False)


# --- the switch ------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["", "on", "1", "fixtures", "memory", " true "])
def test_anything_but_fixture_means_the_real_graph_api(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(sim.META_READS_ENV, value)
    assert sim.simulator_enabled() is False


def test_fixture_turns_it_on_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(sim.META_READS_ENV, " Fixture ")
    assert sim.simulator_enabled() is True


def test_production_refuses_it_outright(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(sim.META_READS_ENV, "fixture")
    monkeypatch.setenv(sim.DEPLOY_ENV, "production")
    with pytest.raises(sim.MetaReadsSimulatorRefused):
        sim.simulator_enabled()


async def test_production_composition_refuses_before_any_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(sim.META_READS_ENV, "fixture")
    monkeypatch.setenv(sim.DEPLOY_ENV, "production")
    with pytest.raises(sim.MetaReadsSimulatorRefused):
        await composition.production_inbox_service_for(tenant_id=TENANT, connection_id=CONNECTION)


def test_the_production_compose_sets_the_marker_and_forces_the_simulator_off() -> None:
    text = (REPO_ROOT / "deploy/docker-compose.prod.yml").read_text(encoding="utf-8")
    anchor = text.index("x-app-env: &app-env")
    block = text[anchor : text.index("\nx-", anchor + 1)]
    assert f"  {sim.DEPLOY_ENV}: {sim.DEPLOY_ENV_PRODUCTION}\n" in block
    assert f'  {sim.META_READS_ENV}: ""\n' in block
    assert f'  {sim.FIXTURE_PATH_ENV}: ""\n' in block


async def test_in_fixture_mode_no_credential_is_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(sim.META_READS_ENV, "fixture")

    class Boom:
        def __init__(self, *_a: object, **_k: object) -> None:
            raise AssertionError("a credential must not be resolved in fixture mode")

    monkeypatch.setattr(composition, "InjectingCredentialResolver", Boom)
    service = await composition.production_inbox_service_for(
        tenant_id=TENANT, connection_id=CONNECTION
    )
    assert isinstance(service, InboxService)


def test_it_only_implements_reads() -> None:
    for cls in (sim.FixtureMediaClient, sim.FixtureCommentsClient):
        public = {
            n for n, _ in inspect.getmembers(cls, inspect.isfunction) if not n.startswith("_")
        }
        assert public <= {"list_recent_media", "list_recent_stories", "get_media", "list_comments"}


# --- the committed fixture -------------------------------------------------------------


def test_the_committed_fixture_is_synthetic_and_loads() -> None:
    raw = json.loads(sim.DEFAULT_FIXTURE.read_text(encoding="utf-8"))
    fixture = sim.MetaReadsFixture(raw, now=NOW)
    assert len(fixture.media) >= 3
    usernames = {c.username for entries in fixture.comments.values() for c in entries}
    assert usernames and all(u and u.startswith("cliente.demo") for u in usernames)
    for media in fixture.media.values():  # no third-party media: inline pictures only
        picture = media.thumbnail_url or media.media_url or ""
        assert picture.startswith("data:image/svg+xml,")


def _fixture() -> sim.MetaReadsFixture:
    return sim.MetaReadsFixture.load(sim.DEFAULT_FIXTURE, now=NOW)


async def test_the_media_list_honours_the_window() -> None:
    client = sim.FixtureMediaClient(_fixture())
    everything = await client.list_recent_media(ig_user_id="x", since=NOW - timedelta(days=14))
    last_day = await client.list_recent_media(ig_user_id="x", since=NOW - timedelta(days=1))
    assert len(last_day) < len(everything)
    assert all(m.timestamp >= NOW - timedelta(days=1) for m in last_day)


async def test_an_unknown_media_answers_like_a_deleted_node() -> None:
    fixture = _fixture()
    with pytest.raises(MediaReadError) as media_error:
        await sim.FixtureMediaClient(fixture).get_media(media_id="nope")
    with pytest.raises(CommentsReadError) as comments_error:
        await sim.FixtureCommentsClient(fixture).list_comments(ig_media_id="nope")
    assert _is_missing_media_error(media_error.value)
    assert _is_missing_media_error(comments_error.value)


async def test_comments_paginate() -> None:
    client = sim.FixtureCommentsClient(_fixture())
    first = await client.list_comments(ig_media_id="17900000000000005")
    cursor = first.paging["cursors"]["after"]  # type: ignore[index]
    second = await client.list_comments(ig_media_id="17900000000000005", after=cursor)
    assert len(first.data) == sim.PAGE_SIZE and second.paging is None
    assert {c.id for c in first.data}.isdisjoint({c.id for c in second.data})


# --- end to end through the real service -----------------------------------------------


async def test_the_real_service_lists_monitors_and_syncs_from_the_fixture() -> None:
    fixture = _fixture()
    repo = MemoryInboxRepository()
    service = InboxService(
        repository=repo,
        comments_client=sim.FixtureCommentsClient(fixture),
        media_client=sim.FixtureMediaClient(fixture),
        granted_scopes=frozenset(COMMENTS_EDGE_PERMISSIONS),
    )
    candidates = await service.list_candidate_media(
        tenant_id=TENANT, connection_id=CONNECTION, ig_user_id="any", now=NOW
    )
    assert candidates and all(c.thumbnail_url or c.media_url for c in candidates)
    for media_id in ("17900000000000001", "17900000000000005"):
        await service.set_media_monitored(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            external_media_id=media_id,
            monitored=True,
            now=NOW,
        )
    summary = await service.sync_comments(tenant_id=TENANT, connection_id=CONNECTION, now=NOW)
    assert summary.media_checked == 2
    assert summary.new_comments == 4 + 30
    again = await service.sync_comments(tenant_id=TENANT, connection_id=CONNECTION, now=NOW)
    assert again.new_comments == 0  # idempotent, like the real edge

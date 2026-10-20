"""TaskDispatcher + reaper tests (design §7.4).

Pure block: `InlineDispatcher` really runs the callable out of the caller's thread, as a
daemon, with the two-UUID keyword signature that IS the future Celery task signature —
plus the platform key resolver's resolve-time (not import-time) failure mode.

`db` block: the reaper against Postgres — a stale DRAFTING row flips to FAILED/timeout
through the FSM's `reap` edge, a fresh one is left alone.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.creative.composition import (
    PLATFORM_KEY_ENV,
    MissingPlatformKey,
    PlatformKeyResolver,
)
from qualify_api.creative.dispatch import InlineDispatcher, reap_stale_drafts
from qualify_api.creative.fsm import DRAFTING, FAILED

# Distinct from every other suite's tenants so the reaper only sweeps this test's rows.
DB_TENANT = UUID("a0000000-0000-4000-8000-0000000000f1")


def test_inline_dispatcher_runs_callable_in_daemon_thread() -> None:
    done = threading.Event()
    seen: dict[str, object] = {}

    def run(*, tenant_id: UUID, draft_id: UUID) -> None:
        seen["tenant_id"] = tenant_id
        seen["draft_id"] = draft_id
        seen["thread"] = threading.current_thread()
        done.set()

    tenant_id, draft_id = uuid4(), uuid4()
    InlineDispatcher(run).dispatch_generation(tenant_id=tenant_id, draft_id=draft_id)

    assert done.wait(timeout=5), "dispatched callable never ran"
    assert seen["tenant_id"] == tenant_id
    assert seen["draft_id"] == draft_id
    worker = seen["thread"]
    assert isinstance(worker, threading.Thread)
    assert worker is not threading.current_thread()
    assert worker.daemon is True  # dies with the process — hence the reaper


def test_platform_key_resolver_fails_at_resolve_time_not_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = PlatformKeyResolver()  # constructing without the env var is fine
    monkeypatch.delenv(PLATFORM_KEY_ENV, raising=False)
    with pytest.raises(MissingPlatformKey):
        resolver.resolve(tenant_id=uuid4(), brand_id=uuid4(), provider="anthropic")

    monkeypatch.setenv(PLATFORM_KEY_ENV, "sk-test-123")
    key = resolver.resolve(tenant_id=uuid4(), brand_id=uuid4(), provider="anthropic")
    assert key.api_key == "sk-test-123"
    assert key.paid_by.value == "platform"
    assert "sk-test-123" not in repr(key)  # the key never reaches a log


# ---------------------------------------------------------------------------
# db: the reaper over real rows


@pytest.fixture
def stale_and_fresh_drafts() -> tuple[UUID, UUID, UUID]:
    """One draft stuck in DRAFTING for 30 minutes, one fresh. Fresh rows every run
    (uuid ids); the tenant/brand/user substrate is insert-if-absent."""
    from qualify_shared.db.admin import admin_session
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    from qualify_api.creative import models as orm
    from qualify_api.tenancy.models import Brand, Tenant, User

    with admin_session() as session:
        if session.get(Tenant, DB_TENANT) is None:
            session.add(
                Tenant(
                    id=DB_TENANT,
                    name="creative-dispatch-t",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        brand = session.scalar(select(Brand).where(Brand.tenant_id == DB_TENANT))
        if brand is None:
            brand = Brand(tenant_id=DB_TENANT, name="creative-dispatch-brand")
            session.add(brand)
            session.flush()
        brand_id = brand.id
        user = User(tenant_id=DB_TENANT, email=f"dispatch-{uuid4()}@t.co", display_name="U")
        session.add(user)
        session.flush()
        user_id = user.id

    with tenant_session(DB_TENANT) as session:
        brief = orm.ContentBrief(
            tenant_id=DB_TENANT,
            brand_id=brand_id,
            objective="sale",
            topic="reaper test",
            platform="instagram",
            format="feed_4_5",
            intent="organic",
            content_type="menu",
            image_route="template_only",
            variants_requested=1,
            created_by=user_id,
        )
        session.add(brief)
        session.flush()
        stale = orm.ContentDraft(
            tenant_id=DB_TENANT,
            brand_id=brand_id,
            brief_id=brief.id,
            status=DRAFTING,
            pipeline_version="creative-v1",
            created_at=datetime.now(UTC) - timedelta(minutes=30),
        )
        fresh = orm.ContentDraft(
            tenant_id=DB_TENANT,
            brand_id=brand_id,
            brief_id=brief.id,
            status=DRAFTING,
            pipeline_version="creative-v1",
        )
        session.add_all([stale, fresh])
        session.flush()
        return DB_TENANT, stale.id, fresh.id


@pytest.mark.db
def test_reaper_flips_stale_drafting_to_failed_timeout(
    stale_and_fresh_drafts: tuple[UUID, UUID, UUID],
) -> None:
    from qualify_shared.db.session import tenant_session

    from qualify_api.creative import models as orm

    tenant_id, stale_id, fresh_id = stale_and_fresh_drafts

    reaped = reap_stale_drafts(tenant_id=tenant_id)
    assert reaped >= 1  # at least our stale row; prior local runs may add none (settled)

    with tenant_session(tenant_id) as session:
        stale = session.get(orm.ContentDraft, stale_id)
        fresh = session.get(orm.ContentDraft, fresh_id)
        assert stale is not None and fresh is not None
        assert stale.status == FAILED
        assert stale.failure_reason == "timeout"  # forced, never caller-supplied
        assert fresh.status == DRAFTING and fresh.failure_reason is None

    # Idempotent: a second sweep leaves both rows exactly where they are.
    reap_stale_drafts(tenant_id=tenant_id)
    with tenant_session(tenant_id) as session:
        stale = session.get(orm.ContentDraft, stale_id)
        fresh = session.get(orm.ContentDraft, fresh_id)
        assert stale is not None and stale.status == FAILED
        assert fresh is not None and fresh.status == DRAFTING


def test_each_provider_resolves_its_own_platform_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Before the video lane every provider got the Anthropic key — a video vendor
    would have been handed it. Each provider now reads its own variable; an unknown one
    (HeyGen since 2026-10-16 included) has none."""
    monkeypatch.setenv(PLATFORM_KEY_ENV, "sk-ant")
    monkeypatch.setenv("QUALIFY_BYTEPLUS_SPEECH_API_KEY", "speech-key")
    monkeypatch.setenv("QUALIFY_BYTEPLUS_CV_API_KEY", "cv-key")
    monkeypatch.setenv("QUALIFY_HEYGEN_API_KEY", "hg-key")
    resolver = PlatformKeyResolver()
    ids = {"tenant_id": uuid4(), "brand_id": uuid4()}
    assert resolver.resolve(**ids, provider="anthropic").api_key == "sk-ant"
    assert resolver.resolve(**ids, provider="seed_speech").api_key == "speech-key"
    assert resolver.resolve(**ids, provider="omnihuman").api_key == "cv-key"
    for retired_or_unknown in ("heygen", "fal"):
        with pytest.raises(MissingPlatformKey):
            resolver.resolve(**ids, provider=retired_or_unknown)
    monkeypatch.delenv("QUALIFY_BYTEPLUS_CV_API_KEY")
    with pytest.raises(MissingPlatformKey, match="QUALIFY_BYTEPLUS_CV_API_KEY"):
        resolver.resolve(**ids, provider="omnihuman")


@pytest.mark.db
def test_reaper_gives_a_talking_presenter_its_render_window(
    stale_and_fresh_drafts: tuple[UUID, UUID, UUID],
) -> None:
    """Review 2026-10-17: OmniHuman renders at ~25x real time, so its draft is not failed
    at the generic 20 min while the render is still running (and being paid for)."""
    from qualify_shared.db.session import tenant_session

    from qualify_api.creative import models as orm
    from qualify_api.creative.dispatch import OMNIHUMAN_REAP_AFTER_MINUTES

    tenant_id, stale_id, _ = stale_and_fresh_drafts
    with tenant_session(tenant_id) as session:
        draft = session.get(orm.ContentDraft, stale_id)
        assert draft is not None
        first = session.get(orm.ContentBrief, draft.brief_id)
        assert first is not None
        brief = orm.ContentBrief(
            tenant_id=tenant_id,
            brand_id=draft.brand_id,
            objective="sale",
            topic="presenter",
            platform="instagram",
            format="reels_9_16",
            intent="organic",
            content_type="menu",
            image_route="template_only",
            variants_requested=1,
            kind="avatar_video",
            media={"video_engine": "omnihuman"},
            created_by=first.created_by,
        )
        session.add(brief)
        session.flush()
        rendering = orm.ContentDraft(
            tenant_id=tenant_id,
            brand_id=draft.brand_id,
            brief_id=brief.id,
            status=DRAFTING,
            pipeline_version="creative-v1",
            created_at=datetime.now(UTC) - timedelta(minutes=30),
        )
        dead = orm.ContentDraft(
            tenant_id=tenant_id,
            brand_id=draft.brand_id,
            brief_id=brief.id,
            status=DRAFTING,
            pipeline_version="creative-v1",
            created_at=datetime.now(UTC) - timedelta(minutes=OMNIHUMAN_REAP_AFTER_MINUTES + 5),
        )
        session.add_all([rendering, dead])
        session.flush()
        rendering_id, dead_id = rendering.id, dead.id

    reap_stale_drafts(tenant_id=tenant_id)
    with tenant_session(tenant_id) as session:
        assert session.get(orm.ContentDraft, stale_id).status == FAILED  # generic: 20 min
        assert session.get(orm.ContentDraft, rendering_id).status == DRAFTING
        assert session.get(orm.ContentDraft, dead_id).status == FAILED
    assert OMNIHUMAN_REAP_AFTER_MINUTES >= 50  # the 40-min poll window plus a margin


@pytest.mark.parametrize(
    ("base", "ready"),
    [
        ("https://qualify.attitudefactory.co", True),
        ("https://abc.trycloudflare.com", True),
        ("http://qualify.attitudefactory.co", False),  # a vendor fetches https only
        ("https://localhost:8000", False),
        ("https://127.0.0.1", False),
        ("https://app.localhost", False),
        ("", False),
    ],
)
def test_public_media_is_ready_only_on_a_public_https_url_with_r2(
    monkeypatch: pytest.MonkeyPatch, base: str, ready: bool
) -> None:
    from qualify_api.creative.composition import PublicReferenceLinks, public_media_ready

    monkeypatch.setenv("QUALIFY_PUBLIC_MEDIA_BASE_URL", base)
    for var in (
        "QUALIFY_R2_ENDPOINT_URL",
        "QUALIFY_R2_ACCESS_KEY_ID",
        "QUALIFY_R2_SECRET_ACCESS_KEY",
        "QUALIFY_R2_BUCKET",
    ):
        monkeypatch.setenv(var, "https://r2.example" if var.endswith("URL") else "x")
    assert public_media_ready() is ready
    assert PublicReferenceLinks().ready() is ready
    monkeypatch.delenv("QUALIFY_R2_BUCKET")
    assert public_media_ready() is False  # no R2, nowhere to put the bytes


def test_a_reference_link_outlives_omnihumans_queue() -> None:
    from qualify_creative.adapters.byteplus_omnihuman import DEFAULT_POLL_TIMEOUT_SECONDS

    from qualify_api.creative.composition import REFERENCE_LINK_TTL_SECONDS
    from qualify_api.publishing.media_token import TOKEN_TTL_SECONDS

    assert REFERENCE_LINK_TTL_SECONDS > DEFAULT_POLL_TIMEOUT_SECONDS > TOKEN_TTL_SECONDS

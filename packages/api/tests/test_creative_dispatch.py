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
            updated_at=datetime.now(UTC) - timedelta(minutes=30),
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


def _set_last_progress(tenant_id: UUID, draft_id: UUID, minutes_ago: float) -> None:
    from qualify_shared.db.session import tenant_session

    from qualify_api.creative import models as orm

    with tenant_session(tenant_id) as session:
        draft = session.get(orm.ContentDraft, draft_id)
        assert draft is not None
        draft.updated_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)


@pytest.mark.db
def test_reaper_spares_a_long_run_that_keeps_making_progress(
    stale_and_fresh_drafts: tuple[UUID, UUID, UUID],
) -> None:
    """m-24852156: a ten-slide animated carousel started 30 min ago and still keeping
    a slide every ~2 min is alive. Its heartbeat (`record_progress`) is what the reaper
    reads; the same draft silent for 21 min is a dead thread and is reaped."""
    from qualify_shared.db.session import tenant_session

    from qualify_api.creative import models as orm
    from qualify_api.creative.dispatch import record_progress

    tenant_id, alive_id, _ = stale_and_fresh_drafts  # born 30 min ago, no progress yet
    record_progress(tenant_id=tenant_id, draft_id=alive_id)  # its latest slide was kept

    # the reaper runs every minute through the rest of the carousel: never flips it
    for _ in range(3):
        reap_stale_drafts(tenant_id=tenant_id)
    with tenant_session(tenant_id) as session:
        assert session.get(orm.ContentDraft, alive_id).status == DRAFTING

    # then the process dies: no stamp for 21 min → reaped, as before
    _set_last_progress(tenant_id, alive_id, minutes_ago=21)
    reap_stale_drafts(tenant_id=tenant_id)
    with tenant_session(tenant_id) as session:
        dead = session.get(orm.ContentDraft, alive_id)
        assert dead.status == FAILED and dead.failure_reason == "timeout"

    # a stamp on a draft already reaped changes nothing
    before = None
    with tenant_session(tenant_id) as session:
        before = session.get(orm.ContentDraft, alive_id).updated_at
    record_progress(tenant_id=tenant_id, draft_id=alive_id)
    with tenant_session(tenant_id) as session:
        assert session.get(orm.ContentDraft, alive_id).updated_at == before


@pytest.mark.db
def test_progress_is_stamped_only_inside_the_owning_tenant(
    stale_and_fresh_drafts: tuple[UUID, UUID, UUID],
) -> None:
    """The heartbeat runs in the draft's tenant session: another business's id stamps
    nothing (RLS), so it cannot keep a foreign draft alive."""
    from qualify_shared.db.session import tenant_session

    from qualify_api.creative import models as orm
    from qualify_api.creative.dispatch import record_progress

    tenant_id, stale_id, _ = stale_and_fresh_drafts
    record_progress(tenant_id=uuid4(), draft_id=stale_id)  # some other tenant
    reap_stale_drafts(tenant_id=tenant_id)
    with tenant_session(tenant_id) as session:
        assert session.get(orm.ContentDraft, stale_id).status == FAILED


@pytest.mark.db
def test_asking_for_another_version_of_an_old_piece_restarts_the_clock(
    stale_and_fresh_drafts: tuple[UUID, UUID, UUID],
) -> None:
    """«Pedir otra versión» puts a draft born long ago back in DRAFTING: the run starts
    then, so the reaper must not fail it on the next listing."""
    from qualify_shared.db.session import tenant_session

    from qualify_api.creative import models as orm
    from qualify_api.creative.service import PostgresContentRepository

    tenant_id, old_id, _ = stale_and_fresh_drafts
    _set_last_progress(tenant_id, old_id, minutes_ago=60 * 24)
    with tenant_session(tenant_id) as session:
        session.get(orm.ContentDraft, old_id).status = "rejected"
    PostgresContentRepository().update_status(
        tenant_id=tenant_id, draft_id=old_id, new_status=DRAFTING, failure_reason=None
    )
    reap_stale_drafts(tenant_id=tenant_id)
    with tenant_session(tenant_id) as session:
        assert session.get(orm.ContentDraft, old_id).status == DRAFTING


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
            updated_at=datetime.now(UTC) - timedelta(minutes=30),
        )
        dead = orm.ContentDraft(
            tenant_id=tenant_id,
            brand_id=draft.brand_id,
            brief_id=brief.id,
            status=DRAFTING,
            pipeline_version="creative-v1",
            created_at=datetime.now(UTC) - timedelta(minutes=OMNIHUMAN_REAP_AFTER_MINUTES + 5),
            updated_at=datetime.now(UTC) - timedelta(minutes=OMNIHUMAN_REAP_AFTER_MINUTES + 5),
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


class _FakeGate:
    """Records writes; `stored` maps key -> size, a missing key raises like R2's HEAD."""

    def __init__(self, stored: dict[str, int]) -> None:
        self.stored = stored
        self.puts: list[str] = []

    def object_size(self, tenant_id: UUID, object_key: str) -> int:
        from qualify_shared.objects.gate import ObjectNotFound

        if object_key not in self.stored:
            raise ObjectNotFound(object_key)
        return self.stored[object_key]

    def put_media(self, tenant_id: UUID, object_key: str, body: object, ct: str) -> None:
        self.puts.append(object_key)


def _wire_reference_links(monkeypatch: pytest.MonkeyPatch, gate: _FakeGate) -> list[str]:
    """Swap R2, Redis and the token store for fakes; returns the keys tokens were issued for."""
    import redis
    from qualify_shared.objects import config, s3
    from qualify_shared.objects import gate as gate_module

    from qualify_api import config as api_config
    from qualify_api.publishing import media_token

    issued: list[str] = []

    class _Tokens:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def issue(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str:
            issued.append(object_key)
            return "tok"

    class _Settings:
        def public_media_url(self, token: str) -> str:
            return f"https://media.example/m/{token}"

    monkeypatch.setattr(api_config.PublicMediaSettings, "from_env", lambda: _Settings())
    monkeypatch.setattr(config.R2Settings, "from_env", lambda: None)
    monkeypatch.setattr(s3, "R2ObjectStore", lambda settings: None)
    monkeypatch.setattr(gate_module, "ObjectGate", lambda store: gate)
    monkeypatch.setattr(redis.Redis, "from_url", lambda *a, **k: None)
    monkeypatch.setattr(media_token, "MediaTokenStore", _Tokens)
    return issued


def test_a_reused_reference_is_not_rewritten_under_the_object_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second use of the same bytes finds the content-addressed key and skips the put
    the bucket's retention lock would refuse (`ObjectLockedByBucketPolicy`)."""
    import hashlib

    from qualify_shared.objects.keys import tenant_prefix

    from qualify_api.creative.composition import PublicReferenceLinks

    tenant, data = uuid4(), b"same clip bytes"
    key = f"{tenant_prefix(tenant)}creative-refs/{hashlib.sha256(data).hexdigest()[:32]}.mp4"
    gate = _FakeGate({key: len(data)})
    issued = _wire_reference_links(monkeypatch, gate)

    url = PublicReferenceLinks()(tenant_id=tenant, key="clip.MP4", data=data, content_type="v")

    assert gate.puts == []
    assert issued == [key]
    assert url == "https://media.example/m/tok"


def test_a_new_reference_is_uploaded_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.creative.composition import PublicReferenceLinks

    gate = _FakeGate({})
    issued = _wire_reference_links(monkeypatch, gate)

    PublicReferenceLinks()(tenant_id=uuid4(), key="voz.mp3", data=b"new", content_type="a")

    assert len(gate.puts) == 1
    assert gate.puts[0].endswith(".mp3")
    assert issued == gate.puts


def test_a_reference_whose_size_r2_cannot_tell_is_still_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 4: the size probe answered 403/503/a timeout and the link was lost;
    an unknown answer falls through to the put, as before the probe existed."""
    from qualify_api.creative.composition import PublicReferenceLinks

    class _Flaky(_FakeGate):
        def object_size(self, tenant_id: UUID, object_key: str) -> int:
            raise TimeoutError("R2 HEAD timed out")

    gate = _Flaky({})
    issued = _wire_reference_links(monkeypatch, gate)

    url = PublicReferenceLinks()(tenant_id=uuid4(), key="voz.mp3", data=b"new", content_type="a")

    assert len(gate.puts) == 1 and issued == gate.puts
    assert url == "https://media.example/m/tok"

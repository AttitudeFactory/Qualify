"""TikTok draft (inbox) upload (m-24921091), offline: httpx mocked, fakes for storage/DB."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.connections.credential_reader import CredentialNotFound
from qualify_api.connections.read import ConnectionSummary
from qualify_api.connections.resolver import build_authenticated_client
from qualify_api.planner.post_reader import (
    NotPublishable,
    PublishableMedia,
    PublishablePost,
    UnpublishableReason,
)
from qualify_api.planner.publishable import SCHEDULABLE_PLATFORMS
from qualify_api.publishing.tiktok_client import (
    HttpTikTokPostClient,
    RemoteState,
    RemoteStatus,
    TikTokPublishError,
    plan_chunks,
)
from qualify_api.publishing.tiktok_drafts import (
    STALE_PENDING_AFTER,
    DraftRecord,
    DraftRefused,
    TikTokDraftService,
    draft_idempotency_key,
    failure_text,
)

TENANT = uuid4()
USER = uuid4()
CONN = uuid4()
POST = uuid4()
MB = 1024 * 1024
UPLOAD_URL = "https://open-upload.tiktokapis.com/video/?upload_id=1&upload_token=t"


def test_tiktok_is_never_schedulable() -> None:
    """Hard rule (ADR 21(d)/23(c)): no scheduled publishing for TikTok."""
    assert "tiktok" not in SCHEDULABLE_PLATFORMS


def test_chunk_plan_rules() -> None:
    assert plan_chunks(3 * MB).total_chunk_count == 1
    assert plan_chunks(64 * MB).total_chunk_count == 1
    big = plan_chunks(300 * MB)
    assert (big.chunk_size, big.total_chunk_count) == (64 * MB, 4)
    with pytest.raises(TikTokPublishError):
        plan_chunks(0)


def _api(handler):
    client = build_authenticated_client(
        "TOK", scheme="Bearer", transport=httpx.MockTransport(handler)
    )
    return client


async def test_init_file_upload_body_and_headers_and_chunked_put() -> None:
    seen: list[httpx.Request] = []

    def api(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "data": {"publish_id": "v_inbox_file~v2.1", "upload_url": UPLOAD_URL},
                "error": {"code": "ok", "message": "", "log_id": "l"},
            },
        )

    puts: list[httpx.Request] = []

    def upload(request: httpx.Request) -> httpx.Response:
        puts.append(request)
        return httpx.Response(201)

    video = b"v" * (70 * MB)
    client = HttpTikTokPostClient(client=_api(api), upload_transport=httpx.MockTransport(upload))
    init = await client.init_file_upload(video_size=len(video))
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/v2/post/publish/inbox/video/init/"
    assert seen[0].headers["authorization"] == "Bearer TOK"
    assert body == {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": 70 * MB,
            "chunk_size": 64 * MB,
            "total_chunk_count": 1,
        }
    }
    assert "post_info" not in body  # inbox draft, never a direct post
    await client.upload_file(
        upload_url=init.upload_url, fileobj=io.BytesIO(video), video_size=len(video)
    )
    assert len(puts) == 1  # 70 MB < 128 MB: the remainder folds into the single last chunk
    assert puts[0].headers["content-range"] == f"bytes 0-{70 * MB - 1}/{70 * MB}"
    assert "authorization" not in puts[0].headers  # pre-signed URL: no bearer


async def test_error_code_surfaces_without_body() -> None:
    def api(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"error": {"code": "spam_risk_too_many_pending_share", "message": "TOKEN"}}
        )

    client = HttpTikTokPostClient(client=_api(api))
    with pytest.raises(TikTokPublishError) as err:
        await client.init_file_upload(video_size=MB)
    assert err.value.code == "spam_risk_too_many_pending_share" and "TOKEN" not in str(err.value)
    assert "sin terminar" in failure_text(err.value.code)


async def test_status_fetch_parses_states() -> None:
    def api(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"publish_id": "p1"}
        return httpx.Response(
            200, json={"data": {"status": "SEND_TO_USER_INBOX"}, "error": {"code": "ok"}}
        )

    state = await HttpTikTokPostClient(client=_api(api)).fetch_status(publish_id="p1")
    assert state.status.value == "SEND_TO_USER_INBOX"


# --- service ------------------------------------------------------------------------------


@dataclass
class FakeRepo:
    rows: dict[str, dict] = field(default_factory=dict)
    by_id: dict[UUID, str] = field(default_factory=dict)

    def create_or_get(self, *, idempotency_key: str, **kw):
        if idempotency_key in self.rows:
            return self._rec(idempotency_key), False
        rid = uuid4()
        self.rows[idempotency_key] = {
            "id": rid,
            "status": "pending",
            "publish_id": None,
            "code": None,
            "caption": kw["caption"],
            "started_at": datetime.now(UTC),
            **kw,
        }
        self.by_id[rid] = idempotency_key
        return self._rec(idempotency_key), True

    def _rec(self, key: str) -> DraftRecord:
        r = self.rows[key]
        return DraftRecord(
            r["id"],
            r["status"],
            r["publish_id"],
            r["code"],
            r["caption"],
            r["status"] in ("in_inbox", "failed"),
            r["started_at"],
        )

    def get(self, *, tenant_id, draft_id):
        return self._rec(self.by_id[draft_id]) if draft_id in self.by_id else None

    def update(
        self,
        *,
        draft_id,
        status,
        publish_id=None,
        video_bytes=None,
        platform_error_code=None,
        tenant_id=None,
    ):
        r = self.rows[self.by_id[draft_id]]
        if r["status"] in ("in_inbox", "failed"):
            return
        r["status"] = status
        r["publish_id"] = publish_id or r["publish_id"]
        r["code"] = platform_error_code or r["code"]


class FakePosts:
    def __init__(self, verdict) -> None:
        self.verdict = verdict
        self.destinations: list[str | None] = []

    def get_publishable(self, *, destination=None, **_):
        self.destinations.append(destination)
        return self.verdict


def approved(**kw) -> PublishablePost:
    media = kw.pop("media", (PublishableMedia(f"t/{TENANT}/v.mp4", "video/mp4", "VIDEO", 0),))
    return PublishablePost(
        tenant_id=TENANT,
        post_id=POST,
        brand_id=uuid4(),
        approved_revision=kw.pop("rev", 3),
        caption="Hola #qualify",
        media_product_type=kw.pop("mpt", "REELS"),
        media=media,
    )


class FakeGate:
    def open_object(self, tenant_id, key):
        return io.BytesIO(b"x" * (2 * MB))


class FakeTikTok:
    def __init__(
        self,
        status="SEND_TO_USER_INBOX",
        init_error: Exception | None = None,
        upload_error: Exception | None = None,
    ):
        self.upload_error = upload_error
        self.status = status
        self.init_error = init_error
        self.inits = 0
        self.uploads = 0

    async def init_file_upload(self, *, video_size: int):
        self.inits += 1
        if self.init_error:
            raise self.init_error
        return SimpleNamespace(publish_id="v_inbox_file~v2.9", upload_url=UPLOAD_URL)

    async def upload_file(self, **_):
        self.uploads += 1
        if self.upload_error:
            raise self.upload_error

    async def fetch_status(self, *, publish_id: str):
        return RemoteState(status=RemoteStatus(self.status), fail_reason="file_format_check_failed")


def summary(**kw) -> ConnectionSummary:
    base = dict(
        connection_id=CONN,
        brand_id=None,
        platform="tiktok",
        external_account_id="o",
        external_username="ana",
        status="active",
        granted_scopes=("video.upload",),
        access_posture="development",
        last_verified_at=None,
        connected_at=None,
        data_access_expires_at=None,
        last_health_checked_at=None,
    )
    base.update(kw)
    return ConnectionSummary(**base)


def service(
    verdict, tiktok=None, conns=None, repo=None, degraded=None, factory_error=None, clock=None
) -> tuple[TikTokDraftService, FakeRepo, FakeTikTok, FakePosts]:
    repo = repo or FakeRepo()
    tiktok = tiktok or FakeTikTok()
    posts = FakePosts(verdict)

    class Factory:
        async def client_for(self, *, tenant_id, connection_id):
            if factory_error is not None:
                raise factory_error
            return tiktok

    svc = TikTokDraftService(
        posts=posts,  # type: ignore[arg-type]
        connections=lambda t: conns if conns is not None else (summary(),),
        repository=repo,  # type: ignore[arg-type]
        gate=FakeGate(),  # type: ignore[arg-type]
        client_factory=Factory(),  # type: ignore[arg-type]
        connection_degrader=(lambda **kw: degraded.append(kw)) if degraded is not None else None,
        **({"clock": clock} if clock is not None else {}),
    )
    return svc, repo, tiktok, posts


async def send(svc, **kw):
    return await svc.send_to_inbox(
        tenant_id=TENANT, user_id=USER, connection_id=CONN, post_id=POST, **kw
    )


async def test_approved_piece_lands_in_the_inbox_once() -> None:
    svc, repo, tiktok, posts = service(approved())
    state = await send(svc)
    assert (state.status, state.settled, state.created) == ("in_inbox", True, True)
    assert "notificación" in state.message
    assert posts.destinations == ["tiktok"]
    assert (tiktok.inits, tiktok.uploads) == (1, 1)
    row = next(iter(repo.rows.values()))
    assert row["approved_revision"] == 3 and row["upload_mode"] == "FILE_UPLOAD"
    assert row["publish_id"] == "v_inbox_file~v2.9"


async def test_double_click_never_creates_a_second_draft() -> None:
    svc, repo, tiktok, _ = service(approved())
    await send(svc)
    again = await send(svc)
    assert again.created is False and tiktok.inits == 1 and len(repo.rows) == 1


async def test_new_approved_revision_is_a_new_draft() -> None:
    assert draft_idempotency_key(post_id=POST, output_port=None, approved_revision=3) != (
        draft_idempotency_key(post_id=POST, output_port=None, approved_revision=4)
    )


async def test_unapproved_piece_is_refused_and_nothing_is_sent() -> None:
    verdict = NotPublishable(post_id=POST, reason=UnpublishableReason.NOT_APPROVED)
    svc, repo, tiktok, _ = service(verdict)
    with pytest.raises(DraftRefused) as err:
        await send(svc)
    assert err.value.code == "not_approved" and "aprobada" in err.value.message
    assert tiktok.inits == 0 and repo.rows == {}


async def test_non_video_or_carousel_is_refused() -> None:
    svc, repo, tiktok, _ = service(approved(mpt="IMAGE"))
    with pytest.raises(DraftRefused) as err:
        await send(svc)
    assert err.value.code == "not_a_video" and tiktok.inits == 0


@pytest.mark.parametrize(
    "conns",
    [
        (),
        (summary(platform="instagram"),),
        (summary(status="degraded"),),
        (summary(granted_scopes=("user.info.basic",)),),
    ],
)
async def test_connection_must_be_an_active_tiktok_with_upload_scope(conns) -> None:
    svc, _, tiktok, _ = service(approved(), conns=conns)
    with pytest.raises(DraftRefused):
        await send(svc)
    assert tiktok.inits == 0


async def test_platform_error_fails_the_draft_with_a_spanish_message() -> None:
    err = TikTokPublishError("x", code="spam_risk_too_many_pending_share", http_status=403)
    svc, repo, _, _ = service(approved(), tiktok=FakeTikTok(init_error=err))
    state = await send(svc)
    assert state.status == "failed" and state.settled
    assert "sin terminar" in state.message
    assert next(iter(repo.rows.values()))["code"] == "spam_risk_too_many_pending_share"


async def test_auth_failure_degrades_the_connection() -> None:
    err = TikTokPublishError("x", code="access_token_invalid", http_status=401)
    degraded: list[dict] = []
    svc, _, _, _ = service(approved(), tiktok=FakeTikTok(init_error=err), degraded=degraded)
    state = await send(svc)
    assert state.status == "failed" and degraded == [{"tenant_id": TENANT, "connection_id": CONN}]


async def test_still_processing_stays_open_until_refreshed() -> None:
    tiktok = FakeTikTok(status="PROCESSING_UPLOAD")
    svc, _, _, _ = service(approved(), tiktok=tiktok)
    state = await send(svc)
    assert (state.status, state.settled) == ("processing", False)
    tiktok.status = "SEND_TO_USER_INBOX"
    done = await svc.refresh(tenant_id=TENANT, connection_id=CONN, draft_id=state.draft_id)
    assert done.status == "in_inbox" and done.settled


async def test_tiktok_side_failure_is_terminal() -> None:
    svc, _, _, _ = service(approved(), tiktok=FakeTikTok(status="FAILED"))
    state = await send(svc)
    assert state.status == "failed" and "formato" in state.message


@pytest.mark.parametrize("error", [httpx.ConnectError("boom"), RuntimeError("bug"), KeyError("x")])
async def test_unexpected_error_before_publish_id_settles_the_row_failed(error) -> None:
    svc, repo, tiktok, _ = service(approved(), factory_error=error)
    state = await send(svc)
    assert (state.status, state.settled, state.publish_id) == ("failed", True, None)
    assert "Inténtalo de nuevo" in state.message and tiktok.inits == 0
    # Same attempt: the settled row comes back, nothing is sent.
    again = await send(svc)
    assert (again.status, again.created, tiktok.inits) == ("failed", False, 0)
    # The explicit retry (attempt + 1) is a fresh draft and goes through.
    svc._clients = type(  # noqa: SLF001 — swap the factory for a working one
        "F", (), {"client_for": lambda self, **_: _ready(tiktok)}
    )()
    retry = await send(svc, attempt=2)
    assert (retry.status, retry.created, tiktok.inits) == ("in_inbox", True, 1)
    assert len(repo.rows) == 2


async def _ready(client):
    return client


async def test_init_crash_settles_failed_but_upload_crash_after_publish_id_is_reconciled() -> None:
    svc, _, _, _ = service(approved(), tiktok=FakeTikTok(init_error=ValueError("bad json")))
    assert (await send(svc)).status == "failed"
    tiktok = FakeTikTok(status="PROCESSING_UPLOAD", upload_error=httpx.ReadTimeout("slow"))
    svc, _, _, _ = service(approved(), tiktok=tiktok)
    state = await send(svc)
    # The publish_id is stored before the bytes go up: TikTok owns the outcome now.
    assert (state.status, state.settled, state.publish_id) == (
        "uploading",
        False,
        "v_inbox_file~v2.9",
    )
    tiktok.status = "FAILED"
    done = await svc.refresh(tenant_id=TENANT, connection_id=CONN, draft_id=state.draft_id)
    assert done.status == "failed" and done.settled


async def test_missing_credential_asks_to_reconnect_and_settles_the_row() -> None:
    svc, repo, _, _ = service(approved(), factory_error=CredentialNotFound("none"))
    with pytest.raises(DraftRefused) as err:
        await send(svc)
    assert err.value.code == "needs_reconnect"
    row = next(iter(repo.rows.values()))
    assert (row["status"], row["code"]) == ("failed", "access_token_invalid")


async def test_refresh_settles_a_pending_row_without_publish_id_after_the_timeout() -> None:
    now = [datetime.now(UTC)]
    svc, repo, tiktok, _ = service(approved(), clock=lambda: now[0])
    record, _ = repo.create_or_get(  # a request that crashed right after the write-ahead
        idempotency_key="k", caption=None, tenant_id=TENANT, connection_id=CONN
    )
    fresh = await svc.refresh(tenant_id=TENANT, connection_id=CONN, draft_id=record.id)
    assert (fresh.status, fresh.settled) == ("pending", False)  # maybe still in flight
    now[0] += STALE_PENDING_AFTER + timedelta(seconds=1)
    stale = await svc.refresh(tenant_id=TENANT, connection_id=CONN, draft_id=record.id)
    assert (stale.status, stale.settled) == ("failed", True)
    assert "Inténtalo de nuevo" in stale.message and tiktok.inits == 0
    assert repo.rows["k"]["code"] == "stale_pending"

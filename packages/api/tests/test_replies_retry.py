"""ATENDER-9 (m-24849130): a public reply that did not go out is classified in four kinds,
and only a passing failure can be retried — on the owner's tap, once.

Offline: the classification is pure, the HTTP client runs over `httpx.MockTransport`, and
the service over the Memory repository with a fake reply client.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.assisted.approval import HumanApproval
from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.replies.client import CommentReplyError, HttpCommentReplyClient
from qualify_api.replies.failures import (
    classify_reply_error,
    error_code_for,
    failure_kind,
    is_retryable,
)
from qualify_api.replies.repository import CandidateComment, MemoryReplyRepository
from qualify_api.replies.service import ReplyService, RetryRefused, UnknownDraft
from qualify_api.sentiment.repository import AnalysisVersion

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")
USER = UUID("33333333-3333-4333-8333-333333333333")
OTHER_USER = UUID("44444444-4444-4444-8444-444444444444")
VERSION = AnalysisVersion(
    detector_version="det-1", pipeline_version="pipe-1", model_id="model-1", model_revision=None
)


# -- classification ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "kind", "code"),
    [
        (CommentReplyError("no route", not_sent=True), "transient", "transient:not_sent"),
        (
            CommentReplyError("down", platform_code=2, http_status=500),
            "transient",
            "transient:platform:2",
        ),
        (
            CommentReplyError("rate", platform_code=4, http_status=400),
            "transient",
            "transient:platform:4",
        ),
        (
            CommentReplyError(
                "flag", platform_code=9999, http_status=400, platform_is_transient=True
            ),
            "transient",
            "transient:platform:9999",
        ),
        (CommentReplyError("503", http_status=503), "transient", "transient:http:503"),
        (
            CommentReplyError("gone", platform_code=100, platform_subcode=33, http_status=400),
            "comment_deleted",
            "deleted:100/33",
        ),
        (
            CommentReplyError("validation", platform_code=100, http_status=400),
            "refused",
            "platform:100",
        ),
        (CommentReplyError("perm", platform_code=10, http_status=403), "refused", "platform:10"),
        (CommentReplyError("auth", platform_code=190, http_status=401), "refused", "auth:190"),
        (CommentReplyError("bare 400", http_status=400), "refused", "unknown"),
        (
            CommentReplyError("read timeout", is_ambiguous=True),
            "unknown",
            "ambiguous:transport",
        ),
        (CommentReplyError("gateway", http_status=504), "unknown", "ambiguous:http:504"),
    ],
)
def test_every_failure_has_one_kind_and_a_code_for_the_team(
    error: CommentReplyError, kind: str, code: str
) -> None:
    assert classify_reply_error(error) == kind
    assert error_code_for(error, classify_reply_error(error)) == code


def test_a_read_timeout_is_never_retryable_because_the_reply_may_be_public() -> None:
    """Measured 2026-10-22 (m-24789646 R4): the client timed out and the reply WAS out."""
    error = CommentReplyError("timeout", is_ambiguous=True)
    assert classify_reply_error(error) == "unknown"


@pytest.mark.parametrize(
    ("status", "code", "kind"),
    [
        ("send_failed", "transient:not_sent", "transient"),
        ("send_failed", "deleted:100/33", "comment_deleted"),
        ("send_failed", "platform:10", "refused"),
        ("send_failed", "auth:190", "refused"),
        ("send_failed", "unknown", "refused"),  # rows written before ATENDER-9
        ("send_failed", None, "refused"),
        ("send_ambiguous", "ambiguous:transport", "unknown"),
        ("sent", None, None),
        ("proposed", None, None),
    ],
)
def test_a_stored_outcome_reads_back_as_its_kind(
    status: str, code: str | None, kind: str | None
) -> None:
    assert failure_kind(status, code) == kind
    assert is_retryable(status, code) is (kind == "transient")


# -- the HTTP client ----------------------------------------------------------------------


def _client(handler) -> HttpCommentReplyClient:
    graph = _InjectedAuthClient("t", scheme="Bearer", transport=httpx.MockTransport(handler))
    return HttpCommentReplyClient(graph_client=graph, graph_url="https://graph.test/v21.0")


async def test_a_connect_error_is_marked_not_sent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    with pytest.raises(CommentReplyError) as info:
        await _client(handler).post_reply(ig_comment_id="1789", message="Gracias")
    assert info.value.not_sent is True
    assert info.value.is_ambiguous is False
    assert classify_reply_error(info.value) == "transient"


async def test_a_read_timeout_stays_ambiguous() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(CommentReplyError) as info:
        await _client(handler).post_reply(ig_comment_id="1789", message="Gracias")
    assert info.value.not_sent is False
    assert info.value.is_ambiguous is True
    assert classify_reply_error(info.value) == "unknown"


async def test_meta_is_transient_flag_is_read_from_the_error_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500, json={"error": {"code": 2, "is_transient": True, "message": "x"}}
        )

    with pytest.raises(CommentReplyError) as info:
        await _client(handler).post_reply(ig_comment_id="1789", message="Gracias")
    assert info.value.platform_is_transient is True
    assert classify_reply_error(info.value) == "transient"


async def test_a_deleted_comment_carries_its_subcode() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 100, "error_subcode": 33}})

    with pytest.raises(CommentReplyError) as info:
        await _client(handler).post_reply(ig_comment_id="1789", message="Gracias")
    assert classify_reply_error(info.value) == "comment_deleted"


# -- the service --------------------------------------------------------------------------


class FakeProvider:
    model_id = "fake-model"

    def draft_reply(self, *, comment_text: str, business_name: str | None = None) -> str:
        return "¡Gracias por tu comentario!"


class FakeReplyClient:
    def __init__(self) -> None:
        self.errors: list[Exception] = []
        self.calls: list[tuple[str, str]] = []

    async def post_reply(self, *, ig_comment_id: str, message: str) -> str:
        self.calls.append((ig_comment_id, message))
        if self.errors:
            raise self.errors.pop(0)
        return f"reply-{len(self.calls)}"


class FakeClientFactory:
    def __init__(self, client: FakeReplyClient) -> None:
        self._client = client

    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> FakeReplyClient:
        return self._client


def _approval(draft_id: UUID, user_id: UUID = USER) -> HumanApproval:
    return HumanApproval(user_id=user_id, approved_at=datetime.now(UTC), draft_id=draft_id)


def _setup(*errors: Exception, edited: str | None = None):
    repo = MemoryReplyRepository()
    client = FakeReplyClient()
    client.errors = list(errors)
    service = ReplyService(
        repository=repo,
        version=VERSION,
        generator_version="qua22.1:test",
        provider=FakeProvider(),
        client_factory=FakeClientFactory(client),
    )
    candidate = CandidateComment(
        message_id=uuid4(),
        source_id="ext-comment-1",
        text="qué rico!",
        sentiment_result_id=uuid4(),
        sentiment_label="POS",
        author_username="ana",
    )
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    [draft] = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    decided = service.decide(
        tenant_id=TENANT,
        draft_id=draft.id,
        decision="edited" if edited else "accepted",
        final_text=edited,
        decided_by_user_id=USER,
    ).draft
    sent = asyncio.run(
        service.send(tenant_id=TENANT, draft_id=decided.id, approval=_approval(decided.id))
    )
    return repo, client, service, sent


def _send(service: ReplyService, draft_id: UUID, user_id: UUID = USER):
    return asyncio.run(
        service.send(tenant_id=TENANT, draft_id=draft_id, approval=_approval(draft_id, user_id))
    )


def test_a_passing_failure_stays_visible_for_retry() -> None:
    repo, _client, _service, sent = _setup(CommentReplyError("down", not_sent=True))
    assert sent.status == "send_failed"
    assert sent.send_error_code == "transient:not_sent"
    retryable = repo.list_retryable_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    assert [d.id for d in retryable] == [sent.id]


@pytest.mark.parametrize(
    "error",
    [
        CommentReplyError("gone", platform_code=100, platform_subcode=33, http_status=400),
        CommentReplyError("perm", platform_code=10, http_status=403),
        CommentReplyError("timeout", is_ambiguous=True),
    ],
)
def test_other_failures_are_never_offered_a_retry(error: CommentReplyError) -> None:
    repo, client, service, sent = _setup(error)
    assert repo.list_retryable_drafts(tenant_id=TENANT, connection_id=CONNECTION) == ()
    with pytest.raises(RetryRefused):
        service.prepare_retry(tenant_id=TENANT, draft_id=sent.id, user_id=USER)
    assert len(client.calls) == 1  # nothing went out again


def test_retry_makes_a_new_approved_draft_and_never_sends_by_itself() -> None:
    repo, client, service, failed = _setup(CommentReplyError("down", not_sent=True))
    new = service.prepare_retry(tenant_id=TENANT, draft_id=failed.id, user_id=OTHER_USER)

    assert new.id != failed.id
    assert new.status == "accepted"
    assert new.final_text == failed.final_text
    assert new.decided_by_user_id == OTHER_USER  # the person who tapped
    assert len(client.calls) == 1  # preparing is not sending (N13)
    # The failed row is kept as the record of what happened.
    assert repo.get_draft(tenant_id=TENANT, draft_id=failed.id).send_error_code == (
        "transient:not_sent"
    )

    sent = _send(service, new.id, OTHER_USER)
    assert sent.status == "sent"
    assert client.calls[-1] == ("ext-comment-1", failed.final_text)
    assert repo.list_retryable_drafts(tenant_id=TENANT, connection_id=CONNECTION) == ()


def test_retry_keeps_the_owners_edit() -> None:
    _repo, client, service, failed = _setup(
        CommentReplyError("down", not_sent=True), edited="¡Gracias, Ana!"
    )
    new = service.prepare_retry(tenant_id=TENANT, draft_id=failed.id, user_id=USER)
    assert new.status == "edited"
    _send(service, new.id)
    assert client.calls[-1][1] == "¡Gracias, Ana!"


def test_a_second_tap_never_sends_twice() -> None:
    _repo, client, service, failed = _setup(CommentReplyError("down", not_sent=True))
    first = service.prepare_retry(tenant_id=TENANT, draft_id=failed.id, user_id=USER)
    with pytest.raises(RetryRefused):
        service.prepare_retry(tenant_id=TENANT, draft_id=failed.id, user_id=USER)
    _send(service, first.id)
    with pytest.raises(RetryRefused):
        service.prepare_retry(tenant_id=TENANT, draft_id=failed.id, user_id=USER)
    assert len(client.calls) == 2  # the first attempt and ONE retry


def test_a_retry_that_fails_again_replaces_the_card() -> None:
    repo, _client, service, failed = _setup(
        CommentReplyError("down", not_sent=True), CommentReplyError("down", not_sent=True)
    )
    new = service.prepare_retry(tenant_id=TENANT, draft_id=failed.id, user_id=USER)
    again = _send(service, new.id)
    assert again.status == "send_failed"
    retryable = repo.list_retryable_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    assert [d.id for d in retryable] == [again.id]  # one card per comment, the newest


def test_retry_of_an_unknown_draft_raises() -> None:
    _repo, _client, service, _failed = _setup(CommentReplyError("down", not_sent=True))
    with pytest.raises(UnknownDraft):
        service.prepare_retry(tenant_id=TENANT, draft_id=uuid4(), user_id=USER)

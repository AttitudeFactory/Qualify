"""S5 (m-24849192) offline: the 60 s page-load cache, the acting-login gate before
publish/send, and that every publish/send door actually calls the gate."""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.auth import NOT_A_MEMBER_MESSAGE, ActiveBusiness, NotAMember, membership
from qualify_api.tenancy.acting import acting_login, current_acting_login, require_acting_member
from qualify_api.whatsapp.chats import ChatService, MemoryChatRepository, TextSend
from qualify_api.whatsapp.outbox import MemoryOutboxRepository

LOGIN = uuid4()
TENANT = uuid4()
NOW = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)


def _business(tenant_id: UUID = TENANT) -> ActiveBusiness:
    return ActiveBusiness(
        tenant_id=tenant_id,
        business_name="Bianki",
        user_id=uuid4(),
        email="duena@example.com",
        display_name="Dueña",
        role="owner",
    )


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeDirectory:
    """Stands in for the database behind `open_business`."""

    def __init__(self) -> None:
        self.members: set[tuple[UUID, UUID]] = {(LOGIN, TENANT)}
        self.calls = 0

    def open_business(self, auth_user_id: UUID, tenant_id: UUID) -> ActiveBusiness:
        self.calls += 1
        if (auth_user_id, tenant_id) not in self.members:
            raise NotAMember()
        return _business(tenant_id)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(membership, "_cache", membership.MembershipCache(clock=fake))
    return fake


@pytest.fixture
def directory(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> FakeDirectory:
    fake = FakeDirectory()
    monkeypatch.setattr(membership, "open_business", fake.open_business)
    return fake


def test_ttl_is_the_signed_sixty_seconds() -> None:
    assert membership.MEMBERSHIP_CACHE_TTL == timedelta(seconds=60)


def test_page_load_keeps_working_within_the_ttl_and_refuses_after_it(
    directory: FakeDirectory, clock: FakeClock
) -> None:
    assert membership.check_membership(LOGIN, TENANT).tenant_id == TENANT
    directory.members.clear()  # the seat is removed with the session open

    clock.now += 59
    assert membership.check_membership(LOGIN, TENANT).tenant_id == TENANT  # cached
    assert directory.calls == 1

    clock.now += 1  # 60 s after the check
    with pytest.raises(NotAMember) as refused:
        membership.check_membership(LOGIN, TENANT)
    assert refused.value.message == NOT_A_MEMBER_MESSAGE
    assert NOT_A_MEMBER_MESSAGE == (
        "Ya no tienes acceso a este negocio. Vuelve a entrar para elegir otro."
    )


def test_a_refusal_is_never_cached_as_access(directory: FakeDirectory) -> None:
    directory.members.clear()
    for _ in range(2):
        with pytest.raises(NotAMember):
            membership.check_membership(LOGIN, TENANT)
    assert directory.calls == 2


def test_the_fresh_check_ignores_the_cache_and_evicts_it_on_refusal(
    directory: FakeDirectory,
) -> None:
    membership.check_membership(LOGIN, TENANT)
    directory.members.clear()
    with pytest.raises(NotAMember):
        membership.require_membership_now(LOGIN, TENANT)
    # The next page load agrees at once instead of trusting the stale entry.
    with pytest.raises(NotAMember):
        membership.check_membership(LOGIN, TENANT)
    assert directory.calls == 3


def test_cache_is_per_login_and_business(directory: FakeDirectory) -> None:
    other = uuid4()
    membership.check_membership(LOGIN, TENANT)
    with pytest.raises(NotAMember):
        membership.check_membership(LOGIN, other)
    with pytest.raises(NotAMember):
        membership.check_membership(uuid4(), TENANT)


def test_nobody_acting_is_a_no_op(directory: FakeDirectory) -> None:
    directory.members.clear()
    assert current_acting_login() is None
    require_acting_member(TENANT)  # workers / webhooks: unchanged
    assert directory.calls == 0


def test_the_acting_login_is_checked_fresh_every_time(directory: FakeDirectory) -> None:
    with acting_login(LOGIN):
        require_acting_member(TENANT)
        require_acting_member(TENANT)
        assert directory.calls == 2  # never served from the cache
        directory.members.clear()
        with pytest.raises(NotAMember):
            require_acting_member(TENANT)
    assert current_acting_login() is None


def test_acting_login_reaches_asyncio_to_thread(directory: FakeDirectory) -> None:
    directory.members.clear()

    async def handler() -> None:
        with acting_login(LOGIN):
            await asyncio.to_thread(require_acting_member, TENANT)

    with pytest.raises(NotAMember):
        asyncio.run(handler())


def test_acting_login_rejects_a_non_uuid() -> None:
    with pytest.raises(TypeError), acting_login("not-a-uuid"):  # type: ignore[arg-type]
        pass


def test_whatsapp_send_by_a_removed_login_writes_nothing(directory: FakeDirectory) -> None:
    repo = MemoryChatRepository()
    outbox = MemoryOutboxRepository(clock=lambda: NOW)
    service = ChatService(repo, outbox, clock=lambda: NOW)
    thread_id = repo.add_thread(tenant_id=TENANT, connection_id=uuid4(), wa_id="573001112233")
    repo.add_message(thread_id=thread_id, direction="inbound", text_value="hola", posted_at=NOW)
    directory.members.clear()

    with acting_login(LOGIN), pytest.raises(NotAMember):
        service.send(TENANT, thread_id, uuid4(), TextSend(text="hola"))
    assert outbox.rows == {}
    assert thread_id not in repo.states  # automation was not paused either


def _gated() -> list[object]:
    from qualify_api.conversations.ice_breakers import IceBreakerService
    from qualify_api.conversations.outbox import PostgresConversationOutboxRepository
    from qualify_api.planner.service import PlannerService
    from qualify_api.publishing import composition
    from qualify_api.replies.service import ReplyService
    from qualify_api.whatsapp.campaigns import CampaignService
    from qualify_api.whatsapp.menus.repository import PostgresMenuRepository
    from qualify_api.whatsapp.outbox import PostgresOutboxRepository
    from qualify_api.whatsapp.template_reply import TemplateReplyService
    from qualify_api.whatsapp.templates import TemplateService

    return [
        composition.stage_and_start_publish,
        composition.stage_and_start_many_publish,
        PlannerService._plan,
        PlannerService.reschedule,
        ReplyService.send,
        PostgresConversationOutboxRepository.enqueue,
        PostgresOutboxRepository.enqueue,
        ChatService.send,
        TemplateReplyService.send,
        CampaignService.launch,
        TemplateService.create,
        TemplateService.delete,
        PostgresMenuRepository.publish_version,
        IceBreakerService.publish,
        IceBreakerService.remove,
    ]


@pytest.mark.parametrize("door", _gated(), ids=lambda f: getattr(f, "__qualname__", str(f)))
def test_every_publish_or_send_door_calls_the_gate(door: object) -> None:
    """A static guard: removing the gate from a door must fail here, not in production."""
    source = inspect.getsource(door)  # type: ignore[arg-type]
    # Called directly, or handed to `asyncio.to_thread` by the async publishing seams.
    assert "require_acting_member(tenant_id)" in source or (
        "to_thread(require_acting_member, tenant_id)" in source
    )

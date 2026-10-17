"""The one switch of the Conversaciones composition (QUA-226): which pair answers for
channel `dm`. Offline: no Postgres, no Meta — the Instagram pair is built but never
called, and the in-memory pair is the same object the seed fills.
"""

from __future__ import annotations

import pytest

from qualify_api.conversations import composition
from qualify_api.conversations.contracts import CHANNEL_DM
from qualify_api.conversations.devseed import (
    EXIT_NOT_MEMORY_MODE,
    build_parser,
    fill_sample_conversations,
)
from qualify_api.conversations.instagram_source import (
    InstagramDirectSender,
    InstagramDirectSource,
)
from qualify_api.conversations.memory_source import (
    MemoryConversationSender,
    MemoryConversationSource,
)


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch: pytest.MonkeyPatch):
    composition.production_registry.cache_clear()
    monkeypatch.setattr(composition, "_MEMORY_SOURCE", None)
    monkeypatch.setattr(composition, "_MEMORY_SENDER", None)
    yield
    composition.production_registry.cache_clear()


def test_default_mode_is_instagram_and_typos_never_select_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(composition.DM_CHANNEL_ENV, raising=False)
    assert composition.dm_channel_mode() == composition.DM_CHANNEL_INSTAGRAM
    monkeypatch.setenv(composition.DM_CHANNEL_ENV, "memry")
    assert composition.dm_channel_mode() == composition.DM_CHANNEL_INSTAGRAM
    monkeypatch.setenv(composition.DM_CHANNEL_ENV, " Memory ")
    assert composition.dm_channel_mode() == composition.DM_CHANNEL_MEMORY


def test_instagram_mode_registers_the_messenger_platform_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(composition.DM_CHANNEL_ENV, raising=False)
    registry = composition.production_registry()
    assert isinstance(registry.source_for(CHANNEL_DM), InstagramDirectSource)
    assert isinstance(registry.sender_for(CHANNEL_DM), InstagramDirectSender)
    assert list(registry.channels()) == [CHANNEL_DM]


def test_memory_mode_registers_the_shared_in_memory_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(composition.DM_CHANNEL_ENV, "memory")
    registry = composition.production_registry()
    source, sender = composition.memory_pair()
    assert isinstance(source, MemoryConversationSource)
    assert isinstance(sender, MemoryConversationSender)
    assert registry.source_for(CHANNEL_DM) is source
    assert registry.sender_for(CHANNEL_DM) is sender


def test_the_seed_fills_three_conversations_with_one_closed_window() -> None:
    source = MemoryConversationSource()
    fill_sample_conversations(source, own_account_id="ig-1")
    assert sorted(source.conversations) == [
        "seed-igsid-alice",
        "seed-igsid-bruno",
        "seed-igsid-carla",
    ]
    assert len(source.messages["seed-igsid-alice"]) == 2
    directions = [m.direction for m in source.messages["seed-igsid-bruno"]]
    assert directions == ["inbound", "outbound"]
    assert source.messages["seed-igsid-bruno"][1].author_external_id == "ig-1"
    # Re-filling is harmless for the sync: the same mids dedupe at INSERT time.
    mids = [m.external_message_id for msgs in source.messages.values() for m in msgs]
    assert len(mids) == len(set(mids)) == 5


def test_the_seed_refuses_outside_memory_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from uuid import uuid4

    from qualify_api.conversations import devseed

    monkeypatch.delenv(composition.DM_CHANNEL_ENV, raising=False)
    import asyncio

    assert asyncio.run(devseed._run(uuid4(), None)) == EXIT_NOT_MEMORY_MODE
    with pytest.raises(SystemExit):
        build_parser().parse_args([])

"""QUA-106 V1 redesign: the ONLY backend logic `qualify_api.stories` still owns —
Meta's trending-audio reference (`GET /ig_audio`). Fully offline, fakes only. Same
degrade-don't-block guarantees the old `StoryProposalService.suggest_trend_audio`
had, now exercised directly against the standalone `suggest_trend_audio_using`."""

from __future__ import annotations

from uuid import UUID

from qualify_api.publishing.service import ConnectionTarget
from qualify_api.stories import TrendAudioError, TrendAudioOption, suggest_trend_audio_using

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")


class FakeConnections:
    def __init__(self, target: ConnectionTarget | None) -> None:
        self.target = target

    def read(self, *, tenant_id: UUID, connection_id: UUID) -> ConnectionTarget | None:
        return self.target


class FakeTrendAudioClient:
    def __init__(self, options: tuple[TrendAudioOption, ...] | Exception) -> None:
        self._options = options
        self.last_search_query: str | None = "unset"

    async def trending_audio(
        self, *, ig_user_id: str, audio_type: str, search_query: str | None = None
    ) -> tuple[TrendAudioOption, ...]:
        self.last_search_query = search_query
        if isinstance(self._options, Exception):
            raise self._options
        return self._options


class FakeTrendAudioClientFactory:
    def __init__(self, client: FakeTrendAudioClient) -> None:
        self._client = client

    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> FakeTrendAudioClient:
        return self._client


def _connections(target: ConnectionTarget | None = None) -> FakeConnections:
    return FakeConnections(
        target or ConnectionTarget(ig_user_id="17841448653847824", status="active")
    )


def test_suggest_trend_audio_returns_options_from_the_client() -> None:
    import asyncio

    option = TrendAudioOption(
        audio_id="a1",
        title="Song",
        artist_or_creator="Artist",
        audio_type="music",
        duration_ms=1000,
        rank=0,
    )
    options = asyncio.run(
        suggest_trend_audio_using(
            connections=_connections(),
            trend_clients=FakeTrendAudioClientFactory(FakeTrendAudioClient((option,))),
            tenant_id=TENANT,
            connection_id=CONNECTION,
        )
    )

    assert options == (option,)


def test_suggest_trend_audio_degrades_to_empty_on_error_never_raises() -> None:
    import asyncio

    options = asyncio.run(
        suggest_trend_audio_using(
            connections=_connections(),
            trend_clients=FakeTrendAudioClientFactory(
                FakeTrendAudioClient(TrendAudioError("boom"))
            ),
            tenant_id=TENANT,
            connection_id=CONNECTION,
        )
    )

    assert options == ()


def test_suggest_trend_audio_without_a_client_factory_returns_empty() -> None:
    import asyncio

    options = asyncio.run(
        suggest_trend_audio_using(
            connections=_connections(),
            trend_clients=None,
            tenant_id=TENANT,
            connection_id=CONNECTION,
        )
    )

    assert options == ()


def test_suggest_trend_audio_unknown_connection_returns_empty() -> None:
    import asyncio

    options = asyncio.run(
        suggest_trend_audio_using(
            connections=_connections(target=None),
            trend_clients=FakeTrendAudioClientFactory(FakeTrendAudioClient(())),
            tenant_id=TENANT,
            connection_id=CONNECTION,
        )
    )

    assert options == ()


def test_suggest_trend_audio_defaults_to_no_search_query() -> None:
    """The trending-list behavior, unchanged: omitting `search_query` forwards
    `None`, never an empty string or a sentinel — Meta's own documented default
    ("if no search query is provided, trending audio is returned")."""
    import asyncio

    client = FakeTrendAudioClient(())
    asyncio.run(
        suggest_trend_audio_using(
            connections=_connections(),
            trend_clients=FakeTrendAudioClientFactory(client),
            tenant_id=TENANT,
            connection_id=CONNECTION,
        )
    )

    assert client.last_search_query is None


def test_suggest_trend_audio_forwards_a_search_query_verbatim() -> None:
    import asyncio

    client = FakeTrendAudioClient(())
    asyncio.run(
        suggest_trend_audio_using(
            connections=_connections(),
            trend_clients=FakeTrendAudioClientFactory(client),
            tenant_id=TENANT,
            connection_id=CONNECTION,
            search_query="Oud Is Good",
        )
    )

    assert client.last_search_query == "Oud Is Good"

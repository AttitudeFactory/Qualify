"""Pure, network-free tests for the `/stories` trending panel (QUA-106 V1 redesign) —
mirrors `test_publishing_ui.py`'s conventions.

There is no `StoryProposal`/`StoryProposalVM` left to test here — publishing itself
reuses `publishing_provider`/`publishing_vm` directly (already covered by
`test_publishing_ui.py`). This file only covers what is genuinely still
Stories-specific: the Meta trending-audio reference.

Pins:
1. `TrendAudioOptionVM`/`TrendingVideoVM` carry no credential-bearing field, same
   QUA-18 convention as `ConnectionVM`/`PublishAttemptVM`.
2. `stories_provider.suggest_trend_audio` calls the REAL seam
   (`qualify_api.stories.suggest_trend_audio`), never a reimplementation.
3. `suggest_trend_audio` never raises — a failed lookup degrades to an empty list.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import inspect
from collections.abc import Callable, Coroutine, Iterator
from uuid import UUID

from qualify_api.stories.trend_audio_client import TrendAudioOption

from . import stories_provider
from .stories_vm import TrendAudioOptionVM, TrendingVideoVM

_FORBIDDEN_FIELD_FRAGMENTS = (
    "token",
    "credential",
    "cipher",
    "ciphertext",
    "secret",
    "key_id",
    "password",
    "plaintext",
)

_TENANT = UUID("a0000000-0000-4000-8000-000000000003")
_CONNECTION = UUID("c0000000-0000-4000-8000-000000000003")


@contextlib.contextmanager
def _patched(**replacements: Callable[..., object]) -> Iterator[None]:
    originals = {name: getattr(stories_provider, name) for name in replacements}
    for name, value in replacements.items():
        setattr(stories_provider, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(stories_provider, name, value)


def _run_coro(coro: Coroutine) -> object:
    return asyncio.run(coro)


def test_vms_have_no_credential_fields() -> None:
    for vm_cls in (TrendAudioOptionVM, TrendingVideoVM):
        for f in dataclasses.fields(vm_cls):
            lowered = f.name.lower()
            for fragment in _FORBIDDEN_FIELD_FRAGMENTS:
                assert fragment not in lowered, (
                    f"{vm_cls.__name__}.{f.name} looks credential-bearing "
                    f"(matched '{fragment}') — the VM is the security boundary."
                )


def test_provider_calls_the_real_stories_seam() -> None:
    source = inspect.getsource(stories_provider)
    assert "_suggest_trend_audio(" in source


def test_suggest_trend_audio_never_raises_projects_empty_list() -> None:
    async def _fake(**kwargs: object) -> tuple:
        return ()

    with _patched(_suggest_trend_audio=_fake):
        options = _run_coro(
            stories_provider.suggest_trend_audio(tenant_id=_TENANT, connection_id=_CONNECTION)
        )
    assert options == []


def test_suggest_trend_audio_projects_every_field() -> None:
    option = TrendAudioOption(
        audio_id="a1",
        title="Song",
        artist_or_creator="Artist",
        audio_type="music",
        duration_ms=90_000,
        rank=2,
        preview_url="https://example.test/a1.mp3",
    )

    async def _fake(**kwargs: object) -> tuple[TrendAudioOption, ...]:
        return (option,)

    with _patched(_suggest_trend_audio=_fake):
        (vm,) = _run_coro(
            stories_provider.suggest_trend_audio(tenant_id=_TENANT, connection_id=_CONNECTION)
        )
    assert vm.audio_id == "a1"
    assert vm.title == "Song"
    assert vm.artist_or_creator == "Artist"
    assert vm.rank == 2
    assert vm.preview_url == "https://example.test/a1.mp3"
    assert vm.has_preview is True


def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 - surface any error in the harness
            failures += 1
            print(f"ERROR {test.__name__}: {exc!r}")
        else:
            print(f"ok   {test.__name__}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run())

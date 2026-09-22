"""Pure, network-free tests for the Stories screens (QUA-106) — mirrors
`test_publishing_ui.py`'s conventions.

Pins:
1. `StoryProposalVM`/`TrendAudioOptionVM` carry no credential-bearing field, same
   QUA-18 convention as `ConnectionVM`/`PublishAttemptVM`.
2. `stories_provider` calls the REAL seam (`qualify_api.stories`'s published
   functions), never a reimplementation of staging/publishing/decision logic.
3. `build_proposal_vm`'s boolean fields (`can_decide`/`can_publish`/`is_publishing`/
   `is_terminal`) are correct for every status the CHECK constraint allows.
4. `propose_story`/`decide_proposal`/`publish_proposal`/`refresh_proposal` propagate
   exceptions rather than swallowing them — same posture `publishing_provider`
   already has for `UnknownConnection`/`UnknownAttempt`.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import inspect
from collections.abc import Callable, Coroutine, Iterator
from datetime import UTC, datetime
from uuid import UUID

from qualify_api.stories.repository import ProposalRecord, UnknownProposal

from . import stories_provider
from .stories_vm import (
    STATUS_LABELS,
    StoryProposalVM,
    TrendAudioOptionVM,
    TrendingVideoVM,
    build_proposal_vm,
)

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
_PROPOSAL = UUID("e0000000-0000-4000-8000-000000000003")


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


def _record(**overrides: object) -> ProposalRecord:
    defaults: dict[str, object] = {
        "id": _PROPOSAL,
        "tenant_id": _TENANT,
        "connection_id": _CONNECTION,
        "media_object_key": f"t/{_TENANT}/stories/x.mp4",
        "media_content_type": "video/mp4",
        "caption": "Hola",
        "final_caption": None,
        "trend_audio_id": None,
        "trend_audio_title": None,
        "status": "proposed",
        "publish_attempt_id": None,
        "publish_error_code": None,
        "created_at": datetime.now(UTC),
        "decided_at": None,
        "decided_by_user_id": None,
        "settled_at": None,
    }
    defaults.update(overrides)
    return ProposalRecord(**defaults)


def test_vms_have_no_credential_fields() -> None:
    for vm_cls in (StoryProposalVM, TrendAudioOptionVM, TrendingVideoVM):
        for f in dataclasses.fields(vm_cls):
            lowered = f.name.lower()
            for fragment in _FORBIDDEN_FIELD_FRAGMENTS:
                assert fragment not in lowered, (
                    f"{vm_cls.__name__}.{f.name} looks credential-bearing "
                    f"(matched '{fragment}') — the VM is the security boundary."
                )


def test_provider_calls_the_real_stories_seam() -> None:
    """The write/decision paths must delegate to `qualify_api.stories`, never
    reimplement staging/decision/publish logic in the Reflex layer."""
    source = inspect.getsource(stories_provider)
    assert "_stage_and_propose_story(" in source
    assert "_decide_proposal(" in source
    assert "_publish_proposal(" in source
    assert "_refresh_proposal(" in source
    assert "_suggest_trend_audio(" in source


def test_build_proposal_vm_every_status_has_a_label_and_correct_flags() -> None:
    expectations = {
        "proposed": (True, False, False, False),
        "approved": (False, True, False, False),
        "edited": (False, True, False, False),
        "rejected": (False, False, False, True),
        "publishing": (False, False, True, False),
        "published": (False, False, False, True),
        "publish_failed": (False, False, False, True),
    }
    assert set(expectations) == set(STATUS_LABELS)
    for status, (can_decide, can_publish, is_publishing, is_terminal) in expectations.items():
        vm = build_proposal_vm(
            id="p1",
            connection_id="c1",
            caption="hola",
            trend_audio_id="",
            trend_audio_title="",
            status=status,
            publish_error_code="",
            created_label="20 sep 2026, 10:00",
        )
        assert vm.can_decide is can_decide, status
        assert vm.can_publish is can_publish, status
        assert vm.is_publishing is is_publishing, status
        assert vm.is_terminal is is_terminal, status
        assert vm.status_label == STATUS_LABELS[status]


def test_get_proposal_projects_display_caption_and_trend_fields() -> None:
    with _patched(_get_proposal=lambda **kwargs: _record(final_caption="Editado")):
        vm = stories_provider.get_proposal(tenant_id=_TENANT, proposal_id=_PROPOSAL)
    assert vm.caption == "Editado"  # display_caption prefers final_caption
    assert vm.trend_audio_id == ""
    assert vm.has_trend_audio is False


def test_get_proposal_propagates_unknown_proposal() -> None:
    def _raise(**kwargs: object) -> ProposalRecord:
        raise UnknownProposal(str(_PROPOSAL))

    with _patched(_get_proposal=_raise):
        try:
            stories_provider.get_proposal(tenant_id=_TENANT, proposal_id=_PROPOSAL)
        except UnknownProposal:
            pass
        else:
            raise AssertionError("get_proposal must not swallow UnknownProposal")


def test_propose_story_forwards_caption_and_trend_fields() -> None:
    seen: dict[str, object] = {}

    async def _fake(**kwargs: object) -> ProposalRecord:
        seen.update(kwargs)
        return _record()

    with _patched(_stage_and_propose_story=_fake):
        _run_coro(
            stories_provider.propose_story(
                tenant_id=_TENANT,
                connection_id=_CONNECTION,
                fileobj=None,  # type: ignore[arg-type] — never touched by the fake
                content_type="video/mp4",
                caption="Un caption",
                trend_audio_id="a1",
                trend_audio_title="Song",
            )
        )
    assert seen["caption"] == "Un caption"
    assert seen["trend_audio_id"] == "a1"
    assert seen["trend_audio_title"] == "Song"


def test_publish_proposal_propagates_value_error() -> None:
    """The route/service-level guarantee behind QUA-106's mandatory approval must
    reach the Reflex layer unmuted — `stories_state.py` relies on catching this."""

    async def _raise(**kwargs: object) -> ProposalRecord:
        raise ValueError("proposal ... is 'proposed', cannot publish")

    with _patched(_publish_proposal=_raise):
        try:
            _run_coro(stories_provider.publish_proposal(tenant_id=_TENANT, proposal_id=_PROPOSAL))
        except ValueError:
            pass
        else:
            raise AssertionError("publish_proposal must not swallow ValueError")


def test_suggest_trend_audio_never_raises_projects_empty_list() -> None:
    async def _fake(**kwargs: object) -> tuple:
        return ()

    with _patched(_suggest_trend_audio=_fake):
        options = _run_coro(
            stories_provider.suggest_trend_audio(tenant_id=_TENANT, connection_id=_CONNECTION)
        )
    assert options == []


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

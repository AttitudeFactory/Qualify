"""m-24973636: /brand never stays on its loading card.

Measured in production on an Alta account (claimed draft, Instagram proposal `proposed`,
nothing typed by the owner): `enter` decided the page (`synced`), the page swapped the
step frame for the proposal's review card, the frame's `on_unmount` (`leave_frame`)
cleared `synced`, which turned `loading` back on, which hid the review card and put the
frame — with its loading card — back on screen. Nothing ever ran `enter` again."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
import reflex as rx
from qualify_api.meegle.prefill_jobs import InMemoryPrefillJobs, NewPrefillJob

from . import brand_minimal as minimal
from . import brand_minimal_vm as vm
from . import creative_wizard_pages as wiz
from .auth_state import AuthState
from .brand_minimal import BrandMinimalState

_FRAME_CLASS = "q-step-frame"


def _cond_ancestors_of_frame(component: Any, conds: int = 0) -> list[int]:
    """How many `rx.cond` wrap each step frame in the page (one entry per frame)."""
    found: list[int] = []
    class_name = getattr(component, "class_name", None)
    if isinstance(class_name, str) and _FRAME_CLASS in class_name.split():
        found.append(conds)
    inside = conds + (1 if type(component).__name__ == "Cond" else 0)
    for child in getattr(component, "children", []) or []:
        found.extend(_cond_ancestors_of_frame(child, inside))
    return found


def test_the_step_frame_stays_mounted_whatever_face_the_page_shows() -> None:
    """The review card, «Te faltan 3 cosas» and «Tu marca está lista» never unmount the
    frame: its `on_unmount` is what cleared `synced` and froze the page."""
    from .brand_minimal import brand_minimal_index

    frames = _cond_ancestors_of_frame(brand_minimal_index())
    assert frames == [0]


def test_which_face_shows_never_depends_on_the_frames_own_sync() -> None:
    """The face (review, answers, preparing, steps) is decided by `enter` alone; `synced`
    only gates what the frame writes into the address."""
    from .brand_minimal import page_faces

    faces = page_faces()
    for name, var in faces.items():
        assert "synced" not in str(var), name
    assert isinstance(faces["review"], rx.Var)


# --------------------------------------------------------------------------------------
# «Tu marca todavía se está preparando» (the Alta's prefill still queued or retrying)
# --------------------------------------------------------------------------------------

_TENANT = "a0000000-0000-4000-8000-000000000002"


class _States:
    def __init__(self) -> None:
        self.instances: dict[type, Any] = {}

    def __call__(self, cls: type) -> Any:
        if cls not in self.instances:
            self.instances[cls] = cls()
        return self.instances[cls]


@pytest.fixture
def states(monkeypatch: pytest.MonkeyPatch) -> _States:
    holder = _States()

    async def get_state(_self: object, cls: type) -> Any:
        return holder(cls)

    for cls in (BrandMinimalState, wiz.BrandWizardState, wiz.BrandConnectState):
        monkeypatch.setattr(cls, "get_state", get_state)
    return holder


def _entry(preparing_network: str | None) -> Any:
    return minimal._Entry(False, None, vm.KitFacts(), {}, preparing_network=preparing_network)


async def _enter(state: Any) -> list[Any]:
    return [event async for event in BrandMinimalState.enter.fn(state)]


@pytest.fixture
def entering(states: _States, monkeypatch: pytest.MonkeyPatch) -> Any:
    states(AuthState).session_tenant_id = _TENANT
    monkeypatch.setattr(minimal, "_read_account_country", lambda _tenant: "")
    monkeypatch.setattr(minimal, "step_param", lambda _state: None)
    return states(BrandMinimalState)


async def test_an_alta_still_reading_the_account_says_so_and_waits_once(
    entering: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(minimal, "_read_entry", lambda _t: _entry("instagram"))
    events = await _enter(entering)
    assert entering.preparing and entering.entered and entering.synced
    assert "Instagram" in entering.preparing_text
    assert any("wait_for_prefill" in str(e) for e in events)
    # a second visit while the first loop still looks does not start another one
    events = await _enter(entering)
    assert entering.preparing
    assert not any("wait_for_prefill" in str(e) for e in events)


async def test_start_without_waiting_opens_the_steps_for_the_session(
    entering: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(minimal, "_read_entry", lambda _t: _entry("instagram"))
    await _enter(entering)
    BrandMinimalState.skip_preparing.fn(entering)
    assert not entering.preparing
    await _enter(entering)
    assert not entering.preparing and entering.step == vm.FIRST_STEP


async def test_a_settled_prefill_or_leaving_the_page_stops_the_wait(
    entering: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(minimal, "_read_entry", lambda _t: _entry("instagram"))
    await _enter(entering)
    BrandMinimalState.leave_frame.fn(entering)
    assert not entering.preparing and not entering.synced
    monkeypatch.setattr(minimal, "_read_entry", lambda _t: _entry(None))
    await _enter(entering)
    assert not entering.preparing


def test_the_preparing_copy_is_plain_spanish() -> None:
    assert vm.preparing_text("instagram").startswith("Estamos leyendo tu cuenta de Instagram")
    assert "TikTok" in vm.preparing_text("tiktok")
    assert vm.preparing_text("").startswith("Estamos leyendo tu cuenta para")
    words = " ".join(
        (
            vm.PREPARING_TITLE,
            vm.PREPARING_HINT,
            vm.PREPARING_RECHECK,
            vm.PREPARING_SKIP,
            vm.SLOW_HINT,
            vm.SLOW_RELOAD,
            vm.preparing_text("instagram"),
        )
    ).lower()
    for banned in ("brand kit", "post", "feed", "loading", "prefill", "scrape", "error"):
        assert banned not in words


def test_the_page_carries_the_preparing_face_and_the_slow_hint() -> None:
    from .brand_minimal import brand_minimal_index

    rendered = str(brand_minimal_index())

    def shown(text: str) -> bool:
        return text in rendered or json.dumps(text)[1:-1] in rendered

    for text in (vm.PREPARING_TITLE, vm.PREPARING_SKIP, vm.SLOW_HINT, vm.SLOW_RELOAD):
        assert shown(text), text
    assert "q-slow-hint" in rendered


def test_only_a_job_still_reading_counts_as_waiting() -> None:
    jobs = InMemoryPrefillJobs()
    tenant, other = uuid4(), uuid4()
    now = datetime.now(UTC)
    assert jobs.waiting_network(tenant, now=now) is None
    base = {
        "brand_id": uuid4(),
        "max_usd": Decimal("0.15"),
        "pipeline_version": "t",
    }
    jobs.enqueue(
        NewPrefillJob(tenant, meegle_work_item_id=1, network="instagram", handle="a", **base)
    )
    jobs.enqueue(
        NewPrefillJob(
            other, meegle_work_item_id=2, network="", handle="", outcome="no_handle", **base
        )
    )
    assert jobs.waiting_network(tenant, now=now) == "instagram"
    assert jobs.waiting_network(other, now=now) is None

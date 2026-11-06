"""m-24973458: «Crear publicación» shows the ring while a publication is being made.

Offline: the server read's windows, the watching loop (reads, polls only while busy,
one loop per session, a failed read keeps the last answer, a guest is never busy), and
that the sidebar and the phone's bar draw the ring only under the flag. Tenant
isolation of the read itself is the `db` test in
`packages/api/tests/test_creative_in_flight_db.py`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_api.creative import in_flight
from qualify_api.creative.draft_mode import FINAL_STALE_SECONDS

from Qualify import generation_state as gs
from Qualify.auth_state import business_state_classes
from Qualify.generation_state import BUSY_TEXT, LOOP_STALE_S, GenerationState, loop_alive
from Qualify.ui import layout

#: The busy text as it appears in a rendered component (Reflex escapes the accents).
BUSY_RENDERED = "Creando tu publicaci"

# -- the server read -----------------------------------------------------------------


def test_the_read_uses_the_reapers_window_and_the_finals_stale_threshold() -> None:
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    params = in_flight.in_flight_params(now=now, epoch_now=1_000_000.0)
    assert params["drafting"] == "drafting"
    assert params["alive_after"] == now - timedelta(minutes=in_flight.ALIVE_MINUTES)
    assert in_flight.ALIVE_MINUTES >= 20  # never shorter than the reaper's default
    assert params["rendering_after"] == 1_000_000.0 - FINAL_STALE_SECONDS
    assert params["immediate"] == "immediate"  # a nightly job is not «now»
    assert params["final"] == "final" and params["now"] == now  # a due final in the queue
    assert {params["queued"], params["claimed"], params["submitted"]} == {
        "queued",
        "claimed",
        "submitted",
    }


def test_the_read_is_one_exists_through_the_tenant_door(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class _Result:
        def scalar_one(self) -> bool:
            return True

    class _Session:
        def execute(self, statement, params):
            seen["sql"] = str(statement)
            seen["params"] = params
            return _Result()

    class _Door:
        def __init__(self, tenant_id: UUID) -> None:
            seen["tenant"] = tenant_id

        def __enter__(self) -> _Session:
            return _Session()

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(in_flight, "tenant_session", _Door)
    tenant = uuid4()
    assert in_flight.generation_in_flight(tenant) is True
    assert seen["tenant"] == tenant
    sql = str(seen["sql"])
    assert sql.count("SELECT EXISTS") == 1
    # RLS does the scoping: nothing filters by tenant by hand
    assert "tenant_id" not in sql


# -- the watching loop ---------------------------------------------------------------


class _Fake:
    """Just enough of a Reflex state for `GenerationState._watch`."""

    def __init__(self, tenant: UUID | None, answers: list[bool | None]) -> None:
        self.busy = False
        self._loop_beat = 0.0
        self._loop_id = 0
        self.tenant = tenant
        self.answers = answers
        self.reads = 0

    async def __aenter__(self) -> _Fake:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def _tenant(self) -> UUID | None:
        return self.tenant

    async def _read(self, _tenant_id: UUID) -> bool | None:
        self.reads += 1
        return self.answers.pop(0)


def _run(fake: _Fake, *, force: bool, monkeypatch) -> list[bool]:
    seen: list[bool] = []

    async def _sleep(_s: float) -> None:
        seen.append(fake.busy)

    monkeypatch.setattr(gs.asyncio, "sleep", _sleep)
    asyncio.run(GenerationState._watch(fake, force=force))
    return seen


def test_the_flag_is_on_while_something_is_made_and_off_when_it_lands(monkeypatch) -> None:
    fake = _Fake(uuid4(), [True, True, False])
    slept = _run(fake, force=False, monkeypatch=monkeypatch)
    assert fake.reads == 3
    assert slept == [True, True]  # polled only while busy
    assert fake.busy is False
    assert fake._loop_beat == 0.0  # the loop ended: the next mount reads again


def test_nothing_running_means_one_read_and_no_poll(monkeypatch) -> None:
    fake = _Fake(uuid4(), [False])
    slept = _run(fake, force=False, monkeypatch=monkeypatch)
    assert fake.reads == 1
    assert slept == []
    assert fake.busy is False


def test_a_failed_read_keeps_the_last_answer(monkeypatch) -> None:
    fake = _Fake(uuid4(), [True, None, False])
    slept = _run(fake, force=False, monkeypatch=monkeypatch)
    assert slept == [True, True]
    assert fake.busy is False


def test_a_guest_is_never_busy_and_never_reads(monkeypatch) -> None:
    fake = _Fake(None, [])
    fake.busy = True
    _run(fake, force=False, monkeypatch=monkeypatch)
    assert fake.busy is False
    assert fake.reads == 0


def test_one_loop_per_session(monkeypatch) -> None:
    fake = _Fake(uuid4(), [False])
    fake._loop_beat = gs.time.time()  # a loop is alive
    _run(fake, force=False, monkeypatch=monkeypatch)
    assert fake.reads == 0  # a mount leaves it to the live loop
    slept = _run(fake, force=True, monkeypatch=monkeypatch)
    assert fake.reads == 1  # a refresh reads once…
    assert slept == []  # …without starting a second loop


def test_a_newer_loop_retires_an_older_one(monkeypatch) -> None:
    fake = _Fake(uuid4(), [True, True])
    real_read = fake._read

    async def _read_then_superseded(tenant_id: UUID) -> bool | None:
        answer = await real_read(tenant_id)
        fake._loop_id += 1  # another mount started a loop while this one read
        return answer

    fake._read = _read_then_superseded
    slept = _run(fake, force=False, monkeypatch=monkeypatch)
    assert fake.reads == 1 and slept == []  # the old loop left without polling


def test_leaving_the_business_turns_the_ring_off(monkeypatch) -> None:
    fake = _Fake(uuid4(), [True])
    fake.busy = True
    real_read = fake._read

    async def _read_then_logout(tenant_id: UUID) -> bool | None:
        answer = await real_read(tenant_id)
        fake.tenant = None
        return answer

    fake._read = _read_then_logout
    _run(fake, force=False, monkeypatch=monkeypatch)
    assert fake.busy is False and fake._loop_beat == 0.0


def test_the_menu_and_the_generator_say_the_same_words() -> None:
    from Qualify.creative_vm import CREATING_LABEL

    assert BUSY_TEXT == CREATING_LABEL


def test_a_dead_loop_does_not_freeze_the_ring() -> None:
    assert loop_alive(100.0, 100.0 + LOOP_STALE_S - 1)
    assert not loop_alive(100.0, 100.0 + LOOP_STALE_S)
    assert not loop_alive(0.0, 5.0)


def test_logout_resets_the_flag() -> None:
    assert GenerationState in business_state_classes()


def test_the_bookkeeping_stays_on_the_server() -> None:
    sent_to_browser = set(GenerationState.vars)
    assert "busy" in sent_to_browser
    assert "_loop_beat" not in sent_to_browser


# -- the menu ------------------------------------------------------------------------


def test_only_crear_publicacion_carries_the_ring() -> None:
    labels = {label for label, _icon, _route, enabled in layout.NAV_ITEMS if enabled}
    assert set(layout.NAV_BUSY) == {"Crear publicación"}
    assert set(layout.NAV_BUSY) <= labels
    # a counted entry has its own spoken name: the two maps must never meet
    assert not set(layout.NAV_BUSY) & set(layout.NAV_COUNTERS)


def test_the_ring_takes_the_icons_place_only_under_the_flag() -> None:
    icon = layout.nav_icon("wand-sparkles", 18)
    assert layout.busy_icon(icon, None) is icon
    assert layout.busy_icon(icon, False) is icon
    assert "q-spinner" in str(layout.busy_icon(icon, True).render())
    assert "q-spinner" not in str(icon.render())
    under_flag = str(layout.busy_icon(icon, GenerationState.busy).render())
    assert "q-spinner" in under_flag and "cond_state" in under_flag
    assert "generation_state" in under_flag


def test_the_sidebar_entry_says_it_is_busy() -> None:
    rendered = str(layout._nav_item("Crear publicación", "wand-sparkles", "/create", True).render())
    assert "q-spinner" in rendered
    assert "generation_state" in rendered
    assert "aria-busy" in rendered or "ariaBusy" in rendered
    assert BUSY_RENDERED in rendered
    # other entries never show it
    plain = str(layout._nav_item("Galería", "images", "/catalog", True).render())
    assert "q-spinner" not in plain and BUSY_RENDERED not in plain


def test_the_busy_name_starts_with_the_visible_word() -> None:
    on = layout.busy_attrs("Crear publicación", True)
    assert on["aria_busy"] == "true"
    assert on["aria_label"].startswith("Crear publicación")
    assert BUSY_TEXT in on["aria_label"]
    assert "title" not in on  # collapsed, the menu's own label says it (no double tooltip)
    assert layout.busy_label("Crear publicación", True) == f"Crear publicación · {BUSY_TEXT}"
    assert layout.busy_label("Galería", None) is None
    assert layout.busy_attrs("Crear publicación", False) == {"aria_busy": "false"}
    assert layout.busy_attrs("Galería", None) == {}


def test_the_phone_bar_shows_the_ring_on_crear() -> None:
    rendered = str(layout._bottom_bar().render())
    assert "q-spinner" in rendered and "generation_state" in rendered
    assert "Crear publicaci\\\\u00f3n. " + BUSY_RENDERED in rendered


def test_every_screen_asks_on_mount() -> None:
    assert "GenerationState.on_shell_mount" in str(layout.sidebar().event_triggers["on_mount"])


@pytest.mark.parametrize("handler", ["poll_generator", "poll_draft", "poll_final"])
def test_the_generator_lights_the_ring_when_it_starts_watching(handler: str) -> None:
    import inspect

    from Qualify import creative_state

    source = inspect.getsource(getattr(creative_state.CreativeState, handler).fn)
    assert "GenerationState.refresh" in source


def test_a_landed_piece_drops_the_ring_at_once() -> None:
    from Qualify.creative_state import _generation_done_events

    for outcome in ("ready", "failed"):
        events = [str(event) for event in _generation_done_events(outcome)]
        assert any("GenerationState.refresh" in event for event in events)

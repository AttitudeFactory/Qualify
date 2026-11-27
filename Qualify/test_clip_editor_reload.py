"""ED-04 (m-25026627, Deivid 2026-11-20: «cuando selecciono las fotos, imágenes, la página
se recarga»). «Arma tu video» writes its own history: choosing a block (`?bloque=`) and
opening a side panel push an entry; letting it go — «Listo», ✕, the phone's «atrás» —
walks back, a `popstate`. Reflex runs the page's `on_load` on every route change, and
`load_create` swapped the whole workspace for «Cargando el generador»: the step remounted
and every picture was asked for again — what looked like a reload. A step of the
editor's own history on the page already loaded now keeps the workspace on screen; a
real reload or a reconnect (another socket) still shows the loading card.

Also: picking in «Tu Galería» from the side panel never navigates nor touches the
history, and never changes the step that is keyed (`key=gen_step_key`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from . import clip_editor_vm
from . import creative_state as module
from .creative_state import CreativeState
from .gen_gallery_pick_provider import GalleryPick
from .test_generator_campaign import _Proxy

_TENANT = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND = UUID("c0000000-0000-4000-8000-000000000003")
_SOCKET = "sid-1"
_PHOTO = f"gallery/{_TENANT}/m1/foto.jpg"


@pytest.fixture
def editor_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", True)


def _editor_page() -> CreativeState:
    """«Arma tu video» on screen, the page already loaded on this socket."""
    state = CreativeState()
    state.choose_category("clip")
    state.create_entered = True
    state.create_loading = False
    state._brand_id = str(_BRAND)
    state._create_loaded_identity = (str(_TENANT), str(_BRAND), _SOCKET)
    return state


def _loads(monkeypatch: pytest.MonkeyPatch, state: CreativeState, socket: str) -> list[bool]:
    """`load_create`'s reads replaced: what `create_loading` was during each."""
    seen: list[bool] = []

    async def ids(self: object) -> tuple[UUID, UUID, UUID]:
        seen.append(state.create_loading)
        return _TENANT, _BRAND, _TENANT

    async def voice(tenant: UUID, brand: UUID) -> bool:
        return False

    async def creations(self: object, tenant: UUID, brand: UUID) -> None:
        return None

    def read(result: Any):  # noqa: ANN202 — a test double
        def inner(*args: object) -> Any:
            seen.append(state.create_loading)
            return result

        return inner

    monkeypatch.setattr(CreativeState, "_create_session_id", lambda self: socket)
    monkeypatch.setattr(CreativeState, "_session_ids", ids)
    monkeypatch.setattr(CreativeState, "_kit_voice_missing", staticmethod(voice))
    monkeypatch.setattr(CreativeState, "_refresh_creations", creations)
    monkeypatch.setattr(module, "brand_readiness", read(None))
    monkeypatch.setattr(module, "route_options_for", read(()))
    monkeypatch.setattr(module, "brand_media", read([]))
    monkeypatch.setattr(module, "brand_campaign_options", read([]))
    monkeypatch.setattr(module, "brand_cta_patterns", read(()))
    return seen


async def test_a_history_step_of_the_editor_keeps_the_workspace(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _editor_page()
    assert state.clip_editor_on_screen
    seen = _loads(monkeypatch, state, _SOCKET)
    await CreativeState.load_create.fn(_Proxy(state))
    assert seen and not any(seen)  # never «Cargando el generador»
    assert not state.create_loading and state.gen_step_key == "show"


async def test_a_reload_or_a_reconnect_still_shows_the_loading_card(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _editor_page()
    seen = _loads(monkeypatch, state, "sid-2")  # another socket: a reload or a reconnect
    await CreativeState.load_create.fn(_Proxy(state))
    assert seen and all(seen)
    assert not state.create_loading


async def test_outside_the_editor_the_load_is_as_before(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _editor_page()
    state.gen_step = 1  # «Qué decir»: not the editor
    assert not state.clip_editor_on_screen
    seen = _loads(monkeypatch, state, _SOCKET)
    await CreativeState.load_create.fn(_Proxy(state))
    assert seen and all(seen)


@pytest.mark.parametrize("socket", [_SOCKET, "sid-2"])
async def test_a_session_saved_with_the_old_text_loads_it_as_text_one(
    editor_on: None, monkeypatch: pytest.MonkeyPatch, socket: str
) -> None:
    """ED-13 (m-25029108): a session kept from before ED-13 holds ED-10's ONE text in
    `clip_overlay_text` & co.; a history step or a reload of the step loads it as text 1
    of `clip_text_uses` — its place and seconds, never twice — and the old fields are
    left empty."""
    state = _editor_page()
    state.clip_overlay_text = "2×1 hoy"
    state._clip_text_committed = "2×1 hoy"
    state.clip_text_place = "top"
    state.clip_text_start, state.clip_text_end = 2.0, 6.0
    _loads(monkeypatch, state, socket)
    await CreativeState.load_create.fn(_Proxy(state))
    (use,) = state.clip_text_uses
    assert (use["uid"], use["text"], use["place"]) == ("t1", "2×1 hoy", "top")
    assert (use["start"], use["end"], use["blocks"]) == (2.0, 6.0, [])
    assert (state.clip_overlay_text, state._clip_text_committed) == ("", "")
    # loaded again: still one text
    await CreativeState.load_create.fn(_Proxy(state))
    assert len(state.clip_text_uses) == 1


def test_a_gallery_pick_keeps_the_step_and_the_address(editor_on: None) -> None:
    state = _editor_page()
    before = (state.gen_step_key, state.create_step_n, state.clip_editor_on_screen)
    added = state.add_gallery_picks(
        [GalleryPick(key=_PHOTO, media_type="image", name="foto.jpg", role="product")]
    )
    assert added == 1 and [i["key"] for i in state.clip_images] == [_PHOTO]
    assert (state.gen_step_key, state.create_step_n, state.clip_editor_on_screen) == before
    assert not state.create_loading and state.media_drawer_open is False


def test_the_gallery_pick_path_never_navigates() -> None:
    """Nothing on the tap's way (`pick` → `finish` → `add_gallery_picks`) redirects,
    reloads or writes the history: only choosing a block does (`?bloque=`)."""
    here = Path(__file__).resolve().parent
    source = (here / "gen_gallery_pick_state.py").read_text(encoding="utf-8")
    for word in ("rx.redirect", "history.", "location.", "call_script"):
        assert word not in source
    state = (here / "creative_state.py").read_text(encoding="utf-8")
    picks = state[state.index("    def add_gallery_picks(") :]
    picks = picks[: picks.index("\n    def ", 10)]
    for word in ("rx.redirect", "call_script", "_clip_choose", "_clip_block_url"):
        assert word not in picks

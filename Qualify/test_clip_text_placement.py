"""EF-20 phase 2 (m-25026599): «el texto puede tapar tu producto» in the text's panel of
«Arma tu video». The server keeps, once per uploaded video, where the product shows and
the better band for the text (`qualify_api.creative.placement_advice`); the editor reads
it once per Clip (`creative_provider.clip_placement_advice`, behind
`QUALIFY_VIDEO_PLACEMENT_AI`), compares it with the place the owner chose on every change
(`clip_texts_vm.placement_hint`) and shows the warning with «Poner el texto arriba».
Deivid (2026-11-23): never a block, never a move by itself.

Offline: the provider's read is simulated; handlers are called through `.fn`
(`test_creative_state.py` explains why)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from qualify_api.creative import placement_advice as pa_mod
from qualify_api.creative import upload_previews
from qualify_api.creative.placement_advice import PlacementAdvice

from . import clip_editor_vm, clip_texts_vm, creative_provider
from . import creative_state as module
from .creative_provider import ClipPlacementRead
from .creative_state import CreativeState
from .test_clip_editor_state import _KEY, _SECOND, _timeline_state

_TENANT = UUID("a0000000-0000-4000-8000-000000000001")
_OTHER = UUID("b0000000-0000-4000-8000-000000000002")
_SWITCH = "QUALIFY_VIDEO_PLACEMENT_AI"


def _advice(
    key: str, bands: tuple[str, ...], text: str = "top", logo: str = "top"
) -> dict[str, Any]:
    """A kept advice as the server stores it (`PlacementAdvice.to_params`)."""
    return PlacementAdvice(
        source_key=key,
        subject_bands=bands,
        recommended_text_band=text,
        recommended_logo_band=logo,
        reason_es="",
        model="claude-haiku",
        prompt_version="v1",
        frames=(),
        cost_usd=Decimal("0.001"),
        made_at=datetime(2026, 11, 24, tzinfo=UTC),
    ).to_params()


@pytest.fixture
def editor_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", True)


# -- the view model: the warning and the better place ------------------------------------------


def test_no_advice_says_nothing() -> None:
    assert clip_texts_vm.placement_hint([], "bottom") == {
        "warning": "",
        "use_text": "",
        "use_place": "",
        "done": "",
    }


def test_a_place_over_the_product_warns_and_offers_the_better_one() -> None:
    hint = clip_texts_vm.placement_hint([_advice(_KEY, ("bottom",), "top")], "bottom")
    assert hint == {
        "warning": "Abajo, el texto puede tapar tu producto. Arriba no lo tapa.",
        "use_text": "Poner el texto arriba",
        "use_place": "top",
        "done": "Listo: el texto quedó arriba, sin tapar tu producto.",
    }


@pytest.mark.parametrize("place", ["top", "middle"])
def test_the_best_place_or_a_free_one_says_nothing(place: str) -> None:
    hint = clip_texts_vm.placement_hint([_advice(_KEY, ("bottom",), "top")], place)
    assert hint["warning"] == "" and hint["use_place"] == ""


def test_a_product_that_fills_the_video_says_where_it_covers_it_less() -> None:
    advice = _advice(_KEY, ("top", "middle", "bottom"), "top")
    hint = clip_texts_vm.placement_hint([advice], "middle")
    expected = "En el medio, el texto puede tapar tu producto. Arriba lo tapa menos."
    assert hint["warning"] == expected
    assert hint["use_place"] == "top"
    assert hint["done"] == "Listo: el texto quedó arriba, donde tapa menos tu producto."


@pytest.mark.parametrize(
    ("place", "advice", "expected"),
    [
        ("bottom", ("bottom",), "Abajo, el texto puede tapar tu producto. Arriba no lo tapa."),
        (
            "middle",
            ("middle",),
            "En el medio, el texto puede tapar tu producto. Arriba no lo tapa.",
        ),
        ("top", ("top",), "Arriba, el texto puede tapar tu producto. Abajo no lo tapa."),
    ],
)
def test_ux3_the_warning_names_the_place_chosen(
    place: str, advice: tuple[str, ...], expected: str
) -> None:
    """UX review 3 (m-25026599): «Aquí…» did not say where — the warning names the place
    the owner chose with the editor's own words (Arriba / En el medio / Abajo)."""
    best = "bottom" if place == "top" else "top"
    hint = clip_texts_vm.placement_hint([_advice(_KEY, advice, best)], place)
    assert hint["warning"] == expected
    assert "Aquí" not in hint["warning"]


def test_ux2_the_confirmation_says_the_text_no_longer_covers_the_product() -> None:
    """ux-designer 2: «Listo: el texto quedó arriba, sin tapar tu producto.»; a product
    that fills the video: «…, donde tapa menos tu producto.»"""
    for band, words in pa_mod.BAND_WORDS.items():  # the server's words, not a copy
        assert (
            clip_texts_vm.placement_done_line(band)
            == f"Listo: el texto quedó {words}, sin tapar tu producto."
        )
    fills = clip_texts_vm.placement_done_line("top", fills_frame=True)
    assert fills == "Listo: el texto quedó arriba, donde tapa menos tu producto."
    assert clip_texts_vm.placement_done_line("left") == ""


def test_ux1_the_button_never_offers_a_place_another_text_takes() -> None:
    """ux-designer 1: two texts in one place stop «Siguiente» («Aquí se verían dos
    textos…»): a place another text takes at those seconds is skipped (`TEXT_PREFERENCE`
    order); none free that does not cover the product: the warning without a button."""
    advice = [_advice(_KEY, ("bottom",), "top")]
    hint = clip_texts_vm.placement_hint(advice, "bottom", taken=["top"])
    assert hint["use_place"] == "middle"
    assert hint["use_text"] == "Poner el texto en el medio"
    assert hint["warning"] == "Abajo, el texto puede tapar tu producto. En el medio no lo tapa."
    alone = clip_texts_vm.placement_hint(advice, "bottom", taken=["top", "middle"])
    assert alone == {
        "warning": "Abajo, el texto puede tapar tu producto.",
        "use_text": "",
        "use_place": "",
        "done": "",
    }


def test_several_videos_count_the_product_of_all_of_them() -> None:
    """The text keeps one place for the whole piece: the product low in one video and high
    in the other leaves the middle (`combine_advice`)."""
    advices = [_advice(_KEY, ("bottom",), "top"), _advice(_SECOND, ("top",), "bottom")]
    hint = clip_texts_vm.placement_hint(advices, "top")
    assert hint["warning"] == "Arriba, el texto puede tapar tu producto. En el medio no lo tapa."
    assert hint["use_text"] == "Poner el texto en el medio"
    assert hint["use_place"] == "middle"
    assert clip_texts_vm.placement_hint(advices, "middle")["warning"] == ""


def test_with_subtitles_a_recommended_abajo_gives_way_to_a_free_place() -> None:
    """«Abajo» is the subtitles' (Deivid 2026-11-23): the button never offers it."""
    advice = _advice(_KEY, ("top",), "bottom")
    hint = clip_texts_vm.placement_hint([advice], "top", subtitles=True)
    assert hint["use_place"] == "middle"
    assert hint["warning"] == "Arriba, el texto puede tapar tu producto. En el medio no lo tapa."
    # nothing free besides «Abajo»: the warning alone, no button (ux-designer 1)
    busy = _advice(_KEY, ("top", "middle"), "bottom")
    alone = clip_texts_vm.placement_hint([busy], "top", subtitles=True)
    assert alone["warning"] == "Arriba, el texto puede tapar tu producto."
    assert alone["use_place"] == alone["use_text"] == ""


def test_an_unusable_advice_is_left_out() -> None:
    broken = {"recommended_text_band": "left", "subject_bands": ["bottom"]}
    assert clip_texts_vm.placement_hint([broken, "nada"], "bottom")["warning"] == ""  # type: ignore[list-item]


def test_the_videos_that_may_carry_advice() -> None:
    videos = [
        {"key": _KEY, "source": "upload"},
        {"key": "reel.mp4", "source": "reel"},
        {"key": _KEY, "source": "upload"},
        {"key": "", "source": "upload"},
        {"key": _SECOND, "source": "upload"},
    ]
    assert clip_texts_vm.placement_keys(videos) == [_KEY, _SECOND]


def test_the_advice_is_read_once_per_clip_and_retried_only_for_a_missing_one() -> None:
    sig = clip_texts_vm.placement_signature("t", [_SECOND, _KEY])
    assert sig == clip_texts_vm.placement_signature("t", [_KEY, _SECOND])
    due = clip_texts_vm.placement_ask_due
    assert due(sig, asked="", missing=False, asked_at=0.0, now=1.0)
    assert not due(sig, asked=sig, missing=False, asked_at=0.0, now=10_000.0)
    assert not due(sig, asked=sig, missing=True, asked_at=100.0, now=130.0)
    assert due(sig, asked=sig, missing=True, asked_at=100.0, now=160.0)
    assert due(clip_texts_vm.placement_signature("t", [_KEY]), asked=sig, missing=False,
               asked_at=0.0, now=1.0)  # fmt: skip
    assert not due("", asked="", missing=False, asked_at=0.0, now=1.0)


def test_the_panel_row_carries_the_warning() -> None:
    state = _timeline_state()
    use = {"uid": "t1", "text": "2×1 hoy", "place": "bottom", "start": 0.0, "end": 4.0}
    media = state._clip_tl_media()
    row = clip_texts_vm.text_panel_row(use, media, placement=[_advice(_KEY, ("bottom",))])
    assert row["placement_warning"].startswith("Abajo, el texto puede tapar tu producto.")
    assert row["placement_use"] == "Poner el texto arriba"
    assert row["placement_place"] == "top"
    plain = clip_texts_vm.text_panel_row(use, media)
    assert plain["placement_warning"] == plain["placement_use"] == plain["placement_place"] == ""


# -- the provider: one read, behind the switch -------------------------------------------------


def test_with_the_switch_off_the_provider_reads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def never(*_a: Any) -> dict[str, Any]:
        raise AssertionError("the advice is read with the switch off")

    monkeypatch.setattr(pa_mod, "placement_advice_for", never)
    off = ClipPlacementRead()
    assert creative_provider.clip_placement_advice(_TENANT, [_KEY], env={}) == off
    assert creative_provider.clip_placement_advice(_TENANT, [_KEY], env={_SWITCH: "off"}) == off


def test_with_the_switch_on_it_reads_every_video_in_one_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[UUID, list[str]]] = []

    def read(tenant_id: UUID, keys: list[str]) -> dict[str, PlacementAdvice]:
        calls.append((tenant_id, list(keys)))
        advice = PlacementAdvice.from_params(_advice(_KEY, ("bottom",)))
        assert advice is not None
        return {_KEY: advice}

    monkeypatch.setattr(pa_mod, "placement_advice_for", read)
    # both are the business's uploads: the second one is still waiting for its advice
    monkeypatch.setattr(upload_previews, "is_previewable", lambda tenant_id, key: True)
    got = creative_provider.clip_placement_advice(_TENANT, [_KEY, _SECOND], env={_SWITCH: "on"})
    assert calls == [(_TENANT, [_KEY, _SECOND])]
    assert set(got.advice) == {_KEY} and got.advice[_KEY]["subject_bands"] == ["bottom"]
    assert got.waiting and not got.failed
    # a video that never gets advice (Galería, stock…) is not waited for
    monkeypatch.setattr(upload_previews, "is_previewable", lambda tenant_id, key: key == _KEY)
    got = creative_provider.clip_placement_advice(_TENANT, [_KEY, _SECOND], env={_SWITCH: "on"})
    assert not got.waiting


def test_a_failed_read_leaves_no_advice(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a: Any) -> dict[str, Any]:
        raise RuntimeError("db down")

    monkeypatch.setattr(pa_mod, "placement_advice_for", broken)
    got = creative_provider.clip_placement_advice(_TENANT, [_KEY], env={_SWITCH: "1"})
    assert got.advice == {} and got.failed and got.waiting


# -- the state: read once per Clip, warn, move only on the owner's tap -----------------------


def _with_text(place: str = "bottom") -> CreativeState:
    """«Arma tu video» with a photo and two videos, and a text being put at `place`."""
    state = _timeline_state()
    CreativeState.open_clip_flow.fn(state, "text")
    uid = state._clip_text_current()
    CreativeState.set_clip_text_value.fn(state, uid, "2×1 hoy")
    CreativeState.commit_clip_text.fn(state, uid, "2×1 hoy")
    if place != "bottom":
        CreativeState.set_clip_text_place.fn(state, uid, place)
    return state


def _serve(
    monkeypatch: pytest.MonkeyPatch,
    found: dict[str, dict[str, Any]],
    tenant: UUID = _TENANT,
    *,
    advisable: tuple[str, ...] = (_KEY, _SECOND),
    fail: bool = False,
) -> list[tuple[UUID, list[str]]]:
    """The provider simulated: `found` kept advice, `advisable` the videos that may get
    one (the owner's uploads), `fail` a read that failed."""
    calls: list[tuple[UUID, list[str]]] = []

    async def session_tenant(self: CreativeState) -> UUID:
        return tenant

    def read(tenant_id: UUID, keys: list[str]) -> ClipPlacementRead:
        calls.append((tenant_id, list(keys)))
        if fail:
            return ClipPlacementRead(failed=True, waiting=True)
        advice = {k: v for k, v in found.items() if k in keys}
        waiting = any(k in advisable and k not in advice for k in keys)
        return ClipPlacementRead(advice=advice, waiting=waiting)

    monkeypatch.setenv(_SWITCH, "on")  # the state reads nothing with the switch off
    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", session_tenant)
    monkeypatch.setattr(module, "clip_placement_advice", read)
    return calls


async def test_with_the_switch_off_the_state_does_not_even_look_up_the_session(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review: with `QUALIFY_VIDEO_PLACEMENT_AI` off, `load_clip_placement` returns before
    the session's business (`get_state(AuthState)`) and before any thread."""

    async def never_tenant(self: CreativeState) -> UUID:
        raise AssertionError("the session is looked up with the switch off")

    async def never_thread(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a thread is started with the switch off")

    state = _with_text("bottom")
    monkeypatch.setenv(_SWITCH, "off")
    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", never_tenant)
    monkeypatch.setattr(module.asyncio, "to_thread", never_thread)
    await CreativeState.load_clip_placement.fn(state)
    assert state._clip_placement_asked == "" and state._clip_placement == {}
    assert state.clip_text_panel_row["placement_warning"] == ""


async def test_the_panel_warns_and_the_button_moves_the_text_only_when_tapped(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _with_text("bottom")
    calls = _serve(monkeypatch, {_KEY: _advice(_KEY, ("bottom",), "top")})
    uid = state._clip_text_current()
    await CreativeState.load_clip_placement.fn(state)
    assert calls == [(_TENANT, [_KEY, _SECOND])]
    row = state.clip_text_panel_row
    # read, never applied: the text stays where the owner put it
    assert row["place"] == "bottom"
    assert row["placement_warning"] == "Abajo, el texto puede tapar tu producto. Arriba no lo tapa."
    assert row["placement_use"] == "Poner el texto arriba"
    # a warning, never a block: «Siguiente» does not wait for it
    assert state.clip_text_problem == "" and not state._clip_text_holds_next()
    focus = CreativeState.use_clip_text_placement.fn(state, uid)
    row = state.clip_text_panel_row
    assert row["place"] == "top" and row["placement_warning"] == ""
    # the button leaves the page: the focus goes to the place chosen, never lost
    assert focus is not None
    # tapped again with nothing to warn: nothing moves
    assert CreativeState.use_clip_text_placement.fn(state, uid) is None
    assert state.clip_text_panel_row["place"] == "top"


async def test_the_button_ignores_a_text_whose_panel_is_not_open(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _with_text("bottom")
    _serve(monkeypatch, {_KEY: _advice(_KEY, ("bottom",), "top")})
    await CreativeState.load_clip_placement.fn(state)
    CreativeState.use_clip_text_placement.fn(state, "t9")
    assert state.clip_text_panel_row["place"] == "bottom"


async def test_a_text_in_a_free_place_shows_nothing_new(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _with_text("middle")
    _serve(monkeypatch, {_KEY: _advice(_KEY, ("bottom",), "top")})
    await CreativeState.load_clip_placement.fn(state)
    assert state.clip_text_panel_row["placement_warning"] == ""


async def test_without_advice_the_panel_shows_nothing_new(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _with_text("bottom")
    _serve(monkeypatch, {})
    await CreativeState.load_clip_placement.fn(state)
    row = state.clip_text_panel_row
    assert row["placement_warning"] == row["placement_use"] == row["placement_place"] == ""
    CreativeState.use_clip_text_placement.fn(state, state._clip_text_current())
    assert state.clip_text_panel_row["place"] == "bottom"


async def test_with_the_switch_off_the_panel_shows_nothing_new(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real provider, the switch off: no read at all, nothing on screen."""

    async def session_tenant(self: CreativeState) -> UUID:
        return _TENANT

    def never(*_a: Any) -> dict[str, Any]:
        raise AssertionError("the advice is read with the switch off")

    monkeypatch.delenv(_SWITCH, raising=False)
    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", session_tenant)
    monkeypatch.setattr(pa_mod, "placement_advice_for", never)
    state = _with_text("bottom")
    await CreativeState.load_clip_placement.fn(state)
    assert state.clip_text_panel_row["placement_warning"] == ""


async def test_with_the_switch_on_the_real_provider_feeds_the_panel(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def session_tenant(self: CreativeState) -> UUID:
        return _TENANT

    def read(tenant_id: UUID, keys: list[str]) -> dict[str, PlacementAdvice]:
        advice = PlacementAdvice.from_params(_advice(_KEY, ("bottom",), "top"))
        assert advice is not None and tenant_id == _TENANT
        return {_KEY: advice}

    monkeypatch.setenv(_SWITCH, "on")
    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", session_tenant)
    monkeypatch.setattr(pa_mod, "placement_advice_for", read)
    state = _with_text("bottom")
    await CreativeState.load_clip_placement.fn(state)
    assert state.clip_text_panel_row["placement_use"] == "Poner el texto arriba"


async def test_the_advice_is_read_once_per_clip_not_per_change(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _with_text("bottom")
    calls = _serve(
        monkeypatch,
        {_KEY: _advice(_KEY, ("bottom",)), _SECOND: _advice(_SECOND, ("bottom",))},
    )
    await CreativeState.load_clip_placement.fn(state)
    uid = state._clip_text_current()
    for place in ("top", "middle", "bottom"):
        CreativeState.set_clip_text_place.fn(state, uid, place)
        _ = state.clip_text_panel_row
    await CreativeState.load_clip_placement.fn(state)  # the panel opened again
    assert len(calls) == 1


async def test_a_video_still_without_advice_is_asked_again_after_a_minute(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _with_text("bottom")
    found: dict[str, dict[str, Any]] = {}
    calls = _serve(monkeypatch, found)
    await CreativeState.load_clip_placement.fn(state)
    await CreativeState.load_clip_placement.fn(state)
    assert len(calls) == 1 and state.clip_text_panel_row["placement_warning"] == ""
    # the media-worker kept it meanwhile; a minute went by
    found[_KEY] = _advice(_KEY, ("bottom",), "top")
    state._clip_placement_at -= clip_texts_vm.PLACEMENT_RETRY_S + 1
    await CreativeState.load_clip_placement.fn(state)
    assert len(calls) == 2
    assert state.clip_text_panel_row["placement_use"] == "Poner el texto arriba"


async def test_another_business_never_sees_the_last_ones_advice(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _with_text("bottom")
    _serve(monkeypatch, {_KEY: _advice(_KEY, ("bottom",), "top")})
    await CreativeState.load_clip_placement.fn(state)
    assert state.clip_text_panel_row["placement_warning"] != ""
    calls = _serve(monkeypatch, {}, tenant=_OTHER)
    await CreativeState.load_clip_placement.fn(state)
    assert calls == [(_OTHER, [_KEY, _SECOND])]
    assert state.clip_text_panel_row["placement_warning"] == ""


async def test_a_video_taken_out_of_the_clip_no_longer_counts(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _with_text("top")
    _serve(
        monkeypatch,
        {_KEY: _advice(_KEY, ("bottom",), "top"), _SECOND: _advice(_SECOND, ("top",), "bottom")},
    )
    await CreativeState.load_clip_placement.fn(state)
    # both videos: «Arriba» covers the second one's product
    assert state.clip_text_panel_row["placement_place"] == "middle"
    state.clip_videos = [v for v in state.clip_videos if v["key"] != _SECOND]
    assert state._clip_placement_kept() == [_advice(_KEY, ("bottom",), "top")]


async def test_no_session_business_reads_nothing(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def nobody(self: CreativeState) -> None:
        return None

    def never(*_a: Any) -> dict[str, Any]:
        raise AssertionError("read without a business")

    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", nobody)
    monkeypatch.setattr(module, "clip_placement_advice", never)
    state = _with_text("bottom")
    await CreativeState.load_clip_placement.fn(state)
    assert state.clip_text_panel_row["placement_warning"] == ""


async def test_a_failed_read_keeps_what_the_clip_already_showed(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _with_text("bottom")
    _serve(monkeypatch, {_KEY: _advice(_KEY, ("bottom",), "top")})
    await CreativeState.load_clip_placement.fn(state)
    assert state._clip_placement_missing  # the second video is still waiting
    calls = _serve(monkeypatch, {}, fail=True)
    state._clip_placement_at -= clip_texts_vm.PLACEMENT_RETRY_S + 1
    await CreativeState.load_clip_placement.fn(state)
    assert len(calls) == 1
    assert state.clip_text_panel_row["placement_use"] == "Poner el texto arriba"


async def test_a_video_that_never_gets_advice_is_not_asked_again(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A video from Galería or stock (not uploaded here) never gets advice: no retry."""
    state = _with_text("bottom")
    calls = _serve(monkeypatch, {_KEY: _advice(_KEY, ("bottom",))}, advisable=(_KEY,))
    await CreativeState.load_clip_placement.fn(state)
    state._clip_placement_at -= clip_texts_vm.PLACEMENT_RETRY_S + 1
    await CreativeState.load_clip_placement.fn(state)
    assert len(calls) == 1


async def test_with_subtitles_the_button_never_puts_the_text_abajo(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _with_text("bottom")
    state.clip_subtitles = True
    uid = state._clip_text_current()
    CreativeState.set_clip_text_place.fn(state, uid, "top")
    _serve(monkeypatch, {_KEY: _advice(_KEY, ("top",), "bottom")})
    await CreativeState.load_clip_placement.fn(state)
    row = state.clip_text_panel_row
    assert row["placement_use"] == "Poner el texto en el medio"
    CreativeState.use_clip_text_placement.fn(state, uid)
    assert state.clip_text_panel_row["place"] == "middle"


def test_the_hidden_reader_mounts_again_for_another_text_or_video_set(
    editor_on: None,
) -> None:
    state = _with_text("bottom")
    first = state.clip_placement_mount
    assert first == f"{state._clip_text_current()}|{_KEY}|{_SECOND}"
    state.clip_videos = [v for v in state.clip_videos if v["key"] != _SECOND]
    assert state.clip_placement_mount != first


def test_the_focus_after_the_button_goes_to_the_place_chosen() -> None:
    script = clip_texts_vm.focus_place_script("texto-t1")
    assert '[aria-labelledby="clip-text-place-title"]' in script
    assert '[data-tl-panel="texto-t1"]' in script
    # ux-designer 5: «Dónde va el texto» shut — its folded header, before the whole panel
    assert "getElementById('clip-text-place-title')" in script
    assert "closest('button')" in script and "b || s || p" in script
    assert "texto-t1');" not in clip_texts_vm.focus_place_script("texto-t1');alert(1)//")


# -- UX review of the warning (m-25026599): 2, 4 and 6 ---------------------------------------


def _nodes(tree: Any) -> list[dict[str, Any]]:
    """Every rendered element of `tree` (`Component.render()`), cond branches included."""
    found: list[dict[str, Any]] = []
    if isinstance(tree, dict):
        if "name" in tree:
            found.append(tree)
        for key in ("children", "true_value", "false_value"):
            value = tree.get(key)
            for child in value if isinstance(value, list) else [value]:
                found.extend(_nodes(child))
    return found


def _live(node: dict[str, Any]) -> bool:
    props = " ".join(str(p) for p in node.get("props", []))
    return 'role:"status"' in props or 'role:"alert"' in props or "aria-live" in props


def _warning_tree() -> dict[str, Any]:
    from .ui import text_panel as tp

    row = CreativeState.clip_text_panel_row
    return tp._placement_warning(row, CreativeState.use_clip_text_placement).render()


def test_ux2_the_warning_has_one_live_region_not_one_inside_another() -> None:
    """UX review 2: one `role=status`, always in the page; its callouts carry no role of
    their own and the button is outside it (never read as part of the message)."""
    tree = _warning_tree()
    live = [node for node in _nodes(tree) if _live(node)]
    assert len(live) == 1
    region = live[0]
    assert 'id:"clip-text-placement-live"' in region["props"]
    assert '"aria-atomic":"true"' in region["props"]
    inside = _nodes(region)
    assert not any(_live(node) for node in inside[1:])  # nothing nested speaks again
    assert any("Callout.Root" in node["name"] for node in inside)
    assert not any("Button" in node["name"] for node in inside)
    assert any("Button" in node["name"] for node in _nodes(tree))
    # the design system's callout still speaks by itself elsewhere
    from .ui.primitives import callout

    assert 'role:"status"' in str(callout("Hola", tone="warn").render())
    assert "role:" not in str(callout("Hola", tone="warn", live=False).render())


def test_ux4_the_warning_unfolds_without_a_jump_and_respects_reduced_motion() -> None:
    """UX review 4: the block is always in the page and opens (`data-open`) as a grid row
    from 0 to its height — no sudden push of «Dónde va el texto» —; nothing moves with
    `prefers-reduced-motion`."""
    from pathlib import Path

    tree = _warning_tree()
    assert tree["name"] == '"div"'  # the wrapper itself is never conditional
    props = " ".join(tree["props"])
    assert 'className:"q-place-warn"' in props and '"data-open"' in props
    css = (Path(__file__).resolve().parent.parent / "assets" / "qualify-creative.css").read_text(
        encoding="utf-8"
    )
    block = css[css.index(".q-place-warn {") :]
    assert "grid-template-rows: 0fr" in block and "transition: grid-template-rows" in block
    assert '.q-place-warn[data-open="1"] { grid-template-rows: 1fr; }' in css
    reduced = css[css.index("@media (prefers-reduced-motion: reduce) {\n  .q-place-warn") :]
    assert ".q-place-warn { transition: none; }" in reduced[:120]


async def test_ux6_the_button_says_what_it_did_once_in_the_panel(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UX review 6: «Listo: el texto quedó arriba, …» in the panel's own live region (the panel
    is modal: the timeline's line sits behind it), no toast, not said again by the
    timeline's line, and gone with the editor's next change."""
    state = _with_text("bottom")
    _serve(monkeypatch, {_KEY: _advice(_KEY, ("bottom",), "top")})
    uid = state._clip_text_current()
    await CreativeState.load_clip_placement.fn(state)
    assert state.clip_text_panel_row["placement_done"] == ""
    event = CreativeState.use_clip_text_placement.fn(state, uid)
    row = state.clip_text_panel_row
    assert row["placement_done"] == "Listo: el texto quedó arriba, sin tapar tu producto."
    assert row["placement_warning"] == ""
    assert state.clip_edit_notice == ""  # never «Cambiaste el lugar del texto.» as well
    assert "toast" not in str(event)
    # the editor's next change: the line was about the last one only
    CreativeState.set_clip_text_place.fn(state, uid, "middle")
    assert state.clip_text_panel_row["placement_done"] == ""
    assert state.clip_edit_notice != ""


# -- Deivid's decision A, ux-designer 1 at the state, review nit 1 ---------------------------


def _resolved(*uses: tuple[str, str, float, float]) -> list[dict[str, object]]:
    """Written texts at their seconds: `(uid, place, start, end)`."""
    return [
        {"uid": uid, "text": "Hola", "place": place, "start": start, "end": end}
        for uid, place, start, end in uses
    ]


def test_decision_a_a_new_text_is_born_where_it_does_not_cover_the_product() -> None:
    """Deivid (A): kept advice → the recommended place; taken at those seconds → the next
    free one of `TEXT_PREFERENCE` that does not cover the product; none, or no advice →
    `default_place` («Abajo»; never «Abajo» with the subtitles on)."""
    place = clip_texts_vm.new_text_place
    advice = [_advice(_KEY, ("bottom",), "top")]
    new = ("t2", "bottom", 0.0, 4.0)
    assert place([], _resolved(new), "t2") == "bottom"
    assert place(advice, _resolved(new), "t2") == "top"
    # «Arriba» taken by another text at those seconds: the middle, free and clear
    assert place(advice, _resolved(("t1", "top", 2.0, 6.0), new), "t2") == "middle"
    # «Arriba» taken only at other seconds: still free
    assert place(advice, _resolved(("t1", "top", 4.0, 6.0), new), "t2") == "top"
    # every free place covers the product or is taken: «Abajo», as before
    full = _resolved(("t1", "top", 0.0, 4.0), ("t3", "middle", 0.0, 4.0), new)
    assert place(advice, full, "t2") == "bottom"
    # subtitles: never «Abajo», even when it is recommended
    low = [_advice(_KEY, ("top",), "bottom")]
    assert place(low, _resolved(new), "t2", subtitles=True) == "middle"
    assert place([], _resolved(new), "t2", subtitles=True) == "middle"


def _put_another(state: CreativeState) -> str:
    """«+ Texto» once more, after letting the current text go."""
    CreativeState.done_clip_block.fn(state)
    CreativeState.open_clip_flow.fn(state, "text")
    return state._clip_text_current()


async def test_decision_a_the_state_puts_the_new_text_in_the_recommended_place(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _with_text("bottom")
    first = state._clip_text_current()
    _serve(monkeypatch, {_KEY: _advice(_KEY, ("bottom",), "top")})
    await CreativeState.load_clip_placement.fn(state)
    second = _put_another(state)
    assert second and second != first
    places = {str(u["uid"]): u["place"] for u in state.clip_text_uses}
    # the new one is born «Arriba»; the one that already had a place never moves
    assert places[second] == "top" and places[first] == "bottom"


async def test_decision_a_without_advice_a_new_text_is_born_abajo(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _with_text("middle")
    _serve(monkeypatch, {})
    await CreativeState.load_clip_placement.fn(state)
    second = _put_another(state)
    assert {str(u["uid"]): u["place"] for u in state.clip_text_uses}[second] == "bottom"


async def test_ux1_the_button_skips_the_place_of_a_text_shown_at_the_same_time(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ux-designer 1 at the state: the other text «Arriba» at the same seconds — the
    button puts this one in the middle and «Siguiente» is not stopped."""
    state = _with_text("top")
    first = state._clip_text_current()
    second = _put_another(state)
    CreativeState.set_clip_text_value.fn(state, second, "Envío gratis")
    CreativeState.commit_clip_text.fn(state, second, "Envío gratis")
    CreativeState.set_clip_text_place.fn(state, second, "bottom")
    resolved = state._clip_text_resolved()
    one = next(u for u in resolved if u["uid"] == first)
    two = next(u for u in resolved if u["uid"] == second)
    assert clip_texts_vm._overlap(one, two)  # shown at the same time
    _serve(monkeypatch, {_KEY: _advice(_KEY, ("bottom",), "top")})
    await CreativeState.load_clip_placement.fn(state)
    row = state.clip_text_panel_row
    assert row["uid"] == second
    assert row["placement_use"] == "Poner el texto en el medio"
    CreativeState.use_clip_text_placement.fn(state, second)
    assert state.clip_text_panel_row["place"] == "middle"
    assert state.clip_text_problem == ""


async def test_review_nit1_the_confirmation_goes_with_another_text_or_the_panel_shut(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _with_text("bottom")
    uid = state._clip_text_current()
    _serve(monkeypatch, {_KEY: _advice(_KEY, ("bottom",), "top")})
    await CreativeState.load_clip_placement.fn(state)
    CreativeState.use_clip_text_placement.fn(state, uid)
    assert state.clip_text_panel_row["placement_done"] != ""
    CreativeState.done_clip_block.fn(state)  # the panel shut
    assert state._clip_placement_done == state._clip_placement_done_line == ""
    CreativeState.select_clip_block.fn(state, clip_texts_vm.text_block_id(uid))
    assert state.clip_text_panel_row["placement_done"] == ""

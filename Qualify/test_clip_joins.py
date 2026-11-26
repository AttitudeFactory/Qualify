"""m-25114465 «Tocar la unión»: the join between two blocks of «Fotos y videos» in the
Clip editor — «Corte» by default, «Fundido» / «Barrido» only where they fit, the switch
`QUALIFY_CLIP_BLOCK_TRANSITIONS`, the recipe's `transition_in` in the server's exact
shape, the Clip's length less its transitions, the preview and the join's buttons. A
standalone `CreativeState`, handlers called through `.fn` (`test_creative_state.py`)."""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import reflex as rx
from qualify_api.creative.video_pipeline import recipe as server_recipe
from qualify_creative import schemas
from qualify_creative.effects import load_effects

from . import clip_editor_vm as vm
from . import clip_joins_vm as joins
from . import edit_sequence
from . import editor_preview_contract as contract
from .creative_state import CreativeState
from .ui import timeline as tl

_KEY = "uploads/t/clip/video.mp4"
_PHOTO = "uploads/t/clip/foto.jpg"
_SECOND = "uploads/t/clip/otro.mp4"


@pytest.fixture
def editor_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vm, "CLIP_EDITOR_ON", True)


@pytest.fixture
def joins_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(joins.JOINS_SWITCH, "on")


@pytest.fixture
def joins_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(joins.JOINS_SWITCH, raising=False)


def _state() -> CreativeState:
    """A photo (2 s), the own video (20 s: 0-15 s used) and a second video (8 s): blocks
    at 0-2, 2-17 and 17-25 s."""
    state = CreativeState()
    state.gen_category = "clip"
    state.brief_kind = "clip"
    state.clip_images = [{"key": _PHOTO, "name": "foto.jpg", "source": "upload", "role": "product"}]
    state.clip_videos = [
        {"key": _KEY, "name": "video.mp4", "source": "upload"},
        {"key": _SECOND, "name": "otro.mp4", "source": "upload"},
    ]
    state.clip_sequence = [_PHOTO, _KEY, _SECOND]
    CreativeState.report_clip_source.fn(state, _KEY, 20.0, 1080, 1920)
    CreativeState.report_clip_media.fn(state, _SECOND, 8.0, 1080, 1920)
    return state


def _ids(state: CreativeState) -> list[str]:
    return [row["id"] for row in state.clip_tl_media_rows]


def _choose(state: CreativeState, block_id: str, kind: str) -> None:
    CreativeState.open_clip_join.fn(state, block_id)
    CreativeState.set_clip_join.fn(state, kind)


def _segments(state: CreativeState) -> list[dict[str, Any]]:
    return state._clip_edit_media()["segments"]  # type: ignore[return-value]


def _library_default(effect_id: str, name: str) -> object:
    entry = load_effects().get(effect_id, 2)
    assert entry is not None
    return entry.params[name].default


# -- the switch ---------------------------------------------------------------------------


def test_the_switch_is_the_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    assert joins.JOINS_SWITCH == server_recipe.CLIP_BLOCK_TRANSITIONS_SWITCH
    monkeypatch.setenv(joins.JOINS_SWITCH, "on")
    assert joins.joins_enabled() and server_recipe.clip_block_transitions_on()
    for value in ("", "off", "1", "yes"):  # only «on» turns it on, as the server reads it
        monkeypatch.setenv(joins.JOINS_SWITCH, value)
        assert not joins.joins_enabled()
        assert joins.joins_enabled() == server_recipe.clip_block_transitions_on()
    monkeypatch.delenv(joins.JOINS_SWITCH)
    assert not joins.joins_enabled()


@pytest.mark.usefixtures("editor_on", "joins_on")
def test_switch_on_what_the_editor_sends_the_server_does_not_refuse() -> None:
    state = _state()
    _choose(state, _ids(state)[1], joins.FADE)
    _choose(state, _ids(state)[2], joins.WIPE)
    segments = _segments(state)
    part = schemas.PartRecipe(index=1, mode="local", seconds=20.0, segments=segments)
    found = server_recipe.validate_recipe((part,), video_by_parts=False)
    assert not [p for p in found if "transition" in (p.field or "") or "block" in p.code]


@pytest.mark.usefixtures("editor_on", "joins_off")
def test_switch_off_draws_no_join_and_sends_no_transition() -> None:
    state = _state()
    assert state.clip_tl_joins == []
    second = _ids(state)[1]
    CreativeState.open_clip_join.fn(state, second)
    assert state.clip_join_open == ""
    state.clip_block_joins = {second: joins.FADE}  # even a stored choice does nothing
    assert all("transition_in" not in seg for seg in _segments(state))
    assert state.clip_tl_total == "25"


# -- the default and the choices ----------------------------------------------------------


@pytest.mark.usefixtures("editor_on", "joins_on")
def test_every_join_is_corte_by_default_and_nothing_travels() -> None:
    state = _state()
    rows = state.clip_tl_joins
    assert [row["id"] for row in rows] == _ids(state)[1:]  # none before the first block
    assert {row["kind"] for row in rows} == {joins.CUT}
    assert rows[0]["name"] == "Unión entre Foto 1 y Video 2: Corte"
    assert rows[1]["name"] == "Unión entre Video 2 y Video 3: Corte"
    assert all("transition_in" not in seg for seg in _segments(state))
    # the digest's shape: a Clip with only cuts is exactly what it was
    data = state._clip_edit_media()["segments"]
    assert json.dumps(data) == json.dumps(
        contract.to_dict(contract.PartRecipe(segments=state._clip_edit_recipe().segments))[
            "segments"
        ]
    )


@pytest.mark.usefixtures("editor_on", "joins_on")
def test_a_fade_goes_in_the_contracts_exact_shape_and_never_on_block_one() -> None:
    state = _state()
    second, third = _ids(state)[1], _ids(state)[2]
    _choose(state, second, joins.FADE)
    _choose(state, third, joins.WIPE)
    segments = _segments(state)
    assert "transition_in" not in segments[0]
    assert segments[1]["transition_in"] == {
        "effect_id": "fundido",
        "version": 2,
        "params": {"duration_s": _library_default("fundido", "duration_s")},
    }
    assert segments[2]["transition_in"] == {
        "effect_id": "barrido",
        "version": 2,
        "params": {
            "direction": _library_default("barrido", "direction"),
            "duration_s": _library_default("barrido", "duration_s"),
        },
    }
    assert list(segments[1])[-1] == "transition_in"  # the contract's last field
    assert state.clip_edit_notice == "Pusiste un barrido entre Video 2 y Video 3."
    # the server reads and accepts it as it is
    part = schemas.PartRecipe(index=1, mode="local", seconds=20.0, segments=segments)
    assert server_recipe.block_transition_room_problems(part) == ()
    assert part.segments[1].transition_in is not None
    assert part.segments[0].transition_in is None


@pytest.mark.usefixtures("editor_on", "joins_on")
def test_choosing_corte_again_takes_the_transition_out() -> None:
    state = _state()
    second = _ids(state)[1]
    _choose(state, second, joins.FADE)
    CreativeState.set_clip_join.fn(state, joins.CUT)
    assert state.clip_block_joins == {}
    assert all("transition_in" not in seg for seg in _segments(state))
    assert state.clip_edit_notice == "Dejaste un corte entre Foto 1 y Video 2."


@pytest.mark.usefixtures("editor_on", "joins_on")
def test_a_kind_not_offered_is_refused() -> None:
    state = _state()
    CreativeState.open_clip_join.fn(state, _ids(state)[1])
    CreativeState.set_clip_join.fn(state, "humo_capa")
    assert state.clip_block_joins == {}


# -- the Clip's length --------------------------------------------------------------------


@pytest.mark.usefixtures("editor_on", "joins_on")
def test_the_clip_lasts_its_blocks_less_each_transition() -> None:
    state = _state()
    second, third = _ids(state)[1], _ids(state)[2]
    _choose(state, second, joins.FADE)  # 0.5 s
    _choose(state, third, joins.WIPE)  # 0.4 s
    fade = float(_library_default("fundido", "duration_s"))  # type: ignore[arg-type]
    wipe = float(_library_default("barrido", "duration_s"))  # type: ignore[arg-type]
    expected = 25.0 - fade - wipe
    assert state.clip_tl_total == f"{expected:g}"
    assert vm.recipe_seconds(state._clip_edit_recipe().segments) == pytest.approx(expected)
    # the server's own length of the same Clip
    part = schemas.PartRecipe(index=1, mode="local", seconds=20.0, segments=_segments(state))
    assert server_recipe.clip_seconds(part) == pytest.approx(expected)
    # each block starts where the server starts it (its join comes off the block before)
    rows = state.clip_tl_media_rows
    assert [float(r["start"]) for r in rows] == pytest.approx([0.0, 2.0 - fade, 17.0 - fade - wipe])
    joins_at = [float(r["at"]) for r in state.clip_tl_joins]
    # each point in the middle of its overlap (Deivid: «bloques enteros, encimados»)
    assert joins_at == pytest.approx([2.0 - fade / 2, 17.0 - fade - wipe / 2], abs=0.01)
    # the preview's clock is the same
    seq = json.loads(state.clip_seq_json)
    assert seq["total"] == pytest.approx(expected)
    assert seq["blocks"][1]["join"] == "fade" and seq["blocks"][2]["join"] == "wipe"
    assert seq["blocks"][2]["join_dir"] == _library_default("barrido", "direction")
    assert seq["blocks"][0]["join"] == ""


def test_recipe_seconds_counts_transitions_like_the_server() -> None:
    fade = joins.use_of(joins.FADE)
    segments = (
        contract.SourceSegment(_PHOTO, 0.0, 2.0, kind="photo"),
        contract.SourceSegment(_KEY, 0.0, 4.0, transition_in=fade),
    )
    data = contract.to_dict(contract.PartRecipe(segments=segments))["segments"]
    part = schemas.PartRecipe(index=1, mode="local", seconds=5.5, segments=data)
    assert vm.recipe_seconds(segments) == pytest.approx(server_recipe.clip_seconds(part))


# -- room: only «Corte» and the server's warning --------------------------------------------


def _short_photos(seconds: float) -> list[dict[str, object]]:
    return [
        {"id": f"p{n}", "key": f"uploads/t/clip/p{n}.jpg", "kind": "photo", "dur": seconds}
        for n in range(3)
    ]


def test_without_room_only_corte_is_offered() -> None:
    media = _short_photos(1.0)  # 30 frames each
    segments = vm.timeline_segments(media)
    assert joins.options(segments, 1, local=True) == (joins.CUT, joins.FADE, joins.WIPE)
    # the middle photo's other join at the library's longest: no default fits beside it
    longest = joins.specs()[joins.FADE].max_s
    long_fade = contract.EffectUse("fundido", 2, params=(("duration_s", longest),))
    taken = (*segments[:2], dataclasses.replace(segments[2], transition_in=long_fade))
    server_part = joins._server_part(taken)
    room = server_recipe.block_transition_room_s(server_part, 1)
    assert room < min(spec.duration_s for spec in joins.specs().values())
    assert joins.options(taken, 1, local=True) == (joins.CUT,)


def _fast_middle() -> list[dict[str, object]]:
    """A photo, 2 s of a video at ×10 (0,2 s: 6 frames) with a fade into it, a photo."""
    media: list[dict[str, object]] = [
        {"id": "p0", "key": "uploads/t/clip/p0.jpg", "kind": "photo", "dur": 3.0},
        {"id": "v1", "key": _KEY, "kind": "video", "src_start": 0.0, "src_end": 2.0,
         "src_len": 20.0, "speed": 10.0},
        {"id": "p2", "key": "uploads/t/clip/p2.jpg", "kind": "photo", "dur": 3.0},
    ]  # fmt: skip
    return joins.apply_joins(media, {"v1": joins.FADE}, enabled=True, local=True)


def test_a_block_too_short_shows_the_servers_words_and_stops_crear() -> None:
    media = _fast_middle()
    segments = vm.timeline_segments(media)
    words = server_recipe.transitions_longer_than_block_text(2)
    assert joins.room_problems(segments) == {1: words}
    assert vm.recipe_problem(contract.PartRecipe(segments=segments)) == (words, "warn")
    rows = joins.join_rows(media, segments, local=True, starts=[0.0, 2.5, 2.7])
    assert rows[0]["warn"] == "1" and rows[0]["problem"] == words
    assert rows[1]["warn"] == "1"  # the join after the short block touches it too
    assert joins.option_rows(rows[0]) == [{"value": joins.CUT, "label": "Corte"}]
    # the server refuses the same recipe with the same code
    data = contract.to_dict(contract.PartRecipe(segments=segments))["segments"]
    part = schemas.PartRecipe(index=1, mode="local", seconds=5.0, segments=data)
    codes = [p.code for p in server_recipe.block_transition_room_problems(part)]
    assert codes == ["transitions_longer_than_block"]


# -- a Clip not made here, and the avatar -------------------------------------------------


def test_a_clip_not_made_here_offers_only_corte_and_carries_none() -> None:
    media = _short_photos(3.0)
    segments = vm.timeline_segments(media)
    assert joins.options(segments, 1, local=False) == (joins.CUT,)
    applied = joins.apply_joins(media, {"p1": joins.FADE}, enabled=True, local=False)
    assert all("join" not in item and "tail_s" not in item for item in applied)
    assert all(s.transition_in is None for s in vm.timeline_segments(applied))


def test_a_join_beside_an_avatar_block_stays_corte() -> None:
    media = _short_photos(3.0)
    media[1] = {**media[1], "kind": joins.AVATAR_KIND}
    segments = vm.timeline_segments(_short_photos(3.0))
    kinds = [str(item["kind"]) for item in media]
    assert joins.options(segments, 1, local=True, kinds=kinds) == (joins.CUT,)
    assert joins.options(segments, 2, local=True, kinds=kinds) == (joins.CUT,)
    chosen = {"p1": joins.FADE, "p2": joins.WIPE}
    applied = joins.apply_joins(media, chosen, enabled=True, local=True)
    assert all("join" not in item for item in applied)


# -- reordering and removing ---------------------------------------------------------------


@pytest.mark.usefixtures("editor_on", "joins_on")
def test_a_block_moved_first_takes_no_transition_with_it() -> None:
    state = _state()
    second = _ids(state)[1]
    _choose(state, second, joins.FADE)
    CreativeState.drop_clip_block.fn(state, second, "move", 0)
    assert _ids(state)[0] == second
    assert state.clip_block_joins == {}
    assert all("transition_in" not in seg for seg in _segments(state))
    assert [row["kind"] for row in state.clip_tl_joins] == [joins.CUT, joins.CUT]


def test_clean_joins_keeps_only_blocks_after_the_first() -> None:
    media = _short_photos(3.0)
    kept = joins.clean_joins({"p0": joins.FADE, "p2": joins.WIPE, "gone": joins.FADE}, media)
    assert kept == {"p2": joins.WIPE}


# -- the time it takes ---------------------------------------------------------------------


@pytest.mark.usefixtures("editor_on", "joins_on")
def test_the_video_takes_longer_only_with_a_join_and_says_how_much() -> None:
    state = _state()
    second, third = _ids(state)[1], _ids(state)[2]

    def words(n: int) -> str:
        return f"Con las uniones que elegiste, tu video tarda unos {n} minutos más en estar listo."

    assert state.clip_join_hint == joins.FIND_HINT  # how to find them, at first
    CreativeState.open_clip_join.fn(state, second)
    assert state.clip_join_chosen["slower"] == "" and state.clip_join_slower == ""
    CreativeState.set_clip_join.fn(state, joins.FADE)
    # never twice: with the panel open only the panel says it
    assert state.clip_join_chosen["slower"] == words(6) and state.clip_join_slower == ""
    assert state.clip_join_hint == ""  # gone with the first join chosen
    CreativeState.close_clip_join.fn(state)
    assert state.clip_join_slower == words(6)  # closed: under the timeline
    _choose(state, third, joins.WIPE)  # two joins: the whole Clip's time, in the panel too
    assert state.clip_join_chosen["slower"] == words(7) and state.clip_join_slower == ""
    CreativeState.close_clip_join.fn(state)
    assert state.clip_join_slower == words(7)
    for block in (second, third):
        _choose(state, block, joins.CUT)
    CreativeState.close_clip_join.fn(state)
    assert state.clip_join_slower == "" and state.clip_join_hint == ""


def test_the_extra_minutes_follow_the_servers_measure() -> None:
    # #804: about 5 min once per video with a join that is not «Corte», plus ~1 per join
    assert joins.extra_minutes([]) is None
    assert joins.extra_minutes([joins.CUT, joins.CUT]) is None
    assert joins.slower_line([joins.CUT]) == ""
    assert joins.extra_minutes([joins.FADE]) == 6
    assert joins.extra_minutes([joins.WIPE, joins.CUT, joins.WIPE]) == 7
    assert joins.extra_minutes([joins.FADE] * 4 + [joins.WIPE] * 3) == 12
    assert "unos 12 minutos" in joins.slower_line([joins.FADE] * 7)
    source = Path(joins.__file__).read_text("utf-8")
    assert "6 minutos" not in source and "9 minutos" not in source


@pytest.mark.usefixtures("editor_on", "joins_on")
def test_the_hint_waits_for_two_blocks() -> None:
    state = _state()
    state.clip_images = []
    state.clip_videos = [{"key": _KEY, "name": "video.mp4", "source": "upload"}]
    state.clip_sequence = [_KEY]
    assert state.clip_tl_joins == [] and state.clip_join_hint == ""


@pytest.mark.usefixtures("editor_on", "joins_on")
def test_a_block_chosen_closes_the_join() -> None:
    state = _state()
    second = _ids(state)[1]
    CreativeState.open_clip_join.fn(state, second)
    assert state.clip_join_open == second
    CreativeState.select_clip_block.fn(state, second)
    assert state.clip_join_open == ""
    CreativeState.open_clip_join.fn(state, second)
    assert state.clip_tl_selected == ""


@pytest.mark.usefixtures("editor_on", "joins_on")
def test_escape_closes_the_join_like_listo_and_the_focus_goes_back_to_its_point() -> None:
    state = _state()
    second = _ids(state)[1]
    CreativeState.open_clip_join.fn(state, second)
    # Escape in the join's panel: the script reports it with edge «join»
    assert CreativeState.clip_block_key.fn(state, second, "join", "Escape") == []
    assert state.clip_join_open == "" and state.clip_tl_selected == ""
    # «Listo»: it closes and asks the script to focus that join's point
    CreativeState.open_clip_join.fn(state, second)
    events = CreativeState.close_clip_join.fn(state)
    assert state.clip_join_open == ""
    assert "focusJoin" in str(events) and second in str(events)
    assert CreativeState.close_clip_join.fn(state) == []  # nothing open: nothing to do
    # the script: Escape in `[data-tl-join-panel]` focuses `[data-join-id]` and reports
    script = (Path(__file__).parent.parent / "assets" / "timeline.js").read_text("utf-8")
    escape = script.split('closest("[data-tl-join-panel]")', 1)[1].split("var root", 1)[0]
    assert 'e.key === "Escape"' in escape and "preventDefault" in escape
    assert (
        "joinById(jid, joinOwner)" in escape
        and 'report(joinOwner, jid, "join", "Escape")' in escape
    )
    assert "focusJoin: focusJoin" in script and "data-join-id" in script


# -- the ranges come from the library ------------------------------------------------------


def test_the_durations_are_the_librarys() -> None:
    library = load_effects()
    for kind in (joins.FADE, joins.WIPE):
        spec = joins.specs()[kind]
        entry = library.get(kind, spec.version)
        assert entry is not None
        assert (spec.version, kind) in {(v, i) for (i, v) in server_recipe.DRAWN_TRANSITIONS}
        assert spec.duration_s == entry.params["duration_s"].default
        assert (spec.min_s, spec.max_s) == server_recipe.transition_duration_range(kind)
        assert spec.min_s <= spec.duration_s <= spec.max_s


def test_the_contract_reads_back_a_transition() -> None:
    fade = joins.use_of(joins.FADE)
    recipe = contract.PartRecipe(
        segments=(
            contract.SourceSegment(_PHOTO, 0.0, 2.0, kind="photo"),
            contract.SourceSegment(_KEY, 0.0, 4.0, transition_in=fade),
        )
    )
    again = contract.from_dict(contract.to_dict(recipe))
    assert again.segments[1].transition_in == fade
    assert again.segments[0].transition_in is None
    cut = {"effect_id": "corte", "version": 1, "params": {}}
    raw = contract.to_dict(recipe)
    raw["segments"][1]["transition_in"] = cut  # type: ignore[index]
    assert contract.from_dict(raw).segments[1].transition_in is None


# -- the buttons ---------------------------------------------------------------------------


def test_each_join_renders_as_a_named_button() -> None:
    rows = joins.join_rows(
        _short_photos(3.0),
        vm.timeline_segments(_short_photos(3.0)),
        local=True,
        starts=[0.0, 3.0, 6.0],
    )
    assert [row["name"] for row in rows] == [
        "Unión entre Foto 1 y Foto 2: Corte",
        "Unión entre Foto 2 y Foto 3: Corte",
    ]
    assert [row["at"] for row in rows] == ["3", "6"]
    rendered = str(
        tl._joins(
            rx.Var.create(rows),  # type: ignore[arg-type]
            lambda block: rx.console_log(block),
            rx.Var.create(""),
        ).render()
    )
    assert "q-tl__join" in rendered and '"button"' in rendered
    assert "aria-label" in rendered or "ariaLabel" in rendered
    assert "aria-expanded" in rendered or "ariaExpanded" in rendered
    panel = str(
        tl.timeline_join_panel(
            rx.Var.create(rows[0]),  # type: ignore[arg-type]
            rx.Var.create(joins.option_rows(rows[0])),  # type: ignore[arg-type]
            on_change=lambda value: rx.console_log(value),
            on_done=rx.console_log("done"),
            help_text=joins.HELP,
        ).render()
    )
    assert "q-source-seg" in panel and "Listo" in panel
    # the CSS: a target 44 px tall, 24 px wide (WCAG 2.5.8), however small the dot
    css = (Path(__file__).parent.parent / "assets" / "qualify-creative.css").read_text("utf-8")
    block = css.split(".q-tl__join {", 1)[1].split("}", 1)[0]
    assert "width: 24px" in block and "height: 44px" in block
    assert "position: absolute" in block and "margin: 0;" in block
    assert ".q-tl__join:focus-visible" in css
    assert '.q-tl__join[data-join-off="1"] { visibility: hidden;' in css


def _page(joins_rows: list[dict[str, str]] | None, selected: str = "") -> str:
    extra: dict[str, Any] = {}
    if joins_rows is not None:
        extra = {
            "joins": rx.Var.create(joins_rows).to(list[dict[str, str]]),
            "on_join": lambda block: rx.console_log(block),
        }
    return str(
        tl.timeline(
            media=rx.Var.create([]).to(list[dict[str, str]]),  # type: ignore[arg-type]
            texts=rx.Var.create([]).to(list[dict[str, str]]),  # type: ignore[arg-type]
            effects=rx.Var.create([]).to(list[dict[str, str]]),  # type: ignore[arg-type]
            ticks=rx.Var.create([]).to(list[dict[str, str]]),  # type: ignore[arg-type]
            total="9",
            selected=rx.Var.create(selected),
            on_select=lambda block: rx.console_log(block),
            **extra,
        ).render()
    )


def _names(page: str) -> str:
    return page.split("q-tl__names", 1)[1].split("q-tl__scroller", 1)[0]


def test_the_joins_move_no_track() -> None:
    """Deivid 2026-11-26 («las pistas se mueven hacia abajo»): with joins or without,
    the timeline has the same tracks in the same order and the same names column — the
    joins lie over the media track (absolute, no height, no margin)."""
    media = _short_photos(3.0)
    rows = joins.join_rows(media, vm.timeline_segments(media), local=True, starts=[0, 3, 6])
    plain, joined, empty = _page(None), _page(rows), _page([])
    assert _names(plain) == _names(joined) == _names(empty)
    assert "q-tl__name--joins" not in joined
    tracks = ("q-tl__ruler", "q-tl__scrub", "q-tl__lane--media", "q-tl__lane--text")
    for page in (plain, joined, empty):
        at = [page.index(track) for track in tracks]
        assert at == sorted(at)
    # the joins sit INSIDE the media track's box, before the text track begins
    assert joined.index("q-tl__media") < joined.index("q-tl__lane--media")
    assert joined.index("q-tl__lane--media") < joined.index("q-tl__joins")
    assert joined.index("q-tl__joins") < joined.index("q-tl__lane--text")
    css = (Path(__file__).parent.parent / "assets" / "qualify-creative.css").read_text("utf-8")
    layer = css.split(".q-tl__joins {", 1)[1].split("}", 1)[0]
    assert "position: absolute" in layer and "inset: 0" in layer
    assert "height" not in layer and "margin" not in layer
    box = css.split(".q-tl__media {", 1)[1].split("}", 1)[0]
    assert box.strip() == "position: relative;"  # no height, padding nor margin of its own
    assert ".q-tl__name--joins" not in css


def test_a_chosen_blocks_handles_win_over_its_joins() -> None:
    media = _short_photos(3.0)
    rows = joins.join_rows(media, vm.timeline_segments(media), local=True, starts=[0, 3, 6])
    assert [(row["before"], row["id"]) for row in rows] == [("p0", "p1"), ("p1", "p2")]
    page = _page(rows, selected="p1")
    assert "data-join-off" in page


def test_the_preview_sequence_takes_the_join() -> None:
    media = joins.apply_joins(_short_photos(3.0), {"p1": joins.FADE}, enabled=True, local=True)
    seq = edit_sequence.from_timeline(media, [], {})
    fade = joins.overlap_s(joins.use_of(joins.FADE))
    assert seq.blocks[0].out_end == pytest.approx(3.0 - fade)
    assert seq.blocks[1].join == "fade" and seq.blocks[1].join_s == pytest.approx(fade)
    assert seq.total == pytest.approx(9.0 - fade)


# -- the preview's script (node) -----------------------------------------------------------

_NODE = shutil.which("node")


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_the_preview_draws_a_fade_and_a_wipe_in_their_first_seconds() -> None:
    core = Path(__file__).parent.parent / "assets" / "edit-sequence-core.js"
    script = (
        f"const c = require({json.dumps(str(core))});\n"
        "const fade = {out_start: 2, join: 'fade', join_s: 0.5};\n"
        "const wipe = {out_start: 2, join: 'wipe', join_s: 0.4, join_dir: 'left'};\n"
        "console.log(JSON.stringify([\n"
        "  c.joinFrame(fade, 2.25, false), c.joinFrame(fade, 2.6, false),\n"
        "  c.joinFrame(fade, 2.25, true), c.joinFrame(wipe, 2.2, false),\n"
        "  c.joinFrame({out_start: 0}, 0.1, false)]));\n"
    )
    out = subprocess.run(
        [str(_NODE)], input=script, capture_output=True, text=True, timeout=30, check=True
    )
    half, done, still, wiping, cut = json.loads(out.stdout)
    assert half == {"a": 0.5, "clip": ""}
    assert done == still == cut == {"a": 1, "clip": ""}
    assert wiping == {"a": 1, "clip": "inset(0 0 0 50%)"}


# -- Deivid 2026-11-26: the duration bar and the wipe's direction --------------------------


def _three_photos(first: float, middle: float, last: float) -> list[dict[str, object]]:
    return [
        {"id": f"p{n}", "key": f"uploads/t/clip/p{n}.jpg", "kind": "photo", "dur": dur}
        for n, dur in enumerate((first, middle, last))
    ]


def test_offered_when_the_shortest_fits_and_it_starts_at_the_longest_that_fits() -> None:
    wipe = joins.specs()[joins.WIPE]
    fade = joins.specs()[joins.FADE]
    # the middle photo (1 s) already gives the next join a wipe at its default: the join
    # before it keeps less than the fade's default, but more than the range's shortest
    media = joins.apply_joins(
        _three_photos(3.0, 1.0, 3.0), {"p2": joins.WIPE}, enabled=True, local=True
    )
    segments = vm.timeline_segments(media)
    assert joins.options(segments, 1, local=True) == (joins.CUT, joins.FADE, joins.WIPE)
    fit = joins.fit_seconds(segments, 1, joins.FADE)
    assert fit is not None and fade.min_s <= fit < fade.duration_s
    assert joins.start_seconds(joins.FADE, fit) == fit
    # with room, the library's default
    roomy = vm.timeline_segments(_three_photos(3.0, 3.0, 3.0))
    start = joins.start_seconds(joins.FADE, joins.fit_seconds(roomy, 1, joins.FADE))
    assert start == fade.duration_s
    assert wipe.directions == ("left", "right", "up", "down")


@pytest.mark.usefixtures("editor_on", "joins_on")
def test_the_bar_changes_the_duration_the_length_and_the_request() -> None:
    state = _state()
    second = _ids(state)[1]
    _choose(state, second, joins.FADE)
    spec = joins.specs()[joins.FADE]
    assert state.clip_join_seconds_value == spec.duration_s
    assert state.clip_join_seconds_min == spec.min_s
    assert state.clip_join_seconds_max == spec.max_s
    assert state.clip_join_chosen["seconds_line"] == "Dura 0,5 s"
    CreativeState.set_clip_join_seconds.fn(state, [0.74])  # snapped to the 0,1 s grid
    assert state.clip_join_seconds == {second: 0.7}
    assert _segments(state)[1]["transition_in"]["params"] == {"duration_s": 0.7}
    assert state.clip_tl_total == "24.3"  # 25 s less 0,7 s
    assert json.loads(state.clip_seq_json)["blocks"][1]["join_s"] == pytest.approx(0.7)
    assert state.clip_edit_notice == (
        "La unión entre Foto 1 y Video 2 dura 0,7 s. Tu video queda 0,7 s más corto."
    )
    CreativeState.set_clip_join_seconds.fn(state, [5.0])  # never past the range
    assert state.clip_join_seconds == {second: spec.max_s}
    CreativeState.set_clip_join_seconds.fn(state, [0.0])
    assert state.clip_join_seconds == {second: spec.min_s}


def test_the_bar_never_goes_past_what_fits() -> None:
    media = joins.apply_joins(
        _three_photos(3.0, 1.0, 3.0),
        {"p1": joins.FADE, "p2": joins.WIPE},
        enabled=True,
        local=True,
        seconds={"p1": 0.3},
    )
    segments = vm.timeline_segments(media)
    rows = joins.join_rows(media, segments, local=True, starts=[0.0, 2.7, 3.3])
    fit = float(rows[0]["fit"])
    assert float(rows[0]["seconds_max"]) == fit < joins.specs()[joins.FADE].max_s


@pytest.mark.usefixtures("editor_on", "joins_on")
def test_a_wipe_takes_the_owners_direction() -> None:
    state = _state()
    second = _ids(state)[1]
    _choose(state, second, joins.WIPE)
    assert [d["value"] for d in state.clip_join_directions] == ["left", "right", "up", "down"]
    labels = [d["label"] for d in state.clip_join_directions]
    assert labels == ["Izquierda", "Derecha", "Arriba", "Abajo"]
    assert state.clip_join_chosen["direction"] == "left"  # the library's default
    CreativeState.set_clip_join_direction.fn(state, "up")
    assert _segments(state)[1]["transition_in"]["params"]["direction"] == "up"
    assert json.loads(state.clip_seq_json)["blocks"][1]["join_dir"] == "up"
    assert state.clip_edit_notice == "Video 2 entra hacia arriba."
    CreativeState.set_clip_join_direction.fn(state, "diagonal")  # not the library's
    assert state.clip_join_dirs == {second: "up"}
    # a fade has no direction, and back to «Corte» forgets both
    CreativeState.set_clip_join.fn(state, joins.FADE)
    assert state.clip_join_directions == []
    assert "direction" not in _segments(state)[1]["transition_in"]["params"]
    CreativeState.set_clip_join.fn(state, joins.CUT)
    assert state.clip_join_seconds == {} and state.clip_join_dirs == {}


def test_the_panel_renders_the_bar_and_the_named_direction_group() -> None:
    media = joins.apply_joins(
        _three_photos(3.0, 3.0, 3.0), {"p1": joins.WIPE}, enabled=True, local=True
    )
    row = joins.join_rows(media, vm.timeline_segments(media), local=True, starts=[0, 3, 6])[0]
    panel = str(
        tl.timeline_join_panel(
            rx.Var.create(row),  # type: ignore[arg-type]
            rx.Var.create(joins.option_rows(row)),  # type: ignore[arg-type]
            on_change=lambda value: rx.console_log(value),
            on_done=rx.console_log("done"),
            help_text=joins.HELP,
            seconds=0.4,
            seconds_min=0.3,
            seconds_max=0.8,
            on_seconds=lambda value: rx.console_log(value),
            directions=rx.Var.create(joins.direction_rows(row)),  # type: ignore[arg-type]
            on_direction=lambda value: rx.console_log(value),
        ).render()
    )
    assert "Slider" in panel or "slider" in panel
    assert row["direction_title"] == "Hacia dónde se mueve Foto 2"
    assert "arrow-left" in panel.lower() or "ArrowLeft" in panel or "arrow_left" in panel.lower()
    assert row["seconds_label"] == "Duración del barrido"
    assert row["seconds_line"] == "Dura 0,4 s"
    assert [d["icon"] for d in joins.direction_rows(row)] == [
        "arrow-left",
        "arrow-right",
        "arrow-up",
        "arrow-down",
    ]


# -- the reviews of 2026-11-26 --------------------------------------------------------------


def _part(segments: tuple[contract.SourceSegment, ...]) -> schemas.PartRecipe:
    data = contract.to_dict(contract.PartRecipe(segments=segments))["segments"]
    return schemas.PartRecipe(index=1, mode="local", seconds=1.0, segments=data)


def test_the_length_is_judged_as_the_server_judges_it() -> None:
    longest = contract.EffectUse(
        "fundido", 2, params=(("duration_s", joins.specs()[joins.FADE].max_s),)
    )
    cases = {
        # two blocks of 30,3 s with a fade: 60,6 s laid end to end, over 60 s
        "over": (
            contract.SourceSegment(_KEY, 0.0, 30.3),
            contract.SourceSegment(_SECOND, 0.0, 30.3, transition_in=longest),
        ),
        # 59 s laid, under 60 s even before the fade takes its seconds off
        "inside": (
            contract.SourceSegment(_KEY, 0.0, 30.0),
            contract.SourceSegment(_SECOND, 0.0, 29.0, transition_in=longest),
        ),
        # 3,2 s laid, under 3 s once the fade takes its seconds off
        "under": (
            contract.SourceSegment(_PHOTO, 0.0, 1.6, kind="photo"),
            contract.SourceSegment(_KEY, 0.0, 1.6, transition_in=longest),
        ),
    }
    for name, segments in cases.items():
        server = [
            p
            for p in server_recipe._length_problems(_part(segments), None, in_clip=True)
            if p.code == "local_length_out_of_range"
        ]
        words, _ = vm.recipe_problem(contract.PartRecipe(segments=segments))
        screen = "Tu video dura" in words
        assert screen == bool(server), name
        if server:
            assert f"{server[0].duration_s:g}".replace(".", ",") in words, name


@pytest.mark.usefixtures("editor_on", "joins_on")
def test_a_block_taken_out_takes_its_join_and_closes_its_panel() -> None:
    state = _state()
    photo, second, third = _ids(state)
    _choose(state, second, joins.FADE)
    _choose(state, third, joins.WIPE)
    CreativeState.open_clip_join.fn(state, third)
    # the photo (first) goes with its ✕: the own video is first now — its join goes
    CreativeState.remove_clip_image.fn(state, _PHOTO)
    assert _ids(state)[0] == second
    assert state.clip_block_joins == {third: joins.WIPE}
    assert set(state.clip_join_seconds) == {third}
    CreativeState.open_clip_join.fn(state, third)  # (open again: its block is there)
    assert state.clip_join_open == third
    # the second video goes: the open join's block is gone, its panel closes
    CreativeState.remove_clip_video.fn(state, _SECOND)
    assert state.clip_block_joins == {} and state.clip_join_open == ""
    assert photo not in _ids(state)


def test_a_block_of_no_length_neither_joins_nor_shifts_the_numbers() -> None:
    media: list[dict[str, object]] = [
        {"id": "p0", "key": "uploads/t/clip/p0.jpg", "kind": "photo", "dur": 3.0},
        {"id": "p1", "key": "uploads/t/clip/p1.jpg", "kind": "photo", "dur": 0.0},
        {"id": "p2", "key": "uploads/t/clip/p2.jpg", "kind": "photo", "dur": 3.0},
    ]
    assert joins.segment_ids(media) == ["p0", "p2"]
    applied = joins.apply_joins(media, {"p2": joins.FADE}, enabled=True, local=True)
    fade = joins.overlap_s(joins.use_of(joins.FADE))
    assert applied[0]["tail_s"] == pytest.approx(fade)  # the block before it that has length
    assert "tail_s" not in applied[1]
    segments = vm.timeline_segments(applied)
    assert len(segments) == 2 and segments[1].transition_in is not None
    rows = joins.join_rows(applied, segments, local=True, starts=[0.0, 3.0, 3.0])
    assert [row["id"] for row in rows] == ["p2"]
    assert rows[0]["name"] == "Unión entre Foto 1 y Foto 3: Fundido"
    assert rows[0]["offered"] == ",".join((joins.CUT, joins.FADE, joins.WIPE))
    assert joins.clean_joins({"p1": joins.FADE, "p2": joins.FADE}, media) == {"p2": joins.FADE}


@pytest.mark.usefixtures("editor_on", "joins_on")
def test_opening_a_join_brings_its_panel_into_view_with_the_focus_on_the_choice() -> None:
    state = _state()
    events = CreativeState.open_clip_join.fn(state, _ids(state)[1])
    assert "revealJoin" in str(events)
    script = (Path(__file__).parent.parent / "assets" / "timeline.js").read_text("utf-8")
    reveal = script.split("function revealJoin", 1)[1].split("\n  }\n", 1)[0]
    assert "scrollIntoView" in reveal and '[role="radio"]' in reveal and ".focus(" in reveal
    # Escape on the open join's own point closes it too, and points are found inside
    # their own timeline
    assert '[data-join-id][aria-expanded="true"]' in script
    assert "function joinById(id, root)" in script
    # the duration bar's thumb says «0,5 segundos»
    assert '" segundos"' in script and "aria-valuetext" in script


_FAKE_DOM = """
const attrs = (o) => ({
  a: o, getAttribute: function (k) { return k in this.a ? String(this.a[k]) : null; },
  setAttribute: function (k, v) { this.a[k] = v; },
});
const thumb = attrs({"aria-valuenow": "0.5"});
const radio = Object.assign(attrs({}), {focused: false, focus() { this.focused = true; }});
const panel = Object.assign(attrs({"data-tl-join-panel": "b2"}), {
  scrollIntoView() {}, focus() {},
  querySelector(sel) { return sel.includes("aria-checked") ? radio : null; },
  querySelectorAll(sel) { return sel.includes("data-join-seconds") ? [thumb] : []; },
});
const watches = [];
global.window = global;
global.MutationObserver = class {
  constructor(cb) { this.cb = cb; watches.push(this); }
  observe(target, options) { this.target = target; this.options = options; }
  disconnect() {}
};
global.requestAnimationFrame = (f) => 0;
global.document = {
  addEventListener() {}, querySelector() { return null; },
  querySelectorAll(sel) { return sel.includes("data-tl-join-panel") ? [panel] : []; },
};
"""


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_the_bar_says_its_seconds_as_the_state_comes_back() -> None:
    timeline = Path(__file__).parent.parent / "assets" / "timeline.js"
    script = (
        _FAKE_DOM
        + f"require({json.dumps(str(timeline))});\n"
        + "window.__qTimeline.revealJoin('b2');\n"
        + "const first = thumb.getAttribute('aria-valuetext');\n"
        + "thumb.setAttribute('aria-valuenow', '0.7');\n"
        + "watches.forEach((w) => w.cb([]));\n"
        + "window.__qTimeline.revealJoin('b2');  // opened again: one watch only\n"
        + "console.log(JSON.stringify({first, then: thumb.getAttribute('aria-valuetext'),"
        + " focused: radio.focused, count: watches.length,"
        + " filter: watches[0].options.attributeFilter, sub: watches[0].options.subtree}));\n"
    )
    out = subprocess.run(
        [str(_NODE)], input=script, capture_output=True, text=True, timeout=30, check=True
    )
    got = json.loads(out.stdout)
    assert got == {
        "first": "0,5 segundos",
        "then": "0,7 segundos",
        "focused": True,
        "count": 1,
        "filter": ["aria-valuenow"],
        "sub": True,
    }


# -- Deivid's test (2026-11-26): «hay un corte antes de las transiciones» -------------------

_PREVIEW_DOM = """
global.window = global;
let reduced = false;
global.matchMedia = () => ({ matches: reduced });
global.setTimeout = () => 0; global.clearTimeout = () => {};
global.requestAnimationFrame = () => 0;
global.performance = { now: () => 0 };
class El {
  constructor(a) { this.a = Object.assign({}, a); this.style = {}; this.paused = true;
    this.readyState = 4; this.currentTime = 0; this.loads = 0; this.seeks = 0;
    this.textContent = ""; }
  getAttribute(k) { return k in this.a ? String(this.a[k]) : null; }
  setAttribute(k, v) { this.a[k] = String(v); }
  removeAttribute(k) { delete this.a[k]; }
  hasAttribute(k) { return k in this.a; }
  toggleAttribute(k, on) { if (on) this.a[k] = ""; else delete this.a[k]; return on; }
  play() { this.paused = false; return Promise.resolve(); }
  pause() { this.paused = true; }
  load() { this.loads += 1; }
  closest() { return null; }
}
function seekable(v) {
  let now = 0;
  Object.defineProperty(v, "currentTime", {
    get() { return now; }, set(x) { now = x; v.seeks += 1; },
  });
  return v;
}
function makeHost(seq) {
  const els = {
    a: seekable(new El({"data-edit-seq-video": "a"})),
    b: seekable(new El({"data-edit-seq-video": "b"})),
    photo: new El({"data-edit-seq-photo": ""}),
    under: new El({"data-edit-seq-under": ""}),
    card: new El({"data-edit-seq-card": ""}),
  };
  const one = {
    "[data-edit-seq-photo]": els.photo, "[data-edit-seq-under]": els.under,
    "[data-edit-seq-card]": els.card,
    'video[data-edit-seq-video="a"]': els.a, 'video[data-edit-seq-video="b"]': els.b,
  };
  const host = new El({"data-edit-seq": JSON.stringify(seq)});
  host.querySelector = (s) => one[s] || null;
  host.querySelectorAll = (s) => s.includes("data-edit-seq-video")
    ? [els.a, els.b, els.photo, els.card] : [];
  host.els = els; host.isConnected = true; host.contains = () => true;
  return host;
}
global.document = { addEventListener() {}, querySelectorAll() { return []; },
  querySelector() { return null; } };
"""


def _run_preview(sequence: str, body: str) -> Any:
    assets = Path(__file__).parent.parent / "assets"
    script = (
        _PREVIEW_DOM
        + f"require({json.dumps(str(assets / 'edit-sequence-core.js'))});\n"
        + f"require({json.dumps(str(assets / 'edit-preview.js'))});\n"
        + "const P = window.__qEditPreview.seq;\n"
        + f"const SEQ = {sequence};\n"
        + "const snap = (e) => ({on: e.hasAttribute('data-on'),"
        + " under: e.hasAttribute('data-under'),"
        + " paused: e.paused, t: e.currentTime, seeks: e.seeks, loads: e.loads,"
        + " src: e.getAttribute('src'), op: e.style.opacity || '',"
        + " clip: e.style.clipPath || ''});\n"
        + f"console.log(JSON.stringify((() => {{ {body} }})()));\n"
    )
    out = subprocess.run(
        [str(_NODE)], input=script, capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(out.stdout)


def _two_pieces_with_a_fade() -> str:
    """Two pieces of ONE video (0-4 s and 4-8 s of `a.mp4`), a fade into the second."""
    media: list[dict[str, object]] = [
        {"id": "v1", "key": "a", "kind": "video", "src_start": 0.0, "src_end": 4.0,
         "src_len": 8.0},
        {"id": "v2", "key": "a", "kind": "video", "src_start": 4.0, "src_end": 8.0,
         "src_len": 8.0},
    ]  # fmt: skip
    applied = joins.apply_joins(media, {"v2": joins.FADE}, enabled=True, local=True)
    return edit_sequence.from_timeline(applied, [], {"a": "/a.mp4"}).to_json()


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_the_preview_plays_both_blocks_through_a_fade_with_no_cut_before_it() -> None:
    fade = joins.specs()[joins.FADE].duration_s
    start = 4.0 - fade  # where the second piece starts on the clock
    got = _run_preview(
        _two_pieces_with_a_fade(),
        f"""
        const host = makeHost(SEQ); const {{a, b}} = host.els;
        P.load(host); const st = P.state(host); st.playing = true;
        st.t = 3.0; P.show(host, true);
        const before = {{a: snap(a), b: snap(b)}};
        // the first piece plays up to its span's end: the clock moves to the second
        a.currentTime = {start}; const seeksA = a.seeks;
        st.t = {start}; P.show(host, true);
        const at = {{a: snap(a), b: snap(b), seeksA}};
        st.t = {start + fade / 2}; P.paint(host);
        const middle = {{a: snap(a), b: snap(b)}};
        st.t = {start + fade + 0.05}; P.paint(host);
        const after = {{a: snap(a), b: snap(b)}};
        return {{before, at, middle, after}};
        """,
    )
    # before the join: the second piece is already loaded and waiting in the other
    # player at its first second — nothing to load or seek when it comes in
    assert got["before"]["a"]["on"] and not got["before"]["a"]["paused"]
    assert got["before"]["b"]["src"] == "/a.mp4" and got["before"]["b"]["t"] == 4.0
    assert not got["before"]["b"]["on"]
    # at the join: BOTH show — the first goes on under (playing, not seeked, not hidden),
    # the second plays over it in its own player
    at = got["at"]
    assert at["b"]["on"] and not at["b"]["under"] and not at["b"]["paused"]
    assert at["a"]["on"] and at["a"]["under"] and not at["a"]["paused"]
    assert at["a"]["seeks"] == at["seeksA"]  # no seek of the block going out
    assert at["a"]["loads"] == 1 and at["b"]["loads"] == 1  # no new load of either
    # half way: the second at half opacity over the first, which is fully shown
    assert got["middle"]["b"]["op"] == "0.5" and got["middle"]["a"]["op"] == ""
    assert got["middle"]["a"]["on"] and not got["middle"]["a"]["paused"]
    # after the fade: only the second
    assert not got["after"]["a"]["on"] and got["after"]["a"]["paused"]
    assert got["after"]["b"]["on"] and got["after"]["b"]["op"] == ""


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_with_reduced_motion_the_join_is_a_clean_cut() -> None:
    start = 4.0 - joins.specs()[joins.FADE].duration_s
    got = _run_preview(
        _two_pieces_with_a_fade(),
        f"""
        reduced = true;
        const host = makeHost(SEQ); const {{a, b}} = host.els;
        P.load(host); const st = P.state(host); st.playing = true;
        st.t = 3.0; P.show(host, true);
        st.t = {start}; P.show(host, true);
        return {{a: snap(a), b: snap(b)}};
        """,
    )
    shown = [name for name in ("a", "b") if got[name]["on"]]
    assert len(shown) == 1 and got[shown[0]]["op"] == "" and not got[shown[0]]["under"]


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_a_photo_stays_under_the_photo_that_wipes_in() -> None:
    applied = joins.apply_joins(
        _three_photos(3.0, 3.0, 3.0), {"p1": joins.WIPE}, enabled=True, local=True
    )
    sources = {f"uploads/t/clip/p{n}.jpg": f"/p{n}.jpg" for n in range(3)}
    wipe = joins.specs()[joins.WIPE].duration_s
    start = 3.0 - wipe
    got = _run_preview(
        edit_sequence.from_timeline(applied, [], sources).to_json(),
        f"""
        const host = makeHost(SEQ); const {{photo, under}} = host.els;
        P.load(host); const st = P.state(host); st.playing = true;
        st.t = 1.0; P.show(host, true);
        st.t = {start + wipe / 2}; P.show(host, true);
        const middle = {{photo: snap(photo), under: snap(under)}};
        st.t = {start + wipe + 0.05}; P.paint(host);
        return {{middle, after: {{photo: snap(photo), under: snap(under)}}}};
        """,
    )
    middle = got["middle"]
    assert middle["under"]["on"] and middle["under"]["src"] == "/p0.jpg"
    assert middle["photo"]["on"] and middle["photo"]["src"] == "/p1.jpg"
    assert middle["photo"]["clip"].startswith("inset(") and middle["under"]["clip"] == ""
    assert not got["after"]["under"]["on"] and got["after"]["photo"]["clip"] == ""


# -- the preview's review (2026-11-26) ------------------------------------------------------

_INTO_THE_FADE = """
const host = makeHost(SEQ); const {a, b} = host.els;
P.load(host); const st = P.state(host); st.playing = true;
st.t = 3.0; P.show(host, true);
a.currentTime = START; st.t = START; P.show(host, true);
"""


def _into_the_fade(body: str) -> Any:
    start = 4.0 - joins.specs()[joins.FADE].duration_s
    return _run_preview(
        _two_pieces_with_a_fade(),
        _INTO_THE_FADE.replace("START", str(start)) + body,
    )


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_a_handle_or_a_jump_shows_the_block_alone_not_the_transition() -> None:
    start = 4.0 - joins.specs()[joins.FADE].duration_s
    got = _run_preview(
        _two_pieces_with_a_fade(),
        f"""
        const host = makeHost(SEQ); const {{a, b}} = host.els;
        P.load(host);
        P.showHandle(host, 1, "start");  // the second piece's start handle
        const handle = {{a: snap(a), b: snap(b), t: P.time(host)}};
        P.goTo(host, {start}, false, true);  // a jump to the block just added
        const jump = {{a: snap(a), b: snap(b)}};
        P.goTo(host, {start + 0.1}, true);  // the owner slides the tracks: it shows again
        const slide = {{a: snap(a), b: snap(b)}};
        return {{handle, jump, slide}};
        """,
    )
    for case in ("handle", "jump"):
        shown = [p for p in ("a", "b") if got[case][p]["on"]]
        assert len(shown) == 1, case  # only the block the owner asked for
        assert got[case][shown[0]]["op"] == "" and not got[case][shown[0]]["under"], case
    assert got["handle"]["t"] == pytest.approx(start)
    assert sum(1 for p in ("a", "b") if got["slide"][p]["under"]) == 1


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_the_block_under_never_plays_past_its_stretch() -> None:
    got = _into_the_fade(
        """
        const under = a.hasAttribute("data-under") ? a : b;
        const before = under.paused;
        under.currentTime = 8.5;  // past its stretch (src_end 4): the next one still loads
        P.paint(host);
        return {before, after: under.paused, still: under.hasAttribute("data-on")};
        """
    )
    assert got == {"before": False, "after": True, "still": True}


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_the_block_under_keeps_its_player_and_is_not_sought_while_it_plays() -> None:
    got = _into_the_fade(
        """
        const under = a.hasAttribute("data-under") ? a : b;
        const name = under === a ? "a" : "b"; const seeks = under.seeks;
        under.currentTime = under.currentTime;  // (a read-back, as a browser's clock)
        const base = under.seeks;
        st.t += 0.2; P.show(host, true);  // a show inside the transition (e.g. a resize)
        const still = a.hasAttribute("data-under") ? "a" : "b";
        return {name, still, extra: under.seeks - base, seeks};
        """
    )
    assert got["name"] == got["still"]  # no swap of roles between the two players
    assert got["extra"] == 0  # no seek of the one going on under


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_pausing_in_the_transition_and_jumping_out_of_it() -> None:
    got = _into_the_fade(
        """
        const under = a.hasAttribute("data-under") ? a : b;
        const top = under === a ? b : a;
        P.pause(host, true);
        const paused = {under: snap(under), top: snap(top)};
        P.goTo(host, 6.0);  // out of the transition, into the second piece
        return {paused, out: {under: snap(under), top: snap(top)}};
        """
    )
    # paused mid-transition: both stay shown, both stop
    assert got["paused"]["under"]["on"] and got["paused"]["under"]["paused"]
    assert got["paused"]["top"]["on"] and got["paused"]["top"]["paused"]
    # jumped out: only the second piece, the one under gone
    out = got["out"]
    shown = [k for k in ("under", "top") if out[k]["on"]]
    assert len(shown) == 1 and not out[shown[0]]["under"] and out[shown[0]]["op"] == ""


# -- the preview's last review (2026-11-26) -------------------------------------------------


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_a_jump_while_playing_keeps_the_next_transition() -> None:
    start = 4.0 - joins.specs()[joins.FADE].duration_s
    got = _run_preview(
        _two_pieces_with_a_fade(),
        f"""
        const host = makeHost(SEQ); const {{a, b}} = host.els;
        P.load(host); const st = P.state(host); st.playing = true;
        st.t = 0; P.show(host, true);
        P.goTo(host, 1.0, false, true);  // a block just added, while it plays
        const flag = st.noJoin;
        // the first piece plays up to its span's end: the clock moves to the second
        const active = a.hasAttribute("data-on") ? a : b;
        active.currentTime = {start};
        st.noJoin = true;  // (even a stale flag goes at the next block)
        P.tick(host);
        const under = [a, b].filter((e) => e.hasAttribute("data-under")).length;
        return {{flag, after: st.noJoin, under, idx: st.idx}};
        """,
    )
    assert got == {"flag": False, "after": False, "under": 1, "idx": 1}


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_a_trim_frame_shows_no_transition_and_playing_shows_it_again() -> None:
    start = 4.0 - joins.specs()[joins.FADE].duration_s
    got = _run_preview(
        _two_pieces_with_a_fade(),
        f"""
        const host = makeHost(SEQ); const {{a, b}} = host.els;
        P.load(host);
        P.showSource(host, 1, 4.0);  // the second piece's start, its handle moving
        const under = () => [a, b].filter((e) => e.hasAttribute("data-under")).length;
        const trim = under();
        P.goTo(host, {start + 0.1}, true);  // the owner slides the tracks
        const slid = under();
        P.showSource(host, 1, 4.0);
        P.play(host);
        return {{trim, slid, played: under()}};
        """,
    )
    assert got == {"trim": 0, "slid": 1, "played": 1}


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_a_fast_block_under_is_not_sought_for_a_small_drift() -> None:
    media: list[dict[str, object]] = [
        {"id": "v1", "key": "a", "kind": "video", "src_start": 0.0, "src_end": 16.0,
         "src_len": 20.0, "speed": 4.0},
        {"id": "v2", "key": "b", "kind": "video", "src_start": 0.0, "src_end": 4.0,
         "src_len": 4.0},
    ]  # fmt: skip
    applied = joins.apply_joins(media, {"v2": joins.FADE}, enabled=True, local=True)
    sequence = edit_sequence.from_timeline(applied, [], {"a": "/a.mp4", "b": "/b.mp4"})
    start = sequence.blocks[1].out_start
    got = _run_preview(
        sequence.to_json(),
        f"""
        const host = makeHost(SEQ); const {{a, b}} = host.els;
        P.load(host); const st = P.state(host); st.playing = true;
        st.t = 1.0; P.show(host, true);
        const out = a.hasAttribute("data-on") ? a : b;
        out.currentTime = {start} * 4; st.t = {start}; P.show(host, true);
        // the clock moves on; the player under drifts ~0,3 s of its source
        out.currentTime = ({start} + 0.1) * 4 + 0.3; const drift = out.seeks;
        st.t = {start} + 0.1; P.show(host, true);
        return {{under: out.hasAttribute("data-under"), extra: out.seeks - drift}};
        """,
    )
    assert got == {"under": True, "extra": 0}


# -- Deivid 2026-11-26: «bloques enteros, encimados» ------------------------------------------


def test_every_block_is_drawn_whole_and_the_next_lies_over_its_end() -> None:
    from .ui import timeline_vm as tl_vm

    media = _three_photos(3.0, 2.0, 3.0)
    plain = tl_vm.media_blocks(media)
    assert [(r["start"], r["length"]) for r in plain] == [("0", "3"), ("3", "2"), ("5", "3")]
    applied = joins.apply_joins(
        media, {"p1": joins.FADE, "p2": joins.WIPE}, enabled=True, local=True
    )
    fade = joins.overlap_s(joins.use_of(joins.FADE))
    wipe = joins.overlap_s(joins.use_of(joins.WIPE))
    rows = tl_vm.media_blocks(applied)
    # each block keeps its whole length on the track…
    assert [float(r["length"]) for r in rows] == [3.0, 2.0, 3.0]
    # …and the next one starts where it really starts: over the end of the one before
    starts = [float(r["start"]) for r in rows]
    assert starts == pytest.approx([0.0, 3.0 - fade, 5.0 - fade - wipe])
    assert starts[1] + 2.0 - wipe == pytest.approx(starts[2])
    # the overlap is marked on the block coming in, with its transition
    assert [(r["join_kind"], float(r["join_in"])) for r in rows] == [
        ("", 0.0),
        ("fundido", pytest.approx(fade)),
        ("barrido", pytest.approx(wipe)),
    ]
    # the track (total, ruler, clock) still lasts what the server makes
    assert tl_vm.total_seconds(applied) == pytest.approx(8.0 - fade - wipe)
    assert starts[2] + 3.0 == pytest.approx(tl_vm.total_seconds(applied))
    # the join's point sits in the middle of the overlap
    segments = vm.timeline_segments(applied)
    joined = joins.join_rows(applied, segments, local=True, starts=starts)
    assert float(joined[0]["at"]) == pytest.approx(starts[1] + fade / 2, abs=0.01)
    assert float(joined[1]["at"]) == pytest.approx(starts[2] + wipe / 2, abs=0.01)


def test_the_overlap_is_a_picture_with_the_transitions_icon() -> None:
    from .ui import timeline_vm as tl_vm

    applied = joins.apply_joins(
        _three_photos(3.0, 2.0, 3.0), {"p1": joins.FADE}, enabled=True, local=True
    )
    rows = tl_vm.media_blocks(applied)
    page = str(
        tl.timeline(
            media=rx.Var.create(rows).to(list[dict[str, str]]),  # type: ignore[arg-type]
            texts=rx.Var.create([]).to(list[dict[str, str]]),  # type: ignore[arg-type]
            effects=rx.Var.create([]).to(list[dict[str, str]]),  # type: ignore[arg-type]
            ticks=rx.Var.create([]).to(list[dict[str, str]]),  # type: ignore[arg-type]
            total="7.5",
            selected=rx.Var.create(""),
            on_select=lambda block: rx.console_log(block),
        ).render()
    )
    assert "q-tl__overlap" in page
    css = (Path(__file__).parent.parent / "assets" / "qualify-creative.css").read_text("utf-8")
    veil = css.split(".q-tl__overlap {", 1)[1].split("}", 1)[0]
    assert "pointer-events: none" in veil and "position: absolute" in veil
    assert "var(--b-in) / var(--b-len)" in veil  # its width is the transition's share
    # a chosen block comes over its neighbours
    assert '.q-tl__item[data-tl-chosen="true"] { z-index: 3; }' in css
    # review: on a desktop the point's target starts in the canvas' 4 px gap, never the ruler
    assert "top: -4px;" in css and "gap: 4px;" in css


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_a_point_is_dimmed_only_when_a_handle_really_covers_it() -> None:
    """ux review: measured in PIXELS (`timeline-drag-core.js` `joinsNear`, used by
    `timeline.js` `markJoins` on the laid-out boxes), never with a fixed number of
    seconds — a desktop's scale is not a phone's."""
    core = Path(__file__).parent.parent / "assets" / "timeline-drag-core.js"
    script = (
        f"const c = require({json.dumps(str(core))});\n"
        "const handles = [{left: 100, right: 144}, {left: 300, right: 344}];\n"
        "const points = [{left: 60, right: 84}, {left: 130, right: 154},"
        " {left: 200, right: 224}, {left: 340, right: 364}];\n"
        "console.log(JSON.stringify([c.joinsNear({points, handles}),"
        " c.joinsNear({points, handles: []})]));\n"
    )
    out = subprocess.run(
        [str(_NODE)], input=script, capture_output=True, text=True, timeout=30, check=True
    )
    near, none = json.loads(out.stdout)
    assert near == [False, True, False, True]
    assert none == [False, False, False, False]
    timeline = (Path(__file__).parent.parent / "assets" / "timeline.js").read_text("utf-8")
    assert "function markJoins(root)" in timeline and "core.joinsNear(" in timeline
    assert '.q-tl__item[data-tl-chosen="true"] .q-tl__handle' in timeline
    assert "getBoundingClientRect" in timeline.split("function markJoins", 1)[1]
    css = (Path(__file__).parent.parent / "assets" / "qualify-creative.css").read_text("utf-8")
    # touching the chosen block: hidden; under a handle: dimmed, the taps go through
    assert '.q-tl__join[data-join-off="1"] { visibility: hidden; pointer-events: none; }' in css
    assert ".q-tl__join[data-join-near] { pointer-events: none; opacity: 0.35; }" in css


def test_the_point_carries_the_transitions_icon_and_the_veil_does_not() -> None:
    from .ui import timeline_vm as tl_vm

    applied = joins.apply_joins(
        _three_photos(3.0, 3.0, 3.0), {"p1": joins.FADE, "p2": joins.WIPE},
        enabled=True, local=True,
    )  # fmt: skip
    starts = [float(r["start"]) for r in tl_vm.media_blocks(applied)]
    rows = joins.join_rows(applied, vm.timeline_segments(applied), local=True, starts=starts)
    point = str(
        tl._join(rx.Var.create(rows[0]), lambda b: rx.console_log(b), rx.Var.create("")).render()
    )  # type: ignore[arg-type]
    assert "Blend" in point or "blend" in point.lower()
    assert "ArrowLeftRight" in point or "arrow-left-right" in point.lower()
    assert "q-tl__join-icon" in point and "q-tl__join-dot" in point
    blocks = tl_vm.media_blocks(applied)
    veil = str(
        tl._block(
            rx.Var.create(blocks[1]),  # type: ignore[arg-type]
            selected=rx.Var.create(""),
            on_select=lambda b: rx.console_log(b),
            overlap=True,
        ).render()
    )
    overlay = veil.split("q-tl__overlap", 1)[1].split("q-tl__item", 1)[0]
    assert "Blend" not in overlay and "ArrowLeftRight" not in overlay
    assert "data-tl-in" in veil  # its name and picture start after the stripes
    css = (Path(__file__).parent.parent / "assets" / "qualify-creative.css").read_text("utf-8")
    assert '.q-tl__item[data-tl-in="1"] .q-tl__block {' in css
    assert '.q-tl__item[data-tl-in="1"] .q-tl__pic {' in css
    assert "color: var(--accent-contrast)" in css  # the icon on the accent


@pytest.mark.usefixtures("editor_on", "joins_on")
def test_the_panel_says_why_the_video_is_shorter() -> None:
    state = _state()
    second = _ids(state)[1]
    _choose(state, second, joins.FADE)
    assert state.clip_join_chosen["overlap_line"] == (
        "Durante el fundido se ven los dos a la vez, así que tu video queda 0,5 s más corto."
    )
    CreativeState.set_clip_join.fn(state, joins.WIPE)
    assert state.clip_join_chosen["overlap_line"].startswith("Durante el barrido")
    assert "0,4 s más corto" in state.clip_join_chosen["overlap_line"]
    CreativeState.set_clip_join.fn(state, joins.CUT)
    assert state.clip_join_chosen["overlap_line"] == ""


# -- review of «bloques enteros, encimados» --------------------------------------------------


@pytest.mark.skipif(_NODE is None, reason="node is not installed")
def test_lifting_a_block_without_moving_it_keeps_its_place() -> None:
    """Blocks laid over each other at their transitions: the reorder counts each block's
    STEP on the row (`stepWidths`), so a block lifted and let go where it was stays."""
    core = Path(__file__).parent.parent / "assets" / "timeline-drag-core.js"
    script = (
        f"const c = require({json.dumps(str(core))});\n"
        "const out = {};\n"
        "for (const fade of [22, 44]) {\n"  # 0,5 s and 1 s at 44 px a second
        "  const widths = [88, 88, 88, 88, 88];\n"  # five photos of 2 s
        "  const lefts = widths.map((w, i) => i * (88 - fade));\n"
        "  const steps = c.stepWidths(lefts, widths);\n"
        "  out[fade] = {steps,\n"
        "    rest: lefts.map((l, i) => c.dropIndex(steps, i, l)),\n"
        "    shifts: lefts.map((l, i) => c.layoutShifts(steps, i, i)),\n"
        "    span: steps.reduce((a, b) => a + b, 0), end: lefts[4] + 88,\n"
        "    old: lefts.map((l, i) => c.dropIndex(widths, i, l))};\n"
        "}\n"
        "console.log(JSON.stringify(out));\n"
    )
    out = subprocess.run(
        [str(_NODE)], input=script, capture_output=True, text=True, timeout=30, check=True
    )
    got = json.loads(out.stdout)
    for fade in ("22", "44"):
        case = got[fade]
        assert case["rest"] == [0, 1, 2, 3, 4], fade  # at rest: its own place
        assert all(s == 0 for shifts in case["shifts"] for s in shifts), fade
        assert case["span"] == case["end"], fade  # never dragged past the row's end
    assert got["22"]["old"] != [0, 1, 2, 3, 4]  # (the drawn widths moved it)
    drag = (Path(__file__).parent.parent / "assets" / "timeline-drag.js").read_text("utf-8")
    assert "core().stepWidths(" in drag


def test_the_overlap_comes_from_the_block_coming_in() -> None:
    """Review: a block of no length between two blocks — the transition is on the block
    that comes in, never read off the block before it on the track."""
    from .ui import timeline_vm as tl_vm

    media: list[dict[str, object]] = [
        {"id": "p0", "key": "uploads/t/clip/p0.jpg", "kind": "photo", "dur": 3.0},
        {"id": "x", "key": "", "kind": "photo", "dur": 2.0},
        {"id": "p2", "key": "uploads/t/clip/p2.jpg", "kind": "photo", "dur": 3.0},
    ]
    applied = joins.apply_joins(media, {"p2": joins.FADE}, enabled=True, local=True)
    fade = joins.overlap_s(joins.use_of(joins.FADE))
    rows = tl_vm.media_blocks(applied)
    assert [(r["join_kind"], float(r["join_in"])) for r in rows] == [
        ("", 0.0),
        ("", 0.0),
        ("fundido", pytest.approx(fade)),
    ]


def test_the_names_follow_the_blocks_when_they_move() -> None:
    media = _three_photos(3.0, 3.0, 3.0)
    first = joins.join_rows(media, vm.timeline_segments(media), local=True, starts=[0, 3, 6])
    assert [r["name"] for r in first] == [
        "Unión entre Foto 1 y Foto 2: Corte",
        "Unión entre Foto 2 y Foto 3: Corte",
    ]
    moved = [media[2], media[0], media[1]]  # the last photo first: names by place
    again = joins.join_rows(moved, vm.timeline_segments(moved), local=True, starts=[0, 3, 6])
    assert [(r["id"], r["before_label"], r["after_label"]) for r in again] == [
        ("p0", "Foto 1", "Foto 2"),
        ("p1", "Foto 2", "Foto 3"),
    ]
    # m-25129405 (D1 of the editor's mockups): «bloque» never reaches the screen; the
    # words name what the owner sees
    assert joins.HELP == "Elige cómo pasa tu video de una foto o video al siguiente."
    assert joins.NO_ROOM == (
        "Estas fotos o videos son muy cortos para unirlos con fundido o barrido. "
        "Alárgalos para elegirlos."
    )
    assert "entre dos fotos o videos" in joins.FIND_HINT
    for text in (joins.HELP, joins.NO_ROOM, joins.FIND_HINT):
        assert "bloque" not in text
    assert "Hacia dónde se mueve Foto 3" == joins.direction_title("Foto 3")


# -- the last details before the PR (2026-11-26) ---------------------------------------------


def _css() -> str:
    return (Path(__file__).parent.parent / "assets" / "qualify-creative.css").read_text("utf-8")


def test_on_a_phone_too_the_point_never_reaches_the_ruler() -> None:
    css = _css()
    block = css.split(".q-tl__join {", 1)[1].split("}", 1)[0]
    # the target starts in the canvas' 4 px gap and runs 44 px down, at every size
    assert "top: -4px;" in block and "height: 44px;" in block
    assert "translateX(-50%)" in block and "translate(-50%, -50%)" not in block
    # the dot rides the edge as a picture only: the ruler keeps its taps
    assert ".q-tl__join .q-tl__join-dot { margin-top: -6px; pointer-events: none; }" in css


def test_the_points_hide_while_blocks_are_reordered() -> None:
    assert '[data-tl-dragging="move"] .q-tl__joins { opacity: 0; visibility: hidden; }' in _css()
    drag = (Path(__file__).parent.parent / "assets" / "timeline-drag.js").read_text("utf-8")
    assert 'd.root.setAttribute("data-tl-dragging", d.mode)' in drag


def test_the_points_under_the_handles_are_measured_again_after_a_trim() -> None:
    assets = Path(__file__).parent.parent / "assets"
    drag = (assets / "timeline-drag.js").read_text("utf-8")
    release = drag.split("function trimRelease", 1)[1].split("\n  }\n", 1)[0]
    assert release.count("remarkJoins(t.root)") == 2  # once answered, and on giving up
    assert "remarkJoins(d.root)" in drag.split("function clearOnRender", 1)[1]
    timeline = (assets / "timeline.js").read_text("utf-8")
    assert "markJoins: markJoins" in timeline
    # a point that just hid gives the focus to the chosen block
    marks = timeline.split("function markJoins", 1)[1].split("\n  }\n", 1)[0]
    assert 'getAttribute("data-join-off") === "1"' in marks and ".focus(" in marks


def test_a_block_of_no_length_beside_a_join_hides_it_when_chosen() -> None:
    media: list[dict[str, object]] = [
        {"id": "p0", "key": "uploads/t/clip/p0.jpg", "kind": "photo", "dur": 3.0},
        {"id": "x", "key": "uploads/t/clip/x.jpg", "kind": "photo", "dur": 0.0},
        {"id": "p2", "key": "uploads/t/clip/p2.jpg", "kind": "photo", "dur": 3.0},
    ]
    rows = joins.join_rows(media, vm.timeline_segments(media), local=True, starts=[0, 3, 3])
    assert [(r["id"], r["before"], r["beside"]) for r in rows] == [("p2", "p0", "x")]
    page = str(
        tl._join(
            rx.Var.create(rows[0]),  # type: ignore[arg-type]
            lambda b: rx.console_log(b),
            rx.Var.create("x"),
        ).render()
    )
    assert "beside" in page and "data-join-off" in page

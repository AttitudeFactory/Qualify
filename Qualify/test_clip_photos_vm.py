"""ED-14 (m-25029109): a still photo's seconds in the Clip editor — offline."""

from __future__ import annotations

import pytest

from . import clip_editor_vm
from . import clip_photos_vm as vm
from . import editor_preview_contract as contract
from .ui import timeline_vm

_PHOTO = {"key": "a.jpg", "kind": "image", "source": "upload", "name": "a.jpg"}
_PHOTO_B = {"key": "b.jpg", "kind": "image", "source": "upload", "name": "b.jpg"}
_VIDEO = {"key": "v.mp4", "kind": "video", "source": "upload", "name": "v.mp4"}
_PHOTO_C = {"key": "c.jpg", "kind": "image", "source": "upload", "name": "c.jpg"}


def _media(
    strip: list[dict[str, str]], lengths: dict[str, float] | None = None
) -> list[dict[str, object]]:
    return clip_editor_vm.timeline_media(
        strip,
        own_key="",
        cut_start=0.0,
        cut_end=0.0,
        speed=1.0,
        rotate=0,
        lengths=lengths or {},
    )


def _recipe(media: list[dict[str, object]]) -> contract.PartRecipe:
    return clip_editor_vm.recipe_of(
        video_key="",
        start=0.0,
        end=0.0,
        rotate=0,
        effects=(),
        speed=1,
        text="",
        place="bottom",
        timeline=media,
    )


# -- criterion 1: a photo comes in at 2 s and travels as `kind` photo ------------------------


def test_default_matches_the_editor_and_the_contract_bounds() -> None:
    assert vm.DEFAULT_SECONDS == clip_editor_vm.PHOTO_SECONDS == 2.0
    assert (timeline_vm.PHOTO_MIN_S, timeline_vm.PHOTO_MAX_S) == (
        contract.PHOTO_SECONDS_MIN,
        contract.PHOTO_SECONDS_MAX,
    )


def test_an_added_photo_shows_2_s_and_is_saved_as_a_photo_segment() -> None:
    media = vm.apply_photo_settings(_media([_PHOTO]), {}, {})
    assert media[0]["dur"] == 2.0
    recipe = _recipe(media)
    assert recipe.segments == (contract.SourceSegment("a.jpg", 0.0, 2.0, 1.0, 0, "photo"),)
    assert contract.segment_problems(recipe.segments[0]) == []


def test_the_owner_s_seconds_reach_the_recipe() -> None:
    media = vm.apply_photo_settings(_media([_PHOTO, _PHOTO_B]), {"b.jpg": 3.5})
    segments = _recipe(media).segments
    assert [(s.key, s.start_s, s.end_s, s.kind) for s in segments] == [
        ("a.jpg", 0.0, 2.0, "photo"),
        ("b.jpg", 0.0, 3.5, "photo"),
    ]
    assert clip_editor_vm.recipe_seconds(segments) == 5.5


def test_a_turned_photo_s_stretch_is_valid_for_the_contract() -> None:
    media = vm.apply_photo_settings(_media([_PHOTO]), {"a.jpg": 2.7}, {"a.jpg": 90})
    seg = _recipe(media).segments[0]
    assert seg == contract.SourceSegment("a.jpg", 0.0, 2.5, 1.0, 90, "photo")
    assert contract.segment_problems(seg) == []
    # out of bounds or not a quarter turn: read normalized, never past the contract
    odd = vm.apply_photo_settings(_media([_PHOTO]), {"a.jpg": 9}, {"a.jpg": 45})
    assert (_recipe(odd).segments[0].end_s, _recipe(odd).segments[0].rotate) == (5.0, 0)


# -- criterion 2: 1 s to 5 s, ½ s at a time ------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (2, 2.0),
        (2.2, 2.0),
        (2.3, 2.5),
        (0.2, 1.0),
        (0, 1.0),
        (-3, 1.0),
        (5.2, 5.0),
        (99, 5.0),
        ("3.5", 3.5),
        (None, 2.0),
        ("", 2.0),
        ("mucho", 2.0),
        (float("nan"), 2.0),
    ],
)
def test_normalize(raw: object, expected: float) -> None:
    assert vm.normalize(raw) == expected


def test_nudge_goes_half_a_second_and_stops_at_the_edges() -> None:
    assert vm.nudge(2.0, vm.NUDGE_S) == (2.5, "")
    assert vm.nudge(2.0, -vm.NUDGE_S) == (1.5, "")
    assert vm.nudge(1.0, -0.5) == (1.0, vm.AT_MIN)
    assert vm.nudge(5.0, 0.5) == (5.0, vm.AT_MAX)
    assert vm.nudge(4.5, 0.5) == (5.0, "")
    assert not vm.can_less(1.0) and vm.can_less(1.5)
    assert not vm.can_more(5.0) and vm.can_more(4.5)


def test_every_reachable_value_is_on_the_magnet() -> None:
    seconds, seen = vm.DEFAULT_SECONDS, set()
    for delta in [0.5] * 12 + [-0.5] * 12:
        seconds, _why = vm.nudge(seconds, delta)
        seen.add(seconds)
    assert seen == {1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0}


def test_drag_lands_on_the_magnet() -> None:
    assert vm.from_drag(3.26) == 3.5
    assert vm.from_drag(0.4) == 1.0
    assert vm.from_drag(7.0) == 5.0


def test_the_editor_s_own_nudge_agrees() -> None:
    media = vm.apply_photo_settings(_media([_PHOTO]))
    for start, delta in ((2.0, 0.5), (1.0, -0.5), (5.0, 0.5), (3.0, -1.0)):
        media[0]["dur"] = start
        nudged, _ = timeline_vm.nudge(media, [], "a.jpg", "end", delta)  # type: ignore[arg-type]
        assert nudged[0]["dur"] == vm.nudge(start, delta)[0]


def test_the_button_goes_off_at_the_edge_with_its_line() -> None:
    assert vm.limit_line(1.0) == vm.AT_MIN
    assert vm.limit_line(5.0) == vm.AT_MAX
    assert vm.limit_line(2.5) == ""


def test_limit_lines_say_what_to_do() -> None:
    for line in (vm.AT_MIN, vm.AT_MAX, vm.AT_MAX_FULL):
        assert line.endswith(".")
        assert "«" in line or "agrega" in line or "alarga" in line


def test_a_full_timeline_never_says_add_another_photo() -> None:
    # ED-12 (#771): at 8 photos or videos nothing more goes in, so «agrega otra foto»
    # would be a dead end
    full_media = _media([{**_PHOTO, "key": f"{n}.jpg"} for n in range(8)])
    assert clip_editor_vm.timeline_full(full_media)
    full = clip_editor_vm.timeline_full(full_media)
    assert vm.limit_line(5.0, full=full) == vm.AT_MAX_FULL
    assert vm.nudge(5.0, 0.5, full=full) == (5.0, vm.AT_MAX_FULL)
    assert "agrega" not in vm.AT_MAX_FULL
    # the low edge says the same whether the timeline is full or not
    assert vm.limit_line(1.0, full=True) == vm.AT_MIN
    assert vm.nudge(1.0, -0.5, full=True) == (1.0, vm.AT_MIN)


def test_a_full_timeline_suggests_another_photo_only_if_one_can_grow() -> None:
    # Deivid 2026-11-24 («sugerir solo si se puede»)
    media = vm.apply_photo_settings(
        _media([_PHOTO, _VIDEO, _PHOTO_B]), {"a.jpg": 5.0, "b.jpg": 3.0}
    )
    assert vm.other_room(media, "a.jpg")  # b.jpg is under 5 s
    assert vm.limit_line(5.0, full=True, room=True) == vm.AT_MAX_FULL
    assert vm.nudge(5.0, 0.5, full=True, room=True) == (5.0, vm.AT_MAX_FULL)
    # every other photo already at 5 s (a video does not count): no impossible advice
    at_top = vm.apply_photo_settings(_media([_PHOTO, _VIDEO, _PHOTO_B]), {"a.jpg": 5, "b.jpg": 5})
    assert not vm.other_room(at_top, "a.jpg")
    assert vm.limit_line(5.0, full=True, room=False) == vm.AT_MAX_END
    assert vm.nudge(5.0, 0.5, full=True, room=False) == (5.0, vm.AT_MAX_END)
    assert vm.photo_row_fields(5.0, full=True, room=False)["limit"] == vm.AT_MAX_END
    assert "alarga" not in vm.AT_MAX_END and "agrega" not in vm.AT_MAX_END
    assert vm.AT_MAX_END.endswith(".")
    # not full: «agrega otra foto», whatever the others are
    assert vm.limit_line(5.0, full=False, room=False) == vm.AT_MAX
    # the only photo of the Clip: nothing else to lengthen
    assert not vm.other_room(vm.apply_photo_settings(_media([_PHOTO, _VIDEO])), "a.jpg")


def test_photo_row_fields() -> None:
    # Deivid 2026-11-24: no «− ½ s / + ½ s» — only the handle and, at an edge, its line
    assert vm.photo_row_fields(2.0) == {"handles": "1", "limit": "", "end_why": ""}
    low = vm.photo_row_fields(1.0)
    assert (low["limit"], low["end_why"]) == (vm.AT_MIN, vm.LIMIT_ID)
    high = vm.photo_row_fields(5.0, full=True)
    assert (high["limit"], high["end_why"]) == (vm.AT_MAX_FULL, vm.LIMIT_ID)
    assert all(isinstance(v, str) for v in high.values())
    # the panel says how to change it: by dragging, never a button
    assert "arrastra" in vm.DRAG_HINT and "toca" not in vm.DRAG_HINT


def test_photo_place_counts_every_block() -> None:
    media = _media([_PHOTO, _VIDEO, _PHOTO_B])
    assert vm.photo_place(media, "a.jpg") == 1
    assert vm.photo_place(media, "b.jpg") == 3
    assert vm.photo_place(media, "v.mp4") == 0  # a video
    assert vm.photo_place(media, "gone.jpg") == 0


# -- criterion 5: «Foto {n} de {m}, se ve {s} s» --------------------------------------------


def test_texts_use_the_decimal_comma() -> None:
    assert vm.seconds_text(2.5) == "2,5" and vm.seconds_text(2) == "2"
    # a sentence read aloud says «segundos» (a bare «s» is read as the letter)
    assert vm.changed_line(1, 1.5) == "La foto 1 ahora se ve 1,5 segundos."
    assert vm.changed_line(1, 1) == "La foto 1 ahora se ve 1 segundo."
    # «Girar» says how the photo stands now, so a screen reader knows whether to tap again
    assert vm.turned_line(2, 90) == "Giraste la foto 2: ahora está de lado, girada a la derecha."
    assert vm.turned_line(2, 180) == "Giraste la foto 2: ahora está al revés."
    assert vm.turned_line(2, 270) == "Giraste la foto 2: ahora está de lado, girada a la izquierda."
    assert vm.turned_line(2, 0) == "Giraste la foto 2: volvió a quedar derecha."
    assert vm.turned_line(2) != clip_editor_vm.change_message({"rotate": 0}, {"rotate": 90})


def test_limit_lines_are_plain_spanish() -> None:
    # qualify-copy-es (ED-14 UX review): whole words, never «lo más posible» nor a bare «s»
    assert vm.AT_MIN == "La foto ya está en 1 segundo, el mínimo. Si no la quieres, toca «Quitar»."
    assert vm.AT_MAX == (
        "La foto ya está en 5 segundos, el máximo. Para mostrarla más tiempo, agrega otra foto."
    )
    for line in (vm.AT_MIN, vm.AT_MAX, vm.AT_MAX_FULL):
        assert "posible" not in line and " s," not in line and " s." not in line


def test_texts_match_the_timeline_rows_counting_every_block() -> None:
    # «Foto {n} de {m}» counts every block of «Fotos y videos» (Deivid 2026-11-20)
    media = vm.apply_photo_settings(_media([_PHOTO, _VIDEO, _PHOTO_B]), {"b.jpg": 4.5})
    rows = timeline_vm.media_blocks(media)  # type: ignore[arg-type]
    photos = [(n, row) for n, row in enumerate(rows, start=1) if row["kind"] == "photo"]
    assert [(n, row["name"], row["panel"], row["end_text"]) for n, row in photos] == [
        (1, "Foto 1 de 3, se ve 2 s", "Foto 1 · 2 s", "Se ve 2 s"),
        (3, "Foto 3 de 3, se ve 4,5 s", "Foto 3 · 4,5 s", "Se ve 4,5 s"),
    ]
    assert [vm.photo_place(media, "a.jpg"), vm.photo_place(media, "b.jpg")] == [1, 3]


# -- the bar of a chosen photo -----------------------------------------------------------------


def test_the_editor_s_photo_bar_is_turn_and_remove() -> None:
    # no «Duración» in the bar: the panel and the end handle only (Deivid 2026-11-20).
    # The buttons are named by their visible text («Girar», «Quitar»; their icons are
    # `aria-hidden`), inside the bar «Acciones de Foto n».
    assert [t[0] for t in clip_editor_vm.EDITOR_ACTIONS["photo"]] == ["Girar", "Quitar"]
    assert clip_editor_vm.EDITOR_ACTIONS["photo"][0] == (clip_editor_vm.ROTATE, "rotate-cw")


# -- the state: `clip_photo_seconds` / `clip_photo_turns`, ONE PER BLOCK ---------------------

#: Two blocks of the same photo, as they will look once a photo can repeat (today a photo
#: block's id is its file key and the strip holds each file once).
_TWICE: list[dict[str, object]] = [
    {"id": "a.jpg", "key": "a.jpg", "kind": "photo", "dur": 2.0},
    {"id": "v.mp4", "key": "v.mp4", "kind": "video", "src_start": 0.0, "src_end": 3.0},
    {"id": "a.jpg#2", "key": "a.jpg", "kind": "photo", "dur": 2.0},
]


def test_a_photo_block_s_id_is_its_file_key_today() -> None:
    media = _media([_PHOTO, _VIDEO, _PHOTO_B])
    assert [vm.block_key(item) for item in media if item["kind"] == "photo"] == [
        "a.jpg",
        "b.jpg",
    ]


def test_the_id_stays_when_blocks_move() -> None:
    media = vm.apply_photo_settings(_media([_PHOTO, _VIDEO, _PHOTO_B]), {"b.jpg": 4.0})
    moved = timeline_vm.move_to(media, "b.jpg", 0)  # type: ignore[arg-type]
    assert moved[0]["id"] == "b.jpg"
    again = vm.apply_photo_settings(moved, {"b.jpg": 4.0})  # type: ignore[arg-type]
    assert again[0]["dur"] == 4.0 and again[1]["dur"] == 2.0


def test_each_block_keeps_its_own_seconds_and_turn() -> None:
    seconds = vm.with_seconds({}, "a.jpg#2", 4.0)
    turns = vm.with_turn({}, "a.jpg#2")
    out = vm.apply_photo_settings(_TWICE, seconds, turns)
    assert (out[0]["dur"], out[0]["rotate"]) == (2.0, 0)
    assert (out[2]["dur"], out[2]["rotate"]) == (4.0, 90)
    photos = [s for s in clip_editor_vm.timeline_segments(out) if s.kind == "photo"]
    assert photos == [
        contract.SourceSegment("a.jpg", 0.0, 2.0, 1.0, 0, "photo"),
        contract.SourceSegment("a.jpg", 0.0, 4.0, 1.0, 90, "photo"),
    ]


def test_a_value_kept_by_file_reaches_every_block_until_one_is_changed() -> None:
    by_file = {"a.jpg": 3.0}
    out = vm.apply_photo_settings(_TWICE, by_file, {"a.jpg": 180})
    assert [out[0]["dur"], out[2]["dur"]] == [3.0, 3.0]
    assert [out[0]["rotate"], out[2]["rotate"]] == [180, 180]
    assert vm.seconds_of(vm.with_seconds(by_file, "a.jpg#2", 5.0), "a.jpg#2", "a.jpg") == 5.0
    assert vm.turn_of(vm.with_turn({"a.jpg": 180}, "a.jpg#2", "a.jpg"), "a.jpg#2") == 270


def test_a_state_without_seconds_reads_2_s() -> None:
    assert vm.seconds_of(None, "a.jpg") == 2.0
    assert vm.seconds_of({}, "a.jpg#2", "a.jpg") == 2.0
    assert vm.with_seconds(None, "a.jpg", 2.0) == {}
    out = vm.apply_photo_settings(_TWICE)
    assert [out[0]["dur"], out[2]["dur"]] == [2.0, 2.0]


def test_with_seconds_keeps_the_others_normalized_and_drops_defaults() -> None:
    saved = {"a.jpg": 2.0, "b.jpg": 7, "c.jpg#2": "1.2", "": 3.0, "d.jpg": None}
    assert vm.with_seconds(saved, "e.jpg", 3.0) == {"b.jpg": 5.0, "c.jpg#2": 1.0, "e.jpg": 3.0}


def test_with_seconds_returns_a_new_dict() -> None:
    store: dict[str, float] = {"a.jpg": 3.0}
    out = vm.with_seconds(store, "a.jpg#2", 4.2)
    assert out == {"a.jpg": 3.0, "a.jpg#2": 4.0}
    assert out is not store and store == {"a.jpg": 3.0}
    assert vm.with_seconds(out, "a.jpg", 2.0) == {"a.jpg#2": 4.0}


def test_prune_keeps_the_blocks_on_the_timeline_by_id() -> None:
    store = {"a.jpg": 3.0, "a.jpg#2": 4.0, "gone.jpg": 5.0}
    assert vm.prune(store, _TWICE) == {"a.jpg": 3.0, "a.jpg#2": 4.0}
    # a value kept by file moves to each block's id
    assert vm.prune({"a.jpg": 3.0}, _TWICE[2:]) == {"a.jpg#2": 3.0}
    assert vm.prune({"gone.jpg": 5.0}, _TWICE) == {}
    assert vm.prune_turns({"a.jpg": 90, "gone.jpg": 90}, _TWICE) == {
        "a.jpg": 90,
        "a.jpg#2": 90,
    }


def test_turns() -> None:
    store: dict[str, int] = {}
    for expected in (90, 180, 270, 0):
        store = vm.with_turn(store, "a.jpg")
        assert vm.turn_of(store, "a.jpg") == expected
    assert store == {}
    assert vm.turn_of({"a.jpg": 45}, "a.jpg") == 0
    assert vm.turn_of({"a.jpg": "x"}, "a.jpg") == 0


def test_timeline_segments_carries_the_photo_s_turn() -> None:
    # the recipe gets each photo's seconds AND turn
    media = vm.apply_photo_settings(
        _media([_PHOTO, _VIDEO, _PHOTO_B]), {"b.jpg": 3.5}, {"b.jpg": 90}
    )
    photos = [s for s in clip_editor_vm.timeline_segments(media) if s.kind == "photo"]
    assert photos == [
        contract.SourceSegment("a.jpg", 0.0, 2.0, 1.0, 0, "photo"),
        contract.SourceSegment("b.jpg", 0.0, 3.5, 1.0, 90, "photo"),
    ]


def test_timeline_segments_keeps_a_photo_upright_on_an_odd_turn() -> None:
    # a turn that is not a quarter (a hand-made state) never reaches the recipe
    media = [{"id": "a.jpg", "key": "a.jpg", "kind": "photo", "dur": 2.0, "rotate": 45}]
    assert clip_editor_vm.timeline_segments(media)[0].rotate == 0
    media[0]["rotate"] = "x"
    assert clip_editor_vm.timeline_segments(media)[0].rotate == 0


# -- ED-12 (#771): media put in at a place read the photos' own seconds ----------------------


def test_where_a_new_block_goes_reads_the_photo_s_seconds() -> None:
    # the browser measured the video: 3 s (unmeasured it would take 15 s,
    # `contract.DEFAULT_STRETCH_SECONDS`)
    plain = _media([_PHOTO, _VIDEO, _PHOTO_B], {"v.mp4": 3.0})
    longer = vm.apply_photo_settings(plain, {"a.jpg": 4.0})
    # the marker at 3.9 s: inside the video with 2 s photos, still on the 4 s photo
    assert clip_editor_vm.index_after_playhead(plain, 3.9) == 2
    assert clip_editor_vm.index_after_playhead(longer, 3.9) == 1
    # and the preview jumps to where the block starts on the final video
    assert clip_editor_vm.block_start(plain, 2) == 2.0 + 3.0
    assert clip_editor_vm.block_start(longer, 2) == 4.0 + 3.0


def test_a_photo_put_in_comes_at_2_s_and_the_others_keep_theirs() -> None:
    strip = [_PHOTO, _VIDEO, _PHOTO_B, _PHOTO_C]  # c.jpg just chosen, at the end
    seconds = {"b.jpg": 4.0}
    turns = {"b.jpg": 270}
    media = vm.apply_photo_settings(_media(strip), seconds, turns)
    keys = [str(item["key"]) for item in strip]
    order = clip_editor_vm.insert_order(keys, media, ["c.jpg"], 1)
    assert order == ["a.jpg", "c.jpg", "v.mp4", "b.jpg"]
    by_key = {str(item["key"]): item for item in strip}
    placed = vm.apply_photo_settings(_media([by_key[k] for k in order]), seconds, turns)
    assert [(i["id"], i.get("dur"), i.get("rotate")) for i in placed] == [
        ("a.jpg", 2.0, 0),
        ("c.jpg", 2.0, 0),
        ("v.mp4", None, None),
        ("b.jpg", 4.0, 270),
    ]
    # the place in the live line counts every block, as the panel's title
    assert clip_editor_vm.added_line(placed, [1]) == "Agregaste la foto 2."
    assert vm.photo_place(placed, "b.jpg") == 4


def test_the_cap_counts_a_photo_once_whatever_its_seconds() -> None:
    strip = [{**_PHOTO, "key": f"{n}.jpg"} for n in range(8)] + [_PHOTO_C]
    media = vm.apply_photo_settings(_media(strip), {"0.jpg": 5.0})
    assert clip_editor_vm.keep_within_cap(["c.jpg"], media) == ([], ["c.jpg"])


def test_apply_leaves_videos_alone_and_copies() -> None:
    media = _media([_PHOTO, _VIDEO])
    out = vm.apply_photo_settings(media, {"a.jpg": 4.0}, {"a.jpg": 90})
    assert out[0]["dur"] == 4.0 and out[0]["rotate"] == 90
    assert out[1] == media[1]
    assert media[0]["dur"] == 2.0 and "rotate" not in media[0]

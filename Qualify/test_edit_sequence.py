"""ED-01b (m-25029106): the browser's sequence — order, the final video's clock with
speed, photos (the recipe v2's `SourceSegment.kind`, or the timeline's rows), texts
(`text_layers`, up to three) and effects by time."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from . import edit_sequence as seq
from . import editor_preview_contract as c

_MEDIA = [
    {"id": "video-1", "key": "v/a.mp4", "kind": "video", "src_start": 0.0, "src_end": 4.0,
     "src_len": 15.0},
    {"id": "video-2", "key": "v/a.mp4", "kind": "video", "src_start": 4.0, "src_end": 9.0,
     "src_len": 15.0},
    {"id": "foto-3", "key": "p/foto.jpg", "kind": "photo", "dur": 2.0},
    {"id": "video-4", "key": "v/b.mp4", "kind": "video", "src_start": 0.0, "src_end": 30.0,
     "src_len": 30.0, "speed": 10.0},
]  # fmt: skip
_OVERLAYS = [
    {"id": "t1", "kind": "text", "label": "2×1 hoy", "start": 2.0, "end": 5.0, "place": "top"},
    {"id": "e1", "kind": "effect", "label": "Vapor", "start": 4.0, "end": 9.0},
]
_URLS = {"v/a.mp4": "/_upload/a.mp4", "v/b.mp4": "/_upload/b.mp4", "p/foto.jpg": "/f.jpg"}


def _timeline() -> seq.PreviewSequence:
    return seq.from_timeline(_MEDIA, _OVERLAYS, _URLS)


def test_blocks_play_in_order_on_one_clock() -> None:
    s = _timeline()
    assert [(b.kind, b.key) for b in s.blocks] == [
        ("video", "v/a.mp4"),
        ("video", "v/a.mp4"),
        ("photo", "p/foto.jpg"),
        ("video", "v/b.mp4"),
    ]
    # 4 s · 5 s · a 2 s photo · 30 s at ×10 = 3 s: end to end, no gaps
    assert [(b.out_start, b.out_end) for b in s.blocks] == [
        (0.0, 4.0),
        (4.0, 9.0),
        (9.0, 11.0),
        (11.0, 14.0),
    ]
    assert s.total == 14.0
    assert [b.url for b in s.blocks] == [
        "/_upload/a.mp4",
        "/_upload/a.mp4",
        "/f.jpg",
        "/_upload/b.mp4",
    ]
    assert [b.label for b in s.blocks] == ["Video 1", "Video 2", "Foto 3", "Video 4"]


def test_block_at_a_final_time() -> None:
    s = _timeline()
    assert [s.block_at(t) for t in (0.0, 3.99, 4.0, 9.5, 11.0, 13.9, 99.0)] == [
        0,
        0,
        1,
        2,
        3,
        3,
        3,
    ]
    assert seq.PreviewSequence().block_at(1.0) == -1


def test_a_photo_is_timed_and_bounded() -> None:
    s = seq.from_timeline([{"id": "f", "kind": "photo", "dur": 9.0}], [], {})
    assert (s.blocks[0].dur, s.total) == (5.0, 5.0)  # 1–5 s
    s = seq.from_timeline([{"id": "f", "kind": "photo", "dur": 0.2}], [], {})
    assert s.total == 1.0


def test_texts_and_effects_by_time() -> None:
    s = _timeline()
    assert s.overlays_at(1.9) == ([], [])
    assert s.overlays_at(2.0) == ([0], [])
    assert s.overlays_at(4.5) == ([0], [0])
    assert s.overlays_at(5.0) == ([], [0])  # the text ends at 0:05
    assert s.overlays_at(9.0) == ([], [])
    assert (s.texts[0].text, s.texts[0].place) == ("2×1 hoy", "top")
    assert s.effects[0].url == ""  # no loop file yet: not drawn


def test_speed_above_sixteen_says_the_preview_is_slower() -> None:
    assert not _timeline().slower  # ×10
    fast = [dict(_MEDIA[3], speed=20.0)]
    assert seq.from_timeline(fast, [], _URLS).slower


def test_json_is_what_the_script_reads() -> None:
    data = json.loads(_timeline().to_json())
    assert data["total"] == 14.0 and data["slower"] is False
    assert data["blocks"][2] == {
        "key": "p/foto.jpg",
        "kind": "photo",
        "out_start": 9.0,
        "out_end": 11.0,
        "url": "/f.jpg",
        "poster": "",
        "label": "Foto 3",
        "src_start": 0.0,
        "src_end": 0.0,
        "speed": 1.0,
        "rotate": 0,
        "dur": 2.0,
    }
    assert data["texts"][0]["start"] == 2.0 and data["texts"][0]["end"] == 5.0


def test_from_a_recipe_with_one_text(tmp_path: Path) -> None:
    recipe = c.PartRecipe(
        segments=(
            c.SourceSegment("v/a.mp4", 2.0, 6.0),
            c.SourceSegment("v/a.mp4", 10.0, 30.0, speed=10.0, rotate=90),
        ),
        text_layer=c.VideoTextLayer("Hoy", place="middle", start_s=1.0),
        effects=(
            c.EffectUse("camara_rapida"),
            c.EffectUse("humo_capa", 1, (), 2.0, 5.0),
            c.EffectUse("vapor_capa"),
        ),
    )
    s = seq.from_recipe(recipe, {"v/a.mp4": c.PreviewSource("v/a.mp4", "/a.mp4", 40.0)})
    assert [(b.out_start, b.out_end, b.speed, b.rotate) for b in s.blocks] == [
        (0.0, 4.0, 1.0, 0),
        (4.0, 6.0, 10.0, 90),
    ]
    assert s.blocks[0].url == "/a.mp4"
    assert (s.texts[0].start, s.texts[0].end, s.texts[0].place) == (1.0, 6.0, "middle")
    # «Cámara rápida» is the stretch's speed, not a layer; a layer without times = all
    assert [(e.effect_id, e.start, e.end) for e in s.effects] == [
        ("humo_capa", 2.0, 5.0),
        ("vapor_capa", 0.0, 6.0),
    ]
    assert all(e.url == "" for e in s.effects)
    loop = tmp_path / "effects" / "vapor_capa" / "v1" / "preview.webm"
    loop.parent.mkdir(parents=True)
    loop.write_bytes(b"x")
    s = seq.from_recipe(recipe, {}, assets_root=tmp_path)
    assert s.effects[1].url == "/effects/vapor_capa/v1/preview.webm"
    assert s.blocks[0].url == ""  # no address: still timed, never stops the sequence


def test_an_empty_recipe_is_an_empty_sequence() -> None:
    s = seq.from_recipe(c.PartRecipe(), {})
    assert (s.blocks, s.total, s.texts) == ((), 0.0, ())


def test_a_recipe_photo_is_a_timed_block_in_its_place() -> None:
    recipe = c.PartRecipe(
        segments=(
            c.SourceSegment("v/a.mp4", 2.0, 6.0),
            c.SourceSegment("p/foto.jpg", 0.0, 3.0, rotate=90, kind="photo"),
            c.SourceSegment("v/a.mp4", 10.0, 30.0, speed=10.0),
        ),
    )
    s = seq.from_recipe(recipe, {"v/a.mp4": "/a.mp4", "p/foto.jpg": "/f.jpg"})
    assert [(b.kind, b.out_start, b.out_end) for b in s.blocks] == [
        ("video", 0.0, 4.0),
        ("photo", 4.0, 7.0),
        ("video", 7.0, 9.0),
    ]
    photo = s.blocks[1]
    assert (photo.key, photo.url, photo.dur, photo.rotate, photo.speed) == (
        "p/foto.jpg",
        "/f.jpg",
        3.0,
        90,
        1.0,
    )
    assert s.block_at(5.0) == 1 and s.total == 9.0
    # the JSON keeps the shape the script reads (a photo's `dur`, a video's stretch)
    data = json.loads(s.to_json())
    assert data["blocks"][1]["dur"] == 3.0 and data["blocks"][1]["src_end"] == 0.0


def test_the_recipe_round_trip_keeps_the_photo() -> None:
    recipe = c.PartRecipe(
        segments=(
            c.SourceSegment("p/foto.jpg", 0.0, 2.0, kind="photo"),
            c.SourceSegment("v/a.mp4", 0.0, 4.0),
        ),
    )
    data = c.to_dict(recipe)
    assert "kind" not in data["segments"][1]  # a video's stretch carries no `kind`
    back = seq.from_recipe(c.from_dict(data), {})
    assert back == seq.from_recipe(recipe, {})
    assert [b.kind for b in back.blocks] == ["photo", "video"]


def test_a_recipe_shows_up_to_three_texts_by_time() -> None:
    recipe = c.PartRecipe(
        segments=(c.SourceSegment("v/a.mp4", 0.0, 9.0),),
        text_layers=(
            c.VideoTextLayer("Hoy", place="top", start_s=0.0, end_s=3.0),
            c.VideoTextLayer("2×1", place="top", start_s=3.0, end_s=6.0),
            c.VideoTextLayer("  ", place="middle"),  # empty: not shown
            c.VideoTextLayer("Pide ya", place="bottom", start_s=5.0, end_s=40.0),
        ),
    )
    s = seq.from_recipe(recipe, {})
    assert [(o.text, o.place, o.start, o.end) for o in s.texts] == [
        ("Hoy", "top", 0.0, 3.0),
        ("2×1", "top", 3.0, 6.0),
        ("Pide ya", "bottom", 5.0, 9.0),  # cut at the video's end
    ]
    assert s.overlays_at(5.5)[0] == [1, 2]
    assert s.overlays_at(3.0)[0] == [1]


def test_a_v1_text_layer_still_reads_as_the_first_text() -> None:
    recipe = c.PartRecipe(
        segments=(c.SourceSegment("v/a.mp4", 0.0, 4.0),),
        text_layer=c.VideoTextLayer("Hoy"),
        text_layers=(c.VideoTextLayer("Mañana", start_s=2.0),),
    )
    assert [o.text for o in seq.from_recipe(recipe, {}).texts] == ["Hoy", "Mañana"]


@pytest.mark.parametrize("t", [2.0, 2.05, 4.95])
def test_a_text_from_two_to_five_is_on(t: float) -> None:
    assert _timeline().overlays_at(t)[0] == [0]


_CSS = (Path(__file__).resolve().parent.parent / "assets" / "qualify-creative.css").read_text(
    encoding="utf-8"
)


@pytest.mark.parametrize("turn", ["90", "180", "270"])
def test_a_turned_photo_turns_like_a_turned_video(turn: str) -> None:
    # the script sets `data-rotate` on the photo `<img>` too; both share the centred base
    for layer in ("video", "poster"):
        assert f'.q-edit-seq .q-edit-preview__{layer}[data-rotate="{turn}"]' in _CSS
    assert ".q-edit-preview__poster,\n.q-edit-preview__video {" in _CSS  # same base


def test_a_quarter_turned_photo_swaps_its_sides() -> None:
    rule = _CSS[_CSS.index('.q-edit-seq .q-edit-preview__poster[data-rotate="270"] {') :]
    body = rule.split("}", 1)[0]
    assert "width: 177.7778%;" in body and "height: 56.25%;" in body
    assert "max-width: none;" in body  # else the global img/video cap squares it


def test_the_card_name_sits_below_the_play_button_and_the_dot_waits_for_a_time() -> None:
    card = _CSS[_CSS.index(".q-edit-seq__card {") :].split("}", 1)[0]
    assert "align-items: flex-end;" in card
    assert ".q-edit-seq .q-edit-preview__time:empty + .q-edit-seq__dot { display: none; }" in _CSS

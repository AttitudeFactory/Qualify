"""ED-13 (m-25029108): «Texto en pantalla» — up to 3 texts over the Clip, each in its own
seconds and place (a text that already carries blocks still follows them). Pure and
offline: no Reflex state, no service."""

from __future__ import annotations

import dataclasses

import pytest

from . import clip_editor_vm as cevm
from . import clip_texts_vm as vm
from . import edit_sequence
from . import editor_preview_contract as contract
from .ui import timeline_vm as tl

# A 12 s video: photo A (0-2), video B (2-8), photo C (8-10), photo D (10-12).
MEDIA: list[dict[str, object]] = [
    {"id": "a", "key": "a", "kind": "photo", "dur": 2.0},
    {"id": "b", "key": "b", "kind": "video", "src_start": 0.0, "src_end": 6.0, "src_len": 9.0},
    {"id": "c", "key": "c", "kind": "photo", "dur": 2.0},
    {"id": "d", "key": "d", "kind": "photo", "dur": 2.0},
]


def _use(uid: str, text: str, start: float, end: float, place: str = "bottom", **kw: object):
    return vm.normalize_text_use(
        {"uid": uid, "text": text, "place": place, "start": start, "end": end, **kw}
    )


def _stuck(
    media: list[dict[str, object]], text: str, *groups: list[str]
) -> list[dict[str, object]]:
    """One text per group, stuck to its blocks with their seconds — what «¿En qué partes
    va?» wrote before it left the panel (Deivid 2026-11-23); a text that carries them is
    still read and followed."""
    spans = cevm.block_spans(media)
    uses: list[dict[str, object]] = []
    for group in groups:
        start, end = cevm.group_span(spans, group)
        uid = vm.new_text_uid(uses)
        uses.append(_use(uid, text, start, end, blocks=group))
    return uses


# -- the model -------------------------------------------------------------------------------


def test_normalize_cuts_the_text_and_fixes_place_and_fade() -> None:
    use = vm.normalize_text_use(
        {"uid": "t1", "text": "x" * 200, "place": "left", "start": -3, "end": None, "fade": 7}
    )
    assert len(str(use["text"])) == contract.VIDEO_TEXT_MAX == 120
    assert use["place"] == "bottom"
    assert use["start"] == 0.0
    assert use["end"] == vm.OPEN_END
    assert use["fade"] == 1.0
    assert use["blocks"] == []


@pytest.mark.parametrize(
    ("raw", "fade"),
    [(None, 0.5), ("nope", 0.5), (0.1, 0.3), (0.34, 0.3), (0.36, 0.4), (0.8, 0.8), (2, 1.0)],
)
def test_fade_is_on_the_tenth_between_0_3_and_1(raw: object, fade: float) -> None:
    assert vm.normalize_fade(raw) == fade


def test_fade_choices_are_eight_steps_in_spanish() -> None:
    choices = vm.fade_choices()
    assert [c["value"] for c in choices] == [
        "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", "1.0",
    ]  # fmt: skip
    assert choices[2]["text"] == "0,5 s"
    assert choices[-1]["text"] == "1 s"


def test_repeated_or_missing_ids_get_new_ones() -> None:
    uses = vm.normalize_text_uses([{"uid": "t1", "text": "a"}, {"uid": "t1"}, {"text": "c"}])
    assert [u["uid"] for u in uses] == ["t1", "t2", "t3"]


def test_block_ids() -> None:
    assert vm.text_block_id("t2") == "texto-t2"
    assert vm.text_uid("texto-t2") == "t2"
    assert vm.text_uid("efecto-u1") == ""
    # ED-10's single text block (`texto-1`, gone with ED-13) is not a text use
    assert vm.text_uid("texto-1") == ""


# -- creating --------------------------------------------------------------------------------


def test_plus_text_goes_from_the_playhead_to_the_end() -> None:
    uses, uid, why = vm.text_from_playhead([], MEDIA, playhead=4.3)
    assert why == "" and uid == "t1"
    (use,) = vm.resolve_text_uses(uses, MEDIA)
    assert (use["start"], use["end"], use["open"]) == (4.5, 12.0, True)


def test_plus_text_near_the_end_still_lasts_one_second() -> None:
    uses, _uid, _why = vm.text_from_playhead([], MEDIA, playhead=11.8)
    (use,) = vm.resolve_text_uses(uses, MEDIA)
    assert (use["start"], use["end"]) == (11.0, 12.0)


def test_plus_text_is_off_with_three_texts_and_says_why() -> None:
    uses = [_use(f"t{n}", "x", n * 3, n * 3 + 2) for n in range(3)]
    assert vm.add_reason(uses, MEDIA) == vm.TEXTS_FULL
    assert vm.TEXTS_FULL == "Tu video puede tener hasta 3 textos. Quita uno para poner otro."
    after, uid, why = vm.text_from_playhead(uses, MEDIA, playhead=0)
    assert (len(after), uid, why) == (3, "", vm.TEXTS_FULL)
    assert vm.add_reason(uses[:2], MEDIA) == ""


def test_plus_text_needs_media() -> None:
    assert vm.add_reason([], []) == cevm.NEEDS_MEDIA


# -- following the blocks --------------------------------------------------------------------


def test_a_stuck_text_follows_its_block_when_it_moves() -> None:
    uses = _stuck(MEDIA, "Pide al 300", ["c"])
    moved = [MEDIA[2], MEDIA[0], MEDIA[1], MEDIA[3]]  # C first now
    (use,) = vm.resolve_text_uses(uses, moved)
    assert (use["start"], use["end"]) == (0.0, 2.0)


def test_a_stuck_text_goes_with_its_blocks() -> None:
    uses = _stuck(MEDIA, "Pide al 300", ["c"])
    without_c = [m for m in MEDIA if m["id"] != "c"]
    assert vm.resolve_text_uses(uses, without_c) == []
    followed, gone = vm.follow_text_media(uses, without_c)
    assert (followed, gone) == ([], 1)


def test_blocks_no_longer_side_by_side_split_the_text() -> None:
    uses = _stuck(MEDIA, "Promo", ["b", "c"])
    apart = [MEDIA[1], MEDIA[0], MEDIA[2], MEDIA[3]]  # B, A, C, D
    followed, gone = vm.follow_text_media(uses, apart)
    assert gone == 0
    assert [(u["uid"], u["blocks"]) for u in followed] == [("t1", ["b"]), ("t2", ["c"])]


def test_a_cut_piece_keeps_its_text() -> None:
    own = [
        {"id": cevm.piece_id("v", 0), "key": "v", "kind": "video", "src_start": 0.0,
         "src_end": 4.0, "src_len": 8.0},
        {"id": cevm.piece_id("v", 1), "key": "v", "kind": "video", "src_start": 4.0,
         "src_end": 8.0, "src_len": 8.0},
    ]  # fmt: skip
    uses = _stuck(own, "Final", [cevm.piece_id("v", 1)])
    # «Cortar» splits piece 0: the old piece 1 is piece 2 now
    mapping = cevm.cut_mapping("v", 2, 0)
    cut = [
        {**own[0], "id": cevm.piece_id("v", 0), "src_end": 2.0},
        {**own[0], "id": cevm.piece_id("v", 1), "src_start": 2.0},
        {**own[1], "id": cevm.piece_id("v", 2)},
    ]
    followed, _gone = vm.follow_text_media(uses, cut, mapping)
    assert followed[0]["blocks"] == [cevm.piece_id("v", 2)]
    assert (followed[0]["start"], followed[0]["end"]) == (4.0, 8.0)


def test_own_seconds_stay_inside_a_shorter_video() -> None:
    uses = [_use("t1", "x", 9.0, 11.5)]
    short = MEDIA[:2]  # 8 s
    (use,) = vm.resolve_text_uses(uses, short)
    assert (use["start"], use["end"]) == (7.0, 8.0)


# -- moving and trimming ---------------------------------------------------------------------


def test_nudge_moves_an_edge_half_a_second_and_unsticks() -> None:
    uses = _stuck(MEDIA, "x", ["a", "b"])
    after = vm.nudge_text(uses, MEDIA, "t1", "end", -0.5)
    assert (after[0]["start"], after[0]["end"], after[0]["blocks"]) == (0.0, 7.5, [])


def test_nudge_never_leaves_the_video_nor_goes_under_one_second() -> None:
    uses = [_use("t1", "x", 0.0, 1.0)]
    assert vm.nudge_text(uses, MEDIA, "t1", "start", -0.5)[0]["start"] == 0.0
    assert vm.nudge_text(uses, MEDIA, "t1", "start", 0.5)[0]["start"] == 0.0
    assert vm.nudge_text(uses, MEDIA, "t1", "end", -0.5)[0]["end"] == 1.0
    late = [_use("t1", "x", 10.0, 12.0)]
    assert vm.nudge_text(late, MEDIA, "t1", "end", 0.5)[0]["end"] == 12.0


def test_moving_the_start_of_an_open_text_keeps_it_to_the_end() -> None:
    uses = [_use("t1", "x", 0.0, vm.OPEN_END)]
    after = vm.nudge_text(uses, MEDIA, "t1", "start", 0.5)
    assert (after[0]["start"], after[0]["end"]) == (0.5, vm.OPEN_END)


@pytest.mark.parametrize(
    "edit",
    [
        lambda uses: vm.nudge_text(uses, MEDIA, "t1", "start", 0.5),
        lambda uses: vm.nudge_text(uses, MEDIA, "t1", "end", -0.5),
        lambda uses: vm.shift_text(uses, MEDIA, "t1", 0.5),
    ],
)
def test_moving_or_trimming_by_hand_unsticks_the_text(edit) -> None:  # type: ignore[no-untyped-def]
    # Deivid 2026-11-20: as an effect, a text moved or trimmed by hand keeps its own
    # seconds — moving its blocks afterwards no longer moves it
    uses = _stuck(MEDIA, "Pide al 300", ["c"])
    after = edit(uses)
    assert after[0]["blocks"] == []
    (before_move,) = vm.resolve_text_uses(after, MEDIA)
    moved = [MEDIA[2], MEDIA[0], MEDIA[1], MEDIA[3]]  # C first now
    (after_move,) = vm.resolve_text_uses(after, moved)
    assert (after_move["start"], after_move["end"]) == (before_move["start"], before_move["end"])


def test_arrows_move_the_whole_text_half_a_second_inside_the_video() -> None:
    uses = [_use("t1", "x", 2.0, 4.0)]
    right = vm.shift_text(uses, MEDIA, "t1", 0.5)
    assert (right[0]["start"], right[0]["end"]) == (2.5, 4.5)
    edge = [_use("t1", "x", 10.0, 12.0)]
    assert vm.shift_text(edge, MEDIA, "t1", 0.5) == edge
    left = vm.shift_text([_use("t1", "x", 0.0, 2.0)], MEDIA, "t1", -0.5)
    assert left[0]["start"] == 0.0


def test_place_text_fade_and_remove() -> None:
    uses = [_use("t1", "x", 0, 2), _use("t2", "y", 2, 4)]
    assert vm.set_place(uses, "t1", "top")[0]["place"] == "top"
    assert vm.set_place(uses, "t1", "left")[0]["place"] == "bottom"
    assert vm.set_text(uses, "t2", "z" * 130)[1]["text"] == "z" * 120
    assert vm.set_fade(uses, "t2", "0.8")[1]["fade"] == 0.8
    assert [u["uid"] for u in vm.remove_text(uses, "t1")] == ["t2"]
    assert vm.drop_empty([*uses, _use("t3", "  ", 0, 1)]) == uses


# -- two texts in one place (criterion 3) ----------------------------------------------------


def test_two_texts_on_top_at_once_warn_and_block_next() -> None:
    uses = [_use("t1", "2×1 hoy", 0, 4, "top"), _use("t2", "Solo hoy", 3, 6, "top")]
    resolved = vm.resolve_text_uses(uses, MEDIA)
    assert vm.text_clashes(resolved) == [("t1", "t2", "top")]
    assert vm.texts_problem(resolved) == (
        "Aquí se verían dos textos arriba. Pon uno en otro lugar o en otro momento."
    )
    assert vm.next_blocked(resolved)
    assert vm.clashing_uids(resolved) == ["t1", "t2"]


def test_the_clash_is_solved_by_place_or_by_time() -> None:
    uses = [_use("t1", "a", 0, 4, "top"), _use("t2", "b", 3, 6, "top")]
    other_place = vm.set_place(uses, "t2", "bottom")
    assert not vm.next_blocked(vm.resolve_text_uses(other_place, MEDIA))
    later = vm.shift_text(uses, MEDIA, "t2", 0.5)
    after = vm.shift_text(later, MEDIA, "t2", 0.5)  # starts at 4: meets, does not overlap
    assert not vm.next_blocked(vm.resolve_text_uses(after, MEDIA))


def test_an_empty_text_never_clashes() -> None:
    uses = [_use("t1", "a", 0, 4, "top"), _use("t2", "", 0, 4, "top")]
    assert not vm.next_blocked(vm.resolve_text_uses(uses, MEDIA))


@pytest.mark.parametrize(
    ("place", "where"), [("top", "arriba"), ("middle", "en el medio"), ("bottom", "abajo")]
)
def test_clash_line_says_the_place(place: str, where: str) -> None:
    assert vm.clash_line(place).startswith(f"Aquí se verían dos textos {where}.")


def test_more_than_three_after_a_split_blocks_next() -> None:
    uses = [_use(f"t{n}", "x", n * 2, n * 2 + 1, "top") for n in range(4)]
    resolved = vm.resolve_text_uses(uses, MEDIA)
    assert vm.texts_problem(resolved) == vm.too_many_texts_line(4)
    assert vm.next_blocked(resolved)


# -- the recipe (criterion 1) ----------------------------------------------------------------


def test_three_texts_at_different_moments_go_in_text_layers_in_order() -> None:
    uses = [
        _use("t1", "Pide al 300", 9.0, vm.OPEN_END, "bottom"),
        _use("t2", "2×1 hoy", 0.0, 3.0, "top", fade=0.8),
        _use("t3", "Solo martes", 4.0, 7.0, "middle"),
    ]
    resolved = vm.resolve_text_uses(uses, MEDIA)
    layers = vm.text_layers_for_recipe(resolved, total=12.0)
    assert [layer.text for layer in layers] == ["2×1 hoy", "Solo martes", "Pide al 300"]
    assert [(layer.start_s, layer.end_s) for layer in layers] == [
        (0.0, 3.0),
        (4.0, 7.0),
        (9.0, None),
    ]
    assert [layer.place for layer in layers] == ["top", "middle", "bottom"]
    assert layers[0].fade_s == 0.8 and layers[1].fade_s == contract.VIDEO_TEXT_FADE_DEFAULT_S
    assert all(layer.layout_id == contract.TEXT_LAYOUT_ID for layer in layers)
    recipe = vm.with_texts(contract.PartRecipe(), layers)
    assert recipe.text_layers == layers and recipe.text_layer == layers[0]
    assert contract.recipe_problems(recipe) == []
    data = contract.to_dict(recipe)
    assert [t["text"] for t in data["text_layers"]] == ["2×1 hoy", "Solo martes", "Pide al 300"]  # type: ignore[index, union-attr]
    assert contract.from_dict(data).text_layers == layers


def test_one_text_over_the_whole_video_is_the_recipe_of_today() -> None:
    uses, uid, _why = vm.text_from_playhead([], MEDIA, playhead=0.0)
    uses = vm.set_text(uses, uid, "  ¡2×1 en shawarma!  ")
    layers = vm.text_layers_for_recipe(vm.resolve_text_uses(uses, MEDIA), total=12.0)
    today = cevm.recipe_of(
        video_key="",
        start=0,
        end=0,
        rotate=0,
        effects=(),
        speed=1,
        text="¡2×1 en shawarma!",
        place="bottom",
    ).text_layers
    # ED-13 (contract): the editor puts a NEW text leaving with a fade too («Desaparece»);
    # ED-10's one text kept leaving at once — the only difference
    assert layers == tuple(dataclasses.replace(t, motion_out="fade") for t in today)
    assert today[0].motion_out == "none"


def test_a_clash_makes_a_recipe_the_backend_refuses() -> None:
    uses = [_use("t1", "a", 0, 4, "top"), _use("t2", "b", 3, 6, "top")]
    layers = vm.text_layers_for_recipe(vm.resolve_text_uses(uses, MEDIA), total=12.0)
    assert "texts_overlap" in contract.recipe_problems(vm.with_texts(contract.PartRecipe(), layers))


def test_empty_texts_never_travel() -> None:
    uses = [_use("t1", "", 0, 2), _use("t2", "Hola", 2, 4)]
    layers = vm.text_layers_for_recipe(vm.resolve_text_uses(uses, MEDIA))
    assert [layer.text for layer in layers] == ["Hola"]


def test_an_end_at_the_video_end_is_left_open() -> None:
    uses = _stuck(MEDIA, "Fin", ["d"])
    (layer,) = vm.text_layers_for_recipe(vm.resolve_text_uses(uses, MEDIA), total=12.0)
    assert (layer.start_s, layer.end_s) == (10.0, None)


# -- the preview (criterion 4) and the names (criterion 5) -----------------------------------


def test_the_preview_shows_each_text_only_in_its_seconds() -> None:
    uses = [_use("t1", "2×1 hoy", 0.0, 3.0, "top"), _use("t2", "Pide al 300", 9.0, 12.0)]
    resolved = vm.resolve_text_uses(uses, MEDIA)
    overlays = vm.timeline_text_overlays(resolved)
    seq = edit_sequence.from_timeline(MEDIA, overlays, {})
    assert [(t.text, t.start, t.end, t.place) for t in seq.texts] == [
        ("2×1 hoy", 0.0, 3.0, "top"),
        ("Pide al 300", 9.0, 12.0, "bottom"),
    ]
    tol = vm.PREVIEW_TOLERANCE_S
    assert vm.texts_on_at(resolved, 0.0) == ["t1"]
    assert vm.texts_on_at(resolved, 3.0 - tol) == ["t1"]
    assert vm.texts_on_at(resolved, 3.0 + tol) == []
    assert vm.texts_on_at(resolved, 9.0 - tol) == []
    assert vm.texts_on_at(resolved, 9.0 + tol) == ["t2"]


def test_each_block_reads_text_from_to() -> None:
    assert vm.text_name("2×1 hoy", 0.0, 3.0) == "Texto «2×1 hoy», de 0:00 a 0:03"
    assert vm.text_name("Pide al 300", 9.5, 12.0) == "Texto «Pide al 300», de 0:09,5 a 0:12"
    # the timeline's own rows say the same
    resolved = vm.resolve_text_uses([_use("t1", "2×1 hoy", 0.0, 3.0)], MEDIA)

    (row,) = tl.overlay_blocks(vm.timeline_text_overlays(resolved), "text", 12.0)  # type: ignore[arg-type]
    assert row["name"] == vm.text_name("2×1 hoy", 0.0, 3.0)
    assert row["id"] == "texto-t1"


def test_panel_row() -> None:
    (use,) = vm.resolve_text_uses([_use("t1", "Hola", 2.0, 5.5, "middle", fade=0.7)], MEDIA)
    row = vm.text_panel_row(use, MEDIA)
    # A1 (Deivid 2026-11-23): no «Empieza»/«Termina» — the line under the field
    assert not {k for k in row if k.startswith(("start_", "end_"))}
    assert row["time_line"] == (
        "Se ve de 0:02 a 0:05,5. Para cambiarlo, arrastra las puntas de su bloque, abajo."
    )
    assert row["fade"] == "0.7" and row["fade_text"] == "0,7 s"
    assert row["panel"] == "Texto en pantalla · de 0:02 a 0:05,5"
    assert not hasattr(vm, "START_LABEL") and not hasattr(vm, "END_LABEL")


# -- the old single text ---------------------------------------------------------------------


def test_the_old_text_becomes_text_one() -> None:
    uses = vm.migrate_legacy_text(text="2×1", place="top", start=1.5, end=-1.0)
    assert uses == [
        {
            "uid": "t1",
            "text": "2×1",
            "place": "top",
            "start": 1.5,
            "end": vm.OPEN_END,
            "blocks": [],
            "fade": 0.5,
            "layout": "scrim",
            "motion_in": "fade",
            "motion_out": "none",  # ED-10's text left at once: it keeps doing so
            "exit_set": False,
            "box_color": "",  # ED-13: its background's own colour
            "text_color": "",  # round 3: white letters
            "size": "medium",  # round 4: «Mediana»
        }
    ]


def test_migration_keeps_texts_already_there_and_ignores_empty() -> None:
    have = [_use("t1", "Nuevo", 0, 2)]
    assert vm.migrate_legacy_text(text="Viejo", uses=have) == have
    assert vm.migrate_legacy_text(text="   ") == []


def test_the_editor_opens_with_no_text_and_plus_text_starts_empty() -> None:
    # Deivid 2026-11-20: the generated hook is never copied in; the owner writes it
    assert not hasattr(vm, "initial_text_uses")
    assert vm.migrate_legacy_text(text="") == []
    uses, uid, why = vm.text_from_playhead([], MEDIA, playhead=0.0)
    assert why == "" and uses[0]["text"] == ""
    assert vm.text_layers_for_recipe(vm.resolve_text_uses(uses, MEDIA)) == ()


# -- the fade row (Deivid 2026-11-20) --------------------------------------------------------


def test_the_length_row_says_what_it_changes() -> None:
    """Deivid 2026-11-23: ONE length for the entrance and the exit; «Tarda en entrar»
    when it leaves «De golpe»; with «Letra por letra» it changes only the exit."""
    assert vm.fade_line(0.5) == "Tarda en entrar y salir: 0,5 s"
    assert vm.fade_line(1.0) == "Tarda en entrar y salir: 1 s"
    (use,) = vm.resolve_text_uses([_use("t1", "Hola", 0, 6)], MEDIA)
    row = vm.text_panel_row(use, MEDIA)
    assert row["fade_value"] == "Tarda en entrar y salir: 0,5 s" and row["fade_shown"] == "1"
    # the slider is named by what it changes (Deivid 2026-11-24: no «− 0,1 s / + 0,1 s»)
    assert row["fade_label"] == "Tarda en entrar y salir"
    assert not any(key.startswith(("fade_less", "fade_more")) for key in row)
    still = vm.text_panel_row({**use, "motion_out": "none"}, MEDIA)
    assert still["fade_value"] == "Tarda en entrar: 0,5 s"
    assert still["fade_label"] == "Tarda en entrar"
    typing = vm.text_panel_row({**use, "motion_in": "typewriter"}, MEDIA)
    assert typing["fade_value"] == "Tarda en salir: 0,5 s"
    both = vm.text_panel_row({**use, "motion_in": "typewriter", "motion_out": "none"}, MEDIA)
    assert both["fade_shown"] == "" and both["fade_value"] == ""


@pytest.mark.parametrize(
    ("raw", "fade"),
    [([0.4], 0.4), ([0.6000000000000001], 0.6), ([0.2], 0.3), ([1.4], 1.0), (0.7, 0.7),
     ("0.8", 0.8), ([], None), (None, None), (["x"], None), ([float("nan")], None)],
)  # fmt: skip
def test_the_fade_slider_stays_on_its_tenths_and_in_range(raw: object, fade: float | None) -> None:
    # Deivid 2026-11-24: a slider from 0,3 to 1 s, 0,1 s a step (Radix sends a list)
    assert vm.fade_from_slider(raw) == fade


def test_the_fade_slider_sets_only_that_text() -> None:
    uses = [_use("t1", "Hola", 0, 2), _use("t2", "Chao", 2, 4)]
    out = vm.set_fade(uses, "t1", vm.fade_from_slider([0.8]))
    assert (out[0]["fade"], out[1]["fade"]) == (0.8, uses[1]["fade"])
    assert vm.set_fade(uses, "t9", 0.8) == uses


# -- subtitles take «Abajo» (Deivid 2026-11-23) ---------------------------------------------


def test_with_subtitles_abajo_is_off_in_the_panel() -> None:
    (use,) = vm.resolve_text_uses([_use("t1", "Hola", 0, 2, "top")], MEDIA)
    off = vm.text_panel_row(use, MEDIA, subtitles=True)
    assert off["bottom_off"] == "1"
    assert (
        off["place_note"]
        == vm.SUBTITLES_BOTTOM_LINE
        == (
            "Abajo se ven los subtítulos y tu texto se taparía. Elige otra posición o apaga los "
            "subtítulos."
        )
    )
    assert off["covered_note"] == ""  # it is «Arriba»: nothing covers it
    on = vm.text_panel_row(use, MEDIA)
    assert (on["bottom_off"], on["place_note"], on["covered_note"]) == ("", "", "")
    assert not vm.place_offered("bottom", subtitles=True)
    assert vm.place_offered("top", subtitles=True) and vm.place_offered("middle", subtitles=True)
    assert vm.place_offered("bottom") and not vm.place_offered("left")


def test_with_subtitles_a_text_cannot_be_put_abajo() -> None:
    uses = [_use("t1", "Hola", 0, 2, "top")]
    assert vm.set_place(uses, "t1", "bottom", subtitles=True)[0]["place"] == "top"
    assert vm.set_place(uses, "t1", "middle", subtitles=True)[0]["place"] == "middle"
    assert vm.set_place(uses, "t1", "bottom")[0]["place"] == "bottom"
    # a new text goes in the middle while the subtitles take the bottom (UX 2026-11-23)
    assert vm.default_place(subtitles=True) == "middle"
    assert vm.default_place() == "bottom"


def test_a_text_already_abajo_is_not_moved_and_stops_siguiente() -> None:
    """Subtitles turned on with a text already «Abajo»: it stays there (never moved by
    itself), its block shows the warning tone and «Siguiente» waits until it moves."""
    resolved = vm.resolve_text_uses(
        [_use("t1", "Hola", 0, 2), _use("t2", "Chao", 4, 6, "top")], MEDIA
    )
    assert [u["place"] for u in resolved] == ["bottom", "top"]
    assert vm.texts_problem(resolved, subtitles=True) == vm.SUBTITLES_BOTTOM_LINE
    assert vm.next_blocked(resolved, subtitles=True)
    assert vm.under_subtitles(resolved, subtitles=True) == ["t1"]
    assert vm.clashing_uids(resolved, subtitles=True) == ["t1"]
    rows = vm.timeline_text_overlays(resolved, subtitles=True)
    assert [(r["uid"], r["warn"]) for r in rows] == [("t1", True), ("t2", False)]
    # without subtitles nothing stops it
    assert vm.texts_problem(resolved) == "" and not vm.next_blocked(resolved)
    # beside its control: it is under the subtitles («Abajo» itself is off, said under it)
    row = vm.text_panel_row(resolved[0], MEDIA, subtitles=True)
    assert (
        row["covered_note"]
        == vm.SUBTITLES_COVERED_LINE
        == ("Este texto queda debajo de los subtítulos.")
    )
    assert row["bottom_off"] == "1" and row["place"] == "bottom"
    assert vm.text_panel_row(resolved[0], MEDIA)["covered_note"] == ""
    assert not any(r["warn"] for r in vm.timeline_text_overlays(resolved))
    # moved to «Arriba» or «En el medio», «Siguiente» goes on
    moved = vm.resolve_text_uses(vm.set_place(resolved, "t1", "middle", subtitles=True), MEDIA)
    assert not vm.next_blocked(moved, subtitles=True)


def test_a_clash_of_two_texts_is_said_before_the_subtitles() -> None:
    uses = [_use("t1", "a", 0, 4, "top"), _use("t2", "b", 3, 6, "top"), _use("t3", "c", 8, 9)]
    resolved = vm.resolve_text_uses(uses, MEDIA)
    assert vm.texts_problem(resolved, subtitles=True) == vm.clash_line("top")
    assert vm.clashing_uids(resolved, subtitles=True) == ["t1", "t2", "t3"]


def test_the_subtitles_refusal_code_is_the_contracts() -> None:
    from typing import get_args

    assert vm.SUBTITLES_CODE == "text_bottom_with_subtitles"
    assert vm.SUBTITLES_CODE in get_args(contract.RecipeProblem)
    assert cevm.refusal_line([vm.SUBTITLES_CODE]) == vm.SUBTITLES_BOTTOM_LINE


def test_a_clash_marks_both_blocks_warn() -> None:
    """Criterion 3 on the timeline: the two texts «Arriba» that overlap show the warning
    tone; the third, elsewhere, does not."""
    uses = [_use("t1", "a", 0, 4, "top"), _use("t2", "b", 3, 6, "top"), _use("t3", "c", 8, 9)]
    rows = vm.timeline_text_overlays(vm.resolve_text_uses(uses, MEDIA))
    assert [(r["uid"], r["warn"]) for r in rows] == [("t1", True), ("t2", True), ("t3", False)]
    blocks = tl.overlay_blocks(rows, "text", 12.0)  # type: ignore[arg-type]
    assert [b["warn"] for b in blocks] == ["1", "1", ""]
    assert blocks[0]["name"] == "Texto «a», de 0:00 a 0:04"  # criterion 5, warn or not


def test_the_focus_script_names_the_field() -> None:
    assert vm.FIELD_ID == "clip-text-field"
    assert "getElementById('clip-text-field')" in vm.focus_field_script()


# -- ED-13 C: the background («Fondo de las letras», Deivid 2026-11-23) ------------------------


def test_a_new_text_is_drawn_over_sombra_and_the_owner_picks_another() -> None:
    uses, uid, _ = vm.text_from_playhead([], MEDIA, playhead=0.0, text="Hoy")
    assert uses[0]["layout"] == "scrim"
    assert [key for key, _name, _what in vm.LAYOUT_CHOICES] == list(contract.VIDEO_TEXT_LAYOUTS)
    assert [name for _key, name, _what in vm.LAYOUT_CHOICES] == [
        "Sombra",
        "Franja",
        "Recuadro de tu color",
        "Sin fondo",
    ]
    band = vm.set_layout(uses, uid, "band")
    assert band[0]["layout"] == "band"
    assert vm.set_layout(band, uid, "plate") == band  # not one of the four: left
    (layer,) = vm.text_layers_for_recipe(vm.resolve_text_uses(band, MEDIA), total=12.0)
    assert (layer.layout_id, layer.layout_version) == ("band", contract.TEXT_LAYOUT_VERSION)
    row = vm.text_panel_row(vm.resolve_text_uses(band, MEDIA)[0], MEDIA)
    # the summary names the strip's colour too (UX 2026-11-23): black by default
    assert row["layout_summary"] == "Fondo de las letras: Franja, negro"


def test_the_preview_row_carries_the_box_and_its_legible_ink() -> None:
    palette = ["#0F766E", "#FFFFFF", "#F8FAFC"]
    band = vm.preview_text_row(0, text="Hoy", place="top", layout="band", palette=palette)
    assert (band["layout"], band["bg"], band["ink"], band["long"]) == (
        "band",
        "#111111",  # «Franja»: always dark and neutral, white letters
        "#FFFFFF",
        "false",
    )
    fill = vm.preview_text_row(1, text="x" * 40, place="top", layout="brand_fill", palette=[])
    assert (fill["bg"], fill["ink"], fill["long"], fill["index"]) == (
        "#0F766E",
        "#FFFFFF",
        "true",
        "1",
    )
    scrim = vm.preview_text_row(0, text="Hoy", place="top", layout="nope")
    assert (scrim["layout"], scrim["bg"], scrim["ink"]) == ("scrim", "transparent", "#FFFFFF")


# -- ED-13 D: how it enters and leaves («Cómo entra y sale») ----------------------------------


def test_a_new_text_enters_and_leaves_with_a_fade() -> None:
    uses, _uid, _ = vm.text_from_playhead([], MEDIA, playhead=0.0, text="Hoy")
    assert (uses[0]["motion_in"], uses[0]["motion_out"], uses[0]["exit_set"]) == (
        "fade",
        "fade",
        False,
    )
    assert [name for _k, name in vm.MOTION_IN_CHOICES] == [
        "Aparece",
        "Sube",
        "Crece",
        "Letra por letra",
    ]
    assert [name for _k, name in vm.MOTION_OUT_CHOICES] == [
        "Desaparece",
        "Baja",
        "Se encoge",
        "De golpe",
    ]


@pytest.mark.parametrize(
    ("entrance", "exit_"),
    [("slide", "slide"), ("zoom", "zoom"), ("fade", "fade"), ("typewriter", "fade")],
)
def test_the_exit_goes_with_the_entrance_until_the_owner_picks_it(
    entrance: str, exit_: str
) -> None:
    uses, uid, _ = vm.text_from_playhead([], MEDIA, playhead=0.0, text="Hoy")
    moved = vm.set_motion_in(uses, uid, entrance)
    assert (moved[0]["motion_in"], moved[0]["motion_out"]) == (entrance, exit_)


def test_an_exit_the_owner_chose_stays() -> None:
    uses, uid, _ = vm.text_from_playhead([], MEDIA, playhead=0.0, text="Hoy")
    uses = vm.set_motion_out(uses, uid, "none")
    assert uses[0]["exit_set"] is True
    uses = vm.set_motion_in(uses, uid, "slide")
    assert (uses[0]["motion_in"], uses[0]["motion_out"]) == ("slide", "none")
    assert vm.set_motion_out(uses, uid, "typewriter") == uses  # not an exit
    assert vm.set_motion_in(uses, uid, "spin") == uses


def test_letra_por_letra_only_up_to_40_characters() -> None:
    long = "Promoción de 2×1 todos los martes y jueves"
    assert len(long) == 42
    uses, uid, _ = vm.text_from_playhead([], MEDIA, playhead=0.0, text=long)
    assert vm.set_motion_in(uses, uid, "typewriter") == uses  # off: not taken
    row = vm.text_panel_row(vm.resolve_text_uses(uses, MEDIA)[0], MEDIA)
    assert row["typewriter_off"] == "1"
    assert row["typewriter_note"] == "Solo para textos de hasta 40 letras. El tuyo tiene 42."
    short = vm.set_text(uses, uid, "2×1 hoy")
    typing = vm.set_motion_in(short, uid, "typewriter")
    row = vm.text_panel_row(vm.resolve_text_uses(typing, MEDIA)[0], MEDIA)
    assert (row["typewriter_off"], row["typewriter_note"]) == ("", "")
    assert row["typewriter_slow"] == "Tu video tardará un poco más en estar listo."
    # written longer afterwards: «Siguiente» waits and says why
    grown = vm.set_text(typing, uid, long)
    resolved = vm.resolve_text_uses(grown, MEDIA)
    assert vm.texts_problem(resolved) == vm.TYPEWRITER_TOO_LONG_LINE
    assert vm.next_blocked(resolved)


def test_a_short_text_shortens_its_animation_and_says_so() -> None:
    uses = [_use("t1", "Hoy", 0.0, 1.0, fade=0.5)]
    row = vm.text_panel_row(vm.resolve_text_uses(uses, MEDIA)[0], MEDIA)
    assert row["cut_note"] == (
        "Tu texto dura 1 s: la animación se acorta para que se alcance a leer."
    )
    long_enough = [_use("t1", "Hoy", 0.0, 1.5, fade=0.5)]
    assert vm.text_panel_row(vm.resolve_text_uses(long_enough, MEDIA)[0], MEDIA)["cut_note"] == ""


def test_the_recipe_writes_the_motions_and_the_schema_keeps_defaults_out() -> None:
    uses, uid, _ = vm.text_from_playhead([], MEDIA, playhead=0.0, text="Hoy")
    uses = vm.set_motion_in(uses, uid, "zoom")
    (layer,) = vm.text_layers_for_recipe(vm.resolve_text_uses(uses, MEDIA), total=12.0)
    assert (layer.motion_in, layer.motion_out) == ("zoom", "zoom")
    data = contract.to_dict(vm.with_texts(contract.PartRecipe(), (layer,)))
    raw = data["text_layers"][0]  # type: ignore[index]
    assert (raw["motion_in"], raw["motion_out"]) == ("zoom", "zoom")
    plain = vm.set_motion_in(vm.set_motion_out(uses, uid, "none"), uid, "fade")
    (layer,) = vm.text_layers_for_recipe(vm.resolve_text_uses(plain, MEDIA), total=12.0)
    data = contract.to_dict(vm.with_texts(contract.PartRecipe(), (layer,)))
    raw = data["text_layers"][0]  # type: ignore[index]
    assert "motion_in" not in raw and "motion_out" not in raw  # the schema's: left out


def test_the_timeline_overlays_carry_how_the_preview_draws_them() -> None:
    uses = [_use("t1", "Hoy", 0.0, 3.0, layout="shadow", motion_in="slide", motion_out="zoom")]
    (row,) = vm.timeline_text_overlays(vm.resolve_text_uses(uses, MEDIA))
    assert (row["layout"], row["motion_in"], row["motion_out"], row["fade"]) == (
        "shadow",
        "slide",
        "zoom",
        0.5,
    )
    seq = edit_sequence.from_timeline(MEDIA, [row], {})
    (text,) = seq.to_dict()["texts"]
    assert (text["layout"], text["motion_in"], text["motion_out"], text["fade"]) == (
        "shadow",
        "slide",
        "zoom",
        0.5,
    )


def test_a_chosen_motion_is_shown_from_a_moment_before() -> None:
    (use,) = vm.resolve_text_uses([_use("t1", "Hoy", 2.0, 8.0, fade=0.5)], MEDIA)
    assert vm.motion_demo(use, "in", 12.0) == (1.7, 2.8)
    assert vm.motion_demo(use, "out", 12.0) == (7.2, 8.3)
    (whole,) = vm.resolve_text_uses([_use("t1", "Hoy", 0.0, 12.0)], MEDIA)
    assert vm.motion_demo(whole, "in", 12.0) == (0.0, 0.8)
    assert vm.motion_demo(whole, "out", 12.0)[1] == 12.0  # never past the video
    assert "showMotion(h, 1.7, 2.8, false)" in vm.show_motion_script(1.7, 2.8)
    assert "showMotion(h, 1.7, 2.8, true)" in vm.show_motion_script(1.7, 2.8, force=True)


def test_the_servers_motion_refusals_read_in_spanish() -> None:
    assert cevm.refusal_line(["typewriter_text_too_long"]) == vm.TYPEWRITER_TOO_LONG_LINE
    assert cevm.refusal_line(["unknown_text_motion"]) == vm.MOTION_REFUSED_LINE
    assert vm.TYPEWRITER_CODE in contract.RecipeProblem.__args__  # type: ignore[attr-defined]
    assert vm.MOTION_CODE in contract.RecipeProblem.__args__  # type: ignore[attr-defined]


def test_a_text_block_has_its_handles_on_purpose() -> None:
    """A1: its times change only on the timeline — `handles` "1", not by accident."""
    resolved = vm.resolve_text_uses([_use("t1", "Hoy", 0.0, 3.0)], MEDIA)
    (row,) = tl.overlay_blocks(vm.timeline_text_overlays(resolved), "text", 12.0)  # type: ignore[arg-type]
    assert row["handles"] == "1"
    # the handles' bubble and `aria-valuetext` keep «Empieza»/«Termina»
    assert (row["start_value"], row["end_value"]) == ("Empieza 0:00", "Termina 0:03")


# -- ED-13 B: the brand's typography -----------------------------------------------------


def test_the_brand_font_family() -> None:
    assert vm.brand_font_family("") == ""
    assert vm.brand_font_family("Montserrat") == '"Montserrat", sans-serif'
    assert vm.brand_font_family("Montserrat", has_file=True) == (
        '"QualifyBrandHeading", "Montserrat", sans-serif'
    )
    assert vm.brand_font_family("", has_file=True) == '"QualifyBrandHeading", sans-serif'
    assert vm.brand_font_family('Ev"il};') == '"Evil", sans-serif'  # nothing breaks the CSS


# -- ED-13 (Deivid 2026-11-23): the colour of «Franja» / «Recuadro de tu color» -------------


def test_the_box_colour_chips_are_the_palette_then_black_and_white() -> None:
    chips = vm.box_color_chips(["#0f766e", "nope", "#F4C2C2", "#0F766E", "#111", "#2563EB"])
    assert chips == [
        ("#0F766E", "Color principal de tu marca"),
        ("#F4C2C2", "Tercer color de tu marca"),  # named by its place in the palette
        ("#111111", "Color 5 de tu marca"),  # «#111» is black already: no «Negro» after it
        ("#2563EB", "Color 6 de tu marca"),
        ("#FFFFFF", "Blanco"),
    ]
    assert vm.box_color_chips([]) == [("#111111", "Negro"), ("#FFFFFF", "Blanco")]
    assert vm.brand_color_name(1) == "Segundo color de tu marca"


def test_a_picked_colour_is_kept_only_where_a_box_takes_it() -> None:
    palette = ["#0F766E", "#F4C2C2"]
    uses = [_use("t1", "Hoy", 0.0, 3.0, layout="band")]
    picked = vm.set_box_color(uses, "t1", "#f4c2c2", palette)
    assert picked[0]["box_color"] == "#F4C2C2"
    assert vm.set_box_color(uses, "t1", "#ABCDEF", palette) == uses  # not a chip
    assert vm.set_box_color(uses, "t9", "#F4C2C2", palette) == uses  # no such text
    # the default's chip stores none: the text keeps its default shape
    assert vm.set_box_color(picked, "t1", "#111111", palette)[0]["box_color"] == ""
    scrim = [_use("t1", "Hoy", 0.0, 3.0)]
    assert vm.set_box_color(scrim, "t1", "#F4C2C2", palette) == scrim
    # a new background starts on its own default; the same one keeps the colour
    assert vm.set_layout(picked, "t1", "band")[0]["box_color"] == "#F4C2C2"
    assert vm.set_layout(picked, "t1", "brand_fill")[0]["box_color"] == ""
    # normalized: capitals, anything else is the default
    assert vm.normalize_text_use({"uid": "t1", "box_color": "#abcdef"})["box_color"] == "#ABCDEF"
    assert vm.normalize_text_use({"uid": "t1", "box_color": "rojo"})["box_color"] == ""
    assert vm.normalize_text_use({"uid": "t1"})["box_color"] == ""


def test_the_recipe_and_the_preview_carry_the_picked_colour() -> None:
    palette = ["#0F766E", "#F4C2C2"]
    uses = vm.set_box_color([_use("t1", "Hoy", 0.0, 3.0, layout="band")], "t1", "#F4C2C2", palette)
    resolved = vm.resolve_text_uses(uses, MEDIA)
    (layer,) = vm.text_layers_for_recipe(resolved, total=12.0)
    assert layer.box_color == "#F4C2C2"
    data = contract.to_dict(vm.with_texts(contract.PartRecipe(), (layer,)))
    assert data["text_layers"][0]["box_color"] == "#F4C2C2"  # type: ignore[index]
    # «Sin fondo» never sends a colour, even one left in the use
    shadow = [{**uses[0], "layout": "shadow"}]
    (plain,) = vm.text_layers_for_recipe(vm.resolve_text_uses(shadow, MEDIA), total=12.0)
    assert plain.box_color is None
    (overlay,) = vm.timeline_text_overlays(resolved)
    assert overlay["box_color"] == "#F4C2C2"
    seq = edit_sequence.from_timeline(MEDIA, [overlay], {})
    assert seq.texts[0].box_color == "#F4C2C2"
    row = vm.preview_text_row(
        0, text="Hoy", place="bottom", layout="band", palette=palette, box_color="#F4C2C2"
    )
    assert (row["bg"], row["ink"]) == ("#F4C2C2", "#111111")
    default = vm.preview_text_row(0, text="Hoy", place="bottom", layout="band", palette=palette)
    assert (default["bg"], default["ink"]) == ("#111111", "#FFFFFF")


def test_the_panel_names_the_colour_and_warns_about_sin_fondo() -> None:
    palette = ["#0F766E"]
    band = vm.resolve_text_uses([_use("t1", "Hoy", 0.0, 3.0, layout="band")], MEDIA)[0]
    row = vm.text_panel_row(band, MEDIA, palette=palette)
    assert row["box_color_chosen"] == "Elegido: negro"
    assert row["shadow_note"] == ""
    fill = vm.resolve_text_uses([_use("t1", "Hoy", 0.0, 3.0, layout="brand_fill")], MEDIA)[0]
    rows = vm.box_color_rows(fill, palette)
    assert [(r["name"], r["on"], r["ink"]) for r in rows] == [
        ("Color principal de tu marca", "1", "#FFFFFF"),
        ("Negro", "", "#FFFFFF"),
        ("Blanco", "", "#111111"),
    ]
    shadow = vm.resolve_text_uses([_use("t1", "Hoy", 0.0, 3.0, layout="shadow")], MEDIA)[0]
    row = vm.text_panel_row(shadow, MEDIA, palette=palette)
    assert row["shadow_note"] == (
        "Si tu video es claro, las letras pueden perderse: elige un color oscuro para tus letras."
    )
    # round 3: «Sin fondo» shows the chips too, for its letters — white by default
    assert (row["box_color_shown"], row["chips_for_text"]) == ("1", "1")
    assert row["box_color_title"] == "Color de las letras"
    assert row["box_color_chosen"] == "Elegido: blanco"
    assert [(r["name"], r["on"]) for r in vm.box_color_rows(shadow, palette)] == [
        ("Color principal de tu marca", ""),
        ("Negro", ""),
        ("Blanco", "1"),
    ]
    assert vm.text_panel_row(band, MEDIA, palette=palette)["chips_for_text"] == ""
    # «Sin fondo» says what it is now: clean letters, nothing behind
    assert {k: w for k, _n, w in vm.LAYOUT_CHOICES}["shadow"] == (
        "Solo tus letras, limpias, directo sobre tu video."
    )
    assert cevm.refusal_line(["bad_text_box_color"]) == vm.BOX_COLOR_REFUSED_LINE
    assert cevm.refusal_line(["bad_text_color"]) == vm.TEXT_COLOR_REFUSED_LINE


# -- ED-13 round 3 (Deivid 2026-11-23): «Sin fondo»'s letters' colour ------------------------


def test_the_letters_colour_is_kept_only_without_a_background() -> None:
    palette = ["#0F766E"]
    uses = [_use("t1", "Hoy", 0.0, 3.0, layout="shadow")]
    dark = vm.set_text_color(uses, "t1", "#111111", palette)
    assert dark[0]["text_color"] == "#111111"
    assert vm.set_text_color(uses, "t1", "#ABCDEF", palette) == uses  # not a chip
    assert vm.set_text_color(dark, "t1", "#FFFFFF", palette)[0]["text_color"] == ""  # white
    band = [_use("t1", "Hoy", 0.0, 3.0, layout="band")]
    assert vm.set_text_color(band, "t1", "#111111", palette) == band
    # another background starts on white again; the box colour setter leaves it alone
    assert vm.set_layout(dark, "t1", "band")[0]["text_color"] == ""
    assert vm.set_box_color(dark, "t1", "#0F766E", palette) == dark
    assert vm.normalize_text_use({"uid": "t1", "text_color": "#0f766e"})["text_color"] == "#0F766E"
    row = vm.text_panel_row(vm.resolve_text_uses(dark, MEDIA)[0], MEDIA, palette=palette)
    assert row["layout_summary"] == "Fondo de las letras: Sin fondo, letras negras"
    assert row["layout_choice"] == "Sin fondo, letras negras"
    assert row["box_color_chosen"] == "Elegido: negro"
    brand = vm.set_text_color(uses, "t1", "#0F766E", palette)
    brand_row = vm.text_panel_row(vm.resolve_text_uses(brand, MEDIA)[0], MEDIA, palette=palette)
    assert brand_row["layout_choice"] == "Sin fondo, letras en tu color principal"
    white_row = vm.text_panel_row(vm.resolve_text_uses(uses, MEDIA)[0], MEDIA, palette=palette)
    assert white_row["layout_choice"] == "Sin fondo, letras blancas"


def test_the_recipe_and_the_preview_carry_the_letters_colour() -> None:
    palette = ["#0F766E"]
    uses = vm.set_text_color(
        [_use("t1", "Hoy", 0.0, 3.0, layout="shadow")], "t1", "#111111", palette
    )
    resolved = vm.resolve_text_uses(uses, MEDIA)
    (layer,) = vm.text_layers_for_recipe(resolved, total=12.0)
    assert (layer.text_color, layer.box_color) == ("#111111", None)
    data = contract.to_dict(vm.with_texts(contract.PartRecipe(), (layer,)))
    assert data["text_layers"][0]["text_color"] == "#111111"  # type: ignore[index]
    # another background never sends it, even one left in the use
    band = [{**uses[0], "layout": "band"}]
    (plain,) = vm.text_layers_for_recipe(vm.resolve_text_uses(band, MEDIA), total=12.0)
    assert plain.text_color is None
    (overlay,) = vm.timeline_text_overlays(resolved)
    assert overlay["text_color"] == "#111111"
    seq = edit_sequence.from_timeline(MEDIA, [overlay], {})
    assert seq.texts[0].text_color == "#111111"
    row = vm.preview_text_row(
        0, text="Hoy", place="top", layout="shadow", palette=palette, text_color="#111111"
    )
    assert (row["bg"], row["ink"]) == ("transparent", "#111111")
    white = vm.preview_text_row(0, text="Hoy", place="top", layout="shadow", palette=palette)
    assert white["ink"] == "#FFFFFF"
    ignored = vm.preview_text_row(
        0, text="Hoy", place="top", layout="band", palette=palette, text_color="#0F766E"
    )
    assert ignored["ink"] == "#FFFFFF"


# -- round 3 (Deivid 2026-11-23): every section of the panel folds, with a summary ----------


def test_the_folded_sections_say_what_is_chosen() -> None:
    assert vm.place_choice("top") == "Arriba"
    assert vm.place_choice("nope") == "Abajo"  # the default place
    assert vm.place_choice("bottom", covered=True) == "Abajo, debajo de los subtítulos"
    assert vm.motion_choice("slide", "none") == "Sube · De golpe"
    # «¿En qué partes va?» left the panel (Deivid 2026-11-23): no summary for it
    assert not hasattr(vm, "parts_summary") and not hasattr(vm, "part_rows")
    use = vm.resolve_text_uses([_use("t1", "Hoy", 0.0, 3.0, layout="band")], MEDIA)[0]
    row = vm.text_panel_row(use, MEDIA)
    assert row["place_choice"] == vm.PLACE_TEXTS[str(use["place"])]
    assert row["layout_choice"] == "Franja, negro"
    assert row["motion_choice"] == "Aparece · Desaparece"


def test_the_letters_size_is_picked_and_grande_needs_a_short_text() -> None:
    """ED-13 round 4 (Deivid 2026-11-23: «3 tamaños», option A): «Mediana» by default;
    «Grande» off past `LARGE_MAX` characters with its reason; a «Grande» text written
    longer goes back to «Mediana»; the recipe carries the size only when it is not
    «Mediana»."""
    uses = vm.normalize_text_uses([{"uid": "t1", "text": "2×1 hoy", "start": 0, "end": 4}])
    assert uses[0]["size"] == "medium"
    assert vm.size_choice("medium") == "Tamaño: Mediana"
    assert vm.LARGE_MAX == 40
    uses = vm.set_size(uses, "t1", "large")
    assert uses[0]["size"] == "large"
    assert vm.size_choice(uses[0]["size"]) == "Tamaño: Grande"
    assert vm.set_size(uses, "t1", "huge") == uses
    # written longer: back to «Mediana», and the state is told
    longer = vm.set_text(uses, "t1", "a" * 41)
    assert longer[0]["size"] == "medium"
    assert vm.size_went_down(uses, longer, "t1")
    assert not vm.size_went_down(longer, vm.set_text(longer, "t1", "b" * 41), "t1")
    # a long text: «Grande» is off and says why, never taken
    assert vm.set_size(longer, "t1", "large") == longer
    row = vm.text_panel_row(longer[0], [])
    assert (row["large_off"], row["large_note"]) == ("1", vm.LARGE_NOTE)
    assert vm.LARGE_NOTE == "Tu texto es largo: con Grande no cabe. Acórtalo para usarlo."
    short = vm.set_size(vm.set_text(longer, "t1", "Hoy"), "t1", "small")
    row = vm.text_panel_row(short[0], [])
    assert (row["size"], row["size_choice"], row["large_off"]) == ("small", "Tamaño: Pequeña", "")
    assert (
        vm.preview_text_row(0, text="Hoy", place="top", layout="scrim", size="small")["size"]
        == "small"
    )
    assert vm.preview_text_row(0, text="Hoy", place="top", layout="scrim")["size"] == "medium"

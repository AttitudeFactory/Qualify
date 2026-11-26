"""ED-00b (m-25029104): the «Arma tu video» timeline pattern and its `/design` sample.

Offline: the view model's copy (§4 of the proposal), the half-second magnet, the
no-gap media track and the keyboard edits; the component renders the group, the three
tracks, the playhead slider, the handles as sliders and a live status line; the CSS keeps
1 s = 44 px and 44 px handles, slides the tracks inside their own box and switches to the
desktop layout on the component's container; and the `/design` section renders.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import reflex as rx

from Qualify.ui import timeline as tl
from Qualify.ui import timeline_vm as vm

_ASSETS = Path(__file__).parent.parent / "assets"
_CSS = (_ASSETS / "qualify-creative.css").read_text(encoding="utf-8")

_MEDIA = [
    {"id": "v1", "kind": "video", "src_start": 0.0, "src_end": 4.0, "src_len": 15.0},
    {"id": "v2", "kind": "video", "src_start": 4.0, "src_end": 9.0, "src_len": 15.0},
    {"id": "p3", "kind": "photo", "dur": 2.0},
]
_OVERLAYS = [
    {"id": "t1", "kind": "text", "label": "2×1 hoy", "start": 0.0, "end": 6.0},
    {"id": "e1", "kind": "effect", "label": "Vapor", "start": 2.0, "end": 9.0},
]


def _has(rendered: str, text: str) -> bool:
    escaped = json.dumps(text)[1:-1]
    return any(form in rendered for form in (text, escaped, escaped.replace("\\", "\\\\")))


# ---------------------------------------------------------------------------------------
# View model
# ---------------------------------------------------------------------------------------


def test_clock_and_amount_speak_spanish() -> None:
    assert vm.clock(0) == "0:00"
    assert vm.clock(4.5) == "0:04,5"
    assert vm.clock(62) == "1:02"
    assert vm.clock(4.3) == "0:04,5"  # the magnet
    assert vm.amount(5) == "5" and vm.amount(4.5) == "4,5"
    assert vm.playhead_text(5, 12) == "0:05 de 0:12"
    # m-25129389: the playhead's words to the tenth, as the blocks and the total
    assert vm.playhead_text(0, 4.7) == "0:00 de 0:04,7"
    assert vm.playhead_text(1.25, 59.96) == "0:01,3 de 1:00"


def test_media_track_has_no_gaps_and_full_names() -> None:
    rows = vm.media_blocks(_MEDIA)
    assert [(r["start"], r["length"]) for r in rows] == [("0", "4"), ("4", "5"), ("9", "2")]
    assert vm.total_seconds(_MEDIA) == 11
    assert rows[1]["name"] == "Video 2 de 3, usas de 0:04 a 0:09, dura 5 s"
    assert rows[1]["panel"] == "Video 2 · usas 0:04 a 0:09 · 5 s"
    assert rows[2]["name"] == "Foto 3 de 3, se ve 2 s"
    assert rows[2]["panel"] == "Foto 3 · 2 s"
    assert rows[1]["start_handle"] == "Inicio de video 2"
    assert rows[1]["end_handle"] == "Final de video 2"
    assert rows[1]["help"] == "Usa las flechas para cambiarlo de lugar."
    assert rows[1]["help_id"] == "q-tl-help-move"
    # A photo has only its end handle («Duración», 1–5 s).
    assert rows[2]["has_start"] == "" and rows[2]["end_label"] == "Duración"
    assert rows[2]["end_text"] == "Se ve 2 s"


# m-25129389: a video block reads its length and times to the tenth, as the total does.


def _video(block_id: str, start: float, end: float, src_len: float, speed: float = 1) -> dict:
    return {
        "id": block_id,
        "kind": "video",
        "src_start": start,
        "src_end": end,
        "src_len": src_len,
        "speed": speed,
    }


def test_a_video_of_4_7_s_says_4_7_like_the_total() -> None:
    from Qualify import editor_preview_contract as contract

    media = [_video("v1", 0.0, 4.7, 4.7)]
    (row,) = vm.media_blocks(media)
    total = contract.seconds_text(vm.total_seconds(media))
    assert total == "4,7"
    assert row["name"] == "Video 1 de 1, usas de 0:00 a 0:04,7, dura 4,7 s"
    assert row["panel"] == "Video 1 · usas 0:00 a 0:04,7 · 4,7 s"
    assert row["secs"] == "4,7 s"
    assert (row["start_text"], row["end_text"]) == ("0:00", "0:04,7")
    # the handles keep their own exact clock (to the hundredth)
    assert row["end_value"] == "Hasta 0:04,7"


def test_a_cut_at_1_48_s_adds_up_to_the_total() -> None:
    from Qualify import editor_preview_contract as contract

    media = [_video("v1", 0.0, 1.48, 4.7), _video("v2", 1.48, 4.7, 4.7)]
    first, second = vm.media_blocks(media)
    assert first["name"] == "Video 1 de 2, usas de 0:00 a 0:01,5, dura 1,5 s"
    assert second["name"] == "Video 2 de 2, usas de 0:01,5 a 0:04,7, dura 3,2 s"
    assert (first["secs"], second["secs"]) == ("1,5 s", "3,2 s")
    assert second["panel"] == "Video 2 · usas 0:01,5 a 0:04,7 · 3,2 s"
    shown = [float(r["secs"].removesuffix(" s").replace(",", ".")) for r in (first, second)]
    total = float(contract.seconds_text(vm.total_seconds(media)).replace(",", "."))
    assert total == 4.7
    assert abs(sum(shown) - total) <= 0.1 + 1e-9


def test_a_photo_still_reads_its_half_seconds() -> None:
    (row,) = vm.media_blocks([{"id": "p1", "kind": "photo", "dur": 2.5}])
    assert row["name"] == "Foto 1 de 1, se ve 2,5 s"
    assert row["panel"] == "Foto 1 · 2,5 s"
    assert row["secs"] == "2,5 s"
    assert row["end_text"] == "Se ve 2,5 s"


def test_a_video_at_x2_reads_its_length_to_the_tenth() -> None:
    from Qualify import editor_preview_contract as contract

    media = [_video("v1", 0.0, 4.7, 4.7, speed=2)]
    (row,) = vm.media_blocks(media)
    length = contract.seconds_text(vm.total_seconds(media))  # 2,35 s, as the total rounds
    assert row["name"] == f"Video 1 de 1, usas de 0:00 a 0:04,7, dura {length} s"
    assert row["secs"] == f"{length} s"
    assert row["speed_tag"] == "×2"
    two = vm.media_blocks([_video("v1", 0.0, 6.6, 10.0, speed=2)])[0]
    assert two["name"] == "Video 1 de 1, usas de 0:00 a 0:06,6, dura 3,3 s"


def test_the_tenth_helpers_match_the_preview_contract() -> None:
    from Qualify import editor_preview_contract as contract

    values = (0, 0.04, 0.05, 1.15, 1.25, 1.48, 1.75, 2.35, 3.22, 4.7, 9.96, 12.04)
    for value in (*values, 59.95, 59.96, 61.25, 119.96):
        assert vm.amount_tenth(value) == contract.seconds_text(value), value
        assert vm.clock_tenth(value) == contract.clock_text(value), value


def test_a_half_tenth_rounds_up_and_a_minute_carries() -> None:
    from Qualify import editor_preview_contract as contract

    assert vm.amount_tenth(1.25) == "1,3" and vm.amount_tenth(1.75) == "1,8"
    assert vm.clock_tenth(1.25) == "0:01,3" and vm.clock_tenth(1.75) == "0:01,8"
    assert vm.amount_tenth(4.7) == "4,7" and vm.amount_tenth(1.15) == "1,2"  # float noise
    assert vm.amount_tenth(0.04) == "0" and vm.amount_tenth(9.96) == "10"
    # never «0:60»: the rounded second carries into the minute
    assert vm.clock_tenth(59.95) == "1:00" and vm.clock_tenth(59.96) == "1:00"
    assert vm.clock_tenth(119.96) == "2:00"
    assert contract.clock_text(59.96) == "1:00" and contract.clock_text(119.96) == "2:00"
    assert contract.seconds_text(1.25) == "1,3" and contract.seconds_text(1.75) == "1,8"


def test_overlay_names() -> None:
    texts = vm.overlay_blocks(_OVERLAYS, "text", 11)
    effects = vm.overlay_blocks(_OVERLAYS, "effect", 11)
    assert texts[0]["name"] == "Texto «2×1 hoy», de 0:00 a 0:06"
    assert effects[0]["name"] == "Vapor, de 0:02 a 0:09"
    assert effects[0]["panel"] == "Vapor · de 0:02 a 0:09"
    # ED-10 UX review: a text or an effect says what its arrows do; ED-04: an effect's
    # ↑/↓ change its row
    assert texts[0]["help"] == "Usa las flechas para cambiar cuándo sale."
    assert texts[0]["help_id"] == "q-tl-help-time"
    assert effects[0]["help"] == (
        "Usa las flechas izquierda y derecha para cambiar cuándo sale, y arriba y abajo "
        "para pasarlo a otra pista."
    )
    assert effects[0]["help_id"] == "q-tl-help-effect"
    assert effects[0]["start_label"] == "Empieza" and effects[0]["end_label"] == "Termina"


def test_rows_are_serialisable_strings() -> None:
    rows = vm.media_blocks(_MEDIA) + vm.overlay_blocks(_OVERLAYS, "effect", 11)
    assert all(isinstance(v, str) for row in rows for v in row.values())
    json.dumps(rows)


def test_nudge_snaps_clamps_and_closes_the_gap() -> None:
    media, overlays = vm.nudge(_MEDIA, _OVERLAYS, "v1", "end", -0.5)
    assert media[0]["src_end"] == 3.5
    assert [r["start"] for r in vm.media_blocks(media)] == ["0", "3.5", "8.5"]
    # Never shorter than 1 s, never past the source.
    media, _ = vm.nudge(_MEDIA, _OVERLAYS, "v1", "start", 10)
    assert media[0]["src_start"] == 3.0
    media, _ = vm.nudge(_MEDIA, _OVERLAYS, "v2", "end", 30)
    assert media[1]["src_end"] == 15.0
    # A photo lasts 1–5 s and only its end moves.
    media, _ = vm.nudge(_MEDIA, _OVERLAYS, "p3", "end", 9)
    assert media[2]["dur"] == 5.0
    media, _ = vm.nudge(_MEDIA, _OVERLAYS, "p3", "start", 1)
    assert media[2]["dur"] == 2.0
    # The input is never mutated.
    assert _MEDIA[0]["src_end"] == 4.0


def test_shorter_video_cuts_overlays_to_the_new_end() -> None:
    overlays = [{"id": "e", "kind": "effect", "label": "Vapor", "start": 2.0, "end": 11.0}]
    media, overlays = vm.nudge(_MEDIA, overlays, "v2", "end", -2)
    assert vm.total_seconds(media) == 9
    assert overlays[0]["end"] == 9


def test_keyboard_move_and_shift() -> None:
    moved = vm.move(_MEDIA, "v2", -1)
    assert [m["id"] for m in moved] == ["v2", "v1", "p3"]
    assert vm.moved_text(moved, "v2") == "Moviste el video 1."
    assert vm.moved_text(vm.move(_MEDIA, "p3", -1), "p3") == "Moviste la foto 2."
    assert [m["id"] for m in vm.move(_MEDIA, "v1", -1)] == ["v1", "v2", "p3"]
    shifted = vm.shift(_OVERLAYS, "e1", 0.5, 11)
    assert (shifted[1]["start"], shifted[1]["end"]) == (2.5, 9.5)
    assert vm.shift(_OVERLAYS, "e1", 10, 11)[1]["end"] == 11
    assert vm.timed_text(_OVERLAYS, "e1") == "Cambiaste cuándo sale Vapor."
    assert vm.timed_text(_OVERLAYS, "t1") == "Cambiaste cuándo sale el texto."


def test_actions_follow_the_proposal() -> None:
    labels = {key: [label for label, _ in items] for key, items in vm.ACTIONS.items()}
    # ED-10: «Pedir una idea» fits the orbit's pill (16 characters at most)
    assert [text for _, _, text in vm.ADD_OPTIONS] == [
        "Foto o video",
        "Texto",
        "Efecto",
        "Pedir una idea",
    ]
    assert all(len(text) <= 16 for _, _, text in vm.ADD_OPTIONS)
    assert [icon for _, icon, _ in vm.ADD_OPTIONS] == [
        "image-plus",
        "type",
        "sparkles",
        "lightbulb",
    ]
    # ED-10: «Velocidad» and «Duración» live in the panel only (one place each)
    assert labels["video"] == ["Cortar aquí", "Girar", "Quitar"]
    assert labels["photo"] == ["Girar", "Quitar"]
    assert labels["text"] == ["Editar texto", "Quitar"]
    assert labels["effect"] == ["Cambiar efecto", "Quitar"]
    assert all(len(items) <= 4 for items in vm.ACTIONS.values())


# ---------------------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------------------


class _State(rx.State):
    media: list[dict[str, str]] = vm.media_blocks(_MEDIA)
    texts: list[dict[str, str]] = []
    effects: list[dict[str, str]] = vm.overlay_blocks(_OVERLAYS, "effect", 11)
    ticks: list[dict[str, str]] = vm.ticks(11)
    selected: str = "v2"
    status: str = ""

    @rx.event
    def pick(self, block_id: str) -> None:
        self.selected = block_id

    @rx.event
    def key(self, block_id: str, edge: str, key: str) -> None:
        pass


def _rendered() -> str:
    return str(
        tl.timeline(
            media=_State.media,
            texts=_State.texts,
            effects=_State.effects,
            ticks=_State.ticks,
            total="11",
            selected=_State.selected,
            on_select=_State.pick,
            status=_State.status,
            on_key=_State.key,
        ).render()
    )


def test_component_renders_the_accessible_anatomy() -> None:
    rendered = _rendered()
    assert _has(rendered, "Línea de tiempo de tu video") and '"group"' in rendered
    for name in ("Fotos y videos", "Textos", "Efectos"):
        assert _has(rendered, name)
    assert '"list"' in rendered and '"listitem"' in rendered
    assert "q-tl__scrub" in rendered and '"range"' in rendered
    assert _has(rendered, "Momento del video")
    assert '"slider"' in rendered and "aria-valuetext" in rendered
    assert '"status"' in rendered
    assert "aria-pressed" in rendered or "ariaPressed" in rendered
    # An empty track draws no hint text; its accessible name says it is empty.
    assert "Toca + y elige" not in rendered and "Haz clic en + y elige" not in rendered
    assert _has(rendered, "Pista de textos vacía")
    assert _has(rendered, "Pista de efectos vacía")
    # the blocks' help: one hidden span each, read through `aria-describedby`
    assert "aria-describedby" in rendered and 'aria-description"' not in rendered
    assert "q-tl-help-move" in rendered and "q-tl-help-time" in rendered
    assert _has(rendered, "Usa las flechas para cambiar cuándo sale.")
    assert "data-q-timeline" in rendered and "--tl-total" in rendered


def test_action_bar_and_panel_render() -> None:
    actions = str(
        tl.timeline_actions(_State.selected, on_add=lambda key: rx.console_log(key)).render()
    )
    for label in ("Cortar aquí", "Girar", "Editar texto", "Cambiar efecto"):
        assert _has(actions, label)
    # The chosen block's buttons are the kit's glass (`surface`), in a glass island.
    assert '"surface"' in actions and '"soft"' not in actions.split("q-orbit")[0]
    assert "q-island" in actions and "q-tl-island" in actions
    row = rx.Var.create(vm.media_blocks(_MEDIA)[1])
    panel = str(
        tl.timeline_panel(
            row,
            on_nudge=lambda *a: rx.console_log("n"),
            on_done=_State.pick(""),
            on_speed=lambda *a: rx.console_log("s"),
            on_place=lambda *a: rx.console_log("p"),
        ).render()
    )
    assert _has(panel, "− ½ s") and _has(panel, "+ ½ s") and _has(panel, "Listo")
    assert "q-source-seg" in panel
    for name in ("Velocidad normal", "5 veces más rápido", "10 veces más rápido"):
        assert _has(panel, name)
    for place in ("Arriba", "En el medio", "Abajo"):
        assert _has(panel, place)


def test_add_is_the_orbit_with_four_options() -> None:
    rendered = str(tl.timeline_add(lambda key: rx.console_log(key)).render())
    assert "q-orbit-trigger" in rendered and _has(rendered, "Agregar")
    for key, _, text in vm.ADD_OPTIONS:
        assert f'"data-orbit-key":"{key}"' in rendered.replace(" ", "") or key in rendered
        assert _has(rendered, text)
    assert rendered.count("q-orbit-pill") == 4
    # Nothing chosen: the orbit; a block chosen: its bar.
    assert "q-orbit-trigger" in str(
        tl.timeline_actions(_State.selected, on_add=lambda key: rx.console_log(key)).render()
    )


def test_speed_and_place_in_the_view_model() -> None:
    media = vm.set_speed(_MEDIA, "v2", "10")
    rows = vm.media_blocks(media)
    assert rows[1]["speed"] == "10" and rows[1]["speed_tag"] == "×10"
    assert rows[1]["length"] == "0.5"  # 5 s of source at ×10
    assert vm.set_speed(_MEDIA, "v2", "7")[1].get("speed", 1) == 1  # only offered speeds
    assert vm.set_speed(_MEDIA, "p3", "5")[2].get("speed") is None  # a photo has none
    texts = vm.overlay_blocks(vm.set_place(_OVERLAYS, "t1", "bottom"), "text", 11)
    assert texts[0]["place"] == "bottom"
    assert [label for _, label, _ in vm.SPEEDS] == [
        "×1",
        "×2",
        "×3",
        "×5",
        "×10",
        "×20",
    ]


def test_lens_and_island_exist() -> None:
    script = (_ASSETS / tl.SCRIPT).read_text(encoding="utf-8")
    assert "q-glass-blob" in script and "q-glass-blob__surface" in script
    assert "prefers-reduced-motion" in script
    assert ".q-tl__canvas > .q-glass-blob { z-index: 1; }" in _CSS
    assert ".q-tl-island" in _CSS and "@container q-tl-stack (min-width: 52rem)" in _CSS
    # The lens and the island reuse the menu's classes: no copy of their material here.
    block = _CSS[_CSS.index("Round 2 (Deivid, 2026-11-14)") :]
    # (ED-12's off option only switches the glass OFF: `backdrop-filter: none`)
    assert "backdrop-filter: blur" not in block and "backdrop-filter: var(" not in block
    stack = str(tl.timeline_layout(rx.text("t"), rx.text("a"), rx.text("p")).render())
    assert "q-tl-stack__actions" in stack and "q-tl-stack__panel" in stack


def test_blocks_show_a_thumb() -> None:
    rendered = _rendered()
    assert "q-thumb" in rendered


def test_script_exists_and_owns_the_playhead() -> None:
    script = (_ASSETS / tl.SCRIPT).read_text(encoding="utf-8")
    assert "window.__qTimeline" in script
    assert "aria-valuetext" in script and "--tl-t" in script and "scrollLeft" in script


def test_css_phone_scale_handles_and_desktop_switch() -> None:
    assert "container: q-tl / inline-size" in _CSS
    assert "@container q-tl (min-width: 52rem)" in _CSS
    assert "padding-inline: 50cqw" in _CSS  # the playhead can sit on 0:00 and the end
    assert ".q-tl__scroller {\n  overflow-x: auto;" in _CSS
    handle = _CSS[_CSS.index(".q-tl__handle {") :]
    assert "width: 44px;" in handle[: handle.index("}")]  # a finger's target (§3.8)
    # ED-11 review: with a mouse the zone that grabs is the visible bar (16 px), so the
    # cursor, the hover and the time bubble sit on it — the finger keeps its 44 px
    grip = _CSS[_CSS.index(".q-tl__grip {") :]
    assert "width: 16px;" in grip[: grip.index("}")]
    # …and a touch laptop (a fine primary pointer plus a finger) keeps the 44 px too
    fine = _CSS[_CSS.index("@media (pointer: fine) and (not (any-pointer: coarse)) {") :]
    rule = fine[: fine.index("}") + 1]
    assert ".q-tl__handle { width: 16px; }" in rule
    assert "@media (pointer: fine) {" not in _CSS
    assert "@media (pointer: coarse)" not in _CSS  # nothing narrows the finger's target
    assert ".q-tl__lane--media { height: 56px; }" in _CSS
    assert vm.PX_PER_SECOND == 44
    # ED-11 review: high contrast hides the picture (the name never sits on a photo) and
    # shows the icon under it; a block with a picture has a stronger edge, but the chosen
    # one keeps its accent border (a later rule with one attribute more)
    forced = _CSS[_CSS.index("@media (forced-colors: active) {") :]
    forced = forced[: forced.index("\n}") + 2]
    assert ".q-tl__pic { display: none; }" in forced
    assert ".q-tl__pic-fallback" in forced
    pic_edge = '.q-tl__block[data-tl-pic="1"] { border-color: var(--gray-a8); }'
    chosen_edge = (
        '.q-tl__block[aria-pressed="true"][data-tl-pic="1"] { border-color: var(--accent-9); }'
    )
    assert pic_edge in _CSS and chosen_edge in _CSS
    assert _CSS.index(chosen_edge) > _CSS.index(pic_edge)
    assert _CSS.index(pic_edge) > _CSS.index(
        '.q-tl__block[aria-pressed="true"] { border: 2px solid var(--accent-9); }'
    )
    fallback = _CSS[_CSS.index(".q-tl__pic-fallback {") :]
    assert "z-index: -2;" in fallback[: fallback.index("}")]  # under `.q-tl__pic` (-1)
    # Only theme variables: no hex colour in the timeline's rules.
    block = _CSS[_CSS.index("── The timeline of «Arma tu video»") :]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", block)


# ---------------------------------------------------------------------------------------
# /design
# ---------------------------------------------------------------------------------------


def test_design_section_renders() -> None:
    from Qualify import styleguide_page as page

    rendered = str(page._timeline_section().render())
    assert page.TIMELINE_ANCHOR in rendered
    assert _has(rendered, "Línea de tiempo") and "q-tl" in rendered
    assert "q-tl-actions" in rendered


def test_design_sample_data_matches_the_brief() -> None:
    from Qualify import styleguide_page as page

    rows = vm.media_blocks(page._TL_MEDIA)
    assert [r["kind"] for r in rows] == ["video", "video", "photo"]
    assert rows[1]["name"] == "Video 2 de 3, usas de 0:04 a 0:09, dura 5 s"
    kinds = {item["kind"] for item in page._TL_OVERLAYS}
    assert kinds == {"text", "effect"}


def test_keys_reach_the_screen_through_one_hidden_button() -> None:
    rendered = _rendered()
    assert "data-tl-key-trigger" in rendered and tl.KEY_GLOBAL in rendered
    script = (_ASSETS / tl.SCRIPT).read_text(encoding="utf-8")
    assert "data-tl-key-trigger" in script and "__qTimelineKey" in script
    assert "ArrowLeft" in script and "Escape" in script and "preventDefault" in script


# ---------------------------------------------------------------------------------------
# ED-10 m-25026648: drag and drop, values beside ± ½ s, the bar's name
# ---------------------------------------------------------------------------------------


def test_move_to_drops_a_block_at_an_index_without_gaps() -> None:
    assert [m["id"] for m in vm.move_to(_MEDIA, "v1", 2)] == ["v2", "p3", "v1"]
    assert [m["id"] for m in vm.move_to(_MEDIA, "p3", 0)] == ["p3", "v1", "v2"]
    assert [m["id"] for m in vm.move_to(_MEDIA, "v2", 99)] == ["v1", "p3", "v2"]
    assert [m["id"] for m in vm.move_to(_MEDIA, "v2", -5)] == ["v2", "v1", "p3"]
    assert [m["id"] for m in vm.move_to(_MEDIA, "nope", 0)] == ["v1", "v2", "p3"]
    moved = vm.move_to(_MEDIA, "p3", 0)
    rows = vm.media_blocks(moved)
    assert [r["start"] for r in rows] == ["0", "2", "6"]  # laid end to end again
    assert vm.total_seconds(moved) == vm.total_seconds(_MEDIA)


def test_px_to_seconds_and_the_magnet() -> None:
    assert vm.px_to_seconds(88, 44) == 2.0
    assert vm.px_to_seconds(10, 0) == 0.0
    assert vm.track_scale(phone=True) == 44.0
    assert vm.track_scale(phone=False, width=960, total=12) == 80.0
    assert vm.track_scale(phone=False, width=960, total=0) == 44.0
    # 11 px at 44 px/s = 0.25 s: a half rounds up, like the script
    assert vm.seconds_from_drag(2.0, 11, 44, length=3.0, total=12.0) == 2.5
    assert vm.seconds_from_drag(2.0, 10, 44, length=3.0, total=12.0) == 2.0
    assert vm.seconds_from_drag(2.0, -9999, 44, length=3.0, total=12.0) == 0.0
    assert vm.seconds_from_drag(2.0, 9999, 44, length=3.0, total=12.0) == 9.0


def test_each_nudge_shows_its_value() -> None:
    rows = vm.media_blocks(_MEDIA)
    assert (rows[1]["start_value"], rows[1]["end_value"]) == ("Desde 0:04", "Hasta 0:09")
    assert (rows[2]["start_value"], rows[2]["end_value"]) == ("", "Se ve 2 s")
    text = vm.overlay_blocks(_OVERLAYS, "text", 11)[0]
    assert (text["start_value"], text["end_value"]) == ("Empieza 0:00", "Termina 0:06")
    panel = str(
        tl.timeline_panel(
            rx.Var.create(rows[1]), on_nudge=lambda *a: rx.console_log("n"), on_done=_State.pick("")
        ).render()
    )
    assert "start_value" in panel and "end_value" in panel


def test_the_bar_is_named_after_the_chosen_block() -> None:
    assert vm.actions_label("Video 1") == "Acciones de Video 1"
    assert vm.actions_label("") == "Acciones"
    rendered = str(
        tl.timeline_actions(
            rx.Var.create("video"), on_add=lambda key: rx.console_log(key), label="Video 1"
        ).render()
    )
    assert _has(rendered, "Acciones de Video 1")
    only = {"video": (("Quitar", "trash-2"),)}
    mine = str(
        tl.timeline_actions(
            rx.Var.create("video"), on_add=lambda key: rx.console_log(key), actions=only
        ).render()
    )
    assert _has(mine, "Quitar") and not _has(mine, "Cortar aquí")


def test_a_drop_reaches_the_screen_through_a_hidden_button() -> None:
    class _Drag(_State):
        @rx.event
        def drop(self, block_id: str, what: str, value: float) -> None:
            pass

    rendered = str(
        tl.timeline(
            media=_Drag.media,
            texts=_Drag.texts,
            effects=_Drag.effects,
            ticks=_Drag.ticks,
            total="11",
            selected=_Drag.selected,
            on_select=_Drag.pick,
            on_drag=_Drag.drop,
        ).render()
    )
    assert "data-tl-drag-trigger" in rendered and tl.DROP_GLOBAL in rendered
    assert "data-tl-start" in rendered and "data-tl-len" in rendered
    assert "data-tl-no-drag" not in rendered
    assert _has(rendered, vm.LIFT_HINT)
    # without `on_drag` nothing drags
    assert "data-tl-no-drag" in _rendered()
    drag = (_ASSETS / tl.DRAG_SCRIPT).read_text(encoding="utf-8")
    assert "data-tl-drag-trigger" in drag and "__qTimelineDrop" in drag
    assert "q-tl__scroller" in drag  # positions measured against the tracks' scroll
    assert "touchmove" in drag and "contextmenu" in drag


def test_the_playhead_script_follows_the_review() -> None:
    script = (_ASSETS / tl.SCRIPT).read_text(encoding="utf-8")
    # no observer on the whole page; the observers go when the timeline does
    assert ".observe(document.body" not in script
    assert "disconnect" in script and "sweep" in script
    # reduced motion read when it is used, not once at load
    assert "function reduceMotion()" in script
    # crossing the phone/desktop line puts the tracks back on the playhead
    assert "__qTlMode" in script
    # Escape inside a block's panel gives the block back; the panel comes into view
    assert "data-tl-panel" in script and "scrollIntoView" in script
    assert "prefers-reduced-motion" in script
    mount = tl.timeline_script()
    assert "on_mount" in mount.event_triggers and "on_unmount" in mount.event_triggers
    assert "sweep" in str(mount.event_triggers["on_unmount"])


def test_the_bar_can_go_under_the_tracks() -> None:
    stack = str(tl.timeline_layout(rx.text("t"), rx.text("a"), bar_below=True).render())
    assert "q-tl-stack--bar-below" in stack
    assert ".q-tl-stack--bar-below .q-tl-stack__actions { order: 2; }" in _CSS

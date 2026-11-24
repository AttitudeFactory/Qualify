"""ED-13 (m-25029108) «Texto en pantalla» in the Clip editor's state: up to 3 texts put
with «+ Texto» from the marker, each in its own seconds (the timeline changes them)
and place; two in one place at once (or one «Abajo» under the subtitles, Deivid
2026-11-23) stop «Siguiente». Criteria 1–5 of the ticket, the old one-text session's
migration, and the texts following «Fotos y videos». A standalone `CreativeState`,
handlers called through `.fn` (`test_creative_state.py` explains why)."""

from __future__ import annotations

import pytest

from . import clip_editor_vm, clip_texts_vm
from . import editor_preview_contract as contract
from .creative_state import CreativeState
from .test_clip_editor_state import _KEY, _PHOTO, _SECOND, _put_text, _scripts, _timeline_state


@pytest.fixture
def editor_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", True)


def _put_on(state: CreativeState, text: str, *parts: str, place: str = "") -> str:
    """Over the stretch of `parts`: the marker at its start, «+ Texto», typed, its
    end dragged to the stretch's end on the timeline (left open when it is the video's
    end), «Listo». Its uid. The text has its own seconds: no «¿En qué partes va?»."""
    media = state._clip_tl_media()
    spans = clip_editor_vm.block_spans(media)
    start = min(spans[block][0] for block in parts)
    end = max(spans[block][1] for block in parts)
    CreativeState.hear_clip_time.fn(state, start, "pause")
    CreativeState.open_clip_flow.fn(state, "text")
    uid = state._clip_text_current()
    CreativeState.set_clip_text_value.fn(state, uid, text)
    CreativeState.commit_clip_text.fn(state, uid, text)
    if end < clip_editor_vm.media_total(media):
        state._clip_text_time(uid, start, end)
    if place:
        CreativeState.set_clip_text_place.fn(state, uid, place)
    CreativeState.done_clip_block.fn(state)
    return uid


def _stuck(state: CreativeState, text: str, *blocks: str) -> str:
    """A text that already carries `blocks` (a session from before «¿En qué partes
    va?» left the panel, Deivid 2026-11-23): nothing on screen writes them now, but it is
    still read and follows them. Its uid."""
    spans = clip_editor_vm.block_spans(state._clip_tl_media())
    use = clip_texts_vm.normalize_text_use(
        {
            "uid": clip_texts_vm.new_text_uid(state.clip_text_uses),
            "text": text,
            "start": min(spans[block][0] for block in blocks),
            "end": max(spans[block][1] for block in blocks),
            "blocks": list(blocks),
        }
    )
    state.clip_text_uses = [*state.clip_text_uses, use]
    return str(use["uid"])


# -- «+ Texto» -------------------------------------------------------------------------------


def test_mas_texto_puts_an_empty_text_from_the_marker_and_opens_its_panel(
    editor_on: None,
) -> None:
    state = _timeline_state()  # 25 s: the photo 0–2, the own video 2–17, the other 17–25
    state.brief_topic = "Promoción de 2×1 los martes"
    CreativeState.hear_clip_time.fn(state, 6.2, "pause")  # on the ½ s magnet: 0:06
    events = CreativeState.open_clip_flow.fn(state, "text")
    assert state.clip_tl_flow == "text" and state.clip_flow_drawer_open
    assert state.clip_text_panel_on
    row = state.clip_text_panel_row
    # Deivid 2026-11-20: it starts EMPTY (no hook copied), from the marker to the end
    assert row["text"] == "" and row["place"] == "bottom"
    # A1 (Deivid 2026-11-23): no «Empieza»/«Termina» — when it shows, and where to change it
    assert "start_value" not in row and "end_value" not in row
    assert row["time_line"] == (
        "Se ve de 0:06 a 0:25. Para cambiarlo, arrastra las puntas de su bloque, abajo."
    )
    assert row["fade_value"] == "Tarda en entrar y salir: 0,5 s"
    # a new text: «Sombra», enters «Aparece» and leaves «Desaparece»
    assert (row["layout"], row["motion_in"], row["motion_out"]) == ("scrim", "fade", "fade")
    assert row["layout_summary"] == "Fondo de las letras: Sombra"
    assert row["motion_summary"] == "Cómo entra y sale: Aparece · Desaparece"
    assert "getElementById('clip-text-field')" in _scripts(events)  # the focus to its field
    # no «¿En qué partes va?» (Deivid 2026-11-23): its own seconds, nothing stuck
    assert state.clip_text_uses[0]["blocks"] == []
    assert not hasattr(CreativeState, "toggle_clip_text_part")
    # an empty text has no block yet; «Listo» without typing does not keep it
    assert state.clip_tl_text_rows == []
    CreativeState.done_clip_block.fn(state)
    assert state.clip_text_uses == [] and state.clip_edit_notice == ""


def test_its_handles_move_its_times_and_the_panel_its_length(editor_on: None) -> None:
    """A1: the times move on the timeline (the handles, ←/→ on them: `nudge_clip_text`)
    and the panel says them; its animation's length moves in the panel."""
    state = _timeline_state()
    CreativeState.open_clip_flow.fn(state, "text")
    uid = state._clip_text_current()
    CreativeState.set_clip_text_value.fn(state, uid, "2×1 hoy")
    CreativeState.nudge_clip_text.fn(state, uid, "end", -0.5)
    assert state.clip_text_panel_row["time_line"].startswith("Se ve de 0:00 a 0:24,5.")
    assert state.clip_edit_notice == "Pusiste un texto."  # the typing said with it
    CreativeState.nudge_clip_text.fn(state, uid, "start", 0.5)
    assert state.clip_text_panel_row["time_line"].startswith("Se ve de 0:00,5 a 0:24,5.")
    assert state.clip_edit_notice == "Cambiaste cuándo sale el texto."
    CreativeState.step_clip_text_fade.fn(state, uid, 0.1)
    assert state.clip_text_panel_row["fade_value"] == "Tarda en entrar y salir: 0,6 s"
    assert state.clip_edit_notice == "Cambiaste cuánto tarda en entrar y salir el texto."
    for _ in range(10):
        CreativeState.step_clip_text_fade.fn(state, uid, 0.1)
    assert state.clip_text_panel_row["fade_more_off"] == "1"  # 1 s at most
    layer = state._clip_edit_media()["text_layers"][0]  # type: ignore[index]
    assert (layer["start_s"], layer["end_s"], layer["fade_s"]) == (0.5, 24.5, 1.0)
    # at most 120 characters
    CreativeState.set_clip_text_value.fn(state, uid, "x" * 200)
    assert len(state.clip_text_panel_row["text"]) == contract.VIDEO_TEXT_MAX == 120


# -- criterion 1: three texts, in time order -------------------------------------------------


def test_three_texts_at_different_moments_go_in_time_order(editor_on: None) -> None:
    state = _timeline_state()
    # put in another order than they show: the last part first
    _put_on(state, "Pide al 300", _SECOND)
    _put_on(state, "2×1 hoy", _PHOTO, place="top")
    _put_on(state, "Solo martes", _KEY, place="middle")
    assert len(state.clip_text_uses) == 3
    layers = state._clip_edit_media()["text_layers"]
    assert [(t["text"], t["place"], t["start_s"], t.get("end_s")) for t in layers] == [  # type: ignore[union-attr]
        ("2×1 hoy", "top", 0.0, 2.0),
        ("Solo martes", "middle", 2.0, 17.0),
        ("Pide al 300", "bottom", 17.0, None),  # to the end: left open
    ]
    recipe = state._clip_edit_recipe()
    assert len(recipe.text_layers) == 3 and contract.recipe_problems(recipe) == []
    assert state.clip_text_problem == "" and not state._clip_text_holds_next()


def test_two_texts_starting_together_go_top_first(editor_on: None) -> None:
    """Deivid: the same start — the one on top first."""
    state = _timeline_state()
    _put_on(state, "Abajo", _PHOTO)
    _put_on(state, "Arriba", _PHOTO, place="top")
    layers = state._clip_edit_media()["text_layers"]
    assert [t["text"] for t in layers] == ["Arriba", "Abajo"]  # type: ignore[index]


# -- criterion 2: «+ Texto» off with 3, saying why --------------------------------------------


def test_with_three_texts_mas_texto_is_off_and_says_why(editor_on: None) -> None:
    state = _timeline_state()
    assert not state.clip_text_full and state.clip_tl_add_note == ""
    for text, part in (("uno", _PHOTO), ("dos", _KEY), ("tres", _SECOND)):
        _put_on(state, text, part)
    assert state.clip_text_full
    assert (
        state.clip_text_add_reason
        == clip_texts_vm.TEXTS_FULL
        == ("Tu video puede tener hasta 3 textos. Quita uno para poner otro.")
    )
    assert state.clip_tl_add_note == clip_texts_vm.TEXTS_FULL  # above the «+»
    assert CreativeState.open_clip_flow.fn(state, "text") == []
    assert state.clip_edit_notice == clip_texts_vm.TEXTS_FULL
    assert len(state.clip_text_uses) == 3
    # the orbit's «Texto» is off by the same var (`add_off`), described by the note
    from . import clip_editor_view

    rendered = str(clip_editor_view._timeline_body().render())
    assert "clip_text_full" in rendered and "clip_tl_add_note" in rendered
    # one taken out: on again
    CreativeState.select_clip_block.fn(state, "texto-t1")
    CreativeState.clip_block_action.fn(state, "Quitar")
    assert not state.clip_text_full and state.clip_tl_add_note == ""


# -- criterion 3: two texts «Arriba» at once ----------------------------------------------------


def test_two_texts_arriba_that_overlap_warn_and_stop_siguiente(editor_on: None) -> None:
    state = _timeline_state()
    assert state.clip_editor_on_screen
    _put_on(state, "2×1 hoy", _PHOTO, _KEY, place="top")  # 0–17
    _put_on(state, "Solo martes", _KEY, place="top")  # 2–17: over the first
    line = "Aquí se verían dos textos arriba. Pon uno en otro lugar o en otro momento."
    assert state.clip_text_problem == line == clip_texts_vm.clash_line("top")
    assert [r["warn"] for r in state.clip_tl_text_rows] == ["1", "1"]
    assert state.clip_edit_problem == [line, "warn"]  # under the timeline, as «Crear» says
    # «Siguiente» does not go on, and says why beside it
    assert state.create_primary_label == "Siguiente"
    assert state.create_primary_disabled and state.create_reason == line
    step = state.gen_step
    assert CreativeState.next_view.fn(state) is None and state.gen_step == step
    assert CreativeState.go_to_view.fn(state, str(step + 1)) is None and state.gen_step == step
    # one moved to «En el medio»: solved
    CreativeState.select_clip_block.fn(state, "texto-t2")
    CreativeState.set_clip_text_place.fn(state, "t2", "middle")
    assert state.clip_text_problem == "" and not state.create_primary_disabled
    assert [r["warn"] for r in state.clip_tl_text_rows] == ["", ""]
    CreativeState.next_view.fn(state)
    assert state.gen_step == step + 1


# -- criterion 4: the preview shows each text only in its seconds ---------------------------------


def test_the_preview_shows_each_text_only_in_its_seconds(editor_on: None) -> None:
    state = _timeline_state()
    _put_on(state, "2×1 hoy", _PHOTO, place="top")
    _put_on(state, "Pide al 300", _SECOND)
    sequence = state._clip_sequence()
    assert [(t.text, t.start, t.end, t.place) for t in sequence.texts] == [
        ("2×1 hoy", 0.0, 2.0, "top"),
        ("Pide al 300", 17.0, 25.0, "bottom"),
    ]
    tol = clip_texts_vm.PREVIEW_TOLERANCE_S
    assert sequence.overlays_at(1.0)[0] == [0]
    assert sequence.overlays_at(2.0 + tol)[0] == []
    assert sequence.overlays_at(17.0 - tol)[0] == []
    assert sequence.overlays_at(17.0 + tol)[0] == [1]
    assert [t["text"] for t in state.clip_seq_texts] == ["2×1 hoy", "Pide al 300"]


# -- criterion 5: each block reads «Texto «…», de … a …» -------------------------------------------


def test_each_block_reads_texto_de_a(editor_on: None) -> None:
    state = _timeline_state()
    _put_on(state, "2×1 hoy", _PHOTO, place="top")
    _put_on(state, "Pide al 300", _SECOND)
    assert [(r["id"], r["name"]) for r in state.clip_tl_text_rows] == [
        ("texto-t1", "Texto «2×1 hoy», de 0:00 a 0:02"),
        ("texto-t2", "Texto «Pide al 300», de 0:17 a 0:25"),
    ]


# -- the bar, the arrows, the drag -----------------------------------------------------------------


def test_a_chosen_text_keeps_its_panel_while_it_is_emptied(editor_on: None) -> None:
    state = _timeline_state()
    block = _put_text(state, "2×1 hoy")
    CreativeState.select_clip_block.fn(state, block)
    assert state.clip_tl_chosen_kind == "text" and state.clip_text_panel_on
    assert [label for label, _icon in clip_editor_vm.EDITOR_ACTIONS["text"]] == [
        "Editar texto",
        "Quitar",
    ]
    CreativeState.set_clip_text_value.fn(state, "t1", "")
    # no block while it is empty, but its panel and its bar stay
    assert state.clip_tl_text_rows == []
    assert state.clip_tl_chosen_kind == "text" and state.clip_text_panel_on
    # let go empty: it is not kept
    CreativeState.done_clip_block.fn(state)
    assert state.clip_text_uses == []
    assert state.clip_edit_notice == "Quitaste un texto de tu video."


def test_moving_a_text_lets_its_blocks_go(editor_on: None) -> None:
    """Deivid: moving or trimming it by hand unsticks it from its blocks."""
    state = _timeline_state()
    _stuck(state, "2×1 hoy", _KEY)  # 2–17
    CreativeState.clip_block_key.fn(state, "texto-t1", "", "ArrowRight")
    (use,) = state.clip_text_uses
    assert (use["start"], use["end"], use["blocks"]) == (2.5, 17.5, [])
    assert state.clip_edit_notice == "Cambiaste cuándo sale el texto."
    CreativeState.drop_clip_block.fn(state, "texto-t1", "time", 6.2)
    (use,) = state.clip_text_uses
    assert (use["start"], use["end"]) == (6.0, 21.0)


# -- following «Fotos y videos» --------------------------------------------------------------------


def test_a_text_follows_its_blocks_and_goes_with_them(editor_on: None) -> None:
    state = _timeline_state()
    _stuck(state, "Pide al 300", _SECOND)  # 17–25, stuck to the other video
    # the other video moves first: its text goes with it
    CreativeState.clip_block_key.fn(state, _SECOND, "", "ArrowLeft")
    CreativeState.clip_block_key.fn(state, _SECOND, "", "ArrowLeft")
    assert [r["id"] for r in state.clip_tl_media_rows] == [_SECOND, _PHOTO, _KEY]
    (row,) = state.clip_tl_text_rows
    assert row["name"] == "Texto «Pide al 300», de 0:00 a 0:08"
    # cut inside it? it is on the other video; cutting the own video keeps it
    # removed: its text goes too, and the line says so
    CreativeState.select_clip_block.fn(state, _SECOND)
    CreativeState.clip_block_action.fn(state, "Quitar")
    assert state.clip_text_uses == []
    assert "También quitamos el texto «Pide al 300», que iba solo en esa parte." in (
        state.clip_edit_notice
    )


def test_cortar_keeps_a_text_on_both_halves(editor_on: None) -> None:
    state = _timeline_state()
    _stuck(state, "2×1 hoy", _KEY)  # the own video, 2–17
    CreativeState.select_clip_block.fn(state, _KEY)
    CreativeState.hear_clip_time.fn(state, 7.0, "pause")
    CreativeState.cut_clip_video.fn(state)
    (use,) = state.clip_text_uses  # still one text: both halves side by side
    assert use["blocks"] == [_KEY, clip_editor_vm.piece_id(_KEY, 1)]
    assert (use["start"], use["end"]) == (2.0, 17.0)


# -- subtitles take «Abajo» (Deivid 2026-11-23) --------------------------------------------


def test_with_subtitles_abajo_is_off_and_a_new_text_goes_on_top(editor_on: None) -> None:
    state = _timeline_state()
    state.clip_subtitles = True
    CreativeState.open_clip_flow.fn(state, "text")
    uid = state._clip_text_current()
    row = state.clip_text_panel_row
    assert row["place"] == "middle"  # «En el medio», never «Abajo» by itself
    assert row["bottom_off"] == "1" and row["place_note"] == clip_texts_vm.SUBTITLES_BOTTOM_LINE
    assert row["covered_note"] == ""
    CreativeState.set_clip_text_value.fn(state, uid, "2×1 hoy")
    CreativeState.set_clip_text_place.fn(state, uid, "bottom")
    assert state.clip_text_uses[0]["place"] == "middle"  # not taken, and it says why
    assert state.clip_text_warning == clip_texts_vm.SUBTITLES_BOTTOM_LINE
    CreativeState.set_clip_text_place.fn(state, uid, "top")
    assert state.clip_text_uses[0]["place"] == "top" and state.clip_text_warning == ""
    # subtitles off: a new text starts «Abajo», as before
    CreativeState.done_clip_block.fn(state)
    state.clip_subtitles = False
    CreativeState.open_clip_flow.fn(state, "text")
    assert state.clip_text_panel_row["place"] == "bottom"


def test_subtitles_turned_on_over_a_text_abajo_stop_siguiente(editor_on: None) -> None:
    state = _timeline_state()
    _put_on(state, "Pide al 300", _SECOND)  # «Abajo»
    assert not state.create_primary_disabled
    CreativeState.set_clip_subtitles.fn(state, True)
    # it is not moved by itself: the warning, the tone and «Siguiente» waiting
    assert state.clip_text_uses[0]["place"] == "bottom"
    assert state.clip_text_problem == clip_texts_vm.SUBTITLES_BOTTOM_LINE
    assert [r["warn"] for r in state.clip_tl_text_rows] == ["1"]
    assert state.create_primary_disabled
    assert state.create_reason == clip_texts_vm.SUBTITLES_BOTTOM_LINE
    step = state.gen_step
    assert CreativeState.next_view.fn(state) is None and state.gen_step == step
    # its panel says it is under the subtitles; the problem line says what to do
    CreativeState.select_clip_block.fn(state, "texto-t1")
    row = state.clip_text_panel_row
    assert row["covered_note"] == "Este texto queda debajo de los subtítulos."
    assert state.clip_text_warning == clip_texts_vm.SUBTITLES_BOTTOM_LINE
    # moved by the owner (or the subtitles off), it goes on
    CreativeState.set_clip_text_place.fn(state, "t1", "top")
    assert state.clip_text_problem == "" and not state.create_primary_disabled


# -- a session saved with ED-10's one text ---------------------------------------------------------


def test_a_session_with_the_old_text_loads_as_text_one(editor_on: None) -> None:
    state = _timeline_state()
    state.clip_overlay_text = "2×1 hoy"
    state._clip_text_committed = "2×1 hoy"
    state.clip_text_place = "top"
    state.clip_text_start, state.clip_text_end = 3.0, -1.0
    state._clip_migrate_texts()
    assert state.clip_text_uses == [
        {
            "uid": "t1",
            "text": "2×1 hoy",
            "place": "top",
            "start": 3.0,
            "end": -1.0,
            "blocks": [],
            "fade": 0.5,
            # ED-10's text left at once: it keeps doing so
            "layout": "scrim",
            "motion_in": "fade",
            "motion_out": "none",
            "exit_set": False,
            "box_color": "",
            "text_color": "",
            "size": "medium",
        }
    ]
    # the old fields are left empty: never on the video twice
    assert (state.clip_overlay_text, state._clip_text_committed) == ("", "")
    assert (state.clip_text_start, state.clip_text_end, state.clip_text_place) == (
        0.0,
        -1.0,
        "bottom",
    )
    (row,) = state.clip_tl_text_rows
    assert row["name"] == "Texto «2×1 hoy», de 0:03 a 0:25"
    # once more: nothing changes
    state._clip_migrate_texts()
    assert len(state.clip_text_uses) == 1


# -- ED-13 C/D: the background and the motions ---------------------------------------------


def test_the_background_and_the_motions_are_chosen_in_the_panel(editor_on: None) -> None:
    state = _timeline_state()
    uid = _put_on(state, "2×1 hoy", _KEY)
    CreativeState.select_clip_block.fn(state, f"texto-{uid}")
    CreativeState.set_clip_text_layout.fn(state, uid, "brand_fill")
    assert state.clip_text_uses[0]["layout"] == "brand_fill"
    assert state.clip_edit_notice == "Cambiaste el fondo de las letras."
    # a brand without a palette: its box keeps the render's own colour, not named
    assert (
        state.clip_text_panel_row["layout_summary"] == "Fondo de las letras: Recuadro de tu color"
    )
    CreativeState.set_clip_text_layout.fn(state, uid, "nope")  # never taken
    assert state.clip_text_uses[0]["layout"] == "brand_fill"
    # an entrance: the exit goes with it, and the preview shows it once
    events = CreativeState.set_clip_text_motion_in.fn(state, uid, "slide")
    assert (state.clip_text_uses[0]["motion_in"], state.clip_text_uses[0]["motion_out"]) == (
        "slide",
        "slide",
    )
    assert state.clip_edit_notice == "Cambiaste cómo entra y sale el texto."
    assert "showMotion(h, 1.7, 2.8, false)" in _scripts([events])
    assert state.clip_text_panel_row["motion_summary"] == "Cómo entra y sale: Sube · Baja"
    # the owner's exit stays
    events = CreativeState.set_clip_text_motion_out.fn(state, uid, "none")
    assert "showMotion(h, 16.7, 17.3, false)" in _scripts([events])
    CreativeState.set_clip_text_motion_in.fn(state, uid, "zoom")
    assert state.clip_text_uses[0]["motion_out"] == "none"
    assert state.clip_text_panel_row["fade_value"] == "Tarda en entrar: 0,5 s"
    # «Ver cómo se mueve» (prefers-reduced-motion) asks for it
    assert "true)" in _scripts([CreativeState.show_clip_text_motion.fn(state, uid)])
    # the recipe carries them, the background as its `layout_id`
    (layer,) = state._clip_edit_media()["text_layers"]  # type: ignore[misc]
    assert (layer["layout_id"], layer["motion_in"]) == ("brand_fill", "zoom")
    assert "motion_out" not in layer  # «De golpe» is the schema's default
    # the preview draws it over the brand's accent, with legible letters
    state.clip_brand_palette = ["#0F766E", "#FFFFFF", "#F8FAFC"]
    (row,) = state.clip_seq_texts
    assert (row["layout"], row["bg"], row["ink"]) == ("brand_fill", "#0F766E", "#FFFFFF")


def test_the_owner_picks_the_colour_of_the_strip_and_the_box(editor_on: None) -> None:
    """ED-13 (Deivid 2026-11-23): «Franja» / «Recuadro de tu color» in a colour of the
    Brand Kit, black or white — chips under the grid, the preview at once, the live line,
    the recipe; kept per text; another background starts on its own default."""
    state = _timeline_state()
    state.clip_brand_palette = ["#0F766E", "#F4C2C2", "#ffffff"]
    uid = _put_on(state, "2×1 hoy", _KEY)
    CreativeState.select_clip_block.fn(state, f"texto-{uid}")
    assert state.clip_text_color_rows == []  # «Sombra» has no box
    CreativeState.set_clip_text_layout.fn(state, uid, "band")
    chips = state.clip_text_color_rows
    # the palette in its order (each once, by its role), then black; white is already in it
    assert [(c["value"], c["name"], c["on"]) for c in chips] == [
        ("#0F766E", "Color principal de tu marca", ""),
        ("#F4C2C2", "Segundo color de tu marca", ""),
        ("#FFFFFF", "Tercer color de tu marca", ""),
        ("#111111", "Negro", "1"),  # the strip's default
    ]
    row = state.clip_text_panel_row
    assert (row["box_color_shown"], row["box_color_title"]) == ("1", "Color de la franja")
    assert row["box_color_chosen"] == "Elegido: negro"
    assert row["layout_summary"] == "Fondo de las letras: Franja, negro"
    CreativeState.set_clip_text_box_color.fn(state, uid, "#F4C2C2")
    assert state.clip_text_uses[0]["box_color"] == "#F4C2C2"
    assert state.clip_edit_notice == "Cambiaste el color del fondo."
    assert state.clip_text_panel_row["box_color_chosen"] == "Elegido: segundo color de tu marca"
    assert [c["on"] for c in state.clip_text_color_rows] == ["", "1", "", ""]
    # the preview at once, with legible letters on it
    (preview,) = state.clip_seq_texts
    assert (preview["layout"], preview["bg"], preview["ink"]) == ("band", "#F4C2C2", "#111111")
    # the recipe carries it
    (layer,) = state._clip_edit_media()["text_layers"]  # type: ignore[misc]
    assert (layer["layout_id"], layer["box_color"]) == ("band", "#F4C2C2")
    # a colour that is none of the chips is never taken
    CreativeState.set_clip_text_box_color.fn(state, uid, "#123456")
    assert state.clip_text_uses[0]["box_color"] == "#F4C2C2"
    # the default's chip is the default again: the recipe goes back to its shape
    CreativeState.set_clip_text_box_color.fn(state, uid, "#111111")
    assert state.clip_text_uses[0]["box_color"] == ""
    (layer,) = state._clip_edit_media()["text_layers"]  # type: ignore[misc]
    assert "box_color" not in layer
    # «Recuadro de tu color»: its default is the brand's main colour
    CreativeState.set_clip_text_box_color.fn(state, uid, "#FFFFFF")
    CreativeState.set_clip_text_layout.fn(state, uid, "brand_fill")
    assert state.clip_text_uses[0]["box_color"] == ""  # a new background, its own default
    row = state.clip_text_panel_row
    assert row["box_color_title"] == "Color del recuadro"
    assert row["box_color_chosen"] == "Elegido: color principal de tu marca"
    assert row["layout_summary"] == "Fondo de las letras: Recuadro de tu color, color principal"
    # «Sin fondo»: the line about light videos and (round 3) the chips of its letters,
    # white chosen until the owner picks another
    CreativeState.set_clip_text_layout.fn(state, uid, "shadow")
    assert state.clip_text_panel_row["shadow_note"] == clip_texts_vm.SHADOW_NOTE
    assert state.clip_text_panel_row["box_color_shown"] == "1"
    assert [r["value"] for r in state.clip_text_color_rows if r["on"] == "1"] == ["#FFFFFF"]
    CreativeState.set_clip_text_text_color.fn(state, uid, "#111111")
    assert state.clip_text_uses[0]["text_color"] == "#111111"
    assert state.clip_text_panel_row["layout_choice"] == "Sin fondo, letras negras"
    (layer,) = state._clip_edit_media()["text_layers"]  # type: ignore[misc]
    assert layer["text_color"] == "#111111"
    assert state.clip_seq_texts[0]["ink"] == "#111111"
    CreativeState.set_clip_text_box_color.fn(state, uid, "#FFFFFF")  # not its chips
    assert state.clip_text_uses[0]["text_color"] == "#111111"
    CreativeState.set_clip_text_layout.fn(state, uid, "band")
    assert state.clip_text_uses[0]["text_color"] == ""  # a new background: white again


def test_a_box_colour_on_a_brand_without_palette_offers_black_and_white(
    editor_on: None,
) -> None:
    state = _timeline_state()
    uid = _put_on(state, "2×1 hoy", _KEY)
    CreativeState.select_clip_block.fn(state, f"texto-{uid}")
    CreativeState.set_clip_text_layout.fn(state, uid, "band")
    assert [c["name"] for c in state.clip_text_color_rows] == ["Negro", "Blanco"]
    CreativeState.set_clip_text_box_color.fn(state, uid, "#FFFFFF")
    (preview,) = state.clip_seq_texts
    assert (preview["bg"], preview["ink"]) == ("#FFFFFF", "#111111")


def test_letra_por_letra_past_40_letters_is_not_taken(editor_on: None) -> None:
    state = _timeline_state()
    uid = _put_on(state, "Promoción de 2×1 todos los martes y jueves", _KEY)
    CreativeState.select_clip_block.fn(state, f"texto-{uid}")
    assert CreativeState.set_clip_text_motion_in.fn(state, uid, "typewriter") is None
    assert state.clip_text_uses[0]["motion_in"] == "fade"
    assert state.clip_text_panel_row["typewriter_off"] == "1"


def test_the_brand_typography_reaches_the_preview() -> None:
    state = _timeline_state()
    assert (state.clip_text_font_family, state.clip_text_font_css_url) == ("", "")
    state.clip_brand_font = "Montserrat"
    assert state.clip_text_font_family == '"Montserrat", sans-serif'
    assert state.clip_text_font_css_url.startswith("https://fonts.googleapis.com/css2?family=")
    state.clip_brand_font_path = "/r2media/tok"
    assert state.clip_text_font_family.startswith('"QualifyBrandHeading"')
    assert state.clip_text_font_css_url == ""  # the file, not the stylesheet


def test_the_panel_and_the_preview_compile() -> None:
    from . import clip_editor_view

    panel = str(clip_editor_view._text_panel().render())
    for expected in (
        "set_clip_text_layout",
        "set_clip_text_motion_in",
        "set_clip_text_motion_out",
        "show_clip_text_motion",
        "radiogroup",
        "clip-text-layout-title",
        "clip-text-typewriter-note",
        "q-text-show-motion",
        # ED-13 round 2 (Deivid 2026-11-23): the box's colour chips and «Sin fondo»'s note
        "set_clip_text_box_color",
        "clip-text-box-color-title",
        "q-swatch q-swatch--box",
        "clip-text-shadow-note",
        "clip-text-motion-title",
        "q-text-panel__done",
    ):
        assert expected in panel
    assert "nudge_clip_text" not in panel and "Empieza" not in panel
    # «¿En qué partes va?» left the panel (Deivid 2026-11-23); when it shows stays
    assert "toggle_clip_text_part" not in panel and "clip-text-parts-title" not in panel
    assert "En qué partes" not in panel and "time_line" in panel
    # round 3 (Deivid 2026-11-23): every option folds — Radix's accordion, several open
    # at once, all shut at first — each header with its title and what is chosen
    assert "q-text-fold" not in panel and "q-text-section" not in panel
    assert panel.count("q-text-acc__summary") == 4  # round 4: «Tamaño de las letras»
    assert '"multiple"' in panel and "defaultValue" not in panel
    for expected in (
        "clip-text-place-title",
        "place_choice",
        "layout_choice",
        "motion_choice",
        # round 3: «Sin fondo»'s letters pick their colour with the same chips
        "set_clip_text_text_color",
        "chips_for_text",
    ):
        assert expected in panel, expected
    preview = str(clip_editor_view._preview().render())
    assert "--q-text-font" in preview and "QualifyBrandHeading" in preview
    assert "data-seq-type" in preview


def test_leaving_the_editor_forgets_the_texts(editor_on: None) -> None:
    state = _timeline_state()
    _put_text(state, "2×1 hoy")
    state._reset_clip_editor()
    assert state.clip_text_uses == []
    assert state._clip_text_put == [] and state._clip_text_before == {}


def test_the_letters_size_is_chosen_in_the_panel(editor_on: None) -> None:
    """ED-13 round 4 (Deivid 2026-11-23): «Tamaño de las letras» — «Mediana» by default,
    said in the live line when changed, carried to the recipe and the preview; a «Grande»
    text written past the limit goes back to «Mediana» and says so."""
    state = _timeline_state()
    uid = _put_on(state, "2×1 hoy", _KEY)
    CreativeState.select_clip_block.fn(state, f"texto-{uid}")
    assert state.clip_text_panel_row["size_choice"] == "Tamaño: Mediana"
    (layer,) = state._clip_edit_media()["text_layers"]  # type: ignore[misc]
    assert "text_size" not in layer  # «Mediana» is the schema's default
    CreativeState.set_clip_text_size.fn(state, uid, "large")
    assert state.clip_text_uses[0]["size"] == "large"
    assert state.clip_edit_notice == clip_texts_vm.SIZE_CHANGED_LINE
    (layer,) = state._clip_edit_media()["text_layers"]  # type: ignore[misc]
    assert layer["text_size"] == "large"
    (row,) = state.clip_seq_texts
    assert row["size"] == "large"
    CreativeState.set_clip_text_size.fn(state, uid, ["small"])  # the radiogroup's shape
    assert state.clip_text_uses[0]["size"] == "small"
    CreativeState.set_clip_text_size.fn(state, uid, "huge")  # never taken
    assert state.clip_text_uses[0]["size"] == "small"
    # «Grande», then written past the limit: back to «Mediana», said in the live line
    CreativeState.set_clip_text_size.fn(state, uid, "large")
    CreativeState.set_clip_text_value.fn(state, uid, "a" * 41)
    assert state.clip_text_uses[0]["size"] == "medium"
    assert state.clip_edit_notice == clip_texts_vm.SIZE_DOWN_LINE
    assert state.clip_text_panel_row["large_off"] == "1"

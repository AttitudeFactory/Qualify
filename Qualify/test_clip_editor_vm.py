"""ED-02/03/05 (m-25026621, m-25026623, m-25026630): «Arma tu video»'s words, exactly as
the proposal §5 writes them, and «Deshacer» (D-E6)."""

from __future__ import annotations

from . import clip_editor_vm as vm


def _snap(**changes: object) -> dict[str, object]:
    base: dict[str, object] = {
        "start": 0.0,
        "end": 8.0,
        "rotate": 0,
        "effects": [],
        "speed": 10,
        "text": "",
        "place": "bottom",
    }
    return {**base, **changes}


def test_fixed_words() -> None:
    assert vm.STEP_TITLE == "Arma tu video"
    assert vm.PREVIEW_NOTE == "Así va quedando"
    assert vm.PREVIEW_FREE == "Esta vista previa es gratis."
    # one line for a video the preview cannot show, known or a playback error
    assert vm.PREVIEW_UNAVAILABLE == (
        "No pudimos mostrar tu video aquí, así que no puedes cortarlo. Lo verás listo antes de "
        "aprobarlo."
    )
    assert vm.PREVIEW_REMOTE == vm.PREVIEW_BROKEN == vm.PREVIEW_UNAVAILABLE
    assert [vm.speed_aria(s) for s in (2, 3, 5, 10, 20)] == [
        "2 veces más rápido",
        "3 veces más rápido",
        "5 veces más rápido",
        "10 veces más rápido",
        "20 veces más rápido",
    ]
    assert (vm.STRIP_OPENS, vm.STRIP_CLOSES) == ("Abre tu video", "Cierra tu video")
    assert vm.MOTION_ONLY_NOTE == (
        "Este video solo guía el movimiento. Para unir varios, usa «Armar mi video por partes»."
    )
    assert vm.FAST_NEEDS_LONGER == (
        "Para hacerlo más rápido, tu video tiene que durar al menos 6 s."
    )
    assert vm.fast_impossible_line(2) == (
        "Tu video duraría 2 s: muy poco para un reel. Vuelve a la velocidad normal o usa "
        "un video más largo."
    )
    assert vm.fast_on_line(10, had_cut=False) == ("Pusiste tu video ×10: usamos todo tu video.")
    assert vm.fast_on_line(5, had_cut=True) == (
        "Pusiste tu video ×5: usamos todo tu video. "
        "Si vuelves a la velocidad normal, recuperas tu pedazo."
    )
    assert vm.PREVIEW_SLOWER == "En la vista previa se ve más lento que en el video final."
    # ED-10: the tools are gone; «Agregar» opens these flows
    assert not hasattr(vm, "TOOLS") and not hasattr(vm, "TOOL_SLUGS")
    assert [vm.FLOW_QUESTIONS[f] for f in vm.FLOWS] == [
        "¿Con qué lo armamos?",
        "¿Qué dice tu video?",
        "¿Qué le pones a tu video?",
        "¿De qué trata tu video?",
    ]
    assert vm.NO_EFFECTS_YET == (
        "Todavía no hay efectos para tu video. Mientras tanto, agrega un texto."
    )
    assert vm.NO_EFFECTS_GO_TEXT == "Agregar un texto"
    # Deivid 2026-11-17: one side panel with tabs; «Cortar» where the marker is
    assert [name for _f, _i, name in vm.FLOW_TABS] == [
        "¿Con qué lo armamos?",
        "Texto",
        "Efecto",
        "Pedir una idea",
    ]
    assert vm.FLOW_PANEL_TITLE == "Agregar a tu video"
    assert vm.CUT == "Cortar"
    assert vm.CUT_NOT_HERE == "Mueve el marcador dentro de tu video para cortar."
    assert vm.CUT_TOO_CLOSE == "Muy cerca del borde: mueve el marcador al menos 1 s."
    assert vm.too_close_text(1.0) == vm.CUT_TOO_CLOSE
    assert vm.too_close_text(0.5) == "Muy cerca del borde: mueve el marcador al menos ½ s."
    assert vm.too_close_text(2 / 3) == "Muy cerca del borde: mueve el marcador al menos 0,7 s."
    assert vm.PARTS_LINK == "Armar mi video por partes"
    assert vm.TEXT_TITLE == "Texto sobre el video"
    assert list(vm.TEXT_PLACES.values()) == ["Arriba", "En el medio", "Abajo"]
    assert vm.FREE == "Gratis"
    assert vm.SPEED_TITLE == "Velocidad"
    assert [vm.speed_label(s) for s in (2, 3, 5, 10, 20)] == ["×2", "×3", "×5", "×10", "×20"]
    assert not hasattr(vm, "EFFECTS_MODE_LINE")  # «No gasta segundos» is not true yet
    assert vm.TEXT_EXAMPLE == "Ej.: 2×1 solo este fin de semana"
    assert (vm.ORDER_TITLE, vm.ORDER_HINT) == (
        "Orden de tu video",
        "Arrastra las fotos y los videos para ordenarlos: el primero abre tu video y el "
        "último lo cierra.",
    )
    assert vm.whole_label(8) == "Usar el video entero"
    assert vm.whole_label(15) == "Usar el video entero"
    assert vm.whole_label(15.5) == "Usar los primeros 15 s"
    assert vm.fast_too_short_line(2) == (
        "Tu video durará 2 s: muy poco para un reel. Elige un pedazo más largo o una "
        "velocidad menor."
    )
    assert (vm.FROM_LABEL, vm.TO_LABEL) == ("Desde", "Hasta")
    assert (vm.EARLIER, vm.LATER) == ("Medio segundo antes", "Medio segundo después")
    assert (vm.EARLIER_TEXT, vm.LATER_TEXT) == ("− ½ s", "+ ½ s")
    assert vm.ROTATE == "Girar"
    assert vm.ROTATE_LABEL == "Girar el video un cuarto de vuelta"
    assert vm.WHOLE_VIDEO == "Usar el video entero"
    assert vm.TOO_SHORT == "El pedazo tiene que durar al menos 1 segundo."
    assert vm.UNDO == "Deshacer"


def test_numbered_words() -> None:
    assert vm.duration_line(4) == "Tu video durará 4 s."
    assert vm.usage_line(8) == "Usas 8 s de tu video."
    assert vm.usage_line(8.5) == "Usas 8,5 s de tu video."
    # the timeline's ½ s rounding, as the chosen block's heading (Deivid, 2026-11-16)
    assert vm.usage_line(6.6) == "Usas 6,5 s de tu video."
    assert vm.usage_line(12.04) == "Usas 12 s de tu video."
    assert vm.range_line(4, 12) == "Desde 0:04 · Hasta 0:12"
    assert not hasattr(vm, "card_title")  # ED-10: the card «Tu video» is gone
    assert vm.time_of_total(3, 8) == "0:03 de 0:08"


def test_refusals_and_low_resolution() -> None:
    assert vm.refusal_text("too_short") == "El pedazo tiene que durar al menos 1 segundo."
    assert vm.refusal_text("outside_video") == (
        "No pudimos usar ese pedazo de tu video. Prueba con otro."
    )
    assert vm.refusal_text("anything_new") == vm.REFUSAL_GENERIC
    assert vm.low_resolution_line() == (
        "Al ponerlo vertical, tu video se vería borroso. Sube el video original desde tu teléfono."
    )
    assert vm.low_resolution_line(horizontal=True) == (
        "Al ponerlo vertical, tu video se vería borroso. Si puedes, grábalo en vertical."
    )


def test_cortar_is_judged_by_ef03s_plan_prepare() -> None:
    def check(**kw: object) -> tuple[str, str]:
        base: dict[str, object] = {
            "key": "k",
            "start": 0.0,
            "end": 8.0,
            "rotate": 0,
            "speed": 1.0,
            "width": 1080,
            "height": 1920,
            "duration": 20.0,
        }
        return vm.prepare_check(**{**base, **kw})  # type: ignore[arg-type]

    assert check() == ("", "")
    assert check(width=0) == ("", "")  # not measured yet
    assert check(end=0.5) == (vm.TOO_SHORT, "")
    assert check(start=30.0, end=32.0) == (vm.REFUSAL_GENERIC, "")
    assert check(rotate=45) == (vm.REFUSAL_GENERIC, "")
    # a 16:9 phone video, 640×360: the vertical crop is 202×360
    refusal, warning = check(width=640, height=360)
    assert refusal == ""
    assert warning == vm.low_resolution_line(horizontal=True)
    assert warning.endswith("Si puedes, grábalo en vertical.")
    # a vertical but small video: the advice is to upload the original
    assert check(width=360, height=640)[1].endswith("Sube el video original desde tu teléfono.")
    # turned a quarter: 1920×1080 becomes 1080×1920 upright, no warning
    assert check(width=1920, height=1080, rotate=90) == ("", "")


def test_fast_motion_proposal() -> None:
    assert vm.fast_proposal(40) == (0.0, 40.0, 10)  # 4 s
    assert vm.fast_proposal(20) == (0.0, 20.0, 5)  # 4 s
    assert vm.fast_proposal(120) == (0.0, 120.0, 20)  # 6 s
    assert vm.fast_proposal(7.33) == (0.0, 7.5, 2)  # on the grid; ×3 is off (2,5 s)
    assert vm.fast_proposal(130) == (0.0, 130.0, 20)  # 6,5 s; ×2 is off (65 s)


def _speeds_on(duration: float) -> list[str]:
    return [value for value, why in vm.speed_reasons(duration).items() if not why]


def test_speed_reasons_on_only_for_three_to_sixty_seconds() -> None:
    """Deivid 2026-11-17: ×2 and ×3 join; a speed is on only for a 3–60 s result."""
    assert _speeds_on(6.0) == ["1", "2"]  # only ×2 (3 s)
    assert _speeds_on(8.0) == ["1", "2"]  # ×3 leaves 2,7 s
    assert vm.speed_reasons(8.0)["3"] == "Con ×3 tu video duraría 2,7 s."
    # under 6 s every speed is off, with the same line
    assert _speeds_on(4.0) == ["1"]
    four = vm.speed_reasons(4.0)
    assert {four[v] for v in ("2", "3", "5", "10", "20")} == {vm.FAST_NEEDS_LONGER}
    # 130 s: ×2 is off by length (65 s), the others on
    assert vm.speed_reasons(130.0)["2"] == "Con ×2 tu video duraría 65 s."
    assert _speeds_on(130.0) == ["1", "3", "5", "10", "20"]
    # not read yet: every speed waits
    assert vm.speed_reasons(20.0, known=False)["5"] == vm.CUT_WAITING
    assert vm.speed_result_line(10, 1.2) == "Con ×10 tu video duraría 1,2 s."


def test_the_switch_gates_the_editor() -> None:
    common = {"category": "clip", "kind": "clip", "from_reel": False, "has_plan": False}
    assert not vm.editor_shown(**common, reel_video=False, enabled=False)
    assert vm.editor_shown(**common, reel_video=False, enabled=True)
    assert vm.CLIP_EDITOR_SWITCH == "QUALIFY_CLIP_EDITOR"


def test_change_messages() -> None:
    assert vm.change_message(_snap(), _snap(start=1.0)) == "Cambiaste el pedazo de tu video."
    assert vm.change_message(_snap(), _snap(rotate=90)) == "Giraste tu video."
    assert vm.change_message(_snap(), _snap(effects=["humo_capa"])) == (
        "Cambiaste el efecto de tu video."
    )
    assert vm.change_message(_snap(), _snap(speed=20)) == "Cambiaste la velocidad de tu video."
    assert vm.change_message(_snap(), _snap(text="Hola")) == "Cambiaste el texto de tu video."
    assert vm.change_message(_snap(), _snap(place="top")) == "Cambiaste el lugar del texto."
    # the place with the text kept at the same time: the line names the place
    assert vm.change_message(_snap(), _snap(place="top", text="Hola")) == (
        "Cambiaste el lugar del texto."
    )
    assert vm.change_message(_snap(), _snap()) == ""


def test_undo_stack_brings_back_the_exact_state() -> None:
    first, second = _snap(), _snap(start=2.0, effects=["vapor_capa"])
    stack = vm.push_undo([], first)
    stack = vm.push_undo(stack, second)
    previous, stack = vm.pop_undo(stack)
    assert previous == second
    previous, stack = vm.pop_undo(stack)
    assert previous == first and stack == []
    assert vm.pop_undo([]) == (None, [])
    deep: list[dict[str, object]] = []
    for i in range(15):
        deep = vm.push_undo(deep, _snap(start=float(i)))
    assert len(deep) == vm.UNDO_DEPTH and deep[-1]["start"] == 14.0


def test_which_screen_and_which_video() -> None:
    common = {
        "category": "clip",
        "kind": "clip",
        "from_reel": False,
        "has_plan": False,
        "enabled": True,
    }
    assert vm.editor_shown(**common, reel_video=False)
    assert not vm.editor_shown(**{**common, "has_plan": True}, reel_video=False)
    assert not vm.editor_shown(**{**common, "from_reel": True}, reel_video=False)
    assert not vm.editor_shown(**common, reel_video=True)
    assert not vm.editor_shown(**{**common, "category": "image"}, reel_video=False)
    videos = [
        {"key": "r", "source": "reel"},
        {"key": "p", "source": "pinterest"},
        {"key": "mine", "source": "upload", "name": "v.mp4"},
    ]
    assert vm.own_video(videos) == {"key": "mine", "name": "v.mp4"}
    # a publication's or the Galería's video is the business's; stock is only a reference
    assert vm.own_video([{"key": "g", "source": "existing"}]) == {"key": "g", "name": ""}
    assert vm.own_video([{"key": "s", "source": "stock"}]) == {}
    # Inspiración is stock too (saved as "inspiration"): a reference, never a stretch
    assert vm.own_video([{"key": "i", "source": "inspiration"}]) == {}
    assert vm.own_video([]) == {}


def test_recipe_of_a_clip() -> None:
    recipe = vm.recipe_of(
        video_key="k",
        start=4,
        end=12,
        rotate=90,
        effects=["vapor_capa", "camara_rapida"],
        speed=10,
        text=" Hola ",
        place="top",
    )
    assert recipe.segments[0].speed == 10 and recipe.segments[0].rotate == 90
    assert [u.effect_id for u in recipe.effects] == ["vapor_capa", "camara_rapida"]
    assert recipe.effects[1].param_values == {}  # the speed is the stretch's only
    assert recipe.text_layer is not None and recipe.text_layer.text == "Hola"
    photos = vm.recipe_of(
        video_key="",
        start=0,
        end=0,
        rotate=0,
        effects=["camara_rapida", "humo_capa"],
        speed=10,
        text="",
        place="bottom",
    )
    assert photos.segments == () and [u.effect_id for u in photos.effects] == ["humo_capa"]
    assert photos.text_layer is None


def test_fast_motion_is_judged_by_ef04s_plan_speed() -> None:
    assert vm.fast_check(key="k", start=0, end=40, speed=10) == (4.0, "")
    # 7.5 s at ×5 = 45 output frames = 1.5 s: too short for a reel
    seconds, warning = vm.fast_check(key="k", start=0, end=7.5, speed=5)
    assert seconds == 1.5
    assert warning == (
        "Tu video durará 1,5 s: muy poco para un reel. Elige un pedazo más largo o una "
        "velocidad menor."
    )
    # 1300 s at ×20 = 65 s: past a reel's 60 s (EF-07's words)
    seconds, warning = vm.fast_check(key="k", start=0, end=1300, speed=20)
    assert seconds == 65.0
    assert warning == (
        "Con esa velocidad tu video duraría 65 s: muy largo para un reel. Elige una velocidad "
        "mayor o corta un pedazo más corto."
    )
    # what EF-04 cannot plan at all (here, an empty stretch) gets the generic line
    assert vm.fast_check(key="k", start=4, end=4, speed=10) == (0.0, vm.REFUSAL_GENERIC)


# -- ED-10 m-25026648: the timeline -----------------------------------------------------------

_STRIP = [
    {"key": "f1.jpg", "kind": "image", "source": "upload"},
    {"key": "v1.mp4", "kind": "video", "source": "upload"},
    {"key": "pin.jpg", "kind": "image", "source": "pinterest"},
    {"key": "v2.mp4", "kind": "video", "source": "existing"},
]


def _media() -> list[dict[str, object]]:
    return vm.timeline_media(
        _STRIP,
        own_key="v1.mp4",
        cut_start=2.0,
        cut_end=9.0,
        speed=1.0,
        rotate=90,
        lengths={"v2.mp4": 30.0},
    )


def test_everything_chosen_is_already_on_the_timeline_in_its_order() -> None:
    """E3: photos 2 s, the own video its stretch, other videos up to 15 s; references for
    the AI only (Pinterest, a reel, Inspiración) stay off the timeline."""
    media = _media()
    assert [m["id"] for m in media] == ["f1.jpg", "v1.mp4", "v2.mp4"]
    assert media[0] == {"id": "f1.jpg", "key": "f1.jpg", "kind": "photo", "dur": 2.0}
    assert (media[1]["src_start"], media[1]["src_end"], media[1]["rotate"]) == (2.0, 9.0, 90)
    assert (media[2]["src_start"], media[2]["src_end"], media[2]["src_len"]) == (0.0, 15.0, 30.0)
    assert vm.media_total(media) == 2 + 7 + 15
    # a video not measured yet is placed at 15 s until the browser says its length
    unmeasured = vm.timeline_media(
        [{"key": "x.mp4", "kind": "video", "source": "upload"}],
        own_key="",
        cut_start=0,
        cut_end=0,
        speed=1,
        rotate=0,
        lengths={},
    )
    assert unmeasured[0]["src_end"] == 15.0
    # «Cámara rápida» shortens the own video's block
    fast = vm.timeline_media(
        _STRIP[1:2], own_key="v1.mp4", cut_start=0, cut_end=40, speed=10, rotate=0, lengths={}
    )
    assert vm.media_total(fast) == 4.0


def test_the_blocks_read_as_the_proposal_says() -> None:
    from .ui import timeline_vm as tl

    rows = tl.media_blocks(_media())  # type: ignore[arg-type]
    assert rows[1]["name"] == "Video 2 de 3, usas de 0:02 a 0:09, dura 7 s"
    assert rows[0]["name"] == "Foto 1 de 3, se ve 2 s"


def test_texts_and_effects_on_the_timeline() -> None:
    rows = vm.timeline_overlays(
        text=" 2×1 hoy ",
        place="top",
        text_start=0.0,
        text_end=-1.0,
        effects=["camara_rapida", "vapor_capa"],
        effect_times={"vapor_capa": [3.0, 20.0]},
        total=12.0,
    )
    text, vapor = rows
    assert (text["id"], text["label"], text["start"], text["end"]) == ("texto-1", "2×1 hoy", 0, 12)
    # «Cámara rápida» is the video's «Velocidad», never a block (D-T3); an effect past
    # the new end is cut to it
    assert (vapor["id"], vapor["start"], vapor["end"]) == ("efecto-vapor_capa", 3.0, 12.0)
    assert (
        vm.timeline_overlays(
            text="", place="top", text_start=0, text_end=-1, effects=[], effect_times={}, total=5
        )
        == []
    )


def test_the_address_names_a_block_by_its_place() -> None:
    media = _media()
    overlays = vm.timeline_overlays(
        text="Hola",
        place="bottom",
        text_start=0,
        text_end=-1,
        effects=["vapor_capa"],
        effect_times={},
        total=24,
    )
    assert vm.block_slug(media, overlays, "v1.mp4") == "video-2"
    assert vm.block_slug(media, overlays, "f1.jpg") == "foto-1"
    assert vm.block_slug(media, overlays, "texto-1") == "texto-1"
    assert vm.block_slug(media, overlays, "efecto-vapor_capa") == "efecto-1"
    assert vm.block_from_slug(media, overlays, "video-2") == "v1.mp4"
    assert vm.block_from_slug(media, overlays, "efecto-1") == "efecto-vapor_capa"
    assert vm.block_from_slug(media, overlays, "video-9") == ""
    assert vm.block_from_slug(media, overlays, "foto-2") == ""  # place 2 is a video
    assert vm.block_from_slug(media, overlays, "") == ""
    assert vm.BLOCK_PARAM == "bloque"


def test_a_move_keeps_the_references_in_their_place() -> None:
    keys = ["f1.jpg", "v1.mp4", "pin.jpg", "v2.mp4"]
    assert vm.reorder_keys(keys, ["v2.mp4", "f1.jpg", "v1.mp4"]) == [
        "v2.mp4",
        "f1.jpg",
        "pin.jpg",
        "v1.mp4",
    ]
    assert vm.reorder_keys(keys, ["f1.jpg", "v1.mp4", "v2.mp4"]) == keys


def test_flows_are_held_with_a_mark() -> None:
    assert vm.is_flow("+media") and vm.flow_of("+media") == "media"
    assert vm.flow_of("+nope") == "" and vm.flow_of("v1.mp4") == ""
    assert not vm.is_flow("") and not vm.is_flow("texto-1")
    assert vm.speed_value(fast=False, speed=10) == "1"
    assert vm.speed_value(fast=True, speed=20) == "20"
    assert all(len(items) <= 4 for items in vm.EDITOR_ACTIONS.values())


def test_untouched_the_recipe_is_ed02s() -> None:
    """«Siguiente» without touching anything: the same recipe as before ED-10."""
    kwargs: dict[str, object] = {
        "video_key": "k",
        "start": 0.0,
        "end": 15.0,
        "rotate": 0,
        "effects": ["camara_rapida"],
        "speed": 10,
        "text": "2×1 hoy",
        "place": "bottom",
    }
    before = vm.recipe_of(**kwargs)  # type: ignore[arg-type]
    after = vm.recipe_of(**kwargs, text_start=0.0, text_end=None, effect_times={})  # type: ignore[arg-type]
    assert after == before
    assert before.text_layer is not None
    assert (before.text_layer.start_s, before.text_layer.end_s) == (0.0, None)
    assert (before.effects[0].start_s, before.effects[0].end_s) == (None, None)


def test_moved_text_and_effects_carry_their_seconds() -> None:
    recipe = vm.recipe_of(
        video_key="k",
        start=0,
        end=12,
        rotate=0,
        effects=["vapor_capa"],
        speed=10,
        text="Hola",
        place="top",
        text_start=2.5,
        text_end=6.0,
        effect_times={"vapor_capa": [1.0, 4.5]},
    )
    assert recipe.text_layer is not None
    assert (recipe.text_layer.start_s, recipe.text_layer.end_s) == (2.5, 6.0)
    assert (recipe.effects[0].start_s, recipe.effects[0].end_s) == (1.0, 4.5)


def test_timeline_changes_say_what_changed() -> None:
    base = vm.snapshot(
        start=0, end=10, rotate=0, effects=["vapor_capa"], speed=10, text="a", place="top"
    )
    assert base["order"] == [] and base["text_end"] == -1.0 and base["effect_times"] == {}
    moved = {**base, "order": ["b", "a"]}
    assert vm.change_message(base, moved) == "Cambiaste el orden de tu video."
    timed = {**base, "text_start": 2.0}
    assert vm.change_message(base, timed) == "Cambiaste cuándo sale el texto."
    effect = {**base, "effect_times": {"vapor_capa": [2.0, 9.0]}}
    assert vm.change_message(base, effect) == "Cambiaste cuándo sale Vapor."
    assert vm.effect_removed_line("vapor_capa") == "Quitaste Vapor."
    assert vm.TEXT_REMOVED_LINE == "Quitaste el texto de tu video."


# -- «Cortar» where the marker is (Deivid 2026-11-17) -------------------------------------


def _cut_media() -> list[dict[str, object]]:
    """A 2 s photo, then the own video 0:00–0:15 at ×1, then another at ×5 (10 s → 2 s)."""
    return [
        {"id": "foto", "key": "foto", "kind": "photo", "dur": 2.0},
        {"id": "v", "key": "v", "kind": "video", "src_start": 0.0, "src_end": 15.0},
        {"id": "w", "key": "w", "kind": "video", "src_start": 0.0, "src_end": 10.0, "speed": 5.0},
    ]


def test_split_check_cuts_where_the_marker_is() -> None:
    assert vm.split_check(_cut_media(), "v", 7.0) == (5.0, "")  # 5 s into it
    # at ×5 one second of the video is five of the source
    assert vm.split_check(_cut_media(), "w", 18.0) == (5.0, "")


def test_split_check_says_why_not() -> None:
    assert vm.split_check(_cut_media(), "v", 1.0) == (0.0, vm.CUT_NOT_HERE)  # on the photo
    # its very edge: «Muy cerca del borde», never a bare «not here»
    assert vm.split_check(_cut_media(), "v", 2.0) == (0.0, vm.CUT_TOO_CLOSE)
    assert vm.split_check(_cut_media(), "v", 2.4) == (0.0, vm.CUT_TOO_CLOSE)  # under ½ s
    assert vm.split_check(_cut_media(), "v", 16.6) == (0.0, vm.CUT_TOO_CLOSE)
    # at ×1 a piece keeps at least 1 s of the source: 0.8 s in is too close too
    assert vm.split_check(_cut_media(), "v", 2.8) == (0.0, vm.CUT_TOO_CLOSE)
    # at ×5 the edge is ½ s of the final video (2.5 s of the source)
    assert vm.split_check(_cut_media(), "w", 17.4) == (0.0, vm.too_close_text(0.5))
    assert vm.split_check(_cut_media(), "foto", 1.0) == (0.0, vm.CUT_NOT_HERE)
    assert vm.split_check(_cut_media(), "nope", 5.0) == (0.0, vm.CUT_NOT_HERE)


def test_block_at_finds_the_piece_under_the_marker() -> None:
    media = [
        {"id": "foto", "key": "foto", "kind": "photo", "dur": 2.0},
        {"id": "v", "key": "v", "kind": "video", "src_start": 0.0, "src_end": 5.0},
        {"id": "v#parte-2", "key": "v", "kind": "video", "src_start": 5.0, "src_end": 15.0},
    ]
    assert vm.block_at(media, "v", 1.0) == ""  # on the photo
    assert vm.block_at(media, "v", 3.0) == "v"
    # on the line between two pieces: the one that starts there
    assert vm.block_at(media, "v", 7.0) == "v#parte-2"
    assert vm.block_at(media, "v", 16.9) == "v#parte-2"
    assert vm.block_at(media, "v", 17.0) == ""  # past the end


def test_piece_ids_by_place() -> None:
    assert vm.piece_id("uploads/a.mp4", 0) == "uploads/a.mp4"
    assert vm.piece_id("uploads/a.mp4", 1) == "uploads/a.mp4#parte-2"
    assert vm.piece_of("uploads/a.mp4#parte-3") == ("uploads/a.mp4", 2)
    assert vm.piece_of("uploads/a.mp4") == ("uploads/a.mp4", 0)
    assert vm.piece_of("texto-1") == ("texto-1", 0)


def test_the_recipe_carries_one_segment_per_piece() -> None:
    recipe = vm.recipe_of(
        video_key="v",
        start=0.0,
        end=15.0,
        rotate=90,
        effects=[],
        speed=10,
        text="",
        place="bottom",
        pieces=[[6.0, 15.0], [0.0, 4.0]],
    )
    assert [(s.key, s.start_s, s.end_s, s.rotate) for s in recipe.segments] == [
        ("v", 6.0, 15.0, 90),
        ("v", 0.0, 4.0, 90),
    ]


def test_cut_and_piece_changes_say_what_changed() -> None:
    one = _snap(pieces=[])
    two = _snap(pieces=[[0.0, 4.0], [4.0, 8.0]])
    swapped = _snap(pieces=[[4.0, 8.0], [0.0, 4.0]])
    assert vm.change_message(one, two) == vm.CUT_DONE_LINE
    assert vm.change_message(two, _snap(start=4.0, pieces=[])) == vm.PIECE_REMOVED_LINE
    assert vm.change_message(two, swapped) == vm.ORDER_LINE

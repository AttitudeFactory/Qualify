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
    assert [vm.speed_aria(s) for s in (5, 10, 20)] == [
        "5 veces más rápido",
        "10 veces más rápido",
        "20 veces más rápido",
    ]
    assert (vm.STRIP_OPENS, vm.STRIP_CLOSES) == ("Abre tu video", "Cierra tu video")
    assert vm.MOTION_ONLY_NOTE == (
        "Este video solo guía el movimiento. Para unir varios, usa «Armar mi video por partes»."
    )
    assert vm.FAST_NEEDS_LONGER == (
        "Para usar cámara rápida tu video tiene que durar al menos 15 s."
    )
    assert vm.fast_impossible_line(2) == (
        "Tu video duraría 2 s: muy poco para un reel. Quita la cámara rápida o usa un "
        "video más largo."
    )
    assert vm.fast_on_line(10, had_cut=False) == (
        "Pusiste cámara rápida: usamos todo tu video a ×10."
    )
    assert vm.fast_on_line(5, had_cut=True) == (
        "Pusiste cámara rápida: usamos todo tu video a ×5. Si la quitas, vuelve tu pedazo."
    )
    assert vm.PREVIEW_SLOWER == "En la vista previa se ve más lento que en el video final."
    assert [vm.TOOL_LABELS[t] for t in vm.TOOLS] == ["Fotos y videos", "Idea", "Efectos", "Cortar"]
    assert [vm.TOOL_QUESTIONS[t] for t in vm.TOOLS] == [
        "¿Con qué lo armamos?",
        "¿De qué trata tu video?",
        "¿Qué le pones a tu video?",
        "¿Qué pedazo de tu video usas?",
    ]
    assert vm.ADD_MEDIA == "Agregar fotos o videos"
    assert vm.PRODUCT_PREFIX + "Combo Vecino" == "Tu producto: Combo Vecino"
    assert (vm.PRODUCT_CHANGE, vm.PRODUCT_CHOOSE) == ("Cambiar", "Elegir un producto")
    assert vm.PARTS_LINK == "Armar mi video por partes"
    assert vm.TEXT_TITLE == "Texto sobre el video"
    assert list(vm.TEXT_PLACES.values()) == ["Arriba", "En el medio", "Abajo"]
    assert vm.FREE == "Gratis"
    assert vm.SPEED_TITLE == "Velocidad"
    assert [vm.speed_label(s) for s in (5, 10, 20)] == ["×5", "×10", "×20"]
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
    assert vm.range_line(4, 12) == "Desde 0:04 · Hasta 0:12"
    assert vm.card_title(8) == "Tu video · 8 s"
    assert vm.time_of_total(3, 8) == "0:03 de 0:08"
    assert vm.card_line(["vapor_capa"], "Shawarma") == "Vapor · «Shawarma»"
    assert vm.card_line([], "") == ""


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
    assert vm.fast_proposal(7.33) == (0.0, 7.5, 5)  # on the grid


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
    assert vm.own_video([]) == {}
    assert vm.tools_shown(has_own_video=False) == ["media", "idea", "effects"]
    assert vm.tools_shown(has_own_video=True)[-1] == "cut"
    assert vm.tool_from_slug("cortar") == "cut" and vm.tool_from_slug("x") == ""


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

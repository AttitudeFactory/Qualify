"""ED-07 (m-25026638): the «parte con IA» block's words and rules (`ai_block_vm`), pure."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from qualify_api.creative.part_progress import PartState
from qualify_api.creative.video_pipeline import ai_parts as contract_ai
from qualify_api.creative.video_pipeline import validate_recipe
from qualify_api.creative.video_pipeline.mode_choice import MODE_REASON_TEXTS
from qualify_creative import schemas
from qualify_creative.schemas import VideoPartPlan

from . import ai_block_vm as vm
from . import clip_editor_vm, part_editor_vm, part_review_vm
from . import reel_parts_vm as parts

#: The contract's §3 table as `main` has it (`docs/contrato-editor-unico.md`, PR 1
#: m-25129405, f7d8c350), copied literally: the screen reads `ai_parts.AI_PART_TEXTS`,
#: and this copy and the doc's table pin that nothing changed under it unnoticed.
CONTRACT_TABLE = {
    "switched_off": (
        "Las partes con IA todavía no están disponibles. Quítalas para crear tu video."
    ),
    "too_many_blocks": (
        "Tu video puede tener hasta 8 fotos, videos o partes con IA. Quita una para seguir."
    ),
    "too_many_ai_children": (
        "Entre partes con IA y escenas del personaje puedes tener hasta 6 en un video. "
        "Quita una para seguir."
    ),
    "extend_needs_block_before": (
        "«Sigue a la anterior» necesita una parte con IA justo antes. "
        "Pon esta parte después de una, o elige «Nueva»."
    ),
    "extend_after_own_media": (
        "«Sigue a la anterior» solo continúa una parte con IA, no una foto o un video tuyo. "
        "Pon una parte con IA justo antes o elige «Nueva»."
    ),
    "extend_not_same_moment": (
        "«Sigue a la anterior» solo sirve si esta parte y la anterior salen del mismo "
        "momento del video de inspiración. Elige «Nueva»."
    ),
    "edit_needs_reel_window": (
        "«Igual al original» solo sirve con partes que vienen de un video de inspiración. "
        "Elige «Nueva»."
    ),
    "ai_part_with_speed": (
        "Las partes con IA siempre van a velocidad normal. Quita la cámara rápida de esta parte."
    ),
    "own_media_too_short": (
        "Con un personaje en tu video necesitas al menos 3 segundos de tus fotos o videos. "
        "Agrega más o alarga los que ya tienes."
    ),
    "ai_parts_mismatch": (
        "Tuvimos un problema con una de tus partes con IA. Quítala y agrégala de nuevo."
    ),
    "ai_part_length_mismatch": (
        "Una parte con IA no dura lo que marcaste. Cambia sus segundos para que coincidan."
    ),
    "ai_part_outside_clip": (
        "Las partes con IA solo se pueden usar en un video que armas con tus fotos y videos. "
        "Quita esta parte para seguir."
    ),
    "ai_part_local": (
        "Para usar tus fotos y videos no necesitas una parte con IA. Agrégalos directo en tu video."
    ),
    "ai_part_own_recipe": (
        "Los textos, efectos y uniones van en tu video, no dentro de la parte con IA. "
        "Quítalos de esta parte y agrégalos al video."
    ),
    "ai_part_guide_type": (
        "No podemos usar ese archivo como guía. Sube un video MP4 o MOV, o un audio MP3 o WAV."
    ),
    # m-25129406 (PR 2): «Sigue a la anterior» after an own video, `QUALIFY_CLIP_EXTEND_OWN_VIDEO`
    "extend_own_video_speed": (
        "Ese video va rápido o lento. Déjalo a velocidad normal para continuarlo."
    ),
    "extend_own_video_short": (
        "Ese video dura menos de 2 segundos. Usa uno más largo o elige «Nueva»."
    ),
}

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
#: Two reel analyses (`VideoPartPlan.analysis_id` is a UUID).
REEL = "33333333-3333-3333-3333-333333333333"
REEL_B = "44444444-4444-4444-4444-444444444444"
#: A valid layer effect use, for «a recipe of its own» on an entry.
HUMO = {"effect_id": "humo", "version": 1}


@pytest.fixture(autouse=True)
def _ai_parts_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The contract's rules run only with `QUALIFY_CLIP_AI_PARTS` on (off: only
    `switched_off`, its own test)."""
    monkeypatch.setenv(contract_ai.CLIP_AI_PARTS_SWITCH, "on")
    yield


def photo(seconds: float = 2.0) -> dict[str, Any]:
    return {"kind": "photo", "key": "t/x/p.jpg", "start_s": 0, "end_s": seconds, "speed": 1}


def video(seconds: float = 5.0, speed: float = 1.0) -> dict[str, Any]:
    return {"kind": "video", "key": "t/x/v.mp4", "start_s": 0, "end_s": seconds, "speed": speed}


def ai(n: int, seconds: float = 5.0, **extra: Any) -> dict[str, Any]:
    return {
        "kind": "ai_part",
        "key": f"ai_part:{n}",
        "start_s": 0,
        "end_s": seconds,
        "speed": 1,
        "rotate": 0,
        **extra,
    }


def entry(seconds: int = 5, **plan: Any) -> dict[str, Any]:
    return {"mode": "reference", "seconds": seconds, **plan}


# -- contract parity ---------------------------------------------------------------------


def test_refusal_texts_match_the_contract_table() -> None:
    for code, text in CONTRACT_TABLE.items():
        assert vm.AI_PART_TEXTS[code] == text, code
        assert vm.refusal_text(code) == text
        assert vm.refusal_text(code) == contract_ai.ai_part_text(code)
    assert set(vm.AI_PART_TEXTS) == set(CONTRACT_TABLE)
    assert vm.AI_PART_TEXTS is contract_ai.AI_PART_TEXTS  # read, never copied
    assert vm.refusal_text("nope") == ""


def test_the_contracts_words_need_no_bloque() -> None:
    # contract §3.3: «bloque» stays where the screen already says it (Deivid 2026-11-26),
    # and the contract's new words neither need it nor say «línea de tiempo»
    for text in (*vm.AI_PART_TEXTS.values(), *vm.KEY_TEXTS.values()):
        assert "bloque" not in text.lower(), text
        assert "línea de tiempo" not in text.lower(), text


def test_key_texts_are_todays() -> None:
    from qualify_api.creative import media  # noqa: PLC0415

    assert vm.refusal_text("malformed_key") == media._BAD_KEY
    assert vm.refusal_text("foreign_key") == media._FOREIGN_FILE
    assert vm.refusal_text("foreign_key") == "Uno de los archivos de la pieza no es de tu marca."


def _doc_table(text: str) -> dict[str, str]:
    rows = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and re.fullmatch(r"`[a-z_]+`", cells[0]):
            rows[cells[0].strip("`")] = cells[3]
    return rows


def test_refusal_texts_match_the_contract_doc() -> None:
    doc = Path(__file__).resolve().parent.parent / "docs" / "contrato-editor-unico.md"
    table = _doc_table(doc.read_text(encoding="utf-8"))
    assert set(table) == set(CONTRACT_TABLE)
    for code, text in table.items():
        assert vm.AI_PART_TEXTS[code] == text, code


def test_refusal_texts_and_key_are_pr1s_code() -> None:
    assert dict(contract_ai.AI_PART_TEXTS) == CONTRACT_TABLE
    assert all(schemas.ai_part_key(n) == vm.ai_part_key(n) for n in range(6))
    assert vm.AI_PART_KIND == schemas.AI_PART_KIND == "ai_part"
    assert (vm.GUIDE_VIDEO_SUFFIXES, vm.GUIDE_AUDIO_SUFFIXES) == (
        contract_ai.GUIDE_VIDEO_SUFFIXES,
        contract_ai.GUIDE_AUDIO_SUFFIXES,
    )


def test_caps_are_the_contract_caps() -> None:
    assert (vm.BLOCKS_MAX, vm.AI_CHILDREN_MAX) == (8, 6)
    assert (vm.CLIP_MIN_SECONDS, vm.CLIP_MAX_SECONDS, vm.OWN_MEDIA_MIN_SECONDS) == (3, 60, 3)
    assert (vm.SECONDS_MIN, vm.SECONDS_MAX, vm.SECONDS_DEFAULT) == (1, 10, 5)


# -- names -------------------------------------------------------------------------------


def test_names() -> None:
    assert vm.ai_part_name(2) == "Parte con IA 2"
    assert vm.missing_description_line(1) == "Falta contar qué pasa en la parte con IA 1."
    assert vm.PREVIEW_MARK.format(n=1) == "Parte con IA 1 · se crea al tocar «Crear»"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("La parte 1 está para revisar.", "La parte con IA 1 está para revisar."),
        ("Se crea cuando esté la parte 2.", "Se crea cuando esté la parte con IA 2."),
        ("Estamos creando la parte 3.", "Estamos creando la parte con IA 3."),
        (
            "Falta contar qué pasa en las partes 2 y 4.",
            "Falta contar qué pasa en las partes 2 y 4.",
        ),
        ("La parte con IA 1 está lista.", "La parte con IA 1 está lista."),
        ("", ""),
    ],
)
def test_with_ai_name(text: str, expected: str) -> None:
    assert vm.with_ai_name(text) == expected


# -- the mode badge ----------------------------------------------------------------------


def test_badge_of_a_new_part_from_agregar() -> None:
    _segment, plan = vm.new_ai_block(0)
    badge = vm.mode_badge(plan)
    assert badge["short"] == "Nueva"
    assert badge["full"] == "Nueva, con tu producto"
    assert badge["reason"] == "Nueva, con tu producto."
    assert (badge["changed"], badge["back_to"], badge["back_label"]) == ("", "", "")
    assert vm.mode_badge(plan, has_product=False)["full"] == "Nueva, con tu marca"


def test_badge_short_and_full_per_mode() -> None:
    edit = {"mode": "edit", "mode_rule_version": 1, "mode_reason": "reel_no_people"}
    edit["analysis_id"] = REEL
    badge = vm.mode_badge(edit)
    assert (badge["short"], badge["full"]) == (
        "Igual al original",
        "Igual al original, con tu producto",
    )
    assert badge["reason"] == MODE_REASON_TEXTS["reel_no_people"]
    extend = {"mode": "extend", "mode_rule_version": 1, "mode_reason": "split_cut_continues"}
    badge = vm.mode_badge(extend)
    assert (badge["short"], badge["full"]) == ("Sigue a la anterior", "Sigue a la anterior")
    assert badge["reason"] == "Sigue a la anterior: continúa la misma toma del original."
    inspired = {"mode": "reference", "analysis_id": REEL, "mode_rule_version": 1}
    inspired["mode_reason"] = "reel_people"
    badge = vm.mode_badge(inspired)
    assert (badge["short"], badge["full"]) == ("Nueva", "Nueva, inspirada en el original")
    assert badge["reason"] == "Nueva, inspirada en el original: en el original aparece una persona."


def test_badge_changed_by_owner() -> None:
    plan = {"mode": "reference", "mode_rule_version": 1, "mode_reason": "reel_no_people"}
    badge = vm.mode_badge(plan)
    assert badge["reason"] == "Lo cambiaste tú."
    assert badge["changed"] == "1"
    assert badge["back_to"] == "edit"
    assert badge["back_label"] == "Volver a lo que te propusimos"
    # the stored flag alone says it too
    flagged = {"mode": "reference", "mode_rule_version": 1, "mode_reason": "no_source"}
    flagged["mode_changed_by_owner"] = True
    assert vm.mode_reason_text(flagged) == "Lo cambiaste tú."
    assert vm.mode_badge(flagged)["back_to"] == "reference"


@pytest.mark.parametrize(
    "plan",
    [
        {"mode": "reference"},
        {"mode": "reference", "mode_rule_version": 0, "mode_reason": "no_source"},
        {"mode": "reference", "mode_rule_version": 1, "mode_reason": "merged_parts"},
    ],
)
def test_no_reason_without_a_rule(plan: dict[str, Any]) -> None:
    assert vm.mode_reason_text(plan) == ""
    assert vm.mode_badge(plan)["changed"] == ""


# -- «¿Cómo la hacemos?» ------------------------------------------------------------------


def _option(rows: list[dict[str, str]], mode: str) -> dict[str, str]:
    return next(row for row in rows if row["mode"] == mode)


def _split(**plan: Any) -> dict[str, Any]:
    """An entry the plan split from one long take of reel «r»."""
    return entry(mode="extend", original_mode="extend", analysis_id=REEL, **plan)


def test_extend_continues_only_an_ai_part_right_before() -> None:
    plain = {"plan": entry()}
    first = vm.mode_options(plain, [ai(0)], [entry()], 0, extend_on=True)
    assert _option(first, "extend")["reason"] == CONTRACT_TABLE["extend_needs_block_before"]
    for own in (photo(), video()):
        rows = vm.mode_options(plain, [own, ai(0)], [entry()], 1, extend_on=True)
        assert _option(rows, "extend")["reason"] == CONTRACT_TABLE["extend_after_own_media"]
    # an AI part before, but this one was not split from the same take
    not_split = vm.mode_options(plain, [ai(0), ai(1)], [entry(), entry()], 1, extend_on=True)
    assert _option(not_split, "extend")["reason"] == CONTRACT_TABLE["extend_not_same_moment"]
    off = vm.mode_options(plain, [ai(0)], [entry()], 0, extend_on=False)
    assert _option(off, "extend")["reason"] == "Por ahora no está disponible. Elige otra forma."


def test_extend_same_moment_of_the_reel() -> None:
    before = entry(analysis_id=REEL, shot_indexes=[3, 4])
    segments = [ai(0), ai(1)]
    ok = _split(shot_indexes=[4, 5])
    assert vm.extend_code(segments, [before, ok], 1) == ""
    assert vm.extend_reason(segments, [before, ok], 1, extend_on=True) == ""
    for bad in (
        {**ok, "original_mode": None},  # not born «Sigue a la anterior»
        {**ok, "original_mode": "reference"},
        {**ok, "analysis_id": REEL_B},  # another reel
        {**ok, "analysis_id": None},
        {**ok, "shot_indexes": [5, 6]},  # does not start on the last cut before
        {**ok, "shot_indexes": []},
    ):
        assert vm.extend_code(segments, [before, bad], 1) == "extend_not_same_moment", bad
    assert vm.extend_code(segments, [{**before, "shot_indexes": []}, ok], 1) == (
        "extend_not_same_moment"
    )
    # the panel asks with the entry as it would be, before the mode changes
    rows = vm.mode_options({"plan": ok}, segments, [before, entry()], 1, extend_on=True)
    assert _option(rows, "extend")["reason"] == ""
    # a key pointing nowhere is `ai_parts_mismatch`'s business, not this rule's
    assert vm.extend_code([ai(5), ai(1)], [before, ok], 1) == ""


def test_edit_needs_the_reel_window() -> None:
    no_reel = vm.mode_options({"plan": entry()}, [ai(0)], [entry()], 0, extend_on=True)
    assert _option(no_reel, "edit")["reason"] == CONTRACT_TABLE["edit_needs_reel_window"]
    no_cuts = {"plan": entry(analysis_id=REEL, shot_indexes=[])}
    assert vm.edit_reason(no_cuts) == CONTRACT_TABLE["edit_needs_reel_window"]


def test_edit_with_the_window_keeps_todays_reasons() -> None:
    window = entry(mode="edit", analysis_id=REEL, shot_indexes=[2])
    person = {"plan": window, "person": True, "reason": "person"}
    assert vm.edit_reason(person, images=[{"key": "k"}]) == (
        "Aquí aparece una persona y no podemos usar ese video."
    )
    short = {"plan": {**window, "seconds": 3}, "person": False, "reason": ""}
    assert vm.edit_reason(short, images=[{"key": "k"}]) == (
        "Esta parte dura 3 s y para conservar el original necesita al menos 4. "
        "Júntala con la siguiente o hazla nueva."
    )
    ok = {"plan": window, "person": False, "reason": ""}
    assert vm.edit_reason(ok, images=[{"key": "k"}]) == ""
    assert vm.edit_reason(ok) == "Agrega una foto de tu producto para conservar el video."


def test_mode_options_labels_help_and_choice() -> None:
    reel = {"plan": entry(analysis_id=REEL, shot_indexes=[1]), "person": True}
    rows = vm.mode_options(reel, [video(), ai(0)], [reel["plan"]], 1, extend_on=True)
    assert [r["mode"] for r in rows] == ["edit", "reference", "extend"]
    assert [r["short"] for r in rows] == ["Igual al original", "Nueva", "Sigue a la anterior"]
    assert [r["label"] for r in rows] == [
        "Igual al original, con tu producto",
        "Nueva, inspirada en el original",
        "Sigue a la anterior",
    ]
    assert _option(rows, "reference") == {
        "mode": "reference",
        "label": "Nueva, inspirada en el original",
        "help": part_editor_vm.REFERENCE_HELP,
        "reason": "",
        "short": "Nueva",
        "chosen": "1",
    }
    assert _option(rows, "edit")["help"] == part_editor_vm.EDIT_HELP
    assert _option(rows, "extend")["help"] == part_editor_vm.EXTEND_HELP
    no_reel = vm.mode_options(
        {"plan": entry()}, [ai(0)], [entry()], 0, extend_on=False, has_product=False
    )
    assert _option(no_reel, "reference")["label"] == "Nueva, con tu marca"
    assert _option(no_reel, "reference")["help"] == part_editor_vm.NEW_HELP


# -- seconds -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, 1),
        (-3, 1),
        (1, 1),
        (10, 10),
        (11, 10),
        (4.4, 4),
        (4.5, 5),
        ("7", 7),
        ("3,6", 4),
        (None, 5),
        ("abc", 5),
        (float("inf"), 5),
        (float("nan"), 5),
    ],
)
def test_clamp_seconds(raw: object, expected: int) -> None:
    assert vm.clamp_seconds(raw) == expected


def test_seconds_control() -> None:
    plain = vm.seconds_control(5, 20)
    assert plain == {
        "value": "5",
        "text": "5 s",
        "label": "Cuánto dura en tu video",
        "help": "De 1 a 10 s.",
        "minus_reason": "",
        "plus_reason": "",
        "note": "",
    }
    one = vm.seconds_control(1, 20)
    assert one["minus_reason"] == "Una parte con IA dura al menos 1 s."
    assert one["note"] == (
        "Se crea de 4 s y usa 4 s de tu mes. Cuando esté lista, eliges qué 1 s usar "
        "arrastrando sus barras."
    )
    assert vm.seconds_control(3, 20)["note"].endswith("eliges qué 3 s usar arrastrando sus barras.")
    assert vm.seconds_control(4, 20)["note"] == ""
    assert vm.seconds_control(10, 20)["plus_reason"] == "Una parte con IA dura 10 s como máximo."
    assert vm.seconds_control(5, 59.5)["plus_reason"] == "Tu video pasaría de 60 s."
    assert vm.seconds_control(5, 59)["plus_reason"] == ""
    assert vm.seconds_control(99, 20)["value"] == "10"


# -- the block on the track --------------------------------------------------------------


def test_track_block_before_creating() -> None:
    _segment, plan = vm.new_ai_block(0)
    block = vm.track_block(1, plan, start_s=6, poster="/p.jpg")
    assert block == {
        "name": "Parte con IA 1",
        "mark": "✦",
        "badge": "Nueva",
        "full": "Nueva, con tu producto",
        "line": "Parte con IA 1 · 5 s",
        "seconds": "5",
        "state": "plan",
        "state_word": "Sin crear",
        "tone": "neutral",
        "picture": "/p.jpg",
        "dimmed": "1",
        "aria": "Parte con IA 1, Nueva, de 0:06 a 0:11, sin crear",
        "detail": "",
        "handles": "seconds",
    }


@pytest.mark.parametrize(
    ("state", "key", "word", "tone", "picture", "handles"),
    [
        (PartState.QUEUED, "queued", "En fila", "neutral", "/p.jpg", ""),
        ("creating", "creating", "Creando", "info", "/p.jpg", ""),
        (PartState.TO_REVIEW, "review", "Para revisar", "warn", "/f.jpg", "trim"),
        (PartState.READY, "ready", "Lista", "ok", "/f.jpg", "trim"),
        (PartState.FAILED, "failed", "No salió", "error", "/p.jpg", ""),
        (PartState.ORIGINAL_REFUSED, "refused", "No se pudo con el original", "warn", "/p.jpg", ""),
        (PartState.REDO, "redo", "Hay que rehacerla", "warn", "/f.jpg", ""),
        (PartState.EXPIRED, "expired", "Venció", "warn", "/f.jpg", ""),
        ("whatever", "plan", "Sin crear", "neutral", "/p.jpg", "seconds"),
        (None, "plan", "Sin crear", "neutral", "/p.jpg", "seconds"),
    ],
)
def test_track_block_states(
    state: object, key: str, word: str, tone: str, picture: str, handles: str
) -> None:
    plan = entry(4, mode="edit")
    block = vm.track_block(2, plan, start_s=0, state=state, poster="/p.jpg", frame="/f.jpg")  # type: ignore[arg-type]
    assert (block["state"], block["state_word"], block["tone"]) == (key, word, tone)
    assert block["picture"] == picture
    assert block["dimmed"] == ("1" if picture == "/p.jpg" else "")
    assert block["handles"] == handles
    assert block["badge"] == "Igual al original"
    assert block["line"] == (word if key != "plan" else "Parte con IA 2 · 4 s")
    assert block["aria"] == f"Parte con IA 2, Igual al original, de 0:00 a 0:04, {word.lower()}"


def test_track_block_failure_detail_says_parte_con_ia() -> None:
    block = vm.track_block(
        3, entry(), start_s=0, state="queued", detail="Se crea cuando esté la parte 2."
    )
    assert block["detail"] == "Se crea cuando esté la parte con IA 2."
    # made, but no frame yet: the poster stays
    assert vm.track_block(1, entry(), start_s=0, state="ready", poster="/p")["picture"] == "/p"


def test_announcement() -> None:
    assert vm.announcement(1, "to_review") == "La parte con IA 1 está para revisar."
    assert vm.announcement(2, PartState.EXPIRED) == "La vista previa de la parte con IA 2 venció."
    assert vm.announcement(3, "creating") == "Estamos creando la parte con IA 3."


# -- caps --------------------------------------------------------------------------------


def test_add_reason() -> None:
    assert vm.add_reason([photo(), video()]) == ""
    full = [photo(1)] * 8
    assert vm.add_reason(full) == "Tu video ya tiene 8 fotos o videos. Quita una para agregar otra."
    assert vm.add_reason(full) == clip_editor_vm.FULL_LINE
    six = [ai(n, 2) for n in range(6)]
    assert vm.add_reason(six) == (
        "Tu video ya tiene 6 partes con IA, el máximo. Quita una para agregar otra."
    )
    five = [ai(n, 2) for n in range(5)]
    assert vm.add_reason(five) == ""
    assert vm.add_reason(five, other_ai_children=1) == (
        "Tu video ya tiene 6 partes con IA, el máximo. Quita una para agregar otra. "
        "Las escenas con personaje también cuentan."
    )
    long = [video(30), video(30)]
    assert vm.add_reason(long) == (
        "Tu video ya dura 60 s, el máximo. Acorta o quita una parte para agregar otra."
    )
    assert vm.add_reason([video(30), video(29.5)]) == vm.FULL_SECONDS_LINE
    assert vm.add_reason([video(30), video(29)]) == ""


def test_new_part_seconds_fits_under_60() -> None:
    assert vm.new_part_seconds([video(10)]) == 5
    assert vm.only_left_line([video(10)]) == ""
    assert vm.new_part_seconds([video(30), video(27)]) == 3
    assert (
        vm.only_left_line([video(30), video(27)]) == "Solo quedaban 3 s: la parte nueva dura 3 s."
    )
    assert vm.new_part_seconds([video(30), video(30)]) == 0
    assert vm.only_left_line([video(30), video(30)]) == ""
    # a fast video counts at its speed
    assert vm.new_part_seconds([video(60, speed=2), video(27)]) == 3


def _codes(problems: list[dict[str, str]]) -> list[tuple[str, str]]:
    return [(p["code"], p["field"]) for p in problems]


def test_preflight_ok_and_only_ai_parts() -> None:
    assert vm.preflight_problems([photo(), ai(0)], [entry()]) == []
    # a Clip made only of AI parts is valid (contract §3, §5)
    assert vm.preflight_problems([ai(0), ai(1, 4)], [entry(), entry(4)]) == []
    # nothing AI: not this module's business
    assert vm.preflight_problems([photo(1)] * 9, []) == []


def test_preflight_caps_use_the_contract_words() -> None:
    nine = [photo(1)] * 8 + [ai(0)]
    problems = vm.preflight_problems(nine, [entry()])
    assert _codes(problems) == [("too_many_blocks", "segments")]
    assert problems[0]["text"] == CONTRACT_TABLE["too_many_blocks"]
    seven = [ai(n, 2) for n in range(7)]
    problems = vm.preflight_problems(seven, [entry(2)] * 7)
    assert _codes(problems) == [("too_many_ai_children", "ai_parts")]
    assert problems[0]["text"] == CONTRACT_TABLE["too_many_ai_children"]
    problems = vm.preflight_problems(seven[:5], [entry(2)] * 5, other_ai_children=2)
    assert ("too_many_ai_children", "ai_parts") in _codes(problems)


def test_preflight_own_media_rule_only_with_scenes() -> None:
    clip = [photo(2), ai(0)]
    assert vm.preflight_problems(clip, [entry()]) == []
    problems = vm.preflight_problems(clip, [entry()], other_ai_children=1)
    assert _codes(problems) == [("own_media_too_short", "segments")]
    assert problems[0]["text"] == CONTRACT_TABLE["own_media_too_short"]
    assert vm.preflight_problems([photo(3), ai(0)], [entry()], other_ai_children=1) == []


def test_preflight_per_block_rules() -> None:
    problems = vm.preflight_problems(
        [photo(), ai(0), video(), ai(1, 10, speed=2)],
        [entry(mode="extend"), entry(mode="edit", analysis_id=REEL, seconds=5, effects=[HUMO])],
    )
    assert _codes(problems) == [
        ("extend_after_own_media", "ai_parts[0].mode"),
        ("ai_part_with_speed", "segments[3].speed"),
        ("edit_needs_reel_window", "ai_parts[1].shot_indexes"),
        ("ai_part_own_recipe", "ai_parts[1]"),
    ]
    for problem in problems:
        assert problem["text"] == CONTRACT_TABLE[problem["code"]]
    problems = vm.preflight_problems([ai(0, 3), video()], [entry(5)])
    assert _codes(problems) == [("ai_part_length_mismatch", "segments[0].end_s")]
    # a `local` entry the type can read carries its own stretches: both codes say it
    own = {"kind": "photo", "key": "t/x/p.jpg", "start_s": 0, "end_s": 3}
    problems = vm.preflight_problems([ai(0, 3), video()], [entry(3, mode="local", segments=[own])])
    assert _codes(problems) == [
        ("ai_part_local", "ai_parts[0].mode"),
        ("ai_part_own_recipe", "ai_parts[0]"),
    ]
    # one the type cannot read at all (a `local` with nothing) is «quítala y agrégala»
    unreadable = vm.preflight_problems([ai(0, 3), video()], [entry(3, mode="local")])
    assert _codes(unreadable) == [("ai_parts_mismatch", "ai_parts[0]")]
    first = vm.preflight_problems([ai(0)], [entry(mode="extend")])
    assert _codes(first) == [("extend_needs_block_before", "ai_parts[0].mode")]
    after_video = vm.preflight_problems([video(), ai(0)], [entry(mode="extend")])
    assert _codes(after_video) == [("extend_after_own_media", "ai_parts[0].mode")]
    before = entry(analysis_id=REEL, shot_indexes=[3, 4])
    not_same = vm.preflight_problems([ai(0), ai(1)], [before, _split(shot_indexes=[7])])
    assert _codes(not_same) == [("extend_not_same_moment", "ai_parts[1].mode")]
    assert not_same[0]["text"] == CONTRACT_TABLE["extend_not_same_moment"]
    same = vm.preflight_problems([ai(0), ai(1)], [before, _split(shot_indexes=[4])])
    assert same == []


def test_preflight_with_the_switch_off_says_only_switched_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(contract_ai.CLIP_AI_PARTS_SWITCH, "off")
    problems = vm.preflight_problems([photo(), ai(0)], [entry()])
    assert _codes(problems) == [("switched_off", "segments[1]")]
    assert problems[0]["text"] == CONTRACT_TABLE["switched_off"]
    # nothing AI: nothing to say, switch or not
    assert vm.preflight_problems([photo(), video()], []) == []


def test_preflight_is_validate_recipe() -> None:
    """The screen's list is the contract's answer, kept to the AI blocks."""
    segments = [photo(), ai(0), video(), ai(1, 4)]
    entries = [entry(mode="extend"), entry(4)]
    part = schemas.PartRecipe(
        index=1,
        mode="local",
        seconds=16,
        segments=tuple(schemas.SourceSegment.model_validate(s) for s in segments),
    )
    server = validate_recipe(
        (part,),
        video_by_parts=False,
        ai_parts=tuple(VideoPartPlan.model_validate(e) for e in entries),
        other_ai_children=0,
    )
    assert [(p.code, p.field) for p in server if p.code in CONTRACT_TABLE] == _codes(
        vm.preflight_problems(segments, entries)
    )


@pytest.mark.parametrize(
    ("segments", "entries", "at"),
    [
        ([ai(0)], [entry()], 0),
        ([photo(), ai(0)], [entry()], 1),
        ([video(), ai(0)], [entry()], 1),
        ([ai(0), ai(1)], [entry(), entry()], 1),
        (
            [ai(0), ai(1)],
            [entry(analysis_id=REEL, shot_indexes=[3, 4]), _split(shot_indexes=[4, 5])],
            1,
        ),
        (
            [ai(0), ai(1)],
            [entry(analysis_id=REEL, shot_indexes=[3, 4]), _split(shot_indexes=[5])],
            1,
        ),
    ],
)
def test_extend_reason_is_the_contracts_rule(
    segments: list[dict[str, Any]], entries: list[dict[str, Any]], at: int
) -> None:
    """«¿Cómo la hacemos?» says why «Sigue a la anterior» is off with the code the
    contract would give that part made «Sigue a la anterior»."""
    entry_at = vm.ai_part_at(segments[at]["key"])
    assert entry_at is not None
    wanted = [dict(e) for e in entries]
    wanted[entry_at] = vm.with_mode(wanted[entry_at], "extend")
    contract_codes = [
        p["code"] for p in vm.preflight_problems(segments, wanted) if p["field"].endswith(".mode")
    ]
    code = vm.extend_code(segments, entries, at, wanted[entry_at])
    assert contract_codes == ([code] if code else [])


def test_preflight_mismatch() -> None:
    problems = vm.preflight_problems([video(), ai(3)], [entry()])
    assert _codes(problems) == [
        ("ai_parts_mismatch", "segments[1]"),
        ("ai_parts_mismatch", "ai_parts[0]"),
    ]
    twice = vm.preflight_problems([ai(0), ai(0)], [entry()])
    assert _codes(twice) == [("ai_parts_mismatch", "segments[1]")]
    assert twice[0]["text"] == CONTRACT_TABLE["ai_parts_mismatch"]


def test_preflight_length_in_clip_editor_words() -> None:
    problems = vm.preflight_problems([ai(0, 2)], [entry(2)])
    assert _codes(problems) == [("local_length_out_of_range", "segments")]
    assert (
        problems[0]["text"]
        == "Tu video dura 2 s y necesita al menos 3 s. Agrega otra foto o video."
    )
    joined = [
        video(1),
        ai(
            0,
            2,
            transition_in={"effect_id": "fundido", "version": 2, "params": {"duration_s": 0.5}},
        ),
    ]
    assert vm.clip_seconds(joined) == 2.5
    assert vm.preflight_problems(joined, [entry(2)])[0]["text"] == (
        clip_editor_vm.length_out_of_range_line(2.5)
    )
    long = [video(30), video(25), ai(0, 10)]
    problems = vm.preflight_problems(long, [entry(10)])
    assert _codes(problems) == [("local_length_out_of_range", "segments")]
    assert problems[0]["text"].startswith("Tu video dura 65 s y puede durar hasta 60 s.")


def test_seconds_helpers() -> None:
    clip = [photo(2), video(10, speed=2), ai(0, 5)]
    assert vm.laid_seconds(clip) == 12
    assert vm.own_seconds(clip) == 7
    assert vm.ai_block_count(clip) == 1
    assert vm.block_seconds({"start_s": "x", "end_s": None}) == 0
    assert vm.ai_numbers([photo(), ai(1), video(), ai(0)]) == {1: 1, 3: 2}


# -- cost --------------------------------------------------------------------------------


def test_try_line() -> None:
    described = entry(description="Una mano acerca el vaso")
    assert vm.TRY_LABEL == "Probar esta parte"
    assert vm.try_line(described, previews_left=12, previews_quota=20) == (
        "Usa 1 vista previa. Te quedan 12. Las demás las creas con «Crear».",
        "",
    )
    assert vm.try_line(described, previews_left=1, previews_quota=20)[0] == (
        "Usa 1 vista previa. Te queda 1. Las demás las creas con «Crear»."
    )
    assert vm.try_line(entry(), previews_left=12, previews_quota=20)[1] == (
        "Cuéntanos qué pasa en esta parte para probarla."
    )
    none_left = vm.try_line(described, previews_left=0, previews_quota=20, renews="1 de diciembre")
    assert none_left == (
        "Este mes no te quedan vistas previas. Vuelven el 1 de diciembre.",
        "Este mes no te quedan vistas previas. Vuelven el 1 de diciembre.",
    )
    assert vm.try_line(described, previews_left=0, previews_quota=20)[0] == (
        part_review_vm.NO_PREVIEWS_SOON_TEXT
    )
    assert vm.try_line(described, previews_left=0, previews_quota=0) == (
        "Usa 1 vista previa. Las demás las creas con «Crear».",
        "",
    )


def test_redo_line() -> None:
    assert vm.REDO_LABEL == "Rehacer esta parte"
    assert vm.redo_line(previews_left=11, previews_quota=20) == (
        "Usa 1 vista previa. Te quedan 11.",
        False,
    )
    assert vm.redo_line(previews_left=0, previews_quota=20, renews="1 de diciembre") == (
        "Este mes no te quedan vistas previas. Vuelven el 1 de diciembre.",
        True,
    )
    assert vm.redo_line(previews_left=0, previews_quota=0) == (part_review_vm.CHANGE_NOTE, False)


def test_review_cost_lines_as_signed() -> None:
    clip = [photo(), photo(), video(), ai(0, 5), ai(1, 3)]
    lines = vm.review_cost_lines(
        clip,
        [entry(5), entry(3)],
        previews_left=12,
        previews_quota=20,
        seconds_left=40,
        seconds_quota=60,
    )
    assert lines == {
        "now": (
            "Ahora, al crear: 2 vistas previas, una por cada parte con IA. Te quedan 12. "
            "Tus fotos y tu video no gastan nada."
        ),
        "later": (
            "Después, al aprobar: 9 s de video, solo los de las partes con IA (la de 3 s "
            "cuenta como 4). Este mes te quedan 40 s."
        ),
        "not_counted": "Si una parte no sale, no se descuenta su vista previa.",
        "foot": "Usa 2 vistas previas. Te quedan 12.",
    }


def test_review_cost_lines_variants() -> None:
    one = vm.review_cost_lines(
        [photo(), ai(0)],
        [entry()],
        previews_left=1,
        previews_quota=20,
        seconds_left=1,
        seconds_quota=60,
    )
    assert one["now"] == (
        "Ahora, al crear: 1 vista previa, la de tu parte con IA. Te queda 1. Tu foto no gasta nada."
    )
    assert one["later"] == (
        "Después, al aprobar: 5 s de video, solo los de la parte con IA. Este mes te queda 1 s."
    )
    assert one["foot"] == "Usa 1 vista previa. Te queda 1."
    only_ai = vm.review_cost_lines(
        [ai(0, 2), ai(1, 1)],
        [entry(2), entry(1)],
        previews_left=0,
        previews_quota=0,
        seconds_left=0,
        seconds_quota=0,
    )
    assert only_ai["now"] == "Ahora, al crear: 2 vistas previas, una por cada parte con IA."
    assert only_ai["later"] == (
        "Después, al aprobar: 8 s de video, solo los de las partes con IA (las de menos de "
        "4 s cuentan como 4)."
    )
    videos = vm.review_cost_lines(
        [video(), video(), ai(0)],
        [entry()],
        previews_left=3,
        previews_quota=20,
        seconds_left=40,
        seconds_quota=60,
    )
    assert videos["now"].endswith("Te quedan 3. Tus videos no gastan nada.")
    assert vm.review_cost_lines(
        [photo()], [], previews_left=3, previews_quota=20, seconds_left=40, seconds_quota=60
    ) == {"now": "", "later": "", "not_counted": "", "foot": ""}
    assert vm.ai_seconds_used([entry(1), entry(4), entry(10)]) == 18


def test_create_reason_without_previews_says_the_free_way() -> None:
    clip = [photo(), photo(), video(), ai(0), ai(1, 3)]
    body, foot = vm.create_reason(
        clip, [entry(), entry(3)], previews_left=0, previews_quota=15, renews="1 de diciembre"
    )
    assert body == (
        "Crear tu video usa 2 vistas previas, y ya usaste tus 15 de este mes. Vuelven el 1 "
        "de diciembre. Si lo quieres hoy, quita las 2 partes con IA: con tus fotos y tu "
        "video se crea gratis."
    )
    assert foot == "Ya usaste tus vistas previas del mes."
    assert foot == parts.FOOT_NO_PREVIEWS
    only_ai, _ = vm.create_reason([ai(0)], [entry()], previews_left=0, previews_quota=15)
    assert only_ai == (
        "Crear tu video usa 1 vista previa, y ya usaste tus 15 de este mes. Vuelven el próximo mes."
    )


def test_create_reason_short_and_fits() -> None:
    clip = [ai(0), ai(1), ai(2)]
    body, foot = vm.create_reason(
        clip, [entry()] * 3, previews_left=1, previews_quota=20, renews="1 de diciembre"
    )
    assert body == (
        "Crear tu video usa 3 vistas previas y este mes te queda 1. Quita 2 partes con IA, "
        "prueba una sola o espera al 1 de diciembre, cuando vuelven tus 20 vistas previas."
    )
    assert foot == parts.FOOT_SHORT
    assert vm.create_reason(clip, [entry()] * 3, previews_left=3, previews_quota=20) == ("", "")
    assert vm.create_reason(clip, [entry()] * 3, previews_left=0, previews_quota=0) == ("", "")
    assert vm.create_reason([photo()], [], previews_left=0, previews_quota=20) == ("", "")


# -- building the block ------------------------------------------------------------------


def test_ai_part_key_and_back() -> None:
    assert vm.ai_part_key(0) == "ai_part:0"
    assert vm.ai_part_key(5) == "ai_part:5"
    for bad in (-1, True, 1.0, "1"):
        with pytest.raises(ValueError):
            vm.ai_part_key(bad)  # type: ignore[arg-type]
    assert [vm.ai_part_at(vm.ai_part_key(n)) for n in range(3)] == [0, 1, 2]
    for key in ("ai_part:01", "ai_part:", "ai_part:-1", "t/x/v.mp4", ""):
        assert vm.ai_part_at(key) is None


def test_new_ai_block_is_the_contract_shape() -> None:
    segment, plan = vm.new_ai_block(2, seconds=12, image_keys=["t/x/a.jpg"], description=" Hola ")
    assert segment == {
        "kind": "ai_part",
        "key": "ai_part:2",
        "start_s": 0,
        "end_s": 10,
        "speed": 1,
        "rotate": 0,
        "transition_in": None,
    }
    parsed = VideoPartPlan.model_validate(plan)
    assert parsed.mode == "reference"
    assert parsed.seconds == 10
    assert parsed.description == "Hola"
    assert parsed.clip_image_keys == ("t/x/a.jpg",)
    assert (parsed.mode_rule_version, parsed.mode_reason) == (1, "no_source")
    assert not (parsed.effects or parsed.text_layers or parsed.segments or parsed.transition_in)
    assert vm.new_ai_block(0)[1]["clip_image_keys"] is None
    assert vm.new_ai_block(0, seconds=0)[0]["end_s"] == 1


def test_insert_ai_block_at_the_playhead() -> None:
    segments, entries, place = vm.insert_ai_block([photo(), video()], [], 1)
    assert place == 1
    assert [s["kind"] for s in segments] == ["photo", "ai_part", "video"]
    assert segments[1]["key"] == "ai_part:0"
    assert segments[1]["end_s"] == 5
    assert len(entries) == 1
    assert vm.preflight_problems(segments, entries) == []
    # a second one appends its entry: no other key changes
    segments, entries, place = vm.insert_ai_block(segments, entries, 0, image_keys=["k"])
    assert place == 0
    assert [s.get("key") for s in segments][:2] == ["ai_part:1", "t/x/p.jpg"]
    assert entries[1]["clip_image_keys"] == ["k"]
    assert vm.preflight_problems(segments, entries) == []
    # past the end: at the end
    assert vm.insert_ai_block([photo()], [], 99)[2] == 1


def test_insert_ai_block_fits_or_refuses() -> None:
    segments, entries, place = vm.insert_ai_block([video(30), video(27)], [], 2)
    assert (place, segments[2]["end_s"], entries[0]["seconds"]) == (2, 3, 3)
    full = [photo(1)] * 8
    out, out_entries, place = vm.insert_ai_block(full, [], 0)
    assert (place, out, out_entries) == (-1, full, [])
    six = [ai(n, 2) for n in range(6)]
    assert vm.insert_ai_block(six, [entry(2)] * 6, 0)[2] == -1


def test_remove_ai_block_renumbers() -> None:
    fade = {"effect_id": "fundido", "params": {"duration_s": 0.5}}
    segments = [ai(0), {**photo(), "transition_in": fade}, ai(1, 4), ai(2, 3)]
    entries = [entry(), entry(4), entry(3)]
    out, out_entries = vm.remove_ai_block(segments, entries, 0)
    assert [s.get("key") for s in out] == ["t/x/p.jpg", "ai_part:0", "ai_part:1"]
    assert out[0]["transition_in"] is None
    assert [e["seconds"] for e in out_entries] == [4, 3]
    assert vm.preflight_problems(out, out_entries) == []
    # the inputs are not touched
    assert segments[0]["key"] == "ai_part:0"
    assert segments[1]["transition_in"] == fade
    # not an AI block, or out of range: unchanged copies
    assert vm.remove_ai_block(segments, entries, 1) == (segments, entries)
    assert vm.remove_ai_block(segments, entries, 9) == (segments, entries)


# -- «Video o audio tuyo» ----------------------------------------------------------------


def test_guide_option_only_in_nueva() -> None:
    assert vm.guide_option("reference") == {
        "shown": "1",
        "section": "Más opciones",
        "label": "Video o audio tuyo",
        "reason": "",
    }
    for mode in ("edit", "extend"):
        option = vm.guide_option(mode)
        assert option["shown"] == ""
        assert option["reason"] == "Para usar tu video o audio, elige hacer esta parte nueva."
    # today's words of the part editor, not new ones
    assert vm.GUIDE_NEEDS_NEW == part_editor_vm.save_reason(
        "extend", "algo", [], has_own_media=True
    )


def test_with_mode_drops_the_guide_outside_nueva() -> None:
    plan = entry(clip_video_keys=["uploads/a/v.mp4"], clip_audio_keys=["uploads/a/s.mp3"])
    assert vm.with_mode(plan, "reference")["clip_video_keys"] == ["uploads/a/v.mp4"]
    for mode in ("edit", "extend"):
        out = vm.with_mode(plan, mode)
        assert out["mode"] == mode
        assert (out["clip_video_keys"], out["clip_audio_keys"]) == ([], [])
    assert plan["mode"] == "reference"  # not touched


def test_guide_problems_types() -> None:
    plan = entry(
        clip_video_keys=["uploads/a/v.MP4", "uploads/a/v.webm"],
        clip_audio_keys=["uploads/a/s.wav", "uploads/a/s.ogg"],
        clip_image_keys=["uploads/a/p.png"],
    )
    problems = vm.guide_problems(plan, 2)
    assert [(p["code"], p["field"]) for p in problems] == [
        ("ai_part_guide_type", "ai_parts[2].clip_video_keys[1]"),
        ("ai_part_guide_type", "ai_parts[2].clip_audio_keys[1]"),
    ]
    assert problems[0]["text"] == CONTRACT_TABLE["ai_part_guide_type"]
    assert vm.guide_problems(entry(), 0) == []


def test_guide_problems_business_files() -> None:
    plan = entry(
        clip_video_keys=[f"uploads/{TENANT}/v.mp4", f"uploads/{OTHER}/v.mp4"],
        clip_audio_keys=["v.mp3"],
        clip_image_keys=[f"t/{TENANT}/p.jpg", f"t/{OTHER}/p.jpg"],
    )
    problems = vm.guide_problems(plan, 0, TENANT)
    assert [(p["code"], p["field"]) for p in problems] == [
        ("foreign_key", "ai_parts[0].clip_video_keys[1]"),
        ("malformed_key", "ai_parts[0].clip_audio_keys[0]"),
        ("foreign_key", "ai_parts[0].clip_image_keys[1]"),
    ]
    assert problems[0]["text"] == vm.refusal_text("foreign_key")
    assert problems[1]["text"] == vm.refusal_text("malformed_key")
    # a tenant id that is not one owns nothing
    assert (
        vm.guide_problems(entry(clip_image_keys=[f"t/{TENANT}/p.jpg"]), 0, "nope")[0]["code"]
        == "foreign_key"
    )


def test_preflight_checks_the_guide() -> None:
    guided = entry(clip_video_keys=[f"uploads/{OTHER}/v.mov"])
    assert vm.preflight_problems([photo(), ai(0)], [guided]) == []
    problems = vm.preflight_problems([photo(), ai(0)], [guided], tenant_id=TENANT)
    assert [(p["code"], p["field"]) for p in problems] == [
        ("foreign_key", "ai_parts[0].clip_video_keys[0]")
    ]


# -- on the Clip's timeline (the state's shapes) ---------------------------------------------


def _media(*keys: str) -> list[dict[str, Any]]:
    return [{"id": k, "key": k, "kind": "photo", "dur": 2.0} for k in keys]


def test_merge_order_keeps_each_part_before_its_anchor() -> None:
    a, b = vm.token("p1"), vm.token("p2")
    assert vm.merge_order(["x", "y"], ["x", a, "y"], []) == ["x", "y"]  # nothing AI
    assert vm.merge_order(["x", "y"], ["x", a, "y", b], [a, b]) == ["x", a, "y", b]
    # «x» moved after «y» in the strip: the part stays before its anchor «y»
    assert vm.merge_order(["y", "x"], ["x", a, "y"], [a]) == [a, "y", "x"]
    # its anchor gone: last; a part the order does not know yet: at the very end
    assert vm.merge_order(["x"], ["x", a, "y"], [a, b]) == ["x", a, b]
    # a token of a part that no longer exists is dropped
    assert vm.merge_order(["x"], [a, "x"], []) == ["x"]


def test_timeline_items_lays_each_part_as_a_block() -> None:
    a, b = vm.token("p1"), vm.token("p2")
    parts = [{"uid": "p2", "plan": entry(3)}, {"uid": "p1", "plan": entry(4)}]
    items = vm.timeline_items(_media("x", "y"), ["x", a, "y", b], parts)
    assert [i["id"] for i in items] == ["x", a, "y", b]
    first, second = items[1], items[3]
    # `entry` is the place in `media.ai_parts` (the state's order), `ai_n` the track's
    assert (first["entry"], first["ai_n"], first["src_end"]) == (1, 1, 4.0)
    assert (second["entry"], second["ai_n"], second["src_end"]) == (0, 2, 3.0)
    assert first["kind"] == "ai" and first["speed"] == 1.0
    assert vm.timeline_items(_media("x"), ["x"], []) == _media("x")


def test_place_token_never_splits_the_own_videos_pieces() -> None:
    a = vm.token("p1")
    media = [
        {"id": "v", "key": "v"},
        {"id": "v#parte-2", "key": "v"},
        {"id": "f", "key": "f"},
    ]
    assert vm.place_token(["v", "f"], media, 1, a) == ["v", a, "f"]
    assert vm.place_token(["v", "f"], media, 0, a) == [a, "v", "f"]
    assert vm.place_token(["v", "f"], media, 9, a) == ["v", "f", a]


def test_add_options_and_owner_mode() -> None:
    base = (("media", "image-plus", "Foto o video"), ("text", "type", "Texto"))
    assert vm.add_options(base, on=False) == base
    assert [k for k, _i, _t in vm.add_options(base, on=True)] == ["media", "text", "ai_part"]
    plan = {"mode": "reference", "mode_rule_version": 1, "mode_reason": "reel_no_people"}
    changed = vm.with_owner_mode(plan, "reference")
    assert changed["mode_changed_by_owner"] is True  # the rule proposed «edit»
    assert vm.with_owner_mode(plan, "edit")["mode_changed_by_owner"] is False
    assert vm.with_photos(entry(), ["k", "k", ""]) == {
        **entry(),
        "clip_image_keys": ["k"],
        "clip_image_roles": ["product"],
    }
    assert vm.with_seconds(entry(), 14)["seconds"] == 10


def test_problems_of_one_part_and_merge_shown() -> None:
    problems = [
        {"code": "a", "field": "ai_parts[0].mode", "text": "uno"},
        {"code": "b", "field": "segments[1].speed", "text": "dos"},
        {"code": "c", "field": "segments", "text": "tres"},
        {"code": "d", "field": "ai_parts[1]", "text": "cuatro"},
    ]
    assert vm.problems_of(problems, 0, 1) == ["uno", "dos"]
    assert vm.merge_shown(entry(3, analysis_id=REEL))
    assert not vm.merge_shown(entry(3)) and not vm.merge_shown(entry(4, analysis_id=REEL))


def test_the_new_words_are_spanish_and_say_what_to_do() -> None:
    for text in (
        vm.CREATE_OFF_LINE,
        vm.TRY_OFF_LINE,
        vm.ADDED_LINE,
        vm.GUIDE_FULL,
        vm.MERGE_NEXT_PHOTO,
        vm.MERGE_NEXT_VIDEO,
        vm.MERGE_NEXT_NONE,
        vm.CREATE_OFF_SHORT,
        vm.DESCRIPTION_EXAMPLE,
        vm.GUIDE_HELP,
        vm.PHOTOS_NONE,
        vm.SECONDS_HELP,
    ):
        assert "bloque" not in text.lower(), text
        assert text.endswith("."), text
    assert vm.removed_line(2) == "Quitaste la parte con IA 2."
    assert vm.mode_line(1, "edit") == (
        "Cambiaste cómo se hace la parte con IA 1: «Igual al original»."
    )
    assert vm.merged_line(2, 6) == "Juntaste las partes con IA 2 y 3: ahora son una de 6 s."
    assert vm.merge_needs_ai_next("photo") == vm.MERGE_NEXT_PHOTO
    assert vm.merge_needs_ai_next("video") == vm.MERGE_NEXT_VIDEO
    assert vm.merge_needs_ai_next(None) == vm.MERGE_NEXT_NONE
    assert vm.merge_needs_ai_next("ai") == ""
    assert vm.guide_line("audio", 1, added=True) == "Agregaste tu audio a la parte con IA 1."
    assert vm.guide_line("video", 2, added=False) == "Quitaste tu video de la parte con IA 2."
    assert (vm.guide_kind("a/b.MOV"), vm.guide_kind("a/b.wav"), vm.guide_kind("a/b.txt")) == (
        "video",
        "audio",
        "",
    )
    assert vm.mode_fact(has_product=False) == "Creamos una parte nueva con tu marca."

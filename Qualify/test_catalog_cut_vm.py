"""«Corta tu video en partes» (CM-4, m-24955924): the timeline and its texts. Pure.

Pins (`docs/epica-galeria-medios-negocio.md` §5 CM-4):
1. The copy is the epic's, verbatim; the 3 s and «at least one» rules are the service's.
2. «Cortar aquí» splits the kept part under the line; never a removed one.
3. «Quitar esta parte» removes by part number; removed neighbours merge.
4. Rows read «Parte 1 · 0:00 a 0:12»; the line's time shows tenths.
5. «Guardar partes» is blocked with the right sentence; the save question is singular
   or plural; what is sent is exactly what `start_cut` validates.
"""

from __future__ import annotations

from qualify_api.catalog.business_media import CutSpan, validate_cut_spans

from .catalog_cut_vm import (
    CUT_HELP,
    CUT_HERE,
    CUT_TITLE,
    CUTTING_NOTE,
    LEAVE_TITLE,
    NEXT_FRAME,
    NO_PART_KEPT_TEXT,
    NOTHING_CUT_TEXT,
    ON_EDGE_TEXT,
    PART_TOO_SHORT_TEXT,
    PAUSE,
    PLAY,
    PREV_FRAME,
    REMOVE_PART,
    SAVE,
    SAVE_PARTS,
    STAY,
    UNDO,
    Span,
    cut_at,
    cut_done_text,
    cut_spans,
    is_dirty,
    part_rows,
    playhead_label,
    remove_part,
    removed_notice,
    save_blocker,
    save_text,
    start,
    time_label,
    timeline_blocks,
)

_D = 31_000  # a 31 s video


def test_the_copy_is_the_epics() -> None:
    assert CUT_TITLE == "Corta tu video en partes"
    assert CUT_HELP == "Mueve la línea hasta donde quieres cortar y toca «Cortar aquí»."
    assert (CUT_HERE, PREV_FRAME, NEXT_FRAME) == ("Cortar aquí", "Atrás", "Adelante")
    assert REMOVE_PART == "Quitar esta parte"
    assert (STAY, SAVE_PARTS, SAVE) == ("Volver", "Guardar partes", "Guardar")
    # founder 2026-11-07: undo before saving, and watching to find the cut point
    assert (UNDO, PLAY, PAUSE) == ("Deshacer", "Reproducir", "Pausar")
    assert removed_notice(12_000, 22_000) == (
        "Quitaste la parte de 0:12 a 0:22. Si fue un error, toca «Deshacer»."
    )
    assert save_text(2) == (
        "Vamos a guardar 2 partes. El video original y lo que quitaste se borran para siempre."
    )
    assert save_text(1).startswith("Vamos a guardar 1 parte. ")
    assert CUTTING_NOTE == ("Cortando tu video… Puedes salir; tus partes aparecerán en tu Galería.")
    assert cut_done_text(3) == "Listo: tu video quedó en 3 partes."
    assert LEAVE_TITLE == "¿Salir sin guardar? Tu video queda como estaba."
    assert PART_TOO_SHORT_TEXT == "Cada parte debe durar al menos 3 segundos."
    assert NO_PART_KEPT_TEXT == "Deja al menos una parte o cancela."


def test_cortar_aqui_splits_the_part_under_the_line() -> None:
    spans, reason = cut_at(start(_D), 12_000)
    assert reason == "" and spans == [Span(0, 12_000), Span(12_000, _D)]
    rows = part_rows(spans)
    assert [r.label for r in rows] == ["Parte 1 · 0:00 a 0:12", "Parte 2 · 0:12 a 0:31"]
    assert rows[0].spoken == "Parte 1, de 0 segundos a 12 segundos"
    # on an existing cut, or at 0:00 when it opens: nothing changes, and it says why
    assert cut_at(spans, 12_000) == (spans, ON_EDGE_TEXT)
    assert cut_at(start(_D), 0) == (start(_D), ON_EDGE_TEXT)
    assert ON_EDGE_TEXT == "Aquí ya empieza una parte. Mueve la línea un poco más allá."
    assert cut_at(start(_D), _D)[1] == "Ese es el final del video. Mueve la línea un poco antes."


def test_a_removed_part_cannot_be_cut_and_its_neighbours_merge() -> None:
    spans, _ = cut_at(start(_D), 10_000)
    spans, _ = cut_at(spans, 20_000)
    spans = remove_part(spans, 2)  # the middle one
    assert [s.keep for s in spans] == [True, False, True]
    unchanged, reason = cut_at(spans, 15_000)
    assert unchanged == spans and "ya la quitaste" in reason
    spans = remove_part(spans, 2)  # now the last kept one: removed spans merge
    assert spans == [Span(0, 10_000, True), Span(10_000, _D, False)]
    assert [r.label for r in part_rows(spans)] == ["Parte 1 · 0:00 a 0:10"]


def test_saving_is_blocked_with_the_services_sentences() -> None:
    assert save_blocker(start(_D), _D) == NOTHING_CUT_TEXT
    short, _ = cut_at(start(_D), 2_000)
    assert save_blocker(short, _D) == PART_TOO_SHORT_TEXT
    assert part_rows(short)[0].too_short
    none_kept = remove_part(start(_D), 1)
    assert save_blocker(none_kept, _D) == NO_PART_KEPT_TEXT
    good, _ = cut_at(start(_D), 12_000)
    assert save_blocker(good, _D) == ""


def test_what_is_sent_is_what_the_service_accepts() -> None:
    spans, _ = cut_at(start(_D), 10_000)
    spans, _ = cut_at(spans, 20_000)
    spans = remove_part(spans, 2)
    sent = cut_spans(spans)
    assert all(isinstance(s, CutSpan) for s in sent)
    assert validate_cut_spans(sent, _D) == ((0, 10_000), (20_000, _D))


def test_cancel_asks_only_when_something_changed() -> None:
    assert not is_dirty(start(_D), _D)
    assert is_dirty(cut_at(start(_D), 5_000)[0], _D)


def test_times_read_as_minutes_seconds_and_tenths_beside_the_line() -> None:
    assert time_label(72_900) == "1:12"
    assert playhead_label(12_433) == "0:12,4"


def test_the_timeline_draws_each_span_in_place() -> None:
    spans, _ = cut_at(start(10_000), 2_500)
    first, second = timeline_blocks(spans, selected=2)
    assert (first.left, first.width, first.part, first.selected) == ("0.000%", "25.000%", 1, False)
    assert (second.left, second.width, second.part, second.selected) == (
        "25.000%",
        "75.000%",
        2,
        True,
    )


def test_a_trim_is_a_cut_one_part_kept_and_the_rest_left_out() -> None:
    """m-24976897: a 3.9 s clip — cut at 3 s, the 0.9 s left over is too short to keep
    (said with the service's sentence) but fine to leave out; what is sent then is a
    single kept span the service accepts."""
    from .catalog_cut_vm import MIN_PART_HINT, remove_part, save_blocker, start

    assert MIN_PART_HINT.startswith(PART_TOO_SHORT_TEXT)
    spans, reason = cut_at(start(3_900), 3_000)
    assert reason == "" and save_blocker(spans, 3_900) == PART_TOO_SHORT_TEXT
    trimmed = remove_part(spans, 2)
    assert save_blocker(trimmed, 3_900) == ""
    sent = cut_spans(trimmed)
    assert [(s.start_ms, s.end_ms, s.keep) for s in sent] == [
        (0, 3_000, True),
        (3_000, 3_900, False),
    ]
    assert validate_cut_spans(sent, 3_900) == ((0, 3_000),)
    # a kept part under the minimum is still refused, with the same sentence
    short, _ = cut_at(start(3_900), 2_500)
    assert save_blocker(remove_part(short, 2), 3_900) == PART_TOO_SHORT_TEXT

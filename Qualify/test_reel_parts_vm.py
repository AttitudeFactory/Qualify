"""UI-3 (m-24921077): «Tu video, parte por parte» — the pure part of step 2's parts list:
entries from a reel's plan, removing/adding/describing a part, the rows and «Lo que usa de
tu mes». No database, no Reflex."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from qualify_api.creative.parts import plan_from_analysis
from qualify_api.referentes.reel_analysis_types import (
    NOT_OBSERVED,
    OBSERVED,
    UNKNOWN,
    AnalysisProvenance,
    ReelAnalysis,
    ShotAnalysis,
)
from qualify_creative.schemas import VideoPartPlan

from . import reel_parts_vm as vm

ANALYSIS_ID = UUID("5e1f0000-0000-4000-8000-0000000000b3")


def shot(
    index: int,
    start: float,
    end: float,
    *,
    people: str = NOT_OBSERVED,
    faces: str = NOT_OBSERVED,
    subject: str | None = "manos arman el producto sobre una mesa negra",
    spoken: str = "",
) -> ShotAnalysis:
    family = (
        {"status": UNKNOWN, "value": "", "evidence_frames": []}
        if subject is None
        else {"status": OBSERVED, "value": subject, "evidence_frames": ["00-0"]}
    )
    return ShotAnalysis(
        shot_index=index,
        start_s=start,
        end_s=end,
        people_presence=people,
        visible_faces=faces,
        families={"subject": family},
        spoken_text=spoken,
    )


def analysis(
    *shots: ShotAnalysis, width: int = 720, height: int = 1280, editable: bool = True
) -> ReelAnalysis:
    return ReelAnalysis(
        id=ANALYSIS_ID,
        network="instagram",
        post_id="p1",
        analysis_version=8,
        post_url="https://www.instagram.com/reel/p1/",
        source_seconds=shots[-1].end_s,
        width=width,
        height=height,
        fps=30.0,
        covered_from_s=0.0,
        covered_to_s=shots[-1].end_s,
        edit_eligible=editable,
        source_available=True,
        transcript_text="",
        transcript_segments=(),
        transcript_source="none",
        reel_sheet={},
        shots=tuple(shots),
        provenance=AnalysisProvenance(
            model_id="dev",
            model_revision=None,
            prompt_version="dev",
            schema_version="dev",
            detector_version="dev",
            sampling_version="dev",
            sampling_params={},
            source_sha256="0" * 64,
        ),
        finished_at=datetime(2026, 11, 9, tzinfo=UTC),
    )


def entries_of(reel: ReelAnalysis) -> list[dict[str, Any]]:
    return vm.entries_from_plan(reel, plan_from_analysis(reel, products=("smash doble",)))


#: The mockup's reel (§3b): product, a person, a long cut split in two.
MOCKUP = analysis(
    shot(0, 0, 5),
    shot(1, 5, 9, people=OBSERVED, faces=OBSERVED, subject="un chico muerde el producto"),
    shot(2, 9, 21),
)


# -- entries from the plan --------------------------------------------------------------


def test_each_part_says_its_form_and_why_it_is_not_igual_al_original() -> None:
    rows = vm.part_rows(entries_of(MOCKUP))
    assert [r["label"] for r in rows] == [
        "Parte 1 · 5 s",
        "Parte 2 · 4 s",
        "Parte 3 · 6 s",
        "↳ Parte 4 · 6 s",
    ]
    # round 12: no pills on the card — the form is in the item's spoken label
    forms = [
        "igual al original, con tu producto",
        "nueva, inspirada en el original",
        "igual al original, con tu producto",
        "sigue a la anterior",
    ]
    assert all(form in row["aria"] for form, row in zip(forms, rows, strict=True))
    assert not any(field in row for row in rows for field in ("form", "tone", "person"))
    assert rows[0]["why"] == "" and rows[2]["why"] == ""
    assert rows[1]["why"] == (
        "Aquí aparece una persona: la hacemos nueva con tu producto. La persona será otra."
    )
    assert rows[3]["why"] == "Va pegada a la parte 3: se mueve con ella."
    # the description never assumes who someone is, and names the owner's product
    assert rows[1]["description"] == "Una persona muerde smash doble."


def test_aparece_una_persona_only_when_someone_was_seen_never_sin_personas() -> None:
    reel = analysis(
        shot(0, 0, 5, people=OBSERVED),
        shot(1, 5, 10),
        shot(2, 10, 15, people=UNKNOWN, faces=UNKNOWN),
    )
    rows = vm.part_rows(entries_of(reel))
    assert ["aparece una persona" in r["aria"] for r in rows] == [True, False, False]
    assert rows[2]["why"].startswith("No pudimos ver bien si en esta parte aparece alguien")
    assert not any("sin personas" in str(v).lower() for r in rows for v in r.values())


def test_a_reel_that_is_not_vertical_makes_every_part_new_and_says_why() -> None:
    rows = vm.part_rows(entries_of(analysis(shot(0, 0, 5), width=1920, height=1080)))
    assert "nueva, inspirada en el original" in rows[0]["aria"]
    assert rows[0]["why"] == (
        "El reel no es vertical, así que hacemos esta parte nueva con tu producto."
    )


def test_a_reel_whose_video_cannot_be_edited_says_so() -> None:
    rows = vm.part_rows(entries_of(analysis(shot(0, 0, 5), editable=False)))
    assert rows[0]["why"].startswith("No podemos usar el video original en esta parte")


def test_a_part_with_nothing_seen_says_only_the_fact() -> None:
    """No «Cuéntanos…»: until UI-4's sheet nothing on this screen can write it."""
    rows = vm.part_rows(entries_of(analysis(shot(0, 0, 5, subject=None))))
    assert rows[0]["description"] == ""
    assert rows[0]["describe"] == "No pudimos ver qué pasa en esta parte del reel."


def test_a_row_is_announced_whole() -> None:
    row = vm.part_rows(entries_of(MOCKUP))[1]
    assert row["aria"] == (
        "Parte 2 de 4, 4 segundos, nueva, inspirada en el original, aparece una persona"
    )
    assert "edit_label" not in row  # «Cambiar» waits for UI-4
    assert row["remove_label"] == "Quitar la parte 2"


# -- remove, undo-friendly, add, describe -----------------------------------------------


def test_removing_a_part_renumbers_and_says_which_it_was() -> None:
    entries = entries_of(MOCKUP)
    rest, at = vm.remove_part(entries, entries[1]["key"])
    assert at == 2 and len(rest) == 3
    assert vm.removed_text(at) == "Quitaste la parte 2."
    assert [r["label"] for r in vm.part_rows(rest)][:2] == ["Parte 1 · 5 s", "Parte 2 · 6 s"]
    # the entries it was given are untouched (the state keeps them for «Deshacer»)
    assert len(entries) == 4


def test_an_unknown_part_is_not_removed() -> None:
    entries = entries_of(MOCKUP)
    assert vm.remove_part(entries, "nope") == (entries, 0)


def test_an_extend_that_lost_its_part_is_made_new_and_says_why() -> None:
    entries = entries_of(MOCKUP)
    rest, _ = vm.remove_part(entries, entries[2]["key"])
    row = vm.part_rows(rest)[2]
    assert "nueva, inspirada en el original" in row["aria"]
    assert row["label"] == "Parte 3 · 6 s"  # no longer stuck: no «↳»
    assert row["why"] == "Ya no está la parte anterior: la hacemos nueva, inspirada en el original."
    # the plan stays one a brief accepts
    brief_parts = vm.plans(rest)
    assert all(p.mode != "extend" for p in brief_parts)


def test_removing_the_first_part_never_leaves_an_extend_first() -> None:
    reel = analysis(shot(0, 0, 18))  # one long cut → a part and its extend
    entries = entries_of(reel)
    assert [e["plan"]["mode"] for e in entries] == ["edit", "extend"]
    rest, _ = vm.remove_part(entries, entries[0]["key"])
    assert rest[0]["plan"]["mode"] == "reference"


def test_the_entries_are_the_plan_a_video_by_parts_brief_accepts() -> None:
    entries = entries_of(MOCKUP)
    rest, _ = vm.remove_part(entries, entries[0]["key"])
    parts = vm.plans(rest)
    assert len(parts) == 3 and all(isinstance(p, VideoPartPlan) for p in parts)
    assert all(p.analysis_id == ANALYSIS_ID for p in parts)
    assert parts[0].mode != "extend"


# -- head and «Lo que usa de tu mes» ----------------------------------------------------


def test_the_head_counts_parts_and_seconds() -> None:
    entries = entries_of(MOCKUP)
    assert vm.summary_text(len(entries), vm.total_seconds(entries)) == "4 partes · 21 s"
    assert vm.summary_text(1, 5) == "1 parte · 5 s"
    assert vm.based_on_text("@smash_hiro") == "Basado en un reel de @smash_hiro"
    assert vm.based_on_text("") == "Basado en un reel"


@pytest.mark.parametrize(
    ("parts", "left", "quota", "line"),
    [
        (4, 12, 20, "Crear las 4 partes usa 4 vistas previas. Te quedan 12."),
        (1, 1, 20, "Crear la parte usa 1 vista previa. Te queda 1."),
        (4, 2, 20, "Crear las 4 partes usa 4 vistas previas, y este mes te quedan 2."),
        (4, 0, 20, "Crear las 4 partes usa 4 vistas previas, y ya usaste tus 20 de este mes."),
        (4, 12, 0, ""),
        (0, 12, 20, ""),
    ],
)
def test_previews_line(parts: int, left: int, quota: int, line: str) -> None:
    assert vm.previews_line(parts, left, quota) == line


@pytest.mark.parametrize(
    ("used", "joined", "left", "quota", "line"),
    [
        (
            20,
            20,
            40,
            40,
            "Al aprobar el video usas 20 de tus 40 segundos de video del mes. "
            "Te quedarían 20 segundos.",
        ),
        (
            20,
            20,
            21,
            40,
            "Al aprobar el video usas 20 de tus 40 segundos de video del mes. "
            "Te quedaría 1 segundo.",
        ),
        (
            8,
            6,
            40,
            40,
            "Al aprobar el video usas 8 de tus 40 segundos de video del mes. "
            "Te quedarían 32 segundos. Las partes de menos de 4 s cuentan como 4.",
        ),
        (
            20,
            20,
            12,
            40,
            "Al aprobar el video usas 20 de tus 40 segundos de video del mes, y este mes te "
            "quedan 12 segundos. Quita partes o espera al 1 de diciembre, cuando vuelven tus "
            "40 segundos.",
        ),
        (
            20,
            20,
            0,
            40,
            "Al aprobar el video usas 20 segundos de video del mes, y ya usaste tus 40 "
            "segundos de este mes. Espera al 1 de diciembre, cuando vuelven tus 40 segundos.",
        ),
        (20, 20, 40, 0, ""),
    ],
)
def test_seconds_line(used: int, joined: int, left: int, quota: int, line: str) -> None:
    assert vm.seconds_line(used, joined, left, quota, renews="1 de diciembre") == line


def test_seconds_line_without_a_known_day_waits_for_next_month() -> None:
    line = vm.seconds_line(20, 20, 12, 40)
    assert line.endswith("Quita partes o espera al próximo mes, cuando vuelven tus 40 segundos.")


def test_usage_never_shows_money_and_counts_what_is_generated() -> None:
    entries = entries_of(analysis(shot(0, 0, 2), shot(1, 2, 3, people=OBSERVED)))
    # a 2 s part and a 1 s part are generated at 4 s each
    assert vm.generated_seconds(entries) == 8
    lines = vm.usage_lines(
        entries, previews_left=10, previews_quota=20, seconds_left=40, seconds_quota=40
    )
    assert len(lines) == 2
    assert not any(c in line for line in lines for c in ("$", "USD", "dólar", "precio"))


# -- thumbnails (the provider signs one frame per part) -------------------------------


def test_a_row_carries_its_thumbnail_path_or_nothing() -> None:
    entries = entries_of(MOCKUP)
    assert all(row["thumb"] == "" for row in vm.part_rows(entries))
    entries[0]["thumb"] = "/avatar/frame/instagram/p1/x/00-0?s=abc"
    assert vm.part_rows(entries)[0]["thumb"] == "/avatar/frame/instagram/p1/x/00-0?s=abc"


def test_the_provider_signs_a_frame_per_part_from_its_cuts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import reel_wait_provider as provider

    asked: list[tuple[int, ...]] = []

    def thumb(reel: ReelAnalysis, shot_indexes: Any) -> str:
        assert reel is MOCKUP
        asked.append(tuple(shot_indexes))
        return "" if 1 in shot_indexes else f"/avatar/frame/{shot_indexes[0]}"

    monkeypatch.setattr(provider.reel_analysis, "get_analysis", lambda _t, _a: MOCKUP)
    monkeypatch.setattr(provider, "part_thumbnail_path", thumb)
    entries = provider.reel_plan(UUID(int=1), ANALYSIS_ID, ("smash doble",))
    assert entries is not None
    assert asked == [(0,), (1,), (2,), (2,)]
    assert [row["thumb"] for row in vm.part_rows(entries)] == [
        "/avatar/frame/0",
        "",
        "/avatar/frame/2",
        "/avatar/frame/2",
    ]
    # removing a part keeps the others' pictures
    rest, _ = vm.remove_part(entries, entries[0]["key"])
    assert vm.part_rows(rest)[1]["thumb"] == "/avatar/frame/2"


# -- moving parts in «Orden del clip» (round 6) ----------------------------------------


def keys(entries: list[dict[str, Any]]) -> list[str]:
    return [e["key"] for e in entries]


def test_rows_say_which_part_moves_and_which_is_stuck() -> None:
    rows = vm.part_rows(entries_of(MOCKUP))  # edit · person · edit + its extend
    assert [r["movable"] for r in rows] == ["1", "1", "1", ""]
    assert [r["unit"] for r in rows] == ["0", "1", "2", "2"]
    # round 15: no arrows — no end flags nor button labels in the rows
    assert not any(f in rows[0] for f in ("first", "last", "up_label", "down_label"))
    assert rows[3]["aria"].startswith("Parte 4 de 4, 6 segundos, sigue a la anterior")


def test_before_and_after_move_one_place_and_say_where() -> None:
    entries = entries_of(MOCKUP)
    moved, before, after = vm.move_part(entries, entries[1]["key"], -1)
    assert (before, after) == (2, 1)
    assert keys(moved) == [entries[1]["key"], entries[0]["key"], *keys(entries)[2:]]
    assert vm.moved_text(before, after) == "Moviste la parte 2: ahora es la parte 1."
    # the parts themselves are untouched: never a re-plan
    assert [e["plan"] for e in moved] == [entries[i]["plan"] for i in (1, 0, 2, 3)]


def test_a_part_moves_with_the_one_stuck_to_it() -> None:
    entries = entries_of(MOCKUP)
    head, tail = entries[2]["key"], entries[3]["key"]
    moved, before, after = vm.move_part(entries, head, -1)
    assert (before, after) == (3, 2)
    assert keys(moved) == [entries[0]["key"], head, tail, entries[1]["key"]]
    assert moved[2]["plan"]["mode"] == "extend"  # still stuck, still valid
    assert vm.part_rows(moved)[2]["label"].startswith("↳ Parte 3")


def test_a_stuck_part_never_moves_on_its_own_and_the_ends_stay_put() -> None:
    entries = entries_of(MOCKUP)
    assert vm.move_part(entries, entries[3]["key"], -1) == (entries, 0, 0)
    assert vm.move_part(entries, entries[0]["key"], -1) == (entries, 0, 0)
    assert vm.move_part(entries, entries[2]["key"], 1) == (entries, 0, 0)
    assert vm.move_part(entries, "nope", 1) == (entries, 0, 0)


def test_a_drag_moves_a_unit_to_another_place() -> None:
    entries = entries_of(MOCKUP)
    moved, before, after = vm.move_unit(entries, 2, 0)  # the pair to the top
    assert (before, after) == (3, 1)
    assert keys(moved) == [*keys(entries)[2:], *keys(entries)[:2]]
    assert moved[0]["plan"]["mode"] != "extend"
    assert vm.move_unit(entries, 1, 1) == (entries, 0, 0)
    assert vm.move_unit(entries, 0, 9) == (entries, 0, 0)


def test_no_part_ever_ends_up_first_as_sigue_a_la_anterior() -> None:
    entries = entries_of(MOCKUP)
    rest, _ = vm.remove_part(entries, entries[2]["key"])  # the extend is orphaned
    for start in range(vm.unit_count(rest)):
        for target in range(vm.unit_count(rest)):
            moved, _, _ = vm.move_unit(rest, start, target)
            assert moved[0]["plan"]["mode"] != "extend"
            vm.plans(moved)  # always a valid plan


def test_a_stuck_part_says_it_moves_with_its_part() -> None:
    rows = vm.part_rows(entries_of(MOCKUP))
    assert rows[3]["why"] == "Va pegada a la parte 3: se mueve con ella."


def test_rows_group_into_units_for_the_drag_cards() -> None:
    units = vm.part_units(vm.part_rows(entries_of(MOCKUP)))
    assert [[r["index"] for r in unit] for unit in units] == [["1"], ["2"], ["3", "4"]]
    assert vm.part_units([]) == []


def test_the_hint_says_to_drag() -> None:
    assert vm.LIST_HELP == (
        "Tu video va en este orden. Arrastra las partes para cambiarlo; quita las que no quieras."
    )


def test_refused_names_are_cut_listed_and_keep_their_dot() -> None:
    from . import clip_gallery_vm as gallery

    def big(path: str) -> dict:
        return {"file": {"path": path}, "errors": [{"code": "file-too-large"}]}

    image = gallery.IMAGE
    assert gallery.rejected_text([big("./.foto.png")], image) == (
        "No agregamos .foto.png: pesa más de 200 MB."
    )
    long = "a" * 80 + ".mp4"
    text = gallery.rejected_text([big(long)], gallery.VIDEO)
    assert "…" in text and len(text.split(":")[0]) < 80
    many = [big(f"v{n}.mp4") for n in range(5)]
    assert gallery.rejected_text(many, gallery.VIDEO) == (
        "No agregamos v0.mp4, v1.mp4, v2.mp4 y 2 más: pesan más de 200 MB."
    )
    assert gallery.rejected_text(many[:2], gallery.VIDEO) == (
        "No agregamos v0.mp4 y v1.mp4: pesan más de 200 MB."
    )


def test_each_category_says_what_goes_there_and_when_it_is_full() -> None:
    from . import clip_gallery_vm as gallery

    wrong = [{"file": {"path": "x.txt"}, "errors": [{"code": "file-invalid-type"}]}]
    assert gallery.rejected_text(wrong, gallery.IMAGE) == (
        "No agregamos 1 archivo: aquí van fotos PNG, JPG o WEBP."
    )
    assert gallery.rejected_text(wrong * 2, gallery.VIDEO) == (
        "No agregamos 2 archivos: aquí van videos MP4 o MOV."
    )
    assert gallery.rejected_text(wrong, gallery.AUDIO) == (
        "No agregamos 1 archivo: aquí van audios MP3 o WAV."
    )
    assert gallery.full_text(gallery.IMAGE, held=9) == (
        "Ya tienes 9 fotos, el máximo. Quita una para cambiarla."
    )
    assert gallery.full_text(gallery.IMAGE, held=8) == ""
    assert gallery.full_text(gallery.VIDEO, held=3, reel_video=True) == (
        "Ya tienes 2 videos tuyos, el máximo con un reel. Quita uno para cambiarlo."
    )
    assert gallery.full_text(gallery.VIDEO, held=3) == (
        "Ya tienes 3 videos, el máximo. Quita uno para cambiarlo."
    )
    assert gallery.full_text(gallery.AUDIO, held=3) == (
        "Ya tienes 3 audios, el máximo. Quita uno para cambiarlo."
    )
    assert gallery.refused_text(gallery.IMAGE, 2, held=9) == (
        "No agregamos 2 fotos: ya tienes 9, el máximo. Quita una para cambiarla."
    )

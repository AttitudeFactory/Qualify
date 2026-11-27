"""m-25142725: the reference tracks' pure view model (`clip_refs_vm`) — rows, stacking,
the product's block, following an AI part, the contract's answer and the words. Offline
and pure: the contract's own functions are the judge, nothing is read or paid."""

from __future__ import annotations

import re
from typing import Any

import pytest
from qualify_api.creative.video_pipeline import ai_parts as contract_ai

from . import clip_refs_vm as vm

_T = "a0000000-0000-4000-8000-000000000001"


def _k(name: str) -> str:
    return f"uploads/{_T}/{name}"


#: own photo 0-2, «Nueva» 2-7, «Sigue a la anterior»-like other mode 7-12.
_MEDIA: list[dict[str, Any]] = [
    {"id": "f1", "key": _k("uno.jpg"), "kind": "photo", "dur": 2.0},
    {
        "id": "ai:p1",
        "key": "ai:p1",
        "kind": "ai",
        "src_start": 0.0,
        "src_end": 5.0,
        "src_len": 5.0,
        "entry": 0,
        "ai_n": 1,
    },
    {
        "id": "ai:p2",
        "key": "ai:p2",
        "kind": "ai",
        "src_start": 0.0,
        "src_end": 5.0,
        "src_len": 5.0,
        "entry": 1,
        "ai_n": 2,
    },
]
_SEGMENTS = [
    {"key": _k("uno.jpg"), "kind": "photo", "start_s": 0, "end_s": 2},
    {"key": "ai_part:0", "kind": "ai_part", "start_s": 0, "end_s": 5},
    {"key": "ai_part:1", "kind": "ai_part", "start_s": 0, "end_s": 5},
]
_ENTRIES = [
    {"mode": "reference", "seconds": 5, "description": "Una arepa"},
    {"mode": "reference", "seconds": 5, "description": "Una mano"},
]
_TOTAL = 12.0


@pytest.fixture(autouse=True)
def _on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(contract_ai.CLIP_AI_PARTS_SWITCH, "on")


def _plan(items: list[dict[str, Any]], entries: list[dict[str, Any]] = _ENTRIES) -> dict:
    return vm.plan(items, _SEGMENTS, entries, vm.ai_spans(_MEDIA), _TOTAL)


def test_the_ai_parts_spans_are_the_tracks() -> None:
    spans = vm.ai_spans(_MEDIA)
    assert [(s["n"], s["entry"], s["start"], s["end"]) for s in spans] == [
        (1, 0, 2.0, 7.0),
        (2, 1, 7.0, 12.0),
    ]
    assert vm.edges_of(spans) == [2.0, 7.0, 12.0]


def test_a_reference_applies_when_it_overlaps_more_than_005_s() -> None:
    touching = vm.new_item([], "photo", [_k("a.png")], 0.0, 2.05)  # 0,05 s: not enough
    over = vm.new_item([touching], "photo", [_k("b.png")], 0.0, 2.1)
    both = vm.new_item([touching, over], "photo", [_k("c.png")], 6.0, 8.0)
    plan = _plan([touching, over, both])
    assert touching["uid"] in plan["unused"]
    assert plan["used_by"][over["uid"]] == [1]
    assert plan["used_by"][both["uid"]] == [1, 2]
    assert vm.used_text([1, 2]) == "Se usa en las partes con IA 1 y 2."
    assert vm.used_text([1]) == "Se usa en la parte con IA 1."
    assert vm.used_text([1, 2, 3]) == "Se usa en las partes con IA 1, 2 y 3."
    assert vm.used_text([]) == contract_ai.reference_text("reference_unused")


def test_videos_and_audios_only_apply_to_nueva_photos_to_every_mode() -> None:
    video = vm.new_item([], "video", [_k("v.mp4")], 8.0, 10.0)
    photo = vm.new_item([video], "photo", [_k("p.png")], 8.0, 10.0)
    entries = [_ENTRIES[0], {**_ENTRIES[1], "mode": "extend"}]
    plan = vm._plan_here(
        [video, photo],
        entries,
        vm.ai_spans(_MEDIA),
        _TOTAL,
        {"parts": [], "used_by": {}, "ignored": {}, "unused": [], "caps": {}},
    )
    assert plan["ignored"] == {video["uid"]: [2]}
    assert plan["used_by"] == {photo["uid"]: [2]}


def test_the_cap_is_the_models_and_a_part_over_it_is_said_everywhere() -> None:
    cap = contract_ai.reference_caps()["photo"]
    items: list[dict[str, Any]] = []
    for n in range(cap + 1):
        items.append(vm.new_item(items, "photo", [_k(f"p{n}.png")], 2.0, 7.0))
    plan = _plan(items)
    (part,) = [p for p in plan["parts"] if p["entry"] == 0]
    assert part["over"] == {"photo": cap} and part["counts"]["photo"] == cap + 1
    card = vm.cap_card("photo", 1, cap + 1, cap)
    assert vm.over_lines(plan) == [card]
    assert vm.part_problem(plan, 0) == contract_ai.reference_text(
        "too_many_references", kind="photo"
    )
    (col1, col2) = vm.columns(vm.ai_spans(_MEDIA), plan)
    assert (col1["tone"], col1["cap"]) == ("warn", f"⚠ {cap + 1} fotos · máx. {cap}")
    assert (col2["tone"], col2["cap"]) == ("", "")
    assert vm.room_for(_plan(items[:cap]), 0, "photo") == vm.cap_full("photo", 1, cap)
    assert vm.room_for(_plan(items[: cap - 1]), 0, "photo") == ""
    assert vm.cap_card("video", 2, 4, 3) == (
        "La parte con IA 2 tiene 4 videos de referencia y la IA usa hasta 3. "
        "Quita uno o muévelo a otra parte para seguir."
    )
    assert vm.cap_full("video", 2, 3).endswith("Quita uno para agregar otro.")
    assert vm.cap_full("photo", 1, 9).endswith("Quita una para agregar otra.")


def test_overlapping_references_stack_and_rows_come_and_go() -> None:
    a = vm.new_item([], "photo", [_k("a.png")], 2.0, 7.0)
    b = vm.new_item([a], "photo", [_k("b.png")], 3.0, 5.0)
    c = vm.new_item([a, b], "video", [_k("c.mp4")], 3.0, 5.0)
    assert (a["row"], b["row"], c["row"]) == (0, 1, 0)  # a kind's rows are its own
    items = vm.shift([a, b, c], b["uid"], 8.0, _TOTAL, row=0)
    assert {i["uid"]: i["row"] for i in items} == {a["uid"]: 0, b["uid"]: 0, c["uid"]: 0}
    items = vm.shift(items, b["uid"], 4.0, _TOTAL, row=0)  # over «a»: back to a row of its own
    assert {i["uid"]: i["row"] for i in items}[b["uid"]] == 1
    rows = vm.rows(items, _plan(items), _TOTAL)
    lanes, names, folded = vm.lanes(rows)
    assert [n["name"] for n in names] == [
        "Fotos de referencia 1",
        "Fotos de referencia 2",
        "Videos de referencia",
    ]
    assert [len(lane) for lane in lanes] == [1, 1, 1]
    assert folded == "Sin audios de referencia"
    assert vm.folded_text(["photo", "video", "audio"]) == "Sin referencias todavía"
    assert vm.folded_text(["video", "audio"]) == "Sin videos ni audios de referencia"
    assert vm.lanes([]) == ([], [], "Sin referencias todavía")
    assert vm.first_folded_kind(["video", "audio"]) == "video"


def test_times_stick_to_the_ai_parts_edges_and_stay_inside_the_video() -> None:
    edges = vm.edges_of(vm.ai_spans(_MEDIA))
    a = vm.new_item([], "photo", [_k("a.png")], 2.0, 7.0)
    (moved,) = vm.set_time([a], a["uid"], 2.2, 6.8, _TOTAL, edges=edges)
    assert (moved["start"], moved["end"]) == (2.0, 7.0)
    (short,) = vm.set_time([a], a["uid"], 5.0, 5.2, _TOTAL, edges=())
    assert short["end"] - short["start"] == vm.MIN_S
    (late,) = vm.shift([a], a["uid"], 30.0, _TOTAL, edges=edges)
    assert (late["start"], late["end"]) == (7.0, 12.0)
    (pulled,) = vm.shift([a], a["uid"], 6.8, _TOTAL, edges=edges)
    assert pulled["start"] == 7.0  # its start sticks to the part's edge


def test_the_products_block_is_whole_and_counts_each_photo() -> None:
    owner = vm.new_item([], "photo", [_k("a.png")], 2.0, 7.0)
    items = vm.product_item(
        [owner],
        "b0000000-0000-4000-8000-000000000002",
        "Combo",
        [_k("p1.jpg"), _k("p2.jpg"), _k("video.mp4")],
    )
    product = next(i for i in items if i["origin"] == "product")
    assert product["keys"] == [_k("p1.jpg"), _k("p2.jpg")]  # photos only
    assert product["row"] == 0 and next(i for i in items if i is not product)["row"] == 1
    (resolved,) = [i for i in vm.resolved(items, 9.5) if i["origin"] == "product"]
    assert (resolved["start"], resolved["end"]) == (0.0, 9.5)
    refs = vm.brief_references(items, _TOTAL)
    assert [(r["key"], r["origin"]) for r in refs] == [
        (_k("p1.jpg"), "product"),
        (_k("p2.jpg"), "product"),
        (_k("a.png"), "owner"),
    ]
    assert vm.label_of(product, {}) == "Combo · 2 fotos"
    assert vm.without_product(items) == [{**next(i for i in items if i is not product), "row": 0}]
    one = vm.remove_key(items, product["uid"], _k("p1.jpg"))
    assert next(i for i in one if i["origin"] == "product")["keys"] == [_k("p2.jpg")]
    gone = vm.remove_key(one, product["uid"], _k("p2.jpg"))
    assert not any(i["origin"] == "product" for i in gone)


def test_a_reference_whole_under_a_moved_part_follows_it() -> None:
    under = vm.new_item([], "photo", [_k("a.png")], 3.0, 6.0)
    across = vm.new_item([under], "photo", [_k("b.png")], 6.0, 8.0)
    alone = vm.new_item([under, across], "photo", [_k("c.png")], 0.0, 1.5)
    before = {"ai:p1": (2.0, 7.0), "ai:p2": (7.0, 12.0)}
    after = {"ai:p1": (0.0, 5.0), "ai:p2": (7.0, 12.0)}
    items, went, stayed = vm.follow([under, across, alone], before, after, _TOTAL)
    by = {i["uid"]: (i["start"], i["end"]) for i in items}
    assert by[under["uid"]] == (1.0, 4.0)
    assert by[across["uid"]] == (6.0, 8.0) and by[alone["uid"]] == (0.0, 1.5)
    assert (went, stayed) == (["ai:p1"], 1)
    assert vm.follow([under], before, before, _TOTAL)[1:] == ([], 0)
    assert vm.follow_line([1]) == "Las referencias de la parte con IA 1 se movieron con ella."
    assert vm.follow_line([1, 2]) == "Las referencias se movieron con su parte con IA."
    # a shorter part keeps its reference inside it
    shorter = {"ai:p1": (2.0, 4.0), "ai:p2": (4.0, 9.0)}
    (inside,), _went, _stayed = vm.follow([under], before, shorter, _TOTAL)
    assert (inside["start"], inside["end"]) == (3.0, 4.0)


def test_rows_panel_and_box_say_what_each_reference_is_for() -> None:
    a = vm.new_item([], "photo", [_k("a.png")], 2.0, 7.0)
    b = vm.new_item([a], "audio", [_k("b.mp3")], 0.0, 1.5)
    plan = _plan([a, b])
    rows = {r["id"]: r for r in vm.rows([a, b], plan, _TOTAL)}
    row = rows[vm.ref_id(a["uid"])]
    assert row["kind"] == "refphoto" and row["label"] == "Foto de referencia 1"
    assert row["name"] == "Foto de referencia 1, de 0:02 a 0:07. Se usa en la parte con IA 1."
    assert row["help_id"] == vm.HELP_ID and row["ref_tag"] == ""
    assert rows[vm.ref_id(b["uid"])]["ref_tag"] == vm.UNUSED_TAG
    panel = vm.panel(b, plan, _TOTAL)
    assert panel["copy"] == "" and panel["off"] == "1"  # an audio never goes in the video
    assert panel["used"].endswith(vm.UNUSED_HELP)
    assert vm.panel(a, plan, _TOTAL)["copy"] == "1"
    (box,) = vm.ai_box([a, b], plan, 0, _TOTAL)
    assert box["name"] == "Foto de referencia 1" and box["ignored"] == ""
    assert vm.slug([a, b], vm.ref_id(a["uid"]), _TOTAL) == "referencia-foto-1"


def test_the_nearest_join_and_the_kinds_files() -> None:
    assert [vm.nearest_join(_MEDIA, t) for t in (0.4, 1.5, 4.0, 6.5, 11.9)] == [0, 1, 1, 2, 3]
    assert [vm.kind_of_key(k) for k in ("a.PNG", "b.mov", "c.wav", "d.webm")] == [
        "photo",
        "video",
        "audio",
        "",
    ]


def test_the_words_never_say_timeline_track_or_capa() -> None:
    words = [
        value
        for name, value in vars(vm).items()
        if name.isupper() and isinstance(value, str) and " " in value
    ]
    for text in words:
        lower = re.sub(r"\{[^}]*\}", "", text).lower()  # not its placeholders
        for banned in ("timeline", "track", "capa", "línea de tiempo"):
            assert banned not in lower, (banned, text)
    assert len(vm.ADD_LABEL) <= 16  # the orbit's pill (design system §5.9, rule 3)


def test_the_live_line_says_where_it_is_used_now_with_its_article() -> None:
    a = vm.new_item([], "photo", [_k("a.png")], 2.0, 7.0)
    v = vm.new_item([a], "video", [_k("v.mp4")], 0.0, 1.5)
    numbers = vm.numbers_of([a, v], _TOTAL)
    assert (
        vm.now_line(a, numbers, [2]) == "Ahora la foto de referencia 1 se usa en la parte con IA 2."
    )
    assert vm.now_line(a, numbers, [1, 2]) == (
        "Ahora la foto de referencia 1 se usa en las partes con IA 1 y 2."
    )
    assert vm.now_line(v, numbers, []) == (
        "Ahora el video de referencia 1 no está debajo de ninguna parte con IA: la IA no lo usa."
    )
    product = {
        **vm.new_item([], "photo", [_k("p.jpg")], 0, 1),
        "origin": "product",
        "name": "Combo Vecino",
    }
    assert vm.now_line(product, {}, [1, 2]) == (
        "Ahora las fotos de Combo Vecino se usan en las partes con IA 1 y 2."
    )
    assert vm.now_line(product, {}, []).endswith(
        "no están debajo de ninguna parte con IA: la IA no las usa."
    )
    assert vm.removed_line(v, numbers) == "Quitaste el video de referencia 1."
    assert vm.TOO_MANY.startswith(f"Ya tienes {vm.REFERENCES_MAX} referencias")


def test_two_references_that_follow_onto_one_row_never_overlap() -> None:
    a = vm.new_item([], "photo", [_k("a.png")], 2.0, 4.0)
    b = vm.new_item([a], "photo", [_k("b.png")], 4.0, 7.0)  # same row, one after the other
    assert (a["row"], b["row"]) == (0, 0)
    # «b»'s part moves 3 s left: it lands over «a» on their row — it goes to a free row
    before = {"ai:p1": (2.0, 4.0), "ai:p2": (4.0, 7.0)}
    after = {"ai:p1": (2.0, 4.0), "ai:p2": (1.0, 4.0)}
    items, went, _stayed = vm.follow([a, b], before, after, _TOTAL)
    by = {i["uid"]: i for i in items}
    assert went == ["ai:p2"]
    assert (by[b["uid"]]["start"], by[b["uid"]]["end"]) == (1.0, 4.0)
    assert by[b["uid"]]["row"] != by[a["uid"]]["row"]


def test_a_cut_into_a_joined_part_or_out_when_too_little_is_left() -> None:
    a = vm.new_item([], "photo", [_k("a.png")], 11.0, 12.2)
    b = vm.new_item([a], "photo", [_k("b.png")], 11.8, 13.0)
    items = vm.fit_into([a, b], [a["uid"], b["uid"]], (2.0, 12.0))
    assert [(i["start"], i["end"]) for i in items] == [(11.0, 12.0)]

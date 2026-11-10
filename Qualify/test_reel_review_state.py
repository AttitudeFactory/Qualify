"""UI-6 (m-24921081): «Revisa y crea» por partes in `CreativeState` and the view — the
summary in words and its rows, «Crear las n partes» (the frame's primary) and «Probar
solo la parte 1» (aria-disabled, all or nothing), both creating the video's PARENT
through `creative_provider.submit_parts_brief` (a double here: no database, no vendor)
and showing the result, the reasons and ways out beside them, and the usual Crear
unchanged."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.creative.final_video import PreviewUse
from qualify_api.creative.parts import ParentTextCapReached, PartsOverBudget
from sqlalchemy.exc import SQLAlchemyError

from . import creative_state as cs
from . import reel_parts_vm as parts_vm
from .creative_provider import PartsPreviewsShort
from .creative_state import CreativeState
from .test_generator_campaign import _Proxy
from .test_reel_parts_state import planned
from .test_reel_review_vm import entry
from .test_reel_wait_state import replica

DRAFT = uuid4()


def session(monkeypatch: pytest.MonkeyPatch, *, submit: Any = None) -> list[dict[str, Any]]:
    """A signed-in session whose provider records what it is sent (no database)."""
    ids = (uuid4(), uuid4(), uuid4())
    calls: list[dict[str, Any]] = []

    async def session_ids(self: CreativeState) -> tuple[UUID, UUID, UUID]:
        return ids

    async def refresh(self: CreativeState, tenant_id: UUID, brand_id: UUID) -> None:
        return None

    def create(tenant_id: UUID, brand_id: UUID, user_id: UUID, **options: Any) -> UUID:
        calls.append(options)
        return DRAFT

    monkeypatch.setattr(CreativeState, "_session_ids", session_ids)
    monkeypatch.setattr(CreativeState, "_refresh_creations", refresh)
    monkeypatch.setattr(cs, "submit_parts_brief", submit or create)
    return calls


async def press(state: CreativeState, event: str) -> list[Any]:
    handler = getattr(CreativeState, event)
    return [e async for e in handler.fn(_Proxy(state))]


def on_summary(state: CreativeState) -> CreativeState:
    state.gen_step = len(state._gen_steps()) - 1
    assert state._on_summary()
    return state


def with_month(state: CreativeState, *, previews: int, seconds: int = 40) -> CreativeState:
    state.creations_left, state.creations_quota = 10, 30
    state.previews_left, state.previews_quota = previews, 20
    state.videos_left, state.videos_quota = seconds, 40
    state.creations_renews = "1 de diciembre"
    return state


def four_parts(previews: int = 10) -> CreativeState:
    return on_summary(with_month(planned(), previews=previews))


def test_step_5_says_the_plan_in_words() -> None:
    state = four_parts()
    assert state.reel_review_text.startswith("Un reel de 21 s en 4 partes, con tu Smash doble.")
    assert state.reel_create_all_label == "Crear las 4 partes"
    assert state.reel_try_first_shown
    assert state.reel_create_all_reason == state.reel_try_first_reason == ""
    # the usual flow's notices stay out of parts mode
    assert state.gen_problem == "" and state.gen_creations_notice == ""
    assert state.reel_usage_lines[0].startswith("Crear las 4 partes usa 4 vistas previas")


def test_off_the_summary_nothing_is_said() -> None:
    state = with_month(planned(), previews=10)
    assert not state._on_summary()
    assert state.reel_review_text == "" and state.reel_create_all_reason == ""


def test_short_of_vistas_previas_disables_only_create_all() -> None:
    state = four_parts(previews=2)
    assert state.reel_create_all_reason.startswith("Crear las 4 partes usa 4 vistas previas")
    assert state.reel_try_first_reason == "" and state.reel_back_to_parts
    assert state.gen_exhausted == ""


def test_no_vista_previa_disables_both_and_offers_to_ask() -> None:
    state = four_parts(previews=0)
    assert state.reel_create_all_reason != "" and state.reel_try_first_reason != ""
    # «Pedir más a Qualify» goes under the reason, not at the top of the summary
    assert state.reel_exhausted == "previews" and state.gen_exhausted == ""


def test_a_part_that_could_not_be_seen_blocks_both() -> None:
    state = planned()
    entries = [dict(e) for e in state._reel_plan]
    blind = entry("reference", 4, description="", notices=("describe_it",))
    entries[1] = {**entries[1], "plan": blind["plan"]}
    state._set_reel_plan(entries)
    on_summary(with_month(state, previews=10))
    assert state.reel_create_all_reason == (
        "No pudimos ver qué pasa en la parte 2 del reel. Quítala en el paso 2 para crear las demás."
    )
    assert state.reel_try_first_reason == state.reel_create_all_reason
    assert state.reel_back_to_parts
    # nothing is sent while blocked; the frame's primary is disabled
    assert state.create_primary_disabled and state.create_reason == parts_vm.FOOT_BLOCKED


async def test_a_blocked_plan_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = session(monkeypatch)
    state = planned()
    entries = [dict(e) for e in state._reel_plan]
    blind = entry("reference", 4, description="", notices=("describe_it",))
    entries[1] = {**entries[1], "plan": blind["plan"]}
    state._set_reel_plan(entries)
    on_summary(with_month(state, previews=10))
    await press(state, "create_all_reel_parts")
    await press(state, "try_first_reel_part")
    assert calls == [] and state.create_error == "" and state.generator_view != "result"


def test_one_part_has_no_try_first() -> None:
    state = on_summary(with_month(planned([entry("edit", 5)]), previews=5))
    assert state.reel_create_all_label == "Crear la parte" and not state.reel_try_first_shown


@pytest.mark.parametrize(
    ("event", "scope"), [("create_all_reel_parts", "all"), ("try_first_reel_part", "first")]
)
async def test_both_actions_create_the_parent_and_show_the_result(
    event: str, scope: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = session(monkeypatch)
    state = four_parts()
    events = await press(state, event)
    assert len(calls) == 1
    options = calls[0]
    assert options["scope"] == scope and len(options["parts"]) == 4
    assert options["kind"] == "clip"  # the form as Crear sends it; the provider re-kinds it
    # the parent's topic is what the piece is and nothing else: every part inherits it
    assert options["topic"] == "Reel de Smash doble, armado por partes."
    assert options["product_ref"] == "Smash doble"
    assert state.generator_view == "result" and state.gen_draft_id == str(DRAFT)
    assert not state.is_submitting and state.create_error == ""
    assert CreativeState.poll_generator in events


async def test_a_second_tap_while_creating_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = session(monkeypatch)
    state = four_parts()
    state.is_submitting = True
    await press(state, "create_all_reel_parts")
    assert calls == []


async def test_vistas_previas_short_on_arrival_create_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def short(*args: Any, **kwargs: Any) -> UUID:
        raise PartsPreviewsShort(PreviewUse(uses=4, left=2, quota=20, renews_on=None), 4)

    async def refreshed(self: CreativeState, tenant_id: UUID, brand_id: UUID) -> None:
        self.previews_left = 2  # what the month really has, read again

    session(monkeypatch, submit=short)
    monkeypatch.setattr(CreativeState, "_refresh_creations", refreshed)
    state = four_parts()
    await press(state, "create_all_reel_parts")
    # no error: the reason and «Volver al paso 2» show beside the buttons
    assert state.create_error == "" and state.reel_back_to_parts
    assert state.reel_create_all_reason.startswith("Crear las 4 partes usa 4 vistas previas")
    assert state.generator_view != "result" and not state.is_submitting


async def test_short_on_arrival_unseen_by_the_counters_is_still_said(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def short(*args: Any, **kwargs: Any) -> UUID:
        raise PartsPreviewsShort(PreviewUse(uses=4, left=2, quota=20, renews_on=None), 4)

    session(monkeypatch, submit=short)
    state = four_parts()
    await press(state, "create_all_reel_parts")
    assert state.create_error.startswith("Crear las 4 partes usa 4 vistas previas")


@pytest.mark.parametrize(
    "error", [SQLAlchemyError("db down"), ValueError("raw text"), RuntimeError("boom")]
)
async def test_a_failure_says_it_in_spanish_never_raw(
    error: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> UUID:
        raise error

    session(monkeypatch, submit=boom)
    state = four_parts()
    await press(state, "create_all_reel_parts")
    assert state.create_error and "raw text" not in state.create_error
    assert "boom" not in state.create_error and "db down" not in state.create_error
    assert not state.is_submitting and state.generator_view != "result"


async def test_a_foreign_text_is_never_shown(monkeypatch: pytest.MonkeyPatch) -> None:
    class Refusal(Exception):
        text = "Tu equipo llegó al tope de gasto de este mes."

    def refuse(*args: Any, **kwargs: Any) -> UUID:
        raise Refusal("raw english")

    session(monkeypatch, submit=refuse)
    state = four_parts()
    await press(state, "create_all_reel_parts")
    # not a refusal of `qualify_api.creative.parts`: its text is never shown
    assert state.create_error == parts_vm.PARTS_UNAVAILABLE_TEXT


async def test_an_unknown_failure_says_nothing_was_used(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> UUID:
        raise RuntimeError("raw english")

    session(monkeypatch, submit=boom)
    state = four_parts()
    await press(state, "create_all_reel_parts")
    assert (
        state.create_error
        == parts_vm.PARTS_UNAVAILABLE_TEXT
        == (
            "No pudimos crear las partes de tu video y no se usó ninguna vista previa. "
            "Inténtalo más tarde."
        )
    )


def test_the_piece_is_called_video_por_partes_wherever_its_kind_is_named() -> None:
    from . import content_generator as cg

    state = planned()  # steps 2-4 too, not only the summary
    assert state.gen_kind_label == parts_vm.PARTS_PIECE_LABEL == "Video por partes"
    rendered = str(cg._options_panel().render())
    assert "reel_plan_shown" in rendered and "Video por partes" in rendered
    usual = replica("ok")
    assert usual.gen_kind_label != "Video por partes"


def test_no_second_left_is_said_once() -> None:
    state = four_parts(previews=10)
    state.videos_left = 0
    assert state.reel_create_all_reason.startswith("Ya usaste tus 40 segundos de video")
    assert not any("segundos" in line for line in state.reel_usage_lines)
    assert state.create_reason == parts_vm.FOOT_NO_SECONDS


async def test_short_first_part_checks_its_own_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    def short(*args: Any, **kwargs: Any) -> UUID:
        raise PartsPreviewsShort(PreviewUse(uses=1, left=0, quota=20, renews_on=None), 1)

    async def refreshed(self: CreativeState, tenant_id: UUID, brand_id: UUID) -> None:
        self.previews_left = 0

    session(monkeypatch, submit=short)
    monkeypatch.setattr(CreativeState, "_refresh_creations", refreshed)
    state = four_parts()
    await press(state, "try_first_reel_part")
    assert state.create_error == "" and state.reel_try_first_reason != ""


@pytest.mark.parametrize(
    ("refusal", "text"),
    [
        (
            lambda: PartsOverBudget(estimated_usd=Decimal("9"), remaining_usd=Decimal("1")),
            None,
        ),
        (
            lambda: ParentTextCapReached(20),
            "Hoy ya pediste 20 textos nuevos para tu negocio. Mañana puedes pedir otros 20.",
        ),
    ],
    ids=["over-budget", "text-cap"],
)
async def test_only_the_parts_own_refusals_speak_their_text(
    refusal: Any, text: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> UUID:
        raise refusal()

    session(monkeypatch, submit=refuse)
    state = four_parts()
    await press(state, "create_all_reel_parts")
    assert state.create_error == (text or refusal().text)
    assert not state.is_submitting and state.generator_view != "result"


def test_the_summary_shows_what_the_parent_takes() -> None:
    state = four_parts()
    rows = {row["label"]: row for row in state.gen_summary}
    assert rows["Qué creamos"]["value"] == "Video por partes"
    assert rows["Producto"]["value"] == "Smash doble"
    assert rows["Partes"]["value"] == "4 partes · 21 s" and rows["Partes"]["view"] == "reference"
    for hidden in (
        "Video de referencia",
        "Referencias",
        "Abre y cierra",
        "Fotos del medio",
        "Textos del video",
    ):
        assert hidden not in rows
    # the single clip's length is not the video's: «Partes» says it
    assert rows["Publicación"]["value"] == "Producto · Reel (video corto) 9:16"


def test_without_a_chosen_product_the_summary_names_none() -> None:
    state = four_parts()
    state.selected_product_id = ""
    assert ", con tu" not in state.reel_review_text
    assert state._parts_topic() == "Reel armado por partes."


def test_a_reel_nobody_could_see_sends_back_to_the_ideas() -> None:
    blind = entry("reference", 4, description="", notices=("describe_it",))
    state = on_summary(with_month(planned([blind, dict(blind, key="b2")]), previews=10))
    assert state.reel_to_ideas and not state.reel_back_to_parts
    assert state.create_reason == parts_vm.FOOT_BLOCKED_MANY


def test_the_frames_primary_is_crear_las_n_partes() -> None:
    state = four_parts()
    assert state.create_primary_label == "Crear las 4 partes"
    assert not state.create_primary_disabled and state.create_reason == ""
    assert state.create_continue() is CreativeState.create_all_reel_parts
    short = four_parts(previews=2)
    assert short.create_primary_disabled and short.create_reason == parts_vm.FOOT_SHORT


def test_the_previews_line_is_not_said_twice() -> None:
    state = four_parts(previews=2)
    assert not any("vistas previas" in line for line in state.reel_usage_lines)
    assert state.reel_usage_lines[0].startswith("Este video dura 21 s")
    off = with_month(planned(), previews=2)  # step 2 keeps it
    assert off.reel_usage_lines[0].startswith("Crear las 4 partes usa 4 vistas previas")


def test_the_usual_flow_is_unchanged() -> None:
    state = replica("ok")  # a replica whose plan is not open: the usual clip
    assert not state.reel_plan_shown
    on_summary(state)
    assert state.reel_review_text == "" and state.reel_create_all_reason == ""
    assert not state.reel_back_to_parts
    assert state.create_primary_label == "Crear"
    assert state.create_continue() is CreativeState.submit_generator_form


# -- the view, built in memory --------------------------------------------------------


def test_the_parts_review_holds_the_secondary_and_the_reason() -> None:
    from . import content_generator as cg

    rendered = str(cg._parts_review().render())
    # (non-ASCII letters are escaped in the rendered tree)
    for text in (
        "Probar solo la parte 1",
        "Usa 1 vista previa. Las dem",
        "Volver al paso 2",
        "Ideas para tus reels",
        "exit_create",
        "LucideSparkles",
    ):
        assert text in rendered
    assert "aria-disabled" in rendered or "ariaDisabled" in rendered
    assert cg.REEL_CREATE_REASON_ID in rendered
    assert "aria-describedby" in rendered or "ariaDescribedby" in rendered
    assert "try_first_reel_part" in rendered


def test_the_summary_view_carries_the_parts_review() -> None:
    from . import content_generator as cg

    rendered = str(cg._summary_view().render())
    text, rows, usage = (
        rendered.index("reel_review_text"),
        rendered.index("gen_summary"),
        rendered.index("reel_usage_lines"),
    )
    assert text < rows < usage  # summary → rows with «Editar» → «Lo que usa de tu mes»

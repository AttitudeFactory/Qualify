"""QUA-143 in the «Nueva publicación» drawer, offline: each piece shows its POST's
campaign, the selector starts on it, a change warns that it reaches the POST's other
publications, «Nueva campaña» needs a name and offers only the four colours, «… y campaña
en todas» copies it — and «Confirmar» applies the campaign to the POST ONLY AFTER the
piece's publications were created (`schedule_plan_rows`), so a refused schedule leaves the
POST's campaign untouched and creates no campaign."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from qualify_api.planner.service import PlannerError

from . import campaign_provider as cp
from . import planner_drawer
from .planner_state import MODE_ASSIGN, MODE_RESCHEDULE, PlannerState, schedule_plan_rows
from .planner_vm import (
    CAMPAIGN_NAME_REQUIRED,
    CAMPAIGN_NEW,
    CAMPAIGN_NONE,
    ConnectionChoiceVM,
    PlanItem,
    PostOptionVM,
    build_plan_row,
    campaign_warning,
)

LANZ = cp.CampaignOptionVM(id=str(uuid4()), name="Lanzamiento", color="violet")
NAVIDAD = cp.CampaignOptionVM(id=str(uuid4()), name="Navidad", color="pink")
ACCOUNT = ConnectionChoiceVM(id=str(uuid4()), label="@marca", platform="instagram")


def _js(text: str) -> str:
    return json.dumps(text)[1:-1]


def _post(*, campaign: cp.CampaignOptionVM | None = None, event_count: int = 0) -> PostOptionVM:
    return PostOptionVM(
        post_id=str(uuid4()),
        title="Sabor de temporada",
        caption_excerpt="",
        thumbnail_url="",
        category_label="Galería",
        approval_label="Aprobado",
        approval_tone="ok",
        detail_href="",
        schedulable=True,
        campaign_name=campaign.name if campaign else "",
        campaign_color=campaign.color if campaign else "",
        campaign_id=campaign.id if campaign else "",
        event_count=event_count,
    )


def _row(post: PostOptionVM, *, reschedule: bool = False, **item):
    return build_plan_row(
        PlanItem(
            post_id=post.post_id,
            date="2030-01-07",
            time="10:00",
            connection_ids=[ACCOUNT.id],
            **item,
        ),
        post=post,
        connections=[ACCOUNT],
        campaigns=[LANZ, NAVIDAD],
        reschedule=reschedule,
    )


# --- the piece: header badge, preselection, warning, new campaign ----------------------


def test_the_piece_shows_and_preselects_the_posts_campaign() -> None:
    row = _row(_post(campaign=LANZ, event_count=3))
    assert (row.current_campaign_name, row.current_campaign_color) == ("Lanzamiento", "violet")
    assert row.campaign_value == LANZ.id
    assert row.campaign_changed is False and row.campaign_warning == ""
    independent = _row(_post())
    assert independent.current_campaign_name == "" and independent.campaign_value == CAMPAIGN_NONE


def test_a_change_warns_that_it_reaches_the_posts_other_publications() -> None:
    post = _post(campaign=LANZ, event_count=3)
    changed = _row(post, campaign=NAVIDAD.id)
    assert changed.campaign_changed is True
    assert (changed.chosen_campaign_name, changed.chosen_campaign_color) == ("Navidad", "pink")
    assert changed.campaign_warning == (
        "La campaña pertenece al POST y también se aplicará a sus otras 3 publicaciones."
    )
    cleared = _row(post, campaign=CAMPAIGN_NONE)
    assert cleared.campaign_changed is True and "3 publicaciones" in cleared.campaign_warning
    assert campaign_warning(1) == (
        "La campaña pertenece al POST y también se aplicará a su otra publicación."
    )
    # A POST with no publications yet: a change, but nothing else to warn about.
    first_time = _row(_post(event_count=0), campaign=LANZ.id)
    assert first_time.campaign_changed is True and first_time.campaign_warning == ""


def test_a_new_campaign_needs_a_name_and_carries_its_colour() -> None:
    post = _post()
    nameless = _row(post, campaign=CAMPAIGN_NEW, new_campaign_color="orange")
    assert nameless.creating_campaign is True
    assert nameless.error == CAMPAIGN_NAME_REQUIRED
    named = _row(
        post, campaign=CAMPAIGN_NEW, new_campaign_name="  Verano ", new_campaign_color="orange"
    )
    assert named.error != CAMPAIGN_NAME_REQUIRED  # the name is there (destination aside)
    assert (named.chosen_campaign_name, named.chosen_campaign_color) == ("Verano", "orange")
    assert named.campaign_changed is True


def test_a_reschedule_never_touches_the_campaign() -> None:
    row = _row(_post(campaign=LANZ, event_count=2), reschedule=True, campaign=NAVIDAD.id)
    assert row.campaign_changed is False and row.campaign_warning == ""
    assert row.creating_campaign is False
    # The header still says which campaign the POST is in.
    assert row.current_campaign_name == "Lanzamiento"


# --- the state: selector, colours, «… y campaña en todas» -------------------------------


def _state(*posts: PostOptionVM) -> PlannerState:
    state = PlannerState()
    state.form_mode = MODE_ASSIGN
    state.connections = [ACCOUNT]
    state.campaigns = [LANZ, NAVIDAD]
    state.schedulable = list(posts)
    state.plan_items = [PlanItem(post_id=p.post_id, connection_ids=[ACCOUNT.id]) for p in posts]
    return state


def test_new_campaign_preselects_a_campaign_colour_and_refuses_state_colours() -> None:
    post = _post()
    state = _state(post)
    state.set_item_campaign(post.post_id, CAMPAIGN_NEW)
    item = state._item(post.post_id)
    assert item.campaign == CAMPAIGN_NEW
    assert item.new_campaign_color == "blue"  # the next after two existing campaigns
    for state_color in ("teal", "green", "amber", "gray"):
        state.set_item_new_campaign_color(post.post_id, state_color)
        assert state._item(post.post_id).new_campaign_color == "blue"
    state.set_item_new_campaign_color(post.post_id, "orange")
    assert state._item(post.post_id).new_campaign_color == "orange"


def test_apply_to_all_copies_the_campaign_the_piece_shows() -> None:
    with_campaign, other, third = _post(campaign=LANZ), _post(campaign=NAVIDAD), _post()
    state = _state(with_campaign, other, third)
    # The source piece kept its POST's own campaign: that is what is copied.
    state.apply_to_all(with_campaign.post_id)
    assert {i.campaign for i in state.plan_items} == {LANZ.id}
    # A new campaign typed in one piece goes to every piece (created once, by name).
    state.set_item_campaign(third.post_id, CAMPAIGN_NEW)
    state.set_item_new_campaign_name(third.post_id, "Verano")
    state.set_item_new_campaign_color(third.post_id, "orange")
    state.apply_to_all(third.post_id)
    assert {(i.campaign, i.new_campaign_name, i.new_campaign_color) for i in state.plan_items} == {
        (CAMPAIGN_NEW, "Verano", "orange")
    }


def test_the_drawer_renders_the_campaign_field_and_the_renamed_shortcut() -> None:
    rendered = str(planner_drawer._plan_card(planner_drawer.PlannerState.plan_rows[0]))
    assert _js("Usar canales, etiquetas y campaña en todas") in rendered
    assert _js("Usar canales y etiquetas en todas") not in rendered
    assert "current_campaign_name" in rendered and "campaign_warning" in rendered
    field = str(planner_drawer._plan_campaign(planner_drawer.PlannerState.plan_rows[0]))
    for word in ("Campaña", "Sin campaña", "+ Nueva campaña", "Nombre de la nueva campaña"):
        assert _js(word) in field
    for key in cp.COLOR_LABELS:
        assert f"q-swatch q-tint-{key}" in field
    for state_color in ("teal", "green", "amber", "gray"):
        assert f"q-tint-{state_color}" not in field


# --- «Confirmar»: the campaign only after the publications ------------------------------


def _calls():
    log: list[tuple] = []

    def schedule(tenant_id, post_id, *rest):
        log.append(("schedule", post_id))
        return 1

    def apply_campaign(tenant_id, post_id, value, *, new_name, new_color, user_id):
        log.append(("campaign", str(post_id), value, new_name, new_color, user_id))

    return log, schedule, apply_campaign


USER = uuid4()
TENANT = uuid4()


async def _confirm(rows, *, schedule, apply_campaign, mode=MODE_ASSIGN):
    return await schedule_plan_rows(
        TENANT,
        rows,
        mode=mode,
        event_id="",
        view_tz="UTC",
        goals=(),
        schedule=schedule,
        reschedule=lambda *a: None,
        apply_campaign=apply_campaign,
        resolve_user=lambda tenant_id: USER,
    )


@pytest.mark.asyncio
async def test_the_campaign_is_applied_after_the_publications_are_created() -> None:
    log, schedule, apply_campaign = _calls()
    post = _post(campaign=LANZ, event_count=2)
    row = _row(post, campaign=CAMPAIGN_NEW, new_campaign_name="Verano", new_campaign_color="pink")
    created, planned, failure = await _confirm(
        [row], schedule=schedule, apply_campaign=apply_campaign
    )
    assert (created, planned, failure) == (1, [post.post_id], "")
    assert log == [
        ("schedule", post.post_id),
        ("campaign", post.post_id, CAMPAIGN_NEW, "Verano", "pink", USER),
    ]


@pytest.mark.asyncio
async def test_a_refused_schedule_leaves_the_posts_campaign_untouched() -> None:
    log, _schedule, apply_campaign = _calls()

    def refused(tenant_id, post_id, *rest):
        log.append(("schedule", post_id))
        raise PlannerError("refused")

    post = _post(campaign=LANZ, event_count=2)
    row = _row(post, campaign=CAMPAIGN_NEW, new_campaign_name="Verano", new_campaign_color="pink")
    created, planned, failure = await _confirm(
        [row], schedule=refused, apply_campaign=apply_campaign
    )
    assert (created, planned) == (0, [])
    assert failure.startswith("«Sabor de temporada»:")
    assert log == [("schedule", post.post_id)]  # no campaign created, none assigned


@pytest.mark.asyncio
async def test_only_the_pieces_that_were_planned_get_their_campaign() -> None:
    log, schedule, apply_campaign = _calls()
    first, second = _post(), _post()

    def second_refused(tenant_id, post_id, *rest):
        if post_id == second.post_id:
            log.append(("schedule", post_id))
            raise PlannerError("refused")
        return schedule(tenant_id, post_id, *rest)

    rows = [_row(first, campaign=LANZ.id), _row(second, campaign=LANZ.id)]
    created, planned, failure = await _confirm(
        rows, schedule=second_refused, apply_campaign=apply_campaign
    )
    assert planned == [first.post_id] and failure
    assert [entry for entry in log if entry[0] == "campaign"] == [
        ("campaign", first.post_id, LANZ.id, "", "", USER)
    ]


@pytest.mark.asyncio
async def test_no_change_no_campaign_write_and_never_on_a_reschedule() -> None:
    log, schedule, apply_campaign = _calls()
    kept = _row(_post(campaign=LANZ, event_count=1))
    await _confirm([kept], schedule=schedule, apply_campaign=apply_campaign)
    moved = _row(_post(campaign=LANZ), reschedule=True, campaign=NAVIDAD.id)
    await _confirm([moved], schedule=schedule, apply_campaign=apply_campaign, mode=MODE_RESCHEDULE)
    assert [entry for entry in log if entry[0] == "campaign"] == []


@pytest.mark.asyncio
async def test_a_campaign_that_cannot_be_saved_is_reported_after_the_schedule() -> None:
    _log, schedule, _apply = _calls()

    def broken(*args, **kwargs):
        raise cp.InvalidCampaignName("El nombre de la campaña no puede estar vacío.")

    post = _post()
    row = _row(post, campaign=LANZ.id)
    created, planned, failure = await _confirm([row], schedule=schedule, apply_campaign=broken)
    assert (created, planned) == (1, [post.post_id])
    assert "quedó programado, pero no se pudo guardar su campaña" in failure


def test_the_post_choice_maps_to_the_campaign_service(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []
    from qualify_api.creative import campaigns

    monkeypatch.setattr(
        campaigns,
        "create_for_post",
        lambda t, p, name, *, color, created_by: calls.append(("new", name, color, created_by)),
    )
    monkeypatch.setattr(
        campaigns, "set_post_campaign", lambda t, p, campaign_id: calls.append(("set", campaign_id))
    )
    tenant, post, camp = uuid4(), uuid4(), uuid4()
    cp.apply_post_choice(tenant, post, cp.NEW_CAMPAIGN, new_name="Verano", new_color="pink")
    cp.apply_post_choice(tenant, post, cp.NO_CAMPAIGN)
    cp.apply_post_choice(tenant, post, str(camp))
    assert calls == [("new", "Verano", "pink", None), ("set", None), ("set", UUID(str(camp)))]


def test_confirm_shows_the_campaign_the_post_will_have() -> None:
    row = planner_drawer.PlannerState.plan_rows[0]
    rendered = str(planner_drawer._confirm_campaign(row))
    assert "chosen_campaign_name" in rendered and "campaign_warning" in rendered
    for text in (
        "Campaña nueva: se creará al programar.",
        "El POST quedará sin campaña al programar.",
        "La campaña del POST cambiará al programar.",
    ):
        assert _js(text) in rendered
    assert "_confirm_campaign" not in rendered
    timeline = str(planner_drawer._timeline_item(row))
    assert "chosen_campaign_name" in timeline
    field = str(planner_drawer._plan_campaign(row))
    assert _js("Se creará al confirmar la programación.") in field

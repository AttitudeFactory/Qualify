"""QUA-143 on the UI side, offline: the campaign travels from `PostSummary` into every
view-model the calendar and the gallery render (card, panel, gallery option), an
independent POST carries nothing new, the campaign marks are drawn in the tag palette and
never on the status edge, and the «Campaña» field's state and messages."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
import reflex as rx
from qualify_api.creative import campaigns
from qualify_api.planner.post_reader import ApprovalStatus, PostCampaign, PostSummary

from . import campaign_provider as cp
from . import creative_pages, planner_page
from .campaign_state import CampaignState
from .planner_provider import _campaign_fields
from .planner_vm import CardInput, EventCardVM, PostOptionVM, build_card, build_post_option
from .post_card import campaign_badge, campaign_mark

# Stand-ins for the `rx.foreach` item Vars the components receive.
_EventVar = rx.Var(_js_expr="event", _var_type=EventCardVM).guess_type()
_PostVar = rx.Var(_js_expr="post", _var_type=PostOptionVM).guess_type()


def _js(text: str) -> str:
    return json.dumps(text)[1:-1]


def _summary(campaign: PostCampaign | None) -> PostSummary:
    return PostSummary(
        post_id=uuid4(),
        brand_id=uuid4(),
        title="Sabor de temporada",
        approval=ApprovalStatus.APPROVED,
        campaign=campaign,
    )


def _card(**extra) -> CardInput:
    return CardInput(
        event_id="e1",
        post_id="p1",
        scheduled_at=datetime(2026, 10, 12, 15, 0, tzinfo=UTC),
        status="scheduled",
        overdue=False,
        connection_id="c1",
        post_title="Sabor de temporada",
        approval="approved",
        is_publishable=True,
        **extra,
    )


def test_the_campaign_reaches_the_view_models_through_the_post() -> None:
    camp = PostCampaign(id=uuid4(), name="Lanzamiento Polette", color="violet")
    fields = _campaign_fields(_summary(camp))
    assert fields == {"campaign_name": "Lanzamiento Polette", "campaign_color": "violet"}
    card = build_card(_card(**fields), zone=ZoneInfo("UTC"), connections={})
    assert (card.campaign_name, card.campaign_color) == ("Lanzamiento Polette", "violet")
    option = build_post_option(
        post_id="p1",
        title="Sabor de temporada",
        caption_excerpt="",
        thumbnail_url=None,
        category="galeria",
        approval="approved",
        detail_href="/drafts/p1",
        is_publishable=True,
        unpublishable_reason="",
        **fields,
    )
    assert (option.campaign_name, option.campaign_color) == ("Lanzamiento Polette", "violet")


def test_an_independent_post_carries_nothing_new_and_reads_as_before() -> None:
    assert _campaign_fields(_summary(None)) == {}
    assert _campaign_fields(None) == {}  # the POST could not be read
    with_none = build_card(_card(), zone=ZoneInfo("UTC"), connections={})
    assert with_none.campaign_name == "" and with_none.campaign_color == ""
    # The campaign changes nothing else of the card: same state words and tones.
    with_campaign = build_card(
        _card(campaign_name="X", campaign_color="blue"), zone=ZoneInfo("UTC"), connections={}
    )
    for field_name in ("status_label", "status_tone", "approval_label", "approval_tone"):
        assert getattr(with_campaign, field_name) == getattr(with_none, field_name)
    assert with_campaign.overdue == with_none.overdue


def test_the_campaign_marks_use_the_tag_palette_not_the_status_edge() -> None:
    badge = str(campaign_badge("Lanzamiento", "violet"))
    mark = str(campaign_mark("Lanzamiento", "violet"))
    assert "q-campaign-badge q-tint-violet" in badge and "Lanzamiento" in badge
    assert "q-campaign-mark q-tint-violet" in mark
    assert "border-left" not in badge + mark and "borderLeft" not in badge + mark
    assert _js("Campaña: ") + "Lanzamiento" in badge  # the title says what it is
    # The calendar's chip, hover card, «+N más» row and list item all draw it...
    for render in (
        planner_page._calendar_chip,
        planner_page._chip_detail,
        planner_page._hour_list_row,
        planner_page._list_item,
    ):
        assert "campaign_name" in str(render(_EventVar))
    # ...and the chip's status edge is still computed from the state alone.
    assert "campaign" not in str(planner_page._chip_edge(_EventVar))


def test_the_gallery_card_shows_the_campaign() -> None:
    assert "campaign_name" in str(creative_pages._gallery_card(_PostVar))


def test_the_post_detail_has_the_campaign_field() -> None:
    rendered = str(creative_pages._campaign_field())
    for word in ("Campaña", "Nueva campaña", "Sin campaña (post independiente)"):
        assert _js(word) in rendered
    assert cp.NO_CAMPAIGN in rendered


def test_field_state_applies_the_view_model_and_toggles_the_inline_form() -> None:
    state = CampaignState()
    vm = cp.CampaignFieldVM(
        current_id="c1",
        current_name="Lanzamiento",
        current_color="blue",
        options=[cp.CampaignOptionVM(id="c1", name="Lanzamiento", color="blue")],
    )
    state._apply(vm)
    assert (state.current_id, state.current_name, state.current_color) == (
        "c1",
        "Lanzamiento",
        "blue",
    )
    assert [o.name for o in state.options] == ["Lanzamiento"]
    state.start_create()
    assert state.creating and state.new_name == ""
    state.set_new_name("Navidad")
    assert state.new_name == "Navidad"
    state.cancel_create()
    assert not state.creating and state.new_name == ""


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (campaigns.InvalidCampaignName("El nombre admite hasta 60 caracteres."), None),
        (campaigns.UnknownPost("x"), cp.POST_GONE),
        (campaigns.UnknownCampaign("x"), cp.CAMPAIGN_GONE),
        (ValueError("badly formed hexadecimal UUID string"), cp.CAMPAIGN_GONE),
    ],
)
def test_error_messages_are_the_operators_words(exc: Exception, message: str | None) -> None:
    assert cp.error_message(exc) == (message if message is not None else str(exc))


def test_assigning_none_clears_and_an_id_assigns(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(campaigns, "set_post_campaign", lambda t, p, c: calls.append(c))
    monkeypatch.setattr(cp, "campaign_field", lambda t, p: cp.CampaignFieldVM())
    tenant, post, camp = uuid4(), uuid4(), uuid4()
    cp.assign_campaign(tenant, post, cp.NO_CAMPAIGN)
    cp.assign_campaign(tenant, post, str(camp))
    assert calls == [None, camp]


def test_the_colour_picker_offers_only_the_four_campaign_colours() -> None:
    assert (
        tuple(cp.COLOR_LABELS)
        == campaigns.CAMPAIGN_COLORS
        == (
            "violet",
            "pink",
            "blue",
            "orange",
        )
    )
    rendered = str(creative_pages._campaign_field())
    for key in cp.COLOR_LABELS:
        assert f"q-swatch q-tint-{key}" in rendered
    for state_color in ("teal", "green", "amber", "gray"):
        assert f"q-tint-{state_color}" not in rendered
    assert _js("Color de la campaña") in rendered
    assert _js("Cambia el color en todos los posts y publicaciones de esta campaña.") in rendered


def test_new_campaign_preselects_the_suggested_colour() -> None:
    state = CampaignState()
    state._apply(
        cp.CampaignFieldVM(options=[cp.CampaignOptionVM(id="c1", name="A", color="violet")])
    )
    state.start_create()
    assert state.new_color == "pink"  # the next one after one existing campaign
    state.set_new_color("orange")
    assert state.new_color == "orange"


def test_recolouring_goes_to_the_posts_current_campaign(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []
    camp = campaigns.CampaignView(id=uuid4(), name="A", color="violet")
    monkeypatch.setattr(
        campaigns,
        "choices_for_post",
        lambda t, p: campaigns.PostCampaignChoices(current=camp, options=[camp]),
    )
    monkeypatch.setattr(
        campaigns, "set_campaign_color", lambda t, c, color: calls.append((c, color))
    )
    monkeypatch.setattr(cp, "campaign_field", lambda t, p: cp.CampaignFieldVM())
    cp.recolor_post_campaign(uuid4(), uuid4(), "orange")
    assert calls == [(camp.id, "orange")]
    monkeypatch.setattr(
        campaigns,
        "choices_for_post",
        lambda t, p: campaigns.PostCampaignChoices(current=None, options=[]),
    )
    with pytest.raises(campaigns.UnknownCampaign):
        cp.recolor_post_campaign(uuid4(), uuid4(), "orange")
    assert cp.error_message(campaigns.InvalidCampaignColor("x")) == "x"

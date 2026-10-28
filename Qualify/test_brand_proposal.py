"""The proposed Brand Kit on «Tu marca» (m-24852199, PB-5): the literal copy, the card's
view of a proposal, what `enter` hands over, and what each button leaves in the wizard.
The decisions themselves (what is promoted, under RLS) are pinned in
`packages/api/tests/test_brand_prefill_review.py`."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
import reflex as rx
from qualify_api.creative import brand_prefill_review
from qualify_api.creative.brand_kit_store import PREFILL_KEY
from qualify_api.creative.brand_prefill_review import (
    Notice,
    PrefillDecision,
    PrefillReview,
    review_of,
)

from . import brand_minimal, brand_proposal
from . import brand_minimal_vm as minimal_vm
from . import brand_proposal_vm as vm
from . import creative_wizard_pages as wiz
from .brand_minimal import BrandMinimalState
from .brand_proposal import BrandProposalState
from .creative_state import CreativeState

IDS = (
    UUID("c0000000-0000-4000-8000-0000000000d1"),
    UUID("b0000000-0000-4000-8000-0000000000d1"),
    UUID("a0000000-0000-4000-8000-0000000000d1"),
)


def _proposal() -> dict[str, Any]:
    return {
        "connect": {
            "network": "instagram",
            "username": "heladeria.polar",
            "sector": "food_beverage",
            "rubro_text": "Heladería de yogur",
            "country_code": "CO",
            "city": "Cúcuta",
            "hashtags": [
                {"tag": "helados", "origin": "ai", "reason": "r", "model": "m"},
                {"tag": "#yogur", "origin": "catalog", "reason": "", "model": ""},
            ],
        },
        "profile": {
            "username": "heladeria.polar",
            "fullname": "Heladería Polar",
            "bio": "Helados de yogur",
            "category": "Heladería",
            "followers": "1.200",
            "followers_count": 1200,
            "pic": "https://scontent.cdninstagram.com/p.jpg",
            "metrics": [
                {"label": "Seguidores", "hint": "h", "suffix": "", "decimals": 0, "target": 1200}
            ],
        },
        "palette": {"palette": "#0f766e,#f8fafc", "logo_colors": ["#0f766e", "#f8fafc"]},
    }


def _connect(status: str = "ok", state: str = "proposed") -> dict[str, Any]:
    proposal = _proposal() if status == "ok" else None
    return {
        PREFILL_KEY: {
            "status": status,
            "state": state if proposal else "",
            "username": "heladeria.polar",
            "proposal": proposal,
            "provenance": {"source": {"kind": "alta", "meegle_work_item_id": 7}},
        }
    }


# --------------------------------------------------------------------------------------
# copy — literal, as approved (docs/epica-prellenado-brand-kit-alta.md §3 PB-5)
# --------------------------------------------------------------------------------------


def test_the_copy_is_the_approved_text() -> None:
    assert vm.notice_text(Notice.PROPOSAL, "@heladeria.polar") == (
        "Preparamos una propuesta de tu identidad de marca a partir de tu cuenta de "
        "Instagram @heladeria.polar. Revísala y apruébala para empezar a crear publicaciones."
    )
    assert (vm.APPROVE_LABEL, vm.CHANGE_LABEL, vm.DISCARD_LABEL) == (
        "Aprobar",
        "Cambiar",
        "Empezar de cero",
    )
    assert vm.APPROVED_NOTICE == "Listo. Guardamos tu identidad de marca."
    assert vm.notice_text(Notice.UNREADABLE, "x") == (
        "No pudimos leer tu cuenta de Instagram. Completa tu identidad de marca en unos pasos."
    )
    assert vm.notice_text(Notice.PRIVATE, "x") == (
        "Tu cuenta de Instagram es privada, así que no pudimos leerla. Completa tu "
        "identidad de marca en unos pasos."
    )
    assert vm.notice_text(Notice.NONE, "x") == "" and vm.notice_text("otro", "x") == ""


@pytest.mark.parametrize("notice", [Notice.PROPOSAL, Notice.PRIVATE, Notice.UNREADABLE])
def test_tiktok_and_unknown_accounts_never_receive_instagram_notices(notice: Notice) -> None:
    assert "TikTok" in vm.notice_text(notice, "cuenta", "tiktok")
    assert "Instagram" not in vm.notice_text(notice, "cuenta", "tiktok")
    assert "Instagram" not in vm.notice_text(notice, "cuenta", "")


def test_failed_read_retains_the_selected_network_in_the_notice() -> None:
    connect = _connect("private_account")
    connect[PREFILL_KEY]["network"] = "tiktok"
    state = BrandProposalState()
    state.show(review_of(connect, has_kit=False))
    assert state.network == "tiktok" and "TikTok" in state.notice_message
    proposal = _observed_proposal()
    proposal["connect"]["network"] = "tiktok"
    state.show(PrefillReview(Notice.PROPOSAL, "cuenta", proposal))
    assert state.review_title == "Esto es lo que vimos en tu TikTok"


def test_no_client_word_is_english_or_technical() -> None:
    words = " ".join(
        str(getattr(vm, name)) for name in dir(vm) if name.isupper() and not name.startswith("_")
    ).lower()
    for banned in ("brand kit", "post", "feed", "hashtag", "prompt", "error", "dashboard"):
        assert banned not in words


def test_the_backend_resume_flow_is_the_five_steps() -> None:
    assert brand_prefill_review.RESUME_FLOW == minimal_vm.MINIMAL_FLOW


# --------------------------------------------------------------------------------------
# the card
# --------------------------------------------------------------------------------------


def test_the_card_shows_what_was_read() -> None:
    view = vm.proposal_view(_proposal(), country_names={"CO": "Colombia"})
    assert view.username == "heladeria.polar" and view.fullname == "Heladería Polar"
    assert view.rubro == "Heladería de yogur"
    assert view.place == "Cúcuta, Colombia"
    assert view.colours == ["#0f766e", "#f8fafc"]
    assert view.tags == ["#helados", "#yogur"]


def test_without_a_named_rubro_the_category_is_shown() -> None:
    proposal = _proposal()
    proposal["connect"]["rubro_text"] = ""
    proposal["connect"]["city"] = ""
    proposal["palette"] = None
    view = vm.proposal_view(
        proposal, country_names={"CO": "Colombia"}, sector_labels={"food_beverage": "Comida"}
    )
    assert view.rubro == "Comida" and view.place == "Colombia" and view.colours == []
    assert vm.proposal_view(None, country_names={}) == vm.ProposalView()


def test_the_review_card_carries_the_three_buttons() -> None:
    rendered = str(brand_proposal.proposal_review())
    for label in ("Aprobar", "Cambiar", "Empezar de cero"):
        assert label in rendered


# --------------------------------------------------------------------------------------
# the state
# --------------------------------------------------------------------------------------


class _States:
    def __init__(self) -> None:
        self.instances: dict[type, Any] = {}

    def __call__(self, cls: type) -> Any:
        if cls not in self.instances:
            self.instances[cls] = cls()
        return self.instances[cls]


@pytest.fixture
def states(monkeypatch: pytest.MonkeyPatch) -> _States:
    holder = _States()

    async def get_state(_self: object, cls: type) -> Any:
        return holder(cls)

    for cls in (BrandProposalState, BrandMinimalState, wiz.BrandWizardState, wiz.BrandConnectState):
        monkeypatch.setattr(cls, "get_state", get_state)

    async def session_ids(_state: object) -> tuple[UUID, UUID, UUID]:
        return IDS

    from . import brand_finish

    monkeypatch.setattr(brand_finish, "session_ids", session_ids)
    return holder


def _pending(states: _States) -> BrandProposalState:
    state = states(BrandProposalState)
    state.show(review_of(_connect(), has_kit=False))
    return state


def test_a_pending_review_fills_the_card(states: _States) -> None:
    state = _pending(states)
    assert state.notice == "proposal" and state.username == "heladeria.polar"
    assert state.rubro == "Heladería de yogur" and state.place.startswith("Cúcuta")
    assert state.tags == ["#helados", "#yogur"]
    assert state._proposal["connect"]["city"] == "Cúcuta"


@pytest.mark.parametrize(
    ("status", "notice"),
    [("private_account", "private"), ("not_found", "unreadable"), ("account_taken", "unreadable")],
)
def test_a_failed_read_leaves_only_its_notice(states: _States, status: str, notice: str) -> None:
    state = states(BrandProposalState)
    state.show(review_of(_connect(status), has_kit=False))
    assert state.notice == notice and state._proposal == {} and state.rubro == ""


async def test_approve_promotes_then_opens_the_steps_with_the_proposal(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple] = []

    def approve(*ids: UUID) -> PrefillDecision:
        calls.append(ids)
        return PrefillDecision(True, _proposal())

    monkeypatch.setattr(brand_prefill_review, "approve_prefill", approve)
    state = _pending(states)
    events = [e async for e in BrandProposalState.approve.fn(state)]
    assert calls == [IDS]  # the session's own tenant, brand and user
    assert state.approved and state.notice == "" and state.busy == ""
    assert events and "enter" in str(events[-1])  # resumes on the first gap
    connect = states(wiz.BrandConnectState)
    assert connect.rubro_text == "Heladería de yogur" and connect.city == "Cúcuta"
    assert connect.profile_username == "heladeria.polar"
    assert [p["tag"] for p in connect.rubro_hashtags] == ["helados", "#yogur"]
    assert connect.metric_labels == ["Seguidores"]
    assert connect.logo_from_profile
    wizard = states(wiz.BrandWizardState)
    assert wizard.has_logo == wiz.HAS_LOGO_PROFILE and wizard.logo_colors == ["#0f766e", "#f8fafc"]
    assert states(CreativeState).kit_palette == "#0f766e,#f8fafc"


async def test_change_opens_tus_redes_prefilled(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        brand_prefill_review, "change_prefill", lambda *ids: PrefillDecision(True, _proposal())
    )
    minimal = states(BrandMinimalState)
    minimal.step = minimal_vm.STEP_VOICE
    state = _pending(states)
    _ = [e async for e in BrandProposalState.change.fn(state)]
    assert not state.approved and state.notice == ""
    assert minimal.step == minimal_vm.FIRST_STEP and minimal.entered
    assert states(wiz.BrandConnectState).profile_username == "heladeria.polar"


async def test_start_from_scratch_opens_tus_redes_empty(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        brand_prefill_review, "discard_prefill", lambda *ids: PrefillDecision(True, _proposal())
    )
    state = _pending(states)
    _ = [e async for e in BrandProposalState.discard.fn(state)]
    assert state.notice == ""
    connect = states(wiz.BrandConnectState)
    assert connect.profile_username == "" and connect.rubro_text == ""
    assert states(CreativeState).kit_palette == ""
    assert states(BrandMinimalState).step == minimal_vm.FIRST_STEP


async def test_a_decision_that_cannot_be_saved_keeps_the_card(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*ids: UUID) -> PrefillDecision:
        raise RuntimeError("database down")

    monkeypatch.setattr(brand_prefill_review, "approve_prefill", broken)
    state = _pending(states)
    events = [e async for e in BrandProposalState.approve.fn(state)]
    assert state.notice == "proposal" and state.busy == "" and not state.approved
    assert len(events) == 1 and events[0] is not None  # the toast
    assert states(wiz.BrandConnectState).rubro_text == ""


async def test_a_second_tap_while_saving_does_nothing(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        brand_prefill_review,
        "approve_prefill",
        lambda *ids: calls.append(ids) or PrefillDecision(True, _proposal()),
    )
    state = _pending(states)
    state.busy = "change"
    assert [e async for e in BrandProposalState.approve.fn(state)] == []
    assert calls == []


def test_the_entry_reads_the_review_for_an_unfinished_kit(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.creative import brand_kit_store

    from . import creative_provider

    class Store:
        def load_details(self, **_kw: Any) -> Any:
            return brand_kit_store.BrandKitDetails(connect=_connect())

        def list_assets(self, **_kw: Any) -> list:
            return []

    monkeypatch.setattr(brand_kit_store, "BrandKitStore", Store)
    monkeypatch.setattr(creative_provider, "default_brand_id", lambda _t: IDS[1])
    monkeypatch.setattr(creative_provider, "load_kit_form", lambda _t, _b: None)
    entry = brand_minimal._read_entry(IDS[0])
    assert entry is not None and entry.review.pending
    assert entry.review.username == "heladeria.polar"


@pytest.mark.parametrize(
    ("button", "name"),
    [
        (BrandProposalState.approve, "approve_prefill"),
        (BrandProposalState.change, "change_prefill"),
        (BrandProposalState.discard, "discard_prefill"),
    ],
)
async def test_a_proposal_decided_in_another_tab_reloads_before_any_step(
    states: _States, monkeypatch: pytest.MonkeyPatch, button: Any, name: str
) -> None:
    """Review of PB-5: tab A approved; tab B still shows the card and taps a button.
    The backend answers done=False; tab B must not mount the steps on its old (empty)
    wizard states — the save-as-you-go would write them over the approval. Its states
    are dropped (the save waits for the loads) and /brand's loads run again."""
    from . import brand_finish

    monkeypatch.setattr(brand_prefill_review, name, lambda *ids: PrefillDecision(False))
    state = _pending(states)
    creative = states(CreativeState)
    creative._kit_draft_loaded = True
    creative.kit_palette = ""  # tab B's view from before the approval
    wizard = states(wiz.BrandWizardState)
    wizard._assets_loaded = True
    connect = states(wiz.BrandConnectState)
    connect._details_loaded = True
    minimal = states(BrandMinimalState)
    minimal.entered = True
    minimal.step = minimal_vm.STEP_VOICE

    events = [e async for e in button.fn(state)]

    names = " ".join(str(e) for e in events)
    for load in ("load_brand", "load_saved_assets", "load_saved_details", "enter"):
        assert load in names, load
    assert state.notice == "" and not state.approved and state.busy == ""
    # the loading card is up (no step mounted) and the save-as-you-go would refuse
    assert minimal.entered is False
    assert creative._kit_draft_loaded is False
    assert wizard._assets_loaded is False
    assert connect._details_loaded is False
    assert connect.profile_username == "" and creative.kit_palette == ""

    # and the save-as-you-go indeed writes nothing until the loads are back
    persisted: list[Any] = []
    monkeypatch.setattr(brand_finish, "persist_brand_kit", lambda *a, **k: persisted.append(a))
    holder = states

    async def _get_state(_self: object, cls: type) -> Any:
        return holder(cls)

    monkeypatch.setattr(CreativeState, "get_state", _get_state)
    await brand_finish.save_progress(minimal, brand_finish.MINIMAL_FLOW)
    assert persisted == []


def test_the_colour_group_says_how_many_never_the_codes() -> None:
    assert vm.colours_label(3) == "Tus colores: 3 colores"
    assert vm.colours_label(1) == "Tus colores: 1 color"
    rendered = str(brand_proposal._colours())
    assert "aria-hidden" in rendered or "ariaHidden" in rendered


def test_an_owner_who_already_started_sees_no_proposal(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.creative import brand_kit_store

    from . import creative_provider

    class Store:
        def load_details(self, **_kw: Any) -> Any:
            return brand_kit_store.BrandKitDetails(
                connect={**_connect(), "rubro_text": "Lo que escribí"}
            )

        def list_assets(self, **_kw: Any) -> list:
            return []

    monkeypatch.setattr(brand_kit_store, "BrandKitStore", Store)
    monkeypatch.setattr(creative_provider, "default_brand_id", lambda _t: IDS[1])
    monkeypatch.setattr(creative_provider, "load_kit_form", lambda _t, _b: None)
    entry = brand_minimal._read_entry(IDS[0])
    assert entry is not None and not entry.review.pending


def test_the_page_swaps_the_steps_for_the_review_while_pending() -> None:
    page = str(brand_minimal.brand_minimal_index())
    assert "review_title" in page and "Empezar de cero" in page
    assert isinstance(brand_minimal.brand_minimal_index(), rx.Component)


# --------------------------------------------------------------------------------------
# m-24852537: the card shows the R2 copy of the picture, never the expiring CDN link
# --------------------------------------------------------------------------------------


def _kept_connect() -> dict[str, Any]:
    from qualify_api.creative import kept_pictures

    connect = _connect()
    key = kept_pictures.kept_key(IDS[0], IDS[1], kept_pictures.KIND_PROFILE, b"p", ".jpg")
    connect[PREFILL_KEY]["proposal"]["profile"] |= {
        "pic": "",
        "pic_key": key,
        "pic_content_type": "image/jpeg",
    }
    return connect


def test_the_card_shows_the_picture_kept_in_r2(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued: list[tuple[Any, ...]] = []

    def issue(tenant_id: UUID, key: str, media_type: str, content_type: str) -> str:
        issued.append((tenant_id, key, media_type, content_type))
        return "/r2media/tok"

    monkeypatch.setattr(brand_proposal, "issue_view_path", issue)
    state = states(BrandProposalState)
    state.show(review_of(_kept_connect(), has_kit=False))
    assert state.pic_view == "/r2media/tok" and state.avatar_src == "/r2media/tok"
    [(tenant, key, media_type, content_type)] = issued
    assert tenant == IDS[0] and key.startswith(f"t/{IDS[0]}/brand/{IDS[1]}/kept/profile/")
    assert (media_type, content_type) == ("image", "image/jpeg")


def test_a_view_that_cannot_be_issued_leaves_the_card_without_picture(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(*_a: Any) -> str:
        raise ConnectionError("redis down")

    monkeypatch.setattr(brand_proposal, "issue_view_path", down)
    state = states(BrandProposalState)
    state.show(review_of(_kept_connect(), has_kit=False))
    assert state.pic_view == "" and state.notice == "proposal"


def test_a_proposal_without_a_copy_issues_no_view(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(brand_proposal, "issue_view_path", lambda *_a: pytest.fail("issued"))
    state = _pending(states)
    assert state.pic_view == ""


async def test_approve_hands_the_kept_picture_to_the_wizard(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    from . import brand_finish

    kept = _kept_connect()[PREFILL_KEY]["proposal"]
    monkeypatch.setattr(brand_proposal, "issue_view_path", lambda *_a: "/r2media/tok")
    monkeypatch.setattr(
        brand_prefill_review, "approve_prefill", lambda *_ids: PrefillDecision(True, kept)
    )
    state = states(BrandProposalState)
    state.show(review_of(_kept_connect(), has_kit=False))
    _ = [e async for e in BrandProposalState.approve.fn(state)]
    connect = states(wiz.BrandConnectState)
    assert connect.profile_pic_key == kept["profile"]["pic_key"]
    assert connect.profile_pic_view == "/r2media/tok"
    assert connect.profile_avatar_src == "/r2media/tok"
    # the wizard's next save keeps the copy in the profile document
    saved = brand_finish._profile_document(connect)
    assert saved is not None and saved["pic_key"] == kept["profile"]["pic_key"]
    assert saved["pic_content_type"] == "image/jpeg" and saved["pic"] == ""


def test_the_wizard_shows_the_kept_copy_before_the_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.creative import kept_pictures

    issued: list[UUID] = []

    def issue(tenant_id: UUID, key: str, media_type: str, content_type: str) -> str:
        issued.append(tenant_id)
        return "/r2media/own"

    monkeypatch.setattr(wiz, "issue_view_path", issue)
    tenant, brand, _user = IDS
    own = kept_pictures.kept_key(tenant, brand, kept_pictures.KIND_PROFILE, b"p", ".jpg")
    other_tenant = UUID("c0000000-0000-4000-8000-0000000000ee")
    theirs = kept_pictures.kept_key(other_tenant, brand, kept_pictures.KIND_PROFILE, b"p", ".jpg")

    connect = wiz.BrandConnectState()
    connect.network, connect.profile_username = "instagram", "heladeria.polar"
    proxy = connect.profile_avatar_src
    assert proxy and "r2media" not in proxy

    connect.keep_picture_of(tenant, brand, {"pic_key": theirs})  # never another tenant's
    assert connect.profile_pic_key == "" and issued == []
    assert connect.profile_avatar_src == proxy

    connect.keep_picture_of(tenant, brand, {"pic_key": own, "pic_content_type": "image/jpeg"})
    assert issued == [tenant] and connect.profile_pic_key == own
    assert connect.profile_avatar_src == "/r2media/own"

    connect.forget_kept_picture()
    assert connect.profile_avatar_src == proxy


def _observed_proposal() -> dict[str, Any]:
    from qualify_api.creative import kept_pictures

    proposal = _proposal()
    own = kept_pictures.kept_key(IDS[0], IDS[1], kept_pictures.KIND_POST, b"post", ".jpg")
    proposal["observed"] = {
        "posts_count": 12,
        "category_es": "Heladería",
        "posted_last_30d": True,
        "posts_per_week": 2.5,
        "top_media_ids": ["p1"],
        "top_hashtags": ["helados"],
        "links": [{"kind": "whatsapp", "url": "https://wa.me/573001234567"}],
        "recent_media": [
            {
                "id": "p1",
                "is_owner": True,
                "likes": 12,
                "caption": "Pide al +57 300 123 4567",
                "thumb_r2_key": own,
                "thumb_content_type": "image/jpeg",
            }
        ],
    }
    proposal["profile"]["bio"] = "Helados. Pide al +57 300 123 4567"
    return proposal


def test_observed_vm_masks_contacts_before_the_browser_and_hides_unknown_numbers() -> None:
    proposal = _observed_proposal()
    view = vm.proposal_view(proposal, country_names={"CO": "Colombia"})
    assert view.category == "Heladería" and view.posts == "12"
    assert view.frequency == "Publicas unas 2.5 veces por semana."
    assert view.media[0]["top"] == "La que más gustó"
    assert view.links[0]["href"] == ""
    assert "3001234567" not in str(view) and "300 123 4567" not in str(view)
    proposal["profile"]["followers_count"] = 0
    proposal["observed"] |= {"posts_count": 0, "posted_last_30d": False}
    view = vm.proposal_view(proposal, country_names={})
    assert view.posts == view.followers == view.frequency == ""
    assert view.no_posts
    assert view.media == []


def test_untranslated_categories_and_unsafe_links_are_hidden() -> None:
    proposal = _observed_proposal()
    proposal["observed"]["category_es"] = None
    proposal["observed"]["links"] = [
        {"url": "javascript:alert(1)"},
        {"url": "https://example.com/contact/573001234567"},
        {"url": "https://example.com/menu", "title": "Menú"},
    ]
    view = vm.proposal_view(proposal, country_names={})
    assert view.category == ""
    assert view.links == [{"title": "Menú", "text": "", "href": "https://example.com/menu"}]


def test_only_own_thumbnail_keys_receive_views_and_public_state_is_masked(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_api.creative import kept_pictures

    proposal = _observed_proposal()
    foreign = kept_pictures.kept_key(UUID(int=44), IDS[1], kept_pictures.KIND_POST, b"f", ".jpg")
    proposal["observed"]["recent_media"].append({"id": "foreign", "thumb_r2_key": foreign})
    issued = []
    monkeypatch.setattr(
        brand_proposal, "issue_view_path", lambda *args: issued.append(args) or "/r2media/thumb"
    )
    state = states(BrandProposalState)
    state.show(PrefillReview(Notice.PROPOSAL, "heladeria.polar", proposal), owner=IDS[:2])
    assert len(state.media) == len(issued) == 1
    assert state.media[0]["src"] == "/r2media/thumb"
    assert isinstance(state.media[0]["src"], str)
    assert state.review_title == vm.OBSERVED_TITLE
    public = str(state.dict())
    assert "3001234567" not in public and "300 123 4567" not in public
    assert "thumb_r2_key" not in public


def test_corrected_sources_and_rejected_logo_are_shown_as_owner_choices() -> None:
    proposal = _observed_proposal()
    proposal["corrected_fields"] = ["city", "rubro_text", "country_code"]
    proposal["profile"]["use_profile_logo"] = False
    proposal["palette"] = {"logo_colors": ["#112233"], "logo_source": "owner"}
    view = vm.proposal_view(proposal, country_names={"CO": "Colombia"})
    assert view.rubro_source == view.place_source == view.country_source == vm.OWNER_SOURCE
    assert view.colours_source == vm.OWNER_SOURCE
    assert not view.logo
    state = BrandProposalState()
    state.show(PrefillReview(Notice.PROPOSAL, "heladeria.polar", proposal))
    assert state.logo_label == vm.LOGO_UNSET_LABEL


async def test_a_correction_changes_only_the_pending_proposal(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _pending(states)
    state.open_correction("rubro_text")
    assert state.edit_open and state.edit_value == "Heladería de yogur"
    state.set_edit_value("Helados artesanales")
    calls = []

    def edit(tenant: UUID, brand: UUID, field: str, value: Any, **kwargs: Any) -> PrefillDecision:
        calls.append((tenant, brand, field, value, kwargs))
        proposal = _proposal()
        proposal["connect"]["rubro_text"] = value
        return PrefillDecision(True, proposal)

    monkeypatch.setattr(brand_prefill_review, "edit_prefill_field", edit)
    _ = [event async for event in BrandProposalState.save_correction.fn(state)]
    assert calls == [(IDS[0], IDS[1], "rubro_text", "Helados artesanales", {"user_id": IDS[2]})]
    assert state.pending and not state.approved and not state.edit_open
    assert state.rubro == "Helados artesanales"
    assert states(wiz.BrandConnectState).rubro_text == ""


def test_cancelling_or_unknown_correction_never_changes_the_proposal(states: _States) -> None:
    state = _pending(states)
    state.open_correction("rubro_text")
    state.set_edit_value("No guardar")
    state.close_correction(False)
    assert state.rubro == "Heladería de yogur" and not state.edit_open
    state.open_correction("prefill")
    assert not state.edit_open


async def test_invalid_correction_keeps_the_drawer_and_user_input(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _pending(states)
    state.open_correction("colors")
    state.set_edit_value("not a color")

    def invalid(*_args: Any, **_kwargs: Any) -> PrefillDecision:
        raise ValueError("invalid")

    monkeypatch.setattr(brand_prefill_review, "edit_prefill_field", invalid)
    _ = [event async for event in BrandProposalState.save_correction.fn(state)]
    assert state.edit_open and state.edit_error == vm.EDIT_INVALID
    assert state.edit_value == "not a color" and not state.busy


async def test_rejecting_profile_logo_never_reattaches_its_deleted_key_after_approval(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposal = _kept_connect()[PREFILL_KEY]["proposal"]
    proposal["profile"]["use_profile_logo"] = False
    proposal["palette"] = {"logo_colors": ["#112233"], "logo_source": "owner"}
    state = states(BrandProposalState)
    state.show(PrefillReview(Notice.PROPOSAL, "heladeria.polar", proposal))
    monkeypatch.setattr(
        brand_prefill_review, "approve_prefill", lambda *_ids: PrefillDecision(True, proposal)
    )
    _ = [e async for e in BrandProposalState.approve.fn(state)]
    connect = states(wiz.BrandConnectState)
    wizard = states(wiz.BrandWizardState)
    assert connect.profile_pic_key == connect.profile_pic_view == connect.profile_pic == ""
    assert not connect.logo_from_profile and not connect.profile_pic_is_real
    assert wizard.has_logo == wizard.logo_source == "" and wizard.logo_colors == []
    assert states(CreativeState).kit_palette == "#112233"


async def test_owner_palette_does_not_become_colours_contributed_by_the_profile_logo(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposal = _proposal()
    proposal["palette"] = {"logo_colors": ["#112233"], "logo_source": "owner"}
    state = _pending(states)
    monkeypatch.setattr(
        brand_prefill_review, "approve_prefill", lambda *_ids: PrefillDecision(True, proposal)
    )
    _ = [e async for e in BrandProposalState.approve.fn(state)]
    wizard = states(wiz.BrandWizardState)
    assert wizard.has_logo == wiz.HAS_LOGO_PROFILE
    assert wizard.logo_colors == [] and wizard.logo_source == ""
    assert states(CreativeState).kit_palette == "#112233"


async def test_approval_masks_legacy_profile_text_before_wizard_state(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposal = _observed_proposal()
    state = _pending(states)
    monkeypatch.setattr(
        brand_prefill_review, "approve_prefill", lambda *_ids: PrefillDecision(True, proposal)
    )
    _ = [e async for e in BrandProposalState.approve.fn(state)]
    connect = states(wiz.BrandConnectState)
    assert "300 123 4567" not in connect.profile_bio
    assert "••" in connect.profile_bio

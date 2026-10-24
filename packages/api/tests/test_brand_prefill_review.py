"""`brand_prefill_review` (m-24852199, PB-5): the owner approves, changes or discards the
Brand Kit proposed from their account.

Offline: the pure rules (what is pending, which notice each run outcome shows, what
«Aprobar» writes) and the three buttons over a recording fake session — that every
database door is the caller's own tenant, that nothing is promoted before «Aprobar»,
that a decided proposal is never decided twice. The real rows under RLS are the `db`
tests at the bottom."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from qualify_api.creative import brand_prefill, brand_prefill_review
from qualify_api.creative.brand_context import build_context
from qualify_api.creative.brand_kit_store import PREFILL_KEY, BrandKitDetails
from qualify_api.creative.brand_prefill_review import (
    Notice,
    approve_prefill,
    change_prefill,
    discard_prefill,
    review_of,
)
from qualify_api.creative.models import BrandKit as BrandKitRow

TENANT = UUID("c0000000-0000-4000-8000-0000000000c5")
BRAND = UUID("b0000000-0000-4000-8000-0000000000c5")
USER = UUID("a0000000-0000-4000-8000-0000000000c5")
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def _proposal(*, palette: bool = True) -> dict[str, Any]:
    return {
        "connect": {
            "network": "instagram",
            "username": "heladeria.polar",
            "sector": "food_beverage",
            "rubro_text": "Heladería de yogur",
            "country_code": "CO",
            "city": "Cúcuta",
            "hashtags": [{"tag": "helados", "origin": "ai", "reason": "r", "model": "m"}],
        },
        "profile": {
            "username": "heladeria.polar",
            "fullname": "Heladería Polar",
            "bio": "Helados de yogur hechos aquí",
            "category": "Heladería",
            "followers": "1.200",
            "followers_count": 1200,
            "pic": "https://scontent.cdninstagram.com/p.jpg",
            "metrics": [],
        },
        "palette": (
            {
                "palette": "#0f766e,#f8fafc",
                "logo_colors": ["#0f766e", "#f8fafc"],
                "logo_source": "profile",
            }
            if palette
            else None
        ),
    }


def _document(status: str = "ok", state: str = "proposed", **kw: Any) -> dict[str, Any]:
    proposal = kw.pop("proposal", _proposal() if status == "ok" else None)
    return {
        "version": 1,
        "status": status,
        "state": state if proposal is not None else "",
        "network": "instagram",
        "username": "heladeria.polar",
        "proposal": proposal,
        "usage": {"scrapecreators_credits": 2},
        "provenance": {"source": {"kind": "alta", "meegle_work_item_id": 42}},
        **kw,
    }


# --------------------------------------------------------------------------------------
# what is pending, and which notice each outcome shows
# --------------------------------------------------------------------------------------


def test_an_ok_proposal_still_proposed_is_pending() -> None:
    review = review_of({PREFILL_KEY: _document()}, has_kit=False)
    assert review.pending and review.notice is Notice.PROPOSAL
    assert review.username == "heladeria.polar"
    assert review.proposal["connect"]["rubro_text"] == "Heladería de yogur"


@pytest.mark.parametrize("state", ["approved", "changed", "discarded"])
def test_a_decided_proposal_is_not_pending_and_shows_nothing(state: str) -> None:
    review = review_of({PREFILL_KEY: _document(state=state)}, has_kit=False)
    assert review.notice is Notice.NONE and not review.pending


def test_a_finished_kit_shows_nothing() -> None:
    assert review_of({PREFILL_KEY: _document()}, has_kit=True).notice is Notice.NONE
    finished = {PREFILL_KEY: _document(), "progress": {"completed": True}}
    assert review_of(finished, has_kit=True).notice is Notice.NONE
    # a kit row left halfway is not finished: the proposal still shows
    halfway = {PREFILL_KEY: _document(), "progress": {"completed": False}}
    assert review_of(halfway, has_kit=True).pending


def test_a_private_account_has_its_own_notice() -> None:
    review = review_of({PREFILL_KEY: _document("private_account")}, has_kit=False)
    assert review.notice is Notice.PRIVATE and not review.pending


@pytest.mark.parametrize("status", ["not_found", "read_failed", "cap_reached", "account_taken"])
def test_every_other_failed_run_says_the_account_could_not_be_read(status: str) -> None:
    review = review_of({PREFILL_KEY: _document(status)}, has_kit=False)
    assert review.notice is Notice.UNREADABLE


def test_every_outcome_of_a_run_has_a_notice() -> None:
    for outcome in brand_prefill.PrefillOutcome:
        notice = review_of({PREFILL_KEY: _document(outcome.value)}, has_kit=False).notice
        assert notice is not Notice.NONE, outcome


def test_no_document_or_a_broken_one_shows_nothing() -> None:
    assert review_of(None, has_kit=False).notice is Notice.NONE
    assert review_of({"city": "Cali"}, has_kit=False).notice is Notice.NONE
    assert review_of({PREFILL_KEY: "x"}, has_kit=False).notice is Notice.NONE
    broken = _document(proposal={"connect": "x", "profile": {}})
    assert review_of({PREFILL_KEY: broken}, has_kit=False).notice is Notice.NONE


def test_the_review_state_names_match_the_pipelines() -> None:
    assert brand_prefill_review.STATE_PROPOSED == brand_prefill.STATE_PROPOSED


# --------------------------------------------------------------------------------------
# nothing reaches generation before «Aprobar»
# --------------------------------------------------------------------------------------


def test_generation_ignores_an_unapproved_proposal() -> None:
    details = BrandKitDetails(connect={PREFILL_KEY: _document()}, profile={})
    assert build_context(details, [], []) is None


def test_generation_reads_the_proposal_once_approved() -> None:
    connect = {PREFILL_KEY: _document()}
    proposal = review_of(connect, has_kit=False).proposal
    approved = brand_prefill_review.approved_connect(connect, proposal, USER, NOW)
    context = build_context(BrandKitDetails(connect=approved, profile=proposal["profile"]), [], [])
    assert context is not None
    assert context.sector == "Heladería de yogur"
    assert context.hashtags == ("helados",)
    assert context.account_bio == "Helados de yogur hechos aquí"


def test_approving_keeps_the_owners_other_answers_and_the_provenance() -> None:
    connect = {PREFILL_KEY: _document(), "voice_configured": True, "account_kind": "marca"}
    proposal = review_of(connect, has_kit=False).proposal
    out = brand_prefill_review.approved_connect(connect, proposal, USER, NOW)
    assert out["voice_configured"] is True and out["account_kind"] == "marca"
    assert out["city"] == "Cúcuta" and out["network"] == "instagram"
    decided = out[PREFILL_KEY]
    assert decided["state"] == "approved" and decided["reviewed_by"] == str(USER)
    assert decided["reviewed_at"] == NOW.isoformat()
    assert decided["provenance"] == connect[PREFILL_KEY]["provenance"]
    assert decided["proposal"] == connect[PREFILL_KEY]["proposal"]
    # unfinished, in the five steps, with the picture as the logo
    assert out["progress"] == {
        "flow": "minimo",
        "completed": False,
        "logo_from_profile": True,
        "profile_pic_is_real": True,
    }


def test_a_proposal_without_colours_does_not_take_the_picture_as_logo() -> None:
    connect = {PREFILL_KEY: _document(proposal=_proposal(palette=False))}
    proposal = review_of(connect, has_kit=False).proposal
    out = brand_prefill_review.approved_connect(connect, proposal, USER, NOW)
    assert "logo_from_profile" not in out["progress"]
    assert brand_prefill_review.palette_colours(proposal) == []


def test_the_colours_join_the_palette_without_duplicates() -> None:
    merged = brand_prefill_review.merged_palette(["#111111", "#0F766E"], ["#0f766e", "#f8fafc"])
    assert merged == ["#111111", "#0F766E", "#f8fafc"]
    assert brand_prefill_review.merged_palette(None, ["#0f766e"]) == ["#0f766e"]


# --------------------------------------------------------------------------------------
# the three buttons over a fake session
# --------------------------------------------------------------------------------------


class FakeSession:
    def __init__(self, world: World) -> None:
        self.world = world

    def get(self, model: Any, key: UUID, with_for_update: bool = False) -> Any:
        self.world.locked.append(with_for_update)
        return self.world.details.get(key)

    def scalar(self, statement: Any) -> Any:
        if "brand_kit_assets" in str(statement):
            return self.world.asset
        return self.world.kit

    def add(self, obj: Any) -> None:
        self.world.added.append(obj)
        if isinstance(obj, BrandKitRow):
            self.world.kit = obj

    def flush(self) -> None:
        self.world.flushes += 1


class World:
    def __init__(self, connect: dict[str, Any] | None = None, kit: Any = None) -> None:
        row = SimpleNamespace(
            connect=connect if connect is not None else {PREFILL_KEY: _document()},
            profile={},
            logo_brief={},
            updated_by=None,
            updated_at=None,
        )
        self.details: dict[UUID, Any] = {BRAND: row}
        self.kit = kit
        #: A brandboard file of the owner's (any value) or None.
        self.asset: Any = None
        self.added: list[Any] = []
        self.tenants: list[UUID] = []
        self.locked: list[bool] = []
        self.flushes = 0

    @property
    def row(self) -> Any:
        return self.details[BRAND]

    @contextmanager
    def session(self, tenant_id: UUID) -> Iterator[FakeSession]:
        self.tenants.append(tenant_id)
        yield FakeSession(self)


def test_approve_promotes_the_proposal_and_creates_the_kits_colours() -> None:
    world = World()
    decision = approve_prefill(TENANT, BRAND, USER, session_factory=world.session)
    assert decision.done
    assert world.row.connect["rubro_text"] == "Heladería de yogur"
    assert world.row.connect[PREFILL_KEY]["state"] == "approved"
    assert world.row.profile["username"] == "heladeria.polar"
    assert world.row.updated_by == USER
    kit = world.kit
    assert isinstance(kit, BrandKitRow)
    assert kit.tenant_id == TENANT and kit.brand_id == BRAND
    assert kit.palette_rgb == ["#0f766e", "#f8fafc"]
    assert kit.positioning == "" and kit.tone_axes["formal_casual"] == 50
    assert world.locked == [True]


def test_approve_fills_the_empty_kit_the_wizard_saved_first() -> None:
    """Tus redes shown once saves an empty, unfinished kit row: approving fills its
    colours and keeps the rest of it (the tone) as it was."""
    kit = BrandKitRow(tenant_id=TENANT, brand_id=BRAND, language="es")
    kit.positioning, kit.audience = "", ""
    kit.tone_axes = {
        "formal_casual": 70,
        "sober_enthusiastic": 60,
        "technical_plain": 80,
        "brief_elaborate": 40,
    }
    kit.palette_rgb = []
    world = World({PREFILL_KEY: _document(), "progress": {"completed": False}}, kit=kit)
    assert approve_prefill(TENANT, BRAND, USER, session_factory=world.session).done
    assert world.kit is kit and not world.added
    assert kit.palette_rgb == ["#0f766e", "#f8fafc"]
    assert kit.tone_axes["formal_casual"] == 70


@pytest.mark.parametrize("button", [change_prefill, discard_prefill])
def test_change_and_discard_promote_nothing(button: Any) -> None:
    world = World()
    before = dict(world.row.connect[PREFILL_KEY])
    decision = button(TENANT, BRAND, USER, session_factory=world.session)
    assert decision.done and decision.proposal["connect"]["username"] == "heladeria.polar"
    connect = world.row.connect
    assert set(connect) == {PREFILL_KEY}  # no top-level answer, no progress
    assert world.row.profile == {} and world.kit is None and not world.added
    decided = connect[PREFILL_KEY]
    expected = "changed" if button is change_prefill else "discarded"
    assert decided["state"] == expected
    assert decided["proposal"] == before["proposal"]
    assert decided["provenance"] == before["provenance"]


@pytest.mark.parametrize("button", [approve_prefill, change_prefill, discard_prefill])
def test_a_decided_proposal_is_never_decided_twice(button: Any) -> None:
    world = World()
    assert button(TENANT, BRAND, USER, session_factory=world.session).done
    snapshot = (dict(world.row.connect), dict(world.row.profile), world.flushes)
    for again in (approve_prefill, change_prefill, discard_prefill):
        assert not again(TENANT, BRAND, USER, session_factory=world.session).done
    assert (dict(world.row.connect), dict(world.row.profile), world.flushes) == snapshot


def test_nothing_to_decide_without_a_row_or_on_a_finished_kit() -> None:
    world = World()
    world.details = {}
    assert not approve_prefill(TENANT, BRAND, USER, session_factory=world.session).done
    finished = World(kit=BrandKitRow(tenant_id=TENANT, brand_id=BRAND, language="es"))
    assert not approve_prefill(TENANT, BRAND, USER, session_factory=finished.session).done
    failed = World({PREFILL_KEY: _document("private_account")})
    assert not approve_prefill(TENANT, BRAND, USER, session_factory=failed.session).done


# tenant isolation (offline): every door is the caller's own tenant


@pytest.mark.parametrize("button", [approve_prefill, change_prefill, discard_prefill])
def test_every_database_door_is_the_callers_tenant(button: Any) -> None:
    world = World()
    button(TENANT, BRAND, USER, session_factory=world.session)
    assert world.tenants == [TENANT]


def test_the_module_reaches_the_database_only_through_tenant_scoped_doors() -> None:
    source = Path(brand_prefill_review.__file__).read_text(encoding="utf-8")
    for forbidden in ("admin_session", "credential_session", "create_engine", "sessionmaker"):
        assert forbidden not in source
    assert approve_prefill.__kwdefaults__["session_factory"].__name__ == "tenant_session"


# --------------------------------------------------------------------------------------
# the owner's own answers come first (review of PB-5)
# --------------------------------------------------------------------------------------


def test_an_empty_draft_is_not_a_start() -> None:
    empty_save = {
        "network": "",
        "username": "",
        "sector": "",
        "rubro_text": "",
        "country_code": "CO",  # prefilled from the signup's country, not typed
        "city": "",
        "hashtags": [],
        "account_kind": "",
        "has_maps": "",
        "voice_configured": False,
        "progress": {"flow": "minimo", "step": "redes", "completed": False},
    }
    assert not brand_prefill_review.owner_started(
        empty_save, {}, {"brand_avatar": {"x": 1}}, kit_answers=["", "", "", ""]
    )


@pytest.mark.parametrize(
    "kw",
    [
        {"connect": {"rubro_text": "Heladería"}},
        {"connect": {"city": "Cali"}},
        {"connect": {"hashtags": [{"tag": "x"}]}},
        {"connect": {"progress": {"started_without_socials": True}}},
        {"connect": {"progress": {"logo_from_profile": True}}},
        {"profile": {"username": "mi.cuenta"}},
        {"logo_brief": {"style": "moderno"}},
        {"kit_answers": ["Lo hacemos al momento"]},
        {"kit_answers": ["", "", "#111111"]},
        {"has_files": True},
    ],
)
def test_any_answer_of_the_owner_is_a_start(kw: dict[str, Any]) -> None:
    assert brand_prefill_review.owner_started(
        kw.get("connect"),
        kw.get("profile"),
        kw.get("logo_brief"),
        kit_answers=kw.get("kit_answers", ()),
        has_files=kw.get("has_files", False),
    )


def test_a_proposal_is_not_offered_over_the_owners_answers() -> None:
    connect = {PREFILL_KEY: _document(), "rubro_text": "Lo que escribí"}
    assert review_of(connect, has_kit=False, started=True).notice is Notice.NONE
    assert review_of(connect, has_kit=False, started=False).pending


@pytest.mark.parametrize("button", [approve_prefill, change_prefill, discard_prefill])
def test_an_owner_who_already_started_supersedes_the_proposal(button: Any) -> None:
    """Re-checked under the lock: the owner typed while the card was open (or before
    the proposal landed) — nothing is promoted, the proposal is kept as superseded."""
    world = World({PREFILL_KEY: _document(), "rubro_text": "Lo que escribí", "city": "Cali"})
    world.row.profile = {}
    decision = button(TENANT, BRAND, USER, session_factory=world.session)
    assert not decision.done and decision.proposal == {}
    connect = world.row.connect
    assert connect["rubro_text"] == "Lo que escribí" and connect["city"] == "Cali"
    assert "progress" not in connect and world.kit is None and not world.added
    assert connect[PREFILL_KEY]["state"] == "superseded"
    assert connect[PREFILL_KEY]["provenance"] == _document()["provenance"]
    assert brand_prefill_review.is_decided(connect[PREFILL_KEY])


def test_an_uploaded_logo_supersedes_the_proposal() -> None:
    world = World()
    world.asset = BRAND  # a file of the owner's brandboard
    assert not approve_prefill(TENANT, BRAND, USER, session_factory=world.session).done
    assert world.row.connect[PREFILL_KEY]["state"] == "superseded"
    assert world.row.profile == {} and world.kit is None


def test_decided_states_are_the_ones_a_rerun_keeps() -> None:
    assert brand_prefill_review.DECIDED_STATES == {"approved", "changed", "discarded", "superseded"}
    assert not brand_prefill_review.is_decided({"state": "proposed"})
    assert not brand_prefill_review.is_decided({"state": ""})
    assert not brand_prefill_review.is_decided(None)


# --------------------------------------------------------------------------------------
# db: the real rows under RLS — two tenants of this file's own, a fresh brand each run
# --------------------------------------------------------------------------------------

DB_TENANT_A = UUID("c0000000-0000-4000-8000-0000000000e1")
DB_TENANT_B = UUID("d0000000-0000-4000-8000-0000000000e2")


@pytest.fixture
def fresh_brands() -> tuple[tuple[UUID, UUID], tuple[UUID, UUID]]:
    """((tenant A, its new brand), (tenant B, its new brand)): nothing another test
    wrote can make the owner look started."""
    from uuid import uuid4

    from qualify_shared.db.admin import admin_session

    from qualify_api.tenancy.models import Brand, Tenant

    out = []
    with admin_session() as session:
        for tenant_id, name in ((DB_TENANT_A, "A"), (DB_TENANT_B, "B")):
            if session.get(Tenant, tenant_id) is None:
                session.add(
                    Tenant(
                        id=tenant_id,
                        name=f"prefill-review-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
            brand = Brand(tenant_id=tenant_id, name=f"prefill-review-{uuid4()}")
            session.add(brand)
            session.flush()
            out.append((tenant_id, brand.id))
    return out[0], out[1]


def _propose(store: Any, tenant: UUID, brand: UUID) -> None:
    store.set_document_key(
        tenant_id=tenant, brand_id=brand, document="connect", key=PREFILL_KEY, value=_document()
    )


@pytest.mark.db
def test_approving_writes_only_the_own_tenants_brand_kit(fresh_brands: Any) -> None:
    from qualify_shared.db.session import tenant_session

    from qualify_api.creative.brand_kit_store import BrandKitStore
    from qualify_api.creative.brand_service import BrandKitService
    from qualify_api.creative.models import BrandKitDetails as DetailsRow

    (tenant_a, brand_a), (tenant_b, brand_b) = fresh_brands
    store = BrandKitStore()
    _propose(store, tenant_a, brand_a)
    _propose(store, tenant_b, brand_b)

    # tenant B's session cannot see, let alone approve, tenant A's proposal
    assert not approve_prefill(tenant_b, brand_a, None).done
    with tenant_session(tenant_b) as session:
        assert session.get(DetailsRow, brand_a) is None
    assert (
        store.load_details(tenant_id=tenant_a, brand_id=brand_a).connect[PREFILL_KEY]["state"]
        == "proposed"
    )

    assert approve_prefill(tenant_a, brand_a, None).done
    mine = store.load_details(tenant_id=tenant_a, brand_id=brand_a)
    assert mine.connect["rubro_text"] == "Heladería de yogur"
    assert mine.connect[PREFILL_KEY]["state"] == "approved"
    assert mine.profile["username"] == "heladeria.polar"
    kit = BrandKitService().get_kit(tenant_id=tenant_a, brand_id=brand_a)
    assert kit is not None and kit.palette_rgb == ("#0f766e", "#f8fafc")

    # tenant B's proposal still waits, nothing promoted there
    theirs = store.load_details(tenant_id=tenant_b, brand_id=brand_b)
    assert theirs.connect == {PREFILL_KEY: _document()} and theirs.profile == {}
    assert BrandKitService().get_kit(tenant_id=tenant_b, brand_id=brand_b) is None


@pytest.mark.db
def test_discarding_in_postgres_keeps_the_proposal_and_promotes_nothing(
    fresh_brands: Any,
) -> None:
    from qualify_api.creative.brand_kit_store import BrandKitStore

    (tenant, brand), _other = fresh_brands
    store = BrandKitStore()
    _propose(store, tenant, brand)
    assert discard_prefill(tenant, brand, None).done
    saved = store.load_details(tenant_id=tenant, brand_id=brand)
    assert set(saved.connect) == {PREFILL_KEY} and saved.profile == {}
    assert saved.connect[PREFILL_KEY]["state"] == "discarded"
    assert saved.connect[PREFILL_KEY]["proposal"] is not None
    assert build_context(saved, [], []) is None


@pytest.mark.db
def test_a_second_tab_cannot_undo_an_approval_in_postgres(fresh_brands: Any) -> None:
    """Tab A approves; tab B, still showing the card, taps «Cambiar» then «Empezar de
    cero»: both answer done=False and the approved rows stay as they are."""
    from qualify_api.creative.brand_kit_store import BrandKitStore
    from qualify_api.creative.brand_service import BrandKitService

    (tenant, brand), _other = fresh_brands
    store = BrandKitStore()
    _propose(store, tenant, brand)
    assert approve_prefill(tenant, brand, None).done
    approved = store.load_details(tenant_id=tenant, brand_id=brand)
    assert not change_prefill(tenant, brand, None).done
    assert not discard_prefill(tenant, brand, None).done
    assert store.load_details(tenant_id=tenant, brand_id=brand) == approved
    kit = BrandKitService().get_kit(tenant_id=tenant, brand_id=brand)
    assert kit is not None and kit.palette_rgb == ("#0f766e", "#f8fafc")


@pytest.mark.db
def test_the_owners_answers_in_postgres_supersede_the_proposal(fresh_brands: Any) -> None:
    from qualify_api.creative.brand_kit_store import BrandKitStore

    (tenant, brand), _other = fresh_brands
    store = BrandKitStore()
    _propose(store, tenant, brand)
    # the owner typed and saved while the card was open
    store.save_details(
        tenant_id=tenant,
        brand_id=brand,
        user_id=None,
        documents={"connect": {"rubro_text": "Lo que escribí"}},
    )
    assert not approve_prefill(tenant, brand, None).done
    saved = store.load_details(tenant_id=tenant, brand_id=brand)
    assert saved.connect["rubro_text"] == "Lo que escribí" and saved.profile == {}
    assert saved.connect[PREFILL_KEY]["state"] == "superseded"

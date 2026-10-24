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

    def scalar(self, _statement: Any) -> Any:
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
            updated_by=None,
            updated_at=None,
        )
        self.details: dict[UUID, Any] = {BRAND: row}
        self.kit = kit
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


def test_approve_adds_the_colours_to_an_existing_kit() -> None:
    kit = BrandKitRow(tenant_id=TENANT, brand_id=BRAND, language="es")
    kit.positioning, kit.audience = "Lo de siempre", "Vecinos"
    kit.tone_axes = {
        "formal_casual": 70,
        "sober_enthusiastic": 60,
        "technical_plain": 80,
        "brief_elaborate": 40,
    }
    kit.palette_rgb = ["#111111"]
    world = World({PREFILL_KEY: _document(), "progress": {"completed": False}}, kit=kit)
    assert approve_prefill(TENANT, BRAND, USER, session_factory=world.session).done
    assert world.kit is kit and not world.added
    assert kit.palette_rgb == ["#111111", "#0f766e", "#f8fafc"]
    assert kit.positioning == "Lo de siempre" and kit.tone_axes["formal_casual"] == 70


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
# db: the real rows under RLS
# --------------------------------------------------------------------------------------


def _brand_of(tenant: UUID) -> UUID:
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    from qualify_api.tenancy.models import Brand

    with tenant_session(tenant) as session:
        return session.scalar(select(Brand.id).where(Brand.tenant_id == tenant))


def _fresh_proposal(store: Any, tenant: UUID, brand: UUID) -> None:
    """A pending proposal on a kit left halfway (the shared tenants may hold a kit row
    from other tests: an unfinished progress keeps it reviewable)."""
    for key, value in ((PREFILL_KEY, _document()), ("progress", {"completed": False})):
        store.set_document_key(
            tenant_id=tenant, brand_id=brand, document="connect", key=key, value=value
        )


@pytest.mark.db
def test_approving_writes_only_the_own_tenants_brand_kit(seeded_ab: tuple[UUID, UUID]) -> None:
    from qualify_shared.db.session import tenant_session

    from qualify_api.creative.brand_kit_store import BrandKitStore
    from qualify_api.creative.brand_service import BrandKitService
    from qualify_api.creative.models import BrandKitDetails as DetailsRow

    tenant_a, tenant_b = seeded_ab
    brand_a, brand_b = _brand_of(tenant_a), _brand_of(tenant_b)
    store = BrandKitStore()
    _fresh_proposal(store, tenant_a, brand_a)
    theirs_before = store.load_details(tenant_id=tenant_b, brand_id=brand_b)

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
    assert kit is not None and "#0f766e" in kit.palette_rgb

    # tenant B's Brand Kit is exactly as it was
    assert store.load_details(tenant_id=tenant_b, brand_id=brand_b) == theirs_before


@pytest.mark.db
def test_discarding_in_postgres_keeps_the_proposal_and_promotes_nothing(
    seeded_ab: tuple[UUID, UUID],
) -> None:
    from qualify_api.creative.brand_kit_store import BrandKitStore

    tenant_a, _tenant_b = seeded_ab
    brand = _brand_of(tenant_a)
    store = BrandKitStore()
    _fresh_proposal(store, tenant_a, brand)
    before = store.load_details(tenant_id=tenant_a, brand_id=brand)
    assert discard_prefill(tenant_a, brand, None).done
    saved = store.load_details(tenant_id=tenant_a, brand_id=brand)
    assert saved.connect[PREFILL_KEY]["state"] == "discarded"
    assert saved.connect[PREFILL_KEY]["proposal"] is not None
    # everything generation reads is exactly as it was
    assert {k: v for k, v in saved.connect.items() if k != PREFILL_KEY} == {
        k: v for k, v in before.connect.items() if k != PREFILL_KEY
    }
    assert saved.profile == before.profile

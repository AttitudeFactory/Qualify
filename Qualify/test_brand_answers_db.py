"""`db`-marked: «Te faltan 3 cosas que solo tú sabes» (m-24854331) against the test
Postgres. What only the database proves: the path, the rubro's examples and the B1 drafts
are read from the owner's own tenant under RLS — another tenant's approved proposal,
drafts or answers never reach this one — and an answer saved as you go lands in the kit
only of the tenant that wrote it."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.auth import start_brand_kit_draft
from qualify_api.creative.brand_kit_store import PREFILL_KEY, BrandKitStore

from . import brand_answers_vm as vm
from . import brand_finish
from .brand_finish import KitSnapshot
from .brand_minimal import _read_entry
from .connections_provider import acting_user_id
from .creative_provider import default_brand_id, load_kit_form
from .creative_vm import KitFormVM

pytestmark = pytest.mark.db


def _draft() -> tuple[UUID, UUID, UUID]:
    email = f"hlrd1993+answers-{uuid4().hex[:8]}@gmail.com"
    tenant = start_brand_kit_draft(
        email, country="VE", timezone="America/Caracas", currency="USD"
    ).tenant_id
    brand, user = default_brand_id(tenant), acting_user_id(tenant)
    assert brand is not None and user is not None
    return tenant, brand, user


def _connect(state: str) -> dict[str, Any]:
    return {
        "sector": "food_drink",
        "rubro_text": "Heladería de yogur",
        "hashtags": [{"tag": "helados"}],
        "progress": {"flow": "minimo", "completed": False, "logo_from_profile": True},
        PREFILL_KEY: {
            "status": "ok",
            "state": state,
            "proposal": {
                "connect": {},
                "profile": {},
                "borradores": {"distinto": {"texto": "Helado hecho cada mañana.", "fuente": "x"}},
            },
        },
    }


def _approved(ids: tuple[UUID, UUID, UUID], tmp_path: Path, *, state: str = "approved") -> None:
    """What «Aprobar» leaves: a kit with the picture's colours and the approved proposal."""
    brand_finish.persist_brand_kit(
        *ids,
        KitSnapshot(form=KitFormVM(palette_rgb="#0f766e,#f8fafc")),
        adopt_voice=False,
        upload_dir=tmp_path,
    )
    BrandKitStore().save_details(
        tenant_id=ids[0],
        brand_id=ids[1],
        user_id=ids[2],
        documents={"connect": _connect(state), "profile": {"username": "heladeria.polar"}},
    )


def test_the_path_and_its_drafts_are_the_tenants_own(tmp_path: Path) -> None:
    owner = _draft()
    other = _draft()
    _approved(owner, tmp_path)

    mine = _read_entry(owner[0])
    assert mine is not None and mine.answers_path
    assert mine.drafts == {vm.Q_DISTINCT: "Helado hecho cada mañana."}
    assert mine.hints[vm.Q_DISTINCT] == vm.example_hint(vm.EXAMPLE_ICE_CREAM, vm.Q_DISTINCT)

    theirs = _read_entry(other[0])
    assert theirs is not None and not theirs.answers_path and theirs.drafts == {}
    # under RLS another tenant cannot read the owner's documents, even by brand id
    leaked = BrandKitStore().load_details(tenant_id=other[0], brand_id=owner[1])
    assert leaked.connect == {} and leaked.profile == {}


def test_an_answer_saved_as_you_go_lands_only_in_its_tenant(tmp_path: Path) -> None:
    owner = _draft()
    other = _draft()
    _approved(owner, tmp_path)
    _approved(other, tmp_path)

    brand_finish.persist_brand_kit(
        *owner,
        KitSnapshot(form=KitFormVM(positioning="Sin azúcar añadida", palette_rgb="#0f766e")),
        adopt_voice=False,
        upload_dir=tmp_path,
    )
    mine, theirs = load_kit_form(owner[0], owner[1]), load_kit_form(other[0], other[1])
    assert mine is not None and mine.positioning == "Sin azúcar añadida"
    assert theirs is not None and theirs.positioning == ""
    # the proposal survives the save (a reserved key), so the owner stays on the path
    entry = _read_entry(owner[0])
    assert entry is not None and entry.answers_path
    assert entry.facts.positioning == "Sin azúcar añadida"
    assert (
        vm.resume_screen(
            vm.Answers(entry.facts.positioning, entry.facts.audience, entry.facts.example)
        )
        == vm.Q_BUYERS
    )
    # a draft is never written as an answer by reading it
    assert entry.drafts[vm.Q_DISTINCT] != entry.facts.positioning


def test_a_changed_proposal_keeps_the_five_steps(tmp_path: Path) -> None:
    ids = _draft()
    _approved(ids, tmp_path, state="changed")
    entry = _read_entry(ids[0])
    assert entry is not None and not entry.answers_path and entry.drafts == {}

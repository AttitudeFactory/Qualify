"""`db`-marked: the Brand Kit's save-as-you-go against the test Postgres (§ request
2026-10-02). What only the database proves: a pre-login draft's position is stored and
read back as "where to go after the email", and saving at every step keeps ONE copy of
each brandboard file."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.auth import start_brand_kit_draft
from qualify_api.creative.brand_kit_store import EXTRA, BrandKitStore

from . import brand_finish
from .auth_state import _draft_destination_blocking, _kit_complete_blocking
from .brand_finish import KitSnapshot, StagedFile
from .connections_provider import acting_user_id
from .creative_provider import default_brand_id
from .creative_vm import KitFormVM

pytestmark = pytest.mark.db


class _Gate:
    """R2 stand-in: accepts every object (the store under test is the real Postgres)."""

    def put_media(self, tenant_id: UUID, key: str, fileobj: Any, content_type: str) -> None:
        fileobj.read()


def _draft() -> tuple[UUID, UUID, UUID]:
    email = f"hlrd1993+progress-{uuid4().hex[:8]}@gmail.com"
    tenant = start_brand_kit_draft(
        email, country="VE", timezone="America/Caracas", currency="USD"
    ).tenant_id
    brand, user = default_brand_id(tenant), acting_user_id(tenant)
    assert brand is not None and user is not None
    return tenant, brand, user


def _save(ids: tuple[UUID, UUID, UUID], *, step: int, completed: bool, **kw: Any) -> dict:
    snapshot = KitSnapshot(
        form=KitFormVM(positioning="Café de prueba"),
        files=kw.pop("files", []),
        connect={
            "city": "Cúcuta",
            "progress": {"flow": "connect", "step": step, "completed": completed},
        },
    )
    return brand_finish.persist_brand_kit(
        *ids, snapshot, adopt_voice=completed, gate=_Gate(), upload_dir=kw["upload_dir"]
    )


def test_the_email_lands_where_the_draft_stands(tmp_path: Path) -> None:
    ids = _draft()
    assert _draft_destination_blocking(ids[0]) == "/brand"  # nothing yet

    _save(ids, step=9, completed=False, upload_dir=tmp_path)
    status = brand_finish.tenant_kit_status(ids[0])
    assert status.completed is False and status.progress["step"] == 9
    assert _draft_destination_blocking(ids[0]) == "/brand/connect"  # back where it was

    assert _kit_complete_blocking(ids[0]) is False  # a login here is sent to the Brand Kit

    _save(ids, step=19, completed=True, upload_dir=tmp_path)
    assert _draft_destination_blocking(ids[0]) == "/signup"  # finished: create the account
    assert _kit_complete_blocking(ids[0]) is True


def test_saving_at_every_step_keeps_one_copy_of_each_file(tmp_path: Path) -> None:
    ids = _draft()
    local = f"uploads/{ids[0]}/logo/extra/ab_patron.png"
    (tmp_path / local).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / local).write_bytes(b"png")

    uploaded = _save(
        ids,
        step=11,
        completed=False,
        files=[StagedFile(EXTRA, "e0", local, "patron.png")],
        upload_dir=tmp_path,
    )
    remote = uploaded[local]
    # the session now holds the R2 key, so the next step's save does not upload again
    again = _save(
        ids,
        step=12,
        completed=False,
        files=[StagedFile(EXTRA, "e0", remote, "patron.png")],
        upload_dir=tmp_path,
    )
    assert again == {}
    assets = BrandKitStore().list_assets(tenant_id=ids[0], brand_id=ids[1])
    assert [a.object_key for a in assets] == [remote]

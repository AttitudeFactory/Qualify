"""Finishing the Brand Kit saves everything (§ request 2026-10-01): the kit form, the
brandboard's files (to R2, under the tenant's prefix) and the wizards' answers. R2, the
database and the kit save are fakes here; `test_brand_kit_store` covers the store."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from qualify_api.creative.brand_kit_store import EXTRA, LOGO_VERSION, BrandAsset

from . import brand_finish
from .brand_finish import FilesNotSaved, KitSnapshot, StagedFile
from .creative_vm import KitFormVM
from .creative_wizard_pages import BrandConnectState

TENANT = UUID("a0000000-0000-4000-8000-0000000000b9")
BRAND = UUID("b0000000-0000-4000-8000-0000000000b9")
USER = UUID("c0000000-0000-4000-8000-0000000000b9")


class FakeGate:
    def __init__(self, fail: bool = False) -> None:
        self.puts: list[tuple[UUID, str, bytes, str]] = []
        self.fail = fail

    def put_media(self, tenant_id: UUID, key: str, fileobj: Any, content_type: str) -> None:
        if self.fail:
            raise RuntimeError("R2 down")
        self.puts.append((tenant_id, key, fileobj.read(), content_type))


class FakeStore:
    def __init__(self) -> None:
        self.assets: list[BrandAsset] = []
        self.documents: dict[str, Any] = {}

    def replace_assets(self, *, tenant_id: UUID, brand_id: UUID, assets: Any) -> None:
        self.assets = list(assets)

    def save_details(self, *, documents: Any, **_kw: Any) -> None:
        self.documents.update(documents)


@pytest.fixture
def saved_kits(monkeypatch: pytest.MonkeyPatch) -> list[KitFormVM]:
    saved: list[KitFormVM] = []
    monkeypatch.setattr(brand_finish, "save_kit", lambda t, b, u, form: saved.append(form))
    return saved


def _staged(tmp_path: Path, key: str, data: bytes) -> str:
    target = tmp_path / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return key


def test_finishing_uploads_the_staged_files_and_records_them(
    tmp_path: Path, saved_kits: list[KitFormVM]
) -> None:
    iso = _staged(tmp_path, f"uploads/{TENANT}/logo/isotipo/ab12_iso.png", b"png")
    already = f"t/{TENANT}/brand/{BRAND}/extra/e0/old_patron.png"  # saved before
    snapshot = KitSnapshot(
        form=KitFormVM(positioning="café"),
        files=[
            StagedFile(LOGO_VERSION, "isotipo", iso, "iso.png", context="En fondos oscuros"),
            StagedFile(EXTRA, "e0", already, "patron.png", label="Patrón"),
        ],
        logo_brief=None,
        connect={"city": "Cúcuta"},
        profile=None,
    )
    gate, store = FakeGate(), FakeStore()
    brand_finish.persist_brand_kit(
        TENANT, BRAND, USER, snapshot, upload_dir=tmp_path, store=store, gate=gate
    )
    assert saved_kits == [snapshot.form]  # the kit form is saved first
    # only the local file travels to R2, under the brand's prefix in the tenant's
    assert len(gate.puts) == 1
    tenant_id, key, data, content_type = gate.puts[0]
    assert tenant_id == TENANT and data == b"png" and content_type == "image/png"
    assert key.startswith(f"t/{TENANT}/brand/{BRAND}/logo_version/isotipo/")
    assert key.endswith("_iso.png")
    by_slot = {(a.kind, a.slot): a for a in store.assets}
    assert by_slot[(LOGO_VERSION, "isotipo")].object_key == key
    assert by_slot[(LOGO_VERSION, "isotipo")].context == "En fondos oscuros"
    assert by_slot[(EXTRA, "e0")].object_key == already  # kept, not re-uploaded
    # only the documents this screen touched are written
    assert store.documents == {"connect": {"city": "Cúcuta"}}


def test_a_failed_upload_is_reported_after_the_kit_was_saved(
    tmp_path: Path, saved_kits: list[KitFormVM]
) -> None:
    key = _staged(tmp_path, f"uploads/{TENANT}/logo/extra/x_s.png", b"png")
    snapshot = KitSnapshot(form=KitFormVM(), files=[StagedFile(EXTRA, "e1", key, "s.png")])
    store = FakeStore()
    with pytest.raises(FilesNotSaved):
        brand_finish.persist_brand_kit(
            TENANT, BRAND, USER, snapshot, upload_dir=tmp_path, store=store, gate=FakeGate(True)
        )
    assert len(saved_kits) == 1 and store.assets == []


def test_the_connect_flow_answers_and_the_profile_become_documents() -> None:
    state = BrandConnectState()
    assert brand_finish._connect_document(state) is None  # a session that never connected
    assert brand_finish._profile_document(state) is None
    state.network = "instagram"
    state.city = "Cúcuta"
    state.rubro_hashtags = [{"tag": "cafe", "origin": "manual", "reason": "", "model": ""}]
    state.profile_username = "cafedelparque"
    state.profile_followers = "1,2 K"
    state.profile_followers_count = 1200
    state._set_metrics(
        [{"label": "Engagement", "hint": "h", "suffix": "%", "decimals": 1, "target": 4.2}]
    )
    connect = brand_finish._connect_document(state)
    assert connect is not None and connect["city"] == "Cúcuta"
    assert connect["hashtags"][0]["tag"] == "cafe"
    profile = brand_finish._profile_document(state)
    assert profile is not None and profile["followers_count"] == 1200
    assert profile["metrics"] == [
        {"label": "Engagement", "hint": "h", "suffix": "%", "decimals": 1, "target": 4.2}
    ]

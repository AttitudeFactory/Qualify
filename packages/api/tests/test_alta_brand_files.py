"""`meegle.alta_brand_files` (m-24973635): an Alta client's own logo files and colours
loaded into its Brand Kit draft — offline, against an in-memory backend."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from qualify_api.creative.brand_kit_store import (
    EXTRA,
    LOGO_VERSION,
    BrandAsset,
    brand_asset_prefix,
    main_logo_key,
)
from qualify_api.meegle import alta_brand_files as abf

ITEM = 24973550
TENANT = UUID("c0000000-0000-4000-8000-00000000ab01")
BRAND = UUID("c0000000-0000-4000-8000-00000000ab02")
USER = UUID("c0000000-0000-4000-8000-00000000ab03")
NOW = datetime(2026, 11, 6, 21, 0, tzinfo=UTC)
PNG = b"\x89PNG\r\n\x1a\n"


@dataclass
class FakeBackend:
    target: abf.DraftTarget | None = field(
        default_factory=lambda: abf.DraftTarget(TENANT, BRAND, USER, claimed=False)
    )
    jobs: tuple[abf.PrefillJobRow, ...] = ()
    connect: dict[str, Any] = field(default_factory=dict)
    has_kit: bool = False
    palette: tuple[str, ...] = ()
    assets: list[BrandAsset] = field(default_factory=list)
    objects: dict[str, bytes] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    corrected: list[str] | None = None

    def resolve(self, meegle_work_item_id: int) -> abf.DraftTarget | None:
        assert meegle_work_item_id == ITEM
        return self.target

    def read_state(self, target: abf.DraftTarget, meegle_work_item_id: int) -> abf.TargetState:
        return abf.TargetState(
            self.jobs, dict(self.connect), self.has_kit, self.palette, tuple(self.assets)
        )

    def write_connect_key(self, target: abf.DraftTarget, key: str, value: Any) -> None:
        self.calls.append(f"connect.{key}")
        self.connect[key] = value

    def write_palette(self, target: abf.DraftTarget, palette: Sequence[str]) -> None:
        self.calls.append("palette")
        self.has_kit = True
        self.palette = tuple(palette)

    def put_object(self, tenant_id: UUID, key: str, data: bytes, content_type: str) -> None:
        assert key.startswith(f"t/{tenant_id}/")
        self.calls.append("put")
        self.objects[key] = data

    def replace_assets(self, target: abf.DraftTarget, assets: Sequence[BrandAsset]) -> str | None:
        self.calls.append("assets")
        self.assets = list(assets)
        return main_logo_key(assets)

    def correct_proposal_colors(self, target: abf.DraftTarget, colours: Sequence[str]) -> bool:
        self.calls.append("correct")
        self.corrected = list(colours)
        return True

    def drop_proposal_profile_logo(self, target: abf.DraftTarget) -> bool:
        self.calls.append("no_profile_logo")
        return True


@pytest.fixture
def logos(tmp_path: Path) -> dict[str, Path]:
    out = {}
    for name in ("logotipo", "isotipo", "turquesa"):
        path = tmp_path / f"{name}.png"
        path.write_bytes(PNG + name.encode())
        out[name] = path
    return out


def _argv(logos: dict[str, Path], *extra: str) -> list[str]:
    return [
        "--meegle-item",
        str(ITEM),
        "--file",
        f"logo_version:logotipo={logos['logotipo']}",
        "--file",
        f"logo_version:isotipo={logos['isotipo']}",
        "--file",
        f"extra:Logotipo en turquesa={logos['turquesa']}",
        "--colors",
        "#ffd920,#74238C,#1AC5A3",
        *extra,
    ]


def test_file_arguments_name_the_slot_and_an_extra_slot_is_stable_per_label() -> None:
    spec = abf.parse_file_arg("logo_version:isotipo=/x/1.png")
    assert (spec.kind, spec.slot, spec.path) == (LOGO_VERSION, "isotipo", Path("/x/1.png"))
    a = abf.parse_file_arg("extra:Isotipo morado=/x/5.png")
    b = abf.parse_file_arg("extra:  isotipo MORADO =/y/other.png")
    assert a.kind == EXTRA and a.slot == b.slot and len(a.slot) == 8
    assert a.label == "Isotipo morado"
    for bad in ("logo_version:emblema=/x.png", "extra:=/x.png", "logo:main=/x", "x.png"):
        with pytest.raises(ValueError):
            abf.parse_file_arg(bad)


def test_colours_are_checked_upper_cased_and_deduplicated() -> None:
    assert abf.parse_colors("#ffd920, #74238C,#FFD920") == ["#FFD920", "#74238C"]
    for bad in ("", "#fff", "rojo", ",".join(f"#00000{i}" for i in range(7))):
        with pytest.raises(ValueError):
            abf.parse_colors(bad)


def test_a_dry_run_prints_the_plan_and_writes_nothing(logos: dict[str, Path]) -> None:
    backend = FakeBackend()
    report = abf.run(_argv(logos, "--dry-run"), backend, now=NOW)
    assert backend.calls == []
    plan = report["plan"]
    assert report["refused"] == [] and report["claimed"] is False
    prefix = brand_asset_prefix(TENANT, BRAND)
    assert all(f["object_key"].startswith(prefix) and f["upload"] for f in plan["files"])
    assert plan["main_logo"] == plan["files"][0]["object_key"]  # the logotipo
    assert plan["palette_after"] == ("#FFD920", "#74238C", "#1AC5A3")
    assert plan["create_kit"] is True
    assert plan["progress_after"] == {"flow": "minimo", "completed": False}
    assert plan["provenance"]["source"] == "founder_provided_files"
    assert plan["provenance"]["meegle_work_item_id"] == ITEM


def test_a_run_writes_in_order_and_a_rerun_converges_without_duplicates(
    logos: dict[str, Path],
) -> None:
    own = BrandAsset(kind=EXTRA, slot="ab12cd34", object_key=f"t/{TENANT}/brand/x/menu.png")
    backend = FakeBackend(assets=[own])
    abf.run(_argv(logos), backend, now=NOW)
    assert backend.calls == [
        "connect.progress",
        "connect.alta_brand_files",
        "palette",
        "put",
        "put",
        "put",
        "assets",
    ]
    first_assets = list(backend.assets)
    assert own in first_assets and len(first_assets) == 4
    assert backend.connect["progress"]["completed"] is False

    backend.calls.clear()
    abf.run(_argv(logos), backend, now=NOW)
    assert "put" not in backend.calls  # same bytes, same keys: nothing uploaded again
    assert "connect.progress" not in backend.calls  # the kit exists now
    assert backend.assets == first_assets
    assert backend.palette == ("#FFD920", "#74238C", "#1AC5A3")
    assert len(backend.objects) == 3


def test_new_bytes_for_a_slot_replace_its_file_and_hand_picked_colours_stay(
    logos: dict[str, Path],
) -> None:
    backend = FakeBackend(has_kit=True, palette=("#000000", "#74238c"))
    abf.run(_argv(logos), backend, now=NOW)
    logos["logotipo"].write_bytes(PNG + b"v2")
    abf.run(_argv(logos), backend, now=NOW)
    versions = [a for a in backend.assets if a.kind == LOGO_VERSION and a.slot == "logotipo"]
    assert len(versions) == 1 and len(backend.assets) == 3
    assert backend.palette == ("#FFD920", "#74238C", "#1AC5A3", "#000000")


def test_an_unsettled_prefill_job_or_a_waiting_proposal_refuses(logos: dict[str, Path]) -> None:
    pending = FakeBackend(jobs=(abf.PrefillJobRow("running", None, False),))
    with pytest.raises(abf.RefusedError, match="has not finished"):
        abf.run(_argv(logos), pending, now=NOW)
    waiting = FakeBackend(
        jobs=(abf.PrefillJobRow("done", "ok", True),),
        connect={"prefill": {"status": "ok", "state": "proposed"}},
    )
    with pytest.raises(abf.RefusedError, match="waiting"):
        abf.run(_argv(logos), waiting, now=NOW)
    assert pending.calls == [] and waiting.calls == []
    report = abf.run(_argv(logos, "--dry-run"), waiting, now=NOW)
    assert report["refused"] and waiting.calls == []


def test_supersede_loads_anyway_and_says_so(logos: dict[str, Path]) -> None:
    backend = FakeBackend(connect={"prefill": {"status": "ok", "state": "proposed"}})
    report = abf.run(_argv(logos, "--supersede-proposal"), backend, now=NOW)
    assert report["written"] is True and report["plan"]["warnings"]
    assert "assets" in backend.calls


def test_an_approved_proposal_is_no_obstacle(logos: dict[str, Path]) -> None:
    backend = FakeBackend(
        jobs=(abf.PrefillJobRow("done", "ok", True),),
        connect={
            "prefill": {"status": "ok", "state": "approved"},
            "progress": {"flow": "minimo", "completed": False},
        },
        has_kit=True,
        palette=("#a1b2c3",),
    )
    abf.run(_argv(logos), backend, now=NOW)
    assert backend.calls[0] == "connect.alta_brand_files"  # progress left alone
    assert backend.palette == ("#FFD920", "#74238C", "#1AC5A3", "#a1b2c3")


def test_colours_into_the_waiting_proposal_touch_nothing_else() -> None:
    backend = FakeBackend(connect={"prefill": {"status": "ok", "state": "proposed"}})
    argv = ["--meegle-item", str(ITEM), "--colors", "#FFD920,#74238C", "--colors-into-proposal"]
    report = abf.run(argv, backend, now=NOW)
    assert backend.calls == ["correct"] and backend.corrected == ["#FFD920", "#74238C"]
    assert report["written"] is True
    with pytest.raises(abf.RefusedError):
        abf.run(argv, FakeBackend(), now=NOW)  # no proposal waiting
    backend.calls.clear()
    abf.run([*argv, "--no-profile-logo"], backend, now=NOW)
    assert backend.calls == ["correct", "no_profile_logo"]
    backend.calls.clear()
    abf.run([*argv, "--no-profile-logo", "--dry-run"], backend, now=NOW)
    assert backend.calls == []


def test_no_draft_for_the_item_refuses(logos: dict[str, Path]) -> None:
    with pytest.raises(abf.RefusedError, match="no Alta Brand Kit draft"):
        abf.run(_argv(logos), FakeBackend(target=None), now=NOW)


def test_a_claimed_draft_is_the_same_tenant_and_still_loads(logos: dict[str, Path]) -> None:
    backend = FakeBackend(target=abf.DraftTarget(TENANT, BRAND, USER, claimed=True))
    report = abf.run(_argv(logos, "--expect-tenant", str(TENANT)), backend, now=NOW)
    assert report["claimed"] is True and report["written"] is True
    with pytest.raises(abf.RefusedError, match="resolves to tenant"):
        abf.run(_argv(logos, "--expect-tenant", str(USER)), FakeBackend(), now=NOW)


def test_a_registered_kit_with_a_stale_proposal_loads_and_progress_is_untouched(
    logos: dict[str, Path],
) -> None:
    """Araguaney's case: signed up, kit row with no palette, proposal still `proposed`
    and no progress — the kit counts as finished, so the proposal is not waiting."""
    backend = FakeBackend(
        target=abf.DraftTarget(TENANT, BRAND, USER, claimed=True),
        jobs=(abf.PrefillJobRow("done", "ok", True),),
        connect={"prefill": {"status": "ok", "state": "proposed"}},
        has_kit=True,
    )
    report = abf.run(_argv(logos), backend, now=NOW)
    assert report["refused"] == [] and "connect.progress" not in backend.calls
    assert backend.palette == ("#FFD920", "#74238C", "#1AC5A3")


def test_unsupported_files_and_duplicate_slots_are_rejected(
    logos: dict[str, Path], tmp_path: Path
) -> None:
    gif = tmp_path / "x.gif"
    gif.write_bytes(b"GIF89a")
    argv = ["--meegle-item", str(ITEM), "--file", f"logo_version:logotipo={gif}"]
    with pytest.raises(ValueError, match="only"):
        abf.run(argv, FakeBackend(), now=NOW)
    twice = [
        "--meegle-item",
        str(ITEM),
        "--file",
        f"logo_version:isotipo={logos['isotipo']}",
        "--file",
        f"logo_version:isotipo={logos['logotipo']}",
    ]
    with pytest.raises(ValueError, match="same kind and slot"):
        abf.run(twice, FakeBackend(), now=NOW)


def test_the_plan_never_leaves_the_tenant_prefix(logos: dict[str, Path]) -> None:
    loaded = abf.load_file(abf.parse_file_arg(f"extra:Menú de día=/{logos['turquesa']}"))
    loaded = replace(loaded, spec=replace(loaded.spec, path=Path("../../../evil name.png")))
    key = abf.object_key(TENANT, BRAND, loaded)
    assert key.startswith(brand_asset_prefix(TENANT, BRAND)) and ".." not in key.split("/")


# --------------------------------------------------------------------------------------
# `db`: the real backend over Postgres (R2 replaced by an in-memory sink)
# --------------------------------------------------------------------------------------


def _db_backend() -> Any:
    class Backend(abf.DatabaseBackend):
        def __init__(self) -> None:
            super().__init__()
            self.objects: dict[str, bytes] = {}

        def put_object(self, tenant_id: UUID, key: str, data: bytes, content_type: str) -> None:
            assert key.startswith(f"t/{tenant_id}/")
            self.objects[key] = data

    return Backend()


@pytest.mark.db
def test_the_database_backend_loads_an_alta_draft_idempotently(logos: dict[str, Path]) -> None:
    from uuid import uuid4

    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select, text

    from qualify_api.auth.drafts import start_alta_brand_kit_draft
    from qualify_api.creative.brand_kit_store import BrandKitStore
    from qualify_api.creative.brand_prefill_review import kit_finished, owner_started
    from qualify_api.creative.models import BrandKit as KitRow

    item = uuid4().int % 10**12
    draft = start_alta_brand_kit_draft(f"hlrd1993+abf-{uuid4().hex[:8]}@gmail.com", item)
    argv = [
        "--meegle-item",
        str(item),
        "--file",
        f"logo_version:logotipo={logos['logotipo']}",
        "--file",
        f"extra:Logotipo en turquesa={logos['turquesa']}",
        "--colors",
        "#FFD920,#74238C,#1AC5A3",
    ]
    backend = _db_backend()
    dry = abf.run([*argv, "--dry-run"], backend, now=NOW)
    assert dry["tenant_id"] == str(draft.tenant_id) and not backend.objects

    report = abf.run(argv, backend, now=NOW)
    abf.run(argv, backend, now=NOW)  # a re-run converges
    brand = UUID(report["brand_id"])
    assets = BrandKitStore().list_assets(tenant_id=draft.tenant_id, brand_id=brand)
    assert sorted((a.kind, a.label) for a in assets) == [
        ("extra", "Logotipo en turquesa"),
        ("logo_version", ""),
    ]
    assert len(backend.objects) == 2
    with tenant_session(draft.tenant_id) as session:
        kit = session.scalar(select(KitRow).where(KitRow.brand_id == brand))
        assert kit is not None
        assert kit.palette_rgb == ["#FFD920", "#74238C", "#1AC5A3"]
        assert kit.logo_asset_key == report["plan"]["main_logo"]
        connect = session.execute(
            text("SELECT connect FROM brand_kit_details WHERE brand_id = :b"), {"b": brand}
        ).scalar_one()
    assert not kit_finished(True, connect["progress"])  # still an unfinished kit
    assert connect["alta_brand_files"]["source"] == "founder_provided_files"
    assert owner_started(connect, {}, {}, has_files=True)

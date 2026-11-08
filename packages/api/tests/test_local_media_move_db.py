"""`db`-marked tests of CM-9 (m-24957283): the one-time copy of the `uploads` volume to R2
(`creative.local_media_move`) and its key map (migration 0138) against the test Postgres,
with a temporary volume and an in-memory bucket that keeps the production lock on `t/`
(write-once, undeletable). Never R2, never the network."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.connection_purge import connection_purge_session
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.memory import MemoryObjectStore
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.catalog.service import CatalogService
from qualify_api.connections.purge import _PROTECTED_KEYS
from qualify_api.creative import local_media_move as move
from qualify_api.creative import owner_uploads as ou
from qualify_api.creative.media import LocalMediaStore, R2ReadingMediaStore
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db

TENANT_A = UUID("a0000000-0000-4000-8000-0000000c9a01")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000c9b02")
GHOST = UUID("c0000000-0000-4000-8000-0000000c9c03")  # a folder of no business


@dataclass
class World:
    root: Path
    bucket: MemoryObjectStore
    gate: ObjectGate
    brand: UUID
    user: UUID
    product: UUID


@pytest.fixture
def world(tmp_path: Path) -> World:
    # Fresh businesses per test: the app role cannot delete map rows (by design), so a
    # test never reuses another test's tenant.
    global TENANT_A, TENANT_B
    TENANT_A, TENANT_B = uuid4(), uuid4()
    with admin_session() as session:
        brands: dict[UUID, UUID] = {}
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            session.add(
                Tenant(
                    id=tid,
                    name=f"cm9-{name}",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
            brand = Brand(tenant_id=tid, name=f"cm9-brand-{name}")
            session.add(brand)
            session.flush()
            brands[tid] = brand.id
        user = User(tenant_id=TENANT_A, email=f"cm9-{uuid4()}@a.co", display_name="U")
        session.add(user)
        session.flush()
        user_id = user.id
    ou.clear_moved_cache()
    product = CatalogService(store=LocalMediaStore(tmp_path)).create_product(
        tenant_id=TENANT_A, brand_id=brands[TENANT_A], user_id=user_id, name=f"P {uuid4().hex[:6]}"
    )
    bucket = MemoryObjectStore()
    return World(tmp_path, bucket, ObjectGate(bucket), brands[TENANT_A], user_id, product)


def _file(w: World, key: str, data: bytes) -> str:
    path = w.root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key


def _product_photo(w: World, key: str) -> None:
    with tenant_session(TENANT_A) as session:
        session.execute(
            text(
                "INSERT INTO product_media (tenant_id, brand_id, product_id, media_type,"
                " object_key, filename, content_type, normalized, is_primary, position)"
                " VALUES (:t, :b, :p, 'image', :k, 'a.jpg', 'image/jpeg', true, true, 0)"
            ),
            {"t": TENANT_A, "b": w.brand, "p": w.product, "k": key},
        )


def _brief_with_json_key(w: World, key: str) -> UUID:
    brief_id = uuid4()
    with tenant_session(TENANT_A) as session:
        session.execute(
            text(
                "INSERT INTO content_briefs (id, tenant_id, brand_id, objective, topic, platform,"
                " format, intent, content_type, image_route, created_by, media)"
                " VALUES (:id, :t, :b, 'awareness', 'x', 'instagram', 'feed', 'sell', 'image',"
                " 'upload', :u, CAST(:media AS jsonb))"
            ),
            {
                "id": brief_id,
                "t": TENANT_A,
                "b": w.brand,
                "u": w.user,
                "media": json.dumps({"brand_logo_reference_keys": [key], "kind": "x"}),
            },
        )
    return brief_id


def _kit_with_references(w: World, keys: list[str]) -> None:
    with tenant_session(TENANT_A) as session:
        session.execute(
            text(
                "INSERT INTO brand_kits (tenant_id, brand_id, tone_axes, reference_image_keys)"
                " VALUES (:t, :b, '{}'::jsonb, :keys)"
            ),
            {"t": TENANT_A, "b": w.brand, "keys": keys},
        )


def _run(w: World, mode: str, tenants: object = "A", **kw):
    chosen = [TENANT_A] if tenants == "A" else (list(tenants) if tenants is not None else None)
    return move.run(
        root=w.root,
        tenants=chosen,
        mode=mode,
        gate_factory=lambda: w.gate,
        **kw,
    )


def _rows(tenant: UUID | None = None) -> dict[str, tuple[str, str]]:
    with tenant_session(tenant or TENANT_A) as session:
        return {
            r.local_key: (r.status, r.r2_key)
            for r in session.execute(
                text("SELECT local_key, status, r2_key FROM local_media_moves")
            )
        }


# -- the dry run ---------------------------------------------------------------------


def test_the_dry_run_counts_lists_and_writes_nothing(world: World) -> None:
    photo = _file(world, f"uploads/{TENANT_A}/catalog/p/x1.jpg", b"photo-1")
    _file(world, f"generated/{TENANT_A}/d/video.mp4", b"video!")
    _file(world, f"uploads/{TENANT_A}/gallery-staging/{uuid4()}", b"waiting")
    _file(world, f"uploads/{TENANT_A}/catalog_staging/a.jpg", b"waiting")
    _file(world, f"uploads/{GHOST}/x.jpg", b"no business")
    _file(world, "uploads/not-a-tenant/x.jpg", b"?")
    (world.root / f"uploads/{TENANT_A}/link.jpg").symlink_to(world.root / photo)
    _product_photo(world, photo)
    _brief_with_json_key(world, f"uploads/{TENANT_A}/logo/x_gone.png")

    reports, walk = _run(world, "dry-run", tenants=None)
    (report,) = [r for r in reports if r.tenant_id == TENANT_A]
    assert (report.files, report.bytes, report.to_copy) == (2, 13, 2)
    assert report.by_root == {"uploads": [1, 7], "generated": [1, 6]}
    assert walk.staging == 2
    assert f"uploads/{GHOST}/x.jpg" in walk.unowned and "uploads/not-a-tenant/x.jpg" in walk.unowned
    assert walk.skipped_links == [f"uploads/{TENANT_A}/link.jpg"]
    uses = {f"{u.table}.{u.column}": u for u in report.inventory}
    assert uses["product_media.object_key"].keys == {photo}
    assert uses["product_media.object_key"].rewritten
    media = uses["content_briefs.media"]
    assert media.rows == 1 and media.missing == 1 and not media.rewritten
    assert world.bucket.objects == {} and _rows() == {}  # nothing written anywhere
    text_report = move.render(reports, walk, "dry-run")
    assert "would copy: 2 files" in text_report and "UNOWNED" in text_report


# -- the copy ------------------------------------------------------------------------


def test_apply_copies_verifies_maps_and_rewrites_the_key_columns(world: World) -> None:
    photo = _file(world, f"uploads/{TENANT_A}/catalog/p/x1.jpg", b"photo-1")
    logo = _file(world, f"uploads/{TENANT_A}/logo/x_logo.png", b"logo")
    _product_photo(world, photo)
    brief = _brief_with_json_key(world, logo)
    _kit_with_references(world, [logo, f"t/{TENANT_A}/brand/b/ref.jpg"])

    (report,), _walk = _run(world, "apply")
    assert report.copied == 2 and not report.failures and not report.conflicts
    new_photo, new_logo = ou.moved_key_for(photo), ou.moved_key_for(logo)
    assert world.bucket.objects[new_photo] == b"photo-1"
    assert world.bucket.content_types[new_photo] == "image/jpeg"
    assert _rows() == {photo: ("verified", new_photo), logo: ("verified", new_logo)}
    with tenant_session(TENANT_A) as session:
        assert session.scalar(text("SELECT object_key FROM product_media")) == new_photo
        assert session.scalar(text("SELECT reference_image_keys FROM brand_kits")) == [
            new_logo,
            f"t/{TENANT_A}/brand/b/ref.jpg",
        ]
        media = session.scalar(text("SELECT media FROM content_briefs WHERE id = :i"), {"i": brief})
        rewrites = session.scalar(
            text("SELECT rewrites FROM local_media_moves WHERE local_key = :k"), {"k": photo}
        )
        provenance = session.execute(
            text(
                "SELECT pipeline_version, sha256, bytes FROM local_media_moves WHERE local_key = :k"
            ),
            {"k": photo},
        ).one()
    assert media["brand_logo_reference_keys"] == [logo]  # JSON is never rewritten …
    assert rewrites == {"product_media.object_key": 1}
    assert provenance == ("uploads-to-r2-v1", hashlib.sha256(b"photo-1").hexdigest(), 7)

    # … and once the local file is gone, the old JSON key still reads its file: from R2
    (world.root / logo).unlink()
    store = R2ReadingMediaStore(LocalMediaStore(world.root), gate=world.gate)
    assert store.read(logo) == b"logo"
    assert ou.resolve_moved_key(TENANT_A, logo) == new_logo


def test_a_cut_copy_resumes_without_duplicating_or_skipping(world: World) -> None:
    keys = [_file(world, f"uploads/{TENANT_A}/x{i}.jpg", f"photo-{i}".encode()) for i in range(4)]
    calls = {"n": 0}
    real_put = world.bucket.put

    def dies_on_the_third(key, fileobj, content_type):
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyboardInterrupt  # the operator cut the run mid-PUT
        return real_put(key, fileobj, content_type)

    world.bucket.put = dies_on_the_third  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        _run(world, "apply")
    world.bucket.put = real_put  # type: ignore[method-assign]
    before = dict(_rows())
    assert [before[k][0] for k in keys[:2]] == ["verified", "verified"]

    (report,), _walk = _run(world, "apply")
    assert report.already == 2 and report.copied == 2
    assert {k: v[0] for k, v in _rows().items()} == dict.fromkeys(keys, "verified")
    assert sorted(world.bucket.puts) == sorted(ou.moved_key_for(k) for k in keys)  # once each

    (again,), _walk = _run(world, "apply")
    assert again.copied == 0 and again.already == 4 and len(world.bucket.puts) == 4


def test_a_put_that_landed_before_the_cut_is_verified_not_written_again(world: World) -> None:
    key = _file(world, f"uploads/{TENANT_A}/x.jpg", b"photo")
    world.bucket.put(ou.moved_key_for(key), io.BytesIO(b"photo"), "image/jpeg")
    (report,), _walk = _run(world, "apply")
    assert report.copied == 1 and world.bucket.puts == [ou.moved_key_for(key)]
    assert _rows()[key][0] == "verified"


def test_an_r2_key_holding_another_file_is_a_conflict_never_overwritten(world: World) -> None:
    key = _file(world, f"uploads/{TENANT_A}/x.jpg", b"photo")
    target = ou.moved_key_for(key)
    world.bucket.put(target, io.BytesIO(b"another file"), "image/jpeg")
    (report,), _walk = _run(world, "apply")
    assert report.conflicts == [key] and report.copied == 0
    assert world.bucket.objects[target] == b"another file"
    assert _rows()[key][0] == "conflict"
    assert ou.resolve_moved_key(TENANT_A, key) is None  # a conflict never maps
    (again,), _walk = _run(world, "delete-local")
    assert (world.root / key).exists() and again.deleted == 0


# -- deleting the local copy ---------------------------------------------------------


def test_delete_local_only_after_both_copies_verify(world: World) -> None:
    ok = _file(world, f"uploads/{TENANT_A}/ok.jpg", b"ok")
    changed = _file(world, f"uploads/{TENANT_A}/changed.jpg", b"before")
    lost = _file(world, f"uploads/{TENANT_A}/lost.jpg", b"lost in r2")
    pending = f"uploads/{TENANT_A}/never-copied.jpg"
    _run(world, "apply")
    _file(world, pending, b"new")  # appeared after the copy: no verified row
    (world.root / changed).write_bytes(b"after!")  # same file, other bytes now
    del world.bucket.objects[ou.moved_key_for(lost)]  # R2 lost it (test only)

    (report,), _walk = _run(world, "delete-local")
    assert report.deleted == 1 and sorted(report.failures) == sorted([changed, lost])
    assert not (world.root / ok).exists()
    for kept in (changed, lost, pending):
        assert (world.root / kept).exists(), kept
    assert _rows()[ok][0] == "local_deleted" and _rows()[changed][0] == "verified"
    # nothing was ever deleted in R2 (the lock would refuse it anyway)
    assert ou.moved_key_for(ok) in world.bucket.objects


def test_the_readers_still_work_after_delete_local(world: World) -> None:
    key = _file(world, f"uploads/{TENANT_A}/catalog/p/x.jpg", b"photo")
    _run(world, "apply")
    _run(world, "delete-local")
    assert not (world.root / key).exists()
    store = R2ReadingMediaStore(LocalMediaStore(world.root), gate=world.gate)
    assert store.read(key) == b"photo"
    assert ou.read_owner_media(TENANT_A, key, root=world.root, gate=world.gate) == b"photo"


# -- isolation, purge, schema --------------------------------------------------------


def test_each_business_goes_to_its_own_prefix_and_never_sees_the_others_map(
    world: World,
) -> None:
    a = _file(world, f"uploads/{TENANT_A}/a.jpg", b"a")
    b = _file(world, f"uploads/{TENANT_B}/b.jpg", b"b")
    reports, _walk = _run(world, "apply", tenants=None)
    assert {r.tenant_id for r in reports} == {TENANT_A, TENANT_B}
    assert world.bucket.objects[f"t/{TENANT_A}/uploads/a.jpg"] == b"a"
    assert world.bucket.objects[f"t/{TENANT_B}/uploads/b.jpg"] == b"b"
    assert set(_rows(TENANT_A)) == {a} and set(_rows(TENANT_B)) == {b}
    assert ou.resolve_moved_key(TENANT_B, a) is None


def test_the_r2_keys_are_protected_by_the_connection_purge(world: World) -> None:
    assert _PROTECTED_KEYS["local_media_moves"] == ("r2_key",)
    key = _file(world, f"uploads/{TENANT_A}/a.jpg", b"a")
    _product_photo(world, key)
    _run(world, "apply")
    with connection_purge_session(TENANT_A) as session:
        protected = set(
            session.scalars(
                text("SELECT r2_key FROM local_media_moves WHERE tenant_id = :t"), {"t": TENANT_A}
            )
        ) | set(
            session.scalars(
                text("SELECT object_key FROM product_media WHERE tenant_id = :t"), {"t": TENANT_A}
            )
        )
    assert ou.moved_key_for(key) in protected  # the rewritten column and the map alike


@pytest.mark.parametrize(
    ("local", "r2"),
    [
        ("uploads/{b}/x.jpg", "t/{a}/uploads/x.jpg"),  # another business's file
        ("uploads/{a}/x.jpg", "t/{b}/uploads/x.jpg"),  # another business's prefix
        ("other/{a}/x.jpg", "t/{a}/uploads/x.jpg"),
        ("uploads/{a}/../x.jpg", "t/{a}/uploads/x.jpg"),
    ],
)
def test_the_map_refuses_keys_of_another_business(world: World, local: str, r2: str) -> None:
    local, r2 = (k.format(a=TENANT_A, b=TENANT_B) for k in (local, r2))
    with pytest.raises(IntegrityError):
        with tenant_session(TENANT_A) as session:
            session.execute(
                text(
                    "INSERT INTO local_media_moves (tenant_id, local_key, r2_key, bytes, sha256,"
                    " content_type, pipeline_version) VALUES (:t, :l, :r, 1, :s, 'x', 'v')"
                ),
                {"t": TENANT_A, "l": local, "r": r2, "s": "a" * 64},
            )


def test_the_map_is_row_level_isolated(world: World) -> None:
    _file(world, f"uploads/{TENANT_A}/a.jpg", b"a")
    _run(world, "apply")
    with tenant_session(TENANT_B) as session:
        assert session.scalar(text("SELECT count(*) FROM local_media_moves")) == 0
    with pytest.raises(DBAPIError):  # a row for another tenant is refused (WITH CHECK)
        with tenant_session(TENANT_B) as session:
            session.execute(
                text(
                    "INSERT INTO local_media_moves (tenant_id, local_key, r2_key, bytes, sha256,"
                    " content_type, pipeline_version) VALUES (:t, :l, :r, 1, :s, 'x', 'v')"
                ),
                {
                    "t": TENANT_A,
                    "l": f"uploads/{TENANT_A}/z.jpg",
                    "r": f"t/{TENANT_A}/uploads/z.jpg",
                    "s": "a" * 64,
                },
            )


def test_the_cli_is_a_dry_run_unless_told_otherwise(world: World, monkeypatch, capsys) -> None:
    _file(world, f"uploads/{TENANT_A}/a.jpg", b"a")
    from qualify_api.creative import composition

    monkeypatch.setattr(composition, "media_root", lambda: world.root)
    monkeypatch.setattr(ou, "default_gate", lambda: pytest.fail("a dry run touched R2"))
    assert move.main(["--tenant", str(TENANT_A)]) == 0
    assert "would copy: 1 files" in capsys.readouterr().out
    assert _rows() == {}
    with pytest.raises(SystemExit):  # copy and delete are never one run
        move.main(["--tenant", str(TENANT_A), "--apply", "--delete-local"])


def test_conflicts_and_too_large_files_make_the_cli_exit_2(world: World, monkeypatch) -> None:
    from qualify_shared.objects import gate as gate_module

    from qualify_api.creative import composition

    key = _file(world, f"uploads/{TENANT_A}/x.jpg", b"photo")
    big = _file(world, f"uploads/{TENANT_A}/big.mp4", b"0123456789")
    world.bucket.put(ou.moved_key_for(key), io.BytesIO(b"another file"), "image/jpeg")
    monkeypatch.setattr(gate_module, "MAX_MEDIA_BYTES", 8)
    (dry,), _walk = _run(world, "dry-run", with_inventory=False)
    assert dry.too_large == [big] and dry.to_copy == 1  # the dry run already says so
    monkeypatch.setattr(composition, "media_root", lambda: world.root)
    monkeypatch.setattr(ou, "default_gate", lambda: world.gate)
    assert move.main(["--tenant", str(TENANT_A), "--apply", "--no-inventory"]) == 2
    rows = _rows()
    assert rows[key][0] == "conflict" and big not in rows  # too large: never mapped
    assert ou.moved_key_for(big) not in world.bucket.objects


def test_the_sweep_skips_columns_its_role_cannot_read_quietly(world: World, caplog) -> None:
    """Production dry run 2026-11-07 (m-24975366): the credential tables are read only
    through `credential_session`; the sweep must not try them once per business."""
    import logging

    _brief_with_json_key(world, f"uploads/{TENANT_A}/logo/x.png")
    with caplog.at_level(logging.INFO, logger=move.__name__):
        uses = move.inventory(TENANT_A)
        move.inventory(TENANT_B)
    assert not [r for r in caplog.records if "not readable" in r.getMessage()]
    assert "content_briefs" in {u.table for u in uses}  # readable columns still swept

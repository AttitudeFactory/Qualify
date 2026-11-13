"""Scoped brand policy CAS, RLS, current approvals and legacy request replays."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest
from packages.api.tests.test_ad_promotions_db import _request
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.ads.enhancements import (
    FEATURES,
    EnhancementsUnavailable,
    compose_brand_policy,
)
from qualify_api.ads.enhancements_service import load_brand_enhancements, save_brand_enhancements
from qualify_api.ads.promotion_repository import PostgresPromotionRepository, RequestConflict
from qualify_api.ads.promotions import ADAPTER_VERSION, fingerprint
from qualify_api.tenancy.acting import acting_login
from qualify_api.tenancy.models import TenantMember

pytestmark = pytest.mark.db


def world():
    req = _request()
    login = uuid4()
    with admin_session() as s:
        s.execute(
            text("UPDATE users SET auth_user_id=:login WHERE id=:id"),
            {"login": login, "id": req.approved_by},
        )
        s.add(TenantMember(tenant_id=req.tenant_id, user_id=req.approved_by, role="owner"))
    return req, login


def test_default_scoped_save_cas_and_cross_tenant_rejection():
    req, login = world()
    other, _ = world()
    with acting_login(login):
        policy = load_brand_enhancements(tenant_id=req.tenant_id, brand_id=req.brand_id)
        assert policy.version == 0 and not policy.enabled
        flags = {**policy.values, "text_optimizations": True}
        saved = save_brand_enhancements(
            tenant_id=req.tenant_id, brand_id=req.brand_id, values=flags, expected_version=0
        )
        assert saved.version == 1 and saved.enabled
        with pytest.raises(EnhancementsUnavailable):
            save_brand_enhancements(
                tenant_id=req.tenant_id, brand_id=req.brand_id, values=flags, expected_version=0
            )
        assert (
            save_brand_enhancements(
                tenant_id=req.tenant_id, brand_id=req.brand_id, values=flags, expected_version=1
            ).version
            == 1
        )
        with pytest.raises(EnhancementsUnavailable):
            load_brand_enhancements(tenant_id=req.tenant_id, brand_id=other.brand_id)
    with tenant_session(other.tenant_id) as s:
        assert s.execute(text("SELECT count(*) FROM ad_brand_enhancements")).scalar_one() == 0
    with pytest.raises(EnhancementsUnavailable):
        load_brand_enhancements(tenant_id=req.tenant_id, brand_id=req.brand_id)


def test_concurrent_first_save_has_one_winner_and_membership_is_fresh():
    req, login = world()

    def save(feature):
        with acting_login(login):
            try:
                return save_brand_enhancements(
                    tenant_id=req.tenant_id,
                    brand_id=req.brand_id,
                    values={key: key == feature for key in FEATURES},
                    expected_version=0,
                ).version
            except EnhancementsUnavailable:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, FEATURES[:2]), key=lambda value: value is None) == [1, None]
    with admin_session() as s:
        s.execute(
            text("DELETE FROM tenant_members WHERE tenant_id=:tenant AND user_id=:user"),
            {"tenant": req.tenant_id, "user": req.approved_by},
        )
    with acting_login(login), pytest.raises(Exception) as failure:
        load_brand_enhancements(tenant_id=req.tenant_id, brand_id=req.brand_id)
    assert (
        "acceso" in str(failure.value).lower() or "member" in type(failure.value).__name__.lower()
    )


def test_new_promotions_require_current_exact_policy_but_old_approval_stays_immutable():
    req, login = world()
    repo = PostgresPromotionRepository()
    with pytest.raises(EnhancementsUnavailable):
        repo.create_or_get(replace(req, enhancements_snapshot={}, creative={}))
    row = repo.create_or_get(req)
    with acting_login(login):
        old = load_brand_enhancements(tenant_id=req.tenant_id, brand_id=req.brand_id)
        new = save_brand_enhancements(
            tenant_id=req.tenant_id,
            brand_id=req.brand_id,
            values={**old.values, "enhance_cta": True},
            expected_version=0,
        )
    assert repo.create_or_get(req).request == row.request
    with pytest.raises(RequestConflict):
        repo.create_or_get(replace(req, request_key=str(uuid4())))
    updated = compose_brand_policy(replace(req, request_key=str(uuid4())), new)
    second = repo.create_or_get(updated)
    assert second.request["enhancements_snapshot"]["version"] == 1
    assert second.request["creative"]["degrees_of_freedom_spec"]["creative_features_spec"][
        "enhance_cta"
    ] == {"enroll_status": "OPT_IN"}
    assert repo.get(req.tenant_id, row.id).request == row.request


def test_database_rejects_unknown_flags_and_brand_delete_cascades():
    req, login = world()
    with acting_login(login):
        save_brand_enhancements(
            tenant_id=req.tenant_id,
            brand_id=req.brand_id,
            values={key: key == "image_touchups" for key in FEATURES},
            expected_version=0,
        )
    with pytest.raises(IntegrityError), tenant_session(req.tenant_id) as s:
        s.execute(text("UPDATE ad_brand_enhancements SET feature_flags='{}'::jsonb"))
    with admin_session() as s:
        s.execute(text("DELETE FROM brands WHERE id=:id"), {"id": req.brand_id})
    with tenant_session(req.tenant_id) as s:
        assert s.execute(text("SELECT count(*) FROM ad_brand_enhancements")).scalar_one() == 0


def test_real_legacy_approval_replays_without_injecting_new_creative_fields():
    req, _ = world()
    legacy = replace(req, enhancements_snapshot={}, creative={"source_instagram_media_id": "99"})
    snapshot = legacy.snapshot()
    columns = [
        "tenant_id",
        "brand_id",
        "request_key",
        "meta_ad_account_id",
        "content_draft_id",
        "publish_attempt_id",
        "source_media_id",
        "objective",
        "special_ad_categories",
        "cta_type",
        "link_url",
        "budget_kind",
        "budget_minor",
        "currency",
        "start_time",
        "end_time",
        "targeting",
        "approved_by",
        "approved_at",
    ]
    values = {key: snapshot[key] for key in columns}
    values.update(
        request_snapshot=snapshot,
        request_hash=fingerprint(snapshot),
        adapter_version=ADAPTER_VERSION,
    )
    columns += ["request_snapshot", "request_hash", "adapter_version"]
    json_columns = {"request_snapshot", "special_ad_categories", "targeting"}
    for key in json_columns:
        values[key] = json.dumps(values[key])
    placeholders = [
        f"CAST(:{key} AS jsonb)" if key in json_columns else f":{key}" for key in columns
    ]
    with tenant_session(req.tenant_id) as session:
        session.execute(
            text(
                f"INSERT INTO ad_promotions ({','.join(columns)}) VALUES ({','.join(placeholders)})"
            ),
            values,
        )
    replay = PostgresPromotionRepository().create_or_get(legacy)
    assert replay.request == snapshot
    assert "enhancements_snapshot" not in replay.request
    assert "degrees_of_freedom_spec" not in replay.request["creative"]
    assert fingerprint(replay.request) == fingerprint(snapshot)

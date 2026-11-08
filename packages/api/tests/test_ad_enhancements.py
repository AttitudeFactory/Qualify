"""Explicit opt-outs, immutable permissions and exact preview/dispatch binding."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from packages.api.tests.test_ad_promotions import request
from packages.api.tests.test_promotion_wizard import NOW, setup

from qualify_api.ads.enhancements import (
    FEATURES,
    BrandEnhancementSettings,
    EnhancementsUnavailable,
    compose_brand_policy,
    normalize,
    preview_receipt,
)
from qualify_api.ads.promotion_repository import MemoryPromotionRepository, RequestConflict
from qualify_api.ads.promotions import Promotion, fingerprint, step_payload


def test_all_features_are_explicitly_opted_out_and_unknowns_rejected():
    policy = BrandEnhancementSettings(uuid4(), uuid4())
    fields = policy.creative_spec()["creative_features_spec"]
    assert set(fields) == set(FEATURES)
    assert all(value == {"enroll_status": "OPT_OUT"} for value in fields.values())
    assert BrandEnhancementSettings.from_snapshot(policy.snapshot()).snapshot() == policy.snapshot()
    for values in ({}, {**policy.values, "audio": False}, {**policy.values, "image_touchups": 1}):
        with pytest.raises(EnhancementsUnavailable):
            normalize(values)


def test_new_repository_request_requires_canonical_policy_without_rewriting_legacy():
    req = request()
    legacy = replace(req, enhancements_snapshot={}, creative={"source_instagram_media_id": "99"})
    snapshot = legacy.snapshot()
    assert "enhancements_snapshot" not in snapshot
    repo = MemoryPromotionRepository()
    with pytest.raises(EnhancementsUnavailable):
        repo.create_or_get(legacy)
    old = Promotion(
        uuid4(),
        deepcopy(snapshot),
        "paused",
        dict(campaigns="1", adsets="2", adcreatives="3", ads="4"),
    )
    repo.promotions[old.id] = old
    assert repo.create_or_get(legacy).request == snapshot
    assert fingerprint(repo.get(legacy.tenant_id, old.id).request) == fingerprint(snapshot)


def test_payload_is_exact_policy_and_new_brand_revision_changes_approval():
    req = request()
    settings = BrandEnhancementSettings(req.tenant_id, req.brand_id)
    repo = MemoryPromotionRepository()
    row = repo.create_or_get(req)
    payload = step_payload(row, "adcreatives")
    assert payload["degrees_of_freedom_spec"] == settings.creative_spec()
    bad = deepcopy(req.creative)
    bad["degrees_of_freedom_spec"]["creative_features_spec"]["image_touchups"] = {
        "enroll_status": "OPT_IN"
    }
    with pytest.raises(EnhancementsUnavailable):
        replace(req, creative=bad).snapshot()
    enabled = replace(settings, version=1, values={**settings.values, "image_touchups": True})
    changed = compose_brand_policy(req, enabled)
    assert fingerprint(changed.snapshot()) != fingerprint(req.snapshot())
    with pytest.raises(RequestConflict):
        repo.create_or_get(changed)


def evidence(policy, source):
    return dict(
        policy_fingerprint=policy.fingerprint,
        creative_spec_fingerprint=fingerprint(policy.creative_spec()),
        connection_id=str(source.connection_id),
        credential_version=source.credential_version,
        source_media_id=source.source_media_id,
        instagram_user_id=source.instagram_user_id,
        meta_ad_account_id=source.meta_ad_account_id,
        eligible=True,
        checked_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=5)).isoformat(),
        pipeline_version="explicit-test-measured-contract",
    )


@pytest.mark.asyncio
async def test_opt_in_requires_exact_fresh_evidence_before_any_paused_creation():
    wizard, client, gateway, source, args, _ = setup()
    policy = BrandEnhancementSettings(
        args["tenant_id"], source.brand_id, 1, {key: key == "image_animation" for key in FEATURES}
    )
    source = replace(source, credential_version=2)
    wizard.sources.source = source
    wizard.creation.repository.enhancement_policies = lambda *unused: policy
    args["form"] = replace(args["form"], enhancements=policy)
    with pytest.raises(EnhancementsUnavailable):
        await wizard.prepare(**args)
    assert not client.calls
    gateway.checks = replace(gateway.checks, enhancement_compatibility=evidence(policy, source))

    async def remote_preview(**context):
        promotion = context["promotion"]
        ad = client.objects[promotion.ids["ads"]]
        creative_id = ad["creative"]["creative_id"]
        creative = client.objects[creative_id]
        proof = preview_receipt(
            promotion,
            context["source"],
            context["actor"],
            context["preview_hash"],
            NOW + timedelta(minutes=5),
            NOW,
        )
        proof["creative_id"] = creative_id
        proof["remote_creative_fingerprint"] = fingerprint(
            {key: creative.get(key) for key in promotion.request["creative"]}
        )
        proof["pipeline_version"] = "explicit-fake-remote-object-reader"
        return proof

    gateway.enhancement_preview_evidence = remote_preview
    preview = await wizard.prepare(**args)
    assert preview.preview_html
    review = wizard.activations.get(args["tenant_id"], preview.review_id)
    assert review.checks_snapshot["enhancements_preview"]["creative_id"] == "3"
    assert review.checks_snapshot["enhancements_preview"]["ad_id"] == "4"
    assert client.objects["3"]["degrees_of_freedom_spec"]["creative_features_spec"][
        "image_animation"
    ] == {"enroll_status": "OPT_IN"}

    kwargs = dict(
        tenant_id=args["tenant_id"],
        promotion_id=preview.promotion_id,
        review_id=preview.review_id,
        approved_by=args["approved_by"],
        confirm_charge=True,
    )
    client.calls.clear()
    original = deepcopy(client.objects["3"])
    client.objects["3"]["degrees_of_freedom_spec"]["creative_features_spec"]["image_animation"] = {
        "enroll_status": "OPT_OUT"
    }
    with pytest.raises(EnhancementsUnavailable):
        await wizard.confirm(**kwargs)
    assert not any(call[0] == "POST" for call in client.calls)
    client.objects["3"] = original
    del gateway.enhancement_preview_evidence
    with pytest.raises(ValueError):
        await wizard.confirm(**kwargs)
    gateway.enhancement_preview_evidence = remote_preview
    # Outer quote/preview remains valid, but the measured nested feature evidence
    # expires while the transport waits. The guard must run after that wait.
    short = evidence(policy, source)
    short["expires_at"] = (NOW + timedelta(seconds=30)).isoformat()
    gateway.checks = replace(gateway.checks, enhancement_compatibility=short)
    update = client.update

    async def delayed_update(object_id, *, params, before_write=None):
        wizard.clock = lambda: NOW + timedelta(seconds=31)
        return await update(object_id, params=params, before_write=before_write)

    client.update = delayed_update
    client.calls.clear()
    result = await wizard.confirm(**kwargs)
    # The guard still rejects expired nested evidence before the transport POST.
    # Once the durable activation claim exists, rejection is reported as unknown
    # so the interface cannot treat an uncertain operation as a fresh approval.
    assert result.status == "unknown"
    assert not any(call[0] == "POST" for call in client.calls)
    saved = wizard.activations.get(args["tenant_id"], preview.review_id)
    assert saved.state == "unknown" and saved.claim_token is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["policy", "credential", "html", "creative", "receipt"])
async def test_confirmation_rejects_changed_permissions_identity_or_preview(change):
    wizard, client, gateway, source, args, _ = setup()
    preview = await wizard.prepare(**args)
    review = wizard.activations.get(args["tenant_id"], preview.review_id)
    if change == "policy":
        policy = BrandEnhancementSettings(args["tenant_id"], source.brand_id, 1)
        wizard.creation.repository.enhancement_policies = lambda *unused: policy
    elif change == "credential":
        wizard.sources.source = replace(source, credential_version=5)
    elif change == "html":
        wizard.activations.rows[review.id] = replace(review, preview_html="another preview")
    elif change == "creative":
        row = wizard.creation.repository.promotions[preview.promotion_id]
        wizard.creation.repository.promotions[row.id] = replace(
            row, ids={**row.ids, "adcreatives": "999"}
        )
    else:
        checks = deepcopy(review.checks_snapshot)
        checks["enhancements_preview"]["actor"] = str(uuid4())
        wizard.activations.rows[review.id] = replace(review, checks_snapshot=checks)
    client.calls.clear()
    with pytest.raises((EnhancementsUnavailable, ValueError)):
        await wizard.confirm(
            tenant_id=args["tenant_id"],
            promotion_id=preview.promotion_id,
            review_id=preview.review_id,
            approved_by=args["approved_by"],
            confirm_charge=True,
        )
    assert not any(call[0] == "POST" for call in client.calls)


@pytest.mark.asyncio
async def test_old_preview_cannot_be_freshened_by_long_outer_preflight():
    wizard, client, gateway, _, args, _ = setup()
    gateway.checks = replace(gateway.checks, expires_at=NOW + timedelta(days=5))
    preview = await wizard.prepare(**args)
    assert preview.expires_at <= NOW + timedelta(minutes=5)
    wizard.clock = lambda: NOW + timedelta(minutes=6)
    client.calls.clear()
    with pytest.raises(ValueError, match="venci?"):
        await wizard.confirm(
            tenant_id=args["tenant_id"],
            promotion_id=preview.promotion_id,
            review_id=preview.review_id,
            approved_by=args["approved_by"],
            confirm_charge=True,
        )
    assert not any(call[0] == "POST" for call in client.calls)

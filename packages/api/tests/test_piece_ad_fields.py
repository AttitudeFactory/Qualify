"""Offline lifecycle contract, not an evaluation of model quality (m-24828975)."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from qualify_creative.ad_destination import AdCTA
from qualify_creative.enums import BriefIntent
from qualify_creative.schemas import CopyPayload

from qualify_api.creative.brand_service import _apply_kit
from qualify_api.creative.service import DraftEditConflict

from . import test_content_service as base


def test_generated_ad_snapshots_owner_default_and_ignores_model_url() -> None:
    router = base.FakeRouter(
        [base.ok_outcome(base.copy_dict() | {"ads_destination_url": "javascript:invented"})]
    )
    kit = base.make_kit(ads_destination_url="https://example.com/menu")
    service, repo, _ = base.make_service(router=router, kit=kit, voice=base.make_voice())
    draft = repo.seed_draft(base.make_brief(variants=1, intent=BriefIntent.ADS))
    service.run_generation(tenant_id=base.TENANT_ID, draft_id=draft)
    (variant,) = repo.variants_for(tenant_id=base.TENANT_ID, draft_id=draft)
    assert variant.copy["ads_destination_url"] == kit.ads_destination_url
    assert variant.copy["ads_cta_type"] == AdCTA.LEARN_MORE.value
    assert "ads_destination_url" not in router.requests[0].output_schema["properties"]
    prompt = router.requests[0].rendered_prompt
    assert kit.ads_destination_url not in prompt.stable_prefix + prompt.volatile_suffix
    assert variant.fidelity["ad_fields_contract"] == "piece-ad-destination-v1"
    assert "choose exactly LEARN_MORE" in router.requests[0].rendered_prompt.volatile_suffix


def test_regeneration_preserves_the_owners_override_after_brand_default_changes() -> None:
    router = base.FakeRouter([base.ok_outcome(base.copy_dict()), base.ok_outcome(base.copy_dict())])
    service, repo, _ = base.make_service(
        router=router,
        kit=base.make_kit(ads_destination_url="https://example.com/default"),
        voice=base.make_voice(),
    )
    draft = repo.seed_draft(base.make_brief(variants=1, intent=BriefIntent.ADS))
    service.run_generation(tenant_id=base.TENANT_ID, draft_id=draft)
    (variant,) = repo.variants_for(tenant_id=base.TENANT_ID, draft_id=draft)
    owner = CopyPayload.model_validate(
        variant.copy | {"ads_destination_url": "https://example.com/owner"}
    )
    service.edit_variant(
        tenant_id=base.TENANT_ID,
        variant_id=variant.id,
        user_id=base.USER_ID,
        copy=owner,
        expected_revision=repo.drafts[draft].revision,
    )
    service._brand._kit = base.make_kit(ads_destination_url="https://example.com/new-default")
    service.reject(
        tenant_id=base.TENANT_ID,
        draft_id=draft,
        reason="Otra versión",
        user_id=base.USER_ID,
        regenerate=True,
    )
    service.run_generation(tenant_id=base.TENANT_ID, draft_id=draft)
    (current,) = repo.variants_for(tenant_id=base.TENANT_ID, draft_id=draft)
    assert current.copy["ads_destination_url"] == "https://example.com/owner"


def test_manual_url_and_cta_edit_invalidates_approval_and_rejects_stale_editor() -> None:
    service, repo, _ = base.make_service(
        router=base.FakeRouter([base.ok_outcome(base.copy_dict())]),
        kit=base.make_kit(ads_destination_url="https://example.com/current-default"),
        voice=base.make_voice(),
    )
    draft, variant_id = base._generated_draft_with_variant(service, repo)
    service.approve(
        tenant_id=base.TENANT_ID, draft_id=draft, variant_id=variant_id, user_id=base.USER_ID
    )
    before = repo.drafts[draft].revision
    payload = CopyPayload.model_validate(
        base.copy_dict()
        | {"ads_cta_type": "GET_QUOTE", "ads_destination_url": "https://example.com/q"},
        context={"strict_ad_cta": True},
    )
    service.edit_variant(
        tenant_id=base.TENANT_ID,
        variant_id=variant_id,
        copy=payload,
        user_id=base.USER_ID,
        expected_revision=before,
    )
    assert repo.drafts[draft].revision == before + 1
    assert repo.drafts[draft].status == "generated"
    saved = dict(repo.variants[variant_id].edited_copy)
    with pytest.raises(DraftEditConflict):
        service.edit_variant(
            tenant_id=base.TENANT_ID,
            variant_id=variant_id,
            copy=payload.model_copy(update={"ads_destination_url": "https://example.com/stale"}),
            user_id=base.USER_ID,
            expected_revision=before,
        )
    assert repo.variants[variant_id].edited_copy == saved
    assert repo.drafts[draft].revision == before + 1


def test_legacy_read_projects_button_without_mutating_approved_data() -> None:
    service, repo, _ = base.make_service(
        router=base.FakeRouter([base.ok_outcome(base.copy_dict())]),
        kit=base.make_kit(),
        voice=base.make_voice(),
    )
    draft, variant_id = base._generated_draft_with_variant(service, repo)
    old = dict(repo.variants[variant_id].copy) | {"ads_cta_type": "Comprar ahora"}
    repo.variants[variant_id] = replace(repo.variants[variant_id], copy=old)
    before = replace(repo.drafts[draft])
    shown = service.variant_copy(tenant_id=base.TENANT_ID, variant_id=variant_id)
    assert shown.ads_cta_type is AdCTA.SHOP_NOW
    assert shown.ads_destination_url is None
    assert repo.variants[variant_id].copy == old
    assert repo.drafts[draft] == before


def test_omitted_brand_field_preserves_default_and_explicit_clear_removes_it() -> None:
    row = SimpleNamespace(ads_destination_url="https://example.com/existing")
    _apply_kit(row, base.make_kit())
    assert row.ads_destination_url == "https://example.com/existing"
    _apply_kit(row, base.make_kit(ads_destination_url=None))
    assert row.ads_destination_url is None

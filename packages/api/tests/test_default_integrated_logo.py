"""New defaults and frozen history, with actual producers and no paid vendors."""

from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.enums import ContentKind
from qualify_creative.schemas import MediaInputs

from qualify_api.creative import pipeline
from qualify_api.creative.brand_references import BrandReference, brand_reference_block
from qualify_api.creative.media import reel_edit_prompt

from .test_creative_media_byteplus import (
    BUDGET,
    COPY,
    TENANT_ID,
    FakeSeedream,
    _brief,
    _kit,
    _producer,
    _store,
)
from .test_creative_reel_edit import edit_brief
from .test_creative_seedance_video_input import VideoInputSeedance, _measured
from .test_creative_seedance_video_input import _producer as edit_producer
from .test_multi_brand_resources import A, B, C, assets


@pytest.mark.parametrize("key", [None, A])
def test_new_default_integrates_but_stored_missing_mode_is_signature(key: str | None) -> None:
    assert MediaInputs(brand_logo_key=key).brand_logo_in_scene
    assert not MediaInputs.model_validate(
        {"brand_logo_key": key}, context={"preserve_stored_logo_mode": True}
    ).brand_logo_in_scene
    assert not MediaInputs(brand_logo_key=key, brand_logo_in_scene=False).brand_logo_in_scene


@pytest.mark.parametrize("mode", [None, False, True])
def test_frozen_inputs_restore_original_mode_without_reinterpreting_default(
    monkeypatch: pytest.MonkeyPatch, mode: bool | None
) -> None:
    record = _brief(ContentKind.STATIC_FLYER, brand_logo_key=A).model_dump(mode="json")
    if mode is None:
        record["media"].pop("brand_logo_in_scene")
    else:
        record["media"]["brand_logo_in_scene"] = mode

    class Steps:
        def load_step(self, run: Any, step: int) -> Any:
            return {"request": {"brief": record}}

    monkeypatch.setattr(pipeline, "PipelineStore", Steps)
    with pipeline.preparing(pipeline.Preparation(TENANT_ID, uuid4(), 1, "generation", uuid4(), 1)):
        (brief,) = pipeline.frozen_inputs(brief=_brief(ContentKind.STATIC_FLYER))
    assert brief.media.brand_logo_in_scene is (mode if mode is not None else False)


def test_stored_brief_without_any_media_retains_legacy_signature_default() -> None:
    brief = _brief(ContentKind.STATIC_FLYER)
    record = brief.model_dump(mode="json")
    record.pop("media")
    assert type(brief).model_validate(record).media.brand_logo_in_scene
    assert (
        not type(brief)
        .model_validate(record, context={"preserve_stored_logo_mode": True})
        .media.brand_logo_in_scene
    )


@pytest.mark.parametrize(
    "selected,mode", [(False, True), (True, True), (True, False), (False, False)]
)
def test_actual_flyer_default_has_no_implicit_signature_or_unselected_reference(
    selected: bool, mode: bool
) -> None:
    store, vendor = _store(), FakeSeedream()
    producer = _producer(store, seedream=vendor)
    assets(producer, store)
    calls = []
    original = producer._logo

    def logo(kit: Any, key: Any = None) -> Any:
        calls.append((kit.logo_asset_key, key))
        return original(kit, key)

    producer._logo = logo
    result = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_brief(
            ContentKind.STATIC_FLYER,
            brand_logo_key=A if selected else None,
            brand_logo_in_scene=mode,
        ),
        kit=_kit().model_copy(update={"logo_asset_key": A}),
        copy=COPY,
        budget=BUDGET,
    )
    assert result.failure is None, result.detail
    if mode:
        assert calls == [(None, None)]
    elif selected:
        assert calls[0][0] == A
        assert calls[0][1] != A  # exact immutable signature copy
        assert store.read(calls[0][1]) == store.read(A)
    else:
        assert calls == [(A, None)]
    assert len(vendor.requests[0].params.get("images", ())) == int(selected and mode)


def test_actual_edit_empty_notes_integrates_three_logos_and_replaces_product_throughout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _measured(monkeypatch, 5)
    vendor = VideoInputSeedance()
    producer = edit_producer(vendor)
    rows = assets(producer, producer._store)
    rows[:] = [replace(row, context="") for row in rows]
    brief = edit_brief(brand_logo_key=A, brand_logo_reference_keys=(B, C))
    result = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert result.failure is None, result.detail
    request = vendor.requests[0]
    assert len(request.params["reference_images"]) == 4
    prompt = request.params["prompt"]
    for required in [
        "Edit @Video1 in place",
        "Replace product from first appearance/actions",
        "first appearance",
        "pasted/catalog photo",
        "hero/end card",
        "Image 2: principal imagotipo",
        "Keep used assets consistent",
        "Image 3",
        "Image 4",
        "use only needed ones",
        "product/manufacturer labels",
    ]:
        assert required in prompt
    assert len(prompt) <= 2500


def test_old_compact_instruction_bytes_remain_stable() -> None:
    refs = (
        BrandReference(
            asset_key=A,
            label="Old",
            asset_kind="logo_version",
            asset_slot="isotipo",
            selected_logo=True,
            additional_logo=True,
        ),
    )
    assert brand_reference_block(refs, base_index=2, video=True) == (
        "Image 2: Old [logo_version/isotipo; brand element]. Usage: preserve identity. "
        "isotipo: chosen symbol only, no added lettering. "
        "Keep distinct identities/colors/proportions; never merge logo variants, "
        "swap product/presenter/element roles or print notes. "
        "Maintain each resource's instructed identity, presence and action across cuts."
    )
    old = reel_edit_prompt(brief=edit_brief(), kit=_kit(), images=1, brand_refs=refs)
    assert old.startswith("Edit @Video1 in place. Replace its product")
    assert "throughout every relevant shot/action" not in old
    newrefs = tuple(ref.model_copy(update={"instruction_version": 3}) for ref in refs)
    new = reel_edit_prompt(brief=edit_brief(), kit=_kit(), images=1, brand_refs=newrefs)
    assert "throughout every relevant shot/action" in new


def test_old_multi_near_budget_resumes_same_vendor_task_without_new_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_creative.adapters.byteplus_ark import RESUME_TASK_PARAM

    from qualify_api.creative.media import _MediaFailed

    from .test_creative_vendor_task_resume import Book, QueuedSeedance

    _measured(monkeypatch, 5)
    vendor = QueuedSeedance()
    producer = edit_producer(vendor)
    assets(producer, producer._store)
    brief = edit_brief(brand_logo_key=A, brand_logo_reference_keys=(B, C))
    draft = uuid4()
    captured = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=draft, brief=brief, kit=_kit()
    )
    oldrefs = tuple(ref.model_copy(update={"instruction_version": 2}) for ref in captured.refs)
    # An old request can fit while today's stronger protected instructions cannot.
    limit = 0
    for size in range(0, 2500, 20):
        trial = (oldrefs[0].model_copy(update={"note": "x" * size}), *oldrefs[1:])
        try:
            reel_edit_prompt(brief=brief, kit=_kit(), images=1, brand_refs=trial)
        except _MediaFailed:
            break
        limit = size
    oldrefs = (oldrefs[0].model_copy(update={"note": "x" * limit}), *oldrefs[1:])
    with pytest.raises(_MediaFailed):
        reel_edit_prompt(
            brief=brief,
            kit=_kit(),
            images=1,
            brand_refs=tuple(r.model_copy(update={"instruction_version": 3}) for r in oldrefs),
        )
    selected = captured.model_copy(update={"block_version": 2, "refs": oldrefs})
    book = Book()

    def run(binding: Any) -> Any:
        return producer.produce(
            tenant_id=TENANT_ID,
            draft_id=draft,
            brief=brief,
            kit=_kit(),
            copy=COPY,
            budget=BUDGET,
            vendor_tasks=binding,
            brand_references=selected,
        )

    assert run(book).pending
    assert vendor.created == 1
    resumed = Book(known=book.known)
    result = run(resumed)
    assert result.failure is None and not result.pending, result.detail
    assert vendor.created == 1 and resumed.recorded == []
    assert vendor.requests[-1].params[RESUME_TASK_PARAM] == "cgt-1"


def test_reject_regeneration_preserves_selected_resources_and_mode() -> None:
    from . import test_content_service as svc

    service, repo, dispatcher = svc.make_service(kit=svc.make_kit(), voice=svc.make_voice())
    media = edit_brief(brand_logo_key=A, brand_logo_reference_keys=(B, C)).media
    brief = svc.make_brief(variants=1).model_copy(update={"media": media})
    draft = repo.seed_draft(brief, status=svc.GENERATED)
    service.reject(
        tenant_id=svc.TENANT_ID,
        draft_id=draft,
        reason="rejected from HITL #2",
        user_id=svc.USER_ID,
        regenerate=True,
    )
    saved = repo.get_brief(tenant_id=svc.TENANT_ID, brief_id=repo.drafts[draft].brief_id)
    assert saved.media == media
    assert saved.media.brand_logo_in_scene
    assert dispatcher.calls == [(svc.TENANT_ID, draft)]

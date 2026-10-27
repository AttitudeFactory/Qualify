"""Historical previews are read-only until the owner explicitly restores a version."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from qualify_api.creative.service import DraftDetail, VersionSummary

from . import creative_provider as provider
from . import creative_state as state_module
from .creative_state import CreativeState
from .creative_vm import DraftVM


def test_versions_are_buttons_in_the_variant_editor_without_a_dropdown() -> None:
    from .creative_pages import _variant_editor, _version_selector

    buttons = str(_version_selector())
    assert "view_version" in buttons and "version_loading" in buttons
    assert "RadixThemesSelect" not in buttons
    assert "use_viewed_version" not in buttons
    assert '"aria-pressed"' in buttons and "44px" in buttons
    editor = str(_variant_editor())
    assert "Variantes" in editor and "view_version" in editor
    assert "select_variant" in editor


def test_historical_selection_can_be_approved_without_changing_the_current_version(
    monkeypatch,
) -> None:
    current_id, previous_id = uuid4(), uuid4()
    detail = DraftDetail(
        id=uuid4(),
        brand_id=uuid4(),
        brief_id=uuid4(),
        status="generated",
        failure_reason=None,
        selected_variant_id=None,
        voice_profile_version=None,
        pipeline_version="test",
        requires_ai_disclosure=False,
        approved_by=None,
        approved_at=None,
        created_at=datetime.now(UTC),
        variants=(),
        image=None,
        active_version_id=current_id,
        viewed_version_id=previous_id,
        is_version_preview=True,
        can_restore_version=True,
        versions=(
            VersionSummary(
                id=previous_id,
                revision=1,
                created_at=datetime.now(UTC),
                status="active",
                model_id="test",
                model_revision=None,
                spent_usd=Decimal(0),
            ),
        ),
    )
    monkeypatch.setattr(provider, "_draft_costs", lambda *_: (None, ()))
    monkeypatch.setattr(provider, "_retention", lambda *_: None)
    monkeypatch.setattr(
        provider,
        "_with_download",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("historical previews must not download the current version")
        ),
    )
    vm = provider._detail_to_vm(uuid4(), detail)
    assert vm.viewing_previous_version and vm.can_restore_version
    assert vm.can_approve and not vm.can_edit and not vm.can_regenerate
    assert not vm.can_reject and vm.download_path == ""
    assert vm.active_version_id == str(current_id)
    assert vm.viewed_version_id == str(previous_id)
    assert vm.versions[0].available and not vm.versions[0].current


async def test_viewing_a_version_and_returning_to_current_do_not_restore(monkeypatch) -> None:
    tenant, brand, user, draft, version = (uuid4() for _ in range(5))
    current = DraftVM(
        draft_id=str(draft),
        status="generated",
        status_label="Lista",
        status_tone="ok",
        active_version_id=str(uuid4()),
    )
    preview = replace(current, viewed_version_id=str(version), viewing_previous_version=True)

    async def ids(self):
        return tenant, brand, user

    monkeypatch.setattr(CreativeState, "_session_ids", ids)
    monkeypatch.setattr(CreativeState, "_route_draft_id", lambda self: draft)
    monkeypatch.setattr(state_module, "preview_draft_version", lambda *_: preview)
    monkeypatch.setattr(state_module, "draft_detail", lambda *_: current)
    monkeypatch.setattr(state_module, "approval_videos", lambda *_: None)
    monkeypatch.setattr(
        state_module,
        "approve_draft_version",
        lambda *_: (_ for _ in ()).throw(AssertionError("viewing a version must never restore it")),
    )
    state = CreativeState()
    state.draft = current
    state.approve_videos_short = True
    await CreativeState.view_version.fn(state, str(version))
    assert state.draft.viewing_previous_version and not state.version_loading
    assert not state.approve_videos_short
    await CreativeState.view_version.fn(state, "")
    assert not state.draft.viewing_previous_version and not state.version_loading


async def test_approve_sends_the_selected_variant_and_version_together(monkeypatch) -> None:
    from .creative_vm import build_variant_vm

    tenant, brand, user, draft, version = (uuid4() for _ in range(5))
    choices = tuple(
        build_variant_vm(
            variant_id=str(uuid4()),
            ordinal=index,
            copy={"hook": f"Choice {index}", "caption": "c", "cta": "Pide ya"},
            edited_copy=None,
            fidelity={"passed": True},
        )
        for index in range(2)
    )
    vm = DraftVM(
        draft_id=str(draft),
        status="generated",
        status_label="Lista",
        status_tone="ok",
        variants=choices,
        can_approve=True,
        viewing_previous_version=True,
        viewed_version_id=str(version),
    )

    async def ids(self):
        return tenant, brand, user

    async def ready(self, *_):
        return True, ""

    sent = []

    def approve(*args):
        sent.append(args)
        return replace(vm, status="approved", can_approve=False, viewing_previous_version=False)

    monkeypatch.setattr(CreativeState, "_session_ids", ids)
    monkeypatch.setattr(CreativeState, "_route_draft_id", lambda self: draft)
    monkeypatch.setattr(CreativeState, "_schedule_readiness", ready)
    monkeypatch.setattr(state_module, "approve_draft_version", approve)
    monkeypatch.setattr(
        state_module,
        "approve_draft",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("a selected old version must be activated and approved together")
        ),
    )
    state = CreativeState()
    state.draft = vm
    state.select_variant(choices[1].variant_id)
    assert state.can_approve_now
    _ = [event async for event in CreativeState.approve_selected.fn(state)]
    assert sent == [(tenant, draft, UUID(choices[1].variant_id), user, version)]
    assert state.draft.status == "approved"
    assert state.selected_variant_id == choices[1].variant_id

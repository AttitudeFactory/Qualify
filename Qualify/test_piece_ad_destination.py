"""Persisted ad-button edits, explicit defaults and stale-version protection (m-24828975)."""

from __future__ import annotations

from dataclasses import replace
from types import MethodType, SimpleNamespace
from uuid import uuid4

from qualify_api.creative.service import DraftEditConflict
from qualify_creative.ad_destination import AdCTA
from qualify_creative.schemas import CopyPayload

from . import creative_provider as provider
from . import creative_state as state_module
from .creative_state import CreativeState
from .creative_vm import DraftVM, KitFormVM, build_variant_vm


def _copy(**changes: object) -> CopyPayload:
    return CopyPayload.model_validate(
        {"hook": "Tu café de hoy", "caption": "Ven por tu café.", "cta": "Visítanos", **changes}
    )


def _variant(**changes: object):
    return build_variant_vm(
        variant_id=str(uuid4()),
        ordinal=0,
        copy=_copy(**changes).model_dump(),
        edited_copy=None,
        fidelity=None,
    )


def test_legacy_button_is_labelled_and_saved_link_is_projected() -> None:
    variant = _variant(
        ads_cta_type="Comprar ahora", ads_destination_url="https://cafe.example/menu"
    )
    assert variant.ads_cta_type == "SHOP_NOW"
    assert variant.ads_cta_label == "Comprar"
    assert variant.ads_destination_url == "https://cafe.example/menu"


def test_brand_default_requires_an_explicit_choice_and_cancel_restores_saved_piece() -> None:
    state = CreativeState()
    variant = _variant(ads_cta_type="LEARN_MORE")
    draft = DraftVM(
        draft_id=str(uuid4()),
        status="generated",
        status_label="Listo para revisar",
        status_tone="info",
        variants=(variant,),
        has_ad_destination=True,
        brand_ads_destination_url="https://cafe.example",
        revision=7,
    )
    state._apply_detail(draft)
    assert state.edit_ads_destination_url == ""
    state.edit_mode = True
    CreativeState.use_brand_ad_url.fn(state)
    assert state.edit_ads_destination_url == "https://cafe.example"
    CreativeState.set_edit_ads_cta_type.fn(state, "WHATSAPP_MESSAGE")
    CreativeState.cancel_edit.fn(state)
    assert state.edit_ads_destination_url == ""
    assert state.edit_ads_cta_type == "LEARN_MORE"


def test_brand_form_round_trip_keeps_the_default_for_other_section_saves() -> None:
    state = CreativeState()
    state._apply_kit_form(
        KitFormVM(ads_destination_url="https://cafe.example", positioning="Antes")
    )
    state.kit_positioning = "Después"
    assert state._kit_form().ads_destination_url == "https://cafe.example"


class _Service:
    def __init__(self) -> None:
        self.saved: dict = {}

    def variant_copy(self, **_kwargs) -> CopyPayload:
        return _copy(
            ads_primary_text="Un café recién hecho",
            ads_headline="Visítanos hoy",
            ads_description="En el centro",
            ads_cta_type="SHOP_NOW",
            ads_destination_url="https://cafe.example/antes",
        )

    def edit_variant(self, **kwargs) -> tuple:
        self.saved = kwargs
        return ()


def _edit(service: _Service, monkeypatch, **kwargs) -> tuple[str, ...]:
    monkeypatch.setattr(provider, "production_content_service", lambda: service)
    return provider.edit_variant(
        uuid4(),
        uuid4(),
        uuid4(),
        hook="Tu café",
        caption="Ven hoy",
        hashtags="#cafe",
        cta="Ven",
        **kwargs,
    )


def test_ad_edit_retains_other_ad_text_and_passes_revision(monkeypatch) -> None:
    service = _Service()
    assert not _edit(
        service, monkeypatch, ads_cta_type="LEARN_MORE", ads_destination_url="", expected_revision=7
    )
    copy = service.saved["copy"]
    assert copy.ads_cta_type == AdCTA.LEARN_MORE
    assert copy.ads_destination_url is None
    assert copy.ads_headline == "Visítanos hoy"
    assert copy.ads_primary_text == "Un café recién hecho"
    assert service.saved["expected_revision"] == 7


def test_bad_url_and_unknown_button_are_actionable_and_never_written(monkeypatch) -> None:
    service = _Service()
    errors = _edit(service, monkeypatch, ads_destination_url="http://cafe.example")
    assert "https://" in errors[0] and not service.saved
    errors = _edit(service, monkeypatch, ads_cta_type="not-a-real-button")
    assert errors == ("Elige un botón de la lista para tu anuncio.",)
    assert not service.saved


class _Proxy:
    """Model StateProxy's non-reentrant lock, including calls through bound helpers."""

    def __init__(self, state: CreativeState) -> None:
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "_locked", False)

    async def __aenter__(self):
        assert not self._locked, "StateProxy locks cannot be nested"
        object.__setattr__(self, "_locked", True)
        return self

    async def __aexit__(self, *_args) -> None:
        object.__setattr__(self, "_locked", False)
        return None

    def __getattr__(self, name: str):
        value = getattr(self.state, name)
        if isinstance(value, MethodType) and value.__self__ is self.state:
            return MethodType(value.__func__, self)
        return value

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self.state, name, value)


def _login(monkeypatch, ids):
    auth = SimpleNamespace(
        session_tenant_id=str(ids[0]),
        guest_tenant_id="",
        _auth_user_id=str(ids[2]),
        _session_user_id=str(ids[2]),
    )

    async def get_state(_self, _cls):
        return auth

    monkeypatch.setattr(CreativeState, "get_state", get_state)
    return auth


async def test_save_uses_edit_start_revision_and_keeps_input_after_a_conflict(monkeypatch) -> None:
    state = CreativeState()
    variant = _variant(ads_cta_type="LEARN_MORE")
    state._apply_detail(
        DraftVM(
            draft_id=str(uuid4()),
            status="generated",
            status_label="Listo",
            status_tone="info",
            variants=(variant,),
            has_ad_destination=True,
            revision=4,
        )
    )
    CreativeState.start_edit.fn(state)
    state.edit_ads_destination_url = "https://cafe.example/nueva"
    state._apply_detail(replace(state.draft, revision=5))
    assert state.edit_ads_destination_url == "https://cafe.example/nueva"
    ids = (uuid4(), uuid4(), uuid4())
    reloaded = []

    async def session(self):
        async with self:
            return ids

    async def reload(_self):
        reloaded.append(True)

    def edit(*_args, **kwargs):
        assert kwargs["expected_revision"] == 4
        assert kwargs["ads_destination_url"] == "https://cafe.example/nueva"
        raise DraftEditConflict()

    monkeypatch.setattr(CreativeState, "_session_ids", session)
    _login(monkeypatch, ids)
    monkeypatch.setattr(CreativeState, "_reload_detail", reload)
    monkeypatch.setattr(state_module, "edit_variant", edit)
    await CreativeState.save_edit.fn(_Proxy(state))
    assert reloaded == []
    assert "cambió" in state.action_error
    assert not state.edit_saving and state.edit_mode and state.edit_conflict
    assert state.edit_ads_destination_url == "https://cafe.example/nueva"
    assert state.draft.revision == 5


async def test_save_response_from_a_previous_session_is_not_applied(monkeypatch) -> None:
    state = CreativeState()
    variant = _variant(ads_cta_type="LEARN_MORE")
    state._apply_detail(
        DraftVM(
            draft_id=str(uuid4()),
            status="generated",
            status_label="Listo",
            status_tone="info",
            variants=(variant,),
            has_ad_destination=True,
            revision=4,
        )
    )
    CreativeState.start_edit.fn(state)
    old_ids = (uuid4(), uuid4(), uuid4())
    new_ids = (uuid4(), uuid4(), uuid4())
    auth = _login(monkeypatch, old_ids)

    async def session(_self):
        return old_ids

    def edit(*_args, **_kwargs):
        auth.session_tenant_id = str(new_ids[0])
        auth._auth_user_id = str(new_ids[2])
        auth._session_user_id = str(new_ids[2])
        return ("Old response",)

    monkeypatch.setattr(CreativeState, "_session_ids", session)
    monkeypatch.setattr(state_module, "edit_variant", edit)
    await CreativeState.save_edit.fn(_Proxy(state))
    assert state.edit_blocking == []
    assert state.action_error == ""


def test_organic_piece_does_not_accept_a_brand_url_choice() -> None:
    state = CreativeState()
    variant = _variant()
    state._apply_detail(
        DraftVM(
            draft_id=str(uuid4()),
            status="generated",
            status_label="Listo",
            status_tone="info",
            variants=(variant,),
            has_ad_destination=False,
            brand_ads_destination_url="https://cafe.example",
        )
    )
    state.edit_mode = True
    CreativeState.use_brand_ad_url.fn(state)
    assert state.edit_ads_destination_url == ""


def test_ad_controls_have_labels_and_truthful_supported_button_notice() -> None:
    from .creative_pages import _ad_destination_fields

    rendered = str(_ad_destination_fields())
    assert '"piece-ad-button"' in rendered
    assert '"piece-ad-destination-url"' in rendered
    assert "Usar enlace de mi marca" in rendered
    assert "LEARN_MORE" in rendered and "WHATSAPP_MESSAGE" in rendered

"""A destination diagnosis is guidance, never authorization to create a paid ad."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from qualify_api.ads.messaging_destinations import (
    LINK_GUIDE,
    PENDING,
    UNKNOWN,
    MessagingDestination,
)
from qualify_api.ads.wizard import PromotionSource

from . import promotion_provider as provider
from .promotion_vm import PromotionSourceVM


@pytest.mark.parametrize("linked, reason", [(True, PENDING), (False, LINK_GUIDE), (None, UNKNOWN)])
def test_unknown_link_is_not_shown_as_an_explicitly_unlinked_number(
    monkeypatch: pytest.MonkeyPatch, linked: bool | None, reason: str
) -> None:
    row = MessagingDestination("whatsapp", "WhatsApp", False, reason, uuid4(), linked)
    monkeypatch.setattr(provider, "load_messaging_destinations", lambda **kwargs: (row,))
    options = provider.messaging_destinations(uuid4(), uuid4())
    assert reason in options[0].notice
    if linked is True:
        assert options[0].notice.startswith("Tu número de WhatsApp está vinculado a esta página.")
    elif linked is False:
        assert "no está vinculado a esta página" in options[0].notice
    else:
        assert options[0].notice == UNKNOWN
    assert options[0].label == "WhatsApp"
    assert not hasattr(options[0], "connection_id")


def test_diagnosis_failure_does_not_expose_remote_errors_or_block_the_website_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed(**kwargs: object) -> None:
        raise RuntimeError("access_token=private remote response")

    monkeypatch.setattr(provider, "load_messaging_destinations", failed)
    options = provider.messaging_destinations(uuid4(), uuid4())
    assert [row.key for row in options] == ["instagram_direct", "whatsapp"]
    assert "No pudimos comprobar" in options[1].notice
    assert "Tus redes" in options[1].notice
    assert "private" not in str(options)
    assert "access_token" not in str(options)


def test_page_entry_does_not_query_meta_and_full_form_deduplicates_destination_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = PromotionSource(
        uuid4(), uuid4(), uuid4(), uuid4(), "123", "456", "Oferta publicada", "@negocio"
    )
    other = replace(source, publish_attempt_id=uuid4())
    monkeypatch.setattr(provider, "list_promotion_sources", lambda **kwargs: [source, other])
    monkeypatch.setattr(
        provider, "read_business_locale", lambda tenant: SimpleNamespace(timezone="America/Bogota")
    )
    calls = []

    def read(**kwargs: object) -> tuple[MessagingDestination, ...]:
        calls.append(kwargs)
        return (MessagingDestination("whatsapp", "WhatsApp", False, UNKNOWN, None),)

    monkeypatch.setattr(provider, "load_messaging_destinations", read)
    tenant = uuid4()
    rows, _ = provider.load_sources(tenant, source.content_draft_id)
    assert calls == []
    assert all(row.messaging_destinations == [] for row in rows)
    rows, _ = provider.load_sources(tenant, source.content_draft_id, check_health=True)
    assert calls == [{"tenant_id": tenant, "connection_id": source.connection_id}]
    assert [row.messaging_destinations[0].notice for row in rows] == [UNKNOWN, UNKNOWN]


def test_messaging_diagnosis_has_no_selector_or_change_to_the_existing_website_form() -> None:
    from .promotion_page import _destination, _messaging_destination
    from .promotion_vm import MessagingDestinationVM

    rendered = str(
        _messaging_destination(MessagingDestinationVM("whatsapp", "WhatsApp", LINK_GUIDE)).render()
    )
    assert "WhatsApp" in rendered
    assert "Tus redes" in rendered and "Meta Business Suite" not in rendered
    assert "on_click" not in rendered
    assert "dangerouslySetInnerHTML" not in rendered
    full = str(_destination().render())
    assert "link_url" in full
    assert "messaging_destinations" in full
    assert "recheck_destinations" in full


def test_recheck_refuses_a_connection_outside_the_selected_published_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.ads.wizard import WizardUnavailable

    source = PromotionSource(uuid4(), uuid4(), uuid4(), uuid4(), "123", "456", "Oferta", "@negocio")
    monkeypatch.setattr(provider, "list_promotion_sources", lambda **kwargs: [source])

    def must_not_read(*args: object) -> None:
        pytest.fail("An unrelated connection must never be diagnosed")

    monkeypatch.setattr(provider, "messaging_destinations", must_not_read)
    with pytest.raises(WizardUnavailable):
        provider.recheck_messaging_destinations(
            uuid4(), source.content_draft_id, source.publish_attempt_id, uuid4()
        )


class _DestinationContext:
    from .promotion_state import PromotionState

    _destination_current = PromotionState._destination_current

    def __init__(self) -> None:
        from .promotion_vm import PromotionDraftVM, PromotionSourceVM

        self.context = tuple(str(uuid4()) for _ in range(3))
        self._loaded_context = self.context
        self._piece_id = str(uuid4())
        self.form = PromotionDraftVM(
            source_id=str(uuid4()),
            link_url="https://negocio.example/oferta",
            budget="25000",
            city_name="Cúcuta",
            location_key="123",
            start_local="2027-01-10T09:00",
            end_local="2027-01-17T09:00",
        )
        self.sources = [
            PromotionSourceVM(self.form.source_id, "@negocio", "Oferta", connection_id=str(uuid4()))
        ]
        self.step = 2
        self.busy = self.loading = self.destinations_working = False
        self.destinations_notice = ""
        self._destination_operation = ""

    @property
    def selected_source(self) -> PromotionSourceVM:
        return self.sources[0]

    async def _session(self) -> tuple[str, str, str]:
        return self.context

    async def __aenter__(self) -> _DestinationContext:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_recheck_keeps_the_entire_form_and_passes_only_the_current_authenticated_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.tenancy.acting import current_acting_login

    from . import promotion_state as state_module
    from .promotion_vm import MessagingDestinationVM

    context = _DestinationContext()
    before = context.form
    source = context.selected_source

    def read(*args: object) -> list[MessagingDestinationVM]:
        assert current_acting_login() == UUID(context.context[1])
        assert args == (
            UUID(context.context[0]),
            UUID(context._piece_id),
            UUID(before.source_id),
            UUID(source.connection_id),
        )
        return [MessagingDestinationVM("whatsapp", "WhatsApp", UNKNOWN)]

    monkeypatch.setattr(state_module, "recheck_messaging_destinations", read)
    await state_module.PromotionState.recheck_destinations.fn(context)
    assert context.form == before
    assert context.step == 2
    assert context.selected_source.messaging_destinations[0].notice == UNKNOWN
    assert context.destinations_working is False


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["session", "publication", "connection"])
async def test_late_diagnosis_cannot_replace_the_current_destination_options(
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    from . import promotion_state as state_module
    from .promotion_vm import MessagingDestinationVM

    context = _DestinationContext()

    async def delayed(*args: object) -> list[MessagingDestinationVM]:
        if changed == "session":
            context.context = tuple(str(uuid4()) for _ in range(3))
        elif changed == "publication":
            context.form = replace(context.form, source_id=str(uuid4()))
        else:
            context.sources = [replace(context.sources[0], connection_id=str(uuid4()))]
        return [MessagingDestinationVM("whatsapp", "WhatsApp", "Old account")]

    monkeypatch.setattr(state_module.asyncio, "to_thread", delayed)
    await state_module.PromotionState.recheck_destinations.fn(context)
    assert context.selected_source.messaging_destinations == []
    assert context.destinations_notice == ""

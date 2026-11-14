"""A destination diagnosis is guidance, never authorization to create a paid ad."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from qualify_api.ads.messaging_destinations import (
    LINK_GUIDE,
    NO_NUMBER,
    READY,
    UNKNOWN,
    MessagingDestination,
)
from qualify_api.ads.wizard import PromotionSource

from . import promotion_provider as provider
from .promotion_vm import PromotionSourceVM


@pytest.mark.parametrize(
    "available, code, reason, notice, action",
    [
        (True, "ready", READY, "Te escriben a tu WhatsApp.", ""),
        (False, "unlinked", LINK_GUIDE, LINK_GUIDE, "Unir mi WhatsApp"),
        (
            False,
            "no_number",
            NO_NUMBER,
            "Para recibir mensajes por WhatsApp, primero conéctalo.",
            "Conectar mi WhatsApp",
        ),
        (False, "unknown", UNKNOWN, UNKNOWN, ""),
    ],
)
def test_whatsapp_card_shows_the_backend_reason_and_its_action_by_reason_code(
    monkeypatch: pytest.MonkeyPatch,
    available: bool,
    code: str,
    reason: str,
    notice: str,
    action: str,
) -> None:
    row = MessagingDestination(
        "whatsapp", "WhatsApp", available, reason, uuid4(), available, reason_code=code
    )
    monkeypatch.setattr(provider, "load_messaging_destinations", lambda **kwargs: (row,))
    [option] = provider.messaging_destinations(uuid4(), uuid4())
    assert (option.available, option.reason_code, option.notice, option.action) == (
        available,
        code,
        notice,
        action,
    )
    assert option.label == "WhatsApp"
    assert not hasattr(option, "connection_id")
    assert "57300" not in str(option)  # never the number


def test_diagnosis_failure_does_not_expose_remote_errors_or_block_the_website_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed(**kwargs: object) -> None:
        raise RuntimeError("access_token=private remote response")

    monkeypatch.setattr(provider, "load_messaging_destinations", failed)
    options = provider.messaging_destinations(uuid4(), uuid4())
    assert [row.key for row in options] == ["whatsapp", "instagram_direct"]
    assert not any(row.available for row in options)
    assert all("No pudimos comprobar" in row.notice for row in options)
    assert all(row.reason_code == "unknown" and not row.action for row in options)
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


def test_chat_cards_live_in_their_own_step_not_in_the_website_form() -> None:
    from .promotion_page import _channel, _destination, _link_destination

    channel = str(_channel())  # the foreach body, as compiled
    assert "messaging_destinations" in channel
    assert "recheck_destinations" in channel
    assert "/connections" in channel
    assert "dangerouslySetInnerHTML" not in channel
    website = str(_link_destination().render())
    assert "link_url" in website
    # Only with QUALIFY_ADS_CHAT_GOAL off does the website form list the chats.
    assert "chat_goal" in website
    assert "todavía no" not in str(_destination().render())


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

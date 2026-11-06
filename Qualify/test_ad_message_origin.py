"""Advertisement origin stays on its exact resolved inbound message, never a whole chat."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from .ad_message_vm import ad_origin_href, ad_origin_label
from .conversations_vm import build_message_vm as instagram_message
from .whatsapp_chats_vm import build_message_vm as whatsapp_message

NOW = datetime(2026, 11, 5, 17, 0, tzinfo=UTC)
ZONE = ZoneInfo("America/Bogota")
ORIGIN = "Vino de un anuncio: Shawarma de pollo"


def _message(**changes: object) -> SimpleNamespace:
    values = {
        "id": uuid4(),
        "direction": "inbound",
        "text": "¿Tienen domicilio?",
        "posted_at": NOW,
        "ingested_at": NOW,
        "delivery_status": None,
        "delivery_error_code": None,
        "media_kind": None,
        "media_type": None,
        "has_media": False,
        "media_mime": None,
    }
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("build", [whatsapp_message, instagram_message])
def test_origin_is_bound_to_one_inbound_and_never_carried_to_organic_or_outbound(
    build: Callable[..., Any],
) -> None:
    promotion = uuid4()
    origin = _message(ad_promotion_id=promotion, ad_origin_label=ORIGIN)
    organic = _message()
    outbound = _message(direction="outbound", ad_promotion_id=promotion, ad_origin_label=ORIGIN)
    rows = [build(row, now=NOW, zone=ZONE) for row in [origin, organic, outbound]]
    assert [row.ad_origin_label for row in rows] == [ORIGIN, "", ""]
    assert [row.ad_origin_href for row in rows] == [f"/promotions/{promotion}", "", ""]
    assert rows[0].text == rows[1].text == "¿Tienen domicilio?"


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"ad_origin_label": ORIGIN},
        {"ad_promotion_id": uuid4()},
        {"ad_promotion_id": uuid4(), "ad_origin_label": 123},
        {"ad_promotion_id": "https://example.com", "ad_origin_label": ORIGIN},
        {"ad_promotion_id": "123456789", "ad_origin_label": ORIGIN},
    ],
)
def test_legacy_unresolved_and_nonlocal_identifiers_cannot_create_origin_links(
    fields: dict[str, object],
) -> None:
    message = _message(**fields)
    assert ad_origin_label(message) == ""
    assert ad_origin_href(message) == ""


def test_chat_bubbles_render_text_and_internal_navigation_without_provider_html() -> None:
    from .conversations_page import _ad_origin as instagram_origin
    from .whatsapp_tab_chats import _ad_origin as whatsapp_origin

    message = _message(ad_promotion_id=uuid4(), ad_origin_label=ORIGIN)
    for build, component in [
        (whatsapp_message, whatsapp_origin),
        (instagram_message, instagram_origin),
    ]:
        model = build(message, now=NOW, zone=ZONE)
        rendered = str(component(model).render())
        assert "Ver anuncio" in rendered
        assert model.ad_origin_href in rendered
        assert "dangerouslySetInnerHTML" not in rendered


def test_switching_threads_clears_the_advertisement_from_both_chat_states() -> None:
    from .conversations_state import ConversationsState
    from .whatsapp_chats_state import WhatsAppChatsState

    message = _message(ad_promotion_id=uuid4(), ad_origin_label=ORIGIN)
    for state, build in [
        (WhatsAppChatsState(), whatsapp_message),
        (ConversationsState(), instagram_message),
    ]:
        state.messages = [build(message, now=NOW, zone=ZONE)]
        state._reset_conversation()
        assert state.messages == []


def test_real_backend_read_models_project_the_origin_without_exposing_remote_ids() -> None:
    from qualify_api.conversations.repository import MessageRecord as InstagramMessage
    from qualify_api.whatsapp.chats import MessageRecord as WhatsAppMessage

    promotion = uuid4()
    records = [
        (
            WhatsAppMessage(
                uuid4(),
                "inbound",
                "Hola",
                NOW,
                None,
                None,
                "wamid.private",
                ad_promotion_id=promotion,
                ad_origin_label=ORIGIN,
                ad_origin_at=NOW,
            ),
            whatsapp_message,
        ),
        (
            InstagramMessage(
                uuid4(),
                uuid4(),
                uuid4(),
                "mid.private",
                "inbound",
                "private_author",
                None,
                "Hola",
                NOW,
                NOW,
                None,
                None,
                ad_promotion_id=promotion,
                ad_origin_label=ORIGIN,
                ad_origin_at=NOW,
            ),
            instagram_message,
        ),
    ]
    for message, build in records:
        view = build(message, now=NOW, zone=ZONE)
        assert view.ad_origin_label == ORIGIN
        assert view.ad_origin_href == f"/promotions/{promotion}"
        assert "private" not in str(view)


@pytest.mark.parametrize("observed, label", [(None, "Sin datos"), (0, "0"), (12, "12")])
def test_observed_chat_count_is_local_not_a_meta_metric_or_an_assumed_zero(
    observed: int | None, label: str
) -> None:
    from qualify_api.ads.results import PromotionResults, PromotionResultSummary

    from .ad_results_provider import detail_vm

    summary = PromotionResultSummary(
        uuid4(), uuid4(), "ACTIVE", "Activo", "COP", 10000, "lifetime", NOW, NOW
    )
    result = PromotionResults(summary, (), NOW, observed_conversations=observed)
    view = detail_vm(result)
    assert view.observed_conversations == label
    assert view.days == []


class _ChatContext:
    def __init__(self) -> None:
        self.tenant_id = uuid4()
        self.open_thread_id = str(uuid4())
        self._connection_id = self.selected_connection_id = str(uuid4())
        self.conv_loading_for = self.conv_loaded_for = self.conv_error = ""
        self._records: list[Any] = []
        self.messages: list[Any] = []
        self.rendered = False

    async def __aenter__(self) -> _ChatContext:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def _tenant(self) -> UUID:
        return self.tenant_id

    def _render_conversation(self) -> None:
        self.rendered = True

    def _reset_conversation(self) -> None:
        pytest.fail("An old read must not reset the currently selected conversation")


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["whatsapp", "instagram"])
@pytest.mark.parametrize("changed", ["tenant", "connection", "thread"])
@pytest.mark.parametrize("outcome", ["success", "missing", "error"])
async def test_late_ad_source_cannot_reappear_after_session_or_account_changes(
    monkeypatch: pytest.MonkeyPatch, channel: str, changed: str, outcome: str
) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    from . import conversations_state, whatsapp_chats_state

    module = whatsapp_chats_state if channel == "whatsapp" else conversations_state
    state_class = (
        whatsapp_chats_state.WhatsAppChatsState
        if channel == "whatsapp"
        else conversations_state.ConversationsState
    )
    context = _ChatContext()
    attributed = _message(ad_promotion_id=uuid4(), ad_origin_label=ORIGIN)
    response = SimpleNamespace(
        messages=[attributed], unsent=[], order=None, has_more=False, media_sources={}
    )

    async def delayed_read(*args: Any, **kwargs: Any) -> Any:
        if changed == "tenant":
            context.tenant_id = uuid4()
        elif changed == "connection":
            context._connection_id = context.selected_connection_id = str(uuid4())
        else:
            context.open_thread_id = str(uuid4())
        if outcome == "missing":
            raise module.ThreadNotFound("Old conversation")
        if outcome == "error":
            raise SQLAlchemyError("Old read failed")
        return response

    monkeypatch.setattr(module, "gateway", lambda: SimpleNamespace(conversation=lambda: None))
    monkeypatch.setattr(module.asyncio, "to_thread", delayed_read)
    await state_class._read_conversation(context, silent=False)
    assert context.messages == []
    assert context.rendered is False
    assert context.conv_error == ""

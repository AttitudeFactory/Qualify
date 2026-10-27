"""Regression checks for the shared connection vocabulary (m-24854866)."""

import pytest

from .connection_copy import STATUS_LABELS, connection_status_display
from .whatsapp_vm import graph_error_notice


@pytest.mark.parametrize("status", ["active", "degraded", "revoked"])
def test_whatsapp_and_network_cards_use_the_same_status(status: str) -> None:
    label, tone, _icon = STATUS_LABELS[status]
    assert connection_status_display(status) == (label, tone)


@pytest.mark.parametrize("status", ["auth_error_190", "unknown", "", "revoked_by_provider"])
def test_unknown_connection_states_do_not_leak_internal_values(status: str) -> None:
    assert connection_status_display(status) == ("Sin verificar", "neutral")


@pytest.mark.parametrize("code", [None, 190, 131009, 987654321])
@pytest.mark.parametrize(
    "auth,transport", [(False, False), (False, True), (True, False), (True, True)]
)
def test_all_whatsapp_error_paths_hide_internal_details(code, auth, transport) -> None:
    message, tone = graph_error_notice(code=code, is_auth_error=auth, is_transport=transport)
    for forbidden in ("meta", "token", "degradada", "revocada", "código"):
        assert forbidden not in message.lower()
    if code is not None:
        assert str(code) not in message
    assert tone in {"warn", "error"}
    if auth:
        assert "equipo de Qualify" in message


def test_account_recovery_banners_offer_real_actions() -> None:
    from .connections_page import (
        _instagram_degraded_banner,
        _instagram_revoked_banner,
        _whatsapp_reconnect_hint,
    )

    for banner in (_instagram_degraded_banner, _instagram_revoked_banner):
        rendered = str(banner().render())
        assert "Volver a conectar" in rendered
        assert "start_connect_flow" in rendered
        assert "Pide ayuda" in rendered and "open_support" in rendered
        assert "Conectar de nuevo" not in rendered
        assert "permiso necesario" not in rendered
        assert "Sin acceso" not in rendered

    rendered = str(_whatsapp_reconnect_hint().render())
    assert "Avisar al equipo de Qualify" in rendered
    assert "open_support" in rendered
    assert "start_connect_flow" not in rendered


def test_permission_callback_uses_the_shared_recovery_action() -> None:
    from .connections_vm import CONNECT_RESULT_NOTICES

    message, tone = CONNECT_RESULT_NOTICES["permission_missing"]
    assert "Volver a conectar" in message
    assert "marcadas" in message and tone == "warn"
    assert "Meta" not in message

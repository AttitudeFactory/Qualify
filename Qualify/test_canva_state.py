"""The Canva card's synchronous pieces: starting the OAuth trip keeps its secrets on the
server, an unconfigured server says so, and a link is shown with a reopen URL that
still carries the correlation (so Canva's "Return" finds it)."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from qualify_api.canva.repository import LinkRecord

from .canva_provider import link_item
from .canva_state import CanvaState


def test_connect_without_credentials_explains_instead_of_redirecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QUALIFY_CANVA_CLIENT_ID", raising=False)
    monkeypatch.delenv("QUALIFY_CANVA_CLIENT_SECRET", raising=False)
    state = CanvaState()
    assert state.connect() is None
    assert "no está configurado" in state.error


def test_connect_keeps_the_pkce_verifier_and_state_server_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUALIFY_CANVA_CLIENT_ID", "cid")
    monkeypatch.setenv("QUALIFY_CANVA_CLIENT_SECRET", "secret")
    state = CanvaState()
    assert state.connect() is not None  # a redirect to Canva's consent page
    assert state._oauth_state and state._pkce_verifier
    # backend-only: never part of what the browser receives
    assert "_pkce_verifier" in CanvaState.backend_vars


def test_a_link_reopens_with_its_correlation_state() -> None:
    link = LinkRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        draft_id=uuid4(),
        created_by_user_id=uuid4(),
        source_object_key="generated/t/d/image.png",
        media_type="image",
        canva_design_id="D1",
        correlation_state="abc123",
        edit_url="https://www.canva.com/design/D1/edit",
        status="exported",
        design_updated_at=1,
        exported_object_key="generated/t/d/canva-1.png",
        exported_at=datetime(2026, 9, 28, 12, 5, tzinfo=UTC),
        error=None,
        created_at=datetime(2026, 9, 28, 12, 0, tzinfo=UTC),
    )
    item = link_item(link)
    assert parse_qs(urlsplit(item["open_url"]).query) == {"correlation_state": ["abc123"]}
    assert item["status_label"] == "Edición traída de Canva"
    assert item["exported_key"] == "generated/t/d/canva-1.png"
    assert item["exported_at"] == "28/09 12:05"

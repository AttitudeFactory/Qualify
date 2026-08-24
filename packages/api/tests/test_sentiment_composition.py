"""`db`-marked tests for the sentiment composition seam (`analyze_pending_comments`) —
proves the WIRING (unknown-connection refusal, real Postgres round-trip), not the model
itself: `production_sentiment_service` is monkeypatched to a stub provider so this file
never loads real weights, same posture `test_inbox_composition.py` establishes for its
own Meta client.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Message, Thread
from qualify_api.sentiment import composition
from qualify_api.sentiment.composition import UnknownSentimentConnection
from qualify_api.sentiment.repository import AnalysisVersion, PostgresSentimentRepository
from qualify_api.sentiment.service import SentimentService
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_C = UUID("e0000000-0000-4000-8000-0000000000f5")
UNKNOWN_CONNECTION = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

STUB_VERSION = AnalysisVersion(
    detector_version="d1", pipeline_version="p1", model_id="stub/deterministic", model_revision=None
)


class StubProvider:
    model_id = "stub/deterministic"

    def classify(self, text: str) -> tuple[str, float]:
        return ("NEG", 0.9) if "mal" in text.lower() else ("POS", 0.9)


@pytest.fixture(autouse=True)
def _stub_production_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real repository (real Postgres), fake model — never loads robertuito here."""
    monkeypatch.setattr(
        composition,
        "production_sentiment_service",
        lambda: SentimentService(
            repository=PostgresSentimentRepository(), version=STUB_VERSION, provider=StubProvider()
        ),
    )


def test_unknown_connection_is_refused_before_any_analysis() -> None:
    with pytest.raises(UnknownSentimentConnection):
        composition.analyze_pending_comments(tenant_id=TENANT_C, connection_id=UNKNOWN_CONNECTION)


def test_full_seam_analyzes_a_real_message_end_to_end() -> None:
    with admin_session() as session:
        if session.get(Tenant, TENANT_C) is None:
            session.add(
                Tenant(
                    id=TENANT_C,
                    name="t-sentiment-comp",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=TENANT_C, email=f"u-{uuid4()}@c.co", display_name="U")
        session.add(user)
        session.flush()
        app_id, user_id = app.id, user.id

    with tenant_session(TENANT_C) as session:
        conn = SocialConnection(
            tenant_id=TENANT_C,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4()}",
            linked_page_id="page-1",
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        connection_id = conn.id

        thread = Thread(
            tenant_id=TENANT_C,
            connection_id=connection_id,
            channel="comment",
            external_thread_id=f"media-{uuid4()}",
            status="open",
        )
        session.add(thread)
        session.flush()
        message = Message(
            tenant_id=TENANT_C,
            thread_id=thread.id,
            connection_id=connection_id,
            external_message_id=f"comment-{uuid4()}",
            direction="inbound",
            text="que mal servicio",
            shape_version="ig-comment-shapes-1.0.0",
        )
        session.add(message)
        session.flush()

    summary = composition.analyze_pending_comments(tenant_id=TENANT_C, connection_id=connection_id)

    assert summary.comments_checked == 1
    assert summary.new_results == 1

    # Idempotent: calling the seam again finds nothing pending.
    summary_again = composition.analyze_pending_comments(
        tenant_id=TENANT_C, connection_id=connection_id
    )
    assert summary_again.comments_checked == 0

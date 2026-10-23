"""`db`: Fase B (m-24789645, PR 2) against Postgres — the candidate query over sentiment
+ intent + followups, intent-only drafts (0081), the atomic «Regenerar», and tenant
isolation of the catalog and the intent rows a draft uses.

Self-seeded, disposable tenants/connections/comments; each test uses fresh analysis
versions so rows other tests leave behind never become its candidates.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.assisted.grounding import Grounding, catalog_grounding_for
from qualify_api.catalog.models import BrandProduct
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.conversations.suggest import Proposal
from qualify_api.inbox.models import Message, Thread
from qualify_api.intent.contract import IntentClass
from qualify_api.intent.models import CommentIntentResult
from qualify_api.replies.repository import CandidateComment, PostgresReplyRepository
from qualify_api.replies.service import ReplyService
from qualify_api.sentiment.models import CommentSentimentResult
from qualify_api.sentiment.repository import AnalysisVersion
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db

TENANT_A = UUID("e0000000-0000-4000-8000-0000000000f9")
TENANT_B = UUID("e0000000-0000-4000-8000-0000000000fa")
RELIABLE = {c: True for c in IntentClass}


def _version(kind: str) -> AnalysisVersion:
    return AnalysisVersion(
        detector_version=f"test-faseb-{kind}-{uuid4().hex[:8]}",
        pipeline_version=f"test-faseb-{kind}-pipeline",
        model_id=f"test/{kind}",
        model_revision=None,
    )


def _ensure_tenant(tenant_id: UUID) -> None:
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=f"t-faseb-{tenant_id.hex[:6]}",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()


def _seed_connection(tenant_id: UUID) -> tuple[UUID, UUID, UUID]:
    """`(connection_id, comment thread id, a real user id)`."""
    _ensure_tenant(tenant_id)
    with admin_session() as session:
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@faseb.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id
    with tenant_session(tenant_id) as session:
        conn = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4()}",
            linked_page_id="page-1",
            granted_scopes=["basic", "manage_comments"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        thread = Thread(
            tenant_id=tenant_id,
            connection_id=conn.id,
            channel="comment",
            external_thread_id=f"media-{uuid4()}",
            status="open",
        )
        session.add(thread)
        session.flush()
        return conn.id, thread.id, user_id


def _seed_comment(
    tenant_id: UUID,
    connection_id: UUID,
    thread_id: UUID,
    comment: str,
    *,
    sentiment: tuple[AnalysisVersion, str] | None = None,
    intent: tuple[AnalysisVersion, dict[str, float]] | None = None,
) -> UUID:
    with tenant_session(tenant_id) as session:
        source_id = f"comment-{uuid4()}"
        message = Message(
            tenant_id=tenant_id,
            thread_id=thread_id,
            connection_id=connection_id,
            external_message_id=source_id,
            direction="inbound",
            text=comment,
            shape_version="ig-comment-shapes-1.0.0",
        )
        session.add(message)
        session.flush()
        if sentiment is not None:
            version, label = sentiment
            session.add(
                CommentSentimentResult(
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    message_id=message.id,
                    source_id=source_id,
                    detector_version=version.detector_version,
                    pipeline_version=version.pipeline_version,
                    model_id=version.model_id,
                    model_revision=version.model_revision,
                    label=label,
                    score=0.9,
                )
            )
        if intent is not None:
            version, confidences = intent
            session.add(
                CommentIntentResult(
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    message_id=message.id,
                    source_id=source_id,
                    detector_version=version.detector_version,
                    pipeline_version=version.pipeline_version,
                    model_id=version.model_id,
                    model_revision=version.model_revision,
                    confidences=confidences,
                    commercial_intent=any(c != "general" for c in confidences),
                )
            )
        session.flush()
        return message.id


def _seed_catalog(tenant_id: UUID, connection_id: UUID, product: str) -> UUID:
    with admin_session() as session:
        brand = Brand(tenant_id=tenant_id, name=f"Marca {uuid4().hex[:6]}")
        session.add(brand)
        session.flush()
        brand_id = brand.id
    with tenant_session(tenant_id) as session:
        row = BrandProduct(
            tenant_id=tenant_id,
            brand_id=brand_id,
            name=product,
            slug=f"p-{uuid4().hex[:8]}",
            price_amount=Decimal("4.50"),
            price_currency="USD",
            position=0,
        )
        session.add(row)
        session.flush()
        connection = session.get(SocialConnection, connection_id)
        assert connection is not None
        connection.brand_id = brand_id
        session.flush()
        return row.id


class FakeGenerator:
    version = "m24789645.1:fake"

    def __init__(self) -> None:
        self.calls: list[Grounding] = []

    def propose(
        self,
        *,
        grounding: Grounding,
        messages: Sequence[Any],
        counterpart: str,
        context: str | None = None,
    ) -> Proposal:
        self.calls.append(grounding)
        return Proposal(
            text=f"¡Hola! Te escribimos por DM ({len(self.calls)}).",
            used_only_given_facts=True,
            model_id="claude-haiku-5-5",
            input_tokens=100,
            output_tokens=20,
            cost_usd=0.00002,
        )


def _service(
    sentiment: AnalysisVersion, intent: AnalysisVersion, generator: FakeGenerator
) -> ReplyService:
    return ReplyService(
        repository=PostgresReplyRepository(),
        version=sentiment,
        generator_version="qua22.2:test",
        intent_version=intent,
        grounded_generator=generator,
        grounding=catalog_grounding_for,
        reliability=lambda detector: RELIABLE,
    )


def _candidate_ids(
    tenant_id: UUID, connection_id: UUID, sentiment: AnalysisVersion, intent: AnalysisVersion
) -> dict[UUID, CandidateComment]:
    found = PostgresReplyRepository().list_reply_candidates(
        tenant_id=tenant_id,
        connection_id=connection_id,
        sentiment_version=sentiment,
        intent_version=intent,
    )
    return {c.message_id: c for c in found}


def test_candidates_are_pos_or_current_commercial_with_no_draft() -> None:
    sentiment, intent, stale = _version("sent"), _version("intent"), _version("stale")
    connection_id, thread_id, user_id = _seed_connection(TENANT_A)
    pos = _seed_comment(
        TENANT_A, connection_id, thread_id, "¡Qué rico!", sentiment=(sentiment, "POS")
    )
    commercial_only = _seed_comment(
        TENANT_A,
        connection_id,
        thread_id,
        "¿Cuánto cuesta?",
        intent=(intent, {"price": 0.95, "product": 0.4}),
    )
    neg_commercial = _seed_comment(
        TENANT_A,
        connection_id,
        thread_id,
        "Muy caro, ¿hay descuento?",
        sentiment=(sentiment, "NEG"),
        intent=(intent, {"price": 0.9}),
    )
    general_neu = _seed_comment(
        TENANT_A,
        connection_id,
        thread_id,
        "Vi esto ayer",
        sentiment=(sentiment, "NEU"),
        intent=(intent, {"general": 0.9}),
    )
    stale_commercial = _seed_comment(
        TENANT_A, connection_id, thread_id, "¿Precio?", intent=(stale, {"price": 0.9})
    )
    with tenant_session(TENANT_A) as session:
        session.execute(
            text(
                "INSERT INTO interaction_followups (tenant_id, connection_id, origin_kind, "
                "origin_message_id, trigger, status, notice_status) VALUES "
                "(:t, :c, 'comment', :m, 'manual', 'open', 'not_requested')"
            ),
            {"t": str(TENANT_A), "c": str(connection_id), "m": str(commercial_only)},
        )

    found = _candidate_ids(TENANT_A, connection_id, sentiment, intent)

    assert set(found) == {pos, commercial_only, neg_commercial}
    assert general_neu not in found and stale_commercial not in found
    c = found[commercial_only]
    assert (c.sentiment_result_id, c.sentiment_label) == (None, "")
    assert c.commercial_intent is True and c.intent_classes == ("price", "product")
    assert c.intent_version == intent and c.intent_result_id is not None
    assert c.followup_status == "open"
    assert found[pos].intent_result_id is None and found[pos].sentiment_label == "POS"

    # A comment with ANY draft — even a discarded one — leaves the automatic batch.
    repo = PostgresReplyRepository()
    draft = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=found[pos],
        gate_reason="r",
        generator_version="v",
        generated_text="¡Gracias!",
    )
    assert draft is not None
    repo.decide_draft(
        tenant_id=TENANT_A,
        draft_id=draft.id,
        decision="discarded",
        final_text=None,
        decided_by_user_id=user_id,
    )
    assert pos not in _candidate_ids(TENANT_A, connection_id, sentiment, intent)


def test_an_intent_only_draft_is_stored_and_a_signalless_one_is_refused() -> None:
    sentiment, intent = _version("sent"), _version("intent")
    connection_id, thread_id, _ = _seed_connection(TENANT_A)
    product_id = _seed_catalog(TENANT_A, connection_id, "Yogurt de taro")
    message_id = _seed_comment(
        TENANT_A, connection_id, thread_id, "¿Cuánto cuesta?", intent=(intent, {"price": 0.9})
    )
    generator = FakeGenerator()

    summary = _service(sentiment, intent, generator).generate_drafts(
        tenant_id=TENANT_A, connection_id=connection_id
    )

    assert summary.drafts_created == 1
    repo = PostgresReplyRepository()
    draft = repo.get_live_draft(tenant_id=TENANT_A, message_id=message_id)
    assert draft is not None
    assert (draft.sentiment_result_id, draft.sentiment_label) == (None, "")
    assert draft.intent_result_id is not None and draft.needs_review is False
    assert draft.grounding is not None and draft.grounding["prices_withheld"] is True
    assert draft.grounding["products"][0]["product_id"] == str(product_id)
    assert draft.grounding["products"][0]["price_amount"] is None
    assert draft.cost_usd == Decimal("0.000020")
    assert not generator.calls[0].has_prices  # D1: the model got no price

    # 0081: a draft resting on no signal at all is unbuildable.
    other = _seed_comment(TENANT_A, connection_id, thread_id, "hola")
    with pytest.raises(IntegrityError, match="ck_reply_draft_has_signal"):
        repo.create_draft(
            tenant_id=TENANT_A,
            connection_id=connection_id,
            candidate=CandidateComment(message_id=other, source_id="x", text="hola"),
            gate_reason="r",
            generator_version="v",
            generated_text="t",
        )


def test_a_double_regenerate_leaves_exactly_one_live_draft() -> None:
    sentiment, intent = _version("sent"), _version("intent")
    connection_id, thread_id, user_id = _seed_connection(TENANT_A)
    _seed_catalog(TENANT_A, connection_id, "Yogurt de taro")
    message_id = _seed_comment(
        TENANT_A, connection_id, thread_id, "¿Cuánto cuesta?", intent=(intent, {"price": 0.9})
    )
    service = _service(sentiment, intent, FakeGenerator())
    service.generate_drafts(tenant_id=TENANT_A, connection_id=connection_id)
    repo = PostgresReplyRepository()
    first = repo.get_live_draft(tenant_id=TENANT_A, message_id=message_id)
    assert first is not None

    regenerated = service.regenerate(tenant_id=TENANT_A, draft_id=first.id, user_id=user_id)
    old = repo.get_draft(tenant_id=TENANT_A, draft_id=first.id)
    assert old is not None and old.status == "discarded" and old.decided_by_user_id == user_id
    assert regenerated.status == "proposed" and regenerated.id != first.id

    # Two concurrent «Regenerar» on the same draft: both reach supersede_draft (a double
    # click read it as 'proposed' before either committed); exactly one wins.
    candidate = repo.get_reply_candidate(
        tenant_id=TENANT_A,
        message_id=message_id,
        sentiment_version=sentiment,
        intent_version=intent,
    )
    assert candidate is not None
    results: list[Any] = []
    barrier = threading.Barrier(2)

    def click() -> None:
        barrier.wait()
        results.append(
            repo.supersede_draft(
                tenant_id=TENANT_A,
                draft_id=regenerated.id,
                decided_by_user_id=user_id,
                candidate=candidate,
                gate_reason="r",
                generator_version="v",
                generated_text="otra",
            )
        )

    threads = [threading.Thread(target=click) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [r for r in results if r is not None]
    assert len(results) == 2 and len(winners) == 1
    with tenant_session(TENANT_A) as session:
        live = session.execute(
            text(
                "SELECT id FROM comment_reply_drafts WHERE message_id = :m "
                "AND status NOT IN ('discarded', 'send_failed')"
            ),
            {"m": str(message_id)},
        ).all()
    assert [row.id for row in live] == [winners[0].id]


def test_a_tenants_draft_never_uses_another_tenants_catalog_or_intent_rows() -> None:
    sentiment, intent = _version("sent"), _version("intent")
    conn_a, thread_a, _ = _seed_connection(TENANT_A)
    conn_b, thread_b, _ = _seed_connection(TENANT_B)
    marker_a, marker_b = f"Taro {uuid4().hex[:6]}", f"Mango {uuid4().hex[:6]}"
    _seed_catalog(TENANT_A, conn_a, marker_a)
    _seed_catalog(TENANT_B, conn_b, marker_b)
    comment_a = _seed_comment(
        TENANT_A, conn_a, thread_a, "¿Cuánto cuesta?", intent=(intent, {"price": 0.9})
    )
    comment_b = _seed_comment(
        TENANT_B, conn_b, thread_b, "¿Cuánto cuesta?", intent=(intent, {"price": 0.9})
    )
    repo = PostgresReplyRepository()

    # Tenant B cannot see A's comment or its intent row, even naming its ids.
    assert _candidate_ids(TENANT_B, conn_a, sentiment, intent) == {}
    assert (
        repo.get_reply_candidate(
            tenant_id=TENANT_B,
            message_id=comment_a,
            sentiment_version=sentiment,
            intent_version=intent,
        )
        is None
    )
    assert catalog_grounding_for(TENANT_B, conn_a).products == ()

    generator = FakeGenerator()
    service = _service(sentiment, intent, generator)
    service.generate_drafts(tenant_id=TENANT_A, connection_id=conn_a)
    service.generate_drafts(tenant_id=TENANT_B, connection_id=conn_b)

    draft_a = repo.get_live_draft(tenant_id=TENANT_A, message_id=comment_a)
    draft_b = repo.get_live_draft(tenant_id=TENANT_B, message_id=comment_b)
    assert draft_a is not None and draft_b is not None
    assert [p["name"] for p in draft_a.grounding["products"]] == [marker_a]
    assert [p["name"] for p in draft_b.grounding["products"]] == [marker_b]
    with tenant_session(TENANT_A) as session:
        own_intent = session.execute(
            text("SELECT message_id FROM comment_intent_results WHERE id = :i"),
            {"i": str(draft_a.intent_result_id)},
        ).scalar_one()
    assert own_intent == comment_a
    assert repo.get_draft(tenant_id=TENANT_B, draft_id=draft_a.id) is None

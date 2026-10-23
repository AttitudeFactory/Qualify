"""`db`-marked end-to-end test for QUA-22's comments tranche: `PostgresReplyRepository`
against a self-seeded, disposable tenant/connection/thread/message/sentiment-result —
same seeding pattern `test_sentiment_results_db.py::_seed_two_comments` establishes,
extended one step further (a `comment_sentiment_results` row, migration 0014's own
composite-FK dependency).

Covers what a purely offline (Memory-repository) test cannot: the real FK/CHECK
constraints from migration 0014, RLS isolation between two tenants, and the
`comment_reply_drafts_settle_once` trigger actually refusing a write.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Message, MonitoredMedia, Thread
from qualify_api.replies.repository import CandidateComment, PostgresReplyRepository
from qualify_api.sentiment.models import CommentSentimentResult
from qualify_api.sentiment.repository import AnalysisVersion
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_A = UUID("e0000000-0000-4000-8000-0000000000f7")
TENANT_B = UUID("e0000000-0000-4000-8000-0000000000f8")


def _fresh_version() -> AnalysisVersion:
    run_id = uuid4().hex[:8]
    return AnalysisVersion(
        detector_version=f"test-replies-e2e-{run_id}",
        pipeline_version="test-replies-e2e-pipeline",
        model_id="test/e2e-stub",
        model_revision=None,
    )


def _ensure_tenant(tenant_id: UUID, name: str) -> None:
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id, name=name, country="CO", timezone="America/Bogota", currency="COP"
                )
            )
            session.flush()


def _seed_pos_comment(
    tenant_id: UUID, version: AnalysisVersion
) -> tuple[UUID, CandidateComment, UUID]:
    """Seeds a connection + comment-channel thread + one inbound message + one POS
    `comment_sentiment_results` row under `version` — the exact shape
    `list_positive_comments_without_draft` reads. Returns
    `(connection_id, candidate, user_id)` — `user_id` is a REAL seeded row, required
    because `decided_by_user_id` carries a live FK to `users.id` (migration 0014); a
    random `uuid4()` would violate it, which is itself worth asserting once (see
    `test_decided_by_user_id_fk_is_enforced` below)."""
    _ensure_tenant(tenant_id, f"t-replies-e2e-{tenant_id.hex[:6]}")
    with admin_session() as session:
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@e2e.co", display_name="U")
        session.add(user)
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
        connection_id = conn.id

        thread = Thread(
            tenant_id=tenant_id,
            connection_id=connection_id,
            channel="comment",
            external_thread_id=f"media-{uuid4()}",
            status="open",
        )
        session.add(thread)
        session.flush()

        source_id = f"comment-{uuid4()}"
        message = Message(
            tenant_id=tenant_id,
            thread_id=thread.id,
            connection_id=connection_id,
            external_message_id=source_id,
            direction="inbound",
            author_username="cliente.feliz",
            text="Me encanta, excelente servicio!",
            shape_version="ig-comment-shapes-1.0.0",
        )
        session.add(message)
        session.flush()

        result = CommentSentimentResult(
            tenant_id=tenant_id,
            connection_id=connection_id,
            message_id=message.id,
            source_id=source_id,
            detector_version=version.detector_version,
            pipeline_version=version.pipeline_version,
            model_id=version.model_id,
            model_revision=version.model_revision,
            label="POS",
            score=0.95,
        )
        session.add(result)
        session.flush()

        candidate = CandidateComment(
            message_id=message.id,
            source_id=source_id,
            text=message.text or "",
            sentiment_result_id=result.id,
            sentiment_label="POS",
            author_username="cliente.feliz",
            external_media_id=thread.external_thread_id,
        )
    return connection_id, candidate, user_id


def test_finds_the_seeded_pos_comment_and_creates_a_draft() -> None:
    version = _fresh_version()
    connection_id, candidate, _user_id = _seed_pos_comment(TENANT_A, version)
    repo = PostgresReplyRepository()

    candidates = repo.list_positive_comments_without_draft(
        tenant_id=TENANT_A, connection_id=connection_id, version=version
    )
    assert [c.message_id for c in candidates] == [candidate.message_id]

    created = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="comment channel, POS sentiment, non-empty text, no existing draft",
        generator_version="qua22.1:test-model",
        generated_text="¡Gracias por tu comentario!",
    )
    assert created is not None
    assert created.status == "proposed"

    # The candidate no longer appears — a draft now exists for it.
    remaining = repo.list_positive_comments_without_draft(
        tenant_id=TENANT_A, connection_id=connection_id, version=version
    )
    assert remaining == ()


def test_a_soft_deleted_comment_is_never_a_draft_candidate() -> None:
    """QUA-101 regression: a comment Meta no longer returns (`messages.deleted_at` set
    by `InboxRepository.reconcile_media_comments`) must never surface as a candidate
    for a NEW reply draft — even though it is still POS-analyzed and has no draft yet.
    Wasting a generator call and showing a human reviewer a draft for a comment that no
    longer exists on Instagram was the exact bug this test pins closed."""
    version = _fresh_version()
    connection_id, candidate, _user_id = _seed_pos_comment(TENANT_A, version)
    with tenant_session(TENANT_A) as session:
        message = session.get(Message, candidate.message_id)
        assert message is not None
        message.deleted_at = datetime.now(UTC)
        session.flush()
    repo = PostgresReplyRepository()

    candidates = repo.list_positive_comments_without_draft(
        tenant_id=TENANT_A, connection_id=connection_id, version=version
    )

    assert candidates == ()


def test_unique_message_id_returns_none_not_an_exception() -> None:
    version = _fresh_version()
    connection_id, candidate, _user_id = _seed_pos_comment(TENANT_A, version)
    repo = PostgresReplyRepository()
    first = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="r",
        generator_version="v1",
        generated_text="text one",
    )
    assert first is not None

    second = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="r",
        generator_version="v1",
        generated_text="text two",
    )
    assert second is None


def test_full_lifecycle_accept_send_sent_is_settled() -> None:
    version = _fresh_version()
    connection_id, candidate, user_id = _seed_pos_comment(TENANT_A, version)
    repo = PostgresReplyRepository()
    draft = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="r",
        generator_version="v1",
        generated_text="¡Gracias!",
    )
    assert draft is not None

    decided = repo.decide_draft(
        tenant_id=TENANT_A,
        draft_id=draft.id,
        decision="accepted",
        final_text=None,
        decided_by_user_id=user_id,
    )
    assert decided.status == "accepted"
    assert decided.settled_at is None  # accepted is NOT terminal — only sent/failed/discarded are

    sending = repo.mark_sending(tenant_id=TENANT_A, draft_id=draft.id)
    assert sending.status == "sending"

    sent = repo.mark_sent(tenant_id=TENANT_A, draft_id=draft.id, external_reply_id="meta-reply-1")
    assert sent.status == "sent"
    assert sent.is_settled is True
    assert sent.external_reply_id == "meta-reply-1"


def test_ambiguous_send_does_not_settle() -> None:
    version = _fresh_version()
    connection_id, candidate, user_id = _seed_pos_comment(TENANT_A, version)
    repo = PostgresReplyRepository()
    draft = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="r",
        generator_version="v1",
        generated_text="¡Gracias!",
    )
    assert draft is not None
    repo.decide_draft(
        tenant_id=TENANT_A,
        draft_id=draft.id,
        decision="accepted",
        final_text=None,
        decided_by_user_id=user_id,
    )
    repo.mark_sending(tenant_id=TENANT_A, draft_id=draft.id)

    ambiguous = repo.mark_send_ambiguous(
        tenant_id=TENANT_A, draft_id=draft.id, error_code="transport:timeout"
    )
    assert ambiguous.status == "send_ambiguous"
    assert ambiguous.settled_at is None  # deliberately unsettled — see migration 0014


def test_settle_once_trigger_refuses_a_second_write_to_a_settled_row() -> None:
    """The `comment_reply_drafts_settle_once` trigger, exercised directly with raw SQL
    — the same class of test `publish_attempts_settle_once` gets, proving the
    invariant is enforced by Postgres, not merely by `PostgresReplyRepository`'s own
    discipline."""
    version = _fresh_version()
    connection_id, candidate, user_id = _seed_pos_comment(TENANT_A, version)
    repo = PostgresReplyRepository()
    draft = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="r",
        generator_version="v1",
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

    with tenant_session(TENANT_A) as session, pytest.raises(DBAPIError, match="already settled"):
        session.execute(
            text("UPDATE comment_reply_drafts SET status = 'proposed' WHERE id = :id"),
            {"id": str(draft.id)},
        )


def test_rls_isolates_another_tenants_draft() -> None:
    version = _fresh_version()
    connection_id, candidate, _user_id = _seed_pos_comment(TENANT_A, version)
    repo = PostgresReplyRepository()
    draft = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="r",
        generator_version="v1",
        generated_text="¡Gracias!",
    )
    assert draft is not None
    _ensure_tenant(TENANT_B, "t-replies-e2e-b")

    invisible = repo.get_draft(tenant_id=TENANT_B, draft_id=draft.id)
    assert invisible is None

    visible = repo.get_draft(tenant_id=TENANT_A, draft_id=draft.id)
    assert visible is not None


def test_decided_by_user_id_fk_is_enforced() -> None:
    """The failure this file's own earlier draft tripped over, kept as a real test
    rather than silently fixed away: `decided_by_user_id` is a live FK to `users.id`
    (migration 0014), so a random, never-seeded uuid must be refused, not silently
    accepted."""
    version = _fresh_version()
    connection_id, candidate, _user_id = _seed_pos_comment(TENANT_A, version)
    repo = PostgresReplyRepository()
    draft = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="r",
        generator_version="v1",
        generated_text="¡Gracias!",
    )
    assert draft is not None

    with pytest.raises(DBAPIError, match="decided_by_user_id_fkey"):
        repo.decide_draft(
            tenant_id=TENANT_A,
            draft_id=draft.id,
            decision="accepted",
            final_text=None,
            decided_by_user_id=uuid4(),
        )


# --- m-24789645 (0080): provenance, one LIVE draft per comment, intent FK, RLS ------------


def _create(repo: PostgresReplyRepository, connection_id: UUID, candidate: CandidateComment, **kw):
    return repo.create_draft(
        tenant_id=kw.pop("tenant_id", TENANT_A),
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="r",
        generator_version="v1",
        generated_text=kw.pop("text", "¡Gracias!"),
        **kw,
    )


def _seed_intent_result(tenant_id: UUID, connection_id: UUID, message_id: UUID) -> UUID:
    from qualify_api.intent.models import CommentIntentResult

    with tenant_session(tenant_id) as session:
        row = CommentIntentResult(
            tenant_id=tenant_id,
            connection_id=connection_id,
            message_id=message_id,
            source_id=f"comment-{uuid4()}",
            detector_version=f"test-intent-{uuid4().hex[:8]}",
            pipeline_version="test-intent-pipeline",
            model_id="test/intent",
            confidences={"price": 0.9},
            commercial_intent=True,
        )
        session.add(row)
        session.flush()
        return row.id


def test_one_live_draft_per_comment_and_a_new_one_after_discard_or_refusal() -> None:
    connection_id, candidate, user_id = _seed_pos_comment(TENANT_A, _fresh_version())
    repo = PostgresReplyRepository()

    first = _create(repo, connection_id, candidate)
    assert first is not None
    assert _create(repo, connection_id, candidate) is None  # the live index holds
    live = repo.get_live_draft(tenant_id=TENANT_A, message_id=candidate.message_id)
    assert live is not None and live.id == first.id

    repo.decide_draft(
        tenant_id=TENANT_A,
        draft_id=first.id,
        decision="discarded",
        final_text=None,
        decided_by_user_id=user_id,
    )
    assert repo.get_live_draft(tenant_id=TENANT_A, message_id=candidate.message_id) is None
    second = _create(repo, connection_id, candidate, text="otra versión")
    assert second is not None and second.id != first.id
    assert _create(repo, connection_id, candidate) is None

    # Meta refused it (send_failed, settled): known not public, room for a new draft.
    repo.decide_draft(
        tenant_id=TENANT_A,
        draft_id=second.id,
        decision="accepted",
        final_text=None,
        decided_by_user_id=user_id,
    )
    repo.mark_sending(tenant_id=TENANT_A, draft_id=second.id)
    repo.mark_send_failed(tenant_id=TENANT_A, draft_id=second.id, error_code="platform:100")
    third = _create(repo, connection_id, candidate)
    assert third is not None

    # Generation still skips the comment: it has drafts, live or not (behaviour unchanged).
    assert repo.has_draft(tenant_id=TENANT_A, message_id=candidate.message_id)
    with tenant_session(TENANT_A) as session:
        count = session.execute(
            text("SELECT count(*) FROM comment_reply_drafts WHERE message_id = :m"),
            {"m": str(candidate.message_id)},
        ).scalar_one()
    assert count == 3


def test_a_sent_or_ambiguous_draft_keeps_the_comment_from_a_second_public_reply() -> None:
    repo = PostgresReplyRepository()
    for settle in ("sent", "send_ambiguous"):
        connection_id, candidate, user_id = _seed_pos_comment(TENANT_A, _fresh_version())
        draft = _create(repo, connection_id, candidate)
        assert draft is not None
        repo.decide_draft(
            tenant_id=TENANT_A,
            draft_id=draft.id,
            decision="accepted",
            final_text=None,
            decided_by_user_id=user_id,
        )
        repo.mark_sending(tenant_id=TENANT_A, draft_id=draft.id)
        if settle == "sent":
            repo.mark_sent(tenant_id=TENANT_A, draft_id=draft.id, external_reply_id="r-1")
        else:
            repo.mark_send_ambiguous(tenant_id=TENANT_A, draft_id=draft.id, error_code="t")
        assert _create(repo, connection_id, candidate) is None, settle


def test_provenance_round_trips_and_defaults_on_the_old_path() -> None:
    from decimal import Decimal

    from qualify_api.replies.repository import DraftProvenance

    connection_id, candidate, _user_id = _seed_pos_comment(TENANT_A, _fresh_version())
    repo = PostgresReplyRepository()
    intent_id = _seed_intent_result(TENANT_A, connection_id, candidate.message_id)
    grounding = {
        "business_name": "Polet",
        "products": [{"product_id": str(uuid4()), "name": "Taro", "price": "$4.5"}],
    }
    draft = _create(
        repo,
        connection_id,
        candidate,
        provenance=DraftProvenance(
            grounding=grounding,
            needs_review=True,
            unsupported_claims=("horario",),
            model_id="claude-haiku-5-5",
            model_revision="rev-1",
            input_tokens=120,
            output_tokens=40,
            cost_usd=Decimal("0.000310"),
            intent_result_id=intent_id,
        ),
    )
    assert draft is not None
    back = repo.get_draft(tenant_id=TENANT_A, draft_id=draft.id)
    assert back is not None
    assert back.grounding == grounding
    assert back.needs_review is True
    assert back.unsupported_claims == ("horario",)
    assert (back.model_id, back.model_revision) == ("claude-haiku-5-5", "rev-1")
    assert (back.input_tokens, back.output_tokens, back.cost_usd) == (
        120,
        40,
        Decimal("0.000310"),
    )
    assert back.intent_result_id == intent_id

    # The QUA-22 path writes none of it: NULL / false.
    other_conn, other_candidate, _ = _seed_pos_comment(TENANT_A, _fresh_version())
    old = _create(repo, other_conn, other_candidate)
    assert old is not None
    assert (old.grounding, old.needs_review, old.unsupported_claims) == (None, False, ())
    assert (old.model_id, old.input_tokens, old.cost_usd, old.intent_result_id) == (
        None,
        None,
        None,
        None,
    )


def test_intent_result_fk_is_tenant_consistent_and_not_swallowed() -> None:
    """A draft cannot point at another tenant's Fase A signal (composite FK, R2) — and
    that refusal is raised, not mistaken for the "already has a live draft" race."""
    from sqlalchemy.exc import IntegrityError

    from qualify_api.replies.repository import DraftProvenance

    connection_a, candidate_a, _ = _seed_pos_comment(TENANT_A, _fresh_version())
    connection_b, candidate_b, _ = _seed_pos_comment(TENANT_B, _fresh_version())
    foreign_intent = _seed_intent_result(TENANT_B, connection_b, candidate_b.message_id)
    repo = PostgresReplyRepository()

    with pytest.raises(IntegrityError, match="fk_reply_draft_intent_tenant"):
        _create(
            repo,
            connection_a,
            candidate_a,
            provenance=DraftProvenance(intent_result_id=foreign_intent),
        )
    # Nothing was written, so the comment is still free for a draft.
    assert repo.get_live_draft(tenant_id=TENANT_A, message_id=candidate_a.message_id) is None


def test_rls_hides_another_tenants_drafts_and_grounding() -> None:
    from qualify_api.replies.repository import DraftProvenance

    connection_id, candidate, _ = _seed_pos_comment(TENANT_A, _fresh_version())
    repo = PostgresReplyRepository()
    marker = f"Secreto {uuid4().hex[:8]}"
    draft = _create(
        repo,
        connection_id,
        candidate,
        provenance=DraftProvenance(grounding={"business_name": marker, "products": []}),
    )
    assert draft is not None
    _ensure_tenant(TENANT_B, "t-replies-e2e-b")

    assert repo.get_draft(tenant_id=TENANT_B, draft_id=draft.id) is None
    assert repo.get_live_draft(tenant_id=TENANT_B, message_id=candidate.message_id) is None
    assert repo.list_pending_drafts(tenant_id=TENANT_B, connection_id=connection_id) == ()
    with tenant_session(TENANT_B) as session:
        leaked = session.execute(
            text(
                "SELECT count(*) FROM comment_reply_drafts "
                "WHERE grounding->>'business_name' = :marker"
            ),
            {"marker": marker},
        ).scalar_one()
    assert leaked == 0
    # A tenant also cannot write a draft onto another tenant's comment (composite FKs).
    _other_conn, undrafted, _ = _seed_pos_comment(TENANT_A, _fresh_version())
    with pytest.raises(DBAPIError):
        _create(repo, _other_conn, undrafted, tenant_id=TENANT_B)

    mine = repo.get_draft(tenant_id=TENANT_A, draft_id=draft.id)
    assert mine is not None and mine.grounding == {"business_name": marker, "products": []}


def test_catalog_grounding_carries_product_ids_and_updated_at() -> None:
    from decimal import Decimal

    from qualify_api.assisted.grounding import catalog_grounding_for
    from qualify_api.catalog.models import BrandProduct
    from qualify_api.tenancy.models import Brand

    connection_id, _candidate, _ = _seed_pos_comment(TENANT_A, _fresh_version())
    with admin_session() as session:
        brand = Brand(tenant_id=TENANT_A, name=f"Polet {uuid4().hex[:6]}")
        session.add(brand)
        session.flush()
        brand_id, brand_name = brand.id, brand.name
    with tenant_session(TENANT_A) as session:
        active = BrandProduct(
            tenant_id=TENANT_A,
            brand_id=brand_id,
            name="Taro",
            slug=f"taro-{uuid4().hex[:8]}",
            price_amount=Decimal("4.50"),
            price_currency="USD",
            category="bebidas",
            position=0,
        )
        hidden = BrandProduct(
            tenant_id=TENANT_A,
            brand_id=brand_id,
            name="Retirado",
            slug=f"old-{uuid4().hex[:8]}",
            is_active=False,
        )
        session.add_all([active, hidden])
        session.flush()
        connection = session.get(SocialConnection, connection_id)
        assert connection is not None
        connection.brand_id = brand_id
        session.flush()
        session.refresh(active)
        product_id, updated_at = active.id, active.updated_at

    g = catalog_grounding_for(TENANT_A, connection_id)

    assert g.business_name == brand_name
    (p,) = g.products
    assert (p.name, p.price_label, p.currency, p.price_amount) == (
        "Taro",
        "$4.5",
        "USD",
        Decimal("4.50"),
    )
    assert p.product_id == product_id and p.updated_at == updated_at
    record = g.as_record()["products"][0]
    assert record["product_id"] == str(product_id)
    assert record["updated_at"] == updated_at.isoformat()
    # Another tenant grounds on nothing for this connection (RLS).
    _ensure_tenant(TENANT_B, "t-replies-e2e-b")
    assert catalog_grounding_for(TENANT_B, connection_id).products == ()


def test_pending_drafts_carry_the_author_and_the_publication(  # m-24842989
) -> None:
    """The review queue joins `threads` (media id) and, outer, `monitored_media`
    (caption): without a media row the draft still shows, caption empty; with one, the
    caption comes through. The candidate query carries author + media id too."""
    version = _fresh_version()
    connection_id, candidate, _user_id = _seed_pos_comment(TENANT_A, version)
    repo = PostgresReplyRepository()
    (found,) = repo.list_positive_comments_without_draft(
        tenant_id=TENANT_A, connection_id=connection_id, version=version
    )
    assert found.author_username == "cliente.feliz"
    assert found.external_media_id == candidate.external_media_id

    repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=found,
        gate_reason="test",
        generator_version="qua22.1:test-model",
        generated_text="¡Gracias!",
    )
    (pending,) = repo.list_pending_drafts(tenant_id=TENANT_A, connection_id=connection_id)
    assert pending.author_username == "cliente.feliz"
    assert pending.external_media_id == candidate.external_media_id
    assert pending.media_caption == ""

    with tenant_session(TENANT_A) as session:
        session.add(
            MonitoredMedia(
                tenant_id=TENANT_A,
                connection_id=connection_id,
                external_media_id=candidate.external_media_id,
                is_monitored=True,
                caption="Shawarma de pollo",
            )
        )
        session.commit()
    (pending,) = repo.list_pending_drafts(tenant_id=TENANT_A, connection_id=connection_id)
    assert pending.media_caption == "Shawarma de pollo"

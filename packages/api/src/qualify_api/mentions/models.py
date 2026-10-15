"""ORM models for the `mentions` module (QUA-49). DDL/RLS/grants are migration 0013's
job; these mirror it for typed access via the sanctioned sessions — same relationship
`inbox/models.py` and `sentiment/models.py` have to their own migrations.

Two tables, same split `inbox`/`sentiment` already establish between "the fact" and "the
derived signal computed from it": `Mention` is the fact (one row per real Instagram
mention of the connected account, resolved to a tenant), `MentionSentimentResult` is an
append-only, versioned analysis of that fact's text — never merged into `Mention` itself,
so re-analyzing under a new model version never mutates or duplicates the underlying
mention. `Mention` is deliberately its OWN entity, not a row in `messages`: a mention is
not a conversational message (it has no thread, no direction, no reply window), and
forcing it into that shape to reuse `CommentSentimentResult`'s plumbing would misrepresent
what actually happened on Instagram — see `mentions/sentiment.py`'s module docstring for
how the sentiment analysis itself is still reused without that conflation.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
)
from sqlalchemy import (
    text as sql_now,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base

# The only platform this table's CHECK constraint accepts today (QUA-49 scope: Instagram
# only, per the explicit "no cambios relacionados con TikTok" instruction). Widening this
# is a migration, not a code change, same posture `Thread.channel`'s CHECK takes.
PLATFORM_INSTAGRAM = "instagram"


class Mention(Base):
    """One real Instagram mention of the connected account, resolved to a tenant.

    Idempotency is a database-owned invariant, not this class's job: migration 0013
    creates `uq_mention_natural_key` as an EXPRESSION unique index over
    `(connection_id, media_id, COALESCE(comment_id, ''))` — a plain column-list
    `UniqueConstraint` would not do, because Postgres treats two NULLs as distinct, and a
    caption mention (no `comment_id`) must still dedupe against a re-delivered webhook for
    the same media. See migration 0013's docstring for why this mirrors
    `comment_sentiment_results`' own `COALESCE(model_revision, '')` reasoning.

    Carries the composite FK `(connection_id, tenant_id) -> social_connections` (R2
    discipline), so a row whose tenant disagrees with its connection is structurally
    unbuildable — same guarantee `inbox`/`sentiment` models already establish.
    """

    __tablename__ = "mentions"
    __table_args__ = (
        CheckConstraint(f"platform = '{PLATFORM_INSTAGRAM}'", name="ck_mention_platform"),
        CheckConstraint(
            "enrichment_status IN ('PENDING','ENRICHED','ENRICHMENT_FAILED')",
            name="ck_mention_enrichment_status",
        ),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_mention_conn_tenant",
        ),
        # Anti-drift target for MentionSentimentResult's composite FK (R2 discipline).
        Index("ux_mention_id_tenant", "id", "tenant_id", unique=True),
        Index("ix_mention_tenant", "tenant_id"),
        # Read pattern this module's one query actually uses: newest mentions for a
        # tenant, optionally filtered by connection — see repository.py's `list_mentions`.
        Index("ix_mention_tenant_received", "tenant_id", "received_at"),
        # `uq_mention_natural_key` (the COALESCE expression index) is created via raw SQL
        # in migration 0013 — same reason `comment_sentiment_results`' own versioning
        # index is, per that table's own docstring: SQLAlchemy's declarative `Index` does
        # not model expression indexes cleanly, and Postgres enforces it at INSERT time
        # regardless of whether the ORM layer can express it.
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False, server_default=PLATFORM_INSTAGRAM)
    # Denormalized from the webhook event / resolve_external_account, not re-derived from
    # the connection at read time — an audit trail of what the event actually named, even
    # if `social_connections.external_account_id` is later rotated.
    external_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    media_id: Mapped[str] = mapped_column(Text, nullable=False)
    comment_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- content, populated by mentioned_media/mentioned_comment enrichment ---
    # All nullable: enrichment can fail (Meta call error, still-pending Advanced Access)
    # without blocking persistence of the mention FACT itself (`enrichment_status` records
    # which case this is). Deliberately no `views`/`plays` column anywhere in this table —
    # see `qualify_shared.social.ig_shapes.MENTIONED_MEDIA_NO_VIEWS_CITATION`: Meta does
    # not expose that metric for content the connected account does not own, for either
    # endpoint, and inventing a column for it would silently invite a fabricated value.
    # `caption` (from `mentioned_media`, a mention outside a comment) and `text` (from
    # `mentioned_comment`, a mention inside a comment) are DIFFERENT Meta fields on
    # different nodes — never merged into one column. Exactly one is populated per row,
    # decided by whether `comment_id` is set (mirrors `MentionsChangeValue`'s own
    # caption-vs-comment split).
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_username: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    like_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The mentioned content's own creation date (from mentioned_media/mentioned_comment),
    # distinct from `received_at` (when OUR webhook delivered the event) — a mention can
    # be delivered well after the underlying comment/caption was posted.
    content_posted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # QUA-152 (migration 0052): the media's link on Instagram, read by a best-effort call
    # after the content; NULL when Meta did not return it. Never built from an id.
    permalink: Mapped[str | None] = mapped_column(Text, nullable=True)
    # QUA-152 (migration 0054): the last SUCCESSFUL re-read from the network, and the last
    # attempt (successful or not). NULL = never re-read since ingestion.
    content_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_refresh_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # QUA-152 (migration 0055): fingerprint of what the sentiment analyzer reads (comment
    # text, else caption). Generated by Postgres, so it can never drift from the text; a
    # sentiment result counts only while it was computed on this exact fingerprint.
    analysis_text_md5: Mapped[str | None] = mapped_column(
        Text, Computed("md5(coalesce(text, caption))", persisted=True), nullable=True
    )

    enrichment_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    received_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)


class MentionSentimentResult(Base):
    """One (mention, model version) sentiment analysis. Append-only, same posture
    `CommentSentimentResult` already establishes: a row is superseded by a new one under a
    new `detector_version`/`pipeline_version`/`model_id`/`model_revision`, never edited in
    place. See `mentions/sentiment.py` for the service that populates this table by
    reusing the SAME underlying model call `qualify_models.social.ig_comments.analyze_text`
    already provides for comments — the reuse is at the model-invocation layer, not by
    routing mentions through `messages`/`comment_sentiment_results`.
    """

    __tablename__ = "mention_sentiment_results"
    __table_args__ = (
        CheckConstraint("label IN ('POS','NEG','NEU')", name="ck_mention_sentiment_label"),
        ForeignKeyConstraint(
            ["mention_id", "tenant_id"],
            ["mentions.id", "mentions.tenant_id"],
            name="fk_mention_sentiment_mention_tenant",
        ),
        Index("ix_mention_sentiment_mention", "mention_id"),
        # `uq_mention_sentiment_analysis` (the COALESCE versioning index) is created via
        # raw SQL in migration 0013 — same reasoning as `comment_sentiment_results`.
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    mention_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    detector_version: Mapped[str] = mapped_column(Text, nullable=False)
    pipeline_version: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    # QUA-152 (migration 0055): `Mention.analysis_text_md5` of the text this result was
    # computed on. Part of the unique index: a new text is a new row, never an overwrite.
    text_md5: Mapped[str | None] = mapped_column(Text, nullable=True)
    analyzed_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)


class MentionSentimentFailure(Base):
    """One FAILED sentiment attempt on a mention under one analysis version (QUA-152,
    migration 0051). Append-only: the attempt count is the number of rows for (mention,
    version), so retries are bounded without any UPDATE. `error_class` is the exception's
    class name only — never a message, which could echo the analyzed (user) text."""

    __tablename__ = "mention_sentiment_failures"
    __table_args__ = (
        CheckConstraint(
            "char_length(error_class) BETWEEN 1 AND 200",
            name="ck_mention_sentiment_failure_error_class",
        ),
        ForeignKeyConstraint(
            ["mention_id", "tenant_id"],
            ["mentions.id", "mentions.tenant_id"],
            name="fk_mention_sentiment_failure_mention_tenant",
        ),
        Index("ix_mention_sentiment_failure_mention", "mention_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    mention_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    detector_version: Mapped[str] = mapped_column(Text, nullable=False)
    pipeline_version: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_class: Mapped[str] = mapped_column(Text, nullable=False)
    # QUA-152 (migration 0055): attempts are counted per text — an edit starts from zero.
    text_md5: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)

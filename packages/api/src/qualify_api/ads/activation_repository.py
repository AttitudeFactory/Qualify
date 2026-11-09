"""Durable preview/confirmation records, with independent write-ahead activation claims."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from threading import RLock
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.promotion_repository import RequestConflict


@dataclass(frozen=True)
class ActivationReview:
    id: UUID
    tenant_id: UUID
    promotion_id: UUID
    request_hash: str
    preview_html: str
    preview_hash: str
    checks_snapshot: dict[str, Any]
    expires_at: datetime
    prepared_by: UUID
    state: str = "ready"
    confirmed_by: UUID | None = None
    confirmed_at: datetime | None = None
    claim_token: UUID | None = None


class ActivationRepository(Protocol):
    def get(self, tenant_id: UUID, review_id: UUID) -> ActivationReview | None: ...
    def for_promotion(self, tenant_id: UUID, promotion_id: UUID) -> ActivationReview | None: ...
    def create(self, review: ActivationReview) -> ActivationReview: ...
    def claim(self, review: ActivationReview, actor: UUID, now: datetime, token: UUID) -> bool: ...
    def finish(self, tenant_id: UUID, review_id: UUID, token: UUID, state: str) -> None: ...


def _record(row: Any) -> ActivationReview | None:
    return (
        ActivationReview(**{k: row[k] for k in ActivationReview.__dataclass_fields__})
        if row
        else None
    )


class PostgresActivationRepository:
    def get(self, tenant_id: UUID, review_id: UUID) -> ActivationReview | None:
        with tenant_session(tenant_id, independent=True) as session:
            return _record(
                session.execute(
                    text("SELECT * FROM ad_promotion_activations WHERE id=:id"), {"id": review_id}
                )
                .mappings()
                .first()
            )

    def for_promotion(self, tenant_id: UUID, promotion_id: UUID) -> ActivationReview | None:
        with tenant_session(tenant_id, independent=True) as session:
            return _record(
                session.execute(
                    text("SELECT * FROM ad_promotion_activations WHERE promotion_id=:id"),
                    {"id": promotion_id},
                )
                .mappings()
                .first()
            )

    def create(self, review: ActivationReview) -> ActivationReview:
        import json

        with tenant_session(review.tenant_id, independent=True) as session:
            # Match the approval snapshot, not merely a tenant-valid UUID.
            promotion = session.execute(
                text("SELECT request_hash,approved_by FROM ad_promotions WHERE id=:id FOR UPDATE"),
                {"id": review.promotion_id},
            ).first()
            if (
                not promotion
                or promotion.request_hash != review.request_hash
                or (promotion.approved_by != review.prepared_by)
            ):
                raise RequestConflict("review differs from promotion approval")
            session.execute(
                text("""INSERT INTO ad_promotion_activations
                (id,tenant_id,promotion_id,request_hash,preview_html,preview_hash,checks_snapshot,
                 pipeline_version,expires_at,prepared_by)
                VALUES (:id,:tenant,:promotion,:hash,:html,:preview,CAST(:checks AS jsonb),
                        'promotion-wizard-v1',:expires,:actor)
                ON CONFLICT(promotion_id) DO NOTHING"""),
                {
                    "id": review.id,
                    "tenant": review.tenant_id,
                    "promotion": review.promotion_id,
                    "hash": review.request_hash,
                    "html": review.preview_html,
                    "preview": review.preview_hash,
                    "checks": json.dumps(review.checks_snapshot),
                    "expires": review.expires_at,
                    "actor": review.prepared_by,
                },
            )
            saved = _record(
                session.execute(
                    text("SELECT * FROM ad_promotion_activations WHERE promotion_id=:id"),
                    {"id": review.promotion_id},
                )
                .mappings()
                .one()
            )
            assert saved is not None
            if (saved.request_hash, saved.preview_hash, saved.prepared_by) != (
                review.request_hash,
                review.preview_hash,
                review.prepared_by,
            ):
                raise RequestConflict("promotion already has another immutable review")
            return saved

    def claim(self, review: ActivationReview, actor: UUID, now: datetime, token: UUID) -> bool:
        with tenant_session(review.tenant_id, independent=True) as session:
            # Use the same parent→child lock order as creation.
            session.execute(
                text("SELECT id FROM ad_promotions WHERE id=:id FOR UPDATE"),
                {"id": review.promotion_id},
            ).one()
            row = session.execute(
                text("""UPDATE ad_promotion_activations
                SET state='in_flight',confirmed_by=:actor,confirmed_at=:now,claim_token=:token
                WHERE id=:id AND state='ready' AND prepared_by=:actor AND expires_at>:now
                  AND request_hash=:hash AND preview_hash=:preview RETURNING promotion_id"""),
                {
                    "id": review.id,
                    "actor": actor,
                    "now": now,
                    "token": token,
                    "hash": review.request_hash,
                    "preview": review.preview_hash,
                },
            ).first()
            if row:
                session.execute(
                    text("UPDATE ad_promotions SET status='activating' WHERE id=:id"),
                    {"id": row.promotion_id},
                )
            return row is not None

    def finish(self, tenant_id: UUID, review_id: UUID, token: UUID, state: str) -> None:
        if state not in {"unknown", "active"}:
            raise ValueError("invalid activation outcome")
        with tenant_session(tenant_id, independent=True) as session:
            parent = session.scalar(
                text("SELECT promotion_id FROM ad_promotion_activations WHERE id=:id"),
                {"id": review_id},
            )
            if parent is None:
                return
            session.execute(
                text("SELECT id FROM ad_promotions WHERE id=:id FOR UPDATE"), {"id": parent}
            ).one()
            changed = session.execute(
                text(
                    "UPDATE ad_promotion_activations SET state=:state "
                    "WHERE id=:id AND claim_token=:token AND state IN ('in_flight','unknown') "
                    "RETURNING promotion_id"
                ),
                {"id": review_id, "token": token, "state": state},
            ).first()
            if changed:
                session.execute(
                    text("UPDATE ad_promotions SET status=:state WHERE id=:id"),
                    {
                        "id": parent,
                        "state": "active" if state == "active" else "activation_unknown",
                    },
                )


class MemoryActivationRepository:
    """Explicit test repository: state survives new workflow objects in the same test."""

    def __init__(self) -> None:
        self.rows: dict[UUID, ActivationReview] = {}
        self._lock = RLock()

    def get(self, tenant_id: UUID, review_id: UUID) -> ActivationReview | None:
        row = self.rows.get(review_id)
        return deepcopy(row) if row and row.tenant_id == tenant_id else None

    def for_promotion(self, tenant_id: UUID, promotion_id: UUID) -> ActivationReview | None:
        return next(
            (
                deepcopy(r)
                for r in self.rows.values()
                if r.tenant_id == tenant_id and r.promotion_id == promotion_id
            ),
            None,
        )

    def create(self, review: ActivationReview) -> ActivationReview:
        with self._lock:
            old = self.for_promotion(review.tenant_id, review.promotion_id)
            if old:
                if (old.request_hash, old.preview_hash, old.prepared_by) != (
                    review.request_hash,
                    review.preview_hash,
                    review.prepared_by,
                ):
                    raise RequestConflict("promotion already has another immutable review")
                return old
            if review.state != "ready":
                raise ValueError("expected new preview")
            self.rows[review.id] = deepcopy(review)
            return deepcopy(review)

    def claim(self, review: ActivationReview, actor: UUID, now: datetime, token: UUID) -> bool:
        with self._lock:
            row = self.get(review.tenant_id, review.id)
            if not row or row.state != "ready" or row.prepared_by != actor or row.expires_at <= now:
                return False
            if (row.request_hash, row.preview_hash) != (review.request_hash, review.preview_hash):
                return False
            self.rows[row.id] = replace(
                row, state="in_flight", confirmed_by=actor, confirmed_at=now, claim_token=token
            )
            return True

    def finish(self, tenant_id: UUID, review_id: UUID, token: UUID, state: str) -> None:
        if state not in {"unknown", "active"}:
            raise ValueError("invalid activation outcome")
        with self._lock:
            row = self.get(tenant_id, review_id)
            if row and row.claim_token == token and row.state in {"in_flight", "unknown"}:
                self.rows[row.id] = replace(row, state=state)


def new_review_id() -> UUID:
    return uuid4()

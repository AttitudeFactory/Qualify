"""Promotion repositories; write-ahead calls commit outside any enclosing unit of work."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.client import Resource
from qualify_api.ads.promotions import (
    ADAPTER_VERSION,
    ID_COLUMNS,
    CreationStep,
    Promotion,
    PromotionRequest,
    fingerprint,
)


class RequestConflict(ValueError):
    """A request key cannot authorize a different payload or spending approval."""


def _promotion(row: Any) -> Promotion:
    return Promotion(
        row["id"],
        deepcopy(row["request_snapshot"]),
        row["status"],
        {r: row[c] for r, c in ID_COLUMNS.items() if row[c] is not None},
    )


class PostgresPromotionRepository:
    def by_request_key(self, tenant_id: UUID, request_key: str) -> Promotion | None:
        with tenant_session(tenant_id, independent=True) as session:
            row = (
                session.execute(
                    text("SELECT * FROM ad_promotions WHERE request_key=:key"), {"key": request_key}
                )
                .mappings()
                .first()
            )
            return _promotion(row) if row else None

    def create_or_get(self, request: PromotionRequest) -> Promotion:
        snapshot = request.snapshot()
        digest = fingerprint(snapshot)
        with tenant_session(request.tenant_id, independent=True) as session:
            # RLS is not sufficient for cross-tenant FK membership: validate under
            # this tenant, and enforce composite source keys in the schema too.
            if not session.execute(
                text("SELECT 1 FROM brands WHERE id=:id"), {"id": request.brand_id}
            ).scalar():
                raise ValueError("brand is outside the tenant")
            if not session.execute(
                text("SELECT 1 FROM users WHERE id=:id"), {"id": request.approved_by}
            ).scalar():
                raise ValueError("approver is outside the tenant")
            if (
                request.content_draft_id
                and not session.execute(
                    text("SELECT 1 FROM content_drafts WHERE id=:id AND brand_id=:brand"),
                    {"id": request.content_draft_id, "brand": request.brand_id},
                ).scalar()
            ):
                raise ValueError("content provenance is outside the brand")
            if request.publish_attempt_id:
                attempt = session.execute(
                    text(
                        "SELECT p.published_media_id, e.post_id FROM publish_attempts p "
                        "JOIN social_connections c ON c.id=p.connection_id "
                        "AND c.tenant_id=p.tenant_id "
                        "LEFT JOIN calendar_events e ON e.publish_attempt_id=p.id "
                        "AND e.tenant_id=p.tenant_id "
                        "WHERE p.id=:id AND c.brand_id=:brand"
                    ),
                    {"id": request.publish_attempt_id, "brand": request.brand_id},
                ).first()
                if (
                    attempt is None
                    or (
                        request.source_media_id is not None
                        and attempt.published_media_id != request.source_media_id
                    )
                    or (
                        request.content_draft_id is not None
                        and attempt.post_id != request.content_draft_id
                    )
                ):
                    raise ValueError("published provenance does not match the brand or media")
            columns = [
                "tenant_id",
                "brand_id",
                "request_key",
                "meta_ad_account_id",
                "content_draft_id",
                "publish_attempt_id",
                "source_media_id",
                "objective",
                "special_ad_categories",
                "cta_type",
                "link_url",
                "budget_kind",
                "budget_minor",
                "currency",
                "start_time",
                "end_time",
                "targeting",
                "approved_by",
                "approved_at",
            ]
            json_columns = {"special_ad_categories", "targeting", "request_snapshot"}
            values = {key: snapshot[key] for key in columns}
            values.update(
                request_snapshot=snapshot, request_hash=digest, adapter_version=ADAPTER_VERSION
            )
            columns.extend(("request_snapshot", "request_hash", "adapter_version"))
            for key in json_columns:
                values[key] = json.dumps(values[key])
            placeholders = [
                f"CAST(:{c} AS jsonb)" if c in json_columns else f":{c}" for c in columns
            ]
            session.execute(
                text(
                    f"INSERT INTO ad_promotions ({','.join(columns)}) "
                    f"VALUES ({','.join(placeholders)}) "
                    "ON CONFLICT (tenant_id,request_key) DO NOTHING"
                ),
                values,
            )
            row = (
                session.execute(
                    text("SELECT * FROM ad_promotions WHERE request_key=:key"),
                    {"key": request.request_key},
                )
                .mappings()
                .one()
            )
            if row["request_hash"] != digest:
                raise RequestConflict("request key already names a different approval snapshot")
            result = _promotion(row)
        return result

    def get(self, tenant_id: UUID, promotion_id: UUID) -> Promotion | None:
        with tenant_session(tenant_id, independent=True) as session:
            row = (
                session.execute(
                    text("SELECT * FROM ad_promotions WHERE id=:id"), {"id": promotion_id}
                )
                .mappings()
                .first()
            )
            return _promotion(row) if row else None

    def step(self, tenant_id: UUID, promotion_id: UUID, resource: Resource) -> CreationStep | None:
        with tenant_session(tenant_id, independent=True) as session:
            row = (
                session.execute(
                    text(
                        "SELECT * FROM ad_promotion_steps "
                        "WHERE promotion_id=:id AND resource=:resource"
                    ),
                    {"id": promotion_id, "resource": resource},
                )
                .mappings()
                .first()
            )
            return (
                CreationStep(
                    row["resource"],
                    deepcopy(row["payload"]),
                    row["state"],
                    row["claim_token"],
                    row["meta_id"],
                )
                if row
                else None
            )

    def claim(
        self,
        tenant_id: UUID,
        promotion_id: UUID,
        resource: Resource,
        payload: dict[str, Any],
        token: UUID,
    ) -> bool:
        if resource not in ID_COLUMNS:
            raise ValueError("unsupported creation resource")
        with tenant_session(tenant_id, independent=True) as session:
            # Lock the parent so two distinct next steps cannot race through dependencies.
            row = (
                session.execute(
                    text("SELECT * FROM ad_promotions WHERE id=:id FOR UPDATE"),
                    {"id": promotion_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise LookupError("promotion not found")
            from qualify_api.ads.promotions import STEPS, step_payload

            promotion = _promotion(row)
            if any(r not in promotion.ids for r in STEPS[: STEPS.index(resource)]):
                raise ValueError("parent creation is incomplete")
            if payload != step_payload(promotion, resource):
                raise ValueError("creation payload differs from approved snapshot")
            result = session.execute(
                text(
                    "INSERT INTO ad_promotion_steps "
                    "(tenant_id,promotion_id,resource,payload,claim_token,state) "
                    "VALUES (:tenant,:id,:resource,CAST(:payload AS jsonb),:token,'in_flight') "
                    "ON CONFLICT (promotion_id,resource) DO NOTHING RETURNING promotion_id"
                ),
                {
                    "tenant": tenant_id,
                    "id": promotion_id,
                    "resource": resource,
                    "payload": json.dumps(payload),
                    "token": token,
                },
            ).first()
            if result:
                session.execute(
                    text("UPDATE ad_promotions SET status='creating' WHERE id=:id"),
                    {"id": promotion_id},
                )
        return result is not None

    def complete(
        self, tenant_id: UUID, promotion_id: UUID, resource: Resource, token: UUID, meta_id: str
    ) -> bool:
        if resource not in ID_COLUMNS or not meta_id.isdigit():
            raise ValueError("invalid resource or remote id")
        with tenant_session(tenant_id, independent=True) as session:
            if not session.execute(
                text("SELECT id FROM ad_promotions WHERE id=:id FOR UPDATE"), {"id": promotion_id}
            ).first():
                return False
            result = session.execute(
                text(
                    "UPDATE ad_promotion_steps SET state='completed',meta_id=:meta "
                    "WHERE promotion_id=:id AND resource=:resource AND state='in_flight' "
                    "AND claim_token=:token RETURNING promotion_id"
                ),
                {"meta": meta_id, "id": promotion_id, "resource": resource, "token": token},
            ).first()
            if result:
                status = "paused" if resource == "ads" else "creating"
                session.execute(
                    text(
                        f"UPDATE ad_promotions SET {ID_COLUMNS[resource]}=:meta,status=:status "
                        "WHERE id=:id"
                    ),
                    {"meta": meta_id, "id": promotion_id, "status": status},
                )
        return result is not None


class MemoryPromotionRepository:
    """Stateful fake with atomic operations and durable snapshots across service instances."""

    def __init__(self) -> None:
        self.promotions: dict[UUID, Promotion] = {}
        self.steps: dict[tuple[UUID, Resource], CreationStep] = {}
        self._lock = RLock()

    def by_request_key(self, tenant_id: UUID, request_key: str) -> Promotion | None:
        return next(
            (
                deepcopy(p)
                for p in self.promotions.values()
                if p.request["tenant_id"] == str(tenant_id)
                and p.request["request_key"] == request_key
            ),
            None,
        )

    def create_or_get(self, request: PromotionRequest) -> Promotion:
        snapshot = request.snapshot()
        with self._lock:
            for row in self.promotions.values():
                if (
                    row.request["tenant_id"] == str(request.tenant_id)
                    and row.request["request_key"] == request.request_key
                ):
                    if row.request != snapshot:
                        raise RequestConflict(
                            "request key already names a different approval snapshot"
                        )
                    return deepcopy(row)
            row = Promotion(uuid4(), snapshot)
            self.promotions[row.id] = row
            return deepcopy(row)

    def get(self, tenant_id: UUID, promotion_id: UUID) -> Promotion | None:
        row = self.promotions.get(promotion_id)
        return deepcopy(row) if row and row.request["tenant_id"] == str(tenant_id) else None

    def step(self, tenant_id: UUID, promotion_id: UUID, resource: Resource) -> CreationStep | None:
        return (
            deepcopy(self.steps.get((promotion_id, resource)))
            if self.get(tenant_id, promotion_id)
            else None
        )

    def claim(
        self,
        tenant_id: UUID,
        promotion_id: UUID,
        resource: Resource,
        payload: dict[str, Any],
        token: UUID,
    ) -> bool:
        from qualify_api.ads.promotions import STEPS, step_payload

        with self._lock:
            row = self.get(tenant_id, promotion_id)
            if row is None:
                raise LookupError("promotion not found")
            if any(
                r not in row.ids for r in STEPS[: STEPS.index(resource)]
            ) or payload != step_payload(row, resource):
                raise ValueError("invalid creation sequence or payload")
            key = (promotion_id, resource)
            if key in self.steps:
                return False
            self.steps[key] = CreationStep(resource, deepcopy(payload), "in_flight", token)
            self.promotions[row.id] = replace(row, status="creating")
            return True

    def complete(
        self, tenant_id: UUID, promotion_id: UUID, resource: Resource, token: UUID, meta_id: str
    ) -> bool:
        with self._lock:
            row, step = (
                self.get(tenant_id, promotion_id),
                self.step(tenant_id, promotion_id, resource),
            )
            if not row or not step or step.state != "in_flight" or step.claim_token != token:
                return False
            if not meta_id.isdigit():
                raise ValueError("invalid remote id")
            self.steps[promotion_id, resource] = replace(step, state="completed", meta_id=meta_id)
            self.promotions[row.id] = replace(
                row,
                ids={**row.ids, resource: meta_id},
                status="paused" if resource == "ads" else "creating",
            )
            return True

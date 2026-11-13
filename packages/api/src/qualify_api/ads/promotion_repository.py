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
    def current_enhancements(self, tenant_id: UUID, brand_id: UUID) -> dict[str, Any]:
        from qualify_api.ads.enhancements_service import read_policy

        with tenant_session(tenant_id, independent=True) as session:
            return read_policy(session, tenant_id, brand_id).snapshot()

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
            existing = (
                session.execute(
                    text("SELECT * FROM ad_promotions WHERE request_key=:key"),
                    {"key": request.request_key},
                )
                .mappings()
                .first()
            )
            if existing:
                if existing["request_hash"] != digest:
                    raise RequestConflict("request key already names a different approval snapshot")
                return _promotion(existing)
            if request.audience_snapshot:
                from qualify_api.ads.audience import AudienceDraft

                audience = AudienceDraft.from_snapshot(request.audience_snapshot)
                for selection in audience.custom_audiences:
                    selected = (
                        session.execute(
                            text("""SELECT r.name,r.kind,r.meta_audience_id
                        FROM ad_custom_audiences r JOIN ad_accounts a
                          ON a.id=r.ad_account_id AND a.tenant_id=r.tenant_id
                        JOIN social_connections c
                          ON c.id=r.connection_id AND c.tenant_id=r.tenant_id
                        JOIN publish_attempts p
                          ON p.connection_id=c.id AND p.tenant_id=c.tenant_id
                        WHERE r.id=:id AND r.brand_id=:brand AND a.brand_id=r.brand_id
                          AND a.ad_account_id=:account AND a.selected AND a.available
                          AND a.connection_id=r.connection_id AND c.brand_id=r.brand_id
                          AND r.credential_version=c.current_credential_version
                          AND a.credential_version=r.credential_version
                          AND c.external_account_id=r.source_instagram_id AND c.status='active'
                          AND c.purge_started_at IS NULL AND c.purged_at IS NULL
                          AND p.id=:published AND p.published_media_id=:media
                          AND r.status='created' FOR SHARE OF r,a,c,p"""),
                            {
                                "id": UUID(selection.local_id),
                                "brand": request.brand_id,
                                "account": request.meta_ad_account_id,
                                "published": request.publish_attempt_id,
                                "media": request.source_media_id,
                            },
                        )
                        .mappings()
                        .first()
                    )
                    if selected is None or any(
                        selected[key] != value
                        for key, value in (
                            ("name", selection.name),
                            ("kind", selection.kind),
                            ("meta_audience_id", selection.id),
                        )
                    ):
                        raise ValueError(
                            "custom audience does not match the approved brand and account"
                        )
            from qualify_api.ads.enhancements import validate_request_policy
            from qualify_api.ads.enhancements_service import read_policy

            policy = validate_request_policy(request, require=True)
            if (
                policy.snapshot()
                != read_policy(session, request.tenant_id, request.brand_id).snapshot()
            ):
                raise RequestConflict("brand creative permissions changed; approve a new request")
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
            if request.messaging_snapshot:
                from qualify_api.ads.messaging import MessagingTarget
                from qualify_api.ads.messaging_attribution import _digits

                target = MessagingTarget.from_snapshot(request.messaging_snapshot)
                binding = (
                    session.execute(
                        text("""
                        SELECT source.current_credential_version AS source_version,
                               destination.current_credential_version AS target_version,
                               source.linked_page_id,source.external_account_id AS instagram_id,
                               phone.display_phone_number
                          FROM publish_attempts pub JOIN social_connections source
                            ON source.id=pub.connection_id AND source.tenant_id=pub.tenant_id
                          JOIN social_connections destination ON destination.id=:destination
                            AND destination.tenant_id=source.tenant_id
                            AND destination.brand_id=source.brand_id
                          LEFT JOIN whatsapp_phone_numbers phone
                            ON phone.connection_id=destination.id
                            AND phone.tenant_id=destination.tenant_id
                            AND phone.brand_id=destination.brand_id
                            AND phone.phone_number_id=:phone
                         WHERE pub.id=:published AND pub.status='published'
                           AND pub.published_media_id=:media AND source.id=:source
                           AND source.brand_id=:brand AND source.platform='instagram'
                           AND source.status='active' AND destination.status='active'
                           AND source.purge_started_at IS NULL AND source.purged_at IS NULL
                           AND destination.purge_started_at IS NULL
                           AND destination.purged_at IS NULL AND destination.platform=:platform
                         FOR SHARE OF source,destination,pub
                    """),
                        {
                            "destination": target.target_connection_id,
                            "source": target.source_connection_id,
                            "phone": target.phone_number_id,
                            "published": request.publish_attempt_id,
                            "media": request.source_media_id,
                            "brand": request.brand_id,
                            "platform": "whatsapp"
                            if target.destination_type == "WHATSAPP"
                            else "instagram",
                        },
                    )
                    .mappings()
                    .one_or_none()
                )
                if (
                    binding is None
                    or binding["source_version"] != target.source_credential_version
                    or binding["target_version"] != target.target_credential_version
                    or binding["linked_page_id"] != target.page_id
                    or binding["instagram_id"] != request.creative["instagram_user_id"]
                    or (
                        target.destination_type == "WHATSAPP"
                        and _digits(binding["display_phone_number"]) != target.whatsapp_phone_number
                    )
                ):
                    raise ValueError("messaging destination does not match the published source")
            if request.lead_form_snapshot:
                from qualify_api.ads.lead_ads import LeadFormTarget

                target = LeadFormTarget.from_snapshot(request.lead_form_snapshot)
                # A published form is terminal and immutable (0143 trigger); lock it and its
                # connection so a purge or reconnect cannot race the approval insert.
                bound = session.execute(
                    text("""SELECT 1 FROM ad_lead_forms f
                      JOIN social_connections c ON c.id=f.connection_id
                        AND c.tenant_id=f.tenant_id AND c.brand_id=f.brand_id
                      JOIN publish_attempts p ON p.connection_id=c.id AND p.tenant_id=c.tenant_id
                     WHERE f.id=:form AND f.status='published' AND f.meta_form_id=:remote
                       AND f.page_id=:page AND f.brand_id=:brand AND f.connection_id=:connection
                       AND f.credential_version=:version AND c.status='active'
                       AND c.linked_page_id=f.page_id
                       AND c.current_credential_version=f.credential_version
                       AND c.purge_started_at IS NULL AND c.purged_at IS NULL
                       AND p.id=:published AND p.published_media_id=:media
                       FOR SHARE OF f,c,p"""),
                    {
                        "form": target.form_id,
                        "remote": target.meta_form_id,
                        "page": target.page_id,
                        "brand": request.brand_id,
                        "connection": target.connection_id,
                        "version": target.credential_version,
                        "published": request.publish_attempt_id,
                        "media": request.source_media_id,
                    },
                ).first()
                if bound is None:
                    raise ValueError("lead form is not a published form of the promoted account")
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

    def __init__(self, *, enhancement_policies: Any = None) -> None:
        self.promotions: dict[UUID, Promotion] = {}
        self.steps: dict[tuple[UUID, Resource], CreationStep] = {}
        self._lock = RLock()
        self.enhancement_policies = enhancement_policies

    def current_enhancements(self, tenant_id: UUID, brand_id: UUID) -> dict[str, Any]:
        from qualify_api.ads.enhancements import BrandEnhancementSettings

        if self.enhancement_policies is not None:
            return self.enhancement_policies(tenant_id, brand_id).snapshot()
        return BrandEnhancementSettings(tenant_id, brand_id).snapshot()

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
            from qualify_api.ads.enhancements import validate_request_policy

            policy = validate_request_policy(request, require=True)
            if policy.snapshot() != self.current_enhancements(request.tenant_id, request.brand_id):
                raise RequestConflict("brand creative permissions changed; approve a new request")
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

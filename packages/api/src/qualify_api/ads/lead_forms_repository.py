"""Tenant-scoped Meta forms, atomic publication claims and duplicate-safe inquiries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.lead_forms import (
    LeadFormDraft,
    LeadFormSummary,
    LeadFormUnavailable,
    MetaLeadSummary,
    draft_from_json,
)
from qualify_api.tenancy.acting import current_acting_login, require_acting_member


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def form_summary(row: object) -> LeadFormSummary:
    return LeadFormSummary(
        id=row.id,
        connection_id=row.connection_id,
        name=row.draft["name"],
        page_id=row.page_id,
        status=row.status,
        meta_form_id=row.meta_form_id or "",
        draft=draft_from_json(row.draft),
        revision=row.revision,
    )


def get_form(tenant_id: UUID, form_id: UUID) -> dict:
    with tenant_session(tenant_id) as session:
        row = session.execute(
            text("SELECT * FROM ad_lead_forms WHERE id=:id"), {"id": form_id}
        ).first()
        if row is None:
            raise LeadFormUnavailable("Este formulario ya no está disponible en tu negocio.")
        return dict(row._mapping)


def list_forms(tenant_id: UUID, connection_id: UUID) -> tuple[LeadFormSummary, ...]:
    with tenant_session(tenant_id) as session:
        rows = session.execute(
            text(
                "SELECT * FROM ad_lead_forms WHERE connection_id=:cid "
                "ORDER BY created_at DESC LIMIT 200"
            ),
            {"cid": connection_id},
        ).all()
        return tuple(form_summary(row) for row in rows)


def save_draft(
    tenant_id: UUID,
    connection: dict,
    draft: LeadFormDraft,
    form_id: UUID | None,
    expected_revision: int | None,
) -> LeadFormSummary:
    draft.payload()
    require_acting_member(tenant_id)
    values = {
        "id": form_id or uuid4(),
        "tid": tenant_id,
        "cid": connection["id"],
        "brand": connection["brand_id"],
        "page": connection["linked_page_id"],
        "version": connection["current_credential_version"],
        "draft": _json(asdict(draft)),
        "revision": expected_revision,
    }
    with tenant_session(tenant_id) as session:
        if form_id is None:
            row = session.execute(
                text("""INSERT INTO ad_lead_forms
                (id,tenant_id,connection_id,brand_id,page_id,credential_version,draft)
                VALUES (:id,:tid,:cid,:brand,:page,:version,CAST(:draft AS jsonb)) RETURNING *"""),
                values,
            ).one()
        else:
            row = session.execute(
                text("""UPDATE ad_lead_forms SET draft=CAST(:draft AS jsonb),
                revision=revision+1,updated_at=now(),credential_version=:version
                WHERE id=:id AND connection_id=:cid AND brand_id=:brand AND page_id=:page
                AND status='draft' AND revision=:revision RETURNING *"""),
                values,
            ).first()
            if row is None:
                raise LeadFormUnavailable(
                    "El formulario cambió o ya fue enviado. Vuelve a revisarlo."
                )
        return form_summary(row)


def claim_publication(tenant_id: UUID, form_id: UUID, expected_revision: int) -> dict:
    actor = current_acting_login()
    if actor is None:
        raise LeadFormUnavailable("Vuelve a entrar para confirmar el formulario.")
    require_acting_member(tenant_id)
    with tenant_session(tenant_id) as session:
        actor = session.scalar(
            text("""SELECT u.id FROM users u JOIN tenant_members m
            ON m.user_id=u.id AND m.tenant_id=:tid WHERE u.auth_user_id=:login"""),
            {"tid": tenant_id, "login": actor},
        )
        if actor is None:
            raise LeadFormUnavailable(
                "Tu aprobación no corresponde al acceso actual de este negocio."
            )
        row = session.execute(
            text("SELECT * FROM ad_lead_forms WHERE id=:id FOR UPDATE"), {"id": form_id}
        ).first()
        if row is None or row.status != "draft" or row.revision != expected_revision:
            raise LeadFormUnavailable("El formulario cambió o ya fue enviado. Vuelve a revisarlo.")
        snapshot = dict(row.draft)
        draft_from_json(snapshot).payload()
        digest = hashlib.sha256(_json(snapshot).encode()).hexdigest()
        result = session.execute(
            text("""UPDATE ad_lead_forms SET status='publishing',
            approved_by=:actor,approved_at=now(),approved_snapshot=CAST(:snapshot AS jsonb),
            approved_hash=:digest,updated_at=now() WHERE id=:id RETURNING *"""),
            {"id": form_id, "actor": actor, "snapshot": _json(snapshot), "digest": digest},
        ).one()
        return dict(result._mapping)


def finish_publication(
    tenant_id: UUID, form_id: UUID, *, meta_form_id: str | None
) -> LeadFormSummary:
    with tenant_session(tenant_id) as session:
        row = session.execute(
            text("""UPDATE ad_lead_forms SET status=:status,
            meta_form_id=:remote,updated_at=now()
            WHERE id=:id AND status='publishing' RETURNING *"""),
            {
                "id": form_id,
                "status": "published" if meta_form_id else "unknown",
                "remote": meta_form_id,
            },
        ).first()
        if row is None:
            raise LeadFormUnavailable("Comprueba el estado del formulario antes de continuar.")
        return form_summary(row)


def lead_summary(row: object) -> MetaLeadSummary:
    custom = {
        question.get("key"): question.get("label")
        for question in row.draft.get("questions", [])
        if question.get("kind") == "CUSTOM"
    }
    answers = {}
    for index, (key, value) in enumerate(row.answers.items()):
        if key in {"full_name", "email", "phone_number"}:
            continue
        label = custom.get(key) or f"Otra respuesta {index + 1}"
        answers[label] = value
    return MetaLeadSummary(
        id=row.id,
        full_name=row.full_name,
        phone=row.phone,
        email=row.email,
        form_name=row.draft["name"],
        meta_form_id=row.meta_form_id,
        meta_ad_id=row.meta_ad_id,
        promotion_id=row.promotion_id,
        created_at=row.source_created_at,
        contacted_at=row.contacted_at,
        answers=answers,
    )


def list_inquiries(tenant_id: UUID) -> tuple[MetaLeadSummary, ...]:
    with tenant_session(tenant_id) as session:
        rows = session.execute(
            text("""SELECT l.*,f.draft,f.meta_form_id FROM meta_lead_submissions l
            JOIN ad_lead_forms f ON f.id=l.form_id AND f.tenant_id=l.tenant_id
            ORDER BY l.contacted_at IS NOT NULL,l.source_created_at DESC LIMIT 200""")
        ).all()
        return tuple(lead_summary(row) for row in rows)


def mark_inquiry(tenant_id: UUID, lead_id: UUID, contacted: bool) -> MetaLeadSummary | None:
    require_acting_member(tenant_id)
    with tenant_session(tenant_id) as session:
        session.execute(
            text("""UPDATE meta_lead_submissions SET contacted_at=
            CASE WHEN :contacted THEN COALESCE(contacted_at,:now) ELSE NULL END WHERE id=:id"""),
            {"id": lead_id, "contacted": contacted, "now": datetime.now(UTC)},
        )
        row = session.execute(
            text("""SELECT l.*,f.draft,f.meta_form_id FROM meta_lead_submissions l
            JOIN ad_lead_forms f ON f.id=l.form_id AND f.tenant_id=l.tenant_id WHERE l.id=:id"""),
            {"id": lead_id},
        ).first()
        return lead_summary(row) if row else None

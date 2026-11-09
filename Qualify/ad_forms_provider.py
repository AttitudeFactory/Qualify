"""Whitelist form data for Reflex; all writes use the actual tenant-scoped service."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import UUID

from qualify_api.ads.lead_forms import LeadFormDraft, LeadFormQuestion, LeadFormSummary
from qualify_api.ads.lead_forms_service import (
    list_lead_form_connections,
    list_lead_forms,
    publish_lead_form,
    save_lead_form_draft,
    subscribe_lead_form,
    sync_lead_form,
)

from .ad_forms_vm import (
    AdFormDraftVM,
    AdFormVM,
    FormConnectionVM,
    custom_question_parts,
    form_status,
)


def backend_draft(draft: AdFormDraftVM) -> LeadFormDraft:
    questions = [
        LeadFormQuestion(kind=kind)
        for enabled, kind in (
            (draft.ask_name, "FULL_NAME"),
            (draft.ask_email, "EMAIL"),
            (draft.ask_phone, "PHONE"),
        )
        if enabled
    ]
    questions.extend(
        LeadFormQuestion(kind="CUSTOM", key=f"question_{index}", label=label, options=options)
        for index, (label, options) in enumerate(
            custom_question_parts(draft.custom_questions), start=1
        )
    )
    return LeadFormDraft(
        name=draft.name.strip(),
        privacy_policy_url=draft.privacy_url.strip(),
        thank_you_title=draft.thank_you_title.strip(),
        thank_you_body=draft.thank_you_body.strip(),
        thank_you_url=draft.thank_you_url.strip(),
        questions=tuple(questions),
        locale="ES_LA",
    )


def form_vm(row: LeadFormSummary) -> AdFormVM:
    draft = row.draft
    kinds = {question.kind for question in draft.questions}
    label, tone = form_status(row.status)
    return AdFormVM(
        id=str(row.id),
        connection_id=str(row.connection_id),
        name=row.name,
        status=row.status,
        status_label=label,
        tone=tone,
        editable=row.status == "draft",
        published=row.status == "published",
        revision=row.revision,
        draft=AdFormDraftVM(
            connection_id=str(row.connection_id),
            name=draft.name,
            ask_name="FULL_NAME" in kinds,
            ask_email="EMAIL" in kinds,
            ask_phone="PHONE" in kinds,
            custom_questions="\n".join(
                " | ".join((question.label, *question.options))
                for question in draft.questions
                if question.kind == "CUSTOM"
            ),
            privacy_url=draft.privacy_policy_url,
            thank_you_title=draft.thank_you_title,
            thank_you_body=draft.thank_you_body,
            thank_you_url=draft.thank_you_url,
        ),
    )


def form_screen(tenant_id: UUID) -> tuple[list[FormConnectionVM], list[AdFormVM]]:
    connections = list_lead_form_connections(tenant_id=tenant_id)
    forms = [
        replace(form_vm(row), page_label=connection.label)
        for connection in connections
        for row in list_lead_forms(tenant_id=tenant_id, connection_id=connection.id)
    ]
    return [
        FormConnectionVM(str(row.id), row.label, row.available, row.reason) for row in connections
    ], forms


def save_form(tenant_id: UUID, draft: AdFormDraftVM, form_id: str, revision: int) -> AdFormVM:
    row = save_lead_form_draft(
        tenant_id=tenant_id,
        connection_id=UUID(draft.connection_id),
        draft=backend_draft(draft),
        form_id=UUID(form_id) if form_id else None,
        expected_revision=revision if form_id else None,
    )
    return form_vm(row)


def publish_form(tenant_id: UUID, form_id: UUID, revision: int) -> AdFormVM:
    return form_vm(
        asyncio.run(
            publish_lead_form(
                tenant_id=tenant_id, form_id=form_id, confirmed=True, expected_revision=revision
            )
        )
    )


def sync_form(tenant_id: UUID, form_id: UUID) -> int:
    return asyncio.run(sync_lead_form(tenant_id=tenant_id, form_id=form_id))


def receive_form(tenant_id: UUID, form_id: UUID) -> None:
    asyncio.run(subscribe_lead_form(tenant_id=tenant_id, form_id=form_id, confirmed=True))

"""Page leadgen handler bound to frozen ownership, never tenant claims from Meta."""

from __future__ import annotations

from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.lead_forms import LeadFormUnavailable
from qualify_api.ads.lead_forms_client import meta_id
from qualify_api.ads.lead_forms_service import (
    _client,
    _form_guard,
    _page_access,
    _persist,
    _remote_form,
    _verify_ad,
    parse_lead,
)
from qualify_api.webhooks.processor import Outcome
from qualify_api.webhooks.repository import (
    STATUS_AMBIGUOUS,
    STATUS_DEAD,
    STATUS_ORPHAN,
    STATUS_PROCESSED,
    ClaimedEvent,
)

PAGE_LEADGEN_HANDLER_KEY = "page:leadgen"


def owned_form(event: ClaimedEvent, form_id: str) -> tuple[UUID, dict] | None:
    if not event.owners:
        return None
    matches = {}
    for tenant_id, connection_id in set(event.owners):
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text("""SELECT * FROM ad_lead_forms WHERE meta_form_id=:form
                AND connection_id=:cid AND page_id=:page AND status='published'"""),
                {"form": form_id, "cid": connection_id, "page": event.entry_id},
            ).all()
            for row in rows:
                matches[(tenant_id, row.id)] = (tenant_id, dict(row._mapping))
    if len(matches) > 1:
        raise LeadFormUnavailable("ambiguous_form_owner")
    return next(iter(matches.values()), None)


async def leadgen_handler(event: ClaimedEvent) -> Outcome:
    if event.object != "page" or event.field != "leadgen" or not isinstance(event.value, dict):
        return Outcome(STATUS_DEAD, "leadgen_contract")
    try:
        lead_id = meta_id(event.value.get("leadgen_id"))
        form_id = meta_id(event.value.get("form_id"))
        page_id = meta_id(event.value.get("page_id"))
        if page_id != event.entry_id:
            return Outcome(STATUS_DEAD, "leadgen_page_mismatch")
    except LeadFormUnavailable:
        return Outcome(STATUS_DEAD, "leadgen_contract")
    try:
        binding = owned_form(event, form_id)
    except LeadFormUnavailable:
        return Outcome(STATUS_AMBIGUOUS, "leadgen_owner_ambiguous")
    if binding is None:
        return Outcome(STATUS_ORPHAN, "leadgen_form_unbound")
    tenant_id, form = binding
    context = _form_guard(tenant_id, form)
    client = await _client(tenant_id, context)
    try:
        await _page_access(client, page_id)
        await _remote_form(client, form)
        raw = await client.read(lead_id, fields="id,form_id,ad_id,created_time,field_data")
        data = parse_lead(raw, form_id=form_id, leadgen_id=lead_id)
        # Never attribute from the notification; compare it only when provided.
        claimed_ad = event.value.get("ad_id")
        if claimed_ad is not None and claimed_ad != data["meta_ad_id"]:
            return Outcome(STATUS_DEAD, "leadgen_ad_mismatch")
        await _verify_ad(client, form, data)
        _persist(tenant_id, form, data, received_via="webhook")
        return Outcome(STATUS_PROCESSED)
    finally:
        await client.aclose()

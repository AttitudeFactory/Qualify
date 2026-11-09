"""Form editor, one-shot publication and read-only lead import composition."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads import lead_forms_repository as repository
from qualify_api.ads.lead_forms import (
    LeadFormConnection,
    LeadFormDraft,
    LeadFormSummary,
    LeadFormUnavailable,
    MetaLeadSummary,
    draft_from_json,
    safe_text,
)
from qualify_api.ads.lead_forms_client import LeadFormsClient, meta_id
from qualify_api.connections.ad_accounts import (
    _authenticated_client,
    _connection,
    _permission_reason,
)
from qualify_api.tenancy.acting import current_acting_login, require_acting_member


def _member(tenant_id: UUID) -> None:
    if current_acting_login() is None:
        raise LeadFormUnavailable("Vuelve a entrar para revisar los formularios de este negocio.")
    require_acting_member(tenant_id)


def _context(tenant_id: UUID, connection_id: UUID, *, version: int | None = None) -> dict:
    with tenant_session(tenant_id) as session:
        try:
            grant = _connection(session, connection_id)
        except ValueError:
            raise LeadFormUnavailable("Esta conexión ya no está disponible.") from None
        reason = _permission_reason(grant)
        if reason:
            raise LeadFormUnavailable(reason)
        if not {
            "leads_retrieval",
            "pages_manage_ads",
            "pages_manage_metadata",
            "pages_show_list",
        } <= set(grant.scopes):
            raise LeadFormUnavailable(
                "Actualiza el acceso con Meta para administrar formularios y recibir sus datos."
            )
        row = session.execute(
            text("""SELECT id,brand_id,linked_page_id,current_credential_version,
            COALESCE(external_username,external_account_id) AS label
            FROM social_connections WHERE id=:id AND status='active'
            AND purge_started_at IS NULL AND purged_at IS NULL"""),
            {"id": connection_id},
        ).first()
        if row is None or (version is not None and row.current_credential_version != version):
            raise LeadFormUnavailable("El acceso con Meta cambió. Vuelve a revisar el formulario.")
        meta_id(row.linked_page_id)
        return dict(row._mapping)


def list_lead_form_connections(*, tenant_id: UUID) -> tuple[LeadFormConnection, ...]:
    _member(tenant_id)
    with tenant_session(tenant_id) as session:
        rows = session.execute(
            text("""SELECT id,linked_page_id,
            COALESCE(external_username,external_account_id) AS label FROM social_connections
            WHERE platform='instagram' AND purged_at IS NULL AND purge_started_at IS NULL
            ORDER BY connected_at DESC""")
        ).all()
    result = []
    for row in rows:
        try:
            _context(tenant_id, row.id)
            reason = ""
        except LeadFormUnavailable as error:
            reason = str(error)
        result.append(
            LeadFormConnection(row.id, row.label, row.linked_page_id or "", not reason, reason)
        )
    return tuple(result)


def list_lead_forms(*, tenant_id: UUID, connection_id: UUID) -> tuple[LeadFormSummary, ...]:
    _member(tenant_id)
    return repository.list_forms(tenant_id, connection_id)


def save_lead_form_draft(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    draft: LeadFormDraft,
    form_id: UUID | None = None,
    expected_revision: int | None = None,
) -> LeadFormSummary:
    _member(tenant_id)
    return repository.save_draft(
        tenant_id, _context(tenant_id, connection_id), draft, form_id, expected_revision
    )


async def _client(tenant_id: UUID, context: dict) -> LeadFormsClient:
    from qualify_api.ads.client import MarketingSettings
    from qualify_api.config import MetaOAuthSettings
    from qualify_api.connections.resolver import derive_page_client

    user = await _authenticated_client(
        tenant_id, context["id"], expected_version=context["current_credential_version"]
    )
    page = None
    try:
        page = await derive_page_client(
            user,
            page_id=context["linked_page_id"],
            graph_url=MarketingSettings.from_env().graph_url,
            scheme=MetaOAuthSettings.from_env().graph_auth_scheme,
        )
        _context(tenant_id, context["id"], version=context["current_credential_version"])
        return LeadFormsClient(page, ad_client=user)
    except Exception:
        await user.aclose()
        if page is not None:
            await page.aclose()
        raise LeadFormUnavailable(
            "No pudimos comprobar el acceso a esta Página. Actualiza Meta."
        ) from None


async def _page_access(client: LeadFormsClient, page_id: str) -> None:
    observed = await client.read(page_id, fields="id,has_lead_access")
    if observed.get("id") != page_id or observed.get("has_lead_access") is not True:
        raise LeadFormUnavailable(
            "No pudimos comprobar el acceso a los datos de esta Página en Meta."
        )


def _form_guard(tenant_id: UUID, form: dict) -> dict:
    context = _context(tenant_id, form["connection_id"], version=form["credential_version"])
    if context["linked_page_id"] != form["page_id"] or context["brand_id"] != form["brand_id"]:
        raise LeadFormUnavailable("La Página o la marca cambió. Revisa de nuevo el formulario.")
    return context


async def publish_lead_form(
    *,
    tenant_id: UUID,
    form_id: UUID,
    confirmed: bool,
    expected_revision: int,
) -> LeadFormSummary:
    _member(tenant_id)
    if confirmed is not True or type(expected_revision) is not int:
        raise LeadFormUnavailable("Confirma el contenido del formulario antes de enviarlo a Meta.")
    form = repository.get_form(tenant_id, form_id)
    context = _form_guard(tenant_id, form)
    client = await _client(tenant_id, context)
    claimed = False
    try:
        await _page_access(client, form["page_id"])
        _member(tenant_id)
        _form_guard(tenant_id, form)
        snapshot = repository.claim_publication(tenant_id, form_id, expected_revision)
        claimed = True
        # Recheck after the claim and immediately before the only POST. A failure
        # after a claim is conservatively unknown, never reopened for retry.
        _member(tenant_id)
        _form_guard(tenant_id, snapshot)
        remote_id = await client.create_form(
            form["page_id"], draft_from_json(snapshot["approved_snapshot"]).payload()
        )
        remote = await client.read(remote_id, fields="id,page_id")
        if remote.get("id") != remote_id or str(remote.get("page_id", "")) != form["page_id"]:
            raise LeadFormUnavailable("No pudimos comprobar la Página del formulario creado.")
        _member(tenant_id)
        _form_guard(tenant_id, snapshot)
        return repository.finish_publication(tenant_id, form_id, meta_form_id=remote_id)
    except Exception:
        if claimed:
            return repository.finish_publication(tenant_id, form_id, meta_form_id=None)
        raise
    finally:
        await client.aclose()


async def subscribe_lead_form(*, tenant_id: UUID, form_id: UUID, confirmed: bool) -> None:
    """Explicitly enable Page leadgen events; preserve all existing own-app fields."""
    from qualify_api.config import MetaOAuthSettings

    _member(tenant_id)
    if confirmed is not True:
        raise LeadFormUnavailable("Confirma que quieres recibir los datos de este formulario.")
    form = repository.get_form(tenant_id, form_id)
    if form["status"] != "published":
        raise LeadFormUnavailable("Primero comprueba que el formulario esté publicado en Meta.")
    context = _form_guard(tenant_id, form)
    client = await _client(tenant_id, context)
    try:
        await _page_access(client, form["page_id"])
        await _remote_form(client, form)
        _member(tenant_id)
        _form_guard(tenant_id, form)

        def before_write() -> None:
            _member(tenant_id)
            _form_guard(tenant_id, form)

        await client.subscribe_leadgen(
            form["page_id"], app_id=MetaOAuthSettings.from_env().app_id, before_write=before_write
        )
    finally:
        await client.aclose()


def list_meta_leads(*, tenant_id: UUID) -> tuple[MetaLeadSummary, ...]:
    _member(tenant_id)
    return repository.list_inquiries(tenant_id)


def set_meta_lead_contacted(
    *,
    tenant_id: UUID,
    lead_id: UUID,
    contacted: bool,
) -> MetaLeadSummary | None:
    _member(tenant_id)
    if type(contacted) is not bool:
        raise LeadFormUnavailable("Revisa el estado de contacto.")
    return repository.mark_inquiry(tenant_id, lead_id, contacted)


def parse_lead(raw: dict, *, form_id: str, leadgen_id: str | None = None) -> dict:
    identity = meta_id(raw.get("id"))
    if (leadgen_id is not None and identity != leadgen_id) or raw.get("form_id") != form_id:
        raise LeadFormUnavailable("El dato recibido no corresponde a este formulario.")
    try:
        created = datetime.fromisoformat(raw["created_time"].replace("Z", "+00:00"))
        if created.tzinfo is None or created > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError
    except (KeyError, TypeError, AttributeError, ValueError):
        raise LeadFormUnavailable("Meta no devolvió una fecha válida para estos datos.") from None
    fields = raw.get("field_data")
    if not isinstance(fields, list) or len(fields) > 20:
        raise LeadFormUnavailable("Meta no devolvió respuestas válidas para el formulario.")
    answers = {}
    for item in fields:
        if not isinstance(item, dict):
            raise LeadFormUnavailable("Meta no devolvió respuestas válidas para el formulario.")
        key = safe_text(item.get("name"), maximum=100)
        values = item.get("values")
        if key in answers or not isinstance(values, list) or not 1 <= len(values) <= 10:
            raise LeadFormUnavailable("Meta no devolvió respuestas válidas para el formulario.")
        answers[key] = "; ".join(safe_text(value, maximum=500, required=False) for value in values)
    ad_id = raw.get("ad_id")
    if ad_id is not None:
        meta_id(ad_id)
    return {
        "leadgen_id": identity,
        "meta_ad_id": ad_id,
        "created": created,
        "full_name": answers.get("full_name") or "Persona interesada",
        "phone": answers.get("phone_number") or None,
        "email": answers.get("email") or None,
        "answers": answers,
    }


async def _remote_form(client: LeadFormsClient, form: dict) -> None:
    remote = await client.read(form["meta_form_id"], fields="id,page_id")
    if (
        remote.get("id") != form["meta_form_id"]
        or str(remote.get("page_id", "")) != form["page_id"]
    ):
        raise LeadFormUnavailable("El formulario de Meta no corresponde a esta Página.")


async def _verify_ad(client: LeadFormsClient, form: dict, data: dict) -> None:
    if data["meta_ad_id"] is None:
        return
    ad = await client.read_ad(data["meta_ad_id"], fields="id,creative{object_story_spec}")
    creative = ad.get("creative")
    spec = creative.get("object_story_spec") if isinstance(creative, dict) else None
    link = spec.get("link_data") if isinstance(spec, dict) else None
    video = spec.get("video_data") if isinstance(spec, dict) else None
    content = link or video
    cta = content.get("call_to_action") if isinstance(content, dict) else None
    value = cta.get("value") if isinstance(cta, dict) else None
    if (
        ad.get("id") != data["meta_ad_id"]
        or not isinstance(spec, dict)
        or spec.get("page_id") != form["page_id"]
        or not isinstance(value, dict)
        or value.get("lead_gen_form_id") != form["meta_form_id"]
    ):
        raise LeadFormUnavailable("No pudimos comprobar el anuncio de este formulario.")


def _persist(tenant_id: UUID, form: dict, data: dict, *, received_via: str) -> bool:
    _form_guard(tenant_id, form)
    with tenant_session(tenant_id) as session:
        # Serialize against revocation/purge/reconnect before retaining any PII.
        connection = session.execute(
            text("""SELECT id FROM social_connections WHERE id=:cid
            AND status='active' AND current_credential_version=:version AND linked_page_id=:page
            AND brand_id=:brand AND purge_started_at IS NULL AND purged_at IS NULL FOR SHARE"""),
            {
                "cid": form["connection_id"],
                "version": form["credential_version"],
                "page": form["page_id"],
                "brand": form["brand_id"],
            },
        ).first()
        if connection is None:
            raise LeadFormUnavailable("El acceso con Meta cambió. Comprueba de nuevo los datos.")
        # Only a proven local exclusive ad mapping may attribute a promotion.
        promotion = session.scalar(
            text("""SELECT id FROM ad_promotions
            WHERE meta_ad_id=:ad AND brand_id=:brand AND objective='OUTCOME_LEADS'
            AND request_snapshot->>'lead_gen_form_id'=:remote"""),
            {"ad": data["meta_ad_id"], "brand": form["brand_id"], "remote": form["meta_form_id"]},
        )
        inserted = session.execute(
            text("""INSERT INTO meta_lead_submissions
            (tenant_id,form_id,leadgen_id,meta_ad_id,promotion_id,full_name,phone,email,answers,
             source_created_at,credential_version,received_via)
            VALUES (:tid,:form,:lead,:ad,:promotion,:name,:phone,:email,CAST(:answers AS jsonb),
                    :created,:version,:via) ON CONFLICT (tenant_id,leadgen_id) DO NOTHING"""),
            {
                "tid": tenant_id,
                "form": form["id"],
                "lead": data["leadgen_id"],
                "ad": data["meta_ad_id"],
                "promotion": promotion,
                "name": data["full_name"],
                "phone": data["phone"],
                "email": data["email"],
                "answers": json.dumps(data["answers"]),
                "created": data["created"],
                "version": form["credential_version"],
                "via": received_via,
            },
        )
        return inserted.rowcount == 1


async def sync_lead_form(*, tenant_id: UUID, form_id: UUID) -> int:
    _member(tenant_id)
    form = repository.get_form(tenant_id, form_id)
    if form["status"] != "published":
        raise LeadFormUnavailable("Primero comprueba que el formulario esté publicado en Meta.")
    context = _form_guard(tenant_id, form)
    client = await _client(tenant_id, context)
    count = 0
    try:
        await _page_access(client, form["page_id"])
        await _remote_form(client, form)
        # Fixed window + overlap. Watermark moves only after every page completed.
        lower = form["backup_since"] or (
            (form["last_synced_at"] or form["approved_at"]) - timedelta(minutes=5)
        )
        completed_at = form["backup_started_at"] or datetime.now(UTC)
        after = form["backup_after"]
        seen = {after} if after is not None else set()
        for _ in range(20):
            _member(tenant_id)
            _form_guard(tenant_id, form)
            page = await client.leads(
                form["meta_form_id"], since=max(0, int(lower.timestamp())), after=after
            )
            for raw in page.rows:
                data = parse_lead(raw, form_id=form["meta_form_id"])
                await _verify_ad(client, form, data)
                _member(tenant_id)
                count += int(_persist(tenant_id, form, data, received_via="backup"))
            if page.after is None:
                _member(tenant_id)
                _form_guard(tenant_id, form)
                with tenant_session(tenant_id) as session:
                    finished = session.execute(
                        text("""UPDATE ad_lead_forms SET last_synced_at=
                        GREATEST(COALESCE(last_synced_at,:completed),:completed)
                        ,backup_since=NULL,backup_started_at=NULL,backup_after=NULL
                        WHERE id=:id AND status='published' AND credential_version=:version
                        AND backup_after IS NOT DISTINCT FROM :after"""),
                        {
                            "id": form_id,
                            "version": form["credential_version"],
                            "completed": completed_at,
                            "after": after,
                        },
                    )
                    if finished.rowcount != 1:
                        raise LeadFormUnavailable(
                            "Otra consulta actualizó el formulario. Vuelve a revisarlo."
                        )
                return count
            if page.after in seen:
                raise LeadFormUnavailable("Meta repitió una página. Vuelve a comprobar los datos.")
            seen.add(page.after)
            with tenant_session(tenant_id) as session:
                advanced = session.execute(
                    text("""UPDATE ad_lead_forms
                    SET backup_since=:since,backup_started_at=:started,backup_after=:next
                    WHERE id=:id AND backup_after IS NOT DISTINCT FROM :after
                    AND status='published' AND credential_version=:version"""),
                    {
                        "since": lower,
                        "started": completed_at,
                        "next": page.after,
                        "id": form_id,
                        "after": after,
                        "version": form["credential_version"],
                    },
                )
                if advanced.rowcount != 1:
                    raise LeadFormUnavailable(
                        "Otra consulta actualizó el formulario. Vuelve a revisarlo."
                    )
            after = page.after
        raise LeadFormUnavailable(
            "Hay más datos por comprobar. Vuelve a consultar para completar la ventana."
        )
    finally:
        await client.aclose()

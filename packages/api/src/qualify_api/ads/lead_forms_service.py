"""Form editor, one-shot publication and read-only lead import composition."""

from __future__ import annotations

import json
import logging
import re
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
    LeadNotVerifiable,
    MetaLeadSummary,
    draft_from_json,
)
from qualify_api.ads.lead_forms_client import LeadFormsClient, meta_id
from qualify_api.connections.ad_accounts import (
    _authenticated_client,
    _connection,
    _permission_reason,
)
from qualify_api.tenancy.acting import current_acting_login, require_acting_member

logger = logging.getLogger(__name__)
PIPELINE = "meta-lead-v1"
UNATTRIBUTED_PIPELINE = "meta-lead-v1:ad-unverified"


def _member(tenant_id: UUID) -> None:
    if current_acting_login() is None:
        raise LeadFormUnavailable("Vuelve a entrar para revisar los formularios de este negocio.")
    require_acting_member(tenant_id)


def _context(tenant_id: UUID, connection_id: UUID, *, version: int | None = None) -> dict:
    with tenant_session(tenant_id) as session:
        try:
            grant = _connection(session, connection_id)
        except ValueError:
            raise LeadFormUnavailable(
                "Esta conexión ya no está disponible. Conéctala de nuevo en «Tus redes»."
            ) from None
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
        if row is None:
            raise LeadFormUnavailable(
                "Tu cuenta de Meta ya no está conectada. Conéctala de nuevo en «Tus redes»."
            )
        if version is not None and row.current_credential_version != version:
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
    # A draft/claim is pinned to the access it was reviewed with. A published form keeps
    # receiving across a token renewal of the same active connection, Page and brand;
    # its frozen credential_version stays as provenance (m-25072004).
    pinned = None if form["status"] == "published" else form["credential_version"]
    context = _context(tenant_id, form["connection_id"], version=pinned)
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


def _lead_text(value: object, *, maximum: int) -> str:
    """Lenient on genuine answers: CR normalized, control chars dropped, long text cut with «…»."""
    if not isinstance(value, str):
        raise LeadFormUnavailable("Meta no devolvió respuestas válidas para el formulario.")
    result = value.replace("\r\n", "\n").replace("\r", "\n")
    result = "".join(char for char in result if ord(char) >= 32 or char in "\n\t").strip()
    return result if len(result) <= maximum else result[: maximum - 1].rstrip() + "…"


def parse_lead(raw: dict, *, form_id: str, leadgen_id: str | None = None) -> dict:
    """Skips only malformed payloads; real answers are normalized, never refused for style."""
    if not isinstance(raw, dict):
        raise LeadFormUnavailable("El dato recibido no corresponde a este formulario.")
    identity = meta_id(raw.get("id"))
    if (leadgen_id is not None and identity != leadgen_id) or raw.get("form_id") != form_id:
        raise LeadFormUnavailable("El dato recibido no corresponde a este formulario.")
    try:
        created = datetime.fromisoformat(raw["created_time"].replace("Z", "+00:00"))
        if created.tzinfo is None or created > datetime.now(UTC) + timedelta(minutes=10):
            raise ValueError
    except (KeyError, TypeError, AttributeError, ValueError):
        raise LeadFormUnavailable("Meta no devolvió una fecha válida para estos datos.") from None
    created = min(created, datetime.now(UTC))  # Meta's clock may run a few minutes ahead.
    fields = raw.get("field_data")
    if not isinstance(fields, list) or len(fields) > 20:
        raise LeadFormUnavailable("Meta no devolvió respuestas válidas para el formulario.")
    answers: dict[str, str] = {}
    names = set()
    for item in fields:
        if not isinstance(item, dict):
            raise LeadFormUnavailable("Meta no devolvió respuestas válidas para el formulario.")
        name = item.get("name")
        key = _lead_text(name, maximum=100)
        values = item.get("values")
        if not key or name in names or not isinstance(values, list) or len(values) > 10:
            raise LeadFormUnavailable("Meta no devolvió respuestas válidas para el formulario.")
        names.add(name)
        base, number = key, 2
        while key in answers:  # Two long names cut to the same prefix: keep both answers.
            suffix = f" ({number})"
            key, number = base[: 100 - len(suffix)] + suffix, number + 1
        answers[key] = "; ".join(_lead_text(value, maximum=500) for value in values)
    ad_id = raw.get("ad_id")
    dropped = False
    try:
        ad_id = None if ad_id is None else meta_id(ad_id)
    except LeadFormUnavailable:
        ad_id, dropped = None, True  # An odd ad id only costs the attribution, never the contact.
    data = {
        "leadgen_id": identity,
        "meta_ad_id": ad_id,
        "created": created,
        "full_name": answers.get("full_name") or "Persona interesada",
        "phone": answers.get("phone_number") or None,
        "email": answers.get("email") or None,
        "answers": answers,
    }
    return _unattributed(data) if dropped else data


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
    ad = await client.read_ad(
        data["meta_ad_id"], fields="id,creative{object_story_spec,object_id,call_to_action}"
    )
    creative = ad.get("creative")
    creative = creative if isinstance(creative, dict) else {}
    spec = creative.get("object_story_spec")
    spec = spec if isinstance(spec, dict) else {}
    content = spec.get("link_data") or spec.get("video_data")
    cta = content.get("call_to_action") if isinstance(content, dict) else None
    page = spec.get("page_id")
    if cta is None:
        # Qualify's lead ads promote an existing Instagram post (m-24828981): the CTA
        # and Page sit on the creative itself, even if Meta synthesizes a bare spec.
        page, cta = creative.get("object_id"), creative.get("call_to_action")
    value = cta.get("value") if isinstance(cta, dict) else None
    if (
        ad.get("id") != data["meta_ad_id"]
        or page != form["page_id"]
        or not isinstance(value, dict)
        or value.get("lead_gen_form_id") != form["meta_form_id"]
    ):
        raise LeadNotVerifiable("No pudimos comprobar el anuncio de este formulario.")


async def _attribution(client: LeadFormsClient, form: dict, data: dict) -> dict:
    """The lead is the owner's either way; only a verified ad may attribute it.

    Transient Meta errors still raise (retry later); a definite "cannot verify" saves the
    contact without ad or promotion, marked in `pipeline_version`.
    """
    try:
        await _verify_ad(client, form, data)
        return data
    except LeadNotVerifiable:
        return _unattributed(data)


def _unattributed(data: dict) -> dict:
    logger.info("lead %s saved without ad attribution (ad_not_verifiable)", data["leadgen_id"])
    return {**data, "meta_ad_id": None, "pipeline": UNATTRIBUTED_PIPELINE}


def _persist(
    tenant_id: UUID, form: dict, data: dict, *, received_via: str, credential_version: int
) -> bool:
    """`credential_version` is the one the lead was fetched with; a rotation since rejects."""
    if form["status"] != "published":
        raise LeadFormUnavailable("Primero comprueba que el formulario esté publicado en Meta.")
    _form_guard(tenant_id, form)
    version = credential_version
    with tenant_session(tenant_id) as session:
        # Serialize against revocation/purge/re-link/rotation before retaining any PII.
        connection = session.execute(
            text("""SELECT id FROM social_connections WHERE id=:cid
            AND status='active' AND current_credential_version=:version AND linked_page_id=:page
            AND brand_id=:brand AND purge_started_at IS NULL AND purged_at IS NULL FOR SHARE"""),
            {
                "cid": form["connection_id"],
                "version": version,
                "page": form["page_id"],
                "brand": form["brand_id"],
            },
        ).first()
        if connection is None:
            raise LeadFormUnavailable("El acceso con Meta cambió. Comprueba de nuevo los datos.")
        # Only a proven local exclusive ad mapping may attribute a promotion.
        promotion = (
            None
            if data["meta_ad_id"] is None
            else session.scalar(
                text("""SELECT id FROM ad_promotions
            WHERE meta_ad_id=:ad AND brand_id=:brand AND objective='OUTCOME_LEADS'
            AND request_snapshot->'lead_form_snapshot'->>'meta_form_id'=:remote"""),
                {
                    "ad": data["meta_ad_id"],
                    "brand": form["brand_id"],
                    "remote": form["meta_form_id"],
                },
            )
        )
        inserted = session.execute(
            text("""INSERT INTO meta_lead_submissions
            (tenant_id,form_id,leadgen_id,meta_ad_id,promotion_id,full_name,phone,email,answers,
             source_created_at,credential_version,received_via,pipeline_version)
            VALUES (:tid,:form,:lead,:ad,:promotion,:name,:phone,:email,CAST(:answers AS jsonb),
                    :created,:version,:via,:pipeline)
            ON CONFLICT (tenant_id,leadgen_id) DO NOTHING"""),
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
                "version": version,
                "via": received_via,
                "pipeline": data.get("pipeline", PIPELINE),
            },
        )
        return inserted.rowcount == 1


async def sync_lead_form(*, tenant_id: UUID, form_id: UUID) -> tuple[int, int]:
    """Returns (saved, skipped). One unreadable lead is skipped so it cannot block the rest."""
    _member(tenant_id)
    form = repository.get_form(tenant_id, form_id)
    if form["status"] != "published":
        raise LeadFormUnavailable("Primero comprueba que el formulario esté publicado en Meta.")
    context = _form_guard(tenant_id, form)
    client = await _client(tenant_id, context)
    count = 0
    skipped: set[str] = set()
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
                try:
                    data = parse_lead(raw, form_id=form["meta_form_id"])
                except LeadFormUnavailable:
                    lead_id = raw.get("id") if isinstance(raw, dict) else None
                    if not (isinstance(lead_id, str) and re.fullmatch(r"[0-9]{1,40}", lead_id)):
                        lead_id = None
                    # Dedupe so the window overlap never counts one contact twice.
                    key = lead_id or json.dumps(raw, sort_keys=True, default=str)
                    if key not in skipped:
                        skipped.add(key)
                        logger.warning(
                            "lead form %s: skipped lead %s (unparseable)", form_id, lead_id or "-"
                        )
                    continue
                data = await _attribution(client, form, data)
                _member(tenant_id)
                count += int(
                    _persist(
                        tenant_id,
                        form,
                        data,
                        received_via="backup",
                        credential_version=context["current_credential_version"],
                    )
                )
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
                return count, len(skipped)
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

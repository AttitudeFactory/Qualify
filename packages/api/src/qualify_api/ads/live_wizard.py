"""Finite production checks backed by real Graph reads and exact validate_only calls.

An accepted validation is not a promise of a future charge or delivery. Unknown
currency units or remote creative fields block execution rather than guessing.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qualify_api.ads.client import MarketingClient, Resource
from qualify_api.ads.enhancements import FEATURES
from qualify_api.ads.errors import MarketingError
from qualify_api.ads.promotions import Promotion, step_payload
from qualify_api.ads.validation import payloads_for_validation, receipt, valid_receipt
from qualify_api.ads.wizard import PromotionSource, WizardForm, WizardUnavailable
from qualify_api.ads.wizard_workflow import VerifiedChecks
from qualify_api.connections.ad_accounts import GraphAdAccountReader, _authenticated_client

LABELS = {
    "permissions": "Permisos de Meta",
    "account": "Cuenta publicitaria",
    "payment": "Información de pago",
    "media": "Publicación de Instagram",
    "currency": "Importe y moneda",
    "validation": "Configuración del anuncio",
    "remote": "Anuncio creado en pausa",
}


def production_currency_offset(currency: str) -> int | None:
    # Official Meta currencies table, retrieved 2026-11-06: COP subdivision=1.
    # https://developers.facebook.com/docs/marketing-api/currencies/
    # ISO decimals are NOT Meta offsets. Other currencies remain unsupported.
    return 1 if currency == "COP" else None


class LiveWizardGateway:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        actor: UUID,
        sources: Any,
        authorize: Callable,
        currency_offset: int | None = None,
        client_factory: Callable | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.tenant_id, self.actor = tenant_id, actor
        self.sources, self.authorize, self.clock = sources, authorize, clock
        self.currency_offset = currency_offset
        self.client_factory = client_factory
        self.diagnostics: list[dict[str, str]] = []
        self._validated: dict[str, tuple[str, datetime]] = {}

    def check(self, key: str, detail: str, *, status: str = "verified") -> None:
        self.diagnostics = [row for row in self.diagnostics if row["key"] != key]
        self.diagnostics.append(
            {"key": key, "label": LABELS[key], "status": status, "detail": detail}
        )

    def fail(self, key: str, detail: str, *, unavailable: bool = False) -> None:
        self.check(key, detail, status="unavailable" if unavailable else "blocked")
        raise WizardUnavailable(detail, diagnostics=tuple(self.diagnostics))

    @asynccontextmanager
    async def client(self, source: PromotionSource):
        if self.client_factory is not None:
            client = await self.client_factory(source)
        else:
            client = MarketingClient(
                client=await _authenticated_client(
                    self.tenant_id, source.connection_id, expected_version=source.credential_version
                ),
                account_id=source.meta_ad_account_id,
            )
        try:
            yield client
        finally:
            await client.aclose()

    def local_guard(self, source: PromotionSource) -> None:
        self.authorize(self.tenant_id, self.actor)
        credential_guard(self.tenant_id, source)
        current = self.sources.get(self.tenant_id, source.publish_attempt_id)
        if current.unavailable_reason:
            self.fail("media", current.unavailable_reason)
        keys = (
            "publish_attempt_id",
            "content_draft_id",
            "connection_id",
            "brand_id",
            "instagram_user_id",
            "source_media_id",
            "meta_ad_account_id",
            "ad_account_id",
            "currency",
            "timezone_name",
            "credential_version",
            "linked_page_id",
            "ad_destination_fingerprint",
        )
        if any(getattr(current, key) != getattr(source, key) for key in keys):
            self.fail("account", "La publicación o la cuenta cambió. Vuelve a comprobarla.")

    async def observations(self, source: PromotionSource, client: MarketingClient) -> None:
        self.local_guard(source)
        try:
            accounts = await GraphAdAccountReader(client._client).list_accounts(
                source.instagram_user_id
            )
        except ValueError:
            self.fail(
                "permissions",
                "Actualiza el acceso con Meta y vuelve a comprobarlo.",
                unavailable=True,
            )
        self.check("permissions", "Meta confirmó el permiso para anunciar con esta conexión.")
        account = next((a for a in accounts if a.ad_account_id == source.meta_ad_account_id), None)
        if account is None or account.instagram_assigned is not True:
            self.fail("account", "Meta no confirmó el acceso a la cuenta y a este Instagram.")
        if account.currency != source.currency or account.timezone_name != source.timezone_name:
            self.fail("account", "La moneda o zona horaria cambió. Actualiza las cuentas.")
        try:
            ZoneInfo(account.timezone_name)
        except (ValueError, ZoneInfoNotFoundError):
            self.fail("account", "Falta comprobar la zona horaria de la cuenta.", unavailable=True)
        if account.account_status != 1 or account.disable_reason != 0:
            self.fail("account", "Revisa las restricciones de la cuenta publicitaria en Meta.")
        self.check("account", "La cuenta está activa y tiene asignado este Instagram.")
        if account.has_funding_source is not True:
            self.fail(
                "payment", "Meta no confirmó un método de pago. Revísalo en Meta.", unavailable=True
            )
        account_data = await client.read_account(
            fields="account_id,currency,failed_delivery_checks"
        )
        if (
            account_data.get("account_id") != source.meta_ad_account_id
            or account_data.get("currency") != "COP"
        ):
            self.fail(
                "payment", "No pudimos comprobar la información de esta cuenta.", unavailable=True
            )
        if account_data.get("failed_delivery_checks") != []:
            self.fail(
                "payment",
                "Meta informa comprobaciones pendientes de la cuenta. Revísala antes de continuar.",
                unavailable=True,
            )
        self.check(
            "payment", "No se observan bloqueos de pago. Meta decide la aprobación y entrega."
        )
        media = await client.read_object(
            source.source_media_id, fields="id,owner,media_type,media_product_type"
        )
        owner = media.get("owner")
        if (
            media.get("id") != source.source_media_id
            or not isinstance(owner, dict)
            or owner.get("id") != source.instagram_user_id
        ):
            self.fail("media", "Meta no confirmó que esta publicación pertenezca a tu Instagram.")
        if (
            media.get("media_type") not in {"IMAGE", "VIDEO"}
            or media.get("media_product_type") == "STORY"
        ):
            self.fail("media", "Esta comprobación admite fotos y vídeos publicados en Instagram.")
        self.check("media", "La publicación pertenece al Instagram de esta marca.")
        self.local_guard(source)

    def supported(self, source: PromotionSource, form: WizardForm) -> None:
        form.validate(for_execution=True)
        if source.currency != "COP" or form.currency != "COP":
            self.fail("currency", "Esta comprobación admite cuentas en pesos colombianos.")
        if not source.linked_page_id.isdigit() or source.credential_version <= 0:
            self.fail("account", "Falta comprobar la página y la versión del acceso de Meta.")
        if form.lead_form is not None and not form.lead_form.matches(source):
            self.fail("validation", "El formulario no corresponde a la cuenta de esta publicación.")
        if form.housing or form.advantage_audience:
            self.fail(
                "validation",
                "La comprobación de Vivienda y del público ampliado todavía no está disponible.",
            )
        if form.enhancements is None or form.enhancements.enabled:
            self.fail(
                "validation",
                "Revisa los permisos de la marca. Esta comprobación requiere "
                "los cuatro cambios desactivados.",
            )
        if form.audience is None:
            self.fail(
                "validation",
                "Vuelve a elegir el lugar del público antes de comprobar la promoción.",
            )
        if form.audience is not None and form.audience.custom_audiences:
            self.fail(
                "validation",
                "Puedes preparar este público, pero falta comprobar su uso en promociones reales. "
                "No se creará ni activará el anuncio.",
            )
        if form.audience is not None and (
            form.audience.interests or form.audience.radius_km is not None
        ):
            self.fail(
                "validation", "Esta comprobación admite lugares sin radio ni intereses añadidos."
            )

    async def preflight(self, source: PromotionSource, form: WizardForm) -> VerifiedChecks:
        self.diagnostics = []
        self.supported(source, form)
        try:
            async with self.client(source) as client:
                await self.observations(source, client)
                offset = self.currency_offset
                if offset is None:
                    offset = production_currency_offset(form.currency)
                if offset in {1, 100} and form.budget_minor * offset % 100:
                    self.fail(
                        "currency",
                        "Meta no admite ese importe exacto. Revisa los decimales del presupuesto.",
                    )
                requested = self.clock()
                payloads = payloads_for_validation(source, form, self.actor, requested, offset)
                for resource in ("campaigns", "adcreatives"):
                    await client.validate(resource, params=payloads[resource])
                self.check(
                    "validation",
                    "Meta aceptó la comprobación de campaña y creatividad, sin crear objetos.",
                )
                if offset != 1:
                    self.fail(
                        "currency",
                        "Falta comprobar cómo expresa Meta los importes en pesos colombianos. "
                        "No se creará ni activará el anuncio.",
                        unavailable=True,
                    )
                if form.budget_minor * offset % 100:
                    self.fail(
                        "currency",
                        "Meta no admite ese importe exacto. Revisa los decimales del presupuesto.",
                    )
                self.check(
                    "currency",
                    "El importe aprobado tiene una conversión exacta a la unidad de Meta.",
                )
                for resource in ("adsets", "ads"):
                    await client.validate(resource, params=payloads[resource])
                now = self.clock()
                proof = receipt(
                    source,
                    form,
                    self.actor,
                    now,
                    requested=requested,
                    offset=offset,
                    payloads=payloads,
                )
                self.local_guard(source)
                self.check(
                    "validation",
                    "Meta aceptó la validación de esta configuración sin crear objetos ni gastar.",
                )
                return VerifiedChecks(
                    None,
                    None,
                    True,
                    None,
                    form.city_key,
                    datetime.fromisoformat(proof["expires_at"]),
                    audience_fingerprint=form.audience.fingerprint if form.audience else "",
                    audience_policy_verified=True,
                    exact_validation=proof,
                    currency_offset=offset,
                    diagnostics=tuple(self.diagnostics),
                )
        except MarketingError:
            self.fail(
                "validation",
                "Meta no confirmó esta configuración. Revisa el presupuesto, las fechas, "
                "el enlace y las ubicaciones.",
                unavailable=True,
            )

    async def validate_step(
        self, promotion: Promotion, resource: Resource, payload: dict[str, Any]
    ) -> None:
        source = self.sources.get(self.tenant_id, UUID(promotion.request["publish_attempt_id"]))
        self.local_guard(source)
        async with self.client(source) as client:
            for parent, identifier in promotion.ids.items():
                row = await client.read_object(identifier, fields="id,account_id,status")
                if (
                    row.get("id") != identifier
                    or row.get("account_id") != source.meta_ad_account_id
                    or (parent != "adcreatives" and row.get("status") != "PAUSED")
                ):
                    self.fail(
                        "remote", "Los objetos existentes cambiaron. No se crearán más anuncios."
                    )
            await client.validate(resource, params=payload)
        self._pending_step = (promotion, resource, payload, self.clock())

    async def before_creation(
        self, source: PromotionSource, form: WizardForm, checks: VerifiedChecks
    ) -> None:
        self.local_guard(source)
        if not valid_receipt(checks.exact_validation, source, form, self.clock(), self.actor):
            self.fail("validation", "La comprobación venció. Vuelve a revisar la promoción.")
        async with self.client(source) as client:
            await self.observations(source, client)
        if not valid_receipt(checks.exact_validation, source, form, self.clock(), self.actor):
            self.fail(
                "validation",
                "La comprobación venció mientras se consultaba Meta. Vuelve a revisarla.",
            )
        pending = getattr(self, "_pending_step", None)
        if pending is None:
            self.fail("validation", "Falta validar el paso de creación con Meta.")
        promotion, resource, payload, checked_at = pending
        if (self.clock() - checked_at).total_seconds() > 300:
            self.fail("validation", "La validación del anuncio venció. Vuelve a comprobarla.")
        await self.validate_step(promotion, resource, payload)
        if not valid_receipt(checks.exact_validation, source, form, self.clock(), self.actor):
            self.fail("validation", "La comprobación venció. Vuelve a revisar la promoción.")
        self.local_guard(source)

    async def remote_guard(
        self, promotion: Promotion, *, active_resources: tuple[str, ...] = ()
    ) -> None:
        source = self.sources.get(self.tenant_id, UUID(promotion.request["publish_attempt_id"]))
        self.local_guard(source)
        async with self.client(source) as client:
            await self.observations(source, client)
            records: dict[str, dict[str, Any]] = {}
            fields = {
                "campaigns": "id,account_id,status,objective,special_ad_categories,"
                "daily_budget,lifetime_budget",
                "adsets": "id,account_id,status,campaign_id,lifetime_budget,daily_budget,"
                "start_time,end_time,targeting,billing_event,optimization_goal,"
                "destination_type",
                "adcreatives": "id,account_id,object_id,source_instagram_media_id,"
                "instagram_user_id,call_to_action,link_url,degrees_of_freedom_spec",
                "ads": "id,account_id,status,campaign_id,adset_id,creative",
            }
            for resource in fields:
                identifier = promotion.ids[resource]
                records[resource] = await client.read_object(identifier, fields=fields[resource])
                row = records[resource]
                if (
                    row.get("id") != identifier
                    or row.get("account_id") != source.meta_ad_account_id
                ):
                    self.fail(
                        "remote",
                        "No pudimos verificar los objetos de esta cuenta. No se activó el anuncio.",
                    )
            campaign, adset, creative, ad = (
                records[k] for k in ("campaigns", "adsets", "adcreatives", "ads")
            )
            adsets = await client.children(promotion.ids["campaigns"], resource="adsets")
            ads = await client.children(promotion.ids["adsets"], resource="ads")
            if (
                len(adsets) != 1
                or adsets[0].get("id") != promotion.ids["adsets"]
                or len(ads) != 1
                or ads[0].get("id") != promotion.ids["ads"]
            ):
                self.fail(
                    "remote",
                    "Hay otros anuncios o conjuntos dentro de esta campaña. "
                    "No se activará contenido que no hayas aprobado aquí.",
                )
            expected = step_payload(promotion, "adsets")
            request = promotion.request
            statuses = all(
                records[resource].get("status")
                == ("ACTIVE" if resource in active_resources else "PAUSED")
                for resource in ("campaigns", "adsets", "ads")
            )
            chain = (
                ad.get("adset_id") == promotion.ids["adsets"]
                and ad.get("campaign_id") == promotion.ids["campaigns"]
                and adset.get("campaign_id") == promotion.ids["campaigns"]
                and isinstance(ad.get("creative"), dict)
                and ad["creative"].get("id") == promotion.ids["adcreatives"]
            )
            campaign_matches = (
                campaign.get("objective") == request["objective"]
                and campaign.get("special_ad_categories") == request["special_ad_categories"]
                and str(campaign.get("daily_budget", "0")) == "0"
                and str(campaign.get("lifetime_budget", "0")) == "0"
            )
            budget = (
                str(adset.get("lifetime_budget")) == str(expected["lifetime_budget"])
                and str(adset.get("daily_budget", "0")) == "0"
            )
            dates = all(_date_equal(adset.get(k), expected[k]) for k in ("start_time", "end_time"))
            targeting = adset.get("targeting") == request["targeting"]
            options = all(adset.get(k) == v for k, v in request["adset_options"].items())
            cta = creative.get("call_to_action")
            creative_matches = (
                creative.get("source_instagram_media_id") == source.source_media_id
                and creative.get("object_id") == source.linked_page_id
                and creative.get("instagram_user_id") == source.instagram_user_id
                and cta == request["creative"]["call_to_action"]
                and ("link_url" not in creative or creative["link_url"] == request["link_url"])
                and creative.get("degrees_of_freedom_spec")
                == request["creative"]["degrees_of_freedom_spec"]
                and all(not value for value in request["enhancements_snapshot"]["values"].values())
                and set(request["enhancements_snapshot"]["values"]) == set(FEATURES)
            )
            if not all(
                (
                    statuses,
                    chain,
                    campaign_matches,
                    budget,
                    dates,
                    targeting,
                    options,
                    creative_matches,
                )
            ):
                self.fail(
                    "remote",
                    "El anuncio de Meta no coincide con el presupuesto, el público, "
                    "las fechas o el enlace aprobados. No se activó.",
                )
            self.check(
                "remote",
                "Los objetos de Meta coinciden con la aprobación y el anuncio está en pausa."
                if not active_resources
                else "Los objetos de Meta siguen coincidiendo con la aprobación.",
            )
        self.local_guard(source)


class PersistedWizardSources:
    def get(self, tenant_id: UUID, source_id: UUID) -> PromotionSource:
        from qualify_shared.db.session import tenant_session
        from sqlalchemy import text

        from qualify_api.ads.wizard import list_promotion_sources

        with tenant_session(tenant_id) as session:
            drafts = session.scalars(
                text(
                    "SELECT DISTINCT post_id FROM calendar_events WHERE publish_attempt_id=:id "
                    "AND status='published'"
                ),
                {"id": source_id},
            ).all()
        if len(drafts) != 1:
            raise WizardUnavailable("Esta publicación de Instagram ya no está disponible.")
        rows = [
            source
            for source in list_promotion_sources(tenant_id=tenant_id, content_draft_id=drafts[0])
            if source.publish_attempt_id == source_id
        ]
        if len(rows) != 1:
            raise WizardUnavailable(
                "La publicación o sus cuentas cambiaron. Abre la promoción de nuevo."
            )
        return rows[0]


def credential_guard(tenant_id: UUID, source: PromotionSource) -> None:
    """Final synchronous fence, including revocation without a credential-epoch change."""
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import text

    from qualify_api.connections.ad_accounts import _connection, _permission_reason

    with tenant_session(tenant_id) as session:
        current = _connection(session, source.connection_id)
        selected = session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM ad_accounts WHERE id=:id "
                "AND connection_id=:connection "
                "AND brand_id=:brand AND ad_account_id=:account AND credential_version=:version "
                "AND selected AND available)"
            ),
            {
                "id": source.ad_account_id,
                "connection": source.connection_id,
                "brand": source.brand_id,
                "account": source.meta_ad_account_id,
                "version": source.credential_version,
            },
        )
    if (
        _permission_reason(current)
        or not selected
        or current.version != source.credential_version
        or current.brand_id != source.brand_id
        or current.external_account_id != source.instagram_user_id
    ):
        raise WizardUnavailable("El acceso o la cuenta cambió. Actualiza el acceso con Meta.")


def authorize_actor(tenant_id: UUID, actor: UUID) -> None:
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import text

    from qualify_api.tenancy.acting import current_acting_login, require_acting_member

    login = current_acting_login()
    if login is None:
        raise WizardUnavailable("Vuelve a entrar para comprobar y aprobar la promoción.")
    require_acting_member(tenant_id)
    with tenant_session(tenant_id) as session:
        matches = session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM users u JOIN tenant_members m ON m.user_id=u.id "
                "WHERE u.id=:actor AND u.auth_user_id=:login AND m.tenant_id=:tenant)"
            ),
            {"actor": actor, "login": login, "tenant": tenant_id},
        )
    if not matches:
        raise WizardUnavailable("Tu aprobación no corresponde al acceso actual de este negocio.")


class ManagedAccountBinding:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.clients: list[Any] = []

    async def resolve(self, *args: Any) -> Any:
        access = await self.delegate.resolve(*args)
        self.clients.append(access.client)
        return access

    async def aclose(self) -> None:
        for client in self.clients:
            await client.aclose()


@asynccontextmanager
async def production_wizard(tenant_id: UUID, actor: UUID):
    from qualify_api.ads.activation_repository import PostgresActivationRepository
    from qualify_api.ads.promotion_repository import PostgresPromotionRepository
    from qualify_api.ads.promotions import PromotionService
    from qualify_api.ads.wizard_workflow import PromotionWizard
    from qualify_api.connections.ad_accounts import PostgresAccountBinding

    authorize_actor(tenant_id, actor)
    sources = PersistedWizardSources()
    gateway = LiveWizardGateway(
        tenant_id=tenant_id, actor=actor, sources=sources, authorize=authorize_actor
    )
    binding = ManagedAccountBinding(PostgresAccountBinding())
    try:
        yield PromotionWizard(
            creation=PromotionService(PostgresPromotionRepository(), binding),
            activations=PostgresActivationRepository(),
            sources=sources,
            gateway=gateway,
            authorize=authorize_actor,
        )
    except MarketingError:
        gateway.fail(
            "remote",
            "No pudimos terminar las comprobaciones de Meta. "
            "Revisa la promoción antes de repetirla.",
            unavailable=True,
        )
    finally:
        await binding.aclose()


def _date_equal(actual: Any, expected: str) -> bool:
    try:
        observed, approved = datetime.fromisoformat(actual), datetime.fromisoformat(expected)
        return observed.utcoffset() is not None and observed == approved
    except (TypeError, ValueError):
        return False

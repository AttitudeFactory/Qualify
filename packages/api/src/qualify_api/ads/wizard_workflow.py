"""Consent-gated orchestration with short-lived normalized or exact-validation proof."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_api.ads.activation_repository import ActivationRepository, ActivationReview
from qualify_api.ads.audience import AudienceDraft
from qualify_api.ads.enhancements import (
    BrandEnhancementSettings,
    preview_receipt,
    verify_compatibility,
    verify_remote_preview,
)
from qualify_api.ads.lead_ads import LeadFormTarget
from qualify_api.ads.promotions import Promotion, PromotionRequest, PromotionService, fingerprint
from qualify_api.ads.wizard import (
    PromotionPreview,
    PromotionResult,
    PromotionSource,
    WizardForm,
    WizardUnavailable,
)


@dataclass(frozen=True)
class VerifiedChecks:
    """Normalized evidence, never a claim about the raw shape of a Meta response."""

    minimum_budget_minor: int | None
    billing_ready: bool | None
    instagram_assigned: bool | None
    eligible: bool | None
    city_key: str
    expires_at: datetime
    estimated_reach: str = ""
    housing_targeting_verified: bool = False
    advantage_targeting_verified: bool = False
    pipeline_version: str = "promotion-wizard-v1"
    audience_fingerprint: str = ""
    audience_policy_verified: bool = False
    enhancement_compatibility: dict[str, Any] = field(default_factory=dict)
    exact_validation: dict[str, Any] = field(default_factory=dict)
    currency_offset: int | None = None
    diagnostics: tuple[dict[str, str], ...] = ()


class WizardGateway(Protocol):
    async def preflight(self, source: PromotionSource, form: WizardForm) -> VerifiedChecks: ...


class WizardSources(Protocol):
    def get(self, tenant_id: UUID, source_id: UUID) -> PromotionSource: ...


def _guard_checks(
    source: PromotionSource,
    form: WizardForm,
    checks: VerifiedChecks,
    now: datetime,
    *,
    actor: UUID | None = None,
) -> None:
    form.validate(for_execution=True)
    if form.lead_form is not None and not form.lead_form.matches(source):
        raise WizardUnavailable(
            "El formulario no corresponde a la cuenta de esta publicación. Elige otro."
        )
    if form.enhancements is not None:
        if form.enhancements.brand_id != source.brand_id:
            raise WizardUnavailable("Los permisos corresponden a otra marca.")
        verify_compatibility(form.enhancements, source, checks.enhancement_compatibility, now)
    from qualify_api.ads.validation import valid_receipt

    exact = bool(checks.exact_validation)
    if exact and (
        not valid_receipt(checks.exact_validation, source, form, now, actor)
        or checks.currency_offset != checks.exact_validation.get("currency_offset")
    ):
        raise WizardUnavailable("La validación de Meta cambió o venció. Vuelve a comprobarla.")
    if (
        source.currency != form.currency
        or not source.meta_ad_account_id.isdigit()
        or not source.source_media_id.isdigit()
        or not source.instagram_user_id.isdigit()
    ):
        raise WizardUnavailable("Revisa la cuenta publicitaria y su moneda en Conexiones.")
    if (
        checks.expires_at.tzinfo is None
        or checks.expires_at.utcoffset() is None
        or checks.expires_at <= now
    ):
        raise WizardUnavailable("La comprobación venció. Prepara una nueva vista previa.")
    if not exact and (
        type(checks.minimum_budget_minor) is not int
        or checks.minimum_budget_minor <= 0
        or checks.billing_ready is not True
        or checks.instagram_assigned is not True
        or checks.eligible is not True
        or (form.audience is None and (not checks.city_key or checks.city_key != form.city_key))
    ):
        raise WizardUnavailable(
            "Falta comprobar el presupuesto, los pagos, el público o la publicación."
        )
    if not exact and form.budget_minor < checks.minimum_budget_minor:
        raise WizardUnavailable(
            "El presupuesto total está por debajo del mínimo comprobado con Meta."
        )
    if form.audience is not None and (
        not checks.audience_policy_verified
        or checks.audience_fingerprint != form.audience.fingerprint
    ):
        raise WizardUnavailable(
            "Falta verificar las reglas del público y dónde se mostrará el anuncio."
        )
    if (form.housing and not checks.housing_targeting_verified) or (
        form.advantage_audience and not checks.advantage_targeting_verified
    ):
        raise WizardUnavailable("Falta verificar las reglas de este público antes de anunciar.")
    if form.start_time <= now:
        raise WizardUnavailable("El inicio de la promoción debe ser posterior al momento actual.")


def _request(
    tenant_id: UUID,
    source: PromotionSource,
    form: WizardForm,
    actor: UUID,
    request_key: str,
    approved_at: datetime,
    *,
    currency_offset: int | None = None,
) -> PromotionRequest:
    policy = form.enhancements or BrandEnhancementSettings(tenant_id, source.brand_id)
    lead = form.lead_form
    return PromotionRequest(
        tenant_id=tenant_id,
        brand_id=source.brand_id,
        request_key=request_key,
        meta_ad_account_id=source.meta_ad_account_id,
        objective="OUTCOME_LEADS" if lead else "OUTCOME_TRAFFIC",
        cta_type=form.lead_cta if lead else "LEARN_MORE",
        link_url="" if lead else form.link_url,
        budget_kind="lifetime",
        budget_minor=form.budget_minor,
        currency=form.currency,
        start_time=form.start_time,
        end_time=form.end_time,
        approved_by=actor,
        approved_at=approved_at,
        content_draft_id=source.content_draft_id,
        publish_attempt_id=source.publish_attempt_id,
        source_media_id=source.source_media_id,
        special_ad_categories=("HOUSING",) if form.housing else (),
        audience_snapshot=form.audience.snapshot() if form.audience else {},
        enhancements_snapshot=policy.snapshot(),
        meta_currency_offset=currency_offset,
        targeting=form.audience.targeting()
        if form.audience
        else {
            "geo_locations": {
                "cities": [
                    {"key": form.city_key, "radius": form.radius_km, "distance_unit": "kilometer"}
                ]
            },
            **({"age_min": form.age_min, "age_max": form.age_max} if not form.housing else {}),
            "publisher_platforms": ["facebook", "instagram"],
            "targeting_automation": {"advantage_audience": int(form.advantage_audience)},
        },
        creative={
            **({"object_id": source.linked_page_id} if source.linked_page_id else {}),
            "source_instagram_media_id": source.source_media_id,
            "instagram_user_id": source.instagram_user_id,
            "call_to_action": lead.call_to_action(form.lead_cta)
            if lead
            else {"type": "LEARN_MORE", "value": {"link": form.link_url}},
            "degrees_of_freedom_spec": policy.creative_spec(),
        },
        adset_options=lead.adset_options()
        if lead
        else {
            "optimization_goal": "LINK_CLICKS",
            "billing_event": "IMPRESSIONS",
            "destination_type": "WEBSITE",
        },
        lead_form_snapshot=lead.snapshot() if lead else {},
    )


def _form(promotion: Promotion, checks: ActivationReview) -> WizardForm:
    request = promotion.request
    enhancements = BrandEnhancementSettings.from_snapshot(request["enhancements_snapshot"])
    lead = (
        {
            "lead_form": LeadFormTarget.from_snapshot(request["lead_form_snapshot"]),
            "lead_cta": request["cta_type"],
        }
        if request.get("lead_form_snapshot")
        else {}
    )
    if request.get("audience_snapshot"):
        audience = AudienceDraft.from_snapshot(request["audience_snapshot"])
        return WizardForm(
            link_url=request["link_url"],
            city_name=audience.location.name,
            start_time=datetime.fromisoformat(request["start_time"]),
            end_time=datetime.fromisoformat(request["end_time"]),
            age_min=audience.age_min,
            age_max=audience.age_max,
            advantage_audience=audience.advantage_audience,
            housing=audience.housing,
            budget_minor=request["budget_minor"],
            currency=request["currency"],
            audience=audience,
            enhancements=enhancements,
            **lead,
        )
    city = request["targeting"]["geo_locations"]["cities"][0]
    return WizardForm(
        link_url=request["link_url"],
        city_name=checks.checks_snapshot["city_name"],
        start_time=datetime.fromisoformat(request["start_time"]),
        end_time=datetime.fromisoformat(request["end_time"]),
        city_key=city["key"],
        radius_km=city["radius"],
        age_min=request["targeting"].get("age_min", 18),
        age_max=request["targeting"].get("age_max", 65),
        advantage_audience=bool(request["targeting"]["targeting_automation"]["advantage_audience"]),
        housing="HOUSING" in request["special_ad_categories"],
        budget_minor=request["budget_minor"],
        currency=request["currency"],
        enhancements=enhancements,
        **lead,
    )


def charge_notice(promotion: Promotion) -> str:
    # COP is displayed with two explicit decimal places; no float rounding.
    minor = promotion.request["budget_minor"]
    amount = f"{minor // 100:,}".replace(",", ".") + f",{minor % 100:02d}"
    return f"Meta cobrará hasta ${amount} COP a tu método de pago durante estas fechas."


class PromotionWizard:
    def __init__(
        self,
        *,
        creation: PromotionService,
        activations: ActivationRepository,
        sources: WizardSources,
        gateway: WizardGateway,
        authorize: Callable[[UUID, UUID], None],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.creation = creation
        self.activations = activations
        self.sources = sources
        self.gateway = gateway
        self.authorize = authorize
        self.clock = clock

    async def prepare(
        self,
        *,
        tenant_id: UUID,
        publish_attempt_id: UUID,
        form: WizardForm,
        approved_by: UUID,
        request_key: str,
    ) -> PromotionPreview:
        self.authorize(tenant_id, approved_by)
        source = self.sources.get(tenant_id, publish_attempt_id)
        checks = await self.gateway.preflight(source, form)
        now = self.clock()
        _guard_checks(source, form, checks, now, actor=approved_by)
        repo = self.creation.repository
        existing = repo.by_request_key(tenant_id, request_key)
        stamp = datetime.fromisoformat(existing.request["approved_at"]) if existing else now
        request = _request(
            tenant_id,
            source,
            form,
            approved_by,
            request_key,
            stamp,
            currency_offset=checks.currency_offset,
        )
        # Approval snapshot conflict is detected before remote creation resumes.
        self.authorize(tenant_id, approved_by)
        live = bool(checks.exact_validation)

        async def creation_guard() -> None:
            self.authorize(tenant_id, approved_by)
            current_source = self.sources.get(tenant_id, publish_attempt_id)
            _guard_checks(current_source, form, checks, self.clock(), actor=approved_by)
            policy = form.enhancements
            if (
                policy is not None
                and self.creation.repository.current_enhancements(tenant_id, source.brand_id)
                != policy.snapshot()
            ):
                raise WizardUnavailable(
                    "Los permisos de la marca cambiaron. Vuelve a comprobarlos."
                )
            await self.gateway.before_creation(source, form, checks)
            self.authorize(tenant_id, approved_by)
            _guard_checks(
                self.sources.get(tenant_id, publish_attempt_id),
                form,
                checks,
                self.clock(),
                actor=approved_by,
            )
            if (
                policy is not None
                and self.creation.repository.current_enhancements(tenant_id, source.brand_id)
                != policy.snapshot()
            ):
                raise WizardUnavailable(
                    "Los permisos cambiaron durante la comprobación. Revísalos de nuevo."
                )
            self.gateway.local_guard(self.sources.get(tenant_id, publish_attempt_id))

        promotion = await self.creation.start(
            request,
            **(
                {"before_write": creation_guard, "validate_step": self.gateway.validate_step}
                if live
                else {}
            ),
        )
        if promotion.status != "paused" or len(promotion.ids) != 4:
            raise WizardUnavailable(
                "La creación quedó pendiente. Revisa la cuenta antes de repetirla."
            )
        if live:
            await self.gateway.remote_guard(promotion)
            checks = replace(checks, diagnostics=tuple(self.gateway.diagnostics))
        old = self.activations.for_promotion(tenant_id, promotion.id)
        if old:
            if old.expires_at <= now or old.prepared_by != approved_by:
                raise WizardUnavailable("La vista previa venció. Prepara una promoción nueva.")
            self._enhancement_guard(promotion, old, source, approved_by)
            return self._preview(promotion, old)
        access = await self.creation._access(promotion)
        page = await access.client.adpreviews(
            promotion.ids["ads"], params={"ad_format": "INSTAGRAM_STANDARD"}
        )
        body = page.data[0].get("body") if len(page.data) == 1 else None
        if not isinstance(body, str) or not body.strip():
            raise WizardUnavailable(
                "No pudimos obtener una vista previa. No se activó ningún anuncio."
            )
        snapshot = asdict(checks)
        snapshot["expires_at"] = checks.expires_at.isoformat()
        snapshot["city_name"] = form.city_name
        preview_hash = hashlib.sha256(body.encode()).hexdigest()
        observed_at = self.clock()
        _guard_checks(source, form, checks, observed_at, actor=approved_by)
        preview_expiry = min(checks.expires_at, observed_at + timedelta(minutes=5))
        snapshot["enhancements_preview"] = preview_receipt(
            promotion, source, approved_by, preview_hash, preview_expiry, observed_at
        )
        policy = BrandEnhancementSettings.from_snapshot(promotion.request["enhancements_snapshot"])
        if policy.enabled:
            snapshot["enhancements_remote_preview"] = await self._remote_preview(
                promotion, source, approved_by, snapshot["enhancements_preview"]
            )
        review = ActivationReview(
            uuid4(),
            tenant_id,
            promotion.id,
            fingerprint(promotion.request),
            body,
            preview_hash,
            snapshot,
            preview_expiry,
            approved_by,
        )
        self._enhancement_guard(
            promotion, review, self.sources.get(tenant_id, source.publish_attempt_id), approved_by
        )
        review = self.activations.create(review)
        return self._preview(promotion, review)

    @staticmethod
    def _preview(promotion: Promotion, review: ActivationReview) -> PromotionPreview:
        return PromotionPreview(
            promotion.id,
            review.id,
            review.preview_html,
            charge_notice(promotion),
            review.expires_at,
            checks=tuple(review.checks_snapshot.get("diagnostics", ())),
        )

    async def confirm(
        self,
        *,
        tenant_id: UUID,
        promotion_id: UUID,
        review_id: UUID,
        approved_by: UUID,
        confirm_charge: bool,
    ) -> PromotionResult:
        if confirm_charge is not True:
            raise WizardUnavailable("Confirma el presupuesto total antes de activar la promoción.")
        self.authorize(tenant_id, approved_by)
        review = self.activations.get(tenant_id, review_id)
        promotion = self.creation.repository.get(tenant_id, promotion_id)
        if (
            not review
            or not promotion
            or review.promotion_id != promotion_id
            or review.prepared_by != approved_by
            or review.request_hash != fingerprint(promotion.request)
        ):
            raise WizardUnavailable("Esta confirmación no corresponde a tu promoción.")
        if review.state == "active":
            return PromotionResult(
                promotion_id, "active", "La activación ya fue solicitada a Meta."
            )
        source = self.sources.get(tenant_id, UUID(promotion.request["publish_attempt_id"]))
        form = _form(promotion, review)
        expected = _request(
            tenant_id,
            source,
            form,
            approved_by,
            promotion.request["request_key"],
            datetime.fromisoformat(promotion.request["approved_at"]),
            currency_offset=promotion.request.get("meta_currency_offset"),
        )
        if fingerprint(expected.snapshot()) != review.request_hash:
            raise WizardUnavailable(
                "La publicación o la cuenta cambió. Prepara una nueva promoción."
            )
        access = await self.creation._access(promotion)
        if review.state != "ready":
            # Read-only reconciliation; never reactivate an operator-paused object.
            return await self._reconcile(access.client, promotion, review)
        self._enhancement_guard(promotion, review, source, approved_by)
        checks = await self.gateway.preflight(source, form)
        now = self.clock()
        _guard_checks(source, form, checks, now, actor=approved_by)
        if review.expires_at <= now:
            raise WizardUnavailable("La vista previa venció. Prepara una nueva promoción.")
        live = bool(checks.exact_validation)
        if live:
            if promotion.request.get("meta_currency_offset") != checks.currency_offset:
                raise WizardUnavailable(
                    "El importe aprobado usa otra unidad. Prepara una promoción nueva."
                )
            await self.gateway.remote_guard(promotion)
        remote_proof = None
        if form.enhancements is not None and form.enhancements.enabled:
            remote_proof = await self._remote_preview(
                promotion, source, approved_by, review.checks_snapshot["enhancements_preview"]
            )
        token = uuid4()
        self.authorize(tenant_id, approved_by)
        if not self.activations.claim(review, approved_by, now, token):
            return PromotionResult(promotion_id, "pending", "La confirmación ya está en proceso.")

        def current_consent() -> None:
            self.authorize(tenant_id, approved_by)
            current = self.clock()
            current_source = self.sources.get(tenant_id, source.publish_attempt_id)
            if live:
                self.gateway.local_guard(current_source)
            current_request = _request(
                tenant_id,
                current_source,
                form,
                approved_by,
                promotion.request["request_key"],
                datetime.fromisoformat(promotion.request["approved_at"]),
                currency_offset=promotion.request.get("meta_currency_offset"),
            )
            if fingerprint(current_request.snapshot()) != fingerprint(promotion.request):
                raise WizardUnavailable(
                    "La publicación o la cuenta cambió. Prepara otra promoción."
                )
            self._enhancement_guard(promotion, review, current_source, approved_by)
            if form.enhancements is not None:
                verify_compatibility(
                    form.enhancements, current_source, checks.enhancement_compatibility, current
                )
                if form.enhancements.enabled:
                    verify_remote_preview(
                        remote_proof, review.checks_snapshot["enhancements_preview"], current
                    )
            if current >= review.expires_at or current >= checks.expires_at:
                raise WizardUnavailable(
                    "La comprobación venció. Revisa la cuenta antes de repetirla."
                )
            if current >= form.start_time:
                raise WizardUnavailable(
                    "La fecha de inicio ya pasó. Revisa la cuenta antes de repetir la promoción."
                )

        try:
            # Children first; only the campaign update can enable delivery of the tree.
            activated: list[str] = []

            async def live_consent() -> None:
                current_consent()
                await self.gateway.remote_guard(promotion, active_resources=tuple(activated))
                current_consent()

            for resource in ("ads", "adsets", "campaigns"):
                current_consent()
                await access.client.update(
                    promotion.ids[resource],
                    params={"status": "ACTIVE"},
                    before_write=live_consent if live else current_consent,
                )
                activated.append(resource)
            if live:
                await self.gateway.remote_guard(promotion, active_resources=tuple(activated))
            review = self.activations.get(tenant_id, review_id)
            assert review is not None
            return await self._reconcile(access.client, promotion, review)
        except Exception:
            # The durable claim exists: even an unexpected local/DB failure may
            # follow an accepted remote write. Keep the UI in read-only recovery.
            # Cancellation/BaseException deliberately leaves the original claim.
            return self._uncertain(tenant_id, promotion_id, review_id, token)

    def _uncertain(
        self, tenant_id: UUID, promotion_id: UUID, review_id: UUID, token: UUID
    ) -> PromotionResult:
        try:
            self.activations.finish(tenant_id, review_id, token, "unknown")
        except Exception:
            # A failed audit update cannot make the remote outcome known. The
            # original in-flight claim remains the conservative recovery anchor.
            pass
        return PromotionResult(
            promotion_id,
            "unknown",
            "No pudimos confirmar la activación. Revisa la cuenta antes de repetirla.",
        )

    def _enhancement_guard(
        self,
        promotion: Promotion,
        review: ActivationReview,
        source: PromotionSource,
        actor: UUID,
    ) -> None:
        policy = BrandEnhancementSettings.from_snapshot(promotion.request["enhancements_snapshot"])
        current = self.creation.repository.current_enhancements(policy.tenant_id, policy.brand_id)
        try:
            observed_at = datetime.fromisoformat(
                review.checks_snapshot["enhancements_preview"]["observed_at"]
            )
            now = self.clock()
            valid_age = (
                observed_at.utcoffset() is not None
                and observed_at <= now
                and (now - observed_at).total_seconds() <= 300
                and review.expires_at <= observed_at + timedelta(minutes=5)
            )
        except (KeyError, TypeError, ValueError):
            raise WizardUnavailable(
                "Vuelve a preparar una vista previa para esta promoción."
            ) from None
        receipt = preview_receipt(
            promotion, source, actor, review.preview_hash, review.expires_at, observed_at
        )
        if not valid_age:
            raise WizardUnavailable("La vista previa venció. Prepara una nueva promoción.")
        if (
            current != policy.snapshot()
            or review.checks_snapshot.get("enhancements_preview") != receipt
            or review.preview_hash != hashlib.sha256(review.preview_html.encode()).hexdigest()
        ):
            raise WizardUnavailable(
                "Los permisos, la cuenta o la vista previa cambiaron. Prepara otra promoción."
            )
        if policy.enabled:
            verify_remote_preview(
                review.checks_snapshot.get("enhancements_remote_preview"), receipt, now
            )

    async def _remote_preview(
        self,
        promotion: Promotion,
        source: PromotionSource,
        actor: UUID,
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        reader = getattr(self.gateway, "enhancement_preview_evidence", None)
        if reader is None:
            raise WizardUnavailable(
                "Falta comprobar los cambios reales de la vista previa con Meta."
            )
        proof = await reader(
            source=source, promotion=promotion, actor=actor, preview_hash=receipt["preview_hash"]
        )
        verify_remote_preview(proof, receipt, self.clock())
        return proof

    async def _reconcile(
        self, client: Any, promotion: Promotion, review: ActivationReview
    ) -> PromotionResult:
        try:
            active = True
            for resource in ("ads", "adsets", "campaigns"):
                state = await client.status(promotion.ids[resource])
                active = active and state.get("status") == "ACTIVE"
            if active and promotion.request.get("meta_currency_offset") is not None:
                await self.gateway.remote_guard(
                    promotion, active_resources=("ads", "adsets", "campaigns")
                )
        except Exception:
            active = False
        assert review.claim_token is not None
        state = "active" if active else "unknown"
        try:
            self.activations.finish(review.tenant_id, review.id, review.claim_token, state)
        except Exception:
            return self._uncertain(review.tenant_id, promotion.id, review.id, review.claim_token)
        return PromotionResult(
            promotion.id,
            state,
            "La activación fue solicitada a Meta; su revisión y entrega pueden estar pendientes."
            if active
            else "No pudimos confirmar la activación. Revisa la cuenta antes de repetirla.",
        )

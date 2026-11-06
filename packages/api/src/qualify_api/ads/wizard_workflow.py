"""Injected, consent-gated orchestration; not composed into production paid execution.

Only the explicit fake in tests supplies verified preflight data today. Unknown
Meta rules never become permissive defaults. A future live adapter must implement
these contracts from evidence before the UI production wrappers may use it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
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
from qualify_api.ads.errors import MarketingError
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


class WizardGateway(Protocol):
    async def preflight(self, source: PromotionSource, form: WizardForm) -> VerifiedChecks: ...


class WizardSources(Protocol):
    def get(self, tenant_id: UUID, source_id: UUID) -> PromotionSource: ...


def _guard_checks(
    source: PromotionSource, form: WizardForm, checks: VerifiedChecks, now: datetime
) -> None:
    form.validate(for_execution=True)
    if form.enhancements is not None:
        if form.enhancements.brand_id != source.brand_id:
            raise WizardUnavailable("Los permisos corresponden a otra marca.")
        verify_compatibility(form.enhancements, source, checks.enhancement_compatibility, now)
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
    if (
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
    if form.budget_minor < checks.minimum_budget_minor:
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
) -> PromotionRequest:
    policy = form.enhancements or BrandEnhancementSettings(tenant_id, source.brand_id)
    return PromotionRequest(
        tenant_id=tenant_id,
        brand_id=source.brand_id,
        request_key=request_key,
        meta_ad_account_id=source.meta_ad_account_id,
        objective="OUTCOME_TRAFFIC",
        cta_type="LEARN_MORE",
        link_url=form.link_url,
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
            "source_instagram_media_id": source.source_media_id,
            "instagram_user_id": source.instagram_user_id,
            "call_to_action": {"type": "LEARN_MORE", "value": {"link": form.link_url}},
            "degrees_of_freedom_spec": policy.creative_spec(),
        },
        adset_options={
            "optimization_goal": "LINK_CLICKS",
            "billing_event": "IMPRESSIONS",
            "destination_type": "WEBSITE",
        },
    )


def _form(promotion: Promotion, checks: ActivationReview) -> WizardForm:
    request = promotion.request
    enhancements = BrandEnhancementSettings.from_snapshot(request["enhancements_snapshot"])
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
        _guard_checks(source, form, checks, now)
        repo = self.creation.repository
        existing = repo.by_request_key(tenant_id, request_key)
        stamp = datetime.fromisoformat(existing.request["approved_at"]) if existing else now
        request = _request(tenant_id, source, form, approved_by, request_key, stamp)
        # Approval snapshot conflict is detected before remote creation resumes.
        self.authorize(tenant_id, approved_by)
        promotion = await self.creation.start(request)
        if promotion.status != "paused" or len(promotion.ids) != 4:
            raise WizardUnavailable(
                "La creación quedó pendiente. Revisa la cuenta antes de repetirla."
            )
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
        _guard_checks(source, form, checks, observed_at)
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
        _guard_checks(source, form, checks, now)
        if review.expires_at <= now:
            raise WizardUnavailable("La vista previa venció. Prepara una nueva promoción.")
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
            for resource in ("ads", "adsets", "campaigns"):
                current_consent()
                await access.client.update(
                    promotion.ids[resource],
                    params={"status": "ACTIVE"},
                    before_write=current_consent,
                )
            review = self.activations.get(tenant_id, review_id)
            assert review is not None
            return await self._reconcile(access.client, promotion, review)
        except MarketingError:
            self.activations.finish(tenant_id, review_id, token, "unknown")
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
        except MarketingError:
            active = False
        assert review.claim_token is not None
        state = "active" if active else "unknown"
        self.activations.finish(review.tenant_id, review.id, review.claim_token, state)
        return PromotionResult(
            promotion.id,
            state,
            "La activación fue solicitada a Meta; su revisión y entrega pueden estar pendientes."
            if active
            else "No pudimos confirmar la activación. Revisa la cuenta antes de repetirla.",
        )

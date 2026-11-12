"""Production image-pair preparation and consent; no changes to the published wizard."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from PIL import Image, UnidentifiedImageError
from qualify_shared.objects.gate import ObjectGate, ObjectNotFound

from qualify_api.ads.activation_repository import ActivationReview, PostgresActivationRepository
from qualify_api.ads.client import MarketingClient
from qualify_api.ads.enhancements import compose_brand_policy
from qualify_api.ads.enhancements_service import load_brand_enhancements
from qualify_api.ads.errors import MarketingError
from qualify_api.ads.live_wizard import authorize_actor
from qualify_api.ads.promotion_repository import PostgresPromotionRepository
from qualify_api.ads.promotions import (
    STEPS,
    AccountAccess,
    Promotion,
    PromotionRequest,
    PromotionService,
    fingerprint,
    step_payload,
)
from qualify_api.ads.unpublished import (
    MAX_IMAGE_BYTES,
    ImageAdForm,
    ImageSelection,
    ImageSource,
    UnpublishedUnavailable,
    creative_payload,
)
from qualify_api.ads.unpublished_repository import (
    UnpublishedRepository,
    guard_source,
    load_image_source,
)
from qualify_api.connections.ad_accounts import GraphAdAccountReader, PostgresAccountBinding


@dataclass(frozen=True)
class UnpublishedPreview:
    recipe_id: UUID
    promotion_id: UUID
    review_id: UUID
    feed_html: str
    vertical_html: str
    expires_at: datetime


def image_bytes(gate: ObjectGate, source: ImageSource, asset: ImageSelection) -> bytes:
    """Use only server-resolved keys and measure bytes, MIME and dimensions before upload."""
    try:
        with gate.open_object(source.tenant_id, asset.object_key) as stream:
            data = stream.read(MAX_IMAGE_BYTES + 1)
        if not 0 < len(data) <= MAX_IMAGE_BYTES:
            raise UnpublishedUnavailable("Cada imagen del anuncio debe ocupar como máximo 8 MB.")
        with Image.open(io.BytesIO(data)) as image:
            if (
                image.size != (asset.width, asset.height)
                or Image.MIME.get(image.format) != asset.content_type
            ):
                raise UnpublishedUnavailable("La imagen cambió. Vuelve a elegir sus formatos.")
            image.verify()
        return data
    except (
        OSError,
        SyntaxError,
        ObjectNotFound,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ):
        raise UnpublishedUnavailable(
            "No pudimos leer la imagen de esta pieza. Vuelve a elegir las imágenes."
        ) from None


class _Binding:
    def __init__(self, source: ImageSource, access: AccountAccess) -> None:
        self.source, self.access = source, access

    async def resolve(
        self, tenant_id: UUID, brand_id: UUID, meta_ad_account_id: str
    ) -> AccountAccess:
        if (tenant_id, brand_id, meta_ad_account_id) != (
            self.source.tenant_id,
            self.source.brand_id,
            self.source.meta_account_id,
        ):
            raise UnpublishedUnavailable("La cuenta no corresponde a esta aprobación.")
        guard_source(self.source)
        return self.access


class UnpublishedImageService:
    """Backend seam for a future ads screen. Production dependencies, never implicit fakes."""

    def __init__(self, gate: ObjectGate) -> None:
        self.gate = gate
        self.recipes = UnpublishedRepository()
        self.promotions = PostgresPromotionRepository()
        self.reviews = PostgresActivationRepository()
        self.accounts = PostgresAccountBinding()

    def _guard(self, source: ImageSource, actor: UUID, expiry: datetime | None = None) -> None:
        authorize_actor(source.tenant_id, actor)
        guard_source(source)
        if expiry is not None and datetime.now(UTC) >= expiry:
            raise UnpublishedUnavailable("La comprobación venció. Prepara otra vista previa.")

    async def _account(self, source: ImageSource, actor: UUID) -> AccountAccess:
        self._guard(source, actor)
        access = await self.accounts.resolve(
            source.tenant_id, source.brand_id, source.meta_account_id
        )
        self._guard(source, actor)
        return access

    async def _observe(self, source: ImageSource, client: MarketingClient, actor: UUID) -> None:
        accounts = await GraphAdAccountReader(client._client).list_accounts(source.instagram_id)
        self._guard(source, actor)
        match = next((row for row in accounts if row.ad_account_id == source.meta_account_id), None)
        if (
            match is None
            or match.instagram_assigned is not True
            or match.has_funding_source is not True
            or match.account_status != 1
            or match.disable_reason != 0
            or match.currency != source.currency
            or match.timezone_name != source.timezone_name
        ):
            raise UnpublishedUnavailable(
                "Revisa el acceso, los pagos y la cuenta publicitaria en Meta."
            )
        account = await client.read_account(fields="account_id,currency,failed_delivery_checks")
        self._guard(source, actor)
        if (
            account.get("account_id") != source.meta_account_id
            or account.get("currency") != "COP"
            or account.get("failed_delivery_checks") != []
        ):
            raise UnpublishedUnavailable("Meta no confirmó que esta cuenta pueda anunciar.")

    async def _upload(
        self, source: ImageSource, asset: ImageSelection, client: MarketingClient, actor: UUID
    ) -> tuple[str, str]:
        data = image_bytes(self.gate, source, asset)
        digest = hashlib.sha256(data).hexdigest()
        self._guard(source, actor)
        row, claimed = self.recipes.claim_upload(source, asset, digest)
        if row["state"] == "created":
            return row["image_hash"], digest
        if not claimed:
            raise UnpublishedUnavailable(
                "No pudimos confirmar la carga en Meta. "
                "Pide ayuda para revisarla antes de continuar."
            )
        try:
            value = await client.upload_image(data, before_write=lambda: self._guard(source, actor))
        except BaseException:
            self.recipes.finish_upload(source.tenant_id, row["id"], None)
            raise
        self.recipes.finish_upload(source.tenant_id, row["id"], value)
        self._guard(source, actor)
        return value, digest

    async def _validate(
        self,
        client: MarketingClient,
        promotion: Promotion,
        source: ImageSource,
        actor: UUID,
        expiry: datetime | None = None,
    ) -> None:
        campaign = step_payload(promotion, "campaigns")
        adset = step_payload(promotion, "adsets")
        adset.pop("campaign_id")
        adset["campaign_spec"] = campaign
        creative = step_payload(promotion, "adcreatives")
        ad = {
            "name": "qualify-validation",
            "status": "PAUSED",
            "adset_spec": adset,
            "creative": creative,
        }
        for resource, payload in zip(STEPS, (campaign, adset, creative, ad), strict=True):
            await client.validate(resource, params=payload)
            self._guard(source, actor, expiry)

    async def prepare(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        ad_account_id: UUID,
        feed_asset_id: UUID,
        vertical_asset_id: UUID,
        form: ImageAdForm,
        actor: UUID,
        request_key: UUID,
        confirm_preparation: bool,
    ) -> UnpublishedPreview:
        if confirm_preparation is not True:
            raise UnpublishedUnavailable("Confirma la preparación del anuncio en pausa.")
        form.validate(datetime.now(UTC))
        source = load_image_source(
            tenant_id, draft_id, ad_account_id, feed_asset_id, vertical_asset_id
        )
        self._guard(source, actor)
        recipe = self.recipes.approve(source, form, actor, request_key)
        access = await self._account(source, actor)
        client = access.client
        try:
            await self._observe(source, client, actor)
            uploaded = [
                await self._upload(source, asset, client, actor)
                for asset in (source.feed, source.vertical)
            ]
            policy = load_brand_enhancements(tenant_id=tenant_id, brand_id=source.brand_id)
            if policy.enabled:
                raise UnpublishedUnavailable(
                    "Desactiva las mejoras automáticas de esta marca antes de preparar el anuncio."
                )
            request = compose_brand_policy(
                PromotionRequest(
                    tenant_id=tenant_id,
                    brand_id=source.brand_id,
                    request_key=f"unpublished:{request_key}",
                    meta_ad_account_id=source.meta_account_id,
                    objective="OUTCOME_TRAFFIC",
                    cta_type=form.cta_type,
                    link_url=form.link_url,
                    budget_kind="lifetime",
                    budget_minor=form.budget_minor,
                    currency="COP",
                    start_time=form.start_time,
                    end_time=form.end_time,
                    approved_by=actor,
                    approved_at=recipe["approved_at"],
                    content_draft_id=draft_id,
                    meta_currency_offset=1,
                    targeting={
                        "geo_locations": {"countries": [form.country]},
                        "publisher_platforms": ["instagram"],
                        "instagram_positions": ["stream", "story", "reels"],
                        "targeting_automation": {"advantage_audience": 0},
                    },
                    adset_options={
                        "billing_event": "IMPRESSIONS",
                        "optimization_goal": "LINK_CLICKS",
                        "destination_type": "WEBSITE",
                    },
                    creative=creative_payload(source, form, tuple(row[0] for row in uploaded)),
                ),
                policy,
            )
            dummy = Promotion(uuid4(), request.snapshot(), ids={key: "0" for key in STEPS})
            expiry = datetime.now(UTC) + timedelta(minutes=5)
            await self._validate(client, dummy, source, actor, expiry)
            promotion = self.promotions.create_or_get(request)
            self.recipes.link(tenant_id, recipe["id"], promotion.id)

            async def fence() -> None:
                self._guard(source, actor, expiry)
                current = load_brand_enhancements(tenant_id=tenant_id, brand_id=source.brand_id)
                if current.snapshot() != policy.snapshot():
                    raise UnpublishedUnavailable(
                        "Las mejoras automáticas de la marca cambiaron. Prepara otra vista previa."
                    )

            async def validate_step(promotion: Promotion, resource: str, payload: dict) -> None:
                await client.validate(resource, params=payload)
                await fence()

            promotion = await PromotionService(self.promotions, _Binding(source, access)).resume(
                tenant_id, promotion.id, before_write=fence, validate_step=validate_step
            )
            if len(promotion.ids) != len(STEPS):
                raise UnpublishedUnavailable(
                    "La creación quedó pendiente de comprobación. No se activó el anuncio."
                )
            await self._remote(client, promotion, source, actor)
            previews = []
            for placement in ("INSTAGRAM_STANDARD", "INSTAGRAM_STORY"):
                page = await client.adpreviews(
                    promotion.ids["ads"], params={"ad_format": placement}
                )
                await fence()
                body = page.data[0].get("body") if len(page.data) == 1 else None
                if not isinstance(body, str) or not body.strip() or len(body) > 200_000:
                    raise UnpublishedUnavailable(
                        "Meta no devolvió las dos vistas previas del anuncio."
                    )
                previews.append(body)
            review = self.reviews.create(
                ActivationReview(
                    uuid4(),
                    tenant_id,
                    promotion.id,
                    fingerprint(promotion.request),
                    previews[0],
                    fingerprint(previews),
                    {
                        "kind": "unpublished-images",
                        "recipe_id": str(recipe["id"]),
                        "source": source.snapshot(),
                        "digests": [row[1] for row in uploaded],
                        "previews": previews,
                    },
                    expiry,
                    actor,
                )
            )
            return UnpublishedPreview(
                recipe["id"], promotion.id, review.id, *previews, review.expires_at
            )
        except MarketingError:
            raise UnpublishedUnavailable(
                "Meta no confirmó la preparación. No se activó el anuncio."
            ) from None
        finally:
            await client.aclose()

    async def _remote(
        self,
        client: MarketingClient,
        promotion: Promotion,
        source: ImageSource,
        actor: UUID,
        activated: tuple[str, ...] = (),
    ) -> None:
        """No permissive identity-only check: compare parents and exact approved payloads."""
        fields = {
            "campaigns": "id,account_id,status,objective,special_ad_categories",
            "adsets": (
                "id,account_id,status,campaign_id,lifetime_budget,targeting,start_time,end_time,"
                "billing_event,optimization_goal,destination_type"
            ),
            "adcreatives": (
                "id,account_id,object_story_spec,asset_feed_spec,degrees_of_freedom_spec"
            ),
            "ads": "id,account_id,status,campaign_id,adset_id,creative",
        }
        for resource in STEPS:
            value = await client.read_object(promotion.ids[resource], fields=fields[resource])
            self._guard(source, actor)
            expected = step_payload(promotion, resource)
            expected.pop("name", None)
            expected.pop("status", None)
            if resource == "ads":
                expected["creative"] = {"id": promotion.ids["adcreatives"]}
            if (
                value.get("id") != promotion.ids[resource]
                or value.get("account_id") != source.meta_account_id
                or (
                    resource != "adcreatives"
                    and value.get("status") != ("ACTIVE" if resource in activated else "PAUSED")
                )
            ):
                raise UnpublishedUnavailable(
                    "El anuncio en Meta cambió. No confirmamos su activación."
                )
            for key, item in expected.items():
                actual = value.get(key)
                if key in {"start_time", "end_time"}:
                    try:
                        same = datetime.fromisoformat(actual) == datetime.fromisoformat(item)
                    except (TypeError, ValueError):
                        same = False
                elif key == "lifetime_budget":
                    same = str(actual) == str(item)
                else:
                    same = actual == item
                if not same:
                    raise UnpublishedUnavailable(
                        "Meta no confirmó la configuración exacta del anuncio."
                    )
        for parent, child, kind in (("campaigns", "adsets", "adsets"), ("adsets", "ads", "ads")):
            children = await client.children(promotion.ids[parent], resource=kind)
            self._guard(source, actor)
            if len(children) != 1 or children[0].get("id") != promotion.ids[child]:
                raise UnpublishedUnavailable("La campaña cambió. Revisa sus anuncios en Meta.")

    async def confirm(
        self,
        *,
        tenant_id: UUID,
        recipe_id: UUID,
        review_id: UUID,
        actor: UUID,
        confirm_charge: bool,
    ) -> str:
        if confirm_charge is not True:
            raise UnpublishedUnavailable("Confirma el presupuesto antes de activar el anuncio.")
        recipe = self.recipes.recipe(tenant_id, recipe_id)
        snapshot = recipe["source"]
        source = load_image_source(
            tenant_id,
            UUID(snapshot["draft_id"]),
            recipe["ad_account_id"],
            UUID(snapshot["feed"]["asset_id"]),
            UUID(snapshot["vertical"]["asset_id"]),
        )
        review = self.reviews.get(tenant_id, review_id)
        promotion = self.promotions.get(tenant_id, recipe["promotion_id"])
        if (
            review is None
            or promotion is None
            or review.promotion_id != promotion.id
            or recipe["approved_by"] != actor
            or review.prepared_by != actor
            or review.checks_snapshot.get("recipe_id") != str(recipe_id)
            or review.checks_snapshot.get("source") != source.snapshot()
            or review.request_hash != fingerprint(promotion.request)
            or review.preview_hash != fingerprint(review.checks_snapshot.get("previews"))
        ):
            raise UnpublishedUnavailable("La aprobación cambió. Prepara otra vista previa.")
        self._guard(source, actor, review.expires_at)
        digests = [
            hashlib.sha256(image_bytes(self.gate, source, asset)).hexdigest()
            for asset in (source.feed, source.vertical)
        ]
        if digests != review.checks_snapshot.get("digests"):
            raise UnpublishedUnavailable("Las imágenes cambiaron. Prepara otra vista previa.")
        if review.state != "ready":
            return "active" if review.state == "active" else "unknown"
        access = await self._account(source, actor)
        client = access.client
        token = uuid4()
        claimed = False
        try:
            await self._observe(source, client, actor)
            await self._validate(client, promotion, source, actor, review.expires_at)
            await self._remote(client, promotion, source, actor)
            self._guard(source, actor, review.expires_at)
            if not self.reviews.claim(review, actor, datetime.now(UTC), token):
                return "unknown"
            claimed = True
            activated: list[str] = []

            async def fence() -> None:
                self._guard(source, actor, review.expires_at)
                policy = load_brand_enhancements(tenant_id=tenant_id, brand_id=source.brand_id)
                if policy.snapshot() != promotion.request["enhancements_snapshot"]:
                    raise UnpublishedUnavailable(
                        "Las mejoras automáticas de la marca cambiaron. Prepara otra vista previa."
                    )
                for asset, digest in zip((source.feed, source.vertical), digests, strict=True):
                    if hashlib.sha256(image_bytes(self.gate, source, asset)).hexdigest() != digest:
                        raise UnpublishedUnavailable(
                            "Las imágenes cambiaron. No activamos el anuncio."
                        )
                # The write client's account lock is held here. Use another authenticated
                # read client; never re-enter the same MarketingClient lock.
                observed = await self._account(source, actor)
                try:
                    await self._observe(source, observed.client, actor)
                    await self._remote(observed.client, promotion, source, actor, tuple(activated))
                finally:
                    await observed.client.aclose()
                self._guard(source, actor, review.expires_at)

            for resource in ("ads", "adsets", "campaigns"):
                await client.update(
                    promotion.ids[resource], params={"status": "ACTIVE"}, before_write=fence
                )
                activated.append(resource)
            await self._remote(client, promotion, source, actor, tuple(activated))
            self.reviews.finish(tenant_id, review.id, token, "active")
            return "active"
        except BaseException:
            if claimed:
                self.reviews.finish(tenant_id, review.id, token, "unknown")
            raise
        finally:
            await client.aclose()

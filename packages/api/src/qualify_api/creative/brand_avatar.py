"""The brand's «avatar animado» — SCAFFOLD (§ request 2026-10-19, design:
docs/brand-kit-avatar-animado.md).

When the operator finishes the Brand Kit, Qualify draws the brand an animated-style
mascot with Seedream (BytePlus ModelArk) from what the kit already knows: name, rubro,
positioning, audience, palette, tone and the logo as a reference image. The Brand Kit
editor shows it and offers «Regenerar».

**State: wired behind a switch, never run live.** The BytePlus keys for this are not
available yet, so:

- Nothing happens unless BOTH ``QUALIFY_BRAND_AVATAR`` is on AND the ModelArk key
  (``QUALIFY_BYTEPLUS_ARK_API_KEY``, the one Seedream already uses) is set —
  `avatar_unavailable_reason` says which is missing, and `generate_brand_avatar` raises
  `BrandAvatarUnavailable` before touching the network, the database or R2.
- The prompt builder (`avatar_inputs` + `build_avatar_prompt`) is real, pure and tested.
- The orchestration (`generate_brand_avatar`) is real and tested against fakes; its
  production collaborators (`production_deps`) reuse the existing seams — the
  `CreativeRouter` over `SeedreamImageAdapter` with the platform key resolver, the R2
  object gate, `BrandKitStore` — but have never run against BytePlus. Every ``TODO(keys)``
  below is a step to close once the keys arrive (checklist in the design doc).

Storage: the image goes to R2 under the brand's prefix
(``t/<tenant>/brand/<brand>/avatar/<uuid>.jpg``) and its record — with provenance:
provider, model id and revision, prompt and prompt version, cost — into the reserved
``brand_avatar`` key of ``brand_kit_details.logo_brief`` (`BrandKitStore.save_avatar`), so
no migration is needed.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from qualify_creative.schemas import BrandContext, BrandKit

logger = logging.getLogger(__name__)

#: The feature switch — off by default. Truthy: 1 / true / yes / on.
AVATAR_SWITCH_ENV = "QUALIFY_BRAND_AVATAR"
#: The key Seedream already resolves through (`composition.PROVIDER_KEY_ENVS["seedream"]`);
#: repeated here so reading the switch never imports the composition root.
ARK_KEY_ENV = "QUALIFY_BYTEPLUS_ARK_API_KEY"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

#: Bumped whenever `build_avatar_prompt` changes what it asks for — provenance: an avatar
#: says which prompt drew it, so a regeneration under a new version is explainable.
PROMPT_VERSION = "brand-avatar-v0"
#: Square, at the size the ad scenes use for 1:1 (`media.SCENE_SIZES["1:1"]`).
AVATAR_SIZE = "2048x2048"
AVATAR_CONTENT_TYPE = "image/jpeg"
#: The pre-flight cap for one avatar: Seedream 5.0 lite bills USD 0.035 per image
#: (pricing v5), so this blocks only a misconfigured model, never a normal run.
AVATAR_BUDGET_USD = Decimal("0.10")
#: Caps for each kit text that enters the prompt (one line each): Seedream's recommended
#: prompt is ~600 English words; the whole prompt stays well under the adapter's 3,000.
_FIELD_CHARS = 180
_MAX_PALETTE = 5
_HEX = re.compile(r"^#?([0-9A-Fa-f]{6})$")


class AvatarStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class BrandAvatarUnavailable(RuntimeError):
    """The feature is off or its key is missing — nothing was attempted. `reason` is one
    of `REASON_SWITCH_OFF` / `REASON_MISSING_KEY` / `REASON_NO_KIT`."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BrandAvatarFailed(RuntimeError):
    """The generation was attempted and failed; a `failed` record was written."""


REASON_SWITCH_OFF = "switch_off"
REASON_MISSING_KEY = "missing_key"
REASON_NO_KIT = "no_kit"


def avatar_unavailable_reason(env: Mapping[str, str] | None = None) -> str | None:
    """None when the avatar may be generated; otherwise why not (switch first)."""
    env = os.environ if env is None else env
    if env.get(AVATAR_SWITCH_ENV, "").strip().lower() not in _TRUTHY:
        return REASON_SWITCH_OFF
    if not env.get(ARK_KEY_ENV, "").strip():
        return REASON_MISSING_KEY
    return None


def avatar_enabled(env: Mapping[str, str] | None = None) -> bool:
    return avatar_unavailable_reason(env) is None


# ---------------------------------------------------------------------------------------
# The prompt — pure


@dataclass(frozen=True)
class AvatarInputs:
    """What the kit says that shapes the avatar, already trimmed to one line each."""

    brand_name: str = ""
    sector: str = ""
    positioning: str = ""
    audience: str = ""
    location: str = ""
    account_category: str = ""
    #: Hex colours, "#RRGGBB", at most `_MAX_PALETTE`.
    palette: tuple[str, ...] = ()
    #: The four tone axes, 0-100 (formal→coloquial, sobrio→entusiasta, técnico→llano,
    #: breve→elaborado); None when the kit has none.
    tone: tuple[int, int, int, int] | None = None
    #: The logo brief's «sensación» and «estilo» (the operator's own words).
    feeling: str = ""
    style: str = ""
    #: The brand's main logo in R2 (`brand_kits.logo_asset_key`), sent as a reference.
    logo_key: str | None = None


def _line(value: object, limit: int = _FIELD_CHARS) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _palette(colours: Sequence[str]) -> tuple[str, ...]:
    out: list[str] = []
    for colour in colours:
        match = _HEX.match(str(colour).strip())
        if match and f"#{match.group(1).upper()}" not in out:
            out.append(f"#{match.group(1).upper()}")
    return tuple(out[:_MAX_PALETTE])


def avatar_inputs(
    kit: BrandKit,
    *,
    brand_name: str = "",
    context: BrandContext | None = None,
    logo_brief: Mapping[str, Any] | None = None,
) -> AvatarInputs:
    """The kit (and what the Brand Kit saved beyond it) → the prompt's inputs."""
    context = context or BrandContext()
    brief = logo_brief or {}
    axes = kit.tone_axes
    return AvatarInputs(
        brand_name=_line(brand_name, 80),
        sector=_line(context.sector),
        positioning=_line(kit.positioning),
        audience=_line(kit.audience),
        location=_line(context.location, 80),
        account_category=_line(context.account_category, 80),
        palette=_palette(kit.palette_rgb),
        tone=(
            axes.formal_casual,
            axes.sober_enthusiastic,
            axes.technical_plain,
            axes.brief_elaborate,
        ),
        feeling=_line(brief.get("feeling")),
        style=_line(brief.get("style")),
        logo_key=kit.logo_asset_key or None,
    )


def _tone_lines(tone: tuple[int, int, int, int] | None) -> list[str]:
    """The axes that move the picture (brief→elaborate is about text; it does not)."""
    if tone is None:
        return []
    casual, enthusiastic, plain, _ = tone
    lines: list[str] = []
    if casual >= 60:
        lines.append("relaxed, approachable and playful body language")
    elif casual <= 40:
        lines.append("composed, professional posture")
    if enthusiastic >= 60:
        lines.append("energetic, big warm smile")
    elif enthusiastic <= 40:
        lines.append("calm, understated expression")
    if plain <= 40:
        lines.append("one subtle detail that hints at the expertise of the trade")
    return lines


def build_avatar_prompt(inputs: AvatarInputs) -> str:
    """The Seedream prompt for the brand's mascot. English instructions (Seedream follows
    them best); the brand's own words go in as written, in quotes.

    TODO(keys): tune against real outputs — style keywords, how strongly the logo
    reference is followed, and whether «animado» should read as 3D or 2D (open question
    in the design doc)."""
    parts: list[str] = [
        "Create the official mascot character of a brand, as a friendly animated "
        "character in a modern 3D animated-film style: one character, full body, "
        "centred, facing the viewer, on a plain soft background.",
    ]
    about: list[str] = []
    if inputs.brand_name:
        about.append(f'The brand is called "{inputs.brand_name}".')
    if inputs.sector:
        about.append(f'Its business: "{inputs.sector}".')
    if inputs.account_category and inputs.account_category != inputs.sector:
        about.append(f'Category: "{inputs.account_category}".')
    if inputs.positioning:
        about.append(f'How it presents itself: "{inputs.positioning}".')
    if inputs.audience:
        about.append(f'Who it speaks to: "{inputs.audience}".')
    if inputs.location:
        about.append(f'Where it is: "{inputs.location}".')
    if about:
        parts.append(" ".join(about))
    parts.append(
        "The character should embody what this business does, so a customer recognises "
        "the trade at a glance."
    )
    if inputs.palette:
        parts.append(
            "Use the brand colours as the character's main colours: "
            + ", ".join(inputs.palette)
            + "."
        )
    tone = _tone_lines(inputs.tone)
    if tone:
        parts.append("Personality: " + "; ".join(tone) + ".")
    if inputs.feeling:
        parts.append(f'The brand wants to make people feel: "{inputs.feeling}".')
    if inputs.style:
        parts.append(f'Visual style the brand likes: "{inputs.style}".')
    if inputs.logo_key:
        parts.append(
            "The reference image is the brand's logo: echo its shapes and colours in the "
            "character, but do not draw the logo itself."
        )
    parts.append("No text, no letters, no logos, no watermark.")
    return " ".join(parts)


# ---------------------------------------------------------------------------------------
# The record


@dataclass(frozen=True)
class BrandAvatar:
    """One avatar as stored (`BrandKitStore.save_avatar`), with its provenance."""

    status: AvatarStatus
    object_key: str = ""
    content_type: str = ""
    provider: str = ""
    model_id: str = ""
    model_revision: str = ""
    prompt: str = ""
    prompt_version: str = PROMPT_VERSION
    cost_usd: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    #: A failure in the operator's words ("" unless `failed`).
    error: str = ""

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["status"] = self.status.value
        return record

    @classmethod
    def from_record(cls, record: Mapping[str, Any] | None) -> BrandAvatar | None:
        if not record:
            return None
        try:
            status = AvatarStatus(str(record.get("status", "")))
        except ValueError:
            return None
        known = {name for name in cls.__dataclass_fields__ if name != "status"}
        return cls(status=status, **{k: str(v) for k, v in record.items() if k in known})


def avatar_object_key(tenant_id: UUID, brand_id: UUID) -> str:
    """A fresh key per generation (a regeneration never overwrites what a page may still
    be showing), inside the brand's prefix (`brand_kit_store.brand_asset_prefix`)."""
    from qualify_api.creative.brand_kit_store import brand_asset_prefix

    return f"{brand_asset_prefix(tenant_id, brand_id)}avatar/{uuid4().hex}.jpg"


# ---------------------------------------------------------------------------------------
# Orchestration


@dataclass(frozen=True)
class SeedreamImage:
    """What one Seedream call gave back — the subset of `GenerationResult` kept."""

    data: bytes
    provider: str
    model_id: str
    model_revision: str
    cost_usd: Decimal


@dataclass(frozen=True)
class AvatarDeps:
    """The collaborators, injectable so tests never touch the network, R2 or Postgres."""

    #: (tenant, brand) → the prompt's inputs; None when the brand has no kit yet.
    load_inputs: Callable[[UUID, UUID], AvatarInputs | None]
    #: An R2 key → its bytes (the logo reference); None when it cannot be read.
    read_media: Callable[[str], bytes | None]
    #: (tenant, brand, prompt, reference images) → the image. Raises on failure.
    render: Callable[[UUID, UUID, str, list[bytes]], SeedreamImage]
    #: (tenant, key, bytes, content type) → stored in R2.
    put_media: Callable[[UUID, str, bytes, str], None]
    #: (tenant, brand, record or None) → `BrandKitStore.save_avatar`.
    save_record: Callable[[UUID, UUID, Mapping[str, Any] | None], None]


def generate_brand_avatar(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    env: Mapping[str, str] | None = None,
    deps: AvatarDeps | None = None,
) -> BrandAvatar:
    """Draw (or redraw) the brand's avatar and store it; returns the `ready` record.

    Raises `BrandAvatarUnavailable` — having done NOTHING — when the switch is off, the
    key is missing or the brand has no kit; raises `BrandAvatarFailed` after storing a
    `failed` record when Seedream or R2 fails. Blocking: call it off the event loop."""
    reason = avatar_unavailable_reason(env)
    if reason is not None:
        raise BrandAvatarUnavailable(reason)
    deps = deps or production_deps()
    inputs = deps.load_inputs(tenant_id, brand_id)
    if inputs is None:
        raise BrandAvatarUnavailable(REASON_NO_KIT)
    prompt = build_avatar_prompt(inputs)
    deps.save_record(
        tenant_id, brand_id, BrandAvatar(status=AvatarStatus.PENDING, prompt=prompt).to_record()
    )
    references: list[bytes] = []
    if inputs.logo_key:
        logo = deps.read_media(inputs.logo_key)
        if logo:
            references.append(logo)
    try:
        image = deps.render(tenant_id, brand_id, prompt, references)
        key = avatar_object_key(tenant_id, brand_id)
        deps.put_media(tenant_id, key, image.data, AVATAR_CONTENT_TYPE)
    except Exception as exc:
        logger.warning("brand avatar failed: %s", type(exc).__name__)
        deps.save_record(
            tenant_id,
            brand_id,
            BrandAvatar(
                status=AvatarStatus.FAILED,
                prompt=prompt,
                error="No pudimos crear tu avatar. Inténtalo de nuevo más tarde.",
            ).to_record(),
        )
        raise BrandAvatarFailed(type(exc).__name__) from exc
    avatar = BrandAvatar(
        status=AvatarStatus.READY,
        object_key=key,
        content_type=AVATAR_CONTENT_TYPE,
        provider=image.provider,
        model_id=image.model_id,
        model_revision=image.model_revision,
        prompt=prompt,
        cost_usd=str(image.cost_usd),
    )
    deps.save_record(tenant_id, brand_id, avatar.to_record())
    return avatar


def maybe_generate_after_kit(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    env: Mapping[str, str] | None = None,
    deps: AvatarDeps | None = None,
) -> BrandAvatar | None:
    """The Brand Kit completion hook: generate when enabled, otherwise a silent no-op.
    Never raises — a missing avatar must never make finishing the kit look failed."""
    if not avatar_enabled(env):
        return None
    try:
        return generate_brand_avatar(tenant_id, brand_id, env=env, deps=deps)
    except (BrandAvatarUnavailable, BrandAvatarFailed):
        return None
    except Exception as exc:  # noqa: BLE001 — a background hook logs, never propagates
        logger.warning("brand avatar hook failed: %s", type(exc).__name__)
        return None


def load_brand_avatar(tenant_id: UUID, brand_id: UUID, *, store: Any = None) -> BrandAvatar | None:
    """The stored avatar record (any status), or None."""
    from qualify_api.creative.brand_kit_store import BrandKitStore

    store = store or BrandKitStore()
    return BrandAvatar.from_record(store.load_avatar(tenant_id=tenant_id, brand_id=brand_id))


# ---------------------------------------------------------------------------------------
# Production wiring — TODO(keys): never run against BytePlus yet


def production_deps() -> AvatarDeps:
    """The real collaborators, built lazily (nothing here is imported or constructed
    while the switch is off). Reuses the existing seams rather than a new client.

    TODO(keys), before switching it on anywhere:
    - record the spend in the usage ledger (`observed` / `billing.usage_events` once it
      exists) — today the cost only lands in the avatar's own record;
    - trace the call in Langfuse (`observed.traced_providers`) like the ad scenes;
    - map ModelArk errors/moderation to the operator's words (`media.ark_failure_text`);
    - run it once live and pin what Seedream really returns for a mascot prompt."""
    from qualify_creative.adapters.byteplus_ark import (
        BASE_URL,
        DEFAULT_SEEDREAM_MODEL,
        SeedreamImageAdapter,
    )
    from qualify_creative.enums import GenerationTask
    from qualify_creative.pricing import JsonPricingTable
    from qualify_creative.providers import GenerationRequest, RenderedPrompt
    from qualify_creative.router import BudgetContext, CreativeRouter

    from qualify_api.creative.brand_context import DbBrandContextReader
    from qualify_api.creative.brand_kit_store import BrandKitStore
    from qualify_api.creative.brand_names import DbBrandNames
    from qualify_api.creative.brand_service import BrandKitService
    from qualify_api.creative.composition import (
        ARK_BASE_URL_ENV,
        PRICING_VERSION,
        SEEDREAM_MODEL_ENV,
        PlatformKeyResolver,
        media_root,
    )
    from qualify_api.creative.media import LocalMediaStore, R2ReadingMediaStore
    from qualify_api.creative.media import _data_url as reference_data_url

    store = BrandKitStore()
    pricing = JsonPricingTable(PRICING_VERSION)
    router = CreativeRouter(
        providers={
            "seedream": SeedreamImageAdapter(
                model=os.environ.get(SEEDREAM_MODEL_ENV) or DEFAULT_SEEDREAM_MODEL,
                base_url=os.environ.get(ARK_BASE_URL_ENV) or BASE_URL,
            )
        },
        pricing=pricing,
        credentials=PlatformKeyResolver(),
    )
    media = R2ReadingMediaStore(LocalMediaStore(media_root()))

    def load_inputs(tenant_id: UUID, brand_id: UUID) -> AvatarInputs | None:
        kit = BrandKitService().get_kit(tenant_id=tenant_id, brand_id=brand_id)
        if kit is None:
            return None
        details = store.load_details(tenant_id=tenant_id, brand_id=brand_id)
        return avatar_inputs(
            kit,
            brand_name=DbBrandNames()(tenant_id=tenant_id, brand_id=brand_id),
            context=DbBrandContextReader(store).context(tenant_id=tenant_id, brand_id=brand_id),
            logo_brief=details.logo_brief,
        )

    def read_media(key: str) -> bytes | None:
        try:
            return media.read(key)
        except Exception as exc:  # noqa: BLE001 — no logo reference is not fatal
            logger.warning("brand avatar logo not read: %s", type(exc).__name__)
            return None

    def render(
        tenant_id: UUID, brand_id: UUID, prompt: str, references: list[bytes]
    ) -> SeedreamImage:
        request = GenerationRequest(
            task=GenerationTask.PRODUCT_IMAGE,
            rendered_prompt=RenderedPrompt("", "", ""),
            params={
                "prompt": prompt,
                # normalized to the JPEG <= 2048 px ModelArk takes, like the ad scenes
                "images": [reference_data_url(image) for image in references],
                "size": AVATAR_SIZE,
            },
        )
        outcome = router.run(
            tenant_id=tenant_id,
            brand_id=brand_id,
            chain=("seedream",),
            request=request,
            budget=BudgetContext(remaining_usd=AVATAR_BUDGET_USD),
        )
        result = outcome.result
        if result is None:
            detail = "; ".join(h.reason or h.action.value for h in outcome.hops)
            raise RuntimeError(f"seedream: {detail}")
        payload = result.payload if isinstance(result.payload, Mapping) else {}
        images = payload.get("images") or ()
        if not images:
            raise RuntimeError(f"{result.model_id} returned no image")
        pieces = max(result.usage.pieces, 1)
        price = pricing.unit_price(model_id=result.model_id, unit="per_piece")
        return SeedreamImage(
            data=bytes(images[0]),
            provider=result.provider,
            model_id=result.model_id,
            model_revision=result.model_revision or result.model_id,
            cost_usd=price * pieces,
        )

    def put_media(tenant_id: UUID, key: str, data: bytes, content_type: str) -> None:
        import io

        from qualify_shared.objects.config import R2Settings
        from qualify_shared.objects.gate import ObjectGate
        from qualify_shared.objects.s3 import R2ObjectStore

        ObjectGate(R2ObjectStore(R2Settings.from_env())).put_media(
            tenant_id, key, io.BytesIO(data), content_type
        )

    def save_record(tenant_id: UUID, brand_id: UUID, record: Mapping[str, Any] | None) -> None:
        store.save_avatar(tenant_id=tenant_id, brand_id=brand_id, record=record)

    return AvatarDeps(
        load_inputs=load_inputs,
        read_media=read_media,
        render=render,
        put_media=put_media,
        save_record=save_record,
    )

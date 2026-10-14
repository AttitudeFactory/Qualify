"""From a Post to the JSON a composition receives (CONTRACT.md §2), validated against
the manifest BEFORE a render is asked for.

The validation here is the cheap, deterministic gate the research on layout loops says
pays most (research-bucle-vision-plantillas.md §3): a hook longer than its port, two
photos where the template wants three, a video port with no video — all caught for free,
before a process is spawned. The render service re-validates and answers
`422 invalid_parameters`; by then it should never happen.

Media is referenced by *store key* while props are built (`key://<store key>`), and the
adapter swaps each for the service's `asset://<id>` after uploading. Compositions never
see storage keys or signed URLs.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from qualify_creative.render.manifest import InputPort, PortType, TemplateManifest
from qualify_creative.schemas import BrandKit, ContentBrief, CopyPayload

KEY_SCHEME = "key://"
ASSET_SCHEME = "asset://"


class BrandProps(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    palette: tuple[str, ...] = ()
    fonts: dict[str, str] = Field(default_factory=dict)
    logo: str | None = None
    tone: str = ""


class ProductProps(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    price: str = ""
    photo: str | None = None


class RenderProps(BaseModel):
    """`meta.port` is filled by the service per output; Python leaves it empty."""

    model_config = ConfigDict(frozen=True)

    meta: dict[str, Any]
    brand: BrandProps
    texts: dict[str, str]
    photos: tuple[str, ...] = ()
    video: str | None = None
    products: tuple[ProductProps, ...] = ()

    def media_refs(self) -> list[str]:
        """Every media reference once, in order of first appearance (a product photo that
        is also one of the photos is uploaded once)."""
        refs: list[str] = []
        for ref in (*self.photos, self.video, self.brand.logo, *(p.photo for p in self.products)):
            if ref and ref not in refs:
                refs.append(ref)
        return refs

    def with_media(self, mapping: Mapping[str, str]) -> RenderProps:
        """Return a copy with every media reference replaced through `mapping`
        (store key → `asset://id`). A reference missing from the mapping is left as is,
        so a caller can prove nothing leaked by checking `unresolved()` afterwards."""

        def sub(ref: str | None) -> str | None:
            return None if ref is None else mapping.get(ref, ref)

        return self.model_copy(
            update={
                "photos": tuple(sub(p) or p for p in self.photos),
                "video": sub(self.video),
                "brand": self.brand.model_copy(update={"logo": sub(self.brand.logo)}),
                "products": tuple(
                    p.model_copy(update={"photo": sub(p.photo)}) for p in self.products
                ),
            }
        )

    def unresolved(self) -> list[str]:
        return [r for r in self.media_refs() if r.startswith(KEY_SCHEME)]

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


@dataclass(frozen=True)
class PropsProblem:
    port: str
    code: str  # missing | too_long | too_few | too_many | not_in_enum | wrong_type
    message: str


@dataclass(frozen=True)
class ProductFacts:
    """What the catalog knows about a product the Post is about — a thin shape so this
    module does not depend on the ORM. `photo_keys` are store keys, primary first."""

    name: str
    price_label: str = ""
    photo_keys: tuple[str, ...] = ()
    video_keys: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


# -- build -----------------------------------------------------------------------------

#: Where a shortened text may end on a natural pause.
_PAUSES = ",.;:!?—"
#: A clause starts at these words: cutting just before one keeps a whole phrase
#: ("Escríbenos al DM | y te la armamos…").
_CLAUSE_STARTS = frozenset("y e o u que pero porque mientras".split())
#: The shortest phrase a cut may leave, so a long text does not shrink to two words.
_MIN_PHRASE = 12
#: Words a shortened Spanish text must not end on: "Escríbanos en el WhatsApp y se la".
_DANGLING = frozenset(
    "a al de del el la las lo los y e o u ni en con por para que se un una unos unas"
    " tu tus su sus mi mis te le les nos antes después hasta desde sin sobre entre hacia"
    " como cuando donde".split()
)


def _without_dangling(phrase: str) -> str:
    """`phrase` without trailing articles, prepositions or punctuation."""
    words = phrase.rstrip(" ,;:—-").split()
    while words and words[-1].lower().strip(_PAUSES) in _DANGLING:
        words.pop()
    return " ".join(words).rstrip(" ,;:—-")


def fit_text(text: str, limit: int | None) -> str:
    """`text` within `limit` characters, shortened where a person would stop — at the
    last pause (comma, colon, dash, end of sentence) or the last start of a clause («y»,
    «que»…) that fits, else at the last whole word, never on a dangling article or
    preposition. A render used to fail outright for a CTA 6 characters over its port
    (§ request 2026-10-08). With no place to cut (one long word) the text is returned
    as is, and `validate_props` still reports it."""
    text = " ".join(text.split())
    if limit is None or len(text) <= limit:
        return text
    cuts: list[str] = []
    for i, ch in enumerate(text[: limit + 1]):
        if ch in _PAUSES:
            cuts.append(text[: i + 1] if ch in ".!?" else text[:i])
        elif ch == " " and text[i + 1 :].split(" ", 1)[0].lower() in _CLAUSE_STARTS:
            cuts.append(text[:i])
    phrases = [_without_dangling(c) for c in cuts]
    phrases = [p for p in phrases if _MIN_PHRASE <= len(p) <= limit]
    if phrases:
        return phrases[-1]
    words: list[str] = []
    for word in text.split():
        if len(" ".join((*words, word))) > limit:
            break
        words.append(word)
    return _without_dangling(" ".join(words)) or text


def build_props(
    *,
    manifest: TemplateManifest,
    brief: ContentBrief,
    copy: CopyPayload,
    kit: BrandKit,
    brand_name: str,
    products: Sequence[ProductFacts],
    tenant_id: UUID,
    draft_id: UUID,
    locale: str | None = None,
    price_line: str | None = None,
    fonts: Mapping[str, str] | None = None,
    key_ref: Callable[[str], str] = lambda key: f"{KEY_SCHEME}{key}",
) -> RenderProps:
    """Assemble props for `manifest` from the Post. Photos: the brief's own product
    uploads first (what the operator chose for THIS piece), then the catalog products'
    photos, deduplicated, capped at the port's max. Texts come from the winning copy."""
    max_photos = manifest.required_photos()[1]
    photo_keys: list[str] = []
    for key in (*brief.media.product_keys, *(k for p in products for k in p.photo_keys)):
        if key not in photo_keys:
            photo_keys.append(key)
    if max_photos is not None:
        photo_keys = photo_keys[:max_photos]

    video_key = next((k for p in products for k in p.video_keys), None)
    if brief.source_media_key and "video" in manifest.inputs:
        video_key = brief.source_media_key

    texts: dict[str, str] = {
        "hook": copy.hook.strip(),
        "cta": copy.cta.strip(),
        "caption": copy.caption.strip(),
    }
    line = price_line if price_line is not None else _price_line(products)
    if line:
        texts["price_line"] = line
    # each text within its port: shortened where a person would stop, not a failed render
    for name, value in texts.items():
        port = manifest.inputs.get(name)
        if port is not None and port.type is PortType.STRING:
            texts[name] = fit_text(value, port.max)

    product_props = tuple(
        ProductProps(
            name=p.name,
            price=p.price_label,
            photo=key_ref(p.photo_keys[0]) if p.photo_keys else None,
        )
        for p in products
    )
    brand = BrandProps(
        name=brand_name,
        palette=tuple(kit.palette_rgb),
        fonts=dict(fonts or {}),
        logo=key_ref(kit.logo_asset_key) if kit.logo_asset_key else None,
        tone=_tone_word(kit),
    )
    return RenderProps(
        meta={
            "templateId": manifest.id,
            "version": manifest.version,
            "port": "",
            "tenantId": str(tenant_id),
            "draftId": str(draft_id),
            "locale": locale or kit.regional_variant,
            "angle": brief.content_type.value,
        },
        brand=brand,
        texts={k: v for k, v in texts.items() if v},
        photos=tuple(key_ref(k) for k in photo_keys),
        video=key_ref(video_key) if video_key else None,
        products=product_props,
    )


def _price_line(products: Sequence[ProductFacts]) -> str:
    labels = [p.price_label for p in products if p.price_label]
    return labels[0] if len(labels) == 1 else ""


def _tone_word(kit: BrandKit) -> str:
    """A few plain words a composition may print or use to pick an animation style.
    The axes are 0..100 sliders (`ToneAxes`); the right-hand pole wins above 65, the
    left-hand one below 35, the middle says nothing."""
    axes = kit.tone_axes
    poles = (
        (axes.formal_casual, "formal", "casual"),
        (axes.sober_enthusiastic, "sobrio", "entusiasta"),
        (axes.technical_plain, "técnico", "llano"),
        (axes.brief_elaborate, "breve", "elaborado"),
    )
    words = [right if v >= 65 else left for v, left, right in poles if v >= 65 or v <= 35]
    return ", ".join(words)


# -- validate --------------------------------------------------------------------------


def validate_props(manifest: TemplateManifest, props: RenderProps) -> list[PropsProblem]:
    """Every problem, not the first: the UI shows them together and the router uses the
    list to decide whether to offer the template at all."""
    problems: list[PropsProblem] = []
    for name, port in manifest.inputs.items():
        value = _port_value(props, name)
        problems.extend(_check_port(name, port, value))
    return problems


def _port_value(props: RenderProps, name: str) -> Any:
    if name == "photos":
        return list(props.photos)
    if name == "video":
        return props.video
    if name == "brand":
        return props.brand
    if name == "products":
        return list(props.products)
    return props.texts.get(name)


def _check_port(name: str, port: InputPort, value: Any) -> list[PropsProblem]:
    empty = value is None or value == "" or (isinstance(value, list) and not value)
    if empty:
        if port.optional:
            return []
        return [PropsProblem(name, "missing", f"'{name}' is required by the template")]
    if port.type is PortType.STRING:
        if not isinstance(value, str):
            return [PropsProblem(name, "wrong_type", f"'{name}' must be text")]
        out: list[PropsProblem] = []
        if port.max is not None and len(value) > port.max:
            out.append(
                PropsProblem(
                    name, "too_long", f"'{name}' has {len(value)} chars; the port allows {port.max}"
                )
            )
        if port.enum is not None and value not in port.enum:
            out.append(PropsProblem(name, "not_in_enum", f"'{name}' must be one of {port.enum}"))
        return out
    if port.is_list:
        if not isinstance(value, list):
            return [PropsProblem(name, "wrong_type", f"'{name}' must be a list")]
        out = []
        if port.min is not None and len(value) < port.min:
            out.append(
                PropsProblem(
                    name,
                    "too_few",
                    f"'{name}' has {len(value)} items; the template needs {port.min}",
                )
            )
        if port.max is not None and len(value) > port.max:
            out.append(
                PropsProblem(
                    name, "too_many", f"'{name}' has {len(value)} items; the port allows {port.max}"
                )
            )
        return out
    if port.type is PortType.IMAGE or port.type is PortType.VIDEO:
        if not isinstance(value, str):
            return [PropsProblem(name, "wrong_type", f"'{name}' must be a media reference")]
        return []
    if port.type is PortType.BRAND_KIT:
        return (
            []
            if isinstance(value, BrandProps)
            else [PropsProblem(name, "wrong_type", f"'{name}' must be the brand kit")]
        )
    if port.type is PortType.NUMBER:
        return (
            []
            if isinstance(value, int | float)
            else [PropsProblem(name, "wrong_type", f"'{name}' must be a number")]
        )
    if port.type is PortType.BOOLEAN:
        return (
            []
            if isinstance(value, bool)
            else [PropsProblem(name, "wrong_type", f"'{name}' must be true or false")]
        )
    return []

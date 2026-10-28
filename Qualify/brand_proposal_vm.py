"""Pure rules of the proposed Brand Kit's review on «Tu marca» (m-24852199, PB-5 of the
epic m-24852192, docs/epica-prellenado-brand-kit-alta.md §3 PB-5).

What is pending and what each run outcome shows are decided in the backend
(`qualify_api.creative.brand_prefill_review.review_of`); this module holds the screen's
side, without Reflex: the literal copy the founder approved on 2026-10-24 (do not
reword it) and the proposal flattened into what the review card shows."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from qualify_api.creative.brand_prefill_review import Notice
from qualify_api.privacy import mask_phones

# -- copy (literal, docs/epica-prellenado-brand-kit-alta.md §3 PB-5) -------------------

PROPOSAL_NOTICE = (
    "Preparamos una propuesta de tu identidad de marca a partir de tu cuenta de "
    "Instagram @{usuario}. Revísala y apruébala para empezar a crear publicaciones."
)
APPROVE_LABEL = "Aprobar"
CHANGE_LABEL = "Cambiar"
DISCARD_LABEL = "Empezar de cero"
APPROVED_NOTICE = "Listo. Guardamos tu identidad de marca."
UNREADABLE_NOTICE = (
    "No pudimos leer tu cuenta de Instagram. Completa tu identidad de marca en unos pasos."
)
PRIVATE_NOTICE = (
    "Tu cuenta de Instagram es privada, así que no pudimos leerla. Completa tu identidad "
    "de marca en unos pasos."
)

# -- copy of the review card (labels around the literal notice) --------------------------

REVIEW_TITLE = "Tu identidad de marca"
OBSERVED_TITLE = "Esto es lo que vimos en tu Instagram"
MEDIA_LABEL = "Tus últimas publicaciones"
MEDIA_SOURCE = "De tu perfil al preparar esta propuesta."
TOP_MEDIA_LABEL = "La que más gustó"
BIO_LABEL = "Así te presentas"
LINKS_LABEL = "Tus enlaces"
RUBRO_SOURCE = "Lo leímos en tu descripción y tus publicaciones."
PLACE_SOURCE = "Lo leímos en tu descripción."
LOGO_LABEL = "Tu logo: tu foto de perfil"
COLOURS_SOURCE = "Salen de tu foto de perfil."
OWNER_SOURCE = "Lo corregiste tú."
LOGO_UNSET_LABEL = "Tu logo: por elegir"
TOP_TAGS_LABEL = "De qué publicas"
TOP_TAGS_SOURCE = "Las etiquetas que más usas."
SUGGESTED_TAGS_LABEL = "Etiquetas que te sugerimos"
CORRECT_LABEL = "Corregir"
EDIT_TITLE = "Corrige este dato"
SAVE_LABEL = "Guardar"
CANCEL_LABEL = "Cancelar"
NO_POSTS_NOTICE = "Tu cuenta está empezando. Tus primeras publicaciones las armamos juntos."
PUBLIC_READ_NOTE = "Solo miramos lo que ya es público en tu perfil."
EDIT_INVALID = "Revisa el dato e inténtalo de nuevo."
RUBRO_LABEL = "A qué te dedicas"
PLACE_LABEL = "Dónde estás"
COLOURS_LABEL = "Tus colores"
TAGS_LABEL = "Etiquetas para tus publicaciones"
#: A button that could not save (the three of them).
DECISION_FAILED = "No pudimos guardar tu respuesta. Revisa tu conexión e inténtalo de nuevo."


def colours_label(count: int) -> str:
    """The colour group's accessible name: how many, never their codes."""
    return f"{COLOURS_LABEL}: {count} {'color' if count == 1 else 'colores'}"


def notice_text(notice: Notice | str, username: str, network: str = "instagram") -> str:
    """The notice for a review (`brand_prefill_review.Notice`); "" for none."""
    notice = Notice(notice) if notice in {n.value for n in Notice} else Notice.NONE
    label = {"instagram": "Instagram", "tiktok": "TikTok"}.get(network, "")
    if notice is Notice.PROPOSAL:
        text = PROPOSAL_NOTICE.replace(" de Instagram", f" de {label}" if label else "")
        return text.format(usuario=username.lstrip("@"))
    if notice is Notice.PRIVATE:
        return PRIVATE_NOTICE.replace(" de Instagram", f" de {label}" if label else "")
    if notice is Notice.UNREADABLE:
        return UNREADABLE_NOTICE.replace(" de Instagram", f" de {label}" if label else "")
    return ""


@dataclass(frozen=True)
class ProposalView:
    """The proposal as the review card shows it."""

    network: str = ""
    username: str = ""
    fullname: str = ""
    category: str = ""
    followers: str = ""
    pic: str = ""
    rubro: str = ""
    place: str = ""
    colours: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    posts: str = ""
    bio: str = ""
    links: list[dict[str, str]] = field(default_factory=list)
    media: list[dict[str, str]] = field(default_factory=list)
    top_tags: list[str] = field(default_factory=list)
    frequency: str = ""
    no_posts: bool = False
    observed: bool = False
    city: str = ""
    country_code: str = ""
    logo: bool = True
    place_source: str = ""
    colours_source: str = ""
    rubro_source: str = ""
    country_source: str = ""


def _text(value: Any) -> str:
    return mask_phones(str(value or ""))[:280]


def _positive(value: Any) -> str:
    try:
        number = int(value)
    except (ValueError, TypeError, OverflowError):
        return ""
    return f"{number:,}".replace(",", ".") if number > 0 else ""


def _links(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, Mapping):
            continue
        url = str(item.get("url") or "")
        masked = _text(url)
        if item.get("kind") == "whatsapp" or "wa.me/" in url.lower():
            number = re.search(r"(?:\+\d{1,3} )?••• ••• ••\d{2}", masked)
            if number:
                out.append({"title": "WhatsApp de tu perfil", "text": number.group(), "href": ""})
            continue
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if parsed.scheme != "https" or not parsed.netloc or parsed.username:
            continue
        # A phone must not survive in the browser's href even when its label is masked.
        if mask_phones(url) != url or "••" in url or re.search(r"\d{8,}", url):
            continue
        out.append({"title": _text(item.get("title")) or masked, "text": "", "href": url})
    return out[:12]


def _media(observed: Mapping[str, Any]) -> list[dict[str, str]]:
    if observed.get("posts_count") == 0:
        return []
    out: list[dict[str, str]] = []
    raw = observed.get("recent_media")
    top = observed.get("top_media_ids") or []
    recent = observed.get("posted_last_30d") is True
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, Mapping) or not item.get("thumb_r2_key"):
            continue
        likes = _positive(item.get("likes"))
        is_top = recent and item.get("is_owner") is True and item.get("id") in top
        out.append(
            {
                "key": str(item["thumb_r2_key"]),
                "content_type": str(item.get("thumb_content_type") or "image/jpeg"),
                "alt": _text(item.get("caption")) or "Publicación de tu cuenta",
                "top": TOP_MEDIA_LABEL if is_top else "",
                "source": f"{likes} me gusta. De tus últimas 12." if is_top and likes else "",
            }
        )
    return out[:6]


def _colours(palette: Any) -> list[str]:
    if not isinstance(palette, Mapping):
        return []
    raw = palette.get("logo_colors")
    if isinstance(raw, list) and raw:
        return [str(c).strip() for c in raw if str(c).strip()]
    return [c.strip() for c in str(palette.get("palette") or "").split(",") if c.strip()]


def proposal_view(
    proposal: Mapping[str, Any] | None,
    *,
    country_names: Mapping[str, str],
    sector_labels: Mapping[str, str] | None = None,
) -> ProposalView:
    """`{"connect", "profile", "palette"}` (a pending review's proposal) → the card. The
    rubro is the one Claude named, else the category's name; the place is «city,
    country» with whichever is known."""
    if not proposal:
        return ProposalView()
    connect = proposal.get("connect") or {}
    profile = proposal.get("profile") or {}
    observed = proposal.get("observed")
    observed = observed if isinstance(observed, Mapping) else {}
    corrected = proposal.get("corrected_fields") or []
    place_hint = observed.get("place_hint")
    place_hint = place_hint if isinstance(place_hint, Mapping) else {}
    place_source = PLACE_SOURCE if place_hint.get("source") == "bio" else ""
    if place_hint.get("source") == "tag":
        place_count = sum(
            1
            for post in observed.get("recent_media") or []
            if isinstance(post, Mapping)
            and post.get("is_owner") is True
            and str(post.get("place") or "").strip()
        )
        if place_count:
            place_source = f"Lo marcaste en {place_count} publicaciones."
    sector = str(connect.get("sector") or "")
    rubro = str(connect.get("rubro_text") or "").strip() or (sector_labels or {}).get(sector, "")
    country = country_names.get(str(connect.get("country_code") or ""), "")
    place = ", ".join(p for p in (str(connect.get("city") or "").strip(), country) if p)
    tags = [
        f"#{str(item.get('tag', '')).lstrip('#')}"
        for item in connect.get("hashtags") or []
        if isinstance(item, Mapping) and str(item.get("tag", "")).strip("# ")
    ]
    username = str(profile.get("username") or connect.get("username") or "").lstrip("@")
    return ProposalView(
        network=str(connect.get("network") or ""),
        username=username,
        fullname=_text(profile.get("fullname")),
        category=_text(observed.get("category_es")),
        followers=_positive(profile.get("followers_count")),
        pic=str(profile.get("pic") or ""),
        rubro=_text(rubro),
        place=_text(place),
        colours=_colours(proposal.get("palette")),
        tags=tags,
        posts=_positive(observed.get("posts_count")),
        bio=_text(profile.get("bio")),
        links=_links(observed.get("links")),
        media=_media(observed),
        top_tags=[
            _text(t).lstrip("#")
            for t in observed.get("top_hashtags") or []
            if isinstance(t, str) and t.strip("# ")
        ][:12],
        frequency=(
            f"Publicas unas {observed['posts_per_week']:g} veces por semana."
            if observed.get("posted_last_30d") is True
            and isinstance(observed.get("posts_per_week"), (int, float))
            and observed["posts_per_week"] > 0
            else ""
        ),
        no_posts=observed.get("posts_count") == 0,
        observed=bool(observed),
        city=_text(connect.get("city")),
        country_code=str(connect.get("country_code") or ""),
        logo=profile.get("use_profile_logo") is not False,
        place_source=OWNER_SOURCE if "city" in corrected else place_source,
        colours_source=(
            OWNER_SOURCE
            if (proposal.get("palette") or {}).get("logo_source") == "owner"
            else COLOURS_SOURCE
        ),
        rubro_source=OWNER_SOURCE if "rubro_text" in corrected else RUBRO_SOURCE,
        country_source=OWNER_SOURCE if "country_code" in corrected else "",
    )

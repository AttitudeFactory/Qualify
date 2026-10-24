"""Pure rules of the proposed Brand Kit's review on «Tu marca» (m-24852199, PB-5 of the
epic m-24852192, docs/epica-prellenado-brand-kit-alta.md §3 PB-5).

What is pending and what each run outcome shows are decided in the backend
(`qualify_api.creative.brand_prefill_review.review_of`); this module holds the screen's
side, without Reflex: the literal copy the founder approved on 2026-10-24 (do not
reword it) and the proposal flattened into what the review card shows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from qualify_api.creative.brand_prefill_review import Notice

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
RUBRO_LABEL = "A qué te dedicas"
PLACE_LABEL = "Dónde estás"
COLOURS_LABEL = "Tus colores"
TAGS_LABEL = "Etiquetas para tus publicaciones"
#: A button that could not save (the three of them).
DECISION_FAILED = "No pudimos guardar tu respuesta. Revisa tu conexión e inténtalo de nuevo."


def notice_text(notice: Notice | str, username: str) -> str:
    """The notice for a review (`brand_prefill_review.Notice`); "" for none."""
    notice = Notice(notice) if notice in {n.value for n in Notice} else Notice.NONE
    if notice is Notice.PROPOSAL:
        return PROPOSAL_NOTICE.format(usuario=username.lstrip("@"))
    if notice is Notice.PRIVATE:
        return PRIVATE_NOTICE
    if notice is Notice.UNREADABLE:
        return UNREADABLE_NOTICE
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
        network=str(connect.get("network") or "instagram"),
        username=username,
        fullname=str(profile.get("fullname") or ""),
        category=str(profile.get("category") or ""),
        followers=str(profile.get("followers") or ""),
        pic=str(profile.get("pic") or ""),
        rubro=rubro,
        place=place,
        colours=_colours(proposal.get("palette")),
        tags=tags,
    )

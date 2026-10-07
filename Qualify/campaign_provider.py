"""The POST's «Campaña» field (QUA-143) — blocking calls over
`qualify_api.creative.campaigns`, returned as plain view-models. Run them off the event
loop (`asyncio.to_thread`).

Setting, changing or clearing the campaign is not a content edit: the service writes
`content_drafts.campaign_id` alone, so the POST keeps its revision, status and approval
(and a scheduled POST keeps publishing)."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from qualify_api.creative import campaigns
from qualify_api.creative.campaigns import (
    CAMPAIGN_COLORS,
    InvalidCampaignColor,
    InvalidCampaignName,
    PostCampaignChoices,
    UnknownCampaign,
    UnknownPost,
)

#: The select's value for «Sin campaña» — Radix reserves the empty string.
NO_CAMPAIGN = "none"
#: The drawer select's value for «Nueva campaña» (name + colour typed in the piece).
NEW_CAMPAIGN = "new"

#: The four campaign colours (the closed list of `CAMPAIGN_COLORS`) with their words, in
#: the order the swatches show them.
COLOR_LABELS: dict[str, str] = {
    "violet": "Violeta",
    "pink": "Rosa",
    "blue": "Azul",
    "orange": "Naranja",
}
assert tuple(COLOR_LABELS) == CAMPAIGN_COLORS  # one list, never two that drift

POST_GONE = "Este POST ya no existe. Vuelve a la bandeja."
CAMPAIGN_GONE = "Esa campaña ya no está disponible. Elige otra."


@dataclass(frozen=True)
class CampaignOptionVM:
    id: str
    name: str
    color: str  # a palette key shared with the planner tags


@dataclass(frozen=True)
class CampaignFieldVM:
    current_id: str = NO_CAMPAIGN
    current_name: str = ""  # "" → an independent POST
    current_color: str = ""
    options: list[CampaignOptionVM] = field(default_factory=list)


def _field(choices: PostCampaignChoices) -> CampaignFieldVM:
    current = choices.current
    return CampaignFieldVM(
        current_id=str(current.id) if current is not None else NO_CAMPAIGN,
        current_name=current.name if current is not None else "",
        current_color=current.color if current is not None else "",
        options=[
            CampaignOptionVM(id=str(c.id), name=c.name, color=c.color) for c in choices.options
        ],
    )


def campaign_field(tenant_id: UUID, post_id: UUID) -> CampaignFieldVM:
    return _field(campaigns.choices_for_post(tenant_id, post_id))


def assign_campaign(tenant_id: UUID, post_id: UUID, value: str) -> CampaignFieldVM:
    """`value` is a campaign id, or `NO_CAMPAIGN` to make the POST independent again."""
    campaign_id = None if value in ("", NO_CAMPAIGN) else UUID(value)
    campaigns.set_post_campaign(tenant_id, post_id, campaign_id)
    return campaign_field(tenant_id, post_id)


def create_campaign_for_post(
    tenant_id: UUID, post_id: UUID, name: str, user_id: UUID | None, color: str | None = None
) -> CampaignFieldVM:
    campaigns.create_for_post(tenant_id, post_id, name, color=color or None, created_by=user_id)
    return campaign_field(tenant_id, post_id)


def recolor_post_campaign(tenant_id: UUID, post_id: UUID, color: str) -> CampaignFieldVM:
    """Recolour the POST's CURRENT campaign — every POST and event of that campaign shows
    it. `UnknownCampaign` when the POST has none (the control is not offered then)."""
    current = campaigns.choices_for_post(tenant_id, post_id).current
    if current is None:
        raise UnknownCampaign("the POST has no campaign")
    campaigns.set_campaign_color(tenant_id, current.id, color)
    return campaign_field(tenant_id, post_id)


def suggested_color(options: list[CampaignOptionVM]) -> str:
    return campaigns.suggested_color(len(options))


def brand_campaign_options(tenant_id: UUID, brand_id: UUID) -> list[CampaignOptionVM]:
    """The brand's campaigns as the drawer's selector offers them."""
    return [
        CampaignOptionVM(id=str(c.id), name=c.name, color=c.color)
        for c in campaigns.list_campaigns(tenant_id, brand_id)
    ]


def apply_post_choice(
    tenant_id: UUID,
    post_id: UUID,
    value: str,
    *,
    new_name: str = "",
    new_color: str = "",
    user_id: UUID | None = None,
) -> None:
    """The drawer's choice for one POST, applied AFTER its publications were created
    (QUA-143 AC 21): `NO_CAMPAIGN` clears it, `NEW_CAMPAIGN` creates the campaign in the
    POST's brand (or picks the one with that name) and assigns it, anything else is a
    campaign id. Same no-edit rule as everywhere: only `campaign_id` (and, for a new one,
    the `campaigns` row) is written."""
    if value == NEW_CAMPAIGN:
        campaigns.create_for_post(
            tenant_id, post_id, new_name, color=new_color or None, created_by=user_id
        )
        return
    campaigns.set_post_campaign(
        tenant_id, post_id, None if value in ("", NO_CAMPAIGN) else UUID(value)
    )


def error_message(exc: Exception) -> str:
    """The operator's words for a refusal; `InvalidCampaignName` already carries them."""
    if isinstance(exc, (InvalidCampaignName, InvalidCampaignColor)):
        return str(exc)
    if isinstance(exc, UnknownPost):
        return POST_GONE
    if isinstance(exc, (UnknownCampaign, ValueError)):
        return CAMPAIGN_GONE
    return "No se pudo guardar la campaña. Inténtalo de nuevo."


__all__ = [
    "COLOR_LABELS",
    "NEW_CAMPAIGN",
    "NO_CAMPAIGN",
    "CampaignFieldVM",
    "CampaignOptionVM",
    "InvalidCampaignColor",
    "InvalidCampaignName",
    "UnknownCampaign",
    "UnknownPost",
    "apply_post_choice",
    "assign_campaign",
    "brand_campaign_options",
    "campaign_field",
    "create_campaign_for_post",
    "error_message",
    "recolor_post_campaign",
    "suggested_color",
]

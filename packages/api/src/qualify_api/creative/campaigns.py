"""Campaigns (QUA-143): several POSTs of a brand grouped under one name and colour.

Herwin, after QUA-118: «Una campaña se conforma de varios posts y en el calendario quiero
diferenciar entre campañas y posts independientes.»

The campaign belongs to the POST (`content_drafts.campaign_id`, FK since 0045), never to a
calendar event: every event of a POST — each account, date, destination or weekly
occurrence — shows the campaign it reads through the POST (`PostSummary.campaign`).

**Setting or clearing a POST's campaign is not a content edit.** It writes that one
column and nothing else: no `revision` bump, no status change, no approval touched.
Bumping `revision` would turn an approved, scheduled POST into «Pendiente» and keep it
from publishing — the same reason planner tags never bump `calendar_events.revision`.

V1 scope: create (from the POST's detail, with a colour), list, assign, clear, and
recolour. No rename or delete — the app role's only UPDATE is the column grant on
`campaigns.color` (0045) — and no dates, budget or status.

**Colour is a closed list of four** (`CAMPAIGN_COLORS`): keys of the planner-tag palette
that carry no state meaning on the calendar. teal (approved/scheduled edge), green
(published), amber (pending/expired) and gray (cancelled) are refused here and by 0045's
`ck_campaign_color`. Recolouring touches `campaigns` only, so every POST and event of the
campaign shows the new colour on its next read and none of them is edited.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from qualify_api.creative.models import Campaign, ContentDraft

#: The colours a campaign may use — mirrors 0045's `ck_campaign_color`. A subset of the
#: planner-tag palette (0025): never teal, green, amber or gray, which mean a state.
CAMPAIGN_COLORS: tuple[str, ...] = ("violet", "pink", "blue", "orange")
NAME_MAX = 60  # 0045's `ck_campaign_name`


class UnknownPost(Exception):
    """The POST does not exist or is another tenant's (RLS: the same answer)."""


class UnknownCampaign(Exception):
    """The campaign does not exist, is another tenant's, or belongs to another brand
    than the POST — the database refuses all three (composite FK), this says so first."""


class InvalidCampaignName(ValueError):
    """Empty after trimming, or longer than `NAME_MAX`."""


class InvalidCampaignColor(ValueError):
    """Not one of `CAMPAIGN_COLORS` — a state colour included."""


@dataclass(frozen=True)
class CampaignView:
    id: UUID
    name: str
    color: str


def clean_name(name: str) -> str:
    """Inner whitespace collapsed, ends trimmed: "  Lanzamiento   Polette " and
    "Lanzamiento Polette" are one campaign (uniqueness also ignores case)."""
    clean = " ".join(name.split())
    if not clean:
        raise InvalidCampaignName("El nombre de la campaña no puede estar vacío.")
    if len(clean) > NAME_MAX:
        raise InvalidCampaignName(f"El nombre admite hasta {NAME_MAX} caracteres.")
    return clean


def check_color(color: str) -> str:
    if color not in CAMPAIGN_COLORS:
        raise InvalidCampaignColor("Elige uno de los colores de campaña disponibles.")
    return color


def suggested_color(existing: int) -> str:
    """The colour «Nueva campaña» preselects: the next one in the list, by how many
    campaigns the brand already has."""
    return CAMPAIGN_COLORS[existing % len(CAMPAIGN_COLORS)]


def _view(campaign: Campaign) -> CampaignView:
    return CampaignView(id=campaign.id, name=campaign.name, color=campaign.color)


def list_campaigns(tenant_id: UUID, brand_id: UUID) -> list[CampaignView]:
    """The brand's campaigns, by name — what the POST's «Campaña» field offers."""
    with tenant_session(tenant_id) as session:
        rows = session.scalars(
            select(Campaign)
            .where(Campaign.brand_id == brand_id)
            .order_by(func.lower(Campaign.name))
        ).all()
        return [_view(row) for row in rows]


def create_campaign(
    tenant_id: UUID,
    brand_id: UUID,
    name: str,
    *,
    color: str | None = None,
    created_by: UUID | None = None,
) -> CampaignView:
    """Create a campaign of the brand in `color` (one of `CAMPAIGN_COLORS`; None → the
    suggested one) — or return the existing one with that name (case ignored), so typing a
    name that already exists picks it, keeping ITS colour, instead of failing."""
    clean = clean_name(name)
    if color is not None:
        check_color(color)
    with tenant_session(tenant_id) as session:
        existing = session.scalar(
            select(Campaign).where(
                Campaign.brand_id == brand_id, func.lower(Campaign.name) == clean.lower()
            )
        )
        if existing is not None:
            return _view(existing)
        count = session.scalar(
            select(func.count()).select_from(Campaign).where(Campaign.brand_id == brand_id)
        )
        color = color or suggested_color(int(count or 0))
        new_id = session.scalar(
            insert(Campaign)
            .values(
                tenant_id=tenant_id,
                brand_id=brand_id,
                name=clean,
                color=color,
                created_by=created_by,
            )
            # A concurrent create of the same name: the unique index wins, we re-read.
            .on_conflict_do_nothing()
            .returning(Campaign.id)
        )
        if new_id is None:
            winner = session.scalar(
                select(Campaign).where(
                    Campaign.brand_id == brand_id, func.lower(Campaign.name) == clean.lower()
                )
            )
            if winner is None:  # pragma: no cover — the conflict was on this very name
                raise UnknownCampaign(clean)
            return _view(winner)
        return CampaignView(id=new_id, name=clean, color=color)


def set_campaign_color(tenant_id: UUID, campaign_id: UUID, color: str) -> CampaignView:
    """Recolour a campaign. Writes `campaigns.color` alone — the only column the app role
    may UPDATE — so no POST and no event is edited: they all read the new colour."""
    check_color(color)
    with tenant_session(tenant_id) as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise UnknownCampaign(str(campaign_id))
        session.execute(
            update(Campaign)
            .where(Campaign.id == campaign_id)
            .values(color=color)
            .execution_options(synchronize_session=False)
        )
        return CampaignView(id=campaign.id, name=campaign.name, color=color)


def campaign_of(tenant_id: UUID, post_id: UUID) -> CampaignView | None:
    """The POST's campaign, or None when it has none. `UnknownPost` when it is not
    readable."""
    with tenant_session(tenant_id) as session:
        draft = session.get(ContentDraft, post_id)
        if draft is None:
            raise UnknownPost(str(post_id))
        if draft.campaign_id is None:
            return None
        campaign = session.get(Campaign, draft.campaign_id)
        return _view(campaign) if campaign is not None else None


def set_post_campaign(tenant_id: UUID, post_id: UUID, campaign_id: UUID | None) -> None:
    """Put the POST in `campaign_id`, or take it out of any with None.

    Writes `content_drafts.campaign_id` alone — a single-column UPDATE, never the ORM
    object — so `revision`, `approved_revision`, `status`, the approval and
    `updated_at` stay exactly as they were (QUA-143 AC 4)."""
    with tenant_session(tenant_id) as session:
        draft = session.get(ContentDraft, post_id)
        if draft is None:
            raise UnknownPost(str(post_id))
        if campaign_id is not None:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None or campaign.brand_id != draft.brand_id:
                raise UnknownCampaign(str(campaign_id))
        session.execute(
            update(ContentDraft)
            .where(ContentDraft.id == post_id)
            .values(campaign_id=campaign_id)
            .execution_options(synchronize_session=False)
        )


@dataclass(frozen=True)
class PostCampaignChoices:
    """What the POST's «Campaña» field shows: its campaign (None when independent) and
    the campaigns of ITS brand — never the session's default brand."""

    current: CampaignView | None
    options: list[CampaignView]


def choices_for_post(tenant_id: UUID, post_id: UUID) -> PostCampaignChoices:
    with tenant_session(tenant_id) as session:
        draft = session.get(ContentDraft, post_id)
        if draft is None:
            raise UnknownPost(str(post_id))
        brand_id, current_id = draft.brand_id, draft.campaign_id
    options = list_campaigns(tenant_id, brand_id)
    current = next((c for c in options if c.id == current_id), None)
    return PostCampaignChoices(current=current, options=options)


def create_for_post(
    tenant_id: UUID,
    post_id: UUID,
    name: str,
    *,
    color: str | None = None,
    created_by: UUID | None = None,
) -> CampaignView:
    """«Nueva campaña» from the POST's detail: create it in the POST's brand (or pick the
    existing one with that name) and put the POST in it. Same no-edit rule as
    `set_post_campaign`."""
    clean = clean_name(name)  # refuse an empty name or a bad colour before touching anything
    if color is not None:
        check_color(color)
    with tenant_session(tenant_id) as session:
        draft = session.get(ContentDraft, post_id)
        if draft is None:
            raise UnknownPost(str(post_id))
        brand_id = draft.brand_id
    campaign = create_campaign(tenant_id, brand_id, clean, color=color, created_by=created_by)
    set_post_campaign(tenant_id, post_id, campaign.id)
    return campaign


__all__ = [
    "CAMPAIGN_COLORS",
    "NAME_MAX",
    "CampaignView",
    "PostCampaignChoices",
    "InvalidCampaignColor",
    "InvalidCampaignName",
    "UnknownCampaign",
    "UnknownPost",
    "campaign_of",
    "check_color",
    "choices_for_post",
    "clean_name",
    "create_campaign",
    "create_for_post",
    "list_campaigns",
    "set_campaign_color",
    "set_post_campaign",
    "suggested_color",
]

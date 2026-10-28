"""The proposed Brand Kit on «Tu marca» — review it and approve it, change it or start
from scratch (m-24852199, PB-5 of the epic m-24852192,
docs/epica-prellenado-brand-kit-alta.md §3 PB-5; design approved 2026-10-24).

An Alta of Meegle may leave a proposal under `brand_kit_details.connect.prefill`
(`qualify_api.creative.brand_prefill`, PB-3/PB-4). `BrandMinimalState.enter` reads it
(`brand_prefill_review.review_of`) and hands it here (`BrandProposalState.show`):

- pending → the review card replaces the five steps: the notice, what was read
  (account, rubro, place, colours, tags) and «Aprobar» · «Cambiar» · «Empezar de cero»;
- the account could not be read, or is private → a notice above Tus redes, the steps
  as for any new brand.

The three decisions are the backend's (`approve_prefill` / `change_prefill` /
`discard_prefill`, one locked transaction each); this state only calls them off the
event loop and then puts the proposal into the wizard's own states, so the steps open
with it: «Aprobar» resumes on the first step that still misses data, «Cambiar» opens
Tus redes with every step prefilled, «Empezar de cero» opens Tus redes empty.

While the card is shown no step is mounted, so the wizard's save-as-you-go
(`_progress_trigger`) writes nothing until the owner has decided."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any
from uuid import UUID

import reflex as rx
from qualify_api.creative import brand_prefill_review, kept_pictures
from qualify_api.creative.brand_prefill_review import Notice, PrefillDecision, PrefillReview
from qualify_api.privacy import mask_phones_in

from . import brand_documents, creator_discovery
from . import brand_proposal_vm as vm
from .creative_state import CreativeState
from .creative_wizard_pages import (
    _AVATAR_BASE,
    _CONTROL_RADIUS,
    COUNTRY_OPTIONS,
    HAS_LOGO_PROFILE,
    LOGO_SOURCE_PROFILE,
    BrandConnectState,
    BrandWizardState,
)
from .r2_media import issue_view_path
from .ui import callout, card, drawer, media_thumb, tag
from .ui import tokens as T

logger = logging.getLogger(__name__)

_COUNTRY_NAMES: dict[str, str] = dict(COUNTRY_OPTIONS)
_SECTOR_LABELS: dict[str, str] = dict(creator_discovery.NICHE_LABELS)

#: Which button is saving ("" none): its spinner, and the other two off meanwhile.
_APPROVE, _CHANGE, _DISCARD = "approve", "change", "discard"


class BrandProposalState(rx.State):
    """The review's notice and the proposal as the card shows it. The proposal itself
    (to put into the wizard) stays backend-only."""

    #: `brand_prefill_review.Notice` value: "", "proposal", "private", "unreadable".
    notice: str = ""
    username: str = ""
    network: str = ""
    fullname: str = ""
    category: str = ""
    followers: str = ""
    pic: str = ""
    #: m-24852537: the `/r2media` view of the profile picture the Alta kept in R2 ("" when
    #: none was kept) — shown first; the CDN link expires in days.
    pic_view: str = ""
    rubro: str = ""
    place: str = ""
    colours: list[str] = []
    tags: list[str] = []
    posts: str = ""
    bio: str = ""
    links: list[dict[str, str]] = []
    media: list[dict[str, str]] = []
    top_tags: list[str] = []
    frequency: str = ""
    no_posts: bool = False
    has_observed: bool = False
    city: str = ""
    country_code: str = ""
    logo: bool = True
    place_source: str = ""
    colours_source: str = ""
    rubro_source: str = ""
    country_source: str = ""
    edit_open: bool = False
    edit_field: str = ""
    edit_label: str = ""
    edit_value: str = ""
    edit_logo: bool = True
    edit_error: str = ""
    #: «Listo. Guardamos tu identidad de marca.» stands until the owner moves on.
    approved: bool = False
    #: The step the approval opened (`BrandMinimalState.enter`): the notice shows there.
    approved_step: str = ""
    busy: str = ""
    _proposal: dict[str, Any] = {}
    _owner: tuple[UUID, UUID] | None = None

    @rx.var
    def review_title(self) -> str:
        label = {"instagram": "Instagram", "tiktok": "TikTok"}.get(self.network)
        return (
            vm.OBSERVED_TITLE.replace("Instagram", label)
            if label and self.has_observed
            else vm.REVIEW_TITLE
        )

    @rx.var
    def country_label(self) -> str:
        return _COUNTRY_NAMES.get(self.country_code, "")

    @rx.var
    def logo_label(self) -> str:
        return vm.LOGO_LABEL if self.logo else vm.LOGO_UNSET_LABEL

    @rx.event
    def set_edit_value(self, value: str) -> None:
        if not self.busy:
            self.edit_value = value

    @rx.event
    def set_edit_logo(self, value: bool) -> None:
        if not self.busy:
            self.edit_logo = value

    @rx.var
    def pending(self) -> bool:
        return self.notice == Notice.PROPOSAL.value

    @rx.var
    def notice_message(self) -> str:
        return vm.notice_text(self.notice, self.username, self.network)

    @rx.var
    def colours_label(self) -> str:
        """The colour group's accessible name («Tus colores: 3 colores»)."""
        return vm.colours_label(len(self.colours))

    @rx.var
    def avatar_src(self) -> str:
        """The account's picture: the copy kept in R2 (m-24852537), else — a proposal
        written before the copy existed — through the backend proxy, like the read
        profile's."""
        if self.pic_view:
            return self.pic_view
        return creator_discovery.avatar_path(
            {"network": self.network, "handle": self.username, "avatar": self.pic}
        )

    def show(self, review: PrefillReview, *, owner: tuple[UUID, UUID] | None = None) -> None:
        """What `BrandMinimalState.enter` read (caller holds the lock)."""
        view = vm.proposal_view(
            review.proposal if review.pending else None,
            country_names=_COUNTRY_NAMES,
            sector_labels=_SECTOR_LABELS,
        )
        self.notice = review.notice.value
        self.username = review.username
        self.network = view.network or review.network
        self.fullname = view.fullname
        self.category = view.category
        self.followers = view.followers
        self.pic = view.pic
        self.pic_view = _picture_view(review.proposal if review.pending else None)
        self.rubro = view.rubro
        self.place = view.place
        self.colours = view.colours
        self.tags = view.tags
        self.posts = view.posts
        self.bio = view.bio
        self.links = view.links
        self.media = _media_views(view.media, owner)
        self.top_tags = view.top_tags
        self.frequency = view.frequency
        self.no_posts = view.no_posts
        self.has_observed = view.observed
        self.city = view.city
        self.country_code = view.country_code
        self.logo = view.logo
        self.place_source = view.place_source
        self.colours_source = view.colours_source
        self.rubro_source = view.rubro_source
        self.country_source = view.country_source
        self._owner = owner
        self.edit_open = False
        self.edit_error = ""
        self._proposal = dict(review.proposal) if review.pending else {}
        self.busy = ""
        if review.pending:
            self.approved = False
            self.approved_step = ""

    @rx.event
    def open_correction(self, field: str) -> None:
        if self.busy or not self.pending:
            return
        values = {
            "rubro_text": (vm.RUBRO_LABEL, self.rubro),
            "city": ("Ciudad", self.city),
            "country_code": ("País", self.country_code),
            "logo": (vm.LOGO_LABEL, ""),
            "colors": (vm.COLOURS_LABEL, ", ".join(self.colours)),
        }
        if field not in values:
            return
        self.edit_field = field
        self.edit_label, self.edit_value = values[field]
        self.edit_logo = self.logo
        self.edit_error = ""
        self.edit_open = True

    @rx.event
    def close_correction(self, opened: bool = False) -> None:
        if not self.busy:
            self.edit_open = opened
            if not opened:
                self.edit_error = ""

    @rx.event(background=True)
    async def save_correction(self) -> AsyncIterator[rx.event.EventSpec | None]:
        from .brand_finish import session_ids

        async with self:
            if self.busy or not self.edit_open or not self.pending:
                return
            self.busy = "edit"
            field, value = self.edit_field, self.edit_value.strip()
            if field == "logo":
                value = self.edit_logo
            elif field == "colors":
                value = [part.strip() for part in value.split(",") if part.strip()]
        ids = await session_ids(self)
        decision = None
        if ids is not None:
            try:
                decision = await asyncio.to_thread(
                    brand_prefill_review.edit_prefill_field,
                    *ids[:2],
                    field,
                    value,
                    user_id=ids[2],
                )
            except ValueError:
                async with self:
                    self.busy = ""
                    self.edit_error = vm.EDIT_INVALID
                yield None
                return
            except Exception as exc:  # noqa: BLE001 — keep the drawer for retry
                logger.warning("brand proposal correction failed: %s", type(exc).__name__)
        if decision is None:
            async with self:
                self.busy = ""
                self.edit_error = vm.DECISION_FAILED
            yield None
            return
        if not decision.done:
            for event in await self._reload():
                yield event
            return
        async with self:
            self.show(
                PrefillReview(
                    notice=Notice.PROPOSAL, username=self.username, proposal=decision.proposal
                ),
                owner=self._owner,
            )
        yield None

    # -- the three buttons ----------------------------------------------------------------

    @rx.event(background=True)
    async def approve(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """«Aprobar»: the proposal becomes the Brand Kit's own answers, then the steps
        resume on the first one that still misses data."""
        if not await self._claim(_APPROVE):
            return
        decision = await self._run(_APPROVE, brand_prefill_review.approve_prefill)
        if decision is None:
            yield brand_documents.notify(vm.DECISION_FAILED, "error")
            return
        if not decision.done:
            for event in await self._reload():
                yield event
            return
        from .brand_minimal import BrandMinimalState

        async with self:
            await _into_wizard(self, decision.proposal)
            self.approved = True
            self._clear()
        yield BrandMinimalState.enter

    @rx.event(background=True)
    async def change(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """«Cambiar»: the steps from Tus redes, each one prefilled with the proposal."""
        if not await self._claim(_CHANGE):
            return
        decision = await self._run(_CHANGE, brand_prefill_review.change_prefill)
        if decision is None:
            yield brand_documents.notify(vm.DECISION_FAILED, "error")
            return
        if not decision.done:
            for event in await self._reload():
                yield event
            return
        await self._open_steps(decision.proposal)
        yield None

    @rx.event(background=True)
    async def discard(self) -> AsyncIterator[rx.event.EventSpec | None]:
        """«Empezar de cero»: the steps from Tus redes, empty."""
        if not await self._claim(_DISCARD):
            return
        decision = await self._run(_DISCARD, brand_prefill_review.discard_prefill)
        if decision is None:
            yield brand_documents.notify(vm.DECISION_FAILED, "error")
            return
        if not decision.done:
            for event in await self._reload():
                yield event
            return
        await self._open_steps(None)
        yield None

    async def _claim(self, button: str) -> bool:
        """One decision at a time: a second tap while one saves does nothing."""
        async with self:
            if self.busy or self.notice != Notice.PROPOSAL.value:
                return False
            self.busy = button
            return True

    async def _run(
        self, button: str, action: Callable[..., PrefillDecision]
    ) -> PrefillDecision | None:
        """One backend decision off the event loop; None when it could not be saved (the
        card stays, with a toast)."""
        from .brand_finish import session_ids

        ids = await session_ids(self)
        decision: PrefillDecision | None = None
        if ids is not None:
            try:
                decision = await asyncio.to_thread(action, *ids)
            except Exception as exc:  # noqa: BLE001 — a toast, never a crash
                logger.warning("brand proposal %s failed: %s", button, type(exc).__name__)
        if decision is None:
            async with self:
                self.busy = ""
        return decision

    async def _open_steps(self, proposal: Mapping[str, Any] | None) -> None:
        from . import brand_minimal_vm
        from .brand_minimal import BrandMinimalState

        async with self:
            if proposal:
                await _into_wizard(self, proposal)
            self._clear()
            minimal = await self.get_state(BrandMinimalState)
            minimal.step = brand_minimal_vm.FIRST_STEP
            minimal.entered = True

    async def _reload(self) -> list[Any]:
        """The proposal was decided elsewhere (another tab or device) or the owner's own
        answers came first (`superseded`): this tab's wizard states are older than the
        database. They are dropped — so the save-as-you-go, which waits for the loads
        (`brand_finish.save_progress`), cannot write them over what is stored — and
        /brand's own loads read everything again; the page shows its loading card until
        `enter` is done, so no step is mounted on the old data."""
        from .brand_minimal import BrandMinimalState

        async with self:
            self._clear()
            for cls in (CreativeState, BrandWizardState, BrandConnectState):
                (await self.get_state(cls)).reset()
            minimal = await self.get_state(BrandMinimalState)
            minimal.entered = False
        return [
            CreativeState.load_brand,
            CreativeState.load_voice,
            BrandWizardState.load_saved_assets,
            BrandConnectState.load_saved_details,
            BrandMinimalState.enter,
        ]

    def _clear(self) -> None:
        self.notice = ""
        self.busy = ""
        self._proposal = {}
        self.edit_open = False
        self.media = []
        self.links = []
        self._owner = None


def _media_views(
    media: list[dict[str, str]], owner: tuple[UUID, UUID] | None
) -> list[dict[str, str]]:
    if owner is None:
        return []
    out = []
    for item in media:
        if not kept_pictures.is_kept_key(*owner, item["key"]):
            continue
        try:
            path = issue_view_path(owner[0], item["key"], "image", item["content_type"])
        except Exception as exc:  # noqa: BLE001 — unavailable thumbnail is hidden
            logger.warning("brand proposal: thumbnail view not issued: %s", type(exc).__name__)
            continue
        out.append(
            {
                "src": path,
                "alt": item["alt"],
                "top": item["top"],
                "source": item["source"],
            }
        )
    return out


def _picture_view(proposal: Mapping[str, Any] | None) -> str:
    """`/r2media/<token>` of the proposal's kept profile picture, or "" (none kept, or
    the token store is down — the card then shows its icon, never an error)."""
    found = brand_prefill_review.picture_key(proposal)
    if found is None:
        return ""
    tenant_id, key, content_type = found
    try:
        return issue_view_path(tenant_id, key, "image", content_type)
    except Exception as exc:  # noqa: BLE001 - cosmetic: Redis down must not break the card
        logger.warning("brand proposal: picture view not issued: %s", type(exc).__name__)
        return ""


async def _into_wizard(state: rx.State, proposal: Mapping[str, Any]) -> None:
    """Put the proposal into the wizard's own states (caller holds the lock) — the same
    fields `BrandConnectState.load_saved_details` fills from a saved draft, the colours
    as «Usar mi foto de perfil» leaves them (`BrandWizardState.apply_logo_colours`)."""
    # Older stored proposals may predate server-side masking. Wizard vars reach the
    # browser too, so sanitize again before hydrating any of its public state.
    proposal = mask_phones_in(dict(proposal))
    connect_doc: Mapping[str, Any] = proposal.get("connect") or {}
    profile: Mapping[str, Any] = proposal.get("profile") or {}
    connect = await state.get_state(BrandConnectState)
    connect.network = str(connect_doc.get("network", ""))
    connect.username = str(connect_doc.get("username", ""))
    connect.sector = str(connect_doc.get("sector", ""))
    connect.rubro_text = str(connect_doc.get("rubro_text", ""))
    connect.hashtags_rubro = connect.rubro_text.strip()
    connect.country_code = str(connect_doc.get("country_code", ""))
    connect.city = str(connect_doc.get("city", ""))
    connect.rubro_hashtags = [
        {str(k): str(v) for k, v in item.items()}
        for item in connect_doc.get("hashtags", [])
        if isinstance(item, Mapping)
    ]
    connect.profile_username = str(profile.get("username", ""))
    connect.profile_fullname = str(profile.get("fullname", ""))
    connect.profile_bio = str(profile.get("bio", ""))
    connect.profile_category = str(profile.get("category", ""))
    connect.profile_followers = str(profile.get("followers", ""))
    connect.profile_followers_count = int(profile.get("followers_count", 0) or 0)
    use_profile_logo = profile.get("use_profile_logo") is not False
    connect.profile_pic = str(profile.get("pic", "")) if use_profile_logo else ""
    # m-24852537: the kept copy, already checked and viewed for the card
    connect.forget_kept_picture()
    found = brand_prefill_review.picture_key(proposal) if use_profile_logo else None
    if found is not None:
        _tenant, connect.profile_pic_key, connect.profile_pic_content_type = found
        connect.profile_pic_view = str(getattr(state, "pic_view", "") or "")
    metrics = [m for m in profile.get("metrics", []) if isinstance(m, Mapping)]
    try:
        connect._set_metrics([dict(m) for m in metrics])
        connect.metric_values = list(connect.metric_targets)
    except (KeyError, TypeError, ValueError):
        connect._set_metrics([])
    connect.error = ""
    wizard = await state.get_state(BrandWizardState)
    has_picture = bool(found or connect.profile_pic)
    connect.logo_from_profile = use_profile_logo and has_picture
    connect.profile_pic_is_real = use_profile_logo and has_picture
    wizard.has_logo = HAS_LOGO_PROFILE if connect.logo_from_profile else ""
    wizard.logo_colors = []
    wizard.logo_source = ""
    colours = brand_prefill_review.palette_colours(proposal)
    if colours:
        creative = await state.get_state(CreativeState)
        creative.kit_palette = ",".join(
            brand_prefill_review.merged_palette(
                [c for c in creative.kit_palette.split(",") if c.strip()], colours
            )
        )
        if (
            connect.logo_from_profile
            and (proposal.get("palette") or {}).get("logo_source") != "owner"
        ):
            wizard.logo_colors = colours
            wizard.logo_source = LOGO_SOURCE_PROFILE


# ---------------------------------------------------------------------------------------
# The views


def _field(
    label: str, value: rx.Var[str], *, field: str = "", source: str | rx.Var[str] = ""
) -> rx.Component:
    """One thing that was read, label above value (a phone's width: no side-by-side)."""
    return rx.cond(
        value != "",
        rx.vstack(
            rx.hstack(
                rx.text(label, size="2", color=T.TEXT_MUTED),
                rx.spacer(),
                *([_correct(field, label)] if field else []),
                width="100%",
                align="center",
            ),
            rx.text(value, size="3", weight="medium"),
            rx.cond(source != "", rx.text(source, size="1", color=T.TEXT_MUTED)),
            spacing="1",
            width="100%",
            align_items="start",
        ),
    )


def _correct(field: str, label: str) -> rx.Component:
    return rx.button(
        vm.CORRECT_LABEL,
        variant="ghost",
        size="2",
        min_height="44px",
        flex_shrink="0",
        aria_label=f"Corregir: {label}",
        disabled=BrandProposalState.busy != "",
        on_click=BrandProposalState.open_correction(field),
    )


def _colour_dot(colour: rx.Var[str]) -> rx.Component:
    """Decorative: the group says how many colours there are, not their codes."""
    return rx.box(
        width="2.25rem",
        height="2.25rem",
        border_radius="9999px",
        background=colour,
        border=T.BORDER,
        aria_hidden="true",
    )


def _colours() -> rx.Component:
    return rx.cond(
        BrandProposalState.colours.length() > 0,
        rx.vstack(
            rx.hstack(
                rx.text(vm.COLOURS_LABEL, size="2", color=T.TEXT_MUTED),
                rx.spacer(),
                _correct("colors", vm.COLOURS_LABEL),
                width="100%",
                align="center",
            ),
            rx.hstack(
                rx.foreach(BrandProposalState.colours, _colour_dot),
                spacing="2",
                flex_wrap="wrap",
                role="group",
                aria_label=BrandProposalState.colours_label,
            ),
            rx.cond(
                BrandProposalState.colours_source != "",
                rx.text(BrandProposalState.colours_source, size="1", color=T.TEXT_MUTED),
            ),
            spacing="1",
            width="100%",
            align_items="start",
        ),
    )


def _tags() -> rx.Component:
    return rx.cond(
        BrandProposalState.tags.length() > 0,
        rx.vstack(
            rx.text(vm.SUGGESTED_TAGS_LABEL, size="2", color=T.TEXT_MUTED),
            rx.hstack(
                rx.foreach(BrandProposalState.tags, lambda t: tag(t, size="2")),
                spacing="2",
                flex_wrap="wrap",
            ),
            spacing="1",
            width="100%",
            align_items="start",
        ),
    )


def _account() -> rx.Component:
    return rx.hstack(
        media_thumb(
            _AVATAR_BASE + BrandProposalState.avatar_src,
            has=(BrandProposalState.pic_view != "")
            | ((BrandProposalState.pic != "") & (BrandProposalState.avatar_src != "")),
            size="3.5rem",
            round=True,
            icon="user",
            icon_size=22,
            custom_attrs={"referrerpolicy": "no-referrer", "draggable": "false"},
        ),
        rx.vstack(
            # §8: h2 under the page's one h1 (`page_header`)
            rx.heading(
                "@", BrandProposalState.username, size="4", as_="h2", overflow_wrap="anywhere"
            ),
            rx.cond(
                BrandProposalState.fullname != "",
                rx.text(BrandProposalState.fullname, size="2", color=T.TEXT_MUTED),
            ),
            rx.cond(
                BrandProposalState.followers != "",
                rx.text(BrandProposalState.followers, " seguidores", size="2"),
            ),
            rx.cond(
                BrandProposalState.posts != "",
                rx.text(BrandProposalState.posts, " publicaciones", size="2"),
            ),
            rx.cond(
                BrandProposalState.category != "",
                rx.text(BrandProposalState.category, size="2", color=T.TEXT_MUTED),
            ),
            spacing="0",
            align_items="start",
            min_width="0",
        ),
        spacing="3",
        align="center",
        width="100%",
    )


def _media_item(item: rx.Var[dict[str, str]]) -> rx.Component:
    return rx.vstack(
        media_thumb(
            _AVATAR_BASE + item["src"],
            width="100%",
            height="auto",
            size=None,
            alt=item["alt"],
            aspect_ratio="1",
            loading="lazy",
        ),
        rx.cond(item["top"] != "", tag(item["top"], size="1")),
        rx.cond(item["source"] != "", rx.text(item["source"], size="1", color=T.TEXT_MUTED)),
        width="100%",
        min_width="0",
        spacing="1",
        align_items="start",
    )


def _observations() -> rx.Component:
    return rx.vstack(
        rx.cond(
            BrandProposalState.media.length() > 0,
            rx.vstack(
                rx.text(vm.MEDIA_LABEL, size="3", weight="medium"),
                rx.text(vm.MEDIA_SOURCE, size="1", color=T.TEXT_MUTED),
                rx.grid(
                    rx.foreach(BrandProposalState.media, _media_item),
                    columns=rx.breakpoints(initial="2", sm="3"),
                    spacing="2",
                    width="100%",
                ),
                width="100%",
                spacing="2",
                align_items="start",
            ),
        ),
        rx.cond(BrandProposalState.no_posts, callout(vm.NO_POSTS_NOTICE, "info")),
        _field(vm.BIO_LABEL, BrandProposalState.bio),
        rx.cond(
            BrandProposalState.links.length() > 0,
            rx.vstack(
                rx.text(vm.LINKS_LABEL, size="2", color=T.TEXT_MUTED),
                rx.foreach(
                    BrandProposalState.links,
                    lambda item: rx.vstack(
                        rx.cond(
                            item["href"] != "",
                            rx.link(
                                item["title"],
                                href=item["href"],
                                is_external=True,
                                overflow_wrap="anywhere",
                            ),
                            rx.text(item["title"], size="2"),
                        ),
                        rx.cond(item["text"] != "", rx.text(item["text"], size="2")),
                        align_items="start",
                        spacing="1",
                        width="100%",
                    ),
                ),
                align_items="start",
                spacing="2",
                width="100%",
            ),
        ),
        width="100%",
        spacing="4",
        align_items="start",
    )


def _top_tags() -> rx.Component:
    return rx.vstack(
        rx.cond(
            BrandProposalState.top_tags.length() > 0,
            rx.vstack(
                rx.text(vm.TOP_TAGS_LABEL, size="2", color=T.TEXT_MUTED),
                rx.hstack(
                    rx.foreach(BrandProposalState.top_tags, lambda t: tag("#" + t)),
                    flex_wrap="wrap",
                    spacing="2",
                ),
                rx.text(vm.TOP_TAGS_SOURCE, size="1", color=T.TEXT_MUTED),
                width="100%",
                spacing="1",
                align_items="start",
            ),
        ),
        rx.cond(
            BrandProposalState.frequency != "", rx.text(BrandProposalState.frequency, size="2")
        ),
        width="100%",
        spacing="2",
        align_items="start",
    )


def _correction_drawer() -> rx.Component:
    country_input = rx.select.root(
        rx.select.trigger(
            placeholder="País",
            width="100%",
            id="proposal-correction-country",
            aria_label=BrandProposalState.edit_label,
        ),
        rx.select.content(*[rx.select.item(name, value=code) for code, name in COUNTRY_OPTIONS]),
        value=BrandProposalState.edit_value,
        on_change=BrandProposalState.set_edit_value,
        disabled=BrandProposalState.busy != "",
    )
    return drawer(
        rx.vstack(
            rx.el.label(
                BrandProposalState.edit_label,
                html_for=rx.cond(
                    BrandProposalState.edit_field == "country_code",
                    "proposal-correction-country",
                    rx.cond(
                        BrandProposalState.edit_field == "logo",
                        "proposal-correction-logo",
                        "proposal-correction",
                    ),
                ),
            ),
            rx.cond(
                BrandProposalState.edit_field == "logo",
                rx.checkbox(
                    "Usar mi foto de perfil",
                    checked=BrandProposalState.edit_logo,
                    on_change=BrandProposalState.set_edit_logo,
                    id="proposal-correction-logo",
                    aria_label=BrandProposalState.edit_label,
                    disabled=BrandProposalState.busy != "",
                ),
                rx.cond(
                    BrandProposalState.edit_field == "country_code",
                    country_input,
                    rx.input(
                        value=BrandProposalState.edit_value,
                        on_change=BrandProposalState.set_edit_value,
                        id="proposal-correction",
                        aria_label=BrandProposalState.edit_label,
                        width="100%",
                        disabled=BrandProposalState.busy != "",
                    ),
                ),
            ),
            rx.cond(
                BrandProposalState.edit_error != "", callout(BrandProposalState.edit_error, "error")
            ),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        open=BrandProposalState.edit_open,
        on_open_change=BrandProposalState.close_correction,
        title=vm.EDIT_TITLE,
        footer=rx.hstack(
            rx.button(
                vm.CANCEL_LABEL,
                variant="soft",
                min_height="44px",
                on_click=BrandProposalState.close_correction(False),
                disabled=BrandProposalState.busy != "",
            ),
            rx.spacer(),
            rx.button(
                vm.SAVE_LABEL,
                min_height="44px",
                on_click=BrandProposalState.save_correction,
                loading=BrandProposalState.busy == "edit",
                disabled=BrandProposalState.busy != "",
            ),
            width="100%",
        ),
    )


def _button(label: str, on_click: Any, busy: str, **props: Any) -> rx.Component:
    """A decision button, at least 44 px tall (N12); off while another one saves."""
    return rx.button(
        label,
        type="button",
        size="3",
        radius=_CONTROL_RADIUS,
        min_height="44px",
        on_click=on_click,
        loading=BrandProposalState.busy == busy,
        disabled=BrandProposalState.busy != "",
        **props,
    )


def proposal_review() -> rx.Component:
    """The review card: the notice, what was read, the three decisions — the main one
    first and widest, under the thumb on a phone."""
    return card(
        rx.vstack(
            callout(BrandProposalState.notice_message, "info", icon="sparkles"),
            _account(),
            _observations(),
            rx.divider(),
            _field(
                vm.RUBRO_LABEL,
                BrandProposalState.rubro,
                field="rubro_text",
                source=BrandProposalState.rubro_source,
            ),
            _field(
                "Ciudad",
                BrandProposalState.city,
                field="city",
                source=BrandProposalState.place_source,
            ),
            _field(
                "País",
                BrandProposalState.country_label,
                field="country_code",
                source=BrandProposalState.country_source,
            ),
            rx.hstack(
                rx.text(BrandProposalState.logo_label, size="2", color=T.TEXT_MUTED),
                rx.spacer(),
                _correct("logo", vm.LOGO_LABEL),
                width="100%",
                align="center",
            ),
            _colours(),
            _top_tags(),
            _tags(),
            rx.text(vm.PUBLIC_READ_NOTE, size="1", color=T.TEXT_MUTED),
            rx.vstack(
                _button(vm.APPROVE_LABEL, BrandProposalState.approve, _APPROVE, width="100%"),
                rx.flex(
                    _button(
                        vm.CHANGE_LABEL,
                        BrandProposalState.change,
                        _CHANGE,
                        variant="soft",
                        flex="1",
                        min_width="0",
                    ),
                    _button(
                        vm.DISCARD_LABEL,
                        BrandProposalState.discard,
                        _DISCARD,
                        variant="ghost",
                        color_scheme="gray",
                        flex="1",
                        min_width="0",
                        # apart from «Cambiar» on a phone, so it is not tapped by mistake
                        margin_top=rx.breakpoints(initial="1rem", sm="0"),
                    ),
                    direction=rx.breakpoints(initial="column", sm="row"),
                    gap="0.5rem",
                    width="100%",
                ),
                spacing="2",
                width="100%",
                padding_top="0.5rem",
            ),
            _correction_drawer(),
            spacing="4",
            width="100%",
            max_width="34rem",
            align_self="center",
        ),
        padding=rx.breakpoints(initial="1rem", sm="1.75rem"),
        width="100%",
        display="flex",
        flex_direction="column",
        align_items="center",
    )


def read_notice(on_first_step: rx.Var[bool]) -> rx.Component:
    """«No pudimos leer…» / «…es privada…» above Tus redes while nothing is read yet."""
    shown = (
        (BrandProposalState.notice == Notice.PRIVATE.value)
        | (BrandProposalState.notice == Notice.UNREADABLE.value)
    ) & on_first_step
    return rx.cond(
        shown & (BrandConnectState.profile_username == ""),
        callout(BrandProposalState.notice_message, "info"),
    )


def approved_notice(step: rx.Var[str]) -> rx.Component:
    """«Listo. Guardamos tu identidad de marca.» on the step the approval opened."""
    return rx.cond(
        BrandProposalState.approved & (BrandProposalState.approved_step == step),
        callout(vm.APPROVED_NOTICE, "ok"),
    )

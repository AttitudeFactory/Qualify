"""The historia's own page (founder 2026-11-26): «Abrir en Instagram» there, the iPhone
line next to «Descargar», no «Promocionar» on a historia's card, and «Ver en Tu semana»
from a switch blocked by its scheduled event. The page follows the card's rule in every
variant of `/drafts/<id>` (single piece, template package, video by parts)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
import reflex as rx
from qualify_api.planner.post_reader import ApprovalStatus, PostOutput, PostSummary

from . import creative_pages, post_card, story_mark_ui
from . import planner_provider as planner
from . import story_mark_provider as provider
from . import story_mark_state as state_module
from .planner_vm import build_post_option, parse_week_param
from .stories_vm import (
    PLATFORM_ANDROID,
    PLATFORM_DESKTOP,
    PLATFORM_IOS,
    STORY_DOWNLOAD_HINT_IOS,
    device_platform,
    story_download_hint_offered,
    story_share_offered,
)
from .story_mark_provider import StoryMarkRefused
from .story_mark_state import StoryMarkState
from .story_mark_vm import (
    REASON_PURGED,
    REASON_SCHEDULED,
    SCHEDULED_LINK,
    StoryMarkVM,
    next_live_event,
    scheduled_event_href,
    story_mark,
)

TENANT = UUID(int=7)
DRAFT = UUID(int=9)
BOGOTA = ZoneInfo("America/Bogota")
WHEN = datetime(2026, 12, 2, 15, tzinfo=UTC)


def _render(component: rx.Component) -> str:
    return str(component.render())


# -- the card's rule, on the page's path ------------------------------------------------


def _summary(**kw: Any) -> PostSummary:
    params: dict[str, Any] = {
        "post_id": DRAFT,
        "brand_id": UUID(int=1),
        "title": "Historia",
        "approval": ApprovalStatus.APPROVED,
        "category": "story",
        "thumbnail_url": "t/x/preview.jpg",
        "asset_count": 1,
        "media_types": ("IMAGE",),
        "is_publishable": True,
    }
    params.update(kw)
    return PostSummary(**params)


_TEMPLATE_STORY = {
    "category": "galeria",
    "outputs": (
        PostOutput(
            port="story",
            media_type="image",
            media_product_type="STORIES",
            is_publishable=True,
            media_types=("IMAGE",),
        ),
    ),
}


@pytest.fixture
def media(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner, "_thumbnail_url", lambda _t, _u: "/r2media/img-token")
    monkeypatch.setattr(planner, "_video_url", lambda _t, key: "/r2media/vid" if key else "")


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({}, "/r2media/img-token"),  # an approved, publishable historia of one image
        (_TEMPLATE_STORY, "/r2media/img-token"),  # a template whose one output is `story`
        ({"category": "galeria"}, ""),  # not a historia
        ({"approval": ApprovalStatus.PENDING}, ""),  # not approved yet
        ({"is_publishable": False}, ""),  # its final file is not ready
        ({"is_publishable": False, "retention_state": "purged"}, ""),  # files deleted
        ({"asset_count": 3, "media_types": ("IMAGE", "IMAGE", "IMAGE")}, ""),  # several
        ({"media_types": ("VIDEO",), "video_object_key": None}, ""),  # no file of its own
        ({"media_types": ("VIDEO",), "video_object_key": "t/x/v.mp4"}, "/r2media/vid"),
    ],
)
def test_the_page_shares_what_the_card_shares(media: None, kw: dict, expected: str) -> None:
    post = _summary(**kw)
    assert planner.story_share_url_of(TENANT, post) == expected
    card = planner._post_option(
        post,
        thumbnails={str(post.post_id): "/r2media/img-token"},
        video_url="/r2media/vid" if post.video_object_key else "",
    )
    assert card.story_share_url == expected  # the same view-model: never two rules


def _event(n: int, status: str, when: datetime = WHEN) -> SimpleNamespace:
    return SimpleNamespace(id=UUID(int=n), status=status, scheduled_at=when)


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch, media: None) -> dict[str, Any]:
    """The provider over a real `PostSummary` and the real `story_share_url_of`; only
    the reads (post, events, zone) and the write are stubbed."""
    box: dict[str, Any] = {"post": _summary(), "events": [], "zones": []}

    class Reader:
        def get(self, *, tenant_id: UUID, post_id: UUID) -> Any:
            return box["post"]

    class Service:
        def update_post(self, **kw: Any) -> None:
            from dataclasses import replace

            box["post"] = replace(box["post"], category=kw["category"])

    def zone(_t: UUID, override: str = "") -> ZoneInfo:
        box["zones"].append(override)
        return ZoneInfo(override or "America/Bogota")

    monkeypatch.setattr(provider, "_reader", Reader)
    monkeypatch.setattr(provider, "_service", Service)
    monkeypatch.setattr(provider, "_events", lambda _t, _d: box["events"])
    monkeypatch.setattr(provider, "_zone", zone)
    return box


def test_a_template_historia_gets_the_actions_but_never_the_switch(db: dict) -> None:
    db["post"] = _summary(**_TEMPLATE_STORY)
    mark = provider.story_mark_info(TENANT, DRAFT)
    assert not mark.shown  # a template package keeps its outputs' own shapes
    assert mark.story_ready and mark.share_url == "/r2media/img-token"


def test_the_switch_flips_the_share_file_and_the_iphone_line_with_it(db: dict) -> None:
    mark = provider.story_mark_info(TENANT, DRAFT)
    assert mark.story_ready and mark.share_url == "/r2media/img-token"
    mark = provider.set_story(TENANT, DRAFT, story=False)
    assert not mark.is_story and not mark.story_ready and mark.share_url == ""
    mark = provider.set_story(TENANT, DRAFT, story=True)
    assert mark.story_ready and mark.share_url == "/r2media/img-token"


@pytest.mark.parametrize(
    ("kw", "ready", "share"),
    [
        ({"approval": ApprovalStatus.PENDING}, False, ""),  # not approved: no iPhone line
        ({"category": "galeria"}, False, ""),
        ({"is_publishable": False, "retention_state": "purged"}, False, ""),
        ({"retention_state": "purged"}, False, ""),  # never minted once the files are gone
        ({"is_publishable": False}, False, ""),
        ({"asset_count": 2, "media_types": ("IMAGE", "IMAGE")}, False, ""),
        ({"media_types": ("VIDEO",), "video_object_key": None}, False, ""),
        ({"media_types": ("VIDEO",), "video_object_key": "t/x/v.mp4"}, True, "/r2media/vid"),
    ],
)
def test_what_the_page_offers_per_piece(db: dict, kw: dict, ready: bool, share: str) -> None:
    db["post"] = _summary(**kw)
    mark = provider.story_mark_info(TENANT, DRAFT)
    assert (mark.story_ready, mark.share_url) == (ready, share)


def test_a_purged_historia_says_why_its_switch_is_off(db: dict) -> None:
    db["post"] = _summary(is_publishable=False, retention_state="purged")
    mark = provider.story_mark_info(TENANT, DRAFT)
    assert mark.reason == REASON_PURGED and not mark.can_change and mark.share_url == ""


def test_a_share_source_that_fails_only_hides_the_button(
    db: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_t: UUID, _p: Any) -> str:
        raise RuntimeError("no token")

    monkeypatch.setattr(provider, "_share_url", boom)
    mark = provider.story_mark_info(TENANT, DRAFT)
    assert mark.shown and mark.share_url == "" and not mark.story_ready


@pytest.mark.parametrize(
    ("agent", "android", "iphone"),
    [
        ("Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/130.0 Mobile", True, False),
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/604.1", False, True),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/130.0", False, False),
    ],
)
def test_android_shares_iphone_reads_the_line_desktop_gets_nothing(
    agent: str, android: bool, iphone: bool
) -> None:
    platform = device_platform(agent)
    assert story_share_offered(platform) is android
    assert story_download_hint_offered(platform) is iphone
    assert not story_download_hint_offered(PLATFORM_DESKTOP)
    assert not story_download_hint_offered(PLATFORM_ANDROID)
    assert story_download_hint_offered(PLATFORM_IOS)
    assert STORY_DOWNLOAD_HINT_IOS == (
        "Descárgala y súbela a tus historias de Instagram con tu música."
    )


def test_the_page_block_renders_the_cards_button_and_the_iphone_line() -> None:
    tree = _render(story_mark_ui.story_page_phone_actions(rx.Var.create("d1")))
    assert "story-share-" in tree and "q-share-busy" in tree  # the card's own block
    assert "story_mark_state.share_url" in tree and "gallery_state.story_share_here" in tree
    # the iPhone line: the card's historia rule, on an iPhone only
    assert "story_mark_state.story_ready" in tree
    assert 'gallery_state.device_rx_state_?.valueOf?.() === "ios"' in tree
    assert "tus historias de Instagram con tu m" in tree


# -- every variant of the page -----------------------------------------------------------


def test_every_variant_of_the_page_has_the_actions_and_the_refresh() -> None:
    single = _render(creative_pages._single_piece_detail())
    parts = _render(creative_pages._parts_parent_made())
    for tree in (single, parts):
        assert "story-share-" in tree  # «Abrir en Instagram»
        assert "tus historias de Instagram con tu m" in tree  # the iPhone line
        # approving on the page remounts the reader: the button shows without a reload
        assert 'creative_state.draft_rx_state_?.["status"]' in tree.replace(" ", "")


def test_approving_remounts_the_reader_on_its_status() -> None:
    tree = _render(story_mark_ui.story_mark_control(rx.Var.create("d1"), rx.Var.create("approved")))
    assert 'key:("d1-"+"approved")' in tree


async def _drain(gen: Any) -> list[Any]:
    return [e async for e in gen]


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    box: dict[str, Any] = {"mark": None, "refuse": ""}

    async def tenant(self: StoryMarkState) -> UUID:
        return TENANT

    async def zone(self: StoryMarkState) -> str:
        return "America/Caracas"

    def info(_t: UUID, _d: UUID, tz: str = "") -> StoryMarkVM:
        box["tz"] = tz
        return box["mark"]

    def write(_t: UUID, _d: UUID, *, story: bool, tz_override: str = "") -> StoryMarkVM:
        raise StoryMarkRefused(box["refuse"])

    monkeypatch.setattr(StoryMarkState, "_tenant", tenant)
    monkeypatch.setattr(StoryMarkState, "_zone_override", zone)
    monkeypatch.setattr(state_module, "story_mark_info", info)
    monkeypatch.setattr(state_module, "set_story", write)
    return box


def _free_mark() -> StoryMarkVM:
    return story_mark(
        category="galeria",
        media_types=("IMAGE",),
        has_outputs=False,
        has_live_event=False,
        purged=False,
        video_too_long=False,
    )


async def test_a_flip_refused_by_a_new_event_shows_the_link_at_once(backend: dict) -> None:
    from dataclasses import replace

    backend["mark"] = _free_mark()
    state = StoryMarkState()
    await StoryMarkState.load_for.fn(state, str(DRAFT))
    assert state.can_change and state.event_href == ""
    assert backend["tz"] == "America/Caracas"  # Tu semana's own zone choice
    # another tab scheduled it meanwhile
    blocked = story_mark(
        category="galeria",
        media_types=("IMAGE",),
        has_outputs=False,
        has_live_event=True,
        purged=False,
        video_too_long=False,
    )
    backend["mark"] = replace(blocked, event_href="/planner?semana=2026-11-30&ficha=e1")
    backend["refuse"] = REASON_SCHEDULED
    assert await _drain(StoryMarkState.set_story.fn(state, True)) == []
    assert state.error == REASON_SCHEDULED and not state.busy
    assert state.reason == REASON_SCHEDULED and not state.can_change
    assert state.event_href == "/planner?semana=2026-11-30&ficha=e1"


async def test_another_refusal_does_not_re_read(backend: dict) -> None:
    backend["mark"] = _free_mark()
    state = StoryMarkState()
    await StoryMarkState.load_for.fn(state, str(DRAFT))
    backend["mark"] = None  # a re-read here would crash `_apply`
    backend["refuse"] = REASON_PURGED
    assert await _drain(StoryMarkState.set_story.fn(state, True)) == []
    assert state.error == REASON_PURGED and state.can_change


async def test_the_state_carries_the_template_historias_actions(
    db: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def tenant(self: StoryMarkState) -> UUID:
        return TENANT

    async def zone(self: StoryMarkState) -> str:
        return ""

    monkeypatch.setattr(StoryMarkState, "_tenant", tenant)
    monkeypatch.setattr(StoryMarkState, "_zone_override", zone)
    db["post"] = _summary(**_TEMPLATE_STORY)
    state = StoryMarkState()
    await StoryMarkState.load_for.fn(state, str(DRAFT))
    assert state.loaded and not state.shown
    assert state.story_ready and state.share_url == "/r2media/img-token"


# -- 2. «Promocionar como anuncio» on a historia (HIS-1, m-25130281) -------------------


def _card(category: str, used: int) -> Any:
    return build_post_option(
        post_id=str(uuid4()),
        title="x",
        caption_excerpt="",
        thumbnail_url="/r2media/t",
        category=category,
        approval="approved",
        detail_href="/drafts/x",
        is_publishable=True,
        unpublishable_reason="",
        gallery_state="schedulable",
        media_types=("IMAGE",),
        content_kind="template",
        times_published=used,
    )


def test_a_historia_card_is_one_the_old_guard_let_through() -> None:
    story, plain = _card("story", used=2), _card("galeria", used=2)
    assert story.is_story and story.used_count > 0
    assert story.kind != "story"  # why `post.kind != "story"` never hid anything
    assert not plain.is_story and plain.used_count > 0


def _cards() -> tuple[str, str]:
    from .gallery_state import GalleryState

    gallery = _render(rx.foreach(GalleryState.visible, creative_pages._gallery_card))
    planner_card = _render(
        rx.foreach(GalleryState.visible, lambda p: post_card.post_card(p, actions=rx.fragment()))
    )
    return gallery, planner_card


def test_both_cards_send_a_historia_to_the_story_ad() -> None:
    """Rendered trees: a historia with a story ad source opens `?formato=historia` with
    its own label; any other POST keeps the plain link behind `used_count`; `kind`
    decides nothing."""
    for tree in _cards():
        story = tree.index('"/promote")+"?formato=historia"')
        cond = tree[:story][tree[:story].rindex("is_story") :]
        assert "story_ad_ready" in cond and "kind" not in cond
        assert "Promocionar como anuncio" in tree[story:]
        rest = tree[story:][tree[story:].index("used_count") :]
        assert '"/promote")' in rest and "kind" not in rest[: rest.index('"/promote")')]


def test_the_story_link_is_the_wizards_story_path() -> None:
    from .promotion_vm import STORY_FORMAT, STORY_PROMOTE, story_ad_href

    assert STORY_PROMOTE == "Promocionar como anuncio"
    assert story_ad_href("p") == f"/drafts/p/promote?formato={STORY_FORMAT}"


def test_the_wizard_says_it_is_a_paid_story_ad_on_the_story_path_only() -> None:
    from . import promotion_page
    from .promotion_vm import STORY_PAID_NOTE

    assert STORY_PAID_NOTE == (
        "Esto crea un anuncio pagado que se muestra entre las historias de otras cuentas. "
        "Tu historia no cambia."
    )
    tree = _render(promotion_page._wizard(rx.fragment(), rx.fragment()))
    note = tree.index(STORY_PAID_NOTE)
    assert "story_entry" in tree[:note][-400:]


def test_only_a_historia_the_story_ad_can_use_gets_the_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A historia without a 9:16 source keeps the link hidden; ONE read asks for the
    approved historias only, never for other publications."""
    ready, unready = _card("story", used=0), _card("story", used=0)
    plain = _card("galeria", used=2)
    pending = replace(_card("story", used=0), is_approved=False)
    asked: list[list[str]] = []

    def story_ads_ready(tenant_id: UUID, ids: list[UUID]) -> set[UUID]:
        asked.append([str(i) for i in ids])
        return {UUID(ready.post_id)}

    monkeypatch.setattr(planner, "story_ads_ready", story_ads_ready)
    marked = planner._with_story_ads(uuid4(), [ready, unready, plain, pending])
    assert [o.story_ad_ready for o in marked] == [True, False, False, False]
    assert asked == [[ready.post_id, unready.post_id]]
    assert marked[1] is unready and marked[2] is plain and marked[3] is pending


def test_a_failed_readiness_read_hides_every_story_link(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(tenant_id: UUID, ids: list[UUID]) -> set[UUID]:
        raise RuntimeError("db down")

    monkeypatch.setattr(planner, "story_ads_ready", broken)
    marked = planner._with_story_ads(uuid4(), [_card("story", used=0)])
    assert not marked[0].story_ad_ready


def test_the_batched_read_is_the_wizards_own_rule() -> None:
    """Same conditions as `_PIECE`/`_ASSETS`, only for many ids at once."""
    from . import promotion_unpublished_provider as pup

    rule = pup._PIECE.text.split("WHERE d.id=:draft", 1)[1]
    assert pup._PIECES.text.endswith(rule) and "d.id=ANY(:drafts)" in pup._PIECES.text
    assert pup._ASSETS_MANY.text.endswith(pup._ASSETS.text.split(":version", 1)[1])
    assert pup.story_ads_ready(uuid4(), []) == set()


# -- 3. «Ver en Tu semana» from the blocked switch -------------------------------------


def test_the_next_event_to_go_out_is_the_earliest() -> None:
    later = ("b", datetime(2026, 12, 9, 15, tzinfo=UTC))
    sooner = ("a", WHEN)
    assert next_live_event([later, sooner]) == sooner
    assert next_live_event([]) is None


@pytest.mark.parametrize(
    ("day", "monday"),
    [
        (date(2026, 12, 2), "2026-11-30"),  # a Wednesday
        (date(2026, 11, 30), "2026-11-30"),  # the Monday itself
        (date(2026, 12, 6), "2026-11-30"),  # a Sunday stays in its week
    ],
)
def test_the_link_lands_on_the_events_week(day: date, monday: str) -> None:
    href = scheduled_event_href("evt", day)
    assert href == f"/planner?semana={monday}&ficha=evt"
    assert parse_week_param(monday) == monday  # the planner reads it as that week


def test_several_events_open_the_next_one_in_the_planners_zone(db: dict) -> None:
    db["events"] = [
        _event(1, "scheduled", datetime(2026, 12, 20, 15, tzinfo=UTC)),
        # Monday 03:00 UTC is still Sunday in Bogotá: the week before
        _event(2, "scheduled", datetime(2026, 12, 7, 3, tzinfo=UTC)),
        _event(3, "published", datetime(2026, 11, 1, 15, tzinfo=UTC)),  # never again
        _event(4, "cancelled", datetime(2026, 11, 2, 15, tzinfo=UTC)),
    ]
    mark = provider.story_mark_info(TENANT, DRAFT)
    assert mark.reason == REASON_SCHEDULED and not mark.can_change
    assert mark.event_href == f"/planner?semana=2026-11-30&ficha={UUID(int=2)}"
    # in Tu semana's own override (Madrid) that same moment is already Monday
    mark = provider.story_mark_info(TENANT, DRAFT, "Europe/Madrid")
    assert mark.event_href == f"/planner?semana=2026-12-07&ficha={UUID(int=2)}"
    assert db["zones"][-1] == "Europe/Madrid"


def test_no_live_event_means_no_link_and_publishing_opens_too(db: dict) -> None:
    db["events"] = [_event(3, "published")]
    assert provider.story_mark_info(TENANT, DRAFT).event_href == ""
    db["events"] = [_event(8, "publishing")]
    assert provider.story_mark_info(TENANT, DRAFT).event_href.endswith(f"ficha={UUID(int=8)}")


def test_a_foreign_or_deleted_event_opens_nothing_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`?ficha=` is re-read under the tenant: the repository (RLS) finds nothing for an
    id of another business or a removed event, and the planner says so plainly."""
    from qualify_api.planner.service import UnknownEvent

    class Service:
        def get(self, *, tenant_id: UUID, event_id: UUID) -> Any:
            raise UnknownEvent(str(event_id))

    monkeypatch.setattr(planner, "production_planner_service", Service)
    with pytest.raises(UnknownEvent) as raised:
        planner.event_detail(TENANT, str(uuid4()))
    assert planner.planner_error_message(raised.value) == (
        "Esa publicación ya no está en el calendario. Actualiza la página."
    )


def test_the_link_is_one_control_by_the_reason_that_describes_the_switch() -> None:
    tree = _render(story_mark_ui.story_mark_control(rx.Var.create("d1")))
    assert '"aria-describedby":"story-mark-note"' in tree and 'id:"story-mark-note"' in tree
    link = tree[tree.index(json.dumps(SCHEDULED_LINK)[1:-1]) - 2000 :]
    button = link[link.rindex("RadixThemesButton") :]
    assert button.index("asChild:true") < button.index("RadixThemesLink")  # one control
    assert '["minHeight"] : "44px"' in button
    assert '"aria-label":"Ver en Tu semana cu' in button
    assert tree.index('id:"story-mark-note"') < tree.index("RadixThemesLink")

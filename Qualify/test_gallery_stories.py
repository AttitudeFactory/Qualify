"""Historias in the publications gallery (founder 2026-11-16): the «Historia» label, the
«Tipo» › «Historias» filter, and «Abrir en Instagram» — approved historias only, on
Android only; an iPhone keeps «Descargar» on the historia's page, a computer never
gets it."""

from __future__ import annotations

import inspect

import pytest

from . import creative_pages, stories_page
from .gallery_state import GalleryState, kind_options
from .planner_vm import (
    GALLERY_FILTER_ALL,
    STORIES_FILTER,
    build_output_chip,
    build_post_option,
    filter_posts,
    is_story_post,
    story_share_source,
)
from .stories_vm import (
    PLATFORM_ANDROID,
    PLATFORM_DESKTOP,
    PLATFORM_IOS,
    device_platform,
    story_share_message,
    story_share_offered,
)

_ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Mobile Safari/537.36"
)
_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)
_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)


def _post(post_id: str, *, category: str = "story", approved: bool = True, **kw: object):
    params: dict[str, object] = {
        "post_id": post_id,
        "title": "Historia " + post_id,
        "caption_excerpt": "",
        "thumbnail_url": "/r2media/tok-" + post_id,
        "category": category,
        "approval": "approved" if approved else "pending",
        "detail_href": "/drafts/" + post_id,
        "is_publishable": approved,
        "unpublishable_reason": "",
        "gallery_state": "schedulable" if approved else "in_review",
        "media_types": ("IMAGE",),
        "content_kind": "template",
    }
    params.update(kw)
    return build_post_option(**params)  # type: ignore[arg-type]


# -- detection ------------------------------------------------------------------------


def test_a_story_is_its_category_or_only_story_outputs() -> None:
    assert is_story_post("story")
    assert is_story_post("galeria", ["story"])
    assert not is_story_post("galeria", ["story", "reel"])  # «Multiformato»
    assert not is_story_post("reel")
    assert not is_story_post("galeria")


def test_the_card_of_a_story_says_historia_and_others_do_not() -> None:
    assert _post("s").is_story
    assert not _post("p", category="galeria").is_story
    chip = build_output_chip(
        port="story", is_publishable=True, unpublishable_reason="", event_status=None
    )
    assert _post("o", category="galeria", outputs=[chip]).is_story


def test_the_card_renders_the_historia_badge_only_for_stories() -> None:
    source = inspect.getsource(creative_pages._gallery_card)
    assert 'rx.cond(post.is_story, destination_badge("story", STORY_BADGE))' in source
    assert creative_pages.STORY_BADGE == "Historia"


# -- filter ---------------------------------------------------------------------------


def test_tipo_offers_historias_first_only_when_there_is_one() -> None:
    mixed = [_post("p", category="galeria"), _post("s")]
    assert [o.value for o in kind_options(mixed)][0] == STORIES_FILTER
    assert [o.label for o in kind_options(mixed)][0] == "Historias"
    assert STORIES_FILTER not in [o.value for o in kind_options([_post("p", category="reel")])]


def test_the_historias_filter_keeps_only_stories() -> None:
    posts = [_post("p", category="galeria"), _post("s"), _post("r", category="reel")]
    kept = filter_posts(posts, state=GALLERY_FILTER_ALL, category="", content_kind=STORIES_FILTER)
    assert [p.post_id for p in kept] == ["s"]


def test_aprobados_filters_historias_and_keeps_it_in_the_address() -> None:
    state = GalleryState()
    state.posts = [_post("p", category="galeria"), _post("s")]
    state.route = "/aprobados"
    assert state.approved_kind_options[0].value == STORIES_FILTER
    script = state.set_approved_kind_filter(STORIES_FILTER)
    assert [p.post_id for p in state.approved_visible] == ["s"]
    assert "tipo=historias" in str(script)


def test_por_aprobar_accepts_the_historias_filter_only_with_a_pending_historia() -> None:
    state = GalleryState()
    state.posts = [_post("p", category="galeria", approved=False), _post("s", approved=False)]
    state.set_content_kind_filter(STORIES_FILTER)
    assert state.content_kind_filter == STORIES_FILTER
    assert [p.post_id for p in state.visible] == ["s"]
    # the only historia is approved: «Por aprobar» has none, the filter falls back
    state.posts = [_post("p", category="galeria", approved=False), _post("s")]
    state.set_content_kind_filter(STORIES_FILTER)
    assert state.content_kind_filter == GALLERY_FILTER_ALL


def _story_chip(kind_type: str = "IMAGE", port: str = "story"):
    return build_output_chip(
        port=port,
        is_publishable=True,
        unpublishable_reason="",
        event_status=None,
        media_types=(kind_type,),
    )


def test_a_template_historia_shares_its_one_story_output() -> None:
    # A template run that rendered only the 9:16 story: category galeria, one output.
    image = _post("ti", category="galeria", outputs=[_story_chip()])
    assert image.is_story and image.kind == "pack"
    assert image.story_share_url == "/r2media/tok-ti"
    video = _post(
        "tv",
        category="galeria",
        outputs=[_story_chip("VIDEO")],
        media_types=("VIDEO",),
        video_url="/r2media/vid-tv",
    )
    assert video.story_share_url == "/r2media/vid-tv"
    # a video output without its own file is never shared as its poster
    no_file = _post(
        "tn", category="galeria", outputs=[_story_chip("VIDEO")], media_types=("VIDEO",)
    )
    assert no_file.story_share_url == ""


def test_a_historia_whose_final_is_not_ready_shares_nothing() -> None:
    # approved, but its file is still the vista previa / being remade: never shared
    pending = _post("tp", category="galeria", outputs=[_story_chip()], is_publishable=False)
    assert pending.is_story and pending.story_share_url == ""
    assert _post("sp", is_publishable=False).story_share_url == ""
    assert (
        story_share_source(
            is_story=True,
            approved=True,
            kind="image",
            video_url="",
            thumbnail_url="/r2media/x",
            publishable=False,
        )
        == ""
    )


def test_every_way_out_of_the_script_gives_the_button_back() -> None:
    js = stories_page.STORY_SHARE_FROM_URL_JS
    outer = js[js.rindex("} catch (e) {") :]
    assert "done();" in outer


def test_a_package_or_a_story_with_more_files_shares_nothing() -> None:
    two = _post("t2", category="galeria", outputs=[_story_chip(), _story_chip(port="reel")])
    assert two.story_share_url == ""
    more = _post("tm", category="galeria", outputs=[_story_chip()], media_types=("IMAGE", "IMAGE"))
    assert more.story_share_url == ""


def test_the_card_line_drops_historia_where_the_label_says_it() -> None:
    story = _post("s")
    assert story.card_media_label == "Imagen · 9:16"
    assert "Historia" in story.media_label  # other screens keep the format's name
    feed = _post("p", category="galeria")
    assert feed.card_media_label == feed.media_label


# -- «Abrir en Instagram»: which file, which phone --------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, "/r2media/img"),  # an approved image story: its own image
        ({"approved": False}, ""),  # not approved yet: never
        ({"is_story": False}, ""),  # not a story: never
        ({"kind": "video", "video_url": "/r2media/vid"}, "/r2media/vid"),
        ({"kind": "video", "video_url": ""}, ""),  # never the poster for a video
        ({"kind": "carousel"}, ""),  # several files: not one share
        ({"thumbnail_url": "uploads/local.jpg"}, ""),  # not fetchable from the browser
    ],
)
def test_the_share_source_is_one_approved_storys_own_file(kwargs, expected) -> None:
    params = {
        "is_story": True,
        "approved": True,
        "kind": "image",
        "video_url": "",
        "thumbnail_url": "/r2media/img",
    }
    params.update(kwargs)
    assert story_share_source(**params) == expected  # type: ignore[arg-type]


def test_only_an_approved_story_card_carries_a_share_file() -> None:
    assert _post("s").story_share_url == "/r2media/tok-s"
    assert _post("s", approved=False).story_share_url == ""
    assert _post("p", category="galeria").story_share_url == ""


@pytest.mark.parametrize(
    ("agent", "platform", "offered"),
    [
        (_ANDROID, PLATFORM_ANDROID, True),
        (_IPHONE, PLATFORM_IOS, False),  # iPhone keeps only «Descargar»
        (_MAC, PLATFORM_DESKTOP, False),
        ("", PLATFORM_DESKTOP, False),
    ],
)
def test_the_share_button_is_android_only(agent: str, platform: str, offered: bool) -> None:
    assert device_platform(agent) == platform
    assert story_share_offered(platform) is offered
    state = GalleryState()
    state.set_device(agent)
    assert state.story_share_here is offered


def test_the_card_gates_the_button_on_the_file_and_the_phone() -> None:
    source = inspect.getsource(creative_pages._story_share)
    assert '(post.story_share_url != "") & GalleryState.story_share_here' in source
    assert "GalleryState.handle_story_share" in source
    assert "STORY_SHARE_BUSY" in source and "data-busy" in source


def test_the_share_button_sits_right_under_the_main_button() -> None:
    source = inspect.getsource(creative_pages._gallery_card)
    assert source.index("_story_share(post)") < source.index('"Ver publicación"')


def test_the_url_and_the_id_reach_the_script_json_encoded() -> None:
    import reflex as rx

    from .gallery_state import GalleryState as State

    spec = stories_page.story_share_from_url(
        rx.Var.create("/r2media/a'b\"c"), rx.Var.create("story-share-x"), State.handle_story_share
    )
    code = str(rx.Var.create(spec))
    assert "('" not in code.split("})")[-1]  # no hand-quoted argument
    assert "JSON.stringify(" in code


def test_the_script_downloads_once_and_restores_the_button() -> None:
    js = stories_page.STORY_SHARE_FROM_URL_JS
    assert '"busy"' in js and "__qualifyStoryBusy" in js
    assert js.count("done()") >= 4  # every way out of the download gives the button back
    assert story_share_message("busy") is None


def test_the_gallery_script_is_android_only_and_fetches_the_file() -> None:
    js = stories_page.STORY_SHARE_FROM_URL_JS
    assert "/Android/i.test" in js and "iPhone" not in js
    assert "fetch(url" in js and "new File(" in js
    assert '"tap_again"' in js  # a fetch that outlived the tap asks for one more tap


def test_the_publish_flow_keeps_its_mobile_gate() -> None:
    # The /publish handoff is unchanged: iPhone and Android, the step-1 File.
    script = stories_page.share_to_instagram_script("publish-gallery-root")
    assert "/Android|iPhone|iPad|iPod/i" in script
    assert 'filesByRoot["publish-gallery-root"]' in script


def test_every_share_outcome_says_what_to_do_and_cancel_says_nothing() -> None:
    assert story_share_message("cancelled") is None
    for result in (
        "shared",
        "tap_again",
        "not_android",
        "insecure",
        "unsupported",
        "fetch_failed",
        "cannot_share_file",
        "error:boom",
    ):
        message = story_share_message(result)
        assert message is not None
        kind, text = message
        assert kind in ("success", "info", "error") and text.endswith(".")
        for word in ("story", "post", "share", "Stories"):
            assert word not in text
    state = GalleryState()
    assert state.handle_story_share("cancelled") is None
    assert state.handle_story_share("shared") is not None

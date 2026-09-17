"""The logo → palette wiring of the Brand Kit wizard (§ request 2026-09-16): colours from
an uploaded file and from the scraped profile picture go through ONE path
(`BrandWizardState.apply_logo_colours`), replace each other, and never touch a colour
picked by hand. Offline: `get_state` is answered by plain state instances and the
profile picture comes from a stubbed `avatar_proxy.resolve_avatar` — no network, no
credits."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from . import creative_wizard_pages as wiz
from .creative_state import CreativeState
from .creative_wizard_pages import BrandConnectState, BrandWizardState


def _png(*fills: str) -> bytes:
    image = Image.new("RGB", (100 * len(fills), 100), "white")
    draw = ImageDraw.Draw(image)
    for i, fill in enumerate(fills):
        draw.rectangle((i * 100 + 10, 10, i * 100 + 90, 90), fill=fill)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


class _Session:
    """The three states one wizard session touches, wired to answer `get_state`."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.creative = CreativeState()
        self.wizard = BrandWizardState()
        self.connect = BrandConnectState()
        self.connect.network = "instagram"
        self.connect.profile_username = "marca.demo"
        self.connect.profile_pic = "https://scontent.cdninstagram.com/pic.jpg"
        self.connect.profile_followers_count = 12_000
        self.connect.profile_pic_is_real = True
        by_class: dict[type, Any] = {
            CreativeState: self.creative,
            BrandWizardState: self.wizard,
            BrandConnectState: self.connect,
        }

        async def get_state(_self: Any, state_cls: type) -> Any:
            return by_class[state_cls]

        monkeypatch.setattr(BrandWizardState, "get_state", get_state)
        monkeypatch.setattr(BrandConnectState, "get_state", get_state)
        self.picture: bytes | None = _png("#be123c")
        self.fetches: list[tuple[str, str, str]] = []

        async def resolve_avatar(network: str, handle: str, url: str = "") -> Any:
            self.fetches.append((network, handle, url))
            return None if self.picture is None else (self.picture, "image/png")

        monkeypatch.setattr(wiz.avatar_proxy, "resolve_avatar", resolve_avatar)

    async def answer(self, value: str) -> None:
        self.connect.step = wiz._LOGO_QUESTION_STEP
        await BrandConnectState.answer_has_logo.fn(self.connect, value)


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> _Session:
    return _Session(monkeypatch)


async def test_an_uploaded_logo_adds_its_colours_next_to_the_hand_picked_ones(
    session: _Session,
) -> None:
    session.creative.kit_palette = "#000000"
    await session.wizard.apply_logo_colours(_png("#0f766e", "#f97316"), wiz.LOGO_SOURCE_UPLOAD)
    assert session.creative.kit_palette == "#000000,#0f766e,#f97316"
    assert session.wizard.logo_source == wiz.LOGO_SOURCE_UPLOAD


async def test_the_profile_picture_as_logo_seeds_the_palette_and_skips_tu_logo(
    session: _Session,
) -> None:
    await session.answer(wiz.HAS_LOGO_PROFILE)
    assert session.fetches == [
        ("instagram", "marca.demo", "https://scontent.cdninstagram.com/pic.jpg")
    ]
    assert session.creative.kit_palette == "#be123c"
    assert session.wizard.logo_source == wiz.LOGO_SOURCE_PROFILE
    assert session.wizard.has_logo == wiz.HAS_LOGO_PROFILE
    # nothing to upload or describe: straight to the palette, and back again
    assert session.connect.step == wiz._PALETTE_STEP
    BrandConnectState.prev_step.fn(session.connect)
    assert session.connect.step == wiz._LOGO_QUESTION_STEP


async def test_changing_the_answer_retires_the_profile_colours(session: _Session) -> None:
    session.creative.kit_palette = "#000000"
    await session.answer(wiz.HAS_LOGO_PROFILE)
    assert session.creative.kit_palette == "#000000,#be123c"

    await session.answer("si")
    assert session.creative.kit_palette == "#000000"  # the hand-picked colour stays
    assert session.connect.logo_from_profile is False
    assert session.connect.step == wiz._LOGO_UPLOAD_STEP  # Tu logo is back

    # then an uploaded file brings its own colours
    await session.wizard.apply_logo_colours(_png("#1e3a8a"), wiz.LOGO_SOURCE_UPLOAD)
    assert session.creative.kit_palette == "#000000,#1e3a8a"


async def test_an_upload_replaces_the_profile_colours_without_duplicates(
    session: _Session,
) -> None:
    await session.answer(wiz.HAS_LOGO_PROFILE)
    await session.wizard.apply_logo_colours(_png("#be123c", "#1e3a8a"), wiz.LOGO_SOURCE_UPLOAD)
    assert session.creative.kit_palette == "#be123c,#1e3a8a"
    assert session.wizard.logo_colors == ["#be123c", "#1e3a8a"]


async def test_a_picture_that_cannot_be_fetched_leaves_the_palette_alone(
    session: _Session,
) -> None:
    session.picture = None
    session.creative.kit_palette = "#000000"
    await session.answer(wiz.HAS_LOGO_PROFILE)
    assert session.creative.kit_palette == "#000000"
    assert session.wizard.logo_source == ""
    assert session.connect.step == wiz._PALETTE_STEP  # still the chosen logo


async def test_removing_the_uploaded_logo_takes_only_its_colours(session: _Session) -> None:
    session.creative.kit_palette = "#000000"
    await session.wizard.apply_logo_colours(_png("#0f766e"), wiz.LOGO_SOURCE_UPLOAD)
    session.wizard.logo_key = "uploads/t/logo/x.png"
    await BrandWizardState.clear_logo.fn(session.wizard)
    assert session.creative.kit_palette == "#000000"
    assert session.wizard.logo_source == "" and session.wizard.logo_colors == []


async def test_removing_an_upload_does_not_touch_profile_colours(session: _Session) -> None:
    await session.answer(wiz.HAS_LOGO_PROFILE)
    await BrandWizardState.clear_logo.fn(session.wizard)
    assert session.creative.kit_palette == "#be123c"


def test_the_logo_question_offers_the_profile_picture_only_when_it_is_real() -> None:
    rendered = str(wiz._connect_step_has_logo())
    assert "Mi foto de perfil es mi logo" in rendered
    # the third card sits behind the real-picture check, not just "has a URL"
    assert "profile_pic_is_real" in rendered


async def test_the_profile_answer_is_ignored_for_a_default_or_missing_picture(
    session: _Session,
) -> None:
    session.connect.profile_pic_is_real = False
    await session.answer(wiz.HAS_LOGO_PROFILE)
    assert session.fetches == []
    assert session.wizard.has_logo == ""
    assert session.connect.step == wiz._LOGO_QUESTION_STEP


DEFAULT_INSTAGRAM = Path(__file__).resolve().parent / "fixtures" / "instagram_default_avatar.jpg"


async def test_the_picture_check_tells_a_real_picture_from_the_default_one(
    session: _Session,
) -> None:
    check = session.connect._picture_is_real
    url = "https://scontent.cdninstagram.com/pic.jpg"

    assert await check("instagram", "marca.demo", url) is True  # a real picture

    session.picture = DEFAULT_INSTAGRAM.read_bytes()
    assert await check("instagram", "sin.foto", url) is False  # the grey silhouette

    session.picture = None
    assert await check("instagram", "caida", url) is False  # cannot be fetched

    calls = len(session.fetches)
    assert await check("instagram", "sin.url", "") is False  # no picture at all
    assert len(session.fetches) == calls  # and nothing was fetched for it


def test_a_new_profile_read_forgets_the_previous_choice() -> None:
    state = BrandConnectState()
    state.logo_from_profile = True
    state.profile_pic_is_real = True
    BrandConnectState._reset_fields(state)
    assert state.logo_from_profile is False
    assert state.profile_pic_is_real is False

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
            wiz.AuthState: wiz.AuthState(),  # no tenant: `analyze` reads live, caches nothing
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
    # nothing to upload or describe: straight to the palette, and back to the question
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


def test_the_brandboard_question_no_longer_offers_the_profile_picture() -> None:
    rendered = str(wiz._connect_step_has_logo())
    assert "Mi foto de perfil es mi logo" not in rendered  # removed 2026-09-29


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


# --------------------------------------------------------------------------------------
# § request 2026-09-21: a REAL profile picture is taken as the logo without asking
# --------------------------------------------------------------------------------------


async def test_a_real_picture_preanswers_the_question_and_skips_only_tu_logo(
    session: _Session,
) -> None:
    session.creative.kit_palette = "#000000"
    await session.connect._use_profile_picture_as_logo()

    assert session.connect.logo_from_profile is True
    assert session.wizard.has_logo == wiz.HAS_LOGO_PROFILE  # "Mi foto de perfil es mi logo"
    assert session.wizard.logo_source == wiz.LOGO_SOURCE_PROFILE
    assert session.creative.kit_palette == "#000000,#be123c"  # its colours joined the palette
    # the question is STILL asked (a brand answers it, or just presses Continuar), and
    # only Tu logo — nothing left to upload or describe — is skipped
    session.connect.step = wiz._IDENTITY_STEP
    BrandConnectState.next_step.fn(session.connect)
    assert session.connect.step == wiz._LOGO_QUESTION_STEP
    BrandConnectState.next_step.fn(session.connect)
    assert session.connect.step == wiz._PALETTE_STEP
    BrandConnectState.prev_step.fn(session.connect)
    assert session.connect.step == wiz._LOGO_QUESTION_STEP
    BrandConnectState.prev_step.fn(session.connect)
    assert session.connect.step == wiz._IDENTITY_STEP


async def test_the_preanswer_can_be_changed_and_tu_logo_comes_back(session: _Session) -> None:
    await session.connect._use_profile_picture_as_logo()
    assert session.wizard.has_logo == wiz.HAS_LOGO_PROFILE

    await session.answer("si")  # "Sí, ya tengo uno" instead of the picture
    assert session.connect.logo_from_profile is False
    assert session.connect.step == wiz._LOGO_UPLOAD_STEP


async def test_an_influencer_gets_the_picture_colours_but_no_logo_screens(
    session: _Session,
) -> None:
    session.connect.account_kind = "influencer"
    await session.connect._use_profile_picture_as_logo()
    session.connect.step = wiz._IDENTITY_STEP
    BrandConnectState.next_step.fn(session.connect)
    assert session.connect.step == wiz._VOICE_STEP  # 2026-09-29: logo + palette skipped


async def test_a_picture_that_cannot_be_fetched_is_not_taken_and_the_question_stays(
    session: _Session,
) -> None:
    session.picture = None
    await session.connect._use_profile_picture_as_logo()

    assert session.connect.logo_from_profile is False
    assert session.wizard.has_logo == ""
    session.connect.step = wiz._IDENTITY_STEP
    BrandConnectState.next_step.fn(session.connect)
    assert session.connect.step == wiz._LOGO_QUESTION_STEP  # asked, as before


async def test_a_new_read_takes_back_what_the_previous_picture_put_in(
    session: _Session,
) -> None:
    session.creative.kit_palette = "#000000"
    await session.connect._use_profile_picture_as_logo()
    assert session.creative.kit_palette == "#000000,#be123c"

    await session.connect._forget_profile_picture_logo()
    assert session.creative.kit_palette == "#000000"  # the hand-picked colour stays
    assert session.wizard.has_logo == ""
    assert session.wizard.logo_source == ""


async def test_forgetting_leaves_an_uploaded_logo_alone(session: _Session) -> None:
    await session.wizard.apply_logo_colours(_png("#1e3a8a"), wiz.LOGO_SOURCE_UPLOAD)
    session.wizard.has_logo = "si"
    await session.connect._forget_profile_picture_logo()
    assert session.wizard.has_logo == "si"
    assert session.wizard.logo_source == wiz.LOGO_SOURCE_UPLOAD
    assert session.creative.kit_palette == "#1e3a8a"


async def test_analyze_detects_a_real_picture_but_no_longer_preanswers_the_question(
    session: _Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = {
        "username": "marca.demo",
        "fullName": "Marca Demo",
        "bio": "",
        "category": "",
        "followers": 12_000,
        "profilePicUrl": "https://scontent.cdninstagram.com/pic.jpg",
    }
    monkeypatch.setattr(
        wiz.scrapecreators_client, "fetch_profile_and_posts", lambda *_a, **_k: profile
    )
    monkeypatch.setattr(
        wiz.creator_discovery,
        "seed_from_profile",
        lambda _profile: wiz.creator_discovery.DiscoverySeed(handle="marca.demo", niches=()),
    )
    state = session.connect
    state.profile_pic_is_real = False
    state.username = "marca.demo"

    async for _ in BrandConnectState.analyze.fn(state):
        pass

    assert state.profile_pic_is_real is True
    assert state.logo_from_profile is False  # no pre-answer since 2026-09-29
    assert session.wizard.has_logo == ""
    assert session.creative.kit_palette == ""  # the picture seeds no colours
    # a brand meets the question unanswered
    state.account_kind = "marca"
    state.step = wiz._IDENTITY_STEP
    BrandConnectState.next_step.fn(state)
    assert state.step == wiz._LOGO_QUESTION_STEP


async def test_analyze_asks_the_question_when_the_picture_is_only_the_default_one(
    session: _Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.picture = DEFAULT_INSTAGRAM.read_bytes()
    profile = {
        "username": "marca.demo",
        "followers": 12_000,
        "profilePicUrl": "https://scontent.cdninstagram.com/default.jpg",
    }
    monkeypatch.setattr(
        wiz.scrapecreators_client, "fetch_profile_and_posts", lambda *_a, **_k: profile
    )
    monkeypatch.setattr(
        wiz.creator_discovery,
        "seed_from_profile",
        lambda _profile: wiz.creator_discovery.DiscoverySeed(handle="marca.demo", niches=()),
    )
    state = session.connect
    state.username = "marca.demo"

    async for _ in BrandConnectState.analyze.fn(state):
        pass

    assert state.profile_pic_is_real is False
    assert state.logo_from_profile is False
    assert session.wizard.has_logo == ""
    state.step = wiz._IDENTITY_STEP
    BrandConnectState.next_step.fn(state)
    assert state.step == wiz._LOGO_QUESTION_STEP


async def test_analyze_asks_the_question_when_the_profile_has_no_picture(
    session: _Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = {"username": "marca.demo", "followers": 12_000, "profilePicUrl": ""}
    monkeypatch.setattr(
        wiz.scrapecreators_client, "fetch_profile_and_posts", lambda *_a, **_k: profile
    )
    monkeypatch.setattr(
        wiz.creator_discovery,
        "seed_from_profile",
        lambda _profile: wiz.creator_discovery.DiscoverySeed(handle="marca.demo", niches=()),
    )
    state = session.connect
    state.username = "marca.demo"

    async for _ in BrandConnectState.analyze.fn(state):
        pass

    assert state.logo_from_profile is False
    assert session.fetches == []  # nothing to fetch for a profile without a picture
    state.step = wiz._IDENTITY_STEP
    BrandConnectState.next_step.fn(state)
    assert state.step == wiz._LOGO_QUESTION_STEP


async def test_an_influencer_whose_picture_cannot_be_taken_skips_to_the_voice(
    session: _Session,
) -> None:
    session.picture = None
    session.connect.account_kind = "influencer"
    await session.connect._use_profile_picture_as_logo()
    assert session.connect.logo_from_profile is False
    session.connect.step = wiz._IDENTITY_STEP
    BrandConnectState.next_step.fn(session.connect)
    assert session.connect.step == wiz._VOICE_STEP


async def _analyze_as(
    session: _Session, monkeypatch: pytest.MonkeyPatch, *, kind: str, picture_url: str
) -> BrandConnectState:
    profile = {"username": "creador.demo", "followers": 12_000, "profilePicUrl": picture_url}
    monkeypatch.setattr(
        wiz.scrapecreators_client, "fetch_profile_and_posts", lambda *_a, **_k: profile
    )
    monkeypatch.setattr(
        wiz.creator_discovery,
        "seed_from_profile",
        lambda _profile: wiz.creator_discovery.DiscoverySeed(handle="creador.demo", niches=()),
    )
    state = session.connect
    state.account_kind = kind
    state.username = "creador.demo"
    async for _ in BrandConnectState.analyze.fn(state):
        pass
    state.step = wiz._IDENTITY_STEP
    BrandConnectState.next_step.fn(state)
    return state


async def test_analyze_does_not_ask_an_influencer_with_a_real_picture(
    session: _Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = await _analyze_as(
        session, monkeypatch, kind="influencer", picture_url="https://cdn.example/real.jpg"
    )
    assert state.logo_from_profile is False
    assert state.step == wiz._VOICE_STEP


async def test_analyze_skips_an_influencer_whose_picture_is_the_default_one(
    session: _Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.picture = DEFAULT_INSTAGRAM.read_bytes()
    state = await _analyze_as(
        session, monkeypatch, kind="influencer", picture_url="https://cdn.example/default.jpg"
    )
    assert state.logo_from_profile is False
    assert state.step == wiz._VOICE_STEP


async def test_analyze_skips_an_influencer_with_no_picture_at_all(
    session: _Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = await _analyze_as(session, monkeypatch, kind="influencer", picture_url="")
    assert state.logo_from_profile is False
    assert state.step == wiz._VOICE_STEP


DEFAULT_TIKTOK = Path(__file__).resolve().parent / "fixtures" / "tiktok_default_avatar.jpg"


async def test_the_picture_check_knows_tiktoks_default_by_its_url_without_downloading(
    session: _Session,
) -> None:
    url = (
        "https://p16-common-sign.tiktokcdn-us.com/musically-maliva-obj/1594805258216454"
        "~tplv-tiktokx-cropcenter:100:100.jpeg?x-signature=y"
    )
    calls = len(session.fetches)
    assert await session.connect._picture_is_real("tiktok", "nuevo.usuario", url) is False
    assert len(session.fetches) == calls  # decided from the URL alone


async def test_the_picture_check_knows_tiktoks_default_by_its_pixels_too(
    session: _Session,
) -> None:
    """A default image served from an object the URL list does not know yet (TikTok
    rotates its CDN objects) is still caught by what it looks like."""
    session.picture = DEFAULT_TIKTOK.read_bytes()
    url = "https://p16-common-sign.tiktokcdn-us.com/some-new-default-object/abc~x.jpeg"
    assert await session.connect._picture_is_real("tiktok", "otro.usuario", url) is False


async def test_analyze_skips_an_influencer_whose_tiktok_picture_is_the_default_one(
    session: _Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.connect.network = "tiktok"
    url = "https://p16-common-sign.tiktokcdn-us.com/musically-maliva-obj/1594805258216454~x.jpeg"
    state = await _analyze_as(session, monkeypatch, kind="influencer", picture_url=url)
    assert state.profile_pic_is_real is False
    assert state.logo_from_profile is False
    assert state.step == wiz._VOICE_STEP


# -- the logo versions colour the palette (§ fix 2026-10-01) -----------------------------


class _Upload:
    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data

    async def read(self) -> bytes:
        return self._data


@pytest.fixture
def staged(session: _Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Session:
    """Uploads land in a temp upload dir, under a session with a tenant."""
    monkeypatch.setattr(wiz.rx, "get_upload_dir", lambda: tmp_path)

    class _Auth:
        session_tenant_id = "a0000000-0000-4000-8000-0000000000c1"

    original = BrandWizardState.get_state

    async def get_state(self: Any, state_cls: type) -> Any:
        if state_cls is wiz.AuthState:
            return _Auth()
        return await original(self, state_cls)

    monkeypatch.setattr(BrandWizardState, "get_state", get_state)
    return session


async def test_uploading_a_logo_version_colours_the_palette(staged: _Session) -> None:
    staged.creative.kit_palette = "#000000"  # hand-picked: always stays
    await BrandWizardState.handle_logo_version_upload.fn(
        staged.wizard, [_Upload("iso.png", _png("#0f766e"))], "isotipo"
    )
    assert staged.creative.kit_palette == "#000000,#0f766e"
    # a fuller mark arrives: its colours replace the isotipo's
    await BrandWizardState.handle_logo_version_upload.fn(
        staged.wizard, [_Upload("imago.png", _png("#f97316"))], "imagotipo"
    )
    assert staged.creative.kit_palette == "#000000,#f97316"
    # a lesser one does not take over the palette
    await BrandWizardState.handle_logo_version_upload.fn(
        staged.wizard, [_Upload("logo.png", _png("#7c3aed"))], "isologo"
    )
    assert staged.creative.kit_palette == "#000000,#f97316"


async def test_removing_the_colouring_version_hands_the_palette_to_the_next(
    staged: _Session,
) -> None:
    staged.creative.kit_palette = "#000000"
    await BrandWizardState.handle_logo_version_upload.fn(
        staged.wizard, [_Upload("iso.png", _png("#0f766e"))], "isotipo"
    )
    await BrandWizardState.handle_logo_version_upload.fn(
        staged.wizard, [_Upload("imago.png", _png("#f97316"))], "imagotipo"
    )
    await BrandWizardState.clear_logo_version.fn(staged.wizard, "imagotipo")
    assert staged.creative.kit_palette == "#000000,#0f766e"
    await BrandWizardState.clear_logo_version.fn(staged.wizard, "isotipo")
    assert staged.creative.kit_palette == "#000000"
    assert staged.wizard.logo_colors == []

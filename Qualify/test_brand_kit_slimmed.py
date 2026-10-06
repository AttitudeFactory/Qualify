"""The Brand Kit slimmed down (§ request 2026-10-05): the brief inside ¿Quién es la marca?
with its proposals applied straight into the fields, the five lists filled on ¿Todo
correcto?, the voice configured in the editor, hashtags created from the account's own
text, and the city category shown even when it comes back empty."""

from __future__ import annotations

from typing import Any

import pytest
from qualify_api.creative.brief_ai import FieldProposal

from . import brand_documents as docs
from . import creative_wizard_pages as wiz
from . import scrapecreators_client as sc
from .creative_state import CreativeState


def _proposal(field: str, label: str, proposed: str, verified: bool | None = True) -> FieldProposal:
    return FieldProposal(field, label, "", proposed, "cita", verified)


# -- the brief, applied directly -------------------------------------------------------------


def test_the_brief_fills_the_fields_without_a_review_panel() -> None:
    creative = CreativeState()
    creative.kit_positioning = "medio escrito a mano"
    creative.kit_do_examples = "¡Hola, vecino!"
    filled = docs.apply_directly(
        creative,
        [
            _proposal("positioning", "Posicionamiento", "Smash burgers de autor en Táchira."),
            _proposal("audience", "Audiencia", "Jóvenes de 18 a 30.", verified=None),
            _proposal("do_examples", "Así sí habla la marca", "¡Hola, vecino!\nPídela ya"),
            _proposal("banned_words", "Palabras prohibidas", "barato", verified=False),
        ],
    )
    # texts replaced, lists merged without duplicates, an unverified quote left out
    assert creative.kit_positioning == "Smash burgers de autor en Táchira."
    assert creative.kit_audience == "Jóvenes de 18 a 30."
    assert creative.kit_do_examples == "¡Hola, vecino!\nPídela ya"
    assert creative.kit_banned_words == ""
    assert filled == ["Posicionamiento", "Audiencia", "Así sí habla la marca"]
    assert "¿Todo correcto?" in docs.filled_message(filled)


def test_identity_carries_the_brief_and_no_panel() -> None:
    rendered = str(wiz._step_identity())
    assert "brand_brief" in rendered  # the brief's upload id
    assert "Posicionamiento" in rendered and "Audiencia" in rendered
    assert "Aplicar" not in rendered  # no proposals panel


# -- ¿Todo correcto? holds the five lists, with their examples --------------------------------


def _js(text: str) -> str:
    """How the compiled component tree spells a Python string (non-ASCII escaped)."""
    import json

    return json.dumps(text)[1:-1]


def test_the_review_fills_the_five_lists_with_examples() -> None:
    rendered = str(wiz._step_confirm())
    for _field, _label, _hint, example, _empty in wiz._KIT_LISTS:
        assert _js(example) in rendered
    for section in ("Tu marca", "Cómo habla tu marca", "Lo que nunca debe decir"):
        assert _js(section) in rendered


def test_the_manual_flow_is_seven_screens_and_resumes_on_the_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert [t for t, _ in wiz.STEPS] == [
        "¿Quién es la marca?",
        "¿Tienes brandboard?",
        "Tu brandboard",
        "Tipografía",
        "Paleta de colores",
        "¿Todo correcto?",
        "Resultados e insights",
    ]
    state = wiz.BrandWizardState()
    creative = CreativeState()
    creative.kit_positioning, creative.kit_audience = "p", "a"
    creative.kit_palette = "#112233"
    state.has_logo = "no"
    state.logo_brief_1 = "minimalista"

    async def get_state(_self: Any, _cls: type) -> Any:
        return creative

    monkeypatch.setattr(wiz.BrandWizardState, "get_state", get_state)
    import asyncio

    asyncio.run(wiz.BrandWizardState.resume.fn(state))
    # no examples yet: they are filled on the review now, so that is where it opens
    assert state.step == wiz._CONFIRM_STEP


def test_the_editor_keeps_the_voice_and_drops_the_list_screens() -> None:
    from .brand_kit_editor import EDIT_STEPS

    titles = [t for t, _ in EDIT_STEPS]
    assert "Tu voz" in titles and "¿Cómo suena?" in titles
    assert "Enséñale a hablar" not in titles and "Lo que nunca debe decir" not in titles


# -- the city category ----------------------------------------------------------------------


def test_an_empty_city_category_is_shown_with_its_note() -> None:
    state = wiz.BrandConnectState()
    state.sector_accounts = [
        {"handle": "@a", "network": "TikTok", "key": "TikTok:@a", "followers": "1"}
    ]
    state.national_accounts = [
        {"handle": "@b", "network": "TikTok", "key": "TikTok:@b", "followers": "1"}
    ]
    state.local_title = "Referentes en Táchira"
    state.local_note = "No encontramos cuentas de Táchira para tu rubro todavía."
    state.sort_stage = 1  # national
    assert state.is_last_stage is False  # there IS a city category after it
    state.sort_stage = 2
    assert state.stage_key == "local" and "Táchira" in state.stage_note
    # a city never asked for (no city given) is still skipped
    state.local_note = "Indica tu ciudad para ver referentes locales."
    state.sort_stage = 1
    assert state.is_last_stage is True


# -- the profile read keeps the latest posts' texts ------------------------------------------


def test_the_post_pages_give_the_texts_the_hashtags_are_created_from() -> None:
    page = {
        "aweme_list": [
            {"desc": "  Doble smash   con cheddar #smashburger "},
            {"desc": ""},
            {"desc": "x" * 500},
        ]
    }
    captions = sc._page_captions("tiktok", page)
    assert captions[0] == "Doble smash con cheddar #smashburger"
    assert len(captions) == 2 and len(captions[1]) == sc.CAPTION_CHARS
    ig = {"items": [{"caption": {"text": "Arepas en Cúcuta"}}, {"caption": "bare string"}]}
    assert sc._page_captions("instagram", ig) == ["Arepas en Cúcuta", "bare string"]


def test_without_a_key_the_accounts_own_hashtags_stand_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
    account = wiz.from_profile.AccountText(
        handle="nibbles", bio="Smash burgers", used_hashtags=("fyp", "smashburger")
    )
    choice, note = wiz._create_hashtags(account)
    assert choice is not None and choice.tags == ("smashburger",) and note == ""
    nothing, note = wiz._create_hashtags(wiz.from_profile.AccountText())
    assert nothing is None and "rubro" in note


# -- Resultados e insights, redesigned (UI only) --------------------------------------------


def test_the_results_tabs_name_each_category_with_its_count() -> None:
    state = wiz.BrandConnectState()
    state.country_code = "VE"
    state.city = "San Cristóbal"
    state.sector_accounts = [{"handle": "@a", "network": "TikTok", "followers": "1"}] * 3
    state.local_note = "No encontramos cuentas de San Cristóbal para tu rubro todavía."
    state.discovering = True  # the national search is still running
    labels = dict(state.results_tabs)
    assert labels == {
        "sector": "Sector · 3",
        "national": "Venezuela · …",
        "local": "San Cristóbal · 0",
    }
    wiz.BrandConnectState.set_results_phase.fn(state, "local")
    assert state.results_phase == "local"
    wiz.BrandConnectState.set_results_phase.fn(state, "nope")
    assert state.results_phase == "local"


def test_the_results_screen_is_one_wide_header_tabs_and_a_card_grid() -> None:
    rendered = str(wiz._connect_step_insights())
    assert "RadixThemesSegmentedControl" in rendered  # the category tabs
    assert "q-clamp-2" in rendered  # compact cards with a two-line bio
    assert "34rem" not in rendered  # no narrow column any more
    assert wiz._RESULTS_COLUMN_MAX == "62rem"


async def test_mejorar_tu_perfil_goes_to_the_signup() -> None:
    from .auth_state import AuthState

    auth = AuthState()

    class Holder:
        async def get_state(self, _cls: type) -> Any:
            return auth

    assert await wiz._finish_route(Holder()) == "/signup"  # a pre-login draft
    auth.session_tenant_id = "00000000-0000-4000-8000-000000000001"
    assert await wiz._finish_route(Holder()) == "/"  # an account has nothing to sign up for


def test_the_login_has_a_way_to_the_brand_kit() -> None:
    from .auth_pages import login_index

    rendered = str(login_index())
    assert "/brand/start" in rendered and "Crear mi Brand Kit" in rendered


def test_answering_the_account_kind_fires_the_hashtag_creation() -> None:
    """Found live on 2026-10-05: the answer moved on through `next_step` but dropped the
    event it returned, so the hashtags were never created on the usual path."""
    state = wiz.BrandConnectState()
    state.step = wiz._ACCOUNT_KIND_STEP
    state.started_without_socials = True
    fired = wiz.BrandConnectState.answer_account_kind.fn(state, "marca")
    assert state.step == wiz._RUBRO_STEP and "suggest_hashtags" in str(fired)

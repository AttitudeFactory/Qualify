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
    for _field, _label, _hint, example in wiz._KIT_LISTS:
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

    state.brand_ready = True  # a card left from an earlier finish

    async def get_state(_self: Any, _cls: type) -> Any:
        return creative

    monkeypatch.setattr(wiz.BrandWizardState, "get_state", get_state)
    import asyncio

    asyncio.run(wiz.BrandWizardState.resume.fn(state))
    assert state.brand_ready is False  # m-24842965: entering opens the steps, not the card
    # no examples yet: they are filled on the review now, so that is where it opens
    assert state.step == wiz._CONFIRM_STEP


def test_the_editor_keeps_the_voice_and_the_lists_as_sections() -> None:
    from .brand_kit_editor import SECTIONS

    titles = [title for _key, title, _icon, _blurb in SECTIONS]
    assert "Voz y tono" in titles
    assert "Cómo habla" in titles and "Lo que nunca dice" in titles


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


def test_without_a_catalog_the_latest_posts_hashtags_come_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
    seed = wiz.creator_discovery.DiscoverySeed("nibbles", ())
    account = wiz.from_profile.AccountText(
        handle="nibbles", bio="Smash burgers", used_hashtags=("fyp", "smashburger")
    )
    choice, note = wiz._hashtags_db_first(None, seed, account)
    assert choice is not None and choice.tags == ("smashburger",) and note == ""
    nothing, note = wiz._hashtags_db_first(None, seed, wiz.from_profile.AccountText())
    assert nothing is None and "rubro" in note


# -- Resultados e insights, redesigned (UI only) --------------------------------------------


def test_the_results_are_one_list_without_country_or_city_tabs() -> None:
    """§ request 2026-10-06: "no quiero la separación entre el país… solo quiero la
    lista" — the sector, the country and the city in one grid, each account once."""
    state = wiz.BrandConnectState()
    state.sector_accounts = [{"handle": "@a", "network": "TikTok", "followers": "1"}]
    state.national_accounts = [
        {"handle": "@b", "network": "TikTok", "followers": "1"},
        {"handle": "@a", "network": "TikTok", "followers": "1"},  # already in the sector
    ]
    state.local_accounts = [{"handle": "@c", "network": "TikTok", "followers": "1"}]
    assert [a["handle"] for a in state.discovered_accounts] == ["@a", "@b", "@c"]
    assert not hasattr(wiz.BrandConnectState, "results_tabs")

    rendered = str(wiz._connect_step_insights())
    assert "RadixThemesSegmentedControl" not in rendered  # no category tabs
    assert "q-clamp-2" in rendered  # compact cards with a two-line bio
    assert "34rem" not in rendered  # no narrow column any more
    assert wiz._RESULTS_COLUMN_MAX == "62rem"


def test_an_empty_finished_search_says_why() -> None:
    state = wiz.BrandConnectState()
    state.discovery_ran = True
    assert state.results_note == "No encontramos referentes para tu rubro todavía."
    state.sector_note = "No pudimos buscar en el sector: inténtalo de nuevo."
    assert state.results_note.startswith("No pudimos")
    state.discovering = True
    assert state.results_note == ""


async def test_finishing_a_draft_goes_to_the_signup_and_an_account_sees_its_brand_ready() -> None:
    """m-24842965: a pre-login draft still goes on to the signup; an account no longer
    lands on `/` (Menciones) — it gets «Tu marca está lista», with no navigation."""
    from .auth_state import AuthState

    auth = AuthState()
    ready = wiz.BrandWizardState()

    class Holder:  # the connect flow's state, which reaches the wizard's through get_state
        async def get_state(self, cls: type) -> Any:
            return ready if cls is wiz.BrandWizardState else auth

    assert await wiz._finish_route(Holder()) == "/registro"  # a pre-login draft
    navigation = await wiz._finish_navigation(Holder())
    assert navigation is not None and "/registro" in str(navigation)
    assert ready.brand_ready is False

    auth.session_tenant_id = "00000000-0000-4000-8000-000000000001"
    assert await wiz._finish_route(Holder()) is None  # nothing to sign up for
    assert await wiz._finish_navigation(Holder()) is None  # no redirect to Menciones
    assert ready.brand_ready is True


def test_the_brand_ready_card_only_leaves_to_its_own_routes() -> None:
    ready = wiz.BrandWizardState()
    for route in ("/create", "/connections", "/brand/kit"):
        ready.brand_ready = True
        spec = wiz.BrandWizardState.leave_brand_ready.fn(ready, route)
        assert ready.brand_ready is False
        assert route in str(spec)
    # the route comes from the client: anything else falls back to the brand
    spec = wiz.BrandWizardState.leave_brand_ready.fn(ready, "https://example.com")
    assert "example.com" not in str(spec) and "/brand/kit" in str(spec)
    ready.brand_ready = True
    wiz.BrandWizardState.hide_brand_ready.fn(ready)
    assert ready.brand_ready is False


def test_the_brand_ready_card_says_it_in_the_owners_words() -> None:
    """The exact strings of m-24842965, the three ways out, ≥ 44 px targets (N12), and
    the old final button's text gone from both flows."""
    import inspect
    import json

    def js(text: str) -> str:  # the compiled JSX escapes «á» as «\\u00e1»
        return json.dumps(text)[1:-1]

    rendered = str(wiz._brand_ready_card())
    for text in (
        "Tu marca está lista",
        "Logo, colores y forma de hablar ya se usan en cada publicación.",
        "Crear mi primera publicación",
        "Conectar mi Instagram",
        "Ver mi marca",
    ):
        assert js(text) in rendered, text
    assert rendered.count("44px") == 3
    source = inspect.getsource(wiz)
    assert "Mejorar tu perfil" not in source
    assert "_APP_HOME_ROUTE" not in source
    assert "Terminar mi marca" in str(wiz._finish_button(wiz.BrandWizardState.finish))
    for page in (wiz.brand_manual_index, wiz.brand_connect_index):
        assert "_or_ready(" in inspect.getsource(page), page.__name__
        assert js("Tu marca está lista") in str(page()), page.__name__


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


# -- third round of 2026-10-05 ----------------------------------------------------------------


def test_network_and_username_are_one_screen() -> None:
    """ "Vamos a unificar el qué red usas y cuál es tu usuario": the field on top, the two
    networks as buttons under it — each one reads the profile, so there is no Continuar."""
    titles = [title for title, _ in wiz.CONNECT_STEPS]
    assert titles[wiz._ACCOUNT_STEP] == "Tu cuenta"
    assert "¿Qué red usas?" not in titles and "¿Cuál es tu usuario?" not in titles
    assert wiz._PROFILE_STEP == wiz._ACCOUNT_STEP + 1
    rendered = str(wiz._connect_step_account())
    assert rendered.index("Ej.: cafedelparque.cuc") < rendered.index("Instagram")
    assert rendered.index("Instagram") < rendered.index("TikTok")
    assert "Analizar" not in rendered


def test_a_network_button_reads_the_profile_on_that_network() -> None:
    state = wiz.BrandConnectState()
    state.username = "nibbles.burger"
    fired = wiz.BrandConnectState.analyze_on.fn(state, "tiktok")
    assert state.network == "tiktok" and "analyze" in str(fired)
    assert wiz.BrandConnectState.analyze_on.fn(state, "myspace") is None
    assert state.network == "tiktok"


def test_enter_without_a_network_asks_for_one() -> None:
    state = wiz.BrandConnectState()
    state.username = "nibbles.burger"
    assert wiz.BrandConnectState.submit_account.fn(state) is None
    assert state.error == wiz._NETWORK_REQUIRED
    state.network = "instagram"
    assert "analyze" in str(wiz.BrandConnectState.submit_account.fn(state))


def test_the_account_screen_has_no_forward_button() -> None:
    controls = str(wiz._connect_controls())
    assert "Analizar" not in controls


def test_the_identity_fields_hide_while_the_brief_is_read() -> None:
    """ "Al momento de cargar el subido del brief vamos a ocultar los inputs mientras
    carga": the fields sit behind `brief_busy`, and the card has no status line under it."""
    rendered = str(wiz._step_identity())
    assert "brief_busy" in rendered
    busy_at = rendered.index("brief_busy", rendered.index("Leyendo tu brief"))
    assert busy_at < rendered.index("Posicionamiento")
    assert "brief_message" not in str(docs.brief_upload_card())


def test_a_document_result_is_a_toast_in_its_tone() -> None:
    assert docs.notify("", "ok") is None
    for tone, kind in (("ok", "success"), ("error", "error"), ("warn", "warning"), ("x", "info")):
        assert kind in str(docs.notify("Rellenamos desde tu brief: Audiencia.", tone))


def test_the_ranking_makes_room_while_a_card_is_held() -> None:
    """ "Hay un pequeño delay al momento de cambiar de posición": the other cards slide out
    of the way during the drag, and the drop is only sent once the card has settled, so
    the server's re-render lands under a screen that already shows the new order."""
    from pathlib import Path

    script = (Path(__file__).parent.parent / "assets" / "rank-drag.js").read_text(encoding="utf-8")
    assert "function makeRoom" in script and "q-shifting" in script
    assert "function clearWhenReordered" in script
    assert "FLIP_MS" not in script  # no slide AFTER the round trip any more
    # the ranking rules live in the Brand Kit sheet since the Liquid Glass split (D10)
    sheet = Path(__file__).parent.parent / "assets" / "qualify-brand.css"
    css = sheet.read_text(encoding="utf-8")
    assert ".q-rank-card.q-shifting" in css


# -- Tu rubro: autocompleted, catalog first (third round of 2026-10-05) ------------------------


def test_there_is_no_suggest_button_and_leaving_the_rubro_reruns_the_search() -> None:
    from . import brand_kit_editor  # noqa: F401 — every page still builds

    rendered = str(wiz._rubro_fields())
    assert "Sugerir" not in rendered
    assert not hasattr(wiz, "_suggest_hashtags_button")
    state = wiz.BrandConnectState()
    state.hashtags_rubro = "hamburguesería smash"
    assert wiz.BrandConnectState.rubro_input_blur.fn(state, "hamburguesería smash ") is None
    assert wiz.BrandConnectState.rubro_input_blur.fn(state, "") is None
    fired = wiz.BrandConnectState.rubro_input_blur.fn(state, "food truck de hamburguesas")
    assert "suggest_hashtags" in str(fired) and state.rubro_text == "food truck de hamburguesas"


def test_a_creator_changing_category_reruns_the_search() -> None:
    state = wiz.BrandConnectState()
    state.step = wiz._RUBRO_STEP
    state.account_kind = "influencer"
    assert "suggest_hashtags" in str(wiz.BrandConnectState.set_sector.fn(state, "food_drink"))
    assert wiz.BrandConnectState.set_sector.fn(state, "food_drink") is None  # same one
    brand = wiz.BrandConnectState()
    brand.step = wiz._RUBRO_STEP
    brand.account_kind = "marca"
    assert wiz.BrandConnectState.set_sector.fn(brand, "food_drink") is None


def test_without_claude_the_rubro_is_the_profiles_category(monkeypatch) -> None:
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
    account = wiz.from_profile.AccountText(handle="nibbles", category="Restaurante")
    assert wiz._propose_rubro(account) == ("restaurante", None)
    assert wiz._propose_rubro(wiz.from_profile.AccountText()) == ("", None)


def test_the_catalog_answers_first_and_a_creation_is_stored(monkeypatch) -> None:
    from uuid import UUID

    from qualify_api.hashtags import MemoryHashtagRepository

    from . import hashtag_catalog

    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(hashtag_catalog, "REPOSITORY", MemoryHashtagRepository())
    monkeypatch.setattr(hashtag_catalog, "_seeded", False)
    tenant = UUID("7a7a0000-0000-4000-8000-0000000000c9")
    seed = wiz.creator_discovery.DiscoverySeed("nibbles", (), (), "VE", "", terms=("xilofonos",))
    account = wiz.from_profile.AccountText(handle="nibbles", bio="Xilófonos hechos a mano")
    created = wiz.from_profile.Proposal(
        (wiz.from_profile.ProposedTag("xilofonosamano", "La bio."),), None, "ai", "m", "xilofonos"
    )
    # nothing in the catalog for that rubro: the created tags are used, and stored
    choice, note = wiz._hashtags_db_first(tenant, seed, account, created=created)
    assert choice is not None and choice.tags == ("xilofonosamano",) and note == ""
    assert hashtag_catalog.REPOSITORY.get(tenant, "xilofonosamano") is not None
    # the next search for that rubro finds them in the catalog — no creation
    again, _ = wiz._hashtags_db_first(tenant, seed, account)
    assert again is not None and again.tags == ("xilofonosamano",) and again.by == "rule"


def test_the_three_cases_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """§ fourth round of 2026-10-05: 1) the database, 2) the latest posts, 3) created from
    the description and the posts — each only when the one before has nothing."""
    from uuid import UUID

    from qualify_api.hashtags import MemoryHashtagRepository

    from . import hashtag_catalog

    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(hashtag_catalog, "REPOSITORY", MemoryHashtagRepository())
    monkeypatch.setattr(hashtag_catalog, "_seeded", False)
    tenant = UUID("7a7a0000-0000-4000-8000-0000000000ca")
    seed = wiz.creator_discovery.DiscoverySeed("nibbles", (), (), "VE", "", terms=("xilofonos",))
    created = wiz.from_profile.Proposal(
        (wiz.from_profile.ProposedTag("xilofonosamano", "La bio."),), None, "ai", "m", "xilofonos"
    )
    posts = wiz.from_profile.AccountText(handle="nibbles", used_hashtags=("fyp", "marimba"))
    # 2. nothing in the database → the posts' own hashtags, nothing created or stored
    choice, _ = wiz._hashtags_db_first(tenant, seed, posts, created=created)
    assert choice is not None and choice.tags == ("marimba",)
    assert hashtag_catalog.REPOSITORY.get(tenant, "xilofonosamano") is None
    # 3. no hashtags in the posts either → created, and stored in the database
    bare = wiz.from_profile.AccountText(handle="nibbles", bio="Xilófonos hechos a mano")
    choice, _ = wiz._hashtags_db_first(tenant, seed, bare, created=created)
    assert choice is not None and choice.tags == ("xilofonosamano",) and choice.by == "ai"
    # 1. the next search for that rubro finds them in the database first
    choice, _ = wiz._hashtags_db_first(tenant, seed, posts)
    assert choice is not None and choice.tags == ("xilofonosamano",) and choice.by == "rule"

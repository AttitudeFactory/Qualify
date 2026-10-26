"""Inicio (m-24842962, NAV-4): view models, routing and the filtered destinations."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from qualify_api.home import HomeCounts

from .conversations_vm import FILTER_PENDING, filter_from_param
from .home_vm import (
    BRAND_STEP_LABEL,
    BRAND_URL,
    COMMENTS_URL,
    CONNECTIONS_URL,
    CONVERSATIONS_PENDING_URL,
    CONVERSATIONS_URL,
    CREATE_URL,
    DRAFTS_TO_APPROVE_URL,
    MENTIONS_URL,
    WHATSAPP_CHATS_URL,
    build_home_vm,
    comments_unanswered_label,
    drafts_to_approve_label,
    first_steps_progress_label,
    people_waiting_label,
)
from .planner_vm import gallery_filter_from_param
from .ui.layout import NAV_ITEMS

_HERE = Path(__file__).parent

_SET_UP = {"instagram_connected": True, "has_publication": True}


def test_zero_data_is_never_empty_first_steps_show() -> None:
    vm = build_home_vm(HomeCounts())
    assert vm.today == []
    assert [s.href for s in vm.first_steps] == [CONNECTIONS_URL, CREATE_URL]
    assert vm.first_steps[0].label == "Conecta tu Instagram para publicar desde aquí"
    assert vm.first_steps[1].label == "Crea tu primera publicación con la foto de un producto"
    assert not any(s.done for s in vm.first_steps)
    assert vm.first_steps_pending
    assert vm.first_steps_progress == "Llevas 0 de 2"
    assert not vm.all_clear
    assert vm.week_needs_connection
    assert not vm.week_quiet


def test_a_done_step_stays_with_its_check() -> None:
    connected = build_home_vm(HomeCounts(instagram_connected=True))
    assert [(s.key, s.done) for s in connected.first_steps] == [
        ("connect", True),
        ("create", False),
    ]
    assert connected.first_steps[0].label == "Conectaste tu Instagram"
    assert connected.first_steps_progress == "Llevas 1 de 2"
    created = build_home_vm(HomeCounts(has_publication=True))
    assert created.first_steps[1].label == "Creaste tu primera publicación"
    assert [s.done for s in created.first_steps] == [False, True]


def test_an_unfinished_brand_is_the_first_thing_to_finish() -> None:
    """PASOS-4 (m-24852243, N2): «Seguir después» on Tu marca lands on Inicio, which
    shows what was left halfway, first, as a link back to it."""
    vm = build_home_vm(HomeCounts(**_SET_UP), brand_done=False)
    assert [(s.key, s.href, s.done) for s in vm.first_steps][0] == ("brand", BRAND_URL, False)
    assert vm.first_steps[0].label == BRAND_STEP_LABEL
    assert vm.first_steps_pending and not vm.all_clear
    assert vm.first_steps_progress == "Llevas 2 de 3"
    assert all(s.key != "brand" for s in build_home_vm(HomeCounts()).first_steps)
    said = build_home_vm(
        HomeCounts(), brand_done=False, brand_label="Termina tu marca: te falta tu logo"
    )
    assert said.first_steps[0].label == "Termina tu marca: te falta tu logo"


def test_nothing_pending_and_set_up_is_all_clear() -> None:
    vm = build_home_vm(HomeCounts(**_SET_UP))
    assert not vm.first_steps_pending  # the block hides once every step is done
    assert vm.all_clear
    assert not vm.week_needs_connection
    assert vm.week_quiet  # connected and a quiet week: a way out, not three zeros


def test_progress_label() -> None:
    assert first_steps_progress_label(1, 2) == "Llevas 1 de 2"


def test_today_shows_only_what_waits_and_links_filtered() -> None:
    vm = build_home_vm(HomeCounts(people_waiting=2, comments_unanswered=5, **_SET_UP))
    assert [(c.label, c.href) for c in vm.today] == [
        ("2 personas esperan tu respuesta", CONVERSATIONS_PENDING_URL),
        ("5 comentarios de esta semana sin responder", COMMENTS_URL),
    ]
    assert not vm.all_clear


def test_today_has_at_most_three_cards_in_order() -> None:
    vm = build_home_vm(
        HomeCounts(people_waiting=1, drafts_to_approve=3, comments_unanswered=1, **_SET_UP)
    )
    assert [c.href for c in vm.today] == [
        CONVERSATIONS_PENDING_URL,
        DRAFTS_TO_APPROVE_URL,
        COMMENTS_URL,
    ]


@pytest.mark.parametrize(
    ("fn", "one", "many"),
    [
        (people_waiting_label, "1 persona espera tu respuesta", "3 personas esperan tu respuesta"),
        (
            drafts_to_approve_label,
            "1 publicación espera tu revisión",
            "3 publicaciones esperan tu revisión",
        ),
        (
            comments_unanswered_label,
            "1 comentario de esta semana sin responder",
            "3 comentarios de esta semana sin responder",
        ),
    ],
)
def test_labels_agree_in_number(fn, one: str, many: str) -> None:
    assert fn(1) == one
    assert fn(3) == many


def test_week_figures_link_to_their_detail() -> None:
    vm = build_home_vm(
        HomeCounts(
            messages_week_dm=4,
            messages_week_whatsapp=1,
            comments_week=7,
            mentions_week=2,
            **_SET_UP,
        )
    )
    assert [(s.label, s.value, s.href) for s in vm.week] == [
        ("Te escribieron", 5, CONVERSATIONS_URL),
        ("Comentaron", 7, COMMENTS_URL),
        ("Hablaron de ti", 2, MENTIONS_URL),
    ]
    assert vm.week[0].hint == "4 por Instagram · 1 por WhatsApp"
    assert not vm.week_quiet


def test_messages_always_open_conversations() -> None:
    vm = build_home_vm(HomeCounts(messages_week_dm=1, messages_week_whatsapp=6))
    assert vm.week[0].href == CONVERSATIONS_URL != WHATSAPP_CHATS_URL
    # Data from WhatsApp alone is something to show, even without Instagram.
    assert not vm.week_needs_connection
    assert not vm.week_quiet


def test_drafts_to_review_follows_the_gallery_rule() -> None:
    from uuid import uuid4

    from qualify_api.planner.post_reader import ApprovalStatus, PostSummary

    from .home_provider import count_needs_review

    def post(approval: ApprovalStatus, publishable: bool) -> PostSummary:
        return PostSummary(
            post_id=uuid4(),
            brand_id=uuid4(),
            title="x",
            approval=approval,
            lifecycle_status="generated",
            is_publishable=publishable,
        )

    posts = [
        post(ApprovalStatus.PENDING, False),  # waits for review → Por completar
        post(ApprovalStatus.APPROVED, False),  # approved but cannot go out → Por completar
        post(ApprovalStatus.APPROVED, True),  # Listo
        post(ApprovalStatus.REJECTED, False),  # Desechado
    ]
    assert count_needs_review(posts) == 2


def test_session_lost_offers_login_not_retry() -> None:
    page = (_HERE / "home_page.py").read_text(encoding="utf-8")
    state = (_HERE / "home_state.py").read_text(encoding="utf-8")
    assert "Tu sesión se cerró. Entra de nuevo para ver tu resumen." in state
    assert '"Iniciar sesión", "log-in", "/login"' in page
    assert "aria_label=" not in page  # the visible text, figure included, names each link


def test_destination_filters_are_read_by_the_lists() -> None:
    assert CONVERSATIONS_PENDING_URL.endswith("filtro=pendientes")
    assert filter_from_param("pendientes") == FILTER_PENDING
    assert filter_from_param("") is None and filter_from_param("xx") is None
    assert DRAFTS_TO_APPROVE_URL.endswith("estado=por-completar")
    assert gallery_filter_from_param("por-completar") == "needs_action"
    assert gallery_filter_from_param("") is None and gallery_filter_from_param("xx") is None


def _routes() -> dict[str, tuple[str, str]]:
    """route → (page function, title) of every `app.add_page(...)` in Qualify.py."""
    tree = ast.parse((_HERE / "Qualify.py").read_text(encoding="utf-8"))
    found: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_page":
            kw = {k.arg: k.value for k in node.keywords}
            route = kw.get("route")
            title = kw.get("title")
            page = node.args[0]
            if isinstance(route, ast.Constant) and isinstance(title, ast.Constant):
                found[route.value] = (getattr(page, "id", ""), title.value)
    return found


def test_root_is_inicio_and_mentions_live_in_resultados() -> None:
    routes = _routes()
    assert routes["/"] == ("home_index", "Qualify · Inicio")
    # m-24843003: «Hablaron de ti» opens Resultados › «Quién habla de ti».
    assert MENTIONS_URL == "/resultados?tab=menciones"
    assert routes["/resultados"] == ("results_index", "Qualify · Resultados")


def test_menu_has_inicio_on_top_and_mentions_off_root() -> None:
    assert NAV_ITEMS[0] == ("Inicio", "house", "/", True)
    assert not [label for label, *_ in NAV_ITEMS if label == "Menciones"]


def test_login_lands_on_inicio() -> None:
    source = (_HERE / "auth_state.py").read_text(encoding="utf-8")
    assert 'return rx.redirect("/")' in source


_ENGLISH = ("post", "feed", "dashboard", "engagement", "lead", "inbox", "Brand Kit")


def test_home_copy_has_no_english() -> None:
    strings = [
        node.value
        for name in ("home_page.py", "home_vm.py", "home_state.py")
        for node in ast.walk(ast.parse((_HERE / name).read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and " " in node.value
    ]
    for text in strings:
        if text.lstrip().startswith(("Inicio (", "State for", "Inicio's", "The ", "A ", "`")):
            continue  # docstrings and comments in English, by convention
        for word in _ENGLISH:
            assert word.lower() not in text.lower().split(), (word, text)


def test_videos_about_to_expire_show_on_today_and_open_por_aprobar() -> None:
    """Founder 2026-10-24: from 2 days before a vista previa expires, Inicio says so and
    links to «Por aprobar» filtered."""
    from .home_vm import videos_expiring_label

    assert videos_expiring_label(1) == "1 video vence pronto"
    assert videos_expiring_label(3) == "3 videos vencen pronto"
    from urllib.parse import parse_qs, urlparse

    from .home_vm import VIDEOS_EXPIRING_URL
    from .planner_vm import GALLERY_ORDER_EXPIRY, GALLERY_ORDER_PARAM

    vm = build_home_vm(HomeCounts(videos_expiring_soon=2, **_SET_UP))
    (card,) = vm.today
    assert (card.key, card.label, card.href) == (
        "expiring",
        "2 videos vencen pronto",
        VIDEOS_EXPIRING_URL,
    )
    # Por aprobar › Por completar, with every piece, sorted by expiry
    query = parse_qs(urlparse(VIDEOS_EXPIRING_URL).query)
    assert urlparse(VIDEOS_EXPIRING_URL).path == urlparse(DRAFTS_TO_APPROVE_URL).path
    assert gallery_filter_from_param(query["estado"][0]) == "needs_action"
    assert query[GALLERY_ORDER_PARAM] == [GALLERY_ORDER_EXPIRY]


def test_por_aprobar_sorted_by_expiry_puts_the_soonest_first_then_the_usual_order() -> None:
    from .gallery_state import sort_for_gallery
    from .planner_vm import build_post_option

    def post(pid: str, state: str, expires: float = 0.0):  # noqa: ANN202
        return build_post_option(
            post_id=pid,
            title=pid,
            caption_excerpt="",
            thumbnail_url=None,
            category="reels",
            approval="pending",
            detail_href=f"/drafts/{pid}",
            is_publishable=False,
            unpublishable_reason="",
            gallery_state=state,
            lifecycle_status="generated",
            expires_at=expires,
        )

    posts = [
        post("ready", "schedulable"),
        post("late", "needs_action", 3000.0),
        post("plain", "needs_action"),
        post("soon", "needs_action", 1000.0),
    ]
    assert [p.post_id for p in sort_for_gallery(posts)] == ["ready", "late", "plain", "soon"]
    assert [p.post_id for p in sort_for_gallery(posts, by_expiry=True)] == [
        "soon",
        "late",
        "ready",
        "plain",
    ]
    assert all(c.key != "expiring" for c in build_home_vm(HomeCounts(**_SET_UP)).today)

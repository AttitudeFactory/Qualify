"""m-24842963 (NAV-6, N11): the menu's pending counters and the tab's «(N)».

Offline: the pure rules (`pending_vm`), the throttle, the provider seam, and that the
menu, the logout and every counting action are wired to the counter.
"""

from __future__ import annotations

import inspect
import re
from uuid import uuid4

import pytest
from qualify_api.attention import PendingCounts
from qualify_api.creative import fsm as draft_fsm
from qualify_api.planner.post_reader import ApprovalStatus, PostSummary

from Qualify import pending_provider
from Qualify.pending_state import ATTENTION_TTL_S, PUBLICATIONS_TTL_S, PendingState, due
from Qualify.pending_vm import (
    BADGE_CAP,
    MenuCounts,
    badge_text,
    clamp,
    count_to_approve,
    entry_aria_label,
    more_button_aria_label,
    title_prefix,
    title_script,
    titled,
)
from Qualify.ui import layout

# -- the badge ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "text"),
    [(0, ""), (-3, ""), (1, "1"), (12, "12"), (BADGE_CAP, "99"), (BADGE_CAP + 1, "99+")],
)
def test_badge_shows_nothing_at_zero_and_caps_long_numbers(count: int, text: str) -> None:
    assert badge_text(count) == text


def test_unreadable_counts_read_as_zero() -> None:
    assert clamp(None) == 0
    assert clamp("x") == 0
    assert clamp("4") == 4


def test_the_total_counts_whatsapp_once() -> None:
    # WhatsApp chats are already inside «Por responder» (ATENDER-1's single count).
    counts = MenuCounts(respond=5, whatsapp=2, approve=3, schedule=1)
    assert counts.total == 9
    assert MenuCounts().total == 0


# -- the tab title --------------------------------------------------------------------


def test_title_starts_with_the_count_when_something_waits() -> None:
    assert titled("Qualify · Por aprobar", 3) == "(3) Qualify · Por aprobar"
    assert titled("Qualify · Por aprobar", 0) == "Qualify · Por aprobar"
    assert title_prefix(150) == "(99+) "


def test_title_never_stacks_two_prefixes() -> None:
    assert titled("(3) Qualify · Tu semana", 5) == "(5) Qualify · Tu semana"
    assert titled("(99+) Qualify · Tu semana", 0) == "Qualify · Tu semana"
    # A title that merely starts with a parenthesis is left alone.
    assert titled("(Borrador) Qualify", 0) == "(Borrador) Qualify"


def test_title_script_carries_only_an_int() -> None:
    script = title_script(7)
    assert script.rstrip().endswith("})(7);")
    assert "document.title" in script and "MutationObserver" in script
    assert title_script(-2).rstrip().endswith("})(0);")
    # The browser regex strips the same prefix `titled` strips.
    assert "/^\\(\\d+\\+?\\) /" in script


# -- what «Por aprobar» counts ----------------------------------------------------------


def _post(approval: ApprovalStatus, *, publishable: bool = True, failed: bool = False):
    return PostSummary(
        post_id=uuid4(),
        brand_id=uuid4(),
        title="x",
        approval=approval,
        is_publishable=publishable,
        lifecycle_status=draft_fsm.FAILED if failed else "",
    )


def test_por_aprobar_counts_only_publications_waiting_for_approval() -> None:
    posts = [
        _post(ApprovalStatus.PENDING),
        _post(ApprovalStatus.PENDING, publishable=False),
        _post(ApprovalStatus.APPROVED, publishable=False),  # approved: not the owner's turn
        _post(ApprovalStatus.APPROVED),
        _post(ApprovalStatus.NOT_READY),
        _post(ApprovalStatus.REJECTED),
        _post(ApprovalStatus.PENDING, failed=True),  # generation failed → discarded
    ]
    assert count_to_approve(posts) == 2


# -- the provider ---------------------------------------------------------------------


def test_no_brand_means_nothing_to_approve_or_schedule(monkeypatch) -> None:
    monkeypatch.setattr(pending_provider, "default_brand_id", lambda _t: None)
    called: list[str] = []
    monkeypatch.setattr(
        pending_provider, "production_planner_service", lambda: called.append("svc")
    )
    assert pending_provider.read_publications(uuid4()) == pending_provider.PublicationCounts()
    assert called == []


def test_publication_counts_come_from_the_planner(monkeypatch) -> None:
    tenant, brand = uuid4(), uuid4()

    class _Service:
        def list_posts(self, *, tenant_id, brand_id):
            assert (tenant_id, brand_id) == (tenant, brand)
            return [_post(ApprovalStatus.PENDING), _post(ApprovalStatus.APPROVED)]

        def list_unscheduled(self, *, tenant_id, brand_id):
            assert (tenant_id, brand_id) == (tenant, brand)
            return ["a", "b", "c"]

    monkeypatch.setattr(pending_provider, "default_brand_id", lambda _t: brand)
    monkeypatch.setattr(pending_provider, "production_planner_service", _Service)
    counts = pending_provider.read_publications(tenant)
    assert (counts.approve, counts.schedule) == (1, 3)


def test_who_waits_is_atender_ones_single_count(monkeypatch) -> None:
    tenant = uuid4()
    seen: list = []

    def fake(tenant_id):
        seen.append(tenant_id)
        return PendingCounts(messages=1, whatsapp=2)

    monkeypatch.setattr(pending_provider, "pending_counts", fake)
    assert pending_provider.read_attention(tenant).total == 3
    assert seen == [tenant]


# -- the throttle ---------------------------------------------------------------------


def test_a_count_is_read_when_due_or_forced() -> None:
    now = 1_000.0
    assert due(0.0, ATTENTION_TTL_S, now, force=False)  # never read
    assert not due(now - 5, ATTENTION_TTL_S, now, force=False)
    assert due(now - ATTENTION_TTL_S, ATTENTION_TTL_S, now, force=False)
    assert due(now - 1, PUBLICATIONS_TTL_S, now, force=True)  # after an action


def test_bookkeeping_stays_on_the_server() -> None:
    sent_to_browser = set(PendingState.vars)
    assert {"respond", "whatsapp", "approve", "schedule"} <= sent_to_browser
    assert not {"_attention_at", "_publications_at", "_busy_since", "_again"} & sent_to_browser


# -- the menu -------------------------------------------------------------------------


def test_each_counted_entry_is_a_real_menu_entry() -> None:
    labels = {label for label, _icon, _route, enabled in layout.NAV_ITEMS if enabled}
    assert set(layout.NAV_COUNTERS) == {"Por responder", "WhatsApp", "Por aprobar", "Tu semana"}
    assert set(layout.NAV_COUNTERS) <= labels


def test_counted_entry_renders_a_warn_badge_only_above_zero() -> None:
    assert layout._count_badge("Tus productos") is None
    rendered = str(layout._count_badge("Por aprobar").render())
    assert "approve_badge" in rendered
    assert "cond_state" in rendered  # nothing rendered when the badge text is empty


def test_the_rail_refreshes_on_every_screen_and_on_a_heartbeat() -> None:
    rail = layout.sidebar()
    assert "on_shell_mount" in str(rail.event_triggers["on_mount"])
    assert "pending_state.tick" in str(rail.render())


# -- wiring: logout and every action that changes a count -----------------------------


def test_logout_resets_the_counts() -> None:
    from Qualify.auth_state import AuthState

    source = inspect.getsource(AuthState.logout.fn)
    assert re.search(r"\bPendingState,", source)


@pytest.mark.parametrize(
    ("module", "state", "handlers"),
    [
        ("Qualify.conversations_state", "ConversationsState", ["send_reply"]),
        ("Qualify.replies_state", "RepliesState", ["_decide_and_send", "discard_draft"]),
        ("Qualify.followups_state", "FollowupsState", ["approve", "discard"]),
        ("Qualify.whatsapp_chats_state", "WhatsAppChatsState", ["_send"]),
        ("Qualify.gallery_state", "GalleryState", ["quick_approve", "confirm_reject_post"]),
        ("Qualify.creative_state", "CreativeState", ["approve_selected", "reject_current"]),
        ("Qualify.conversations_state", "ConversationsState", ["load_conversation"]),
        ("Qualify.planner_state", "PlannerState", ["submit_form", "confirm_cancel"]),
    ],
)
def test_counting_actions_refresh_the_menu(module: str, state: str, handlers: list[str]) -> None:
    import importlib

    cls = getattr(importlib.import_module(module), state)
    for name in handlers:
        member = cls.__dict__.get(name) or getattr(cls, name)
        fn = getattr(member, "fn", member)
        assert "PendingState.refresh_now" in inspect.getsource(fn), f"{state}.{name}"


# -- UX review (m-24842963): the number never goes alone, and the phone sees it ---------


@pytest.mark.parametrize(
    ("label", "count", "spoken"),
    [
        ("Por responder", 0, "Por responder"),
        ("Por responder", 1, "Por responder: 1 persona espera tu respuesta"),
        ("Por responder", 3, "Por responder: 3 personas esperan tu respuesta"),
        ("WhatsApp", 1, "WhatsApp: 1 chat sin responder"),
        ("WhatsApp", 2, "WhatsApp: 2 chats sin responder"),
        ("Por aprobar", 1, "Por aprobar: 1 publicación espera tu aprobación"),
        ("Por aprobar", 4, "Por aprobar: 4 publicaciones esperan tu aprobación"),
        ("Tu semana", 1, "Tu semana: 1 publicación aprobada sin día"),
        ("Tu semana", 2, "Tu semana: 2 publicaciones aprobadas sin día"),
        ("Tu semana", 150, "Tu semana: 99+ publicaciones aprobadas sin día"),
        ("Tus productos", 5, "Tus productos"),
    ],
)
def test_each_count_is_spoken_with_what_it_counts(label: str, count: int, spoken: str) -> None:
    assert entry_aria_label(label, count) == spoken


def test_the_phone_more_button_says_how_much_waits_inside() -> None:
    # m-24842964 (NAV-7): «Más» on the bottom bar replaced the ☰ button; it counts
    # only what waits behind the drawer (WhatsApp + Por aprobar).
    assert more_button_aria_label(0) == "Más: abrir el menú"
    assert more_button_aria_label(1) == "Más: abrir el menú. 1 cosa te espera"
    assert more_button_aria_label(5) == "Más: abrir el menú. 5 cosas te esperan"
    assert MenuCounts(respond=4, whatsapp=1, approve=2, schedule=3).more == 3
    assert MenuCounts(whatsapp=1).more_is_urgent
    assert not MenuCounts(approve=2).more_is_urgent
    rendered = str(layout._bottom_bar().render())
    assert "more_badge" in rendered and "more_aria" in rendered
    assert "q-menu-count" in rendered


def test_only_people_waiting_are_shown_in_the_warning_tone() -> None:
    tones = {label: tone for label, (_text, tone, _aria) in layout.NAV_COUNTERS.items()}
    assert tones == {
        "Por responder": "warn",
        "WhatsApp": "warn",
        "Por aprobar": "neutral",
        "Tu semana": "neutral",
    }


def test_counted_entries_carry_their_spoken_name() -> None:
    rendered = str(layout._nav_item("Por aprobar", "check", "/gallery", True).render())
    assert "approve_aria" in rendered
    plain = str(layout._nav_item("Tus productos", "package", "/catalog", True).render())
    assert "_aria" not in plain

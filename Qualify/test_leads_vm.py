"""m-24842992: «Clientes interesados» — write by WhatsApp from the list and know who was
already written to. Offline: pure view model, the state's list helpers and the render."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from . import leads_vm
from .leads_page import _empty_state, _lead_card, _leads_list
from .leads_provider import LeadVM
from .leads_state import LeadsState, replace_lead, with_contacted

_BOGOTA = ZoneInfo("America/Bogota")


def _lead(lead_id: str = "a", *, contacted: bool = False) -> LeadVM:
    return LeadVM(
        id=lead_id,
        full_name="Ana Pérez",
        whatsapp_phone="+573001112233",
        wa_href=leads_vm.wa_href("+573001112233"),
        interest="Shawarma",
        source="instagram",
        extra_summary="",
        registered_at="Te dejó sus datos el 14 ago.",
        contacted=contacted,
        status_label=leads_vm.CONTACTED_LABEL if contacted else leads_vm.PENDING_LABEL,
        status_tone=leads_vm.CONTACTED_TONE if contacted else leads_vm.PENDING_TONE,
        contacted_note="Le escribiste el 23 oct." if contacted else "",
    )


# --- view model ----------------------------------------------------------------------


def test_wa_href_drops_the_plus() -> None:
    assert leads_vm.wa_href("+573001112233") == "https://wa.me/573001112233"


def test_pending_and_contacted_are_words_with_a_tone() -> None:
    assert leads_vm.contact_label(None) == "Pendiente"
    assert leads_vm.contact_tone(None) == "warn"
    when = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)
    assert leads_vm.contact_label(when) == "Ya le escribiste"
    assert leads_vm.contact_tone(when) == "ok"


def test_contacted_note_uses_the_business_zone() -> None:
    # 02:00 UTC on the 24th is still the 23rd in Bogotá.
    when = datetime(2026, 10, 24, 2, 0, tzinfo=UTC)
    assert leads_vm.contacted_note(when, _BOGOTA) == "Le escribiste el 23 oct."
    assert leads_vm.contacted_note(None, _BOGOTA) == ""


def test_registered_label_and_extra_summary() -> None:
    when = datetime(2026, 8, 14, 18, 3, tzinfo=UTC)
    assert leads_vm.registered_label(when, _BOGOTA) == "Te dejó sus datos el 14 ago."
    assert leads_vm.extra_summary({"turno": "tarde", "zona": "oeste"}) == (
        "turno: tarde · zona: oeste"
    )


def test_zone_for_falls_back_to_utc() -> None:
    assert leads_vm.zone_for("No/Existe") == ZoneInfo("UTC")
    assert leads_vm.zone_for(None) == ZoneInfo("UTC")


def test_form_url_only_when_there_is_a_real_form() -> None:
    template = "https://qualify.la/interes?e={tenant_id}"
    assert leads_vm.form_url(template, "t-1", form_active=True) == (
        "https://qualify.la/interes?e=t-1"
    )
    assert leads_vm.form_url(template, "t-1", form_active=False) == ""
    assert leads_vm.form_url("", "t-1", form_active=True) == ""
    assert leads_vm.form_url("https://qualify.la/interes", "t-1", form_active=True) == ""


def test_empty_copy_matches_the_ticket() -> None:
    assert leads_vm.EMPTY_TITLE == "Todavía no hay interesados"
    assert leads_vm.empty_description("https://x") == (
        "Comparte este enlace en tu perfil o en tus historias para que te dejen sus datos."
    )
    assert leads_vm.empty_description("") == leads_vm.EMPTY_NO_LINK


def test_no_copy_says_qualify_sends_on_its_own() -> None:
    texts = [v for k, v in vars(leads_vm).items() if k.isupper() and isinstance(v, str)]
    joined = " ".join(texts).lower()
    for word in ("enviamos", "automátic", "le enviaremos", "qualify envía"):
        assert word not in joined


# --- state helpers -------------------------------------------------------------------


def test_with_contacted_flips_only_that_card_with_its_words() -> None:
    leads = [_lead("a"), _lead("b")]
    flipped = with_contacted(leads, "b", contacted=True)
    assert flipped[0] == leads[0]
    assert flipped[1].contacted is True
    assert flipped[1].status_label == "Ya le escribiste"
    back = with_contacted(flipped, "b", contacted=False)
    assert back[1].status_label == "Pendiente"
    assert back[1].contacted_note == ""


def test_replace_lead_keeps_the_order() -> None:
    leads = [_lead("a"), _lead("b"), _lead("c")]
    updated = _lead("b", contacted=True)
    assert [lead.id for lead in replace_lead(leads, updated)] == ["a", "b", "c"]
    assert replace_lead(leads, updated)[1] is updated


# --- render --------------------------------------------------------------------------


def test_the_list_is_cards_not_a_table() -> None:
    rendered = str(_leads_list().render())
    assert "RadixThemesTable" not in rendered
    assert "overflow_x" not in rendered


def test_each_card_has_a_44px_whatsapp_button_and_a_word_state() -> None:
    rendered = str(_lead_card(LeadsState.leads[0]).render())
    assert "Escribirle por WhatsApp" in rendered
    assert leads_vm.WRITE_LABEL.endswith("↗")  # N9: leaving Qualify is announced
    assert "44px" in rendered
    assert "Pendiente" in rendered
    assert "Ya le escribiste" in rendered
    assert "Marcar como pendiente" in rendered
    assert "mark_contacted" in rendered


def test_empty_state_offers_copy_link() -> None:
    rendered = str(_empty_state().render())
    assert "Copiar enlace" in rendered
    assert "Comparte este enlace" in rendered


# --- UX review (applied) -------------------------------------------------------------


def test_dates_carry_the_year_only_outside_the_current_year() -> None:
    now = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)
    last_year = datetime(2025, 8, 14, 18, 3, tzinfo=UTC)
    assert leads_vm.registered_label(last_year, _BOGOTA, now=now) == (
        "Te dejó sus datos el 14 ago. de 2025"
    )
    assert leads_vm.contacted_note(datetime(2025, 11, 3, 15, tzinfo=UTC), _BOGOTA, now=now) == (
        "Le escribiste el 3 nov. de 2025"
    )
    this_year = datetime(2026, 8, 14, 18, 3, tzinfo=UTC)
    assert leads_vm.registered_label(this_year, _BOGOTA, now=now) == (
        "Te dejó sus datos el 14 ago."
    )
    # The year boundary follows the business's zone: 03:00 UTC on 1 Jan 2027 is still
    # 31 Dec 2026 in Bogotá, the current year there.
    new_year_utc = datetime(2027, 1, 1, 3, 0, tzinfo=UTC)
    assert leads_vm.registered_label(new_year_utc, _BOGOTA, now=now) == (
        "Te dejó sus datos el 31 dic."
    )


def test_extra_answers_show_the_question_the_business_wrote() -> None:
    labels = leads_vm.question_labels(
        [
            {"key": "zona_entrega", "label": "¿En qué zona vives?"},
            {"key": "turno_pref", "label": "¿A qué hora te escribimos?"},
            {"key": "sin_etiqueta"},
            "basura",
        ]
    )
    assert labels == {
        "zona_entrega": "¿En qué zona vives?",
        "turno_pref": "¿A qué hora te escribimos?",
    }
    summary = leads_vm.extra_summary({"zona_entrega": "oeste", "turno_pref": "tarde"}, labels)
    assert summary == "¿A qué hora te escribimos?: tarde · ¿En qué zona vives?: oeste"
    # No label for a key → the key, never nothing.
    assert leads_vm.extra_summary({"sin_etiqueta": "sí"}, labels) == "sin_etiqueta: sí"
    assert leads_vm.question_labels(None) == {}


def test_pending_summary_counts_who_is_still_waiting() -> None:
    assert leads_vm.pending_summary(3) == "Te faltan 3 por escribir"
    assert leads_vm.pending_summary(1) == "Te falta 1 por escribir"
    assert leads_vm.pending_summary(0) == "¡Al día! Ya le escribiste a todos."


def test_whatsapp_button_is_one_tappable_element_with_a_clear_label() -> None:
    rendered = str(_lead_card(LeadsState.leads[0]).render())
    assert "RadixThemesLink" not in rendered  # no link nested around a button
    assert "asChild" in rendered
    assert "por WhatsApp (se abre WhatsApp)" in rendered


def test_the_list_opens_with_how_many_are_left() -> None:
    assert "pending_summary" in str(_leads_list().render())


def test_failed_mark_also_raises_a_toast() -> None:
    import inspect

    from . import leads_state

    for handler in (leads_state.LeadsState.mark_contacted, leads_state.LeadsState.mark_pending):
        assert "rx.toast.error(MARK_FAILED)" in inspect.getsource(handler.fn)

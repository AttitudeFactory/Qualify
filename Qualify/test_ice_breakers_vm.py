"""«Preguntas iniciales» view models (m-24789472, phase 2 UI), offline and pure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from qualify_api.conversations.ice_breakers import DEFAULT_ITEMS, MAX_QUESTION_CHARS
from qualify_api.conversations.ice_breakers_client import MAX_ICE_BREAKERS, IceBreakerItem

from . import ice_breakers_vm as vm


@dataclass(frozen=True)
class _Config:
    items: tuple[IceBreakerItem, ...] = DEFAULT_ITEMS
    status: str = "draft"
    published_at: datetime | None = None
    is_published: bool = False
    has_unpublished_changes: bool = True
    is_default: bool = True
    remote_verified: bool = False
    error_message: str | None = None


ZONE = ZoneInfo("America/Bogota")
AT = datetime(2026, 10, 23, 19, 5, tzinfo=UTC)  # 14:05 in Bogotá


def test_limits_mirror_the_backend() -> None:
    assert vm.MAX_QUESTIONS == MAX_ICE_BREAKERS
    assert vm.MAX_QUESTION_CHARS == MAX_QUESTION_CHARS


def test_rows_keep_their_payload_and_count_characters() -> None:
    rows = vm.build_rows(DEFAULT_ITEMS)
    assert [r.payload for r in rows] == [i.payload for i in DEFAULT_ITEMS]
    assert rows[0].counter == f"{len(DEFAULT_ITEMS[0].question)}/80"
    assert rows[0].is_first and not rows[0].is_last and rows[-1].is_last

    edited = vm.with_question(rows, 1, "¿Cuánto cuesta el combo?")
    assert edited[1].payload == rows[1].payload  # only the text changes
    assert edited[1].counter == "24/80"
    assert vm.draft_items(edited)[1] == {
        "question": "¿Cuánto cuesta el combo?",
        "payload": rows[1].payload,
    }


def test_a_new_row_goes_out_with_an_empty_payload_and_stops_at_four() -> None:
    rows = vm.without_row(vm.build_rows(DEFAULT_ITEMS), 3)
    assert len(rows) == 3 and rows[-1].is_last
    rows = vm.with_new_row(rows, "nueva-1")
    rows = vm.with_question(rows, 3, "¿Tienen domicilio?")
    assert vm.draft_items(rows)[3] == {"question": "¿Tienen domicilio?", "payload": ""}
    assert vm.with_new_row(rows, "nueva-2") == rows  # already four
    assert vm.question_count(rows) == "4/4"


def test_move_swaps_and_refuses_the_ends() -> None:
    rows = vm.build_rows(DEFAULT_ITEMS)
    down = vm.moved(rows, 0, 1)
    assert down is not None
    assert [r.payload for r in down[:2]] == [rows[1].payload, rows[0].payload]
    assert down[0].is_first and not down[1].is_first
    assert vm.moved(rows, 0, -1) is None
    assert vm.moved(rows, 3, 1) is None
    assert vm.moved(rows, 1, 2) is None


def test_the_error_lands_under_the_question_it_names() -> None:
    rows = vm.build_rows(DEFAULT_ITEMS)
    marked, left = vm.with_error(rows, 2, "Hay dos preguntas iguales.")
    assert left == ""
    assert [r.error for r in marked] == ["", "", "Hay dos preguntas iguales.", ""]
    # Typing in that row clears its error.
    assert vm.with_question(marked, 2, "otra")[2].error == ""
    # No index (or one off the list): the message stays for the panel.
    cleared, left = vm.with_error(marked, None, "Agrega al menos una pregunta.")
    assert left == "Agrega al menos una pregunta." and all(r.error == "" for r in cleared)


def test_status_lines() -> None:
    draft = vm.build_status(_Config(), ZONE)
    assert (draft.label, draft.tone, draft.is_published) == ("Sin publicar", "neutral", False)

    published = vm.build_status(
        _Config(
            status="published",
            published_at=AT,
            is_published=True,
            has_unpublished_changes=False,
            remote_verified=True,
        ),
        ZONE,
    )
    assert published.label == "Publicadas el 23 oct, 14:05"
    assert published.tone == "ok" and published.verified and published.is_published

    pending = vm.build_status(_Config(status="published", published_at=AT, is_published=True), ZONE)
    assert pending.label == "Cambios sin publicar" and pending.tone == "warn"
    assert pending.detail.startswith("Publicadas el 23 oct, 14:05.")

    failed = vm.build_status(
        _Config(
            status="failed",
            error_message="Instagram no respondió. Inténtalo de nuevo en unos minutos.",
            remote_verified=True,
        ),
        ZONE,
    )
    assert failed.label == "No se pudo actualizar Instagram" and failed.tone == "error"
    assert failed.detail == "Instagram no respondió. Inténtalo de nuevo en unos minutos."
    assert failed.verified is False

    removed = vm.build_status(_Config(status="removed"), ZONE)
    assert removed.label == "Sin publicar" and "quitaste" in removed.detail


def test_confirmations_say_what_changes() -> None:
    assert "cualquier persona que abra un chat" in vm.confirm_text("publish")
    assert "ya no verán" in vm.confirm_text("remove")
    assert "se pierde" in vm.confirm_text("restore")
    assert vm.confirm_text("otra cosa") == ""
    assert vm.confirm_text("close") == "Tienes cambios sin guardar."
    assert "close" not in vm.CONFIRM_KINDS  # never a remote action
    assert "sugeridas" in vm.confirm_text("restore")


def test_copy_has_no_english_words() -> None:
    texts = " ".join(
        [
            vm.EXPLANATION,
            vm.ANSWER_NOTE,
            vm.UNAVAILABLE_NOTE,
            *map(vm.confirm_text, vm.CONFIRM_KINDS),
        ]
    ).lower()
    assert "aplicación de instagram del celular" in texts
    for word in ("ice breaker", "post", "inbox", "feed", "chatbot", "bot ", "payload", " app "):
        assert word not in texts

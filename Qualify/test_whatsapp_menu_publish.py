"""m-24842995: publishing the WhatsApp menu is ONE main action. «Publicar en mi WhatsApp»
saves the editor's changes as a new version and publishes it in the same tap (after the
confirmation); «Guardar sin publicar» is the secondary; after publishing the owner sees
«listo» and the next step (the QR). No database, no Graph: the provider calls are faked.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU

from . import whatsapp_menu_state as module
from .whatsapp_menu_provider import MenuDetail, PublishOutcome
from .whatsapp_menu_state import WhatsAppMenuState
from .whatsapp_menu_vm import (
    NEXT_STEP_QR,
    PUBLISH_BUTTON,
    PUBLISH_CONFIRM,
    PUBLISH_OK,
    PUBLISH_PARTIAL,
    SAVE_ONLY_BUTTON,
    MenuSummaryVM,
    MenuVersionVM,
    can_publish,
    publish_confirm_lines,
)
from .whatsapp_state import WhatsAppState

TENANT = uuid4()
CONNECTION = str(uuid4())
MENU_ID = str(uuid4())
V1, V2 = str(uuid4()), str(uuid4())


class _Proxy:
    """Reflex's StateProxy in a test: `async with self` is a no-op lock."""

    def __init__(self, state: WhatsAppMenuState) -> None:
        object.__setattr__(self, "_state", state)

    async def __aenter__(self) -> _Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __getattr__(self, name: str) -> object:
        return getattr(self._state, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._state, name, value)


def _summary(*, published: bool) -> MenuSummaryVM:
    return MenuSummaryVM(
        menu_id=MENU_ID,
        name="Menú principal",
        published_label="Publicado: v2" if published else "Sin publicar",
        is_published=published,
        is_paused=False,
        status_label="Respondiendo en tu WhatsApp" if published else "Sin publicar",
        status_tone="ok" if published else "neutral",
        updated_at="hoy",
    )


def _version(version_id: str, n: int, *, live: bool = False) -> MenuVersionVM:
    return MenuVersionVM(
        version_id=version_id,
        label=f"Versión {n}",
        created_at="hoy",
        published_at="hoy" if live else "",
        is_live=live,
    )


def _detail(versions: list[MenuVersionVM], *, published: bool) -> MenuDetail:
    payload = BIANKI_DEMO_MENU.model_dump(mode="json")
    return MenuDetail(
        summary=_summary(published=published),
        versions=versions,
        latest=BIANKI_DEMO_MENU,
        payloads={v.version_id: payload for v in versions},
    )


def _state(monkeypatch: pytest.MonkeyPatch) -> WhatsAppMenuState:
    async def session(self: object) -> tuple[str, UUID | None, str]:
        return str(TENANT), TENANT, "duena@example.com"

    async def connection_id(self: object) -> str:
        return CONNECTION

    monkeypatch.setattr(WhatsAppMenuState, "_session", session)
    monkeypatch.setattr(WhatsAppMenuState, "_connection_id", connection_id)
    monkeypatch.setattr(module, "user_id_for", lambda *a: None)
    state = WhatsAppMenuState()
    state._scope = {"phone_row_id": str(uuid4()), "brand_id": "", "brand_name": "Bianki"}
    state.menus = [_summary(published=False)]
    state._show_detail(_detail([_version(V1, 1)], published=False), load_form=True)
    return state


def _fake_publish(calls: list[str], *, tone: str = "ok", auth_error: bool = False) -> object:
    async def publish(
        tenant_id: UUID,
        connection_id: UUID,
        scope: object,
        menu_id: UUID,
        version_id: UUID,
        **kw: object,
    ) -> PublishOutcome:
        calls.append(f"publish:{version_id}")
        versions = [_version(str(version_id), 2, live=True), _version(V1, 1)]
        return PublishOutcome(
            detail=_detail(versions, published=True),
            notice=PUBLISH_OK if tone == "ok" else PUBLISH_PARTIAL,
            tone=tone,
            graph_ok=tone == "ok",
            auth_error=auth_error,
        )

    return publish


def _fake_save(calls: list[str]) -> object:
    def save(tenant_id: UUID, scope: object, menu_id: UUID, payload: dict) -> MenuDetail:
        calls.append("save")
        return _detail([_version(V2, 2), _version(V1, 1)], published=False)

    return save


async def _run(handler: object, state: WhatsAppMenuState) -> list[object]:
    return [event async for event in handler.fn(_Proxy(state))]  # type: ignore[attr-defined]


# --- the rule -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"dirty": True, "editing_version_id": ""}, True),  # changes → saved, then published
        ({"dirty": False, "editing_version_id": V1}, True),  # the saved version on screen
        ({"dirty": False, "editing_version_id": ""}, False),  # nothing to publish yet
        ({"dirty": True, "editing_version_id": V1, "error_count": 2}, False),
        ({"dirty": True, "editing_version_id": V1, "busy": True}, False),
        ({"dirty": True, "editing_version_id": V1, "has_menu": False}, False),
    ],
)
def test_can_publish(kwargs: dict, expected: bool) -> None:
    args = {"has_menu": True, "error_count": 0, "busy": False, **kwargs}
    assert can_publish(**args) is expected


# --- one tap: save + publish --------------------------------------------------------------


async def test_publicar_saves_the_changes_and_publishes_the_new_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(module, "save_version", _fake_save(calls))
    monkeypatch.setattr(module, "publish_version", _fake_publish(calls))
    state.set_welcome("¡Hola! Bienvenido a Bianki.")
    assert state.dirty and state.can_publish

    await _run(WhatsAppMenuState.publish_current, state)

    # the edited version is the one that goes live — never the older saved one
    assert calls == ["save", f"publish:{V2}"]
    assert not state.dirty and not state.saving and not state.publishing
    assert state.editing_version_id == V2
    assert state.menu.is_published
    # «listo» + the QR next step, where the owner tapped; no duplicate banner up top
    assert state.just_published and state.banner == ""


async def test_publicar_without_changes_publishes_the_version_on_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(module, "save_version", _fake_save(calls))
    monkeypatch.setattr(module, "publish_version", _fake_publish(calls))
    assert not state.dirty and state.editing_version_id == V1

    await _run(WhatsAppMenuState.publish_current, state)

    assert calls == [f"publish:{V1}"]
    assert state.just_published


async def test_an_older_version_opened_in_the_editor_is_what_publicar_publishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state._show_detail(_detail([_version(V2, 2), _version(V1, 1)], published=False), load_form=True)
    assert state.editing_version_id == V2
    state.open_version(V1)
    assert state.editing_version_id == V1 and not state.dirty
    calls: list[str] = []
    monkeypatch.setattr(module, "publish_version", _fake_publish(calls))

    await _run(WhatsAppMenuState.publish_current, state)

    assert calls == [f"publish:{V1}"]


async def test_a_failed_save_publishes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.exc import OperationalError

    state = _state(monkeypatch)
    calls: list[str] = []

    def broken_save(*a: object, **kw: object) -> MenuDetail:
        raise OperationalError("insert", {}, Exception("down"))

    monkeypatch.setattr(module, "save_version", broken_save)
    monkeypatch.setattr(module, "publish_version", _fake_publish(calls))
    state.set_welcome("¡Hola!")

    await _run(WhatsAppMenuState.publish_current, state)

    assert calls == []
    assert state.dirty  # the owner's edits are still there to retry
    assert not state.saving and not state.publishing and not state.just_published
    assert state.banner_tone == "error" and "Vuelve a intentarlo" in state.banner


async def test_a_partial_failure_shows_only_its_banner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(module, "publish_version", _fake_publish(calls, tone="warn"))

    await _run(WhatsAppMenuState.publish_current, state)

    assert state.banner_tone == "warn" and state.banner.startswith(PUBLISH_PARTIAL)
    assert not state.just_published  # no green «Listo» next to what has to be fixed


async def test_an_auth_error_asks_to_reconnect_instead_of_the_qr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        module, "publish_version", _fake_publish(calls, tone="error", auth_error=True)
    )

    events = await _run(WhatsAppMenuState.publish_current, state)

    assert not state.just_published and state.banner_tone == "error"
    assert events == [WhatsAppState.load_numbers]


async def test_guardar_sin_publicar_saves_only_and_says_how_to_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(module, "save_version", _fake_save(calls))
    monkeypatch.setattr(module, "publish_version", _fake_publish(calls))
    state.set_welcome("¡Hola!")

    await _run_plain(WhatsAppMenuState.save_current_version, state)

    assert calls == ["save"]
    assert state.editing_version_id == V2 and not state.dirty
    assert "sin publicar" in state.banner and PUBLISH_BUTTON in state.banner
    assert not state.just_published


async def _run_plain(handler: object, state: WhatsAppMenuState) -> None:
    await handler.fn(_Proxy(state))  # type: ignore[attr-defined]


def test_an_edit_after_publishing_hides_the_next_step(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch)
    state.just_published = True
    state.set_welcome("Otra bienvenida")
    assert not state.just_published
    state.just_published = True
    state.dismiss_next_step()
    assert not state.just_published


# --- the copy (guide N13: assisted, never autonomous) ------------------------------------


def test_the_copy_says_the_owner_wrote_the_menu_and_takes_the_chat() -> None:
    assert PUBLISH_BUTTON == "Publicar en mi WhatsApp"
    assert SAVE_ONLY_BUTTON == "Guardar sin publicar"
    assert PUBLISH_CONFIRM == (
        "Al publicar, tu WhatsApp responde con los mensajes que tú escribiste en este menú, "
        "nada más. Puedes tomar el control de cualquier chat desde Chats."
    )
    assert NEXT_STEP_QR == "Haz que te escriban: crea tu código QR para el mostrador"
    source = (Path(__file__).parent / "whatsapp_tab_menu.py").read_text()
    state_source = (Path(__file__).parent / "whatsapp_menu_state.py").read_text()
    assert "Tu WhatsApp responde con el menú que tú escribiste" in source
    for text in (source, state_source):
        assert "responde solo" not in text and "Qualify responde" not in text
    # one publish path: the per-version button is gone
    assert "Publicar esta versión" not in source


def test_the_tab_renders_the_single_publish_bar() -> None:
    from . import whatsapp_tab_menu

    rendered = str(whatsapp_tab_menu.menu_tab().render())

    def present(text: str) -> bool:
        escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
        return text in rendered or escaped in rendered

    for text in (
        PUBLISH_BUTTON,
        SAVE_ONLY_BUTTON,
        "Probar el menú",
        "Ver versiones anteriores",
        NEXT_STEP_QR,
        "Crear mi código QR",
        whatsapp_tab_menu.PREVIEW_ELEMENT_ID,
    ):
        assert present(text), text


# --- the confirmation, case by case -------------------------------------------------------


def test_confirm_lines_when_there_are_changes() -> None:
    assert publish_confirm_lines(
        dirty=True, version=_version(V1, 1, live=True), other_published_menu=""
    ) == ["Primero guardamos tus cambios como una versión nueva."]


def test_confirm_lines_for_an_older_version_and_for_the_live_one() -> None:
    older = MenuVersionVM(V1, "Versión 1", "ayer", "ayer", is_live=False)
    assert publish_confirm_lines(dirty=False, version=older, other_published_menu="") == [
        "Tu WhatsApp vuelve a responder con la versión 1."
    ]
    never = _version(V2, 4)
    assert publish_confirm_lines(dirty=False, version=never, other_published_menu="") == [
        "Tu WhatsApp empieza a responder con la versión 4."
    ]
    live = _version(V2, 2, live=True)
    assert publish_confirm_lines(dirty=False, version=live, other_published_menu="") == [
        "Este menú ya está respondiendo. Volvemos a enviar a WhatsApp la bienvenida, los "
        "atajos y los comandos."
    ]


def test_confirm_lines_name_the_menu_it_replaces_only_when_there_is_one() -> None:
    lines = publish_confirm_lines(dirty=True, version=None, other_published_menu="Almuerzos")
    assert lines[-1] == "Tu menú «Almuerzos» deja de responder y este toma su lugar."
    assert all(
        "deja de responder" not in line
        for line in publish_confirm_lines(dirty=True, version=None, other_published_menu="")
    )


def test_the_state_feeds_the_confirmation_from_the_number_s_menus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    other = MenuSummaryVM(
        menu_id=str(uuid4()),
        name="Almuerzos",
        published_label="Publicado: versión 3",
        is_published=True,
        is_paused=False,
        status_label="Respondiendo en tu WhatsApp",
        status_tone="ok",
        updated_at="hoy",
    )
    state.menus = [*state.menus, other]
    assert state.publish_confirm_lines == [
        "Tu WhatsApp empieza a responder con la versión 1.",
        "Tu menú «Almuerzos» deja de responder y este toma su lugar.",
    ]

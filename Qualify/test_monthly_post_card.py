"""m-25120704: the «Publicación del mes» card on the Planificador."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from qualify_api.planner.monthly_post import MonthlyPostSetting
from qualify_creative.enums import ContentKind

from . import monthly_post_provider as provider
from . import monthly_post_state as state_module
from .auth_state import AuthState
from .creative_state import CreativeState
from .monthly_post_state import MonthlyPostState
from .monthly_post_vm import (
    EXPLAIN,
    LOAD_FAILED,
    SAVE_FAILED,
    SESSION_ENDED,
    kind_options,
    monthly_cost_text,
)


def test_choices_are_ready_to_publish_kinds_with_their_spanish_names() -> None:
    options = kind_options()
    values = [o["value"] for o in options]
    # founder, 2026-11-25: only what the monthly chore can make without the owner's inputs
    assert values == ["static_flyer", "clip"]
    assert {"value": "static_flyer", "label": "Imagen publicitaria"} in options
    assert "Por aprobar" in EXPLAIN


_PRESENTER = "Este video con presentador usa 25 de tus creaciones cada mes."
_VIDEO = "Este video usa 5 segundos de tus videos del mes cuando lo apruebas."


@pytest.mark.parametrize(
    ("kind", "engine", "text"),
    [
        ("static_flyer", "seedance", "Usa 1 de tus creaciones cada mes."),
        ("template", "omnihuman", "Usa 1 de tus creaciones cada mes."),
        ("carousel", "seedance", "Usa desde 1 de tus creaciones cada mes."),
        ("avatar_video", "omnihuman", _PRESENTER),
        ("avatar_video", "seedance", _VIDEO),
        ("animated_avatar_video", "seedance", _VIDEO),
        ("clip", "omnihuman", _VIDEO),
        ("nope", "seedance", ""),
    ],
)
def test_cost_is_the_generators_price_for_the_kind(kind: str, engine: str, text: str) -> None:
    assert monthly_cost_text(kind, engine) == text


@pytest.mark.parametrize("engine", ["seedance", "omnihuman"])
def test_every_choice_says_what_it_costs(engine: str) -> None:
    assert all(monthly_cost_text(o["value"], engine) for o in kind_options())


def test_provider_uses_the_default_brand_and_refuses_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brand = uuid4()
    saved: list[tuple] = []
    monkeypatch.setattr(provider, "brand_for", lambda _t, cached: UUID(cached) if cached else brand)
    monkeypatch.setattr(
        provider,
        "set_monthly_post_setting",
        lambda *args: saved.append(args) or MonthlyPostSetting(True, ContentKind.CLIP),
    )
    tenant = uuid4()
    assert provider.save_setting(tenant, "", True, "clip").enabled
    assert saved == [(tenant, brand, True, "clip")]
    monkeypatch.setattr(provider, "brand_for", lambda _t, _c: None)
    with pytest.raises(LookupError):
        provider.read_setting(tenant, "")


TENANT, LOGIN, USER = uuid4(), uuid4(), uuid4()


class Context:
    _session = MonthlyPostState._session

    def __init__(self) -> None:
        self.auth = SimpleNamespace(
            session_tenant_id=str(TENANT), _auth_user_id=str(LOGIN), _session_user_id=str(USER)
        )
        self.creative = SimpleNamespace(_brand_id="")
        self.enabled, self.kind = True, "carousel"  # what another business had
        self.loading, self.saving, self.load_error, self.error = True, False, "", ""
        self._context, self._operation = ("", "", ""), ""

    async def __aenter__(self) -> Context:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def get_state(self, state_class: type) -> object:
        return {AuthState: self.auth, CreativeState: self.creative}[state_class]


def test_load_shows_the_saved_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        state_module, "read_setting", lambda _t, _b: MonthlyPostSetting(True, ContentKind.CLIP)
    )
    context = Context()
    asyncio.run(MonthlyPostState.load.fn(context))
    assert (context.enabled, context.kind, context.loading) == (True, "clip", False)
    assert context.load_error == ""


def test_load_failure_hides_the_switch_behind_a_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_t: object, _b: object) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(state_module, "read_setting", broken)
    context = Context()
    asyncio.run(MonthlyPostState.load.fn(context))
    assert context.load_error == LOAD_FAILED and not context.enabled


def test_save_keeps_what_the_backend_stored_or_says_to_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context()
    context._context = (str(TENANT), str(LOGIN), str(USER))
    monkeypatch.setattr(
        state_module,
        "save_setting",
        lambda _t, _b, enabled, kind: MonthlyPostSetting(enabled, ContentKind(kind)),
    )
    asyncio.run(MonthlyPostState.save.fn(context, False, "static_flyer"))
    assert (context.enabled, context.kind, context.error) == (False, "static_flyer", "")

    def refused(*_: object) -> None:
        raise ValueError("bad kind")

    monkeypatch.setattr(state_module, "save_setting", refused)
    asyncio.run(MonthlyPostState.save.fn(context, True, "creator_script"))
    assert context.error == SAVE_FAILED and not context.enabled and not context.saving


def test_save_from_a_stale_session_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state_module, "save_setting", lambda *_: pytest.fail("must not save"))
    context = Context()  # never loaded for this login
    asyncio.run(MonthlyPostState.save.fn(context, True, "clip"))
    assert context.error == SESSION_ENDED


def test_a_load_in_flight_never_undoes_a_save(monkeypatch: pytest.MonkeyPatch) -> None:
    context = Context()
    context._context = (str(TENANT), str(LOGIN), str(USER))

    def old_value(_t: object, _b: object) -> MonthlyPostSetting:
        # the owner's save lands while this read is still out
        monkeypatch.setattr(
            state_module,
            "save_setting",
            lambda _t, _b, enabled, kind: MonthlyPostSetting(enabled, ContentKind(kind)),
        )
        asyncio.run(MonthlyPostState.save.fn(context, True, "clip"))
        return MonthlyPostSetting()

    monkeypatch.setattr(state_module, "read_setting", old_value)
    asyncio.run(MonthlyPostState.load.fn(context))
    assert (context.enabled, context.kind, context.loading) == (True, "clip", False)

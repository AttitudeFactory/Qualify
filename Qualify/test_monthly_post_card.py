"""m-25120704: the «Publicación del mes» card on the Planificador."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from qualify_api.planner.monthly_post import MONTHLY_POST_KINDS, MonthlyPostSetting
from qualify_creative.enums import ContentKind

from . import monthly_post_provider as provider
from . import monthly_post_state as state_module
from .auth_state import AuthState
from .catalog_vm import ProductVM
from .creative_state import CreativeState
from .monthly_post_state import MonthlyPostState
from .monthly_post_vm import (
    EXPLAIN,
    LOAD_FAILED,
    NO_PRODUCTS_HREF,
    SAVE_FAILED,
    SESSION_ENDED,
    cost_warns,
    kind_options,
    monthly_cost_text,
    product_rows,
)


def test_choices_are_ready_to_publish_kinds_with_their_spanish_names() -> None:
    options = kind_options()
    values = [o["value"] for o in options]
    # founder, 2026-11-26 (m-25121346): every ready-to-publish kind
    assert values == [k.value for k in MONTHLY_POST_KINDS] and len(values) == 6
    assert {"value": "static_flyer", "label": "Imagen publicitaria"} in options
    assert "Por aprobar" in EXPLAIN


# m-25121346: the job's lengths — a clip of 5 s, the avatars at 10 s (founder, 2026-11-26)
_PRESENTER = "Este video con presentador usa 9 de tus creaciones cada mes."
_AVATAR = "Este video usa 10 segundos de tus videos del mes cuando lo apruebas."
_VIDEO = "Este video usa 5 segundos de tus videos del mes cuando lo apruebas."


@pytest.mark.parametrize(
    ("kind", "engine", "text"),
    [
        ("static_flyer", "seedance", "Usa 1 de tus creaciones cada mes."),
        ("template", "omnihuman", "Usa 1 de tus creaciones cada mes."),
        ("carousel", "seedance", "Usa 1 de tus creaciones cada mes."),
        ("avatar_video", "omnihuman", _PRESENTER),
        ("animated_avatar_video", "omnihuman", _PRESENTER),
        ("avatar_video", "seedance", _AVATAR),
        ("animated_avatar_video", "seedance", _AVATAR),
        ("clip", "omnihuman", _VIDEO),
        ("nope", "seedance", ""),
    ],
)
def test_cost_is_the_generators_price_for_the_kind(kind: str, engine: str, text: str) -> None:
    assert monthly_cost_text(kind, engine) == text


def test_a_presenter_names_the_plans_month_and_warns() -> None:
    assert monthly_cost_text("avatar_video", "omnihuman", 30) == (
        "Este video con presentador usa 9 de tus 30 creaciones cada mes."
    )
    assert monthly_cost_text("avatar_video", "omnihuman", 0) == _PRESENTER  # unknown
    assert monthly_cost_text("clip", "omnihuman", 30) == _VIDEO
    assert cost_warns("animated_avatar_video", "omnihuman")
    assert not cost_warns("avatar_video", "seedance") and not cost_warns("clip", "omnihuman")


@pytest.mark.parametrize("engine", ["seedance", "omnihuman"])
def test_every_choice_says_what_it_costs(engine: str) -> None:
    assert all(monthly_cost_text(o["value"], engine) for o in kind_options())


def _product(product_id: str, photos: int) -> ProductVM:
    return ProductVM(
        product_id=product_id,
        name=f"Producto {product_id}",
        slug=product_id,
        description="",
        price_label="",
        price_amount="",
        price_currency="",
        category="",
        primary_photo_key=f"k/{product_id}.jpg" if photos else "",
        photo_count=photos,
        video_count=0,
        counts_label="",
    )


def test_only_products_with_a_photo_can_make_a_template() -> None:
    rows = product_rows([_product("a", 2), _product("b", 0)])
    assert rows == [{"id": "a", "name": "Producto a", "photo_key": "k/a.jpg"}]
    assert NO_PRODUCTS_HREF.startswith("/catalog?") and "volver" not in NO_PRODUCTS_HREF


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
    assert provider.save_setting(tenant, "", True, "template", "p1").enabled
    assert saved == [(tenant, brand, True, "clip", None), (tenant, brand, True, "template", "p1")]
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
        self.product_id, self.product_missing, self.products = "", False, []
        self._saved_kind = "static_flyer"
        self.creations = 0

    _show = MonthlyPostState._show

    async def __aenter__(self) -> Context:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def get_state(self, state_class: type) -> object:
        return {AuthState: self.auth, CreativeState: self.creative}[state_class]


@pytest.fixture(autouse=True)
def _no_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state_module, "template_products", lambda _t, _b: [])
    monkeypatch.setattr(state_module, "monthly_creations", lambda _t, _b: 30)


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
        lambda _t, _b, enabled, kind, _p: MonthlyPostSetting(enabled, ContentKind(kind)),
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
            lambda _t, _b, enabled, kind, _p: MonthlyPostSetting(enabled, ContentKind(kind)),
        )
        asyncio.run(MonthlyPostState.save.fn(context, True, "clip"))
        return MonthlyPostSetting()

    monkeypatch.setattr(state_module, "read_setting", old_value)
    asyncio.run(MonthlyPostState.load.fn(context))
    assert (context.enabled, context.kind, context.loading) == (True, "clip", False)


_ROW = {"id": str(uuid4()), "name": "Shawarma", "photo_key": "k.jpg"}


def test_load_brings_the_products_and_a_missing_one(monkeypatch: pytest.MonkeyPatch) -> None:
    product = UUID(_ROW["id"])
    monkeypatch.setattr(
        state_module,
        "read_setting",
        lambda _t, _b: MonthlyPostSetting(True, ContentKind.TEMPLATE, product, True),
    )
    monkeypatch.setattr(state_module, "template_products", lambda _t, _b: [_ROW])
    context = Context()
    asyncio.run(MonthlyPostState.load.fn(context))
    assert (context.kind, context.product_id, context.product_missing) == (
        "template",
        _ROW["id"],
        True,
    )
    assert context.products == [_ROW] and context.creations == 30


def test_an_unreadable_quota_still_shows_the_card(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_t: object, _b: object) -> int:
        raise RuntimeError("no plan")

    monkeypatch.setattr(state_module, "read_setting", lambda _t, _b: MonthlyPostSetting())
    monkeypatch.setattr(state_module, "monthly_creations", broken)
    context = Context()
    asyncio.run(MonthlyPostState.load.fn(context))
    assert context.load_error == "" and context.creations == 0 and not context.loading


def test_template_waits_for_its_product_then_saves_it() -> None:
    context = Context()
    context.kind, context.enabled = "clip", True
    assert MonthlyPostState.set_kind.fn(context, "template") is None  # nothing saved yet
    assert context.kind == "template"
    assert _save_args(MonthlyPostState.choose_product.fn(context, _ROW["id"])) == (
        True,
        "template",
        _ROW["id"],
    )


def _save_args(event: object) -> tuple:
    assert event.handler.fn.__name__ == "save"
    return tuple(value._var_value for _, value in event.args)


def test_the_switch_still_works_while_the_product_is_gone_or_unchosen() -> None:
    context = Context()
    context.enabled, context.kind, context._saved_kind = True, "template", "template"
    context.product_id, context.product_missing = _ROW["id"], True
    # a template is refused without a usable product: off saves the default kind
    assert _save_args(MonthlyPostState.set_enabled.fn(context, False)) == (
        False,
        "static_flyer",
        "",
    )
    context.product_id, context.product_missing, context._saved_kind = "", False, "clip"
    assert _save_args(MonthlyPostState.set_enabled.fn(context, False)) == (False, "clip", "")

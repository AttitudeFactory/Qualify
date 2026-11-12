"""m-24828975: real saved ad fields, defaults and conflicts, on synthetic local businesses."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.creative import models as orm
from qualify_api.creative.voice_service import VoiceProfileService
from qualify_api.tenancy.models import Brand
from qualify_creative.schemas import CopyPayload
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from .conftest import _finish_brand_kit, expect

_PASSWORD = "e2e-clave-segura"
_BRAND_URL = "https://cafe.example/menu"
_PIECE_URL = "https://cafe.example/oferta"


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict[str, Any]) -> dict[str, Any]:
    binary = os.environ.get("QUALIFY_E2E_BROWSER_BINARY")
    if not binary:
        return browser_type_launch_args
    assert Path(binary).is_file()
    return {
        **browser_type_launch_args,
        "executable_path": binary,
        "args": ["--disable-background-networking", "--disable-gpu", "--renderer-process-limit=1"],
    }


def login(page: Any, base: str, email: str) -> None:
    page.goto(f"{base}/login")
    page.get_by_placeholder("Correo", exact=True).fill(email)
    page.get_by_placeholder("Contraseña", exact=True).fill(_PASSWORD)
    page.get_by_role("button", name="Entrar", exact=True).click()
    expect(page).not_to_have_url(re.compile(r"/login"), timeout=90_000)


def _business(base: str, context: Any) -> tuple[Any, UUID, UUID, str]:
    email = f"e2e-ad-{uuid4().hex[:10]}@example.com"
    signup = context.new_page()
    signup.set_default_timeout(60_000)
    signup.goto(f"{base}/registro")
    signup.locator("#signup-business").fill("Café de prueba")
    signup.locator("#signup-email").fill(email)
    signup.locator("#signup-password").fill(_PASSWORD)
    signup.locator("#signup-country").click()
    signup.get_by_role("option", name="Colombia", exact=True).click()
    signup.get_by_role("button", name="Registrar y entrar").click()
    expect(signup).not_to_have_url(re.compile(r"/registro"), timeout=90_000)
    signup.wait_for_timeout(3_000)
    signup.close()
    tenant_id, user_id = _finish_brand_kit(email)
    with tenant_session(tenant_id) as session:
        brand_id = session.scalar(select(Brand.id))
    assert brand_id is not None
    VoiceProfileService().adopt_from_kit(tenant_id=tenant_id, brand_id=brand_id, user_id=user_id)
    page = context.new_page()
    page.set_default_timeout(60_000)
    login(page, base, email)
    return page, tenant_id, user_id, email


def _seed_piece(tenant_id: UUID, user_id: UUID) -> tuple[UUID, UUID]:
    brief, draft, version, variant = (uuid4() for _ in range(4))
    payload = CopyPayload(
        hook="Tu café de hoy",
        caption="Ven por un café recién hecho.",
        cta="Visítanos",
        hashtags=("cafe",),
        ads_primary_text="Tu café recién hecho te espera.",
        ads_headline="Visítanos hoy",
        ads_description="En tu barrio",
        ads_cta_type="LEARN_MORE",
    )
    with tenant_session(tenant_id) as session:
        brand = session.scalar(select(Brand.id))
        session.add(
            orm.ContentBrief(
                id=brief,
                tenant_id=tenant_id,
                brand_id=brand,
                objective="consideration",
                topic="Café de prueba",
                platform="instagram",
                format="post",
                intent="ads",
                content_type="hours_location",
                image_route="template_only",
                variants_requested=1,
                constraints={},
                kind="static_flyer",
                media={},
                created_by=user_id,
            )
        )
        session.flush()
        row = orm.ContentDraft(
            id=draft,
            tenant_id=tenant_id,
            brand_id=brand,
            brief_id=brief,
            status="generated",
            pipeline_version="e2e-ad-destination-v1",
            title="Café de prueba",
            revision=1,
        )
        session.add(row)
        session.flush()
        session.add(
            orm.PieceVersion(
                id=version,
                tenant_id=tenant_id,
                brand_id=brand,
                draft_id=draft,
                revision=1,
                status="active",
                model_id="e2e-synthetic",
                pipeline_version="e2e-ad-destination-v1",
                brief_id=brief,
            )
        )
        session.flush()
        row.active_version_id = version
        session.add(
            orm.CopyVariant(
                id=variant,
                tenant_id=tenant_id,
                draft_id=draft,
                version_id=version,
                ordinal=0,
                copy=payload.model_dump(mode="json"),
                fidelity={"passed": True},
                model_id="e2e-synthetic",
            )
        )
    return draft, variant


def _stored(tenant: UUID, variant: UUID) -> dict[str, Any] | None:
    with tenant_session(tenant) as session:
        return session.scalar(
            select(orm.CopyVariant.edited_copy).where(orm.CopyVariant.id == variant)
        )


def _shot(page: Any, name: str) -> None:
    target = os.environ.get("QUALIFY_E2E_SHOTS")
    if target:
        directory = Path(target)
        directory.mkdir(parents=True, exist_ok=True)
        page.get_by_text("Botón y enlace del anuncio", exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(directory / name))


@pytest.mark.parametrize("width", [360, 1280], ids=["telefono", "computador"])
def test_saved_piece_link_default_and_stale_edit(app_server: str, context: Any, width: int) -> None:
    page, tenant, user, email = _business(app_server, context)
    page.set_viewport_size({"width": width, "height": 900 if width > 360 else 800})
    draft, variant = _seed_piece(tenant, user)
    fixture = os.environ.get("QUALIFY_PIECE_AD_FIXTURE_FILE")
    if fixture:
        Path(fixture).write_text(
            json.dumps(
                {
                    "email": email,
                    "password": _PASSWORD,
                    "draft_id": str(draft),
                    "tenant_id": str(tenant),
                    "variant_id": str(variant),
                    "base_url": app_server,
                }
            ),
            encoding="utf-8",
        )

    page.goto(f"{app_server}/brand/kit")
    section = page.locator("#seccion-anuncios")
    expect(section).to_be_visible()
    section.get_by_role("button", name="Cambiar", exact=True).click()
    brand_link = page.locator("#brand-ad-destination-url")
    brand_link.fill("http://cafe.example")
    section.get_by_role("button", name="Guardar", exact=True).click()
    expect(
        page.get_by_text(
            "Escribe un enlace completo que empiece por https://, sin espacios.", exact=True
        )
    ).to_be_visible()
    error = page.locator("#brand-ad-destination-error")
    box = error.bounding_box()
    assert box is not None and 0 <= box["y"] < page.viewport_size["height"]
    assert box["y"] + box["height"] <= page.viewport_size["height"]
    brand_link.fill(_BRAND_URL)
    section.get_by_role("button", name="Guardar", exact=True).click()
    expect(section.get_by_text(_BRAND_URL, exact=True)).to_be_visible()

    page.goto(f"{app_server}/drafts/{draft}")
    expect(page.get_by_text("Botón y enlace del anuncio", exact=True)).to_be_visible()
    expect(page.get_by_text("Todavía no hay un enlace guardado.", exact=True)).to_be_visible()
    page.get_by_role("button", name="Editar texto", exact=True).click()
    link = page.locator("#piece-ad-destination-url")
    link.fill("http://cafe.example")
    page.get_by_role("button", name="Guardar cambios", exact=True).click()
    expect(
        page.get_by_text(
            "Escribe un enlace completo que empiece por https://, sin espacios.", exact=True
        )
    ).to_be_visible()
    assert _stored(tenant, variant) is None
    page.get_by_role("button", name="Usar enlace de mi marca", exact=True).click()
    expect(link).to_have_value(_BRAND_URL)
    link.fill(_PIECE_URL)
    page.locator("#piece-ad-button").click()
    page.get_by_role("option", name="Comprar", exact=True).click()
    page.get_by_role("button", name="Guardar cambios", exact=True).click()
    expect(page.get_by_role("button", name="Editar texto", exact=True)).to_be_visible()
    assert _stored(tenant, variant)["ads_destination_url"] == _PIECE_URL
    assert _stored(tenant, variant)["ads_cta_type"] == "SHOP_NOW"
    page.reload()
    expect(page.get_by_text(_PIECE_URL, exact=True)).to_be_visible()
    _shot(page, f"m-24828975-{width}.png")
    with tenant_session(tenant) as session:
        assert session.scalar(select(orm.BrandKit.ads_destination_url)) == _BRAND_URL

    page.get_by_role("button", name="Editar texto", exact=True).click()
    page.locator("#piece-ad-destination-url").fill("https://cafe.example/sin-guardar")
    other = context.new_page()
    other.set_default_timeout(60_000)
    login(other, app_server, email)
    other.goto(f"{app_server}/drafts/{draft}")
    other.get_by_role("button", name="Editar texto", exact=True).click()
    other.locator("#piece-ad-destination-url").fill("https://cafe.example/otra-edicion")
    other.get_by_role("button", name="Guardar cambios", exact=True).click()
    expect(other.get_by_role("button", name="Editar texto", exact=True)).to_be_visible()
    page.get_by_role("button", name="Guardar cambios", exact=True).click()
    expect(
        page.get_by_text("La pieza cambió. Vuelve a abrirla antes de guardar.", exact=True)
    ).to_be_visible()
    expect(page.locator("#piece-ad-destination-url")).to_have_value(
        "https://cafe.example/sin-guardar"
    )
    expect(page.get_by_role("button", name="Guardar cambios", exact=True)).to_be_disabled()
    assert _stored(tenant, variant)["ads_destination_url"] == "https://cafe.example/otra-edicion"
    page.get_by_role("button", name="Volver a cargar la pieza", exact=True).click()
    expect(page.get_by_text("https://cafe.example/otra-edicion", exact=True)).to_be_visible()
    page.get_by_role("button", name="Editar texto", exact=True).click()
    long_url = "https://cafe.example/" + "a" * 450
    page.locator("#piece-ad-destination-url").fill(long_url)
    page.get_by_role("button", name="Guardar cambios", exact=True).click()
    saved_link = page.locator("#piece-ad-destination-saved")
    expect(saved_link).to_have_text(long_url)
    dimensions = saved_link.evaluate(
        """el => ({width: el.getBoundingClientRect().width,
        section: el.closest('.q-rv-section').getBoundingClientRect().width,
        scroll: el.scrollWidth, client: el.clientWidth,
        wrap: getComputedStyle(el).overflowWrap})"""
    )
    assert dimensions["width"] <= dimensions["section"]
    assert dimensions["scroll"] <= dimensions["client"] + 1
    assert dimensions["wrap"] == "anywhere"
    assert _stored(tenant, variant)["ads_destination_url"] == long_url
    other.close()
    page.close()

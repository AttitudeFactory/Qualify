"""`MemoryMenuRepository` (WA-14, persistence half) — the contract the WA-16 editor and the
WA-07 handler code against, exercised without Postgres. The Postgres implementation is
held to the same behaviour in `test_whatsapp_menus_schema_db.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from qualify_api.whatsapp.menus import (
    MemoryMenuRepository,
    MenuNotFound,
    MenuVersionNotFound,
)
from qualify_api.whatsapp.menus.engine import ENGINE_VERSION
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.menus.schema import MenuDefinition

TENANT = uuid4()
PHONE = uuid4()
USER = uuid4()


@pytest.fixture
def repo() -> MemoryMenuRepository:
    return MemoryMenuRepository()


def _tiny() -> dict:
    return {
        "nodes": {"hi": {"kind": "text", "body": "Hola"}},
        "start_node": "hi",
    }


def test_versions_are_numbered_per_menu_from_one(repo: MemoryMenuRepository) -> None:
    menu = repo.create_menu(tenant_id=TENANT, phone_number_row_id=PHONE, name="Principal")
    other = repo.create_menu(tenant_id=TENANT, phone_number_row_id=PHONE, name="Navidad")
    v1 = repo.save_version(tenant_id=TENANT, menu_id=menu.id, definition=BIANKI_DEMO_MENU)
    v2 = repo.save_version(tenant_id=TENANT, menu_id=menu.id, definition=_tiny())
    o1 = repo.save_version(tenant_id=TENANT, menu_id=other.id, definition=_tiny())
    assert (v1.version, v2.version, o1.version) == (1, 2, 1)
    assert v1.engine_version == ENGINE_VERSION
    assert [v.version for v in repo.list_versions(tenant_id=TENANT, menu_id=menu.id)] == [1, 2]
    assert isinstance(v2.definition, MenuDefinition)
    assert v1.definition == BIANKI_DEMO_MENU


def test_a_definition_given_as_json_round_trips(repo: MemoryMenuRepository) -> None:
    menu = repo.create_menu(tenant_id=TENANT, phone_number_row_id=PHONE, name="Principal")
    saved = repo.save_version(
        tenant_id=TENANT, menu_id=menu.id, definition=BIANKI_DEMO_MENU.model_dump(mode="json")
    )
    assert saved.definition == BIANKI_DEMO_MENU


def test_an_invalid_definition_is_refused_and_writes_nothing(repo: MemoryMenuRepository) -> None:
    menu = repo.create_menu(tenant_id=TENANT, phone_number_row_id=PHONE, name="Principal")
    bad = {"nodes": {"hi": {"kind": "text", "body": "Hola", "next": "missing"}}, "start_node": "hi"}
    with pytest.raises(ValidationError):
        repo.save_version(tenant_id=TENANT, menu_id=menu.id, definition=bad)
    assert repo.list_versions(tenant_id=TENANT, menu_id=menu.id) == []


def test_publish_stamps_the_version_once_and_points_the_menu(repo: MemoryMenuRepository) -> None:
    menu = repo.create_menu(tenant_id=TENANT, phone_number_row_id=PHONE, name="Principal")
    v1 = repo.save_version(tenant_id=TENANT, menu_id=menu.id, definition=_tiny())
    v2 = repo.save_version(tenant_id=TENANT, menu_id=menu.id, definition=BIANKI_DEMO_MENU)
    assert repo.get_published(tenant_id=TENANT, menu_id=menu.id) is None

    t1 = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    published = repo.publish_version(
        tenant_id=TENANT, menu_id=menu.id, version_id=v2.id, user_id=USER, now=t1
    )
    assert published.published_version_id == v2.id
    assert published.updated_at == t1
    assert repo.get_published(tenant_id=TENANT, menu_id=menu.id) == BIANKI_DEMO_MENU
    stamped = {v.id: v for v in repo.list_versions(tenant_id=TENANT, menu_id=menu.id)}
    assert (stamped[v2.id].published_at, stamped[v2.id].published_by_user_id) == (t1, USER)
    assert stamped[v1.id].published_at is None

    # Rolling back to v1 and forward again keeps v2's FIRST publication stamp.
    t2 = datetime(2026, 10, 14, 13, 0, tzinfo=UTC)
    repo.publish_version(tenant_id=TENANT, menu_id=menu.id, version_id=v1.id, user_id=USER, now=t2)
    repo.publish_version(tenant_id=TENANT, menu_id=menu.id, version_id=v2.id, user_id=USER, now=t2)
    stamped = {v.id: v for v in repo.list_versions(tenant_id=TENANT, menu_id=menu.id)}
    assert stamped[v2.id].published_at == t1
    assert stamped[v1.id].published_at == t2


def test_publishing_another_menu_on_the_same_number_demotes_the_live_one(
    repo: MemoryMenuRepository,
) -> None:
    a = repo.create_menu(tenant_id=TENANT, phone_number_row_id=PHONE, name="A")
    b = repo.create_menu(tenant_id=TENANT, phone_number_row_id=PHONE, name="B")
    va = repo.save_version(tenant_id=TENANT, menu_id=a.id, definition=_tiny())
    vb = repo.save_version(tenant_id=TENANT, menu_id=b.id, definition=BIANKI_DEMO_MENU)
    repo.publish_version(tenant_id=TENANT, menu_id=a.id, version_id=va.id, user_id=USER)
    assert repo.load_published_menu_for_phone(PHONE) == (va.definition, va.id)

    repo.publish_version(tenant_id=TENANT, menu_id=b.id, version_id=vb.id, user_id=USER)
    live = {
        m.name: m.published_version_id
        for m in repo.list_menus(tenant_id=TENANT, phone_number_row_id=PHONE)
    }
    assert live == {"A": None, "B": vb.id}
    assert repo.load_published_menu_for_phone(PHONE) == (BIANKI_DEMO_MENU, vb.id)


def test_a_paused_menu_is_not_loaded_for_the_number(repo: MemoryMenuRepository) -> None:
    menu = repo.create_menu(tenant_id=TENANT, phone_number_row_id=PHONE, name="Principal")
    v = repo.save_version(tenant_id=TENANT, menu_id=menu.id, definition=_tiny())
    assert repo.load_published_menu_for_phone(PHONE) is None  # nothing published yet
    repo.publish_version(tenant_id=TENANT, menu_id=menu.id, version_id=v.id, user_id=None)
    assert repo.load_published_menu_for_phone(PHONE) is not None

    paused = repo.set_paused(tenant_id=TENANT, menu_id=menu.id, paused=True)
    assert paused.is_paused is True
    assert repo.load_published_menu_for_phone(PHONE) is None
    # Still published: pausing is not unpublishing.
    assert repo.get_published(tenant_id=TENANT, menu_id=menu.id) is not None
    repo.set_paused(tenant_id=TENANT, menu_id=menu.id, paused=False)
    assert repo.load_published_menu_for_phone(PHONE) == (v.definition, v.id)


def test_unknown_menu_and_foreign_version_are_refused(repo: MemoryMenuRepository) -> None:
    menu = repo.create_menu(tenant_id=TENANT, phone_number_row_id=PHONE, name="Principal")
    other = repo.create_menu(tenant_id=TENANT, phone_number_row_id=PHONE, name="Otro")
    v_other = repo.save_version(tenant_id=TENANT, menu_id=other.id, definition=_tiny())
    with pytest.raises(MenuNotFound):
        repo.save_version(tenant_id=TENANT, menu_id=uuid4(), definition=_tiny())
    with pytest.raises(MenuNotFound):
        repo.publish_version(
            tenant_id=uuid4(), menu_id=menu.id, version_id=v_other.id, user_id=None
        )  # another tenant cannot see it
    with pytest.raises(MenuVersionNotFound):
        repo.publish_version(tenant_id=TENANT, menu_id=menu.id, version_id=v_other.id, user_id=None)
    assert repo.get_menu(tenant_id=uuid4(), menu_id=menu.id) is None


def test_menu_names_are_unique_per_number_case_insensitively(repo: MemoryMenuRepository) -> None:
    repo.create_menu(tenant_id=TENANT, phone_number_row_id=PHONE, name="Principal")
    with pytest.raises(ValueError):
        repo.create_menu(tenant_id=TENANT, phone_number_row_id=PHONE, name="PRINCIPAL")
    with pytest.raises(ValueError):
        repo.create_menu(tenant_id=TENANT, phone_number_row_id=PHONE, name="   ")
    # Same name on another number is fine.
    repo.create_menu(tenant_id=TENANT, phone_number_row_id=uuid4(), name="Principal")
    assert len(repo.list_menus(tenant_id=TENANT, phone_number_row_id=PHONE)) == 1

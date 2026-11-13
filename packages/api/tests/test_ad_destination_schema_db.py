"""Nullable rollout, real RLS and loss-aware reversible migration for m-24828975."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from packages.api.tests.test_ad_audience_db import audience_world as shared_audience_world
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from qualify_api.ads.wizard import list_promotion_sources
from qualify_api.tenancy.acting import acting_login
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db
audience_world = shared_audience_world


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[3]
        / "migrations/postgres/versions/0151_brand_ad_destination.py"
    )
    spec = importlib.util.spec_from_file_location("ad_destination_migration_0151", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def kit_scope() -> tuple[UUID, UUID]:
    tenant, brand, kit = uuid4(), uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant,
                name="Ad destination test",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="Destination brand"))
    with tenant_session(tenant) as session:
        session.execute(
            text("""INSERT INTO brand_kits(id,tenant_id,brand_id,language,tone_axes)
          VALUES(:id,:tenant,:brand,'es',CAST(:axes AS jsonb))"""),
            {
                "id": kit,
                "tenant": tenant,
                "brand": brand,
                "axes": json.dumps(
                    {
                        "formal_casual": 50,
                        "sober_enthusiastic": 50,
                        "technical_plain": 50,
                        "brief_elaborate": 50,
                    }
                ),
            },
        )
    return tenant, kit


def test_existing_brand_rollout_nullable_and_tenant_scoped_updates(
    kit_scope: tuple[UUID, UUID],
) -> None:
    tenant, kit = kit_scope
    with tenant_session(tenant) as session:
        assert (
            session.scalar(
                text("SELECT ads_destination_url FROM brand_kits WHERE id=:id"), {"id": kit}
            )
            is None
        )
        session.execute(
            text("UPDATE brand_kits SET ads_destination_url=:url WHERE id=:id"),
            {"url": "https://example.org/destination", "id": kit},
        )
    with tenant_session(uuid4()) as session:
        assert (
            session.execute(text("SELECT id FROM brand_kits WHERE id=:id"), {"id": kit}).first()
            is None
        )
        assert (
            session.execute(
                text(
                    "UPDATE brand_kits SET ads_destination_url='https://bad.invalid' WHERE id=:id"
                ),
                {"id": kit},
            ).rowcount
            == 0
        )
    with tenant_session(tenant) as session:
        assert (
            session.scalar(
                text("SELECT ads_destination_url FROM brand_kits WHERE id=:id"), {"id": kit}
            )
            == "https://example.org/destination"
        )


def test_guarded_downgrade_and_reupgrade_preserve_schema_and_existing_data(
    kit_scope: tuple[UUID, UUID],
) -> None:
    tenant, kit = kit_scope
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE brand_kits SET ads_destination_url='https://example.org/kept' WHERE id=:id"
            ),
            {"id": kit},
        )
    migration = _migration()
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                with Operations.context(MigrationContext.configure(connection)):
                    savepoint = connection.begin_nested()
                    with pytest.raises(DBAPIError, match="downgrade 0151 refused"):
                        migration.downgrade()
                    savepoint.rollback()
                    assert (
                        connection.scalar(
                            text("SELECT ads_destination_url FROM brand_kits WHERE id=:id"),
                            {"id": kit},
                        )
                        == "https://example.org/kept"
                    )
                    # Transaction-only cleanup permits testing the actual reversal without
                    # destroying any destination belonging to another test or inspected row.
                    connection.execute(text("UPDATE brand_kits SET ads_destination_url=NULL"))
                    migration.downgrade()
                    assert (
                        connection.scalar(
                            text("""SELECT count(*) FROM information_schema.columns
                      WHERE table_name='brand_kits' AND column_name='ads_destination_url'""")
                        )
                        == 0
                    )
                    migration.upgrade()
                    column = connection.execute(
                        text("""SELECT data_type,is_nullable,column_default
                      FROM information_schema.columns WHERE table_name='brand_kits'
                        AND column_name='ads_destination_url'""")
                    ).one()
                    assert tuple(column) == ("text", "YES", None)
                    policy = connection.execute(
                        text("""SELECT relrowsecurity,relforcerowsecurity
                      FROM pg_class WHERE oid='brand_kits'::regclass""")
                    ).one()
                    assert tuple(policy) == (True, True)
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
    with tenant_session(tenant) as session:
        assert (
            session.scalar(
                text("SELECT ads_destination_url FROM brand_kits WHERE id=:id"), {"id": kit}
            )
            == "https://example.org/kept"
        )


def test_selected_edited_copy_preloads_url_and_blocks_other_button_without_publishing_change(
    audience_world,
) -> None:
    ids, login, actor, _, _ = audience_world
    variant = uuid4()
    original = {
        "hook": "Hola",
        "caption": "Texto",
        "ads_cta_type": "LEARN_MORE",
        "ads_destination_url": "https://example.org/original",
    }
    edited = {**original, "ads_destination_url": "https://example.org/edited"}
    with tenant_session(ids["tenant_id"]) as session:
        session.execute(
            text("""INSERT INTO copy_variants
          (id,tenant_id,draft_id,ordinal,copy,edited_copy,model_id)
          VALUES(:id,:tenant,:draft,0,CAST(:copy AS jsonb),CAST(:edited AS jsonb),'fixture')"""),
            {
                "id": variant,
                "tenant": ids["tenant_id"],
                "draft": ids["content_draft_id"],
                "copy": json.dumps(original),
                "edited": json.dumps(edited),
            },
        )
        session.execute(
            text("UPDATE content_drafts SET selected_variant_id=:variant WHERE id=:draft"),
            {"variant": variant, "draft": ids["content_draft_id"]},
        )
    with acting_login(login):
        source = list_promotion_sources(
            tenant_id=ids["tenant_id"], content_draft_id=ids["content_draft_id"]
        )[0]
        assert source.default_link_url == edited["ads_destination_url"]
        assert source.ad_destination_fingerprint and not source.unavailable_reason
        published = source.source_media_id, source.caption, source.publish_attempt_id
        with tenant_session(ids["tenant_id"]) as session:
            session.execute(
                text("UPDATE copy_variants SET edited_copy=CAST(:edited AS jsonb) WHERE id=:id"),
                {
                    "edited": json.dumps({**edited, "ads_cta_type": "WHATSAPP_MESSAGE"}),
                    "id": variant,
                },
            )
        source = list_promotion_sources(
            tenant_id=ids["tenant_id"], content_draft_id=ids["content_draft_id"]
        )[0]
        assert "Más información" in source.unavailable_reason
        assert (source.source_media_id, source.caption, source.publish_attempt_id) == published

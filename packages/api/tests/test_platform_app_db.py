"""`ensure_platform_app` — the registration production's `migrate` runs on every deploy.

Regression for 2026-10-08: production had no `platform_apps` row (only the dev seed created
it), so every OAuth callback 500'd with `PlatformAppMissing` after Meta's consent screen.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from qualify_shared.db.admin import admin_session
from sqlalchemy import select

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.models import PlatformApp
from qualify_api.connections.platform_app import SECRET_REF, ensure_platform_app

REPO_ROOT = Path(__file__).resolve().parents[3]


def _settings(app_id: str, api_version: str) -> MetaOAuthSettings:
    return MetaOAuthSettings(
        app_id=app_id,
        app_secret="unused",
        redirect_uri="http://localhost/cb",
        state_secret="unused",
        api_version=api_version,
    )


@pytest.mark.db
def test_ensure_platform_app_is_idempotent_and_tracks_api_version() -> None:
    app_id = f"test-{uuid4().hex}"

    with admin_session() as session:
        assert ensure_platform_app(session, _settings(app_id, "v21.0")) == "created"
    with admin_session() as session:
        assert ensure_platform_app(session, _settings(app_id, "v21.0")) == "unchanged"
    with admin_session() as session:
        assert ensure_platform_app(session, _settings(app_id, "v22.0")) == "updated"

    with admin_session() as session:
        rows = session.scalars(select(PlatformApp).where(PlatformApp.app_id == app_id)).all()
    assert len(rows) == 1
    assert rows[0].api_version == "v22.0"
    assert rows[0].secret_ref == SECRET_REF


def test_production_migrate_registers_the_platform_app() -> None:
    # The seed never runs in production; `migrate` is the only step that can create the row.
    compose = (REPO_ROOT / "deploy" / "docker-compose.prod.yml").read_text()
    migrate = compose.split("\n  migrate:\n", 1)[1].split("\n  api:\n", 1)[0]
    assert "python -m qualify_api.connections.platform_app" in migrate

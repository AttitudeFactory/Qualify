"""ADR 39 amendment of 2026-11-13 (m-25019217): a piece of kind `own_media` — what the
owner published from «Publicar» — is exempt from the 90-day retention. `db` tests: the
rule is read from the database (`read_facts`, `_family_candidates`).

To prove the exemption is by KIND and not only by where the files live, the piece here
carries a file under `t/{tenant}/generated/{draft}/` dated well past the window: an
ordinary piece in that state is purged; the own-media piece is not.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentFormat, PostCategory
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import update

from qualify_api.creative import models as creative
from qualify_api.creative.own_media import (
    OwnMediaItem,
    OwnMediaPiece,
    create_own_media_piece,
)
from qualify_api.creative.retention import (
    RETENTION,
    exempt_ids,
    piece_prefix,
    purge_expired_pieces,
    read_facts,
    retention_of,
)
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
OLD = NOW - RETENTION - timedelta(days=30)


class _Gate:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def delete_prefix(self, tenant_id: UUID, prefix: str, *, execute: bool = False) -> object:
        self.calls.append(prefix)

        class _Found:
            keys: tuple[str, ...] = ("x",)
            total_bytes = 1
            objects = 1

        return _Found()


def _tenant() -> tuple[UUID, UUID, UUID]:
    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id, name=f"r-{tenant_id}", country="CO", timezone="UTC", currency="COP"
            )
        )
        session.flush()
        brand = Brand(tenant_id=tenant_id, name="b")
        user = User(tenant_id=tenant_id, email=f"r-{uuid4()}@p.co", display_name="U")
        session.add_all([brand, user])
        session.flush()
        return tenant_id, brand.id, user.id


def _own_piece(tenant_id: UUID, brand_id: UUID, user_id: UUID) -> UUID:
    with tenant_session(tenant_id) as session:
        draft_id, created = create_own_media_piece(
            session,
            tenant_id=tenant_id,
            piece=OwnMediaPiece(
                brand_id=brand_id,
                user_id=user_id,
                caption="hola",
                category=PostCategory.GALERIA,
                format=ContentFormat.FEED_4_5,
                approved_at=OLD,
                items=(OwnMediaItem(f"t/{tenant_id}/media/c/{uuid4()}", "image/jpeg", "image", 0),),
                request_key=uuid4(),
            ),
        )
        assert created
        # as if its file lived under generated/, dated past the window
        session.execute(
            update(creative.ImageAsset)
            .where(creative.ImageAsset.draft_id == draft_id)
            .values(object_key=piece_prefix(tenant_id, draft_id) + "a.jpg", created_at=OLD)
        )
        return draft_id


def test_an_own_media_piece_is_never_given_a_deadline_nor_purged() -> None:
    tenant_id, brand_id, user_id = _tenant()
    draft_id = _own_piece(tenant_id, brand_id, user_id)
    # the control: the very same rows with another kind ARE purged
    control = _own_piece(tenant_id, brand_id, user_id)
    with tenant_session(tenant_id) as session:
        brief_id = session.get(creative.ContentDraft, control).brief_id  # type: ignore[union-attr]
        session.execute(
            update(creative.ContentBrief)
            .where(creative.ContentBrief.id == brief_id)
            .values(kind="static_flyer")
        )
    with tenant_session(tenant_id) as session:
        assert exempt_ids(session, [draft_id]) == {draft_id}
        assert read_facts(session, tenant_id, [draft_id]) == {}
        assert retention_of(session, tenant_id, [draft_id], NOW) == {}
    gate = _Gate()
    report = purge_expired_pieces(tenant_id=tenant_id, gate=gate, now=NOW, execute=True)
    assert draft_id not in {piece.draft_id for piece in report.purged}
    assert piece_prefix(tenant_id, draft_id) not in gate.calls
    assert piece_prefix(tenant_id, control) in gate.calls
    with tenant_session(tenant_id) as session:
        draft = session.get(creative.ContentDraft, draft_id)
        assert draft is not None and draft.media_purged_at is None

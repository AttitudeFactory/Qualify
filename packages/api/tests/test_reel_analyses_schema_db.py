"""Migration 0119 (m-24921055, VE-03; ADR 44): the shared analysis of a public reel and
the parts of a video, against the live schema.

Pins the acceptance criteria of VE-03:

- the two global tables stay global: no column naming a tenant, a brand or a user, no RLS,
  no policy (ADR 44 F5, ADR 42 §6);
- `qualify_app` can only enqueue (column grants): it creates a `queued` row, a repeat is a
  no-op, and it can never write a result, a key or a cost, nor DELETE;
- `qualify_reels_worker` is NOBYPASSRLS, `qualify_creative_worker` sees nothing (ADR 41);
- the shape the worker relies on (provenance on `ok`, shots cascade with their analysis);
- per tenant: a part needs a parent of its own tenant, `part_index` is 1-6 and unique,
  deleting the parent deletes the parts, tenant B never sees tenant A's parts; a version
  can record its brief; a `shot_video` brief is accepted.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, ProgrammingError

from qualify_api.referentes.reel_analysis_types import ERROR_CODES, ERROR_MODEL_OUTPUT_CUT
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

ANALYSES = "public_reel_analyses"
SHOTS = "public_reel_analysis_shots"
_GLOBAL = (ANALYSES, SHOTS)
# Any of these fragments in a column name of a global table is a leak (ADR 42 §6).
_FORBIDDEN_FRAGMENTS = ("tenant", "brand", "user", "owner", "business", "requested_by")

_SHA = "a" * 64


@pytest.fixture(scope="module")
def owner() -> Iterator[Engine]:
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        yield engine
    finally:
        engine.dispose()


def _world() -> tuple[UUID, UUID]:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant,
                name="Parts test",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="Parts brand"))
    return tenant, brand


def _post_id() -> str:
    return f"C{uuid4().hex[:10]}"


def _enqueue(tenant: UUID, post_id: str, *, version: int = 1) -> UUID | None:
    """What the screen does: `INSERT … ON CONFLICT DO NOTHING RETURNING id` as qualify_app."""
    with tenant_session(tenant) as session:
        return session.scalar(
            text(
                f"INSERT INTO {ANALYSES} (network, post_id, analysis_version, post_url, "
                "pending_video_url, wanted_at) VALUES ('instagram', :p, :v, :u, :vu, now()) "
                "ON CONFLICT (network, post_id, analysis_version) DO NOTHING RETURNING id"
            ),
            {
                "p": post_id,
                "v": version,
                "u": f"https://www.instagram.com/reel/{post_id}/",
                "vu": "https://scontent.cdninstagram.com/v/x.mp4?sig=1",
            },
        )


# -- global tables stay global ---------------------------------------------------------


def test_global_tables_name_no_tenant_brand_or_user() -> None:
    with admin_session() as session:
        rows = session.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = ANY(:t)"
            ),
            {"t": list(_GLOBAL)},
        ).all()
    assert {row.table_name for row in rows} == set(_GLOBAL)
    leaks = [
        f"{row.table_name}.{row.column_name}"
        for row in rows
        if any(fragment in row.column_name for fragment in _FORBIDDEN_FRAGMENTS)
    ]
    assert not leaks, f"a global table names a business: {leaks}"


def test_global_tables_have_no_rls_and_no_policies() -> None:
    with admin_session() as session:
        flags = session.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = ANY(:t) AND relkind = 'r'"
            ),
            {"t": list(_GLOBAL)},
        ).all()
        policies = session.execute(
            text("SELECT tablename FROM pg_policies WHERE tablename = ANY(:t)"),
            {"t": list(_GLOBAL)},
        ).all()
    assert {(r.relname, r.relrowsecurity, r.relforcerowsecurity) for r in flags} == {
        (table, False, False) for table in _GLOBAL
    }
    assert policies == []


# -- qualify_app only enqueues ---------------------------------------------------------


def test_app_enqueues_a_queued_row_once_and_two_tenants_share_it(owner: Engine) -> None:
    (tenant_a, _), (tenant_b, _) = _world(), _world()
    post_id = _post_id()
    first = _enqueue(tenant_a, post_id)
    assert first is not None
    assert _enqueue(tenant_b, post_id) is None, "a repeat must not create a second row"
    assert _enqueue(tenant_a, post_id) is None
    with owner.connect() as conn:
        row = conn.execute(
            text(f"SELECT status, stage, attempts, model_calls FROM {ANALYSES} WHERE id = :i"),
            {"i": first},
        ).one()
    assert tuple(row) == ("queued", None, 0, 0)
    # A new analysis version is a new row, never a rewrite.
    assert _enqueue(tenant_a, post_id, version=2) is not None


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("status", "'ok'"),
        ("reel_sheet", "'{}'::jsonb"),
        ("source_key", "'public/reel-analyses/instagram/x/y/source/source.mp4'"),
        ("cost_usd", "0"),
    ],
)
def test_app_cannot_insert_a_result_column(column: str, value: str) -> None:
    tenant, _ = _world()
    with pytest.raises(ProgrammingError, match="permission denied"):
        with tenant_session(tenant) as session:
            session.execute(
                text(
                    f"INSERT INTO {ANALYSES} (network, post_id, analysis_version, post_url, "
                    f"{column}) VALUES ('instagram', :p, 1, 'https://x', {value})"
                ),
                {"p": _post_id()},
            )


def test_app_may_bump_wanted_at_but_not_update_state_nor_delete() -> None:
    tenant, _ = _world()
    analysis = _enqueue(tenant, _post_id())
    with tenant_session(tenant) as session:
        session.execute(
            text(f"UPDATE {ANALYSES} SET wanted_at = now() WHERE id = :i"), {"i": analysis}
        )
    for statement in (
        f"UPDATE {ANALYSES} SET status = 'ok' WHERE id = :i",
        f"UPDATE {ANALYSES} SET pending_video_url = 'https://evil' WHERE id = :i",
        f"DELETE FROM {ANALYSES} WHERE id = :i",
        f"DELETE FROM {SHOTS} WHERE analysis_id = :i",
    ):
        with pytest.raises(ProgrammingError, match="permission denied"):
            with tenant_session(tenant) as session:
                session.execute(text(statement), {"i": analysis})


def test_role_reach() -> None:
    with admin_session() as session:
        bypass = session.scalar(
            text("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'qualify_reels_worker'")
        )
        reach = {
            (role, table, privilege): session.scalar(
                text("SELECT has_table_privilege(:r, :t, :p)"),
                {"r": role, "t": table, "p": privilege},
            )
            for role in ("qualify_reels_worker", "qualify_creative_worker", "qualify_admin")
            for table in _GLOBAL
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
        }
    assert bypass is False
    for table in _GLOBAL:
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert reach[("qualify_reels_worker", table, privilege)], (table, privilege)
            assert not reach[("qualify_creative_worker", table, privilege)], (table, privilege)
            assert reach[("qualify_admin", table, privilege)] == (privilege == "SELECT")


# -- the shape the worker writes -------------------------------------------------------


def test_ok_requires_provenance_and_shots_cascade(owner: Engine) -> None:
    tenant, _ = _world()
    analysis = _enqueue(tenant, _post_id())
    with pytest.raises(IntegrityError, match="ck_pra_ok_provenance"):
        with owner.begin() as conn:
            conn.execute(
                text(f"UPDATE {ANALYSES} SET status = 'ok' WHERE id = :i"), {"i": analysis}
            )
    with pytest.raises(IntegrityError, match="ck_pra_status_error"):
        with owner.begin() as conn:
            conn.execute(
                text(f"UPDATE {ANALYSES} SET status = 'failed' WHERE id = :i"), {"i": analysis}
            )
    with pytest.raises(IntegrityError, match="ck_pra_covered"):
        with owner.begin() as conn:
            conn.execute(
                text(f"UPDATE {ANALYSES} SET covered_from_s = 0, covered_to_s = 61 WHERE id = :i"),
                {"i": analysis},
            )
    with owner.begin() as conn:
        conn.execute(
            text(
                f"UPDATE {ANALYSES} SET status = 'ok', stage = 'done', model_id = 'claude-haiku', "
                "prompt_version = '1', schema_version = '1', detector_version = '1', "
                "sampling_version = '1', source_sha256 = :sha, reel_sheet = '{}'::jsonb, "
                "finished_at = now(), pending_video_url = NULL WHERE id = :i"
            ),
            {"i": analysis, "sha": _SHA},
        )
        conn.execute(
            text(
                f"INSERT INTO {SHOTS} (analysis_id, shot_index, start_s, end_s, frame_keys, "
                "frame_times_s, people_presence, visible_faces) VALUES "
                "(:i, 0, 0, 2.5, ARRAY['k1','k2'], ARRAY[0.4, 2.1]::real[], 'observed', "
                "'not_observed')"
            ),
            {"i": analysis},
        )
    with pytest.raises(IntegrityError, match="ck_pras_times"):
        with owner.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {SHOTS} (analysis_id, shot_index, start_s, end_s) "
                    "VALUES (:i, 1, 3, 3)"
                ),
                {"i": analysis},
            )
    with owner.begin() as conn:
        conn.execute(text(f"DELETE FROM {ANALYSES} WHERE id = :i"), {"i": analysis})
        left = conn.scalar(
            text(f"SELECT count(*) FROM {SHOTS} WHERE analysis_id = :i"), {"i": analysis}
        )
    assert left == 0


def test_the_error_code_check_matches_the_code_list(owner: Engine) -> None:
    """0152 (m-24993025): every code the worker writes is accepted on a failed row —
    `model_output_cut` included — and anything else is refused."""
    tenant, _ = _world()
    analysis = _enqueue(tenant, _post_id())
    for code in ERROR_CODES:
        with owner.begin() as conn:
            conn.execute(
                text(f"UPDATE {ANALYSES} SET status = 'failed', error_code = :c WHERE id = :i"),
                {"i": analysis, "c": code},
            )
    assert ERROR_MODEL_OUTPUT_CUT in ERROR_CODES
    with pytest.raises(IntegrityError, match="ck_pra_error_code"):
        with owner.begin() as conn:
            conn.execute(
                text(f"UPDATE {ANALYSES} SET error_code = 'output_cut' WHERE id = :i"),
                {"i": analysis},
            )


# -- per tenant: the parts of a video --------------------------------------------------


def _brief(tenant: UUID, brand: UUID, *, kind: str = "clip") -> UUID:
    with tenant_session(tenant) as session:
        return session.scalar(
            text(
                "INSERT INTO content_briefs (tenant_id, brand_id, objective, topic, platform, "
                "format, intent, content_type, image_route, kind) VALUES (:t, :b, 'o', 't', "
                "'instagram', 'reel', 'i', 'video', 'r', :k) RETURNING id"
            ),
            {"t": tenant, "b": brand, "k": kind},
        )


def _draft(
    tenant: UUID, brand: UUID, *, parent: UUID | None = None, part: int | None = None
) -> UUID:
    draft_id = uuid4()
    brief = _brief(tenant, brand, kind="shot_video" if parent is None else "clip")
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "INSERT INTO content_drafts (id, tenant_id, brief_id, brand_id, status, "
                "parent_draft_id, part_index) VALUES (:d, :t, :brief, :b, 'drafting', :p, :i)"
            ),
            {"d": draft_id, "t": tenant, "brief": brief, "b": brand, "p": parent, "i": part},
        )
    return draft_id


def _children(tenant: UUID, parent: UUID) -> int:
    with tenant_session(tenant) as session:
        return session.scalar(
            text("SELECT count(*) FROM content_drafts WHERE parent_draft_id = :p"), {"p": parent}
        )


def test_parts_belong_to_their_parent_and_are_isolated_by_tenant(owner: Engine) -> None:
    (tenant_a, brand_a), (tenant_b, brand_b) = _world(), _world()
    parent = _draft(tenant_a, brand_a)
    _draft(tenant_a, brand_a, parent=parent, part=1)
    _draft(tenant_a, brand_a, parent=parent, part=2)
    assert _children(tenant_a, parent) == 2
    assert _children(tenant_b, parent) == 0, "tenant B must not see tenant A's parts"

    # A part on another tenant's draft has no parent to hang from.
    with pytest.raises(IntegrityError, match="fk_content_drafts_parent"):
        _draft(tenant_b, brand_b, parent=parent, part=1)
    with pytest.raises(IntegrityError, match="fk_content_drafts_parent"):
        _draft(tenant_a, brand_a, parent=uuid4(), part=1)
    with pytest.raises(IntegrityError, match="uq_content_drafts_part"):
        _draft(tenant_a, brand_a, parent=parent, part=2)
    with pytest.raises(IntegrityError, match="ck_content_drafts_part_index"):
        _draft(tenant_a, brand_a, parent=parent, part=7)
    with pytest.raises(IntegrityError, match="ck_content_drafts_part"):
        _draft(tenant_a, brand_a, parent=parent, part=None)

    # `qualify_app` cannot DELETE drafts (retention does, as the owner): delete as owner.
    with owner.begin() as conn:
        conn.execute(text("DELETE FROM content_drafts WHERE id = :p"), {"p": parent})
    assert _children(tenant_a, parent) == 0, "deleting the parent deletes its parts"


def test_a_draft_cannot_be_its_own_parent() -> None:
    tenant, brand = _world()
    draft = _draft(tenant, brand)
    with pytest.raises(IntegrityError, match="ck_content_drafts_not_own_parent"):
        with tenant_session(tenant) as session:
            session.execute(
                text(
                    "UPDATE content_drafts SET parent_draft_id = id, part_index = 1 WHERE id = :d"
                ),
                {"d": draft},
            )


def test_a_version_records_its_brief_of_the_same_tenant() -> None:
    (tenant_a, brand_a), (tenant_b, brand_b) = _world(), _world()
    draft = _draft(tenant_a, brand_a)
    own_brief = _brief(tenant_a, brand_a)
    foreign_brief = _brief(tenant_b, brand_b)

    def _version(brief: UUID, revision: int) -> None:
        with tenant_session(tenant_a) as session:
            session.execute(
                text(
                    "INSERT INTO piece_versions (tenant_id, brand_id, draft_id, revision, "
                    "brief_id) VALUES (:t, :b, :d, :r, :brief)"
                ),
                {"t": tenant_a, "b": brand_a, "d": draft, "r": revision, "brief": brief},
            )

    _version(own_brief, 1)
    with pytest.raises(IntegrityError, match="fk_piece_versions_brief"):
        _version(foreign_brief, 2)

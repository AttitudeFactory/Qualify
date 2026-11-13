"""Migration 0117 (m-24854845, ADR 42 §3 slice R3): public reels kept once for every
tenant, and the per-tenant rows derived from them.

Pins three things against the live schema:

- the four per-tenant tables isolate tenant A from tenant B through `tenant_session`
  (RLS ENABLE + FORCE + the NULLIF policy), including with the GUC reset to '';
- the global tables stay global: no column naming a tenant, a brand or a user, and no RLS
  (ADR 42 §6, «riesgo nuevo»);
- the idempotency keys the services will lean on (`ON CONFLICT`), and the composite FKs
  that stop a row from pointing at another tenant's brand, run or verdict.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

_TENANT_TABLES = (
    "brand_reel_verdicts",
    "brand_reel_runs",
    "brand_reel_ideas",
    "vendor_usage_events",
)
_GLOBAL_TABLES = ("reel_accounts", "public_reels", "vendor_balance", "vendor_payloads")


def _world() -> tuple[UUID, UUID]:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant,
                name="Reels test",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="Reels brand"))
    return tenant, brand


@pytest.fixture
def two_tenants() -> Iterator[tuple[tuple[UUID, UUID], tuple[UUID, UUID]]]:
    yield _world(), _world()


def _reel_id() -> str:
    return f"C{uuid4().hex[:10]}"


def _seed_tenant_rows(tenant: UUID, brand: UUID) -> dict[str, UUID]:
    """One row in each per-tenant table, written through the tenant's own session."""
    reel = _reel_id()
    with tenant_session(tenant) as session:
        verdict = session.scalar(
            text(
                "INSERT INTO brand_reel_verdicts (tenant_id, brand_id, network, reel_id, "
                "brief_hash, input_hash, affinity, fits, format, hook, reason, model_id, "
                "prompt_version, effort, cost_usd) VALUES (:t, :b, 'instagram', :r, 'bh', "
                "'ih', 'producto', true, 'tutorial', 'pregunta', 'ok', 'claude-sonnet-5', "
                "'1', 'low', 0.001) RETURNING id"
            ),
            {"t": tenant, "b": brand, "r": reel},
        )
        run = session.scalar(
            text(
                "INSERT INTO brand_reel_runs (tenant_id, brand_id, trigger, run_date, days, "
                "pipeline_version) VALUES (:t, :b, 'weekly', :d, 30, 'r3-test') RETURNING id"
            ),
            {"t": tenant, "b": brand, "d": date(2026, 11, 2)},
        )
        idea = session.scalar(
            text(
                "INSERT INTO brand_reel_ideas (tenant_id, brand_id, run_id, network, reel_id, "
                "rank, window_days, verdict_id) VALUES (:t, :b, :run, 'instagram', :r, 1, 30, "
                ":v) RETURNING id"
            ),
            {"t": tenant, "b": brand, "run": run, "r": reel, "v": verdict},
        )
        usage = session.scalar(
            text(
                "INSERT INTO vendor_usage_events (tenant_id, brand_id, vendor, feature, "
                "credits, usd_estimate, request_key) VALUES (:t, :b, 'scrapecreators', "
                "'reels_list', 1, 0.002, :k) RETURNING id"
            ),
            {"t": tenant, "b": brand, "k": f"req-{uuid4()}"},
        )
    return {
        "brand_reel_verdicts": verdict,
        "brand_reel_runs": run,
        "brand_reel_ideas": idea,
        "vendor_usage_events": usage,
    }


def _visible(tenant: UUID, table: str, row_id: UUID) -> int:
    with tenant_session(tenant) as session:
        return session.scalar(text(f"SELECT count(*) FROM {table} WHERE id = :id"), {"id": row_id})


def test_tenant_a_cannot_read_tenant_b_rows_in_the_four_rls_tables(two_tenants) -> None:
    (tenant_a, brand_a), (tenant_b, brand_b) = two_tenants
    rows_a = _seed_tenant_rows(tenant_a, brand_a)
    rows_b = _seed_tenant_rows(tenant_b, brand_b)
    for table in _TENANT_TABLES:
        assert _visible(tenant_a, table, rows_a[table]) == 1, table
        assert _visible(tenant_a, table, rows_b[table]) == 0, table
        assert _visible(tenant_b, table, rows_b[table]) == 1, table
        assert _visible(tenant_b, table, rows_a[table]) == 0, table
    # A reused pooled connection resets the GUC to '': the NULLIF form filters to nothing
    # instead of raising on ''::uuid.
    with tenant_session(tenant_a) as session:
        session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        for table in _TENANT_TABLES:
            assert session.scalar(text(f"SELECT count(*) FROM {table}")) == 0, table


def test_rls_is_enabled_and_forced_on_the_four_tables() -> None:
    with admin_session() as session:
        rows = session.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = ANY(:names) AND relkind = 'r'"
            ),
            {"names": list(_TENANT_TABLES)},
        ).all()
    assert {row.relname: (row.relrowsecurity, row.relforcerowsecurity) for row in rows} == {
        table: (True, True) for table in _TENANT_TABLES
    }


def test_writing_a_row_for_another_tenant_is_refused(two_tenants) -> None:
    (tenant_a, brand_a), (tenant_b, _) = two_tenants
    # WITH CHECK: tenant B's session cannot write a row stamped with tenant A.
    with pytest.raises(ProgrammingError), tenant_session(tenant_b) as session:
        session.execute(
            text(
                "INSERT INTO vendor_usage_events (tenant_id, vendor, feature, credits, "
                "request_key) VALUES (:t, 'scrapecreators', 'profile', 1, 'x')"
            ),
            {"t": tenant_a},
        )
    # Composite FK: tenant B cannot hang its own row on tenant A's brand.
    with pytest.raises(IntegrityError), tenant_session(tenant_b) as session:
        session.execute(
            text(
                "INSERT INTO brand_reel_runs (tenant_id, brand_id, trigger, run_date, days, "
                "pipeline_version) VALUES (:t, :b, 'manual', :d, 30, 'r3-test')"
            ),
            {"t": tenant_b, "b": brand_a, "d": date(2026, 11, 3)},
        )


def test_an_idea_cannot_point_at_another_brands_run(two_tenants) -> None:
    (tenant, brand), _ = two_tenants
    rows = _seed_tenant_rows(tenant, brand)
    other_brand = uuid4()
    with admin_session() as session:
        session.add(Brand(id=other_brand, tenant_id=tenant, name="Second brand"))
    with pytest.raises(IntegrityError), tenant_session(tenant) as session:
        session.execute(
            text(
                "INSERT INTO brand_reel_ideas (tenant_id, brand_id, run_id, network, reel_id, "
                "rank, window_days) VALUES (:t, :b, :run, 'tiktok', '123', 1, 30)"
            ),
            {"t": tenant, "b": other_brand, "run": rows["brand_reel_runs"]},
        )


def test_an_idea_cannot_point_at_another_brands_verdict(two_tenants) -> None:
    """Same tenant, two brands: the idea's own run is fine, the verdict is the other
    brand's — the (verdict_id, tenant_id, brand_id) FK refuses it."""
    (tenant, brand), _ = two_tenants
    other_brand = uuid4()
    with admin_session() as session:
        session.add(Brand(id=other_brand, tenant_id=tenant, name="Second brand"))
    rows = _seed_tenant_rows(tenant, brand)
    other_rows = _seed_tenant_rows(tenant, other_brand)
    with pytest.raises(IntegrityError), tenant_session(tenant) as session:
        session.execute(
            text(
                "INSERT INTO brand_reel_ideas (tenant_id, brand_id, run_id, network, reel_id, "
                "rank, window_days, verdict_id) VALUES (:t, :b, :run, 'tiktok', '456', 2, 30, "
                ":v)"
            ),
            {
                "t": tenant,
                "b": brand,
                "run": rows["brand_reel_runs"],
                "v": other_rows["brand_reel_verdicts"],
            },
        )


def test_idempotency_keys_make_repeats_no_ops(two_tenants) -> None:
    (tenant, brand), _ = two_tenants
    key = f"req-{uuid4()}"
    run_sql = text(
        "INSERT INTO brand_reel_runs (tenant_id, brand_id, trigger, run_date, days, "
        "pipeline_version) VALUES (:t, :b, 'manual', :d, 30, 'r3-test') "
        "ON CONFLICT (brand_id, trigger, run_date) DO NOTHING RETURNING id"
    )
    usage_sql = text(
        "INSERT INTO vendor_usage_events (tenant_id, vendor, feature, credits, request_key) "
        "VALUES (:t, 'scrapecreators', 'reels_list', 1, :k) "
        "ON CONFLICT (tenant_id, request_key) DO NOTHING RETURNING id"
    )
    params = {"t": tenant, "b": brand, "d": date(2026, 11, 4), "k": key}
    with tenant_session(tenant) as session:
        assert session.execute(run_sql, params).first() is not None
        assert session.execute(run_sql, params).first() is None  # the double click
        assert session.execute(usage_sql, params).first() is not None
        assert session.execute(usage_sql, params).first() is None
    # The same request key in another tenant is its own event, not a conflict.
    other, _ = _world()
    with tenant_session(other) as session:
        assert session.execute(usage_sql, {**params, "t": other}).first() is not None


def test_usage_events_are_append_only_for_the_app(two_tenants) -> None:
    (tenant, brand), _ = two_tenants
    rows = _seed_tenant_rows(tenant, brand)
    for statement in (
        "UPDATE vendor_usage_events SET credits = 0 WHERE id = :id",
        "DELETE FROM vendor_usage_events WHERE id = :id",
    ):
        with pytest.raises(ProgrammingError), tenant_session(tenant) as session:
            session.execute(text(statement), {"id": rows["vendor_usage_events"]})


def test_global_tables_name_no_tenant_brand_or_user_and_carry_no_rls() -> None:
    with admin_session() as session:
        columns = session.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = ANY(:names)"
            ),
            {"names": list(_GLOBAL_TABLES)},
        ).all()
        flags = session.execute(
            text(
                "SELECT relname, relrowsecurity FROM pg_class "
                "WHERE relname = ANY(:names) AND relkind = 'r'"
            ),
            {"names": list(_GLOBAL_TABLES)},
        ).all()
        policies = session.scalar(
            text("SELECT count(*) FROM pg_policies WHERE tablename = ANY(:names)"),
            {"names": list(_GLOBAL_TABLES)},
        )
    assert {row.table_name for row in columns} == set(_GLOBAL_TABLES)
    offenders = [
        f"{row.table_name}.{row.column_name}"
        for row in columns
        if any(word in row.column_name for word in ("tenant", "brand", "user", "member"))
    ]
    assert not offenders, f"a global table names who asked: {offenders}"
    assert all(not row.relrowsecurity for row in flags)
    assert policies == 0


def test_a_public_reel_is_shared_and_its_metrics_only_move_forward(two_tenants) -> None:
    (tenant_a, _), (tenant_b, _) = two_tenants
    reel = _reel_id()
    now = datetime.now(UTC)
    upsert = text(
        "INSERT INTO public_reels (network, reel_id, handle, views, metrics_at, video_url, "
        "video_url_at, transcript_segments, transcript_reader_version, parser_version) "
        "VALUES ('instagram', :r, 'cuenta.publica', :views, :at, 'https://cdn.example/v.mp4', "
        ":at, CAST(:segments AS jsonb), 1, 1) "
        "ON CONFLICT (network, reel_id) DO UPDATE SET views = EXCLUDED.views, "
        "metrics_at = EXCLUDED.metrics_at WHERE EXCLUDED.metrics_at > public_reels.metrics_at"
    )
    segments = '[{"start": 0.0, "end": 1.5, "text": "hola"}]'
    with tenant_session(tenant_a) as session:
        session.execute(upsert, {"r": reel, "views": 100, "at": now, "segments": segments})
    with tenant_session(tenant_b) as session:
        # A late retry with older metrics never overwrites newer state.
        session.execute(
            upsert,
            {"r": reel, "views": 5, "at": now - timedelta(hours=1), "segments": segments},
        )
        row = session.execute(
            text(
                "SELECT views, transcript_segments FROM public_reels "
                "WHERE network = 'instagram' AND reel_id = :r"
            ),
            {"r": reel},
        ).one()
    assert row.views == 100
    assert row.transcript_segments == [{"start": 0.0, "end": 1.5, "text": "hola"}]
    with admin_session() as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM public_reels WHERE reel_id = :r"), {"r": reel}
            )
            == 1
        )


def test_public_reel_checks_reject_incoherent_rows(two_tenants) -> None:
    (tenant, _), _ = two_tenants
    with tenant_session(tenant) as session:
        payload = session.scalar(
            text(
                "INSERT INTO vendor_payloads (vendor, path, params_key, fetched_at, expires_at) "
                "VALUES ('scrapecreators', '/v1/test', :k, now(), now() + interval '7 days') "
                "RETURNING id"
            ),
            {"k": f"r3-{uuid4()}"},
        )
    bad_rows = (
        # A URL without the moment it was read.
        (
            "ck_public_reel_video_url",
            "INSERT INTO public_reels (network, reel_id, handle, metrics_at, video_url, "
            "parser_version) VALUES ('tiktok', :r, 'cuenta', now(), 'https://x', 1)",
        ),
        # Segments without the reader version that parsed them.
        (
            "ck_public_reel_transcript_segments",
            "INSERT INTO public_reels (network, reel_id, handle, metrics_at, "
            "transcript_segments, parser_version) VALUES ('tiktok', :r, 'cuenta', now(), "
            "'[]'::jsonb, 1)",
        ),
        # A handle that is not normalized.
        (
            "ck_public_reel_handle_normalized",
            "INSERT INTO public_reels (network, reel_id, handle, metrics_at, parser_version) "
            "VALUES ('tiktok', :r, '@Cuenta', now(), 1)",
        ),
        # A real source payload, but not the fetch it came from (the payload row is
        # upserted in place, so the id alone does not pin it).
        (
            "ck_public_reel_source_payload",
            "INSERT INTO public_reels (network, reel_id, handle, metrics_at, "
            "source_payload_id, parser_version) VALUES ('tiktok', :r, 'cuenta', now(), :p, 1)",
        ),
    )
    for constraint, statement in bad_rows:
        with (
            pytest.raises(IntegrityError, match=constraint),
            tenant_session(tenant) as session,
        ):
            session.execute(text(statement), {"r": _reel_id(), "p": payload})

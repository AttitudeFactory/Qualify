"""Isolated real-DB worker tick with synthetic fixtures and GET-only MockTransport.

Run through ads-reads-workload-memory.sh; no real Meta credential is used. Fixture
definitions are loaded from the existing DB tests without importing pytest or tests.
The measured process includes fixture setup, making its peak a conservative estimate.
"""

from __future__ import annotations

import ast
import asyncio
import gc
import json
import resource
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from qualify_api.ads import account_health, reads_cli, results_service
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.sql.elements import TextClause


def fixtures() -> dict[str, Any]:
    path = Path("/fixtures/test_ad_results_db.py")
    original = ast.parse(path.read_text())
    selected = []
    for node in original.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import) and any(x.name == "pytest" for x in node.names):
                continue
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PUBLISHED_CAPTION"
            for target in node.targets
        ):
            selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in ("audience_world", "result_world"):
            node.decorator_list = []
            selected.append(node)
    namespace = {}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


async def main() -> None:
    namespace = fixtures()
    world = namespace["audience_world"]()
    ids, login, *_ = world
    fixture_index = 0

    def fixture_text(statement: str) -> TextClause:
        # Assign each synthetic remote identity once, preserving the immutable-ID trigger.
        if statement.startswith("UPDATE ad_promotions SET meta_campaign_id="):
            for original, replacement in ((1, 1000), (2, 1001), (3, 1002)):
                statement = statement.replace(
                    f"='{original}'", f"='{replacement + fixture_index * 3}'"
                )
        return text(statement)

    namespace["text"] = fixture_text
    with namespace["acting_login"](login):
        for index in range(100):
            fixture_index = index
            namespace["result_world"](world, SimpleNamespace(param="777"))
    account = ids["meta_account_id"]
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
    calls = 0

    def response(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.method != "GET":
            raise AssertionError("Meta write attempted by read-only worker")
        calls += 1
        ad_id = request.url.path.split("/")[-2 if request.url.path.endswith("/insights") else -1]
        if request.url.path.endswith("/insights"):
            payload = {
                "data": [
                    {
                        "ad_id": ad_id,
                        "account_id": account,
                        "account_currency": "COP",
                        "date_start": (yesterday - timedelta(days=day)).isoformat(),
                        "date_stop": (yesterday - timedelta(days=day)).isoformat(),
                        "spend": "1523.45",
                        "clicks": "7",
                        "reach": "40",
                    }
                    for day in range(28)
                ]
            }
        elif "/act_" in request.url.path:
            payload = {
                "account_id": account,
                "currency": "COP",
                "account_status": 1,
                "disable_reason": 0,
                "funding_source": "42",
                "amount_spent": "100",
                "spend_cap": "100000",
            }
        else:
            payload = {
                "id": ad_id,
                "account_id": account,
                "campaign_id": str(int(ad_id) - 2),
                "adset_id": str(int(ad_id) - 1),
                "status": "ACTIVE",
                "effective_status": "ACTIVE",
            }
        return httpx.Response(200, json=payload)

    async def client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(response))

    account_health._authenticated_client = client
    results_service._authenticated_client = client
    totals = await reads_cli.tick(ids["tenant_id"], limit=100)
    assert totals["checked"] == 100 and totals["unavailable"] == 0, totals
    first_calls = calls
    cached = await reads_cli.tick(ids["tenant_id"], limit=100)
    assert cached["checked"] == 0 and calls == first_calls, cached
    # Make only result observations due again; daily health must stay cached.
    with tenant_session(ids["tenant_id"]) as session:
        session.execute(
            text(
                "UPDATE ad_promotion_observations SET "
                "refresh_started_at=now()-interval '26 minutes'"
            )
        )
    repeated = await reads_cli.tick(ids["tenant_id"], limit=100)
    assert repeated["checked"] == 100 and repeated["unavailable"] == 0, repeated
    assert calls == first_calls + 200
    gc.collect()
    await asyncio.sleep(1)
    with tenant_session(ids["tenant_id"]) as session:
        stored = session.scalar(text("SELECT count(*) FROM ad_promotion_insights"))
    assert stored == 2800
    print(
        json.dumps(
            {
                "phase": "100_promotions_28_days_and_cached_tick",
                "totals": totals,
                "get_requests": calls,
                "repeated_totals": repeated,
                "stored_daily_rows": stored,
                "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
                "cgroup_peak_bytes": int(Path("/sys/fs/cgroup/memory.peak").read_text()),
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())

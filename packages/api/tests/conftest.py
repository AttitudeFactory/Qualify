"""Fixtures for the `db`-marked tenancy tests. These need the local Postgres from
docker-compose (migrated + roles created), so they run in CI via service containers,
never as pure unit tests."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.config import app_dsn
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine

from qualify_api.tenancy.models import Brand, Tenant

TENANT_A = UUID("c0000000-0000-4000-8000-00000000000a")
TENANT_B = UUID("d0000000-0000-4000-8000-00000000000b")


@pytest.fixture
def seeded_ab() -> tuple[UUID, UUID]:
    """Two tenants, each with one brand, inserted via the BYPASSRLS admin door.
    Idempotent so local re-runs of `just test-db` don't accumulate rows."""
    with admin_session() as session:
        for tenant_id, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tenant_id) is None:
                session.add(
                    Tenant(
                        id=tenant_id,
                        name=f"tenant-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
            if session.scalar(select(Brand).where(Brand.tenant_id == tenant_id)) is None:
                session.add(Brand(tenant_id=tenant_id, name=f"brand-{name}"))
                session.flush()
    return TENANT_A, TENANT_B


@pytest.fixture
def app_engine() -> Iterator[Engine]:
    """A raw `qualify_app` engine for tests that must observe RLS behavior WITHOUT the
    `app.tenant_id` GUC set (fail-closed, GUC-bleed). Test code may build engines; the
    C-01 static test only forbids it in `src/`."""
    engine = create_engine(app_dsn())
    try:
        yield engine
    finally:
        engine.dispose()


class FakeAsyncRedis:
    """In-memory stand-in for the `redis.asyncio` surface `inbox/sync_guard.py` uses —
    `set` (NX/PX/EX), `get`, and `eval` of its two compare-and-* scripts — with real
    expiry against a clock the test controls. Offline: CI's `test` job has no Redis."""

    def __init__(self) -> None:
        self.now = 0.0  # seconds; advance it to expire keys
        self._data: dict[str, tuple[str, float | None]] = {}
        self.fail_with: Exception | None = None  # set to make every call raise

    def _live(self, key: str) -> str | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and self.now >= expires_at:
            del self._data[key]
            return None
        return value

    def _check(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with

    async def set(
        self,
        name: str,
        value: str,
        *,
        nx: bool = False,
        px: int | None = None,
        ex: int | None = None,
    ) -> bool | None:
        self._check()
        if nx and self._live(name) is not None:
            return None
        ttl = px / 1000 if px is not None else ex
        self._data[name] = (value, self.now + ttl if ttl is not None else None)
        return True

    async def get(self, name: str) -> str | None:
        self._check()
        return self._live(name)

    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> object:
        self._check()
        key, token, *rest = keys_and_args
        if self._live(key) != token:
            return 0
        if "pexpire" in script:
            self._data[key] = (token, self.now + int(rest[0]) / 1000)
            return 1
        del self._data[key]
        return 1

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake_async_redis() -> FakeAsyncRedis:
    return FakeAsyncRedis()


# --------------------------------------------------------------------------------------
# Meegle Event Listener bodies (plan-altas-meegle M1) — shared by the envelope, route,
# handler and intake tests. A plain fixture because test modules cannot import each other
# here (importlib mode, no __init__.py).
# --------------------------------------------------------------------------------------


class MeegleEvents:
    """Builds bodies shaped like the Event Listener docs (`Complete Node 2001`), signed."""

    PLUGIN_ID = "MII_TEST"
    TOKEN = "callback-token"
    REQUEST_TIME = 1730184005453
    IDEMPOTENT = "90d94fba3a8f14e372b0a0e7446fefc761056ef3dcf9d777271cc1c16b10c5d6"
    WORK_ITEM_TYPE = "alta_cliente"
    PROJECT_KEY = "proj-test"

    def data(
        self,
        *,
        event_type: int = 2001,
        work_item_id: int | None = 5390584662,
        nodes: list[str] | None = None,
        idempotent_key: str | None = IDEMPOTENT,
        work_item_type: str = WORK_ITEM_TYPE,
    ) -> dict:
        payload: dict = {
            "event_type": event_type,
            "is_batch_check": False,
            "project_key": self.PROJECT_KEY,
            "flow_type": 0,
            "work_item_type_key": work_item_type,
            "user_info": {"user_key": "7697105028321938981"},
        }
        if idempotent_key is not None:
            payload["idempotent_key"] = idempotent_key
        if work_item_id is not None:
            payload["work_item_info"] = [
                {
                    "work_item_id": work_item_id,
                    "work_item_name": "Arepera La Nona",
                    "work_item_type_key": work_item_type,
                }
            ]
        if nodes is not None:
            payload["node_info"] = {"update_nodes": nodes, "reason": ""}
        return payload

    def body(
        self,
        *,
        source: str = "normal",
        request_time: object = REQUEST_TIME,
        signature: str | None = None,
        **data_kwargs: object,
    ) -> bytes:
        import json

        from qualify_api.meegle.envelope import event_signature

        if signature is None:
            signature = event_signature(
                plugin_id=self.PLUGIN_ID, request_time=request_time, callback_token=self.TOKEN
            )
        payload = {
            "log_id": "2026XXXX",
            "request_time": request_time,
            "signature": signature,
            "source": source,
            "source_plug-in_id": self.PLUGIN_ID,
            "data": self.data(**data_kwargs),  # type: ignore[arg-type]
        }
        return json.dumps(payload).encode("utf-8")

    def value(self, *, source: str = "normal", **data_kwargs: object) -> dict:
        """What the intake records as the change's `value` (`parse_meegle_delivery`)."""
        return {"source": source, "data": self.data(**data_kwargs)}  # type: ignore[arg-type]


@pytest.fixture
def meegle_events() -> MeegleEvents:
    return MeegleEvents()

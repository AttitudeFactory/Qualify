"""WA-05: the administrative connect of a WhatsApp number, fully offline.

Every side effect is a Protocol (`debug_token`, the Graph client, both repositories, the
event publisher), so this file pins the decision tree with fakes and no network, no DB:

- success creates connection + credential + phone row and ends `active`;
- a token without both scopes, or `is_valid=false`, writes NOTHING (exit 2);
- a token Meta rejects on the Graph call writes NOTHING (exit 3);
- a second run rotates the credential (version 2), refreshes metadata, keeps ONE
  connection and ONE phone row, and fires no second `activated` event;
- a run on a `degraded` row reconnects it;
- the token never reaches stdout/stderr.

The Postgres-backed halves (`persist_grant`, the phone upsert under RLS) are proven by the
`db` suite of the connections module and CI's `test-db` job; the fakes here preserve the
two invariants that matter — natural-key uniqueness and append-only credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.events import DomainEventName, InMemoryEventPublisher
from qualify_api.connections.repository import ConnectionRecord, GrantInput
from qualify_api.connections.token_health import TokenHealthReport
from qualify_api.whatsapp import connect as connect_mod
from qualify_api.whatsapp.client import PhoneNumberInfo, WhatsAppApiError
from qualify_api.whatsapp.connect import (
    EXIT_API_ERROR,
    EXIT_AUTH_ERROR,
    EXIT_OK,
    EXIT_TOKEN_REJECTED,
    EXIT_USAGE,
    REQUIRED_SCOPES,
    TOKEN_ENV,
    PhoneNumberMismatch,
    ScopesMissing,
    TokenRejected,
    connect_whatsapp_number,
)
from qualify_api.whatsapp.phone_numbers import PhoneNumberUpsert

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
BRAND = UUID("b0000000-0000-4000-8000-000000000001")
USER = UUID("d0000000-0000-4000-8000-000000000001")
APP_ROW_ID = UUID("e0000000-0000-4000-8000-000000000001")
WABA_ID = "1234567890"
PHONE_NUMBER_ID = "987654321098765"
TOKEN = "EAAB-system-user-token-never-shown"  # a fake, the shape is irrelevant
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
SETTINGS = MetaOAuthSettings(
    app_id="app", app_secret="secret", redirect_uri="http://x", state_secret="s"
)


# --- fakes ------------------------------------------------------------------------------


@dataclass
class FakeTokenHealth:
    is_valid: bool = True
    scopes: tuple[str, ...] = tuple(sorted(REQUIRED_SCOPES))
    calls: int = 0

    def debug_token(self, token: str) -> TokenHealthReport:
        self.calls += 1
        assert token == TOKEN
        return TokenHealthReport(
            is_valid=self.is_valid, expires_at=None, data_access_expires_at=None, scopes=self.scopes
        )


@dataclass
class FakeWhatsAppClient:
    info: PhoneNumberInfo | None = None
    error: WhatsAppApiError | None = None

    async def get_phone_number(self) -> PhoneNumberInfo:
        if self.error is not None:
            raise self.error
        assert self.info is not None
        return self.info


@dataclass
class StoredConnection:
    connection_id: UUID
    grant: GrantInput
    status: str
    credential_version: int
    last_verified_at: datetime | None = None


@dataclass
class FakeRepository:
    """Same shape as `test_oauth_callback.FakeRepository`: unique natural key,
    append-only credentials."""

    connections: dict[tuple[UUID, str, str], StoredConnection] = field(default_factory=dict)
    credentials: list[tuple[UUID, int, bytes]] = field(default_factory=list)
    events: list[tuple[UUID, str]] = field(default_factory=list)

    def platform_app_id(self, app_id: str, *, tenant_id: UUID) -> UUID:
        return APP_ROW_ID

    def persist_grant(self, grant: GrantInput) -> ConnectionRecord:
        key = (grant.tenant_id, grant.platform, grant.external_account_id)
        existing = self.connections.get(key)
        previous_status = existing.status if existing else None
        if existing is None:
            existing = StoredConnection(
                connection_id=uuid4(), grant=grant, status="pending", credential_version=0
            )
            self.connections[key] = existing
        else:
            existing.grant = grant
        version = existing.credential_version + 1
        existing.credential_version = version
        self.credentials.append((existing.connection_id, version, grant.ciphertext))
        self.events.append(
            (existing.connection_id, "granted" if previous_status is None else "reconnected")
        )
        return ConnectionRecord(
            connection_id=existing.connection_id,
            tenant_id=grant.tenant_id,
            credential_version=version,
            previous_status=previous_status,
        )

    def record_status(
        self,
        *,
        connection_id: UUID,
        tenant_id: UUID,
        status: str,
        verified_at: datetime | None,
        event_type: str,
        credential_version: int,
    ) -> None:
        for stored in self.connections.values():
            if stored.connection_id == connection_id:
                stored.status = status
                if verified_at is not None:
                    stored.last_verified_at = verified_at
        self.events.append((connection_id, event_type))

    def record_health_check(self, **_: object) -> None:  # not used by connect
        raise AssertionError("connect must not call record_health_check")

    def only(self) -> StoredConnection:
        assert len(self.connections) == 1, f"expected one connection, got {len(self.connections)}"
        return next(iter(self.connections.values()))


@dataclass
class FakePhoneNumbers:
    rows: dict[str, PhoneNumberUpsert] = field(default_factory=dict)
    upserts: int = 0

    def upsert(self, record: PhoneNumberUpsert) -> bool:
        self.upserts += 1
        created = record.phone_number_id not in self.rows
        self.rows[record.phone_number_id] = record
        return created


def _info(**overrides: object) -> PhoneNumberInfo:
    values: dict[str, object] = {
        "id": PHONE_NUMBER_ID,
        "verified_name": "Bianki",
        "display_phone_number": "+57 300 1234567",
        "quality_rating": "GREEN",
        "messaging_limit_tier": "TIER_1K",
        "name_status": "APPROVED",
        "status": "CONNECTED",
        "code_verification_status": "VERIFIED",
    }
    values.update(overrides)
    return PhoneNumberInfo(**values)  # type: ignore[arg-type]


@dataclass
class Harness:
    repo: FakeRepository = field(default_factory=FakeRepository)
    phones: FakePhoneNumbers = field(default_factory=FakePhoneNumbers)
    publisher: InMemoryEventPublisher = field(default_factory=InMemoryEventPublisher)
    encryptor: DevEncryptor = field(default_factory=DevEncryptor)
    health: FakeTokenHealth = field(default_factory=FakeTokenHealth)
    client: FakeWhatsAppClient = field(default_factory=lambda: FakeWhatsAppClient(info=_info()))

    async def run(self, *, brand_id: UUID | None = BRAND, now: datetime = NOW):
        return await connect_whatsapp_number(
            tenant_id=TENANT,
            brand_id=brand_id,
            user_id=USER,
            waba_id=WABA_ID,
            phone_number_id=PHONE_NUMBER_ID,
            token=TOKEN,
            settings=SETTINGS,
            encryptor=self.encryptor,
            repository=self.repo,
            phone_numbers_repo=self.phones,
            token_health=self.health,
            whatsapp_client=self.client,
            publisher=self.publisher,
            clock=lambda: now,
        )

    def assert_nothing_written(self) -> None:
        assert self.repo.connections == {}
        assert self.repo.credentials == []
        assert self.repo.events == []
        assert self.phones.rows == {}
        assert self.publisher.events == []


# --- the pure orchestration ----------------------------------------------------------


async def test_success_creates_connection_credential_and_phone_row_and_activates() -> None:
    h = Harness()
    outcome = await h.run()

    stored = h.repo.only()
    assert outcome.connection_id == stored.connection_id
    assert outcome.status == "active" == stored.status
    assert outcome.created_connection is True
    assert outcome.created_phone_number is True
    assert outcome.credential_version == 1
    assert outcome.display_phone_number == "+57 300 1234567"
    assert outcome.verified_name == "Bianki"
    assert stored.last_verified_at == NOW

    grant = stored.grant
    assert grant.platform == "whatsapp"
    assert grant.account_type == "waba_phone_number"
    assert grant.external_account_id == PHONE_NUMBER_ID
    assert grant.external_username == "+57 300 1234567"
    assert grant.linked_page_id is None
    assert set(grant.granted_scopes) == REQUIRED_SCOPES
    assert grant.token_type == "system_user"
    assert grant.expires_at is None
    assert grant.issued_at == NOW
    assert grant.user_id == USER
    assert grant.brand_id == BRAND
    assert grant.platform_app_id == APP_ROW_ID

    # The credential is the token, encrypted — never the plaintext.
    (connection_id, version, ciphertext), *rest = h.repo.credentials
    assert rest == []
    assert version == 1
    assert ciphertext != TOKEN.encode()
    assert h.encryptor.decrypt(ciphertext, key_id=h.encryptor.key_id) == TOKEN

    # FSM: born pending, VERIFY_OK → active; one granted + one activated domain event.
    assert h.publisher.names() == [DomainEventName.GRANTED, DomainEventName.ACTIVATED]
    assert h.repo.events == [(stored.connection_id, "granted"), (stored.connection_id, "granted")]

    # Phone row with the Graph metadata, bound to this connection and tenant.
    row = h.phones.rows[PHONE_NUMBER_ID]
    assert row.connection_id == stored.connection_id
    assert row.tenant_id == TENANT
    assert row.brand_id == BRAND
    assert row.waba_id == WABA_ID
    assert (row.verified_name, row.name_status, row.quality_rating) == (
        "Bianki",
        "APPROVED",
        "GREEN",
    )
    assert (row.messaging_limit_tier, row.platform_status) == ("TIER_1K", "CONNECTED")
    assert row.synced_at == NOW


async def test_missing_scope_writes_nothing() -> None:
    h = Harness(health=FakeTokenHealth(scopes=("whatsapp_business_messaging",)))
    with pytest.raises(ScopesMissing) as excinfo:
        await h.run()
    assert excinfo.value.missing == frozenset({"whatsapp_business_management"})
    h.assert_nothing_written()


async def test_invalid_token_writes_nothing() -> None:
    h = Harness(health=FakeTokenHealth(is_valid=False))
    with pytest.raises(TokenRejected):
        await h.run()
    h.assert_nothing_written()


async def test_auth_error_on_graph_writes_nothing() -> None:
    error = WhatsAppApiError("rejected", status=401, code=190)
    h = Harness(client=FakeWhatsAppClient(error=error))
    with pytest.raises(WhatsAppApiError) as excinfo:
        await h.run()
    assert excinfo.value.is_auth_error
    h.assert_nothing_written()


async def test_foreign_number_is_a_plain_api_error_and_writes_nothing() -> None:
    """A number the token cannot see: Meta answers an error that is NOT 401/190."""
    error = WhatsAppApiError("unsupported get request", status=400, code=100, subcode=33)
    h = Harness(client=FakeWhatsAppClient(error=error))
    with pytest.raises(WhatsAppApiError) as excinfo:
        await h.run()
    assert not excinfo.value.is_auth_error
    h.assert_nothing_written()


async def test_graph_answering_another_id_writes_nothing() -> None:
    h = Harness(client=FakeWhatsAppClient(info=_info(id="111")))
    with pytest.raises(PhoneNumberMismatch):
        await h.run()
    h.assert_nothing_written()


async def test_debug_token_runs_before_the_graph_read() -> None:
    """Order is the design: a rejected token must not even reach `/{phone_number_id}`."""

    class Exploding(FakeWhatsAppClient):
        async def get_phone_number(self) -> PhoneNumberInfo:
            raise AssertionError("graph read must not happen for a rejected token")

    h = Harness(health=FakeTokenHealth(is_valid=False), client=Exploding())
    with pytest.raises(TokenRejected):
        await h.run()


async def test_second_run_rotates_credential_and_refreshes_without_duplicating() -> None:
    h = Harness()
    first = await h.run()

    h.client = FakeWhatsAppClient(info=_info(quality_rating="YELLOW", verified_name="Bianki Co"))
    later = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    second = await h.run(brand_id=None, now=later)

    # One connection, same id, still active; credential appended as version 2.
    stored = h.repo.only()
    assert second.connection_id == first.connection_id == stored.connection_id
    assert second.status == "active"
    assert second.created_connection is False
    assert second.credential_version == 2
    assert [v for _, v, _ in h.repo.credentials] == [1, 2]
    assert stored.last_verified_at == later
    # Q1: an active row re-verifying is NOT a transition — no second `activated`.
    assert h.publisher.names() == [
        DomainEventName.GRANTED,
        DomainEventName.ACTIVATED,
        DomainEventName.GRANTED,
    ]
    assert h.repo.events[-2:] == [
        (stored.connection_id, "reconnected"),
        (stored.connection_id, "granted"),
    ]

    # One phone row, refreshed in place.
    assert second.created_phone_number is False
    assert h.phones.upserts == 2
    assert list(h.phones.rows) == [PHONE_NUMBER_ID]
    row = h.phones.rows[PHONE_NUMBER_ID]
    assert row.quality_rating == "YELLOW"
    assert row.verified_name == "Bianki Co"
    assert row.synced_at == later
    assert second.verified_name == "Bianki Co"


async def test_run_on_degraded_connection_reconnects_it() -> None:
    h = Harness()
    await h.run()
    h.repo.only().status = "degraded"  # as `degrade_on_auth_error` would leave it

    outcome = await h.run()

    assert outcome.status == "active"
    assert h.publisher.names()[-2:] == [DomainEventName.GRANTED, DomainEventName.RECONNECTED]


async def test_display_number_falls_back_to_the_id_when_meta_omits_it() -> None:
    h = Harness(client=FakeWhatsAppClient(info=_info(display_phone_number=None)))
    outcome = await h.run()
    assert outcome.display_phone_number == PHONE_NUMBER_ID
    assert h.repo.only().grant.external_username == PHONE_NUMBER_ID


# --- the CLI: exit codes and token discipline ------------------------------------------


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch) -> Harness:
    """Run the real `_run` with the Postgres/HTTP edges swapped for the fakes above."""
    h = Harness()
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    monkeypatch.setattr(connect_mod, "owner_user_id", lambda tenant_id: USER)
    monkeypatch.setattr(connect_mod, "PostgresConnectionRepository", lambda: h.repo)
    monkeypatch.setattr(connect_mod, "PostgresWhatsAppPhoneNumberRepository", lambda: h.phones)
    monkeypatch.setattr(connect_mod, "HttpMetaTokenHealthClient", lambda settings: h.health)
    monkeypatch.setattr(connect_mod, "HttpWhatsAppClient", lambda **kwargs: h.client)
    monkeypatch.setattr(connect_mod, "_cli_publisher", lambda: h.publisher)
    return h


_ARGS = [
    "--tenant",
    str(TENANT),
    "--brand",
    str(BRAND),
    "--waba-id",
    WABA_ID,
    "--phone-number-id",
    PHONE_NUMBER_ID,
]


def test_cli_success_prints_a_summary_without_the_token(
    cli: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    assert connect_mod.main(_ARGS) == EXIT_OK
    out, err = capsys.readouterr()
    assert "status=active" in out
    assert "+57 300 1234567" in out
    assert "(Bianki)" in out
    assert "credential_version=1" in out
    assert TOKEN not in out and TOKEN not in err
    assert cli.repo.only().status == "active"


def test_cli_missing_scope_exits_2_and_writes_nothing(
    cli: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.health.scopes = ("whatsapp_business_messaging",)
    assert connect_mod.main(_ARGS) == EXIT_TOKEN_REJECTED
    out, err = capsys.readouterr()
    assert "whatsapp_business_management" in err
    assert TOKEN not in out and TOKEN not in err
    cli.assert_nothing_written()


def test_cli_invalid_token_exits_2(cli: Harness, capsys: pytest.CaptureFixture[str]) -> None:
    cli.health.is_valid = False
    assert connect_mod.main(_ARGS) == EXIT_TOKEN_REJECTED
    _, err = capsys.readouterr()
    assert TOKEN not in err
    cli.assert_nothing_written()


def test_cli_auth_error_exits_3_and_writes_nothing(
    cli: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.client.error = WhatsAppApiError("rejected", status=401, code=190)
    assert connect_mod.main(_ARGS) == EXIT_AUTH_ERROR
    _, err = capsys.readouterr()
    assert TOKEN not in err
    cli.assert_nothing_written()


def test_cli_other_api_error_exits_1(cli: Harness) -> None:
    cli.client.error = WhatsAppApiError("boom", status=400, code=100)
    assert connect_mod.main(_ARGS) == EXIT_API_ERROR
    cli.assert_nothing_written()


def test_cli_without_token_env_exits_4(cli: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TOKEN_ENV)
    assert connect_mod.main(_ARGS) == EXIT_USAGE
    cli.assert_nothing_written()


def test_cli_rerun_is_idempotent(cli: Harness) -> None:
    assert connect_mod.main(_ARGS) == EXIT_OK
    assert connect_mod.main(_ARGS) == EXIT_OK
    assert len(cli.repo.connections) == 1
    assert cli.repo.only().credential_version == 2
    assert list(cli.phones.rows) == [PHONE_NUMBER_ID]


def test_connect_module_never_prints_or_logs_the_token() -> None:
    """Static guard, same spirit as the `repr` redaction tests elsewhere: no `print(...)`
    or `_LOGGER.*(...)` call in the module takes the `token` name as an argument,
    directly or inside an f-string."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(connect_mod))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_print = isinstance(func, ast.Name) and func.id == "print"
        is_log = (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "_LOGGER"
        )
        if not (is_print or is_log):
            continue
        for arg in [*node.args, *(kw.value for kw in node.keywords)]:
            for inner in ast.walk(arg):
                if isinstance(inner, ast.Name) and inner.id == "token":
                    offenders.append(node.lineno)
    assert offenders == [], f"token referenced in print/log at lines {offenders}"

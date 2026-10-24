"""«Preguntas iniciales» (Instagram Ice Breakers) per connected account (m-24789472, PR 3,
B2; migration 0083). The seam the Reflex screen consumes is `IceBreakerService`.

Up to four questions Instagram shows a person who opens a chat with the business; a tap
reaches Conversaciones as a postback whose payload starts with `QF_` (`choices.py`, 0082).
Here a person edits the four Qualify proposes, restores them, **publishes** them to
Instagram, reads back what Instagram holds, and removes them.

## What is a person's action, and what is not

- **Editing is local.** `get_config` / `save_draft` / `restore_defaults` touch only our row:
  nothing reaches Instagram until a person presses «Publicar». They work with the
  `ice_breakers` capability off.
- **Publishing and removing are human actions** (assisted, never autonomous): each call
  carries the `user_id` that pressed the button, nothing schedules or retries them, and
  both sit behind the `ice_breakers` capability (`followups.capabilities`, TO_VERIFY, env
  `QUALIFY_ICE_BREAKERS`, OFF by default). Off → `IceBreakerUnavailable` with the
  registry's reason, and Meta is not called.
- **Reading back** (`refresh_remote`, a GET) changes nothing on Instagram and works with
  the capability off (the brief's rule: everything but publish/remove still works).

## Publishing, step by step

1. Validate the draft (`clean_items`, at least one question).
2. POST it (`ice_breakers_client`); then GET it back and store the snapshot. The read-back
   failing does not undo a publish Meta confirmed: the row says `published` and the
   snapshot stays as it was (`IceBreakerConfig.remote_verified` is then False).
3. An **ambiguous** failure (the request may have landed) is settled by reading back: if
   Instagram holds exactly what was sent, it was published; otherwise `failed/ambiguous`.
4. Any other failure → `failed` + `last_error_code` (a category) + `last_error_detail`
   (`http_<s>_code_<c>`), then `IceBreakerRemoteError` with the Spanish sentence. An auth
   failure also degrades the connection (QUA-90's seam), as the DM sender does.

`published_items` is what the last successful publish SENT, so «cambios sin publicar» is
`items != published_items`, whatever happened to the draft since.

## Validation (`clean_items`)

At most 4 (`ice-breakers.md`); each question non-empty after collapsing whitespace to one
line and at most 80 characters (provisional, not in the corpus: WhatsApp's Ice Breaker limit
`whatsapp/menus/schema.ICE_BREAKER_MAX_LEN`, the same 80 Meta documents for template titles
— R6 measures it); no two questions equal ignoring case and spacing; payloads are
Qualify's `QF_` + `[A-Z0-9_]` (≤ 64 characters), unique. A new question may come with an
empty payload: it gets the first free `QF_PREGUNTA_<n>`. The `locale: "default"` block is
the client's job (`build_set_body`).

## Tenancy and seeding

Every call takes `tenant_id`; Postgres access is `tenant_session(tenant_id)` only, so
another tenant's account reads as missing (`IceBreakerNotFound`). The row is seeded lazily
with `DEFAULT_ICE_BREAKERS` by `INSERT … ON CONFLICT (connection_id) DO NOTHING` — two
concurrent first opens create one row.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from qualify_api.connections.models import SocialConnection
from qualify_api.conversations.choices import DEFAULT_ICE_BREAKERS, PREFIX_ICE_BREAKER
from qualify_api.conversations.contracts import SourceConnection
from qualify_api.conversations.ice_breakers_client import (
    CATEGORY_AMBIGUOUS,
    CATEGORY_AUTH_EXPIRED,
    CATEGORY_META_UNAVAILABLE,
    CATEGORY_PERMISSION_MISSING,
    CATEGORY_RATE_LIMITED,
    CATEGORY_REJECTED,
    CATEGORY_UNEXPECTED_RESPONSE,
    MAX_ICE_BREAKERS,
    IceBreakerItem,
    IceBreakersApiError,
    IceBreakersClient,
    RemoteIceBreakers,
)
from qualify_api.conversations.models import ConversationIceBreakers

if TYPE_CHECKING:
    from qualify_api.followups.capabilities import Availability

logger = logging.getLogger("qualify_api.conversations.ice_breakers")

#: Provisional (see module docstring): WhatsApp's Ice Breaker limit until R6 measures it.
MAX_QUESTION_CHARS: Final = 80
MAX_PAYLOAD_CHARS: Final = 64
DEFAULTS_VERSION: Final = 1
NEW_PAYLOAD_STEM: Final = f"{PREFIX_ICE_BREAKER}PREGUNTA_"
_PAYLOAD: Final = re.compile(rf"^{PREFIX_ICE_BREAKER}[A-Z0-9_]{{1,{MAX_PAYLOAD_CHARS - 3}}}$")
PLATFORM_INSTAGRAM: Final = "instagram"

STATUS_DRAFT: Final = "draft"
STATUS_PUBLISHED: Final = "published"
STATUS_FAILED: Final = "failed"
STATUS_REMOVED: Final = "removed"
#: 0083's CHECKed list — a test keeps the two in step.
STATUSES: Final[tuple[str, ...]] = (STATUS_DRAFT, STATUS_PUBLISHED, STATUS_FAILED, STATUS_REMOVED)

STATUS_LABELS: Final[dict[str, str]] = {
    STATUS_DRAFT: "Sin publicar",
    STATUS_PUBLISHED: "Publicadas en Instagram",
    STATUS_FAILED: "No se pudo actualizar Instagram",
    STATUS_REMOVED: "Quitadas de Instagram",
}

#: The default four, as items, in the ticket's order.
DEFAULT_ITEMS: Final[tuple[IceBreakerItem, ...]] = tuple(
    IceBreakerItem(question=ib.question, payload=ib.payload) for ib in DEFAULT_ICE_BREAKERS
)


# --- errors (messages are shown to the client: Spanish, qualify-copy-es) ------------------

ERR_TOO_MANY: Final = "too_many"
ERR_QUESTION_EMPTY: Final = "question_empty"
ERR_QUESTION_TOO_LONG: Final = "question_too_long"
ERR_QUESTION_REPEATED: Final = "question_repeated"
ERR_PAYLOAD_INVALID: Final = "payload_invalid"
ERR_PAYLOAD_REPEATED: Final = "payload_repeated"
ERR_NOTHING_TO_PUBLISH: Final = "nothing_to_publish"
ERR_UNAVAILABLE: Final = "unavailable"
ERR_CONNECTION_NOT_FOUND: Final = "connection_not_found"
# Remote outcomes — also the values `last_error_code` holds.
ERR_CONNECTION_UNAVAILABLE: Final = "connection_unavailable"
ERR_UNEXPECTED: Final = "unexpected"

_TRY_AGAIN: Final = "Vuelve a abrir la pantalla e inténtalo de nuevo."
_RECONNECT: Final = "Conéctala de nuevo en Cuentas conectadas."

MESSAGES: Final[dict[str, str]] = {
    ERR_TOO_MANY: f"Puedes tener hasta {MAX_ICE_BREAKERS} preguntas iniciales.",
    ERR_QUESTION_EMPTY: "Escribe la pregunta o quítala de la lista.",
    ERR_QUESTION_TOO_LONG: f"Cada pregunta puede tener hasta {MAX_QUESTION_CHARS} caracteres.",
    ERR_QUESTION_REPEATED: "Hay dos preguntas iguales. Cambia o quita una de ellas.",
    ERR_PAYLOAD_INVALID: f"No pudimos guardar las preguntas. {_TRY_AGAIN}",
    ERR_PAYLOAD_REPEATED: f"No pudimos guardar las preguntas. {_TRY_AGAIN}",
    ERR_NOTHING_TO_PUBLISH: "Agrega al menos una pregunta antes de publicar.",
    ERR_UNAVAILABLE: "Publicar las preguntas iniciales en Instagram no está disponible todavía.",
    ERR_CONNECTION_NOT_FOUND: (
        "No encontramos esa cuenta conectada. Revisa Cuentas conectadas e inténtalo de nuevo."
    ),
    ERR_CONNECTION_UNAVAILABLE: (
        f"Esta cuenta de Instagram no está conectada en este momento. {_RECONNECT}"
    ),
    CATEGORY_AUTH_EXPIRED: f"Instagram pidió volver a conectar la cuenta. {_RECONNECT}",
    CATEGORY_PERMISSION_MISSING: (
        "Instagram no le dio permiso a Qualify para cambiar las preguntas iniciales. "
        "Conecta la cuenta de nuevo en Cuentas conectadas y acepta todos los permisos."
    ),
    CATEGORY_RATE_LIMITED: (
        "Instagram permite pocos cambios seguidos en las preguntas iniciales. Espera unos "
        "minutos e inténtalo de nuevo."
    ),
    CATEGORY_META_UNAVAILABLE: "Instagram no respondió. Inténtalo de nuevo en unos minutos.",
    CATEGORY_AMBIGUOUS: (
        "No sabemos si Instagram recibió el cambio. Revisa el estado en unos minutos antes "
        "de volver a intentarlo."
    ),
    CATEGORY_REJECTED: "Instagram no aceptó el cambio. Revisa las preguntas e inténtalo de nuevo.",
    CATEGORY_UNEXPECTED_RESPONSE: (
        "Instagram respondió algo que no entendimos. Revisa el estado en unos minutos."
    ),
    ERR_UNEXPECTED: "Algo falló al hablar con Instagram. Inténtalo de nuevo en unos minutos.",
}


class IceBreakerError(ValueError):
    """A request the service refuses. `code` is stable (tests, the UI's logic); `message`
    — also `str(error)` — is the Spanish sentence to show the person. `index` points at
    the offending question (0-based) when there is one."""

    def __init__(self, code: str, *, index: int | None = None) -> None:
        self.code = code
        self.message = MESSAGES[code]
        self.index = index
        super().__init__(self.message)


class IceBreakerNotFound(IceBreakerError, LookupError):
    """The account is not visible to this tenant (another tenant's included — RLS makes
    the two indistinguishable, and this keeps it that way) or is not an Instagram one."""


class IceBreakerUnavailable(IceBreakerError, PermissionError):
    """`ice_breakers` is off in this deployment. `reason` is the registry's sentence (its
    state and switch), `state_label` its state in the ticket's vocabulary."""

    def __init__(self, availability: Availability) -> None:
        super().__init__(ERR_UNAVAILABLE)
        self.availability = availability
        self.reason = availability.reason
        self.state_label = availability.state_label


class IceBreakerRemoteError(IceBreakerError):
    """Instagram did not take the change. Recorded first (`status = failed`); `config` is
    the row as it now reads, `code` the category stored in `last_error_code`."""

    def __init__(self, code: str, config: IceBreakerConfig) -> None:
        super().__init__(code)
        self.config = config


# --- records -----------------------------------------------------------------------------


@dataclass(frozen=True)
class IceBreakerConfig:
    tenant_id: UUID
    connection_id: UUID
    items: tuple[IceBreakerItem, ...]
    status: str
    defaults_version: int
    published_items: tuple[IceBreakerItem, ...] | None
    published_at: datetime | None
    published_by_user_id: UUID | None
    removed_at: datetime | None
    removed_by_user_id: UUID | None
    remote: RemoteIceBreakers | None
    remote_checked_at: datetime | None
    last_attempt_at: datetime | None
    last_error_code: str | None
    last_error_detail: str | None
    updated_at: datetime
    updated_by_user_id: UUID | None

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def is_published(self) -> bool:
        return self.published_items is not None

    @property
    def has_unpublished_changes(self) -> bool:
        """The draft differs from what Instagram was last given (or nothing was given)."""
        return self.items != (self.published_items or ())

    @property
    def is_default(self) -> bool:
        return self.items == DEFAULT_ITEMS

    @property
    def remote_verified(self) -> bool:
        """The last read-back, taken after the last publish, shows exactly what was sent."""
        if self.published_items is None or self.remote is None:
            return False
        if self.remote_checked_at is None or self.published_at is None:
            return False
        return (
            self.remote_checked_at >= self.published_at
            and self.remote.default_items == self.published_items
        )

    @property
    def error_message(self) -> str | None:
        """The Spanish sentence for the last failure, while the status says `failed`."""
        if self.status != STATUS_FAILED or self.last_error_code is None:
            return None
        return MESSAGES.get(self.last_error_code, MESSAGES[ERR_UNEXPECTED])


# --- pure functions ----------------------------------------------------------------------


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _question_key(question: str) -> str:
    return _one_line(question).casefold()


ItemInput = IceBreakerItem | Mapping[str, Any]


def _as_pair(item: ItemInput) -> tuple[str, str]:
    if isinstance(item, IceBreakerItem):
        return item.question, item.payload
    question, payload = item.get("question"), item.get("payload")
    return (
        question if isinstance(question, str) else "",
        payload if isinstance(payload, str) else "",
    )


def clean_items(
    items: Sequence[ItemInput], *, require_one: bool = False
) -> tuple[IceBreakerItem, ...]:
    """The questions on one line, trimmed, with a payload each; or `IceBreakerError`
    naming the first problem (and its index). Pure."""
    if len(items) > MAX_ICE_BREAKERS:
        raise IceBreakerError(ERR_TOO_MANY)
    if require_one and not items:
        raise IceBreakerError(ERR_NOTHING_TO_PUBLISH)
    pairs = [_as_pair(item) for item in items]
    seen_questions: set[str] = set()
    seen_payloads: set[str] = set()
    cleaned: list[tuple[str, str]] = []
    for index, (raw_question, raw_payload) in enumerate(pairs):
        question = _one_line(raw_question)
        if not question:
            raise IceBreakerError(ERR_QUESTION_EMPTY, index=index)
        if len(question) > MAX_QUESTION_CHARS:
            raise IceBreakerError(ERR_QUESTION_TOO_LONG, index=index)
        key = _question_key(question)
        if key in seen_questions:
            raise IceBreakerError(ERR_QUESTION_REPEATED, index=index)
        seen_questions.add(key)
        payload = raw_payload.strip()
        if payload:
            if not _PAYLOAD.match(payload):
                raise IceBreakerError(ERR_PAYLOAD_INVALID, index=index)
            if payload in seen_payloads:
                raise IceBreakerError(ERR_PAYLOAD_REPEATED, index=index)
            seen_payloads.add(payload)
        cleaned.append((question, payload))
    result: list[IceBreakerItem] = []
    counter = 1
    for question, payload in cleaned:
        if not payload:
            while f"{NEW_PAYLOAD_STEM}{counter}" in seen_payloads:
                counter += 1
            payload = f"{NEW_PAYLOAD_STEM}{counter}"
            seen_payloads.add(payload)
        result.append(IceBreakerItem(question=question, payload=payload))
    return tuple(result)


def _wire(items: Sequence[IceBreakerItem] | None) -> list[dict[str, str]] | None:
    return None if items is None else [item.as_wire() for item in items]


def _from_wire(raw: Any) -> tuple[IceBreakerItem, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(
        IceBreakerItem(question=str(r["question"]), payload=str(r["payload"]))
        for r in raw
        if isinstance(r, Mapping) and "question" in r and "payload" in r
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --- repository ----------------------------------------------------------------------------

#: Columns a service step may set (anything else stays as it is).
Changes = dict[str, Any]


class IceBreakerRepository(Protocol):
    def ensure(self, *, tenant_id: UUID, connection_id: UUID) -> bool:
        """Seed the defaults unless the account has a row. True when THIS call seeded.
        Raises `IceBreakerNotFound` for an account the tenant cannot see."""
        ...

    def get(self, *, tenant_id: UUID, connection_id: UUID) -> IceBreakerConfig | None: ...

    def update(
        self, *, tenant_id: UUID, connection_id: UUID, changes: Changes
    ) -> IceBreakerConfig | None:
        """Set `changes` (column → value; item tuples and `RemoteIceBreakers` accepted)
        and `updated_at`; None when the row is not visible."""
        ...


def _column_values(changes: Changes) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for column, value in changes.items():
        if column in ("items", "published_items"):
            values[column] = _wire(value)
        elif column == "remote":
            values["remote_snapshot"] = value.to_snapshot() if value is not None else None
        else:
            values[column] = value
    return values


class MemoryIceBreakerRepository:
    """Same contract, dicts underneath. `connections` maps each known account to its
    tenant (the FK and RLS's job in Postgres); `None` accepts any account for any tenant."""

    def __init__(
        self,
        *,
        connections: dict[UUID, UUID] | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._connections = connections
        self._clock = clock
        self.rows: dict[UUID, IceBreakerConfig] = {}

    def ensure(self, *, tenant_id: UUID, connection_id: UUID) -> bool:
        if self._connections is not None and self._connections.get(connection_id) != tenant_id:
            raise IceBreakerNotFound(ERR_CONNECTION_NOT_FOUND)
        row = self.rows.get(connection_id)
        if row is not None:
            if row.tenant_id != tenant_id:
                raise IceBreakerNotFound(ERR_CONNECTION_NOT_FOUND)
            return False
        self.rows[connection_id] = IceBreakerConfig(
            tenant_id=tenant_id,
            connection_id=connection_id,
            items=DEFAULT_ITEMS,
            status=STATUS_DRAFT,
            defaults_version=DEFAULTS_VERSION,
            published_items=None,
            published_at=None,
            published_by_user_id=None,
            removed_at=None,
            removed_by_user_id=None,
            remote=None,
            remote_checked_at=None,
            last_attempt_at=None,
            last_error_code=None,
            last_error_detail=None,
            updated_at=self._clock(),
            updated_by_user_id=None,
        )
        return True

    def get(self, *, tenant_id: UUID, connection_id: UUID) -> IceBreakerConfig | None:
        row = self.rows.get(connection_id)
        return row if row is not None and row.tenant_id == tenant_id else None

    def update(
        self, *, tenant_id: UUID, connection_id: UUID, changes: Changes
    ) -> IceBreakerConfig | None:
        row = self.get(tenant_id=tenant_id, connection_id=connection_id)
        if row is None:
            return None
        fields = dict(changes)
        for column in ("items", "published_items"):
            if column in fields and fields[column] is not None:
                fields[column] = tuple(fields[column])
        updated = replace(row, updated_at=self._clock(), **fields)
        self.rows[connection_id] = updated
        return updated


def _record(row: ConversationIceBreakers) -> IceBreakerConfig:
    return IceBreakerConfig(
        tenant_id=row.tenant_id,
        connection_id=row.connection_id,
        items=_from_wire(row.items),
        status=row.status,
        defaults_version=row.defaults_version,
        published_items=_from_wire(row.published_items) if row.published_items else None,
        published_at=row.published_at,
        published_by_user_id=row.published_by_user_id,
        removed_at=row.removed_at,
        removed_by_user_id=row.removed_by_user_id,
        remote=(
            RemoteIceBreakers.from_snapshot(row.remote_snapshot)
            if row.remote_snapshot is not None
            else None
        ),
        remote_checked_at=row.remote_checked_at,
        last_attempt_at=row.last_attempt_at,
        last_error_code=row.last_error_code,
        last_error_detail=row.last_error_detail,
        updated_at=row.updated_at,
        updated_by_user_id=row.updated_by_user_id,
    )


class PostgresIceBreakerRepository:
    """Every statement under `tenant_session(tenant_id)` — RLS scopes it, and the
    composite FK keeps the row's tenant agreeing with its account's."""

    def ensure(self, *, tenant_id: UUID, connection_id: UUID) -> bool:
        with tenant_session(tenant_id) as session:
            visible = session.scalar(
                select(SocialConnection.id).where(
                    SocialConnection.id == connection_id,
                    SocialConnection.platform == PLATFORM_INSTAGRAM,
                )
            )
            if visible is None:
                raise IceBreakerNotFound(ERR_CONNECTION_NOT_FOUND)
            inserted = session.execute(
                pg_insert(ConversationIceBreakers)
                .values(
                    connection_id=connection_id,
                    tenant_id=tenant_id,
                    items=_wire(DEFAULT_ITEMS),
                    defaults_version=DEFAULTS_VERSION,
                    status=STATUS_DRAFT,
                )
                .on_conflict_do_nothing(index_elements=["connection_id"])
                .returning(ConversationIceBreakers.connection_id)
            ).first()
            return inserted is not None

    def get(self, *, tenant_id: UUID, connection_id: UUID) -> IceBreakerConfig | None:
        with tenant_session(tenant_id) as session:
            row = session.get(ConversationIceBreakers, connection_id)
            return _record(row) if row is not None else None

    def update(
        self, *, tenant_id: UUID, connection_id: UUID, changes: Changes
    ) -> IceBreakerConfig | None:
        values = _column_values(changes)
        values["updated_at"] = _utcnow()
        with tenant_session(tenant_id) as session:
            result = session.execute(
                update(ConversationIceBreakers)
                .where(ConversationIceBreakers.connection_id == connection_id)
                .values(**values)
                .returning(ConversationIceBreakers.connection_id)
            ).first()
            if result is None:
                return None
            session.expire_all()
            row = session.get(ConversationIceBreakers, connection_id)
            return _record(row) if row is not None else None


# --- service -------------------------------------------------------------------------------

#: `(tenant_id, connection_id) -> the ids the client needs`, or None when the account is
#: not an active Instagram connection (`composition.source_connection_for`).
ConnectionReader = Callable[[UUID, UUID], SourceConnection | None]
#: QUA-90's seam (`connections.composition.degrade_connection_on_auth_error`).
ConnectionDegrader = Callable[..., object]


class IceBreakerService:
    """Validation and the publish sequence live here; persistence in the repository; the
    wire in the client. Nothing here runs on its own: every remote call is a person's."""

    def __init__(
        self,
        *,
        repository: IceBreakerRepository,
        client: IceBreakersClient,
        connections: ConnectionReader,
        availability: Availability,
        degrade: ConnectionDegrader | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._repo = repository
        self._client = client
        self._connections = connections
        self._availability = availability
        self._degrade = degrade
        self._clock = clock

    @property
    def availability(self) -> Availability:
        """Whether «Publicar» / «Quitar» can work here, and the reason when they cannot."""
        return self._availability

    # -- local --------------------------------------------------------------------------

    def get_config(self, *, tenant_id: UUID, connection_id: UUID) -> IceBreakerConfig:
        """The account's configuration, seeding the four defaults on first use."""
        self._repo.ensure(tenant_id=tenant_id, connection_id=connection_id)
        config = self._repo.get(tenant_id=tenant_id, connection_id=connection_id)
        if config is None:
            raise IceBreakerNotFound(ERR_CONNECTION_NOT_FOUND)
        return config

    def save_draft(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        items: Sequence[ItemInput],
        user_id: UUID | None,
    ) -> IceBreakerConfig:
        """Replace the draft (0–4 questions, in order). Instagram is not touched. Raises
        `IceBreakerError` (`too_many`, `question_*`, `payload_*`) or `IceBreakerNotFound`."""
        cleaned = clean_items(items)
        return self._set(tenant_id, connection_id, {"items": cleaned}, user_id)

    def restore_defaults(
        self, *, tenant_id: UUID, connection_id: UUID, user_id: UUID | None
    ) -> IceBreakerConfig:
        """The draft back to the four questions Qualify proposes. Instagram is not touched."""
        return self._set(tenant_id, connection_id, {"items": DEFAULT_ITEMS}, user_id)

    def _set(
        self, tenant_id: UUID, connection_id: UUID, changes: Changes, user_id: UUID | None
    ) -> IceBreakerConfig:
        self._repo.ensure(tenant_id=tenant_id, connection_id=connection_id)
        updated = self._repo.update(
            tenant_id=tenant_id,
            connection_id=connection_id,
            changes={**changes, "updated_by_user_id": user_id},
        )
        if updated is None:
            raise IceBreakerNotFound(ERR_CONNECTION_NOT_FOUND)
        return updated

    # -- remote -------------------------------------------------------------------------

    def _require_available(self) -> None:
        if not self._availability.enabled:
            raise IceBreakerUnavailable(self._availability)

    def _connection(self, tenant_id: UUID, connection_id: UUID) -> SourceConnection | None:
        return self._connections(tenant_id, connection_id)

    def _write(self, tenant_id: UUID, connection_id: UUID, changes: Changes) -> IceBreakerConfig:
        updated = self._repo.update(
            tenant_id=tenant_id, connection_id=connection_id, changes=changes
        )
        if updated is None:
            raise IceBreakerNotFound(ERR_CONNECTION_NOT_FOUND)
        return updated

    def _fail(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        *,
        code: str,
        detail: str | None,
        at: datetime,
        operation: str,
    ) -> IceBreakerRemoteError:
        logger.warning(
            "conversations.ice_breakers.%s connection=%s outcome=failed code=%s detail=%s",
            operation,
            connection_id,
            code,
            detail,
        )
        config = self._write(
            tenant_id,
            connection_id,
            {
                "status": STATUS_FAILED,
                "last_attempt_at": at,
                "last_error_code": code,
                "last_error_detail": detail,
            },
        )
        return IceBreakerRemoteError(code, config)

    def _degrade_on_auth(self, tenant_id: UUID, connection_id: UUID, exc: Exception) -> None:
        if self._degrade is None or not getattr(exc, "is_auth_error", False):
            return
        try:
            self._degrade(tenant_id=tenant_id, connection_id=connection_id)
        except Exception:  # noqa: BLE001 — the degrade seam never raises by contract
            logger.exception(
                "conversations.ice_breakers.degrade_failed connection=%s", connection_id
            )

    async def _read_back(self, connection: SourceConnection) -> RemoteIceBreakers | None:
        try:
            return await self._client.fetch(connection)
        except Exception as exc:  # noqa: BLE001 — a read-back never undoes what Meta confirmed
            logger.info(
                "conversations.ice_breakers.read_back connection=%s error=%s",
                connection.connection_id,
                getattr(exc, "detail", type(exc).__name__),
            )
            return None

    async def _remote_call(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        operation: str,
        call: Callable[[SourceConnection], Any],
        landed: Callable[[RemoteIceBreakers], bool],
        at: datetime,
    ) -> tuple[SourceConnection, RemoteIceBreakers | None]:
        """Run one write against Instagram and read it back. Returns the connection and
        the read-back (None if it failed); raises the recorded `IceBreakerRemoteError`."""
        connection = self._connection(tenant_id, connection_id)
        if connection is None:
            raise self._fail(
                tenant_id,
                connection_id,
                code=ERR_CONNECTION_UNAVAILABLE,
                detail=None,
                at=at,
                operation=operation,
            )
        try:
            await call(connection)
        except IceBreakersApiError as exc:
            self._degrade_on_auth(tenant_id, connection_id, exc)
            if exc.is_ambiguous:
                remote = await self._read_back(connection)
                if remote is not None and landed(remote):
                    return connection, remote
            raise self._fail(
                tenant_id,
                connection_id,
                code=exc.category,
                detail=exc.detail,
                at=at,
                operation=operation,
            ) from exc
        except Exception as exc:  # noqa: BLE001 — a credential that cannot be read, etc.
            raise self._fail(
                tenant_id,
                connection_id,
                code=ERR_UNEXPECTED,
                detail=type(exc).__name__.lower()[:64],
                at=at,
                operation=operation,
            ) from exc
        return connection, await self._read_back(connection)

    async def publish(
        self, *, tenant_id: UUID, connection_id: UUID, user_id: UUID | None
    ) -> IceBreakerConfig:
        """Publish the current draft to Instagram — a person pressed «Publicar». Raises
        `IceBreakerUnavailable` (capability off; Meta not called), `IceBreakerError`
        (`nothing_to_publish`, or an invalid draft), `IceBreakerNotFound`, or
        `IceBreakerRemoteError` (recorded as `failed` first)."""
        self._require_available()
        config = self.get_config(tenant_id=tenant_id, connection_id=connection_id)
        items = clean_items(config.items, require_one=True)
        now = self._clock()

        async def call(connection: SourceConnection) -> None:
            await self._client.publish(connection, items)

        _, remote = await self._remote_call(
            tenant_id,
            connection_id,
            "publish",
            call,
            lambda remote: remote.default_items == items,
            now,
        )
        logger.info(
            "conversations.ice_breakers.publish connection=%s outcome=published count=%d "
            "read_back=%s",
            connection_id,
            len(items),
            remote is not None,
        )
        changes: Changes = {
            "status": STATUS_PUBLISHED,
            "published_items": items,
            "published_at": now,
            "published_by_user_id": user_id,
            "last_attempt_at": now,
            "last_error_code": None,
            "last_error_detail": None,
        }
        if remote is not None:
            changes.update(remote=remote, remote_checked_at=self._clock())
        return self._write(tenant_id, connection_id, changes)

    async def remove(
        self, *, tenant_id: UUID, connection_id: UUID, user_id: UUID | None
    ) -> IceBreakerConfig:
        """Delete the account's Ice Breakers on Instagram — a person pressed «Quitar». The
        draft stays, to publish again later. Same raises as `publish`."""
        self._require_available()
        self.get_config(tenant_id=tenant_id, connection_id=connection_id)
        now = self._clock()

        async def call(connection: SourceConnection) -> None:
            await self._client.remove(connection)

        _, remote = await self._remote_call(
            tenant_id, connection_id, "remove", call, lambda remote: remote.is_empty, now
        )
        logger.info(
            "conversations.ice_breakers.remove connection=%s outcome=removed read_back=%s",
            connection_id,
            remote is not None,
        )
        changes: Changes = {
            "status": STATUS_REMOVED,
            "published_items": None,
            "removed_at": now,
            "removed_by_user_id": user_id,
            "last_attempt_at": now,
            "last_error_code": None,
            "last_error_detail": None,
        }
        if remote is not None:
            changes.update(remote=remote, remote_checked_at=self._clock())
        return self._write(tenant_id, connection_id, changes)

    async def refresh_remote(self, *, tenant_id: UUID, connection_id: UUID) -> IceBreakerConfig:
        """Read what Instagram holds now and store it (a GET; nothing changes there).
        Status and draft are untouched. Raises `IceBreakerRemoteError` WITHOUT recording a
        failure — a failed read says nothing about the last publish — and
        `IceBreakerNotFound`."""
        config = self.get_config(tenant_id=tenant_id, connection_id=connection_id)
        connection = self._connection(tenant_id, connection_id)
        if connection is None:
            raise IceBreakerRemoteError(ERR_CONNECTION_UNAVAILABLE, config)
        try:
            remote = await self._client.fetch(connection)
        except IceBreakersApiError as exc:
            self._degrade_on_auth(tenant_id, connection_id, exc)
            raise IceBreakerRemoteError(exc.category, config) from exc
        except Exception as exc:  # noqa: BLE001 — a credential that cannot be read, etc.
            logger.warning(
                "conversations.ice_breakers.refresh connection=%s error=%s",
                connection_id,
                type(exc).__name__,
            )
            raise IceBreakerRemoteError(ERR_UNEXPECTED, config) from exc
        return self._write(
            tenant_id, connection_id, {"remote": remote, "remote_checked_at": self._clock()}
        )


__all__ = [
    "DEFAULTS_VERSION",
    "DEFAULT_ITEMS",
    "MAX_PAYLOAD_CHARS",
    "MAX_QUESTION_CHARS",
    "MESSAGES",
    "STATUSES",
    "STATUS_LABELS",
    "ConnectionReader",
    "IceBreakerConfig",
    "IceBreakerError",
    "IceBreakerItem",
    "IceBreakerNotFound",
    "IceBreakerRemoteError",
    "IceBreakerRepository",
    "IceBreakerService",
    "IceBreakerUnavailable",
    "MemoryIceBreakerRepository",
    "PostgresIceBreakerRepository",
    "clean_items",
]

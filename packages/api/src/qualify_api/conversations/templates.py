"""Message templates for the Conversaciones composer (m-24789472, PR 1; migration 0079).

A per-account library of TEXT templates — «Gracias por escribirnos…», «Te comparto el
precio…» — that a person picks in the composer, edits, and then sends through the reply
flow that already exists. The seam the Reflex UI consumes is `ReplyTemplateService`.

## What this module never does

- **It never sends and never queues.** Nothing here imports the outbox. Picking or
  rendering a template returns a string; the person edits it and it leaves only through
  `ConversationService.reply_text(..., approval=HumanApproval)` (ADR 21c, B5). A test
  pins this.
- **It never calls Meta.** A template is our data; Instagram knows nothing of it.

## Variables

`{nombre}` is the counterpart's name in the thread (its username when Instagram gave no
name) and `{marca}` the brand behind the account (`brands.name` via
`social_connections.brand_id`, else the business's own name, `tenants.name` —
`composition.brand_name_for`). Matching is case- and space-tolerant (`{ Nombre }`).
**A variable with no value, and any unknown `{…}`, is LEFT VISIBLE as written** and
listed in `RenderedTemplate.unresolved`: the person sees «{nombre}» in the composer
before approving and fixes it, which beats a silent «¡Hola, !». Fill-in spaces of the
seeded defaults («[precio]») are not variables — the person types them — and are listed
in `RenderedTemplate.blanks` so the screen can point at them.

## Limits, and why

- `title` 1–60 characters (a picker label, one line: whitespace is collapsed);
- `body` 1–1000 characters: ONE Instagram DM (`service.MAX_REPLY_CHARS`). A template
  never silently becomes two messages; a person who writes more in the composer still can
  (`reply_text` splits at sentence boundaries). A rendered body may exceed 1000 once
  `{marca}` is substituted — the same split covers it.
- at most `MAX_TEMPLATES_PER_CONNECTION` (50) per account: a picker longer than that is
  not a picker. Enforced under the per-account lock (see below).

## Templates with buttons (m-24789472, phase 3; migration 0084)

A template may carry 1–3 `buttons` (`interactive.TemplateButton`: a `postback` with a
`QFB_` payload, or an https `web_url`), validated by `interactive.clean_buttons`. Such a
template is `kind == "buttons"` and is sent as ONE Instagram button template — never
split — so its body is at most 640 characters, not 1000. `render` hands the buttons to
the composer with the text (`RenderedTemplate.buttons`); the composer sends them through
`ConversationService.reply_buttons(..., approval=HumanApproval)`. Without buttons
(`buttons` NULL, every template of PR 1) nothing changes: `kind == "text"` and
`reply_text`. `update(buttons=None)` keeps a template's buttons; `buttons=()` removes
them.

## The defaults, seeded once and only once

`list_for_connection` seeds `DEFAULT_TEMPLATES` the first time an account's library is
opened. Two guarantees, both in Postgres (0079):

- **Idempotent under concurrency.** The seed marker (`conversation_reply_template_seeds`,
  PK = the account) is inserted with `ON CONFLICT DO NOTHING … RETURNING`; only the
  transaction that inserted it inserts the defaults (themselves `ON CONFLICT DO NOTHING`
  on `uq_conv_reply_template_default`). A concurrent first open waits on the marker's
  key, finds it, and seeds nothing.
- **Deleted defaults stay deleted.** The marker, not the presence of default rows, says
  the library was seeded; a person who deletes all four does not get them back.

The marker row is also the per-account lock (`SELECT … FOR UPDATE`) that `create` and
`reorder` take, so two concurrent creates cannot pass the cap together and a reorder sees
a stable set.

## Tenancy

Every call takes `tenant_id`; Postgres access is `tenant_session(tenant_id)` only, so
another tenant's template or account reads as missing (`ReplyTemplateNotFound`).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Final, Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from qualify_api.connections.models import SocialConnection
from qualify_api.conversations.interactive import (
    MAX_BUTTON_TEMPLATE_TEXT_CHARS,
    InteractiveMessageError,
    TemplateButton,
    buttons_from_json,
    buttons_wire,
    clean_buttons,
)
from qualify_api.conversations.interactive import MESSAGES as INTERACTIVE_MESSAGES
from qualify_api.conversations.models import (
    ConversationReplyTemplate,
    ConversationReplyTemplateSeed,
)
from qualify_api.conversations.repository import ThreadRecord

MAX_TITLE_CHARS: Final = 60
# One Instagram DM — `service.MAX_REPLY_CHARS` (a test pins the two equal; importing the
# service here would pull the outbox in). Mirrored by 0079's CHECK.
MAX_BODY_CHARS: Final = 1000
MAX_TEMPLATES_PER_CONNECTION: Final = 50
#: A template with buttons is one button template: `interactive`'s 640, mirrored by 0084.
MAX_BUTTONS_BODY_CHARS: Final = MAX_BUTTON_TEMPLATE_TEXT_CHARS
KIND_TEXT: Final = "text"
KIND_BUTTONS: Final = "buttons"
DEFAULTS_VERSION: Final = 1

VAR_NAME: Final = "nombre"
VAR_BRAND: Final = "marca"
SUPPORTED_VARIABLES: Final = (VAR_NAME, VAR_BRAND)

_PLACEHOLDER = re.compile(r"\{([^{}\n]{1,40})\}")
_BLANK = re.compile(r"\[[^\[\]\n]{1,60}\]")


# --- errors (messages are shown to the client: Spanish, qualify-copy-es) ------------------

ERR_TITLE_EMPTY: Final = "title_empty"
ERR_TITLE_TOO_LONG: Final = "title_too_long"
ERR_BODY_EMPTY: Final = "body_empty"
ERR_BODY_TOO_LONG: Final = "body_too_long"
ERR_LIMIT_REACHED: Final = "limit_reached"
ERR_ORDER_STALE: Final = "order_stale"
ERR_OTHER_ACCOUNT: Final = "other_account"
ERR_TEMPLATE_NOT_FOUND: Final = "template_not_found"
ERR_CONNECTION_NOT_FOUND: Final = "connection_not_found"
ERR_THREAD_NOT_FOUND: Final = "thread_not_found"
ERR_BODY_TOO_LONG_FOR_BUTTONS: Final = "body_too_long_for_buttons"

MESSAGES: Final[dict[str, str]] = {
    ERR_TITLE_EMPTY: "Ponle un nombre corto a la plantilla.",
    ERR_TITLE_TOO_LONG: (
        f"El nombre de la plantilla puede tener hasta {MAX_TITLE_CHARS} caracteres."
    ),
    ERR_BODY_EMPTY: "Escribe el mensaje de la plantilla.",
    ERR_BODY_TOO_LONG: (
        f"El mensaje puede tener hasta {MAX_BODY_CHARS} caracteres, lo que cabe en un "
        "mensaje de Instagram."
    ),
    ERR_LIMIT_REACHED: (
        f"Ya tienes {MAX_TEMPLATES_PER_CONNECTION} plantillas en esta cuenta. Borra alguna "
        "que no uses para crear otra."
    ),
    ERR_ORDER_STALE: (
        "La lista de plantillas cambió mientras la ordenabas. Vuelve a abrirla e inténtalo "
        "de nuevo."
    ),
    ERR_OTHER_ACCOUNT: (
        "Esta plantilla es de otra cuenta conectada. Elige una de la cuenta de esta conversación."
    ),
    ERR_TEMPLATE_NOT_FOUND: "No encontramos esa plantilla. Puede que la hayan borrado.",
    ERR_CONNECTION_NOT_FOUND: (
        "No encontramos esa cuenta conectada. Revisa Cuentas conectadas e inténtalo de nuevo."
    ),
    ERR_THREAD_NOT_FOUND: "No encontramos esa conversación. Vuelve a abrirla.",
    ERR_BODY_TOO_LONG_FOR_BUTTONS: (
        f"Un mensaje con botones puede tener hasta {MAX_BUTTONS_BODY_CHARS} caracteres. "
        "Acórtalo o quita los botones."
    ),
    # The button errors (`buttons_empty`, `button_title_too_long`, …) of `interactive`.
    **INTERACTIVE_MESSAGES,
}


class ReplyTemplateError(ValueError):
    """A request the library refuses. `code` is stable (for tests and the UI's logic);
    `message` — also `str(error)` — is the Spanish sentence to show the person."""

    def __init__(self, code: str, *, index: int | None = None) -> None:
        self.code = code
        self.message = MESSAGES[code]
        # The offending button (0-based) for a button error; None otherwise.
        self.index = index
        super().__init__(self.message)


class ReplyTemplateNotFound(ReplyTemplateError, LookupError):
    """The template, the account or the thread is not visible to this tenant (another
    tenant's included — RLS makes the two indistinguishable, and this keeps it that way)."""


# --- records ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplyTemplate:
    id: UUID
    tenant_id: UUID
    connection_id: UUID
    title: str
    body: str
    position: int
    # Set on a template Qualify seeded (`greeting`, `price`, `hours`, `catalog`).
    default_key: str | None
    created_by_user_id: UUID | None
    updated_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime
    # m-24789472 (0084): empty for a text template.
    buttons: tuple[TemplateButton, ...] = ()

    @property
    def is_default(self) -> bool:
        return self.default_key is not None

    @property
    def kind(self) -> str:
        """`buttons` (sent as one button template) or `text` (sent with `reply_text`)."""
        return KIND_BUTTONS if self.buttons else KIND_TEXT


@dataclass(frozen=True)
class DefaultTemplate:
    key: str
    title: str
    body: str


@dataclass(frozen=True)
class RenderedTemplate:
    """What the composer receives. `text` is a starting point, never something sent."""

    template_id: UUID | None
    text: str
    # Variables left as written: no value for them in this thread, or unknown (`{precio}`).
    unresolved: tuple[str, ...] = ()
    # Fill-in spaces for the person («[precio]»), as they appear in `text`.
    blanks: tuple[str, ...] = ()
    # The template's buttons (m-24789472): non-empty means «send with `reply_buttons`».
    buttons: tuple[TemplateButton, ...] = ()

    @property
    def needs_attention(self) -> bool:
        return bool(self.unresolved or self.blanks)

    @property
    def kind(self) -> str:
        return KIND_BUTTONS if self.buttons else KIND_TEXT


# Seeded on an account's first open (`DEFAULTS_VERSION` 1). Plain neighborly Spanish,
# `tú`, no English (qualify-copy-es); the bracketed spaces are for the person to fill.
DEFAULT_TEMPLATES: Final[tuple[DefaultTemplate, ...]] = (
    DefaultTemplate(
        key="greeting",
        title="Saludo",
        body="¡Hola, {nombre}! Gracias por escribirnos a {marca}. ¿En qué te podemos ayudar?",
    ),
    DefaultTemplate(
        key="price",
        title="Precio",
        body=("Te comparto el precio: [precio]. Si quieres, te cuento cómo hacer tu pedido."),
    ),
    DefaultTemplate(
        key="hours",
        title="Horario",
        body=(
            "Nuestro horario de atención es de [días] de [hora de apertura] a "
            "[hora de cierre]. Con gusto te atendemos."
        ),
    ),
    DefaultTemplate(
        key="catalog",
        title="Catálogo",
        body=(
            "Aquí tienes nuestro catálogo: [enlace al catálogo]. Si algo te gusta, "
            "escríbenos y te ayudamos con tu pedido."
        ),
    ),
)


# --- pure functions --------------------------------------------------------------------


def clean_template(title: str, body: str) -> tuple[str, str]:
    """The title on one line (whitespace collapsed) and the body trimmed (inner line
    breaks kept), or `ReplyTemplateError` naming the first problem."""
    clean_title = " ".join(title.split())
    clean_body = body.strip()
    if not clean_title:
        raise ReplyTemplateError(ERR_TITLE_EMPTY)
    if len(clean_title) > MAX_TITLE_CHARS:
        raise ReplyTemplateError(ERR_TITLE_TOO_LONG)
    if not clean_body:
        raise ReplyTemplateError(ERR_BODY_EMPTY)
    if len(clean_body) > MAX_BODY_CHARS:
        raise ReplyTemplateError(ERR_BODY_TOO_LONG)
    return clean_title, clean_body


def clean_template_buttons(
    body: str, buttons: Sequence[TemplateButton]
) -> tuple[TemplateButton, ...]:
    """A template's buttons, cleaned (`interactive.clean_buttons`), and its already
    cleaned `body` checked against the button template's 640: `()` for no buttons (a text
    template). `ReplyTemplateError` with `interactive`'s code for a bad button, or
    `body_too_long_for_buttons`."""
    if not buttons:
        return ()
    try:
        cleaned = clean_buttons(buttons)
    except InteractiveMessageError as exc:
        raise ReplyTemplateError(exc.code, index=exc.index) from exc
    if len(body) > MAX_BUTTONS_BODY_CHARS:
        raise ReplyTemplateError(ERR_BODY_TOO_LONG_FOR_BUTTONS)
    return cleaned


def counterpart_display_name(thread: ThreadRecord) -> str | None:
    """`{nombre}`: the name Instagram reported, else the username, else nothing."""
    for value in (thread.counterpart_name, thread.counterpart_username):
        if value and value.strip():
            return value.strip()
    return None


def render_template(
    body: str, values: dict[str, str | None], *, template_id: UUID | None = None
) -> RenderedTemplate:
    """Substitute the supported variables in `body`. Pure. A variable with no (or a blank)
    value and any unknown `{…}` stay exactly as written and are listed in `unresolved`;
    nothing raises."""
    known = {k.lower(): v.strip() for k, v in values.items() if v is not None and v.strip()}
    unresolved: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        key = match.group(1).strip().lower()
        if key in SUPPORTED_VARIABLES and key in known:
            return known[key]
        token = match.group(0)
        if token not in unresolved:
            unresolved.append(token)
        return token

    text = _PLACEHOLDER.sub(substitute, body)
    blanks: list[str] = []
    for blank in _BLANK.findall(text):
        if blank not in blanks:
            blanks.append(blank)
    return RenderedTemplate(
        template_id=template_id, text=text, unresolved=tuple(unresolved), blanks=tuple(blanks)
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --- repository ------------------------------------------------------------------------


class ReplyTemplateRepository(Protocol):
    def ensure_defaults(self, *, tenant_id: UUID, connection_id: UUID) -> bool:
        """Seed the defaults unless this account was ever seeded. True when THIS call
        seeded. Raises `ReplyTemplateNotFound` for an account the tenant cannot see."""
        ...

    def list_templates(self, *, tenant_id: UUID, connection_id: UUID) -> list[ReplyTemplate]: ...

    def get_template(self, *, tenant_id: UUID, template_id: UUID) -> ReplyTemplate | None: ...

    def create_template(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        title: str,
        body: str,
        user_id: UUID | None,
        buttons: Sequence[TemplateButton] = (),
    ) -> ReplyTemplate: ...

    def update_template(
        self,
        *,
        tenant_id: UUID,
        template_id: UUID,
        title: str,
        body: str,
        user_id: UUID | None,
        buttons: Sequence[TemplateButton] = (),
    ) -> ReplyTemplate | None:
        """Writes title, body AND buttons (`()` = none): the service resolves «keep»."""
        ...

    def delete_template(self, *, tenant_id: UUID, template_id: UUID) -> bool: ...

    def reorder(
        self, *, tenant_id: UUID, connection_id: UUID, template_ids: Sequence[UUID]
    ) -> list[ReplyTemplate]: ...


def _check_order(current: Iterable[UUID], wanted: Sequence[UUID]) -> None:
    current_set = set(current)
    if len(set(wanted)) != len(wanted) or set(wanted) != current_set:
        raise ReplyTemplateError(ERR_ORDER_STALE)


# --- Memory ----------------------------------------------------------------------------


class MemoryReplyTemplateRepository:
    """Same contract, dicts underneath. `connections` maps each known account to its
    tenant (the FK's job in Postgres); `None` accepts any account for any tenant."""

    def __init__(
        self,
        *,
        connections: dict[UUID, UUID] | None = None,
        defaults: Sequence[DefaultTemplate] = DEFAULT_TEMPLATES,
        defaults_version: int = DEFAULTS_VERSION,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._connections = connections
        self._defaults = tuple(defaults)
        self._version = defaults_version
        self._clock = clock
        self.rows: dict[UUID, ReplyTemplate] = {}
        # connection_id -> (tenant_id, defaults_version): the seed marker.
        self.seeds: dict[UUID, tuple[UUID, int]] = {}

    def _require_connection(self, tenant_id: UUID, connection_id: UUID) -> None:
        if self._connections is None:
            return
        if self._connections.get(connection_id) != tenant_id:
            raise ReplyTemplateNotFound(ERR_CONNECTION_NOT_FOUND)

    def _of(self, tenant_id: UUID, connection_id: UUID) -> list[ReplyTemplate]:
        rows = [
            r
            for r in self.rows.values()
            if r.tenant_id == tenant_id and r.connection_id == connection_id
        ]
        return sorted(rows, key=lambda r: (r.position, r.created_at, str(r.id)))

    def _next_position(self, tenant_id: UUID, connection_id: UUID) -> int:
        return max((r.position for r in self._of(tenant_id, connection_id)), default=-1) + 1

    def _new(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        title: str,
        body: str,
        position: int,
        default_key: str | None,
        user_id: UUID | None,
        buttons: Sequence[TemplateButton] = (),
    ) -> ReplyTemplate:
        now = self._clock()
        record = ReplyTemplate(
            id=uuid4(),
            tenant_id=tenant_id,
            connection_id=connection_id,
            title=title,
            body=body,
            position=position,
            default_key=default_key,
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
            created_at=now,
            updated_at=now,
            buttons=tuple(buttons),
        )
        self.rows[record.id] = record
        return record

    def ensure_defaults(self, *, tenant_id: UUID, connection_id: UUID) -> bool:
        self._require_connection(tenant_id, connection_id)
        seed = self.seeds.get(connection_id)
        if seed is not None:
            if seed[0] != tenant_id:
                raise ReplyTemplateNotFound(ERR_CONNECTION_NOT_FOUND)
            return False
        self.seeds[connection_id] = (tenant_id, self._version)
        existing = {r.default_key for r in self._of(tenant_id, connection_id)}
        start = self._next_position(tenant_id, connection_id)
        for offset, default in enumerate(self._defaults):
            if default.key in existing:
                continue
            self._new(
                tenant_id=tenant_id,
                connection_id=connection_id,
                title=default.title,
                body=default.body,
                position=start + offset,
                default_key=default.key,
                user_id=None,
            )
        return True

    def list_templates(self, *, tenant_id: UUID, connection_id: UUID) -> list[ReplyTemplate]:
        return self._of(tenant_id, connection_id)

    def get_template(self, *, tenant_id: UUID, template_id: UUID) -> ReplyTemplate | None:
        row = self.rows.get(template_id)
        return row if row is not None and row.tenant_id == tenant_id else None

    def create_template(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        title: str,
        body: str,
        user_id: UUID | None,
        buttons: Sequence[TemplateButton] = (),
    ) -> ReplyTemplate:
        self._require_connection(tenant_id, connection_id)
        if len(self._of(tenant_id, connection_id)) >= MAX_TEMPLATES_PER_CONNECTION:
            raise ReplyTemplateError(ERR_LIMIT_REACHED)
        return self._new(
            tenant_id=tenant_id,
            connection_id=connection_id,
            title=title,
            body=body,
            position=self._next_position(tenant_id, connection_id),
            default_key=None,
            user_id=user_id,
            buttons=buttons,
        )

    def update_template(
        self,
        *,
        tenant_id: UUID,
        template_id: UUID,
        title: str,
        body: str,
        user_id: UUID | None,
        buttons: Sequence[TemplateButton] = (),
    ) -> ReplyTemplate | None:
        row = self.get_template(tenant_id=tenant_id, template_id=template_id)
        if row is None:
            return None
        updated = replace(
            row,
            title=title,
            body=body,
            buttons=tuple(buttons),
            updated_by_user_id=user_id,
            updated_at=self._clock(),
        )
        self.rows[row.id] = updated
        return updated

    def delete_template(self, *, tenant_id: UUID, template_id: UUID) -> bool:
        if self.get_template(tenant_id=tenant_id, template_id=template_id) is None:
            return False
        del self.rows[template_id]
        return True

    def reorder(
        self, *, tenant_id: UUID, connection_id: UUID, template_ids: Sequence[UUID]
    ) -> list[ReplyTemplate]:
        self._require_connection(tenant_id, connection_id)
        _check_order((r.id for r in self._of(tenant_id, connection_id)), template_ids)
        now = self._clock()
        for position, template_id in enumerate(template_ids):
            self.rows[template_id] = replace(
                self.rows[template_id], position=position, updated_at=now
            )
        return self._of(tenant_id, connection_id)


# --- Postgres --------------------------------------------------------------------------


def _record(row: ConversationReplyTemplate) -> ReplyTemplate:
    return ReplyTemplate(
        id=row.id,
        tenant_id=row.tenant_id,
        connection_id=row.connection_id,
        title=row.title,
        body=row.body,
        position=row.position,
        default_key=row.default_key,
        created_by_user_id=row.created_by_user_id,
        updated_by_user_id=row.updated_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        buttons=buttons_from_json(row.buttons),
    )


def _buttons_json(buttons: Sequence[TemplateButton]) -> list[dict[str, str]] | None:
    """What 0084's `buttons` column stores: the wire shape, or NULL for a text template."""
    return buttons_wire(buttons) if buttons else None


def _ordered(connection_id: UUID) -> Select[tuple[ConversationReplyTemplate]]:
    return (
        select(ConversationReplyTemplate)
        .where(ConversationReplyTemplate.connection_id == connection_id)
        .order_by(
            ConversationReplyTemplate.position,
            ConversationReplyTemplate.created_at,
            ConversationReplyTemplate.id,
        )
    )


class PostgresReplyTemplateRepository:
    """Every statement under `tenant_session(tenant_id)` — RLS scopes it, and the
    composite FKs keep a template's tenant agreeing with its account's."""

    def __init__(
        self,
        *,
        defaults: Sequence[DefaultTemplate] = DEFAULT_TEMPLATES,
        defaults_version: int = DEFAULTS_VERSION,
    ) -> None:
        self._defaults = tuple(defaults)
        self._version = defaults_version

    def _seed(self, session: Session, tenant_id: UUID, connection_id: UUID) -> bool:
        """Inside the caller's transaction: refuse an invisible account, then insert the
        marker and — only if THIS statement inserted it — the defaults."""
        visible = session.scalar(
            select(SocialConnection.id).where(SocialConnection.id == connection_id)
        )
        if visible is None:
            raise ReplyTemplateNotFound(ERR_CONNECTION_NOT_FOUND)
        inserted = session.execute(
            pg_insert(ConversationReplyTemplateSeed)
            .values(
                connection_id=connection_id,
                tenant_id=tenant_id,
                defaults_version=self._version,
            )
            .on_conflict_do_nothing(index_elements=["connection_id"])
            .returning(ConversationReplyTemplateSeed.connection_id)
        ).first()
        if inserted is None or not self._defaults:
            return inserted is not None
        start = session.scalar(
            select(func.coalesce(func.max(ConversationReplyTemplate.position) + 1, 0)).where(
                ConversationReplyTemplate.connection_id == connection_id
            )
        )
        session.execute(
            pg_insert(ConversationReplyTemplate)
            .values(
                [
                    {
                        "tenant_id": tenant_id,
                        "connection_id": connection_id,
                        "title": d.title,
                        "body": d.body,
                        "position": int(start or 0) + offset,
                        "default_key": d.key,
                    }
                    for offset, d in enumerate(self._defaults)
                ]
            )
            .on_conflict_do_nothing(
                index_elements=["tenant_id", "connection_id", "default_key"],
                index_where=ConversationReplyTemplate.default_key.is_not(None),
            )
        )
        return True

    def _lock(self, session: Session, tenant_id: UUID, connection_id: UUID) -> None:
        """The per-account lock: seed if needed, then hold the marker row."""
        self._seed(session, tenant_id, connection_id)
        session.execute(
            select(ConversationReplyTemplateSeed.connection_id)
            .where(ConversationReplyTemplateSeed.connection_id == connection_id)
            .with_for_update()
        )

    def ensure_defaults(self, *, tenant_id: UUID, connection_id: UUID) -> bool:
        with tenant_session(tenant_id) as session:
            return self._seed(session, tenant_id, connection_id)

    def list_templates(self, *, tenant_id: UUID, connection_id: UUID) -> list[ReplyTemplate]:
        with tenant_session(tenant_id) as session:
            return [_record(r) for r in session.scalars(_ordered(connection_id)).all()]

    def get_template(self, *, tenant_id: UUID, template_id: UUID) -> ReplyTemplate | None:
        with tenant_session(tenant_id) as session:
            row = session.get(ConversationReplyTemplate, template_id)
            return _record(row) if row is not None else None

    def create_template(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        title: str,
        body: str,
        user_id: UUID | None,
        buttons: Sequence[TemplateButton] = (),
    ) -> ReplyTemplate:
        with tenant_session(tenant_id) as session:
            self._lock(session, tenant_id, connection_id)
            count, last = session.execute(
                select(
                    func.count(ConversationReplyTemplate.id),
                    func.max(ConversationReplyTemplate.position),
                ).where(ConversationReplyTemplate.connection_id == connection_id)
            ).one()
            if int(count) >= MAX_TEMPLATES_PER_CONNECTION:
                raise ReplyTemplateError(ERR_LIMIT_REACHED)
            row = ConversationReplyTemplate(
                tenant_id=tenant_id,
                connection_id=connection_id,
                title=title,
                body=body,
                buttons=_buttons_json(buttons),
                position=(int(last) + 1) if last is not None else 0,
                created_by_user_id=user_id,
                updated_by_user_id=user_id,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            return _record(row)

    def update_template(
        self,
        *,
        tenant_id: UUID,
        template_id: UUID,
        title: str,
        body: str,
        user_id: UUID | None,
        buttons: Sequence[TemplateButton] = (),
    ) -> ReplyTemplate | None:
        with tenant_session(tenant_id) as session:
            row = session.get(ConversationReplyTemplate, template_id)
            if row is None:
                return None
            row.title = title
            row.body = body
            row.buttons = _buttons_json(buttons)
            row.updated_by_user_id = user_id
            row.updated_at = _utcnow()
            session.flush()
            session.refresh(row)
            return _record(row)

    def delete_template(self, *, tenant_id: UUID, template_id: UUID) -> bool:
        with tenant_session(tenant_id) as session:
            result = session.execute(
                delete(ConversationReplyTemplate).where(ConversationReplyTemplate.id == template_id)
            )
            return bool(result.rowcount)

    def reorder(
        self, *, tenant_id: UUID, connection_id: UUID, template_ids: Sequence[UUID]
    ) -> list[ReplyTemplate]:
        with tenant_session(tenant_id) as session:
            self._lock(session, tenant_id, connection_id)
            current = session.scalars(
                select(ConversationReplyTemplate.id).where(
                    ConversationReplyTemplate.connection_id == connection_id
                )
            ).all()
            _check_order(current, template_ids)
            now = _utcnow()
            for position, template_id in enumerate(template_ids):
                session.execute(
                    update(ConversationReplyTemplate)
                    .where(ConversationReplyTemplate.id == template_id)
                    .values(position=position, updated_at=now)
                )
            session.flush()
            return [_record(r) for r in session.scalars(_ordered(connection_id)).all()]


# --- service ---------------------------------------------------------------------------


class ThreadReader(Protocol):
    """The one read `render` needs (`ConversationRepository.get_thread`)."""

    def get_thread(self, *, tenant_id: UUID, thread_id: UUID) -> ThreadRecord | None: ...


# `(tenant_id, connection_id) -> the brand name behind the account`, or None.
BrandNameReader = Callable[[UUID, UUID], "str | None"]


class ReplyTemplateService:
    """The seam the composer consumes. Validation lives here; persistence in the
    repository; nothing here can send (no outbox, no channel)."""

    def __init__(
        self,
        *,
        repository: ReplyTemplateRepository,
        threads: ThreadReader,
        brand_name: BrandNameReader,
    ) -> None:
        self._repo = repository
        self._threads = threads
        self._brand_name = brand_name

    def list_for_connection(self, *, tenant_id: UUID, connection_id: UUID) -> list[ReplyTemplate]:
        """The account's library in picker order, seeding the defaults on first use."""
        self._repo.ensure_defaults(tenant_id=tenant_id, connection_id=connection_id)
        return self._repo.list_templates(tenant_id=tenant_id, connection_id=connection_id)

    def create(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        title: str,
        body: str,
        user_id: UUID | None,
        buttons: Sequence[TemplateButton] | None = None,
    ) -> ReplyTemplate:
        """A new template at the end of the list — with `buttons` (1–3), a template sent
        as a button template. Raises `ReplyTemplateError` (`title_*`, `body_*`,
        `limit_reached`, a button code of `interactive`, `body_too_long_for_buttons`) or
        `ReplyTemplateNotFound`."""
        clean_title, clean_body = clean_template(title, body)
        cleaned_buttons = clean_template_buttons(clean_body, buttons or ())
        # The defaults come first even when the very first action is «Crear».
        self._repo.ensure_defaults(tenant_id=tenant_id, connection_id=connection_id)
        if cleaned_buttons:
            return self._repo.create_template(
                tenant_id=tenant_id,
                connection_id=connection_id,
                title=clean_title,
                body=clean_body,
                user_id=user_id,
                buttons=cleaned_buttons,
            )
        return self._repo.create_template(
            tenant_id=tenant_id,
            connection_id=connection_id,
            title=clean_title,
            body=clean_body,
            user_id=user_id,
        )

    def update(
        self,
        *,
        tenant_id: UUID,
        template_id: UUID,
        title: str,
        body: str,
        user_id: UUID | None,
        buttons: Sequence[TemplateButton] | None = None,
    ) -> ReplyTemplate:
        """Edit a template (a seeded default too: it keeps its `default_key`).
        `buttons=None` keeps the template's buttons as they are (a PR-1 caller that edits
        only title and body never strips them); `buttons=()` removes them; a sequence
        replaces them. The body is checked against 640 whenever buttons remain."""
        clean_title, clean_body = clean_template(title, body)
        if buttons is None:
            current = self._repo.get_template(tenant_id=tenant_id, template_id=template_id)
            if current is None:
                raise ReplyTemplateNotFound(ERR_TEMPLATE_NOT_FOUND)
            buttons = current.buttons
        cleaned_buttons = clean_template_buttons(clean_body, buttons)
        updated = self._repo.update_template(
            tenant_id=tenant_id,
            template_id=template_id,
            title=clean_title,
            body=clean_body,
            user_id=user_id,
            buttons=cleaned_buttons,
        )
        if updated is None:
            raise ReplyTemplateNotFound(ERR_TEMPLATE_NOT_FOUND)
        return updated

    def delete(self, *, tenant_id: UUID, template_id: UUID) -> bool:
        """Delete for real. Idempotent: False when it was already gone (a double tap).
        A deleted default is not re-created (the seed marker remembers)."""
        return self._repo.delete_template(tenant_id=tenant_id, template_id=template_id)

    def reorder(
        self, *, tenant_id: UUID, connection_id: UUID, template_ids: Sequence[UUID]
    ) -> list[ReplyTemplate]:
        """`template_ids` is the WHOLE library in its new order. Anything else — a missing,
        extra or repeated id (the list changed under the person) — raises
        `ReplyTemplateError(order_stale)` and moves nothing."""
        return self._repo.reorder(
            tenant_id=tenant_id, connection_id=connection_id, template_ids=list(template_ids)
        )

    def render(self, *, tenant_id: UUID, template_id: UUID, thread_id: UUID) -> RenderedTemplate:
        """The template's text for THIS thread, ready to edit in the composer. Reads the
        thread and the brand name; writes nothing and queues nothing."""
        template = self._repo.get_template(tenant_id=tenant_id, template_id=template_id)
        if template is None:
            raise ReplyTemplateNotFound(ERR_TEMPLATE_NOT_FOUND)
        thread = self._threads.get_thread(tenant_id=tenant_id, thread_id=thread_id)
        if thread is None:
            raise ReplyTemplateNotFound(ERR_THREAD_NOT_FOUND)
        if thread.connection_id != template.connection_id:
            raise ReplyTemplateError(ERR_OTHER_ACCOUNT)
        values = {
            VAR_NAME: counterpart_display_name(thread),
            VAR_BRAND: self._brand_name(tenant_id, thread.connection_id),
        }
        rendered = render_template(template.body, values, template_id=template.id)
        return replace(rendered, buttons=template.buttons) if template.buttons else rendered


__all__ = [
    "DEFAULTS_VERSION",
    "DEFAULT_TEMPLATES",
    "KIND_BUTTONS",
    "KIND_TEXT",
    "MAX_BODY_CHARS",
    "MAX_BUTTONS_BODY_CHARS",
    "MAX_TEMPLATES_PER_CONNECTION",
    "MAX_TITLE_CHARS",
    "MESSAGES",
    "SUPPORTED_VARIABLES",
    "BrandNameReader",
    "DefaultTemplate",
    "MemoryReplyTemplateRepository",
    "PostgresReplyTemplateRepository",
    "RenderedTemplate",
    "ReplyTemplate",
    "ReplyTemplateError",
    "ReplyTemplateNotFound",
    "ReplyTemplateRepository",
    "ReplyTemplateService",
    "ThreadReader",
    "clean_template",
    "clean_template_buttons",
    "counterpart_display_name",
    "render_template",
]

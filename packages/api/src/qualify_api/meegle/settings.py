"""Runtime configuration of the Meegle onboarding engine (plan `docs/plan-altas-meegle.md`).

Everything comes from the environment; nothing here talks to Meegle. The engine is
**off** until all seven variables are set: `MeegleSettings.from_env()` raises
`MeegleNotConfigured` naming the missing ones, and `meegle_configured()` lets callers that
can degrade (the webhook processor, which then leaves Meegle events `unsupported` in the
queue; the registration write-back, which then does nothing) ask first. There is no dev
default for any of them — a forgotten value must fail loudly, never make Qualify write into
someone else's space.

    QUALIFY_MEEGLE_BASE_URL         https://meegle.com (default); the Open API host
    QUALIFY_MEEGLE_PLUGIN_ID        the plugin's id (also the first piece of the signature)
    QUALIFY_MEEGLE_PLUGIN_SECRET    the plugin's secret (SECRET — confined to this package
                                    by `test_meegle_sanctity.py`)
    QUALIFY_MEEGLE_CALLBACK_TOKEN   the Event Listener's callback token (signature)
    QUALIFY_MEEGLE_PROJECT_KEY      the space ("Qualify")
    QUALIFY_MEEGLE_WORK_ITEM_TYPE   the "Alta de cliente" work item type key
    QUALIFY_MEEGLE_USER_KEY         whose name the writes carry (`X-User-Key`, plan D1)

The ticket notifier (`tickets.py`, plan §3bis) is a second, optional layer on the same
engine — off until its webhook is set, with the six above still required:

    QUALIFY_MEEGLE_NOTIFY_WEBHOOK_URL  Lark custom bot webhook of the group that hears
                                       ticket changes (SECRET on Lark's side: whoever has
                                       it can post there)
    QUALIFY_MEEGLE_TICKET_TYPES        work item type keys it covers; default
                                       `story,issue,sub_task` (Features, Issues, Tasks)
    QUALIFY_MEEGLE_WEB_URL             host of the links in the notices; default
                                       https://project.larksuite.com (where the real item
                                       URLs live — meegle.com is the API host only)

The names of the fields and nodes Qualify reads and writes (`MeegleNames`) default to the
plan's §2 and can be overridden one by one (`QUALIFY_MEEGLE_FIELD_*`, `QUALIFY_MEEGLE_NODE_*`)
if the item is created with other labels (e.g. `QUALIFY_MEEGLE_FIELD_PLAN`,
`QUALIFY_MEEGLE_FIELD_PACK`, `QUALIFY_MEEGLE_FIELD_PLAN_REASON`, `QUALIFY_MEEGLE_NODE_PLAN`
for the plan fields and node of m-24852131). Keys and node ids are never configured: the
engine resolves them from the names through the metadata calls, once, and caches them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields

DEFAULT_BASE_URL = "https://meegle.com"

_REQUIRED = (
    "QUALIFY_MEEGLE_PLUGIN_ID",
    "QUALIFY_MEEGLE_PLUGIN_SECRET",
    "QUALIFY_MEEGLE_CALLBACK_TOKEN",
    "QUALIFY_MEEGLE_PROJECT_KEY",
    "QUALIFY_MEEGLE_WORK_ITEM_TYPE",
    "QUALIFY_MEEGLE_USER_KEY",
)


class MeegleNotConfigured(RuntimeError):
    """The engine is off: at least one `QUALIFY_MEEGLE_*` variable is missing."""


@dataclass(frozen=True)
class MeegleSettings:
    base_url: str
    plugin_id: str
    plugin_secret: str
    callback_token: str
    project_key: str
    work_item_type: str
    user_key: str

    @classmethod
    def from_env(cls) -> MeegleSettings:
        values = {name: os.environ.get(name, "").strip() for name in _REQUIRED}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise MeegleNotConfigured(f"Meegle engine is off: {', '.join(missing)} not set")
        return cls(
            base_url=(
                os.environ.get("QUALIFY_MEEGLE_BASE_URL", "").strip() or DEFAULT_BASE_URL
            ).rstrip("/"),
            plugin_id=values["QUALIFY_MEEGLE_PLUGIN_ID"],
            plugin_secret=values["QUALIFY_MEEGLE_PLUGIN_SECRET"],
            callback_token=values["QUALIFY_MEEGLE_CALLBACK_TOKEN"],
            project_key=values["QUALIFY_MEEGLE_PROJECT_KEY"],
            work_item_type=values["QUALIFY_MEEGLE_WORK_ITEM_TYPE"],
            user_key=values["QUALIFY_MEEGLE_USER_KEY"],
        )


def meegle_configured() -> bool:
    """True iff every required variable is set (the cheap question before building anything)."""
    return all(os.environ.get(name, "").strip() for name in _REQUIRED)


NOTIFY_WEBHOOK_ENV = "QUALIFY_MEEGLE_NOTIFY_WEBHOOK_URL"
TICKET_TYPES_ENV = "QUALIFY_MEEGLE_TICKET_TYPES"
WEB_URL_ENV = "QUALIFY_MEEGLE_WEB_URL"
DEFAULT_WEB_URL = "https://project.larksuite.com"
DEFAULT_TICKET_TYPES = ("story", "issue", "sub_task")


@dataclass(frozen=True)
class TicketSettings:
    """The ticket notifier's own knobs. `webhook_url == ""` means the notifier is off."""

    webhook_url: str
    ticket_types: frozenset[str]
    web_url: str

    @classmethod
    def from_env(cls) -> TicketSettings:
        raw_types = os.environ.get(TICKET_TYPES_ENV, "").strip()
        types = frozenset(
            part.strip() for part in raw_types.split(",") if part.strip()
        ) or frozenset(DEFAULT_TICKET_TYPES)
        return cls(
            webhook_url=os.environ.get(NOTIFY_WEBHOOK_ENV, "").strip(),
            ticket_types=types,
            web_url=(os.environ.get(WEB_URL_ENV, "").strip() or DEFAULT_WEB_URL).rstrip("/"),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)


@dataclass(frozen=True)
class MeegleNames:
    """Display names of the fields and nodes of the "Alta de cliente" item (plan §2)."""

    # fields a person fills
    email: str = "Correo"
    person_name: str = "Nombre de la persona"
    note: str = "Nota personal"
    # optional: absent from the type, or empty, the invitation goes out as before (PB-1)
    instagram: str = "Cuenta de Instagram"  # legacy identifier field; never implies network
    channel: str = "Canal"
    account: str = "Cuenta"
    # optional (m-24852131): the plan and fixed pack the team gives the business; absent
    # from the type, or empty, the business stays on the default plan (Básico)
    plan: str = "Plan"
    pack: str = "Paquete"
    plan_reason: str = "Motivo"
    # fields Qualify writes
    status: str = "Estado Qualify"
    invite_link: str = "Enlace de invitación"
    expires: str = "Vence"
    registered_at: str = "Registrada el"
    tenant: str = "Tenant"
    qualify_ref: str = "Qualify ref"
    # nodes
    node_data: str = "Datos"
    node_invited: str = "Invitada"
    node_registered: str = "Registrada"
    # m-24852131: completed (again) on a registered Alta to apply «Plan» / «Paquete»
    node_plan: str = "Plan ampliado"
    # m-24823681: Brand Kit saved — Qualify posts the consumption summary on it
    node_brand_kit_ready: str = "Kit de marca listo"

    @classmethod
    def from_env(cls) -> MeegleNames:
        overrides: dict[str, str] = {}
        for field in fields(cls):
            is_node = field.name.startswith("node_")
            prefix = "QUALIFY_MEEGLE_NODE_" if is_node else "QUALIFY_MEEGLE_FIELD_"
            key = field.name.removeprefix("node_").upper()
            value = os.environ.get(prefix + key, "").strip()
            if value:
                overrides[field.name] = value
        return cls(**overrides)


# Option labels of the "Estado Qualify" select (plan §2).
STATUS_PENDING = "pendiente"
STATUS_INVITED = "invitada"
STATUS_DELIVERED = "entregada"
STATUS_OPENED = "abierta"
STATUS_BOUNCED = "rebotó"
STATUS_REGISTERED = "registrada"
STATUS_EXPIRED = "vencida"
STATUS_ERROR = "error"

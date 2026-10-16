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

The names of the fields and nodes Qualify reads and writes (`MeegleNames`) default to the
plan's §2 and can be overridden one by one (`QUALIFY_MEEGLE_FIELD_*`, `QUALIFY_MEEGLE_NODE_*`)
if the item is created with other labels. Keys and node ids are never configured: the
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


@dataclass(frozen=True)
class MeegleNames:
    """Display names of the fields and nodes of the "Alta de cliente" item (plan §2)."""

    # fields a person fills
    email: str = "Correo"
    person_name: str = "Nombre de la persona"
    note: str = "Nota personal"
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

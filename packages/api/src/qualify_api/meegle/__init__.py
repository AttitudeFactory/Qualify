"""Client onboarding operated from Meegle (`docs/plan-altas-meegle.md`, phase M1).

Qualify has no admin screen for onboarding (founder decision 2026-10-16): each client is a
Meegle work item "Alta de cliente", and this package is the engine behind it —

- `settings`  — `QUALIFY_MEEGLE_*`; unset = engine off (`MeegleNotConfigured`, loud).
- `envelope`  — the Event Listener body: signature check, split into the intake's shape.
- `receiver`  — the request-path half: record the event through the Meta intake's
                INSERT-only door (`POST /api/meegle/events`, `http/meegle_routes.py`).
- `client`    — thin httpx client over the Open API (plugin token, six calls).
- `schema`    — field keys, select values and node ids resolved by display name, cached.
- `onboarding`— the use-cases: invite on **Datos**, expire on termination, mark
                **Registrada** on signup.
- `handlers`  — the webhook-processor handlers (`meegle:2001`, `meegle:1005`,
                `meegle:2004`) and their production assembly.

The plugin secret is confined to this package (`test_meegle_sanctity.py`).
"""

from qualify_api.meegle.settings import (
    MeegleNames,
    MeegleNotConfigured,
    MeegleSettings,
    meegle_configured,
)

__all__ = ["MeegleNames", "MeegleNotConfigured", "MeegleSettings", "meegle_configured"]

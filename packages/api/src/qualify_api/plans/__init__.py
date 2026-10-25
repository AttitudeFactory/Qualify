"""Planes Básico / Plus / Pro (m-24852145), with the subscription shape of ADR 43.

- `catalog`: `planes-v1` and `precios-planes-v1`, versioned data files.
- `schedule`: when a change applies (upgrade now, downgrade next month).
- `billing`: what the team charges a month, by hand (team only).
- `read`: the request path's read-only view of a business's plan (`business_plans`).
- `service`, `cli`: the team's write path (`admin_session`): `just set-plan`, `just plans`.
- `cost_alerts`: the USD cap alert (D18), never a pause.
- `report`: cost against charge (team only).
"""

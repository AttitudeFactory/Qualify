"""Confirmed operational overlays, separate from the immutable initial approval."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.promotions import Promotion, fingerprint
from qualify_api.ads.results import ResultsUnavailable

EDIT_PIPELINE = "ad-verified-edit-v1"


def consistent_intent(action: str, payload: Any, before: Any, after: Any) -> bool:
    if (
        not isinstance(payload, dict)
        or not isinstance(before, dict)
        or not isinstance(after, dict)
        or set(before) != {"budget_minor", "end_time"}
        or set(after) != set(before)
        or type(before["budget_minor"]) is not int
        or type(after["budget_minor"]) is not int
        or not isinstance(before["end_time"], str)
        or not isinstance(after["end_time"], str)
    ):
        return False
    if action == "budget":
        return (
            # Increase or decrease (m-24828979); a decrease is floored before review.
            0 < before["budget_minor"] < 10**18
            and 0 < after["budget_minor"] < 10**18
            and after["budget_minor"] != before["budget_minor"]
            and type(payload.get("lifetime_budget")) is int
            and after["budget_minor"] % 100 == 0
            and after["end_time"] == before["end_time"]
            and payload == {"lifetime_budget": after["budget_minor"] // 100}
        )
    if action == "end_time":
        return after["budget_minor"] == before["budget_minor"] and payload == {
            "end_time": after["end_time"]
        }
    return action == "resume" and before == after and payload == {"status": "ACTIVE"}


def operations(session: Any, promotion_id: UUID) -> list[Any]:
    return list(
        session.execute(
            text(
                "SELECT id,action,payload,approval_evidence,state FROM ad_promotion_operations "
                "WHERE promotion_id=:id ORDER BY created_at,id"
            ),
            {"id": promotion_id},
        )
        .mappings()
        .all()
    )


def revision(rows: list[Any]) -> str:
    # Includes failed and uncertain claims too. A new review cannot silently reuse a
    # baseline after a different actor started and rolled back another operation.
    return fingerprint([{"id": str(row["id"]), "state": row["state"]} for row in rows])


def overlay(promotion: Promotion, rows: list[Any]) -> Promotion:
    request = deepcopy(promotion.request)
    for row in rows:
        evidence = row["approval_evidence"]
        if row["state"] not in {"completed", "reconciled"} or row["action"] == "pause":
            continue
        if (
            not isinstance(evidence, dict)
            or evidence.get("pipeline") != EDIT_PIPELINE
            or evidence.get("confirmed") is not True
        ):
            raise ResultsUnavailable("Falta comprobar un cambio anterior de esta promoción.")
        before, after = evidence.get("before"), evidence.get("after")
        if not consistent_intent(row["action"], row["payload"], before, after):
            raise ResultsUnavailable("El cambio guardado necesita una nueva comprobación.")
        current = {key: request[key] for key in ("budget_minor", "end_time")}
        if before != current or not isinstance(after, dict) or set(after) != set(current):
            raise ResultsUnavailable("El historial cambió. Revisa la promoción antes de editarla.")
        request.update(after)
    return replace(promotion, request=request)


def effective(tenant_id: UUID, promotion: Promotion) -> tuple[Promotion, str]:
    with tenant_session(tenant_id, independent=True) as session:
        rows = operations(session, promotion.id)
    if any(row["state"] in {"in_flight", "unknown"} for row in rows):
        raise ResultsUnavailable(
            "Hay un cambio por comprobar. Actualiza el estado antes de continuar."
        )
    return overlay(promotion, rows), revision(rows)

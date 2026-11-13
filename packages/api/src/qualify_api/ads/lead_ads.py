"""Lead-ad destination: an already-published Meta form inside the approved snapshot (m-24828981).

The form is frozen into the immutable promotion request; creation stays paused and
activation goes through the same explicit consent path as every other promotion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from qualify_api.ads.messaging import numeric_id

LEAD_CTAS = ("SIGN_UP", "LEARN_MORE", "GET_QUOTE")
LEAD_OBJECTIVE = "OUTCOME_LEADS"
# shortcut: QUALITY_LEAD (conversion leads) needs a CRM event setup; add it when measured.
LEAD_OPTIMIZATION = "LEAD_GENERATION"


@dataclass(frozen=True)
class LeadFormTarget:
    form_id: UUID
    meta_form_id: str
    page_id: str
    connection_id: UUID
    brand_id: UUID
    credential_version: int

    def snapshot(self) -> dict[str, Any]:
        if (
            not isinstance(self.form_id, UUID)
            or not isinstance(self.connection_id, UUID)
            or not isinstance(self.brand_id, UUID)
            or numeric_id(self.meta_form_id) is None
            or numeric_id(self.page_id) is None
            or type(self.credential_version) is not int
            or self.credential_version < 1
        ):
            raise ValueError("invalid lead form destination")
        return {
            key: str(value) if isinstance(value, UUID) else value
            for key, value in asdict(self).items()
        }

    @classmethod
    def from_snapshot(cls, value: dict[str, Any]) -> LeadFormTarget:
        try:
            target = cls(
                form_id=UUID(value["form_id"]),
                meta_form_id=value["meta_form_id"],
                page_id=value["page_id"],
                connection_id=UUID(value["connection_id"]),
                brand_id=UUID(value["brand_id"]),
                credential_version=value["credential_version"],
            )
            if target.snapshot() != value:
                raise ValueError("unexpected lead form fields")
            return target
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("invalid lead form snapshot") from exc

    def matches(self, source: Any) -> bool:
        """Same connection, brand, Page and access version as the promoted publication."""
        return (
            self.connection_id == source.connection_id
            and self.brand_id == source.brand_id
            and self.page_id == source.linked_page_id
            and self.credential_version == source.credential_version
        )

    def call_to_action(self, cta_type: str) -> dict[str, Any]:
        return {"type": cta_type, "value": {"lead_gen_form_id": self.meta_form_id}}

    def adset_options(self) -> dict[str, Any]:
        return {
            "optimization_goal": LEAD_OPTIMIZATION,
            "billing_event": "IMPRESSIONS",
            "destination_type": "ON_AD",
            "promoted_object": {"page_id": self.page_id},
        }

    def validate_request(self, request: Any) -> None:
        self.snapshot()
        creative = request.creative
        if (
            request.messaging_snapshot
            or request.objective != LEAD_OBJECTIVE
            or request.cta_type not in LEAD_CTAS
            or request.link_url
            or str(request.brand_id) != str(self.brand_id)
            or request.adset_options != self.adset_options()
            or not isinstance(creative, dict)
            or creative.get("object_id") != self.page_id
            or creative.get("source_instagram_media_id") != request.source_media_id
            or creative.get("call_to_action") != self.call_to_action(request.cta_type)
        ):
            raise ValueError("lead form destination differs from approved request")


def published_lead_form(tenant_id: UUID, form_id: UUID) -> LeadFormTarget:
    """Read a form of this tenant that Meta already accepted; drafts and unknowns never pass."""
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import text

    from qualify_api.ads.wizard import WizardUnavailable

    with tenant_session(tenant_id) as session:
        row = session.execute(
            text("""SELECT f.id,f.meta_form_id,f.page_id,f.connection_id,f.brand_id,
            f.credential_version FROM ad_lead_forms f JOIN social_connections c
              ON c.id=f.connection_id AND c.tenant_id=f.tenant_id AND c.brand_id=f.brand_id
            WHERE f.id=:id AND f.status='published' AND c.status='active'
              AND c.linked_page_id=f.page_id
              AND c.current_credential_version=f.credential_version
              AND c.purge_started_at IS NULL AND c.purged_at IS NULL"""),
            {"id": form_id},
        ).first()
    if row is None:
        raise WizardUnavailable(
            "Elige un formulario que ya esté listo y sea de la misma cuenta de esta publicación."
        )
    return LeadFormTarget(
        row.id,
        row.meta_form_id,
        row.page_id,
        row.connection_id,
        row.brand_id,
        row.credential_version,
    )

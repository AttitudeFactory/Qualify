"""The leads plane of the CRM: the people each tenant has converted into contactable
leads, captured today through the public per-tenant form (the funnel demo for small
businesses) and readable from the Qualify dashboard.

What gets captured varies per tenant: the fixed columns are the invariant core
(identity + consent + attribution) and `lead_form_settings.custom_fields` declares the
tenant-specific questions, whose answers land in `leads.extra`.

The published seam (same shape as `connections`): plain functions/objects over ids, used
by the HTTP routes and by the Reflex UI in-process.
"""

from qualify_api.leads.composition import production_leads_service, upsert_form_settings
from qualify_api.leads.service import (
    FormNotFound,
    IntakeAccepted,
    LeadIntakeService,
    LeadSubmission,
    PublicForm,
    RateLimited,
)

__all__ = [
    "FormNotFound",
    "IntakeAccepted",
    "LeadIntakeService",
    "LeadSubmission",
    "PublicForm",
    "RateLimited",
    "production_leads_service",
    "upsert_form_settings",
]

"""Interest from visitors without an invitation (MARCA-5, m-24842968; founder decision 7b).

Signup is invite-only. A visitor who opens «Crear mi marca» without a code reads that
first and, instead of building a brand that would end in a closed door, leaves their
name, their business and their WhatsApp. That entry is written to the **leads module of
a house tenant** — the business the founder logs into to read `/leads` — named by the
setting `QUALIFY_INTEREST_TENANT_ID`. No account, no tenant and no invite are created
here; the founder answers by WhatsApp and sends an invitation by hand (`just invite`).

Guards, in order, all cheap and all before any write:

1. **Honeypot** (`website`): a field humans never see. Filled → a plausible success and
   nothing written (a refusal would tell the bot which field to stop filling).
2. **Rate limit** per client key, before any DB work.
3. **Consent** is mandatory: «Acepto que me escriban por WhatsApp». Without it nothing
   is stored — `leads.consent_at` is NOT NULL (migration 0005).
4. **Setting**: with `QUALIFY_INTEREST_TENANT_ID` unset or malformed the safe fallback is
   to write nowhere and say so (`InterestNotConfigured`); never a guessed tenant.
5. **Fields**: name, business and a WhatsApp number that resolves to E.164.

Privacy: the phone number is personal data. It is stored (that is the point) but never
logged and never put in an exception message; logs carry only the outcome.

It does not need a `lead_form_settings` row: the house tenant's `/leads` reads `leads`
directly, the consent text and its version are this module's constants, and the
business name travels in `extra["negocio"]` (shown as «negocio: …» on `/leads`).
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from qualify_api.leads.rate_limit import RateLimiter
from qualify_api.leads.repository import LeadRecord, LeadRepository, normalize_phone

logger = logging.getLogger(__name__)

INTEREST_TENANT_ENV = "QUALIFY_INTEREST_TENANT_ID"

#: The consent the checkbox shows, verbatim, and the version stamped on every row.
INTEREST_CONSENT_TEXT = "Acepto que me escriban por WhatsApp"
INTEREST_CONSENT_VERSION = "acceso-invitacion-2026-10"
#: What `/leads` shows as the source of these entries.
INTEREST_SOURCE = "Pidió invitación"
#: The `extra` key the business name is stored under («negocio: …» on `/leads`).
BUSINESS_KEY = "negocio"

_NAME_MAX = 120
#: Country codes of the three markets: a number typed without «+» but starting with one of
#: these (and long enough to carry a subscriber number) is read as international.
_MARKET_PREFIXES = ("598", "57", "58")


class InterestNotConfigured(Exception):
    """`QUALIFY_INTEREST_TENANT_ID` is unset or not a uuid: nothing can be stored."""


class InterestRateLimited(Exception):
    pass


class InterestInvalid(Exception):
    """A field the visitor must fix. `field` is one of `full_name`, `business_name`,
    `whatsapp_phone`, `consent` — the UI maps it to its own Spanish sentence."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


@dataclass(frozen=True)
class InterestRequest:
    full_name: str
    business_name: str
    whatsapp_phone: str  # raw, as typed
    consent: bool
    honeypot: str = ""


@dataclass(frozen=True)
class InterestOutcome:
    #: False only when the honeypot fired: the visitor sees the same confirmation.
    saved: bool


def interest_tenant_id(environ: dict[str, str] | None = None) -> UUID | None:
    """The house tenant that receives the entries, or None when the setting is unset or
    malformed (the safe fallback: store nothing rather than guess a tenant)."""
    raw = (environ if environ is not None else os.environ).get(INTEREST_TENANT_ENV, "").strip()
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        logger.warning("%s is not a uuid; interest entries are not stored", INTEREST_TENANT_ENV)
        return None


def normalize_interest_phone(raw: str) -> str:
    """The WhatsApp number as E.164. Owners type it the way they say it: spaces, dashes,
    `00` instead of `+`, or the country code without the `+` («58 414 123 4567»). A local
    number with no country code cannot be resolved without guessing, so it is refused
    (`normalize_phone`'s rule: never attach the wrong country). Raises `ValueError`."""
    candidate = re.sub(r"[\s\-().]", "", raw or "")
    if candidate.startswith("00"):
        candidate = "+" + candidate[2:]
    elif candidate.isdigit() and len(candidate) >= 11 and candidate.startswith(_MARKET_PREFIXES):
        candidate = "+" + candidate
    return normalize_phone(candidate)


def _clean(text: str) -> str:
    return " ".join((text or "").split())


class AccessInterestService:
    def __init__(
        self,
        *,
        repository: LeadRepository,
        limiter: RateLimiter,
        tenant_id: Callable[[], UUID | None] = interest_tenant_id,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._limiter = limiter
        self._tenant_id = tenant_id
        self._now = now

    def submit(self, request: InterestRequest, *, client_key: str) -> InterestOutcome:
        """Store one consented entry in the house tenant's leads. Raises
        `InterestRateLimited`, `InterestInvalid` or `InterestNotConfigured`."""
        if request.honeypot.strip():
            logger.info("interest form: honeypot filled, nothing stored")
            return InterestOutcome(saved=False)
        if not self._limiter.allow(f"interest:{client_key}"):
            raise InterestRateLimited
        if request.consent is not True:
            raise InterestInvalid("consent")
        full_name = _clean(request.full_name)
        business_name = _clean(request.business_name)
        if not full_name or len(full_name) > _NAME_MAX:
            raise InterestInvalid("full_name")
        if not business_name or len(business_name) > _NAME_MAX:
            raise InterestInvalid("business_name")
        try:
            phone = normalize_interest_phone(request.whatsapp_phone)
        except ValueError:
            raise InterestInvalid("whatsapp_phone") from None
        tenant_id = self._tenant_id()
        if tenant_id is None:
            logger.warning("interest form: %s unset, nothing stored", INTEREST_TENANT_ENV)
            raise InterestNotConfigured
        self._repository.upsert_lead(
            tenant_id=tenant_id,
            record=LeadRecord(
                full_name=full_name,
                whatsapp_phone=phone,
                consent_at=self._now(),
                consent_policy_version=INTEREST_CONSENT_VERSION,
                source_declared=INTEREST_SOURCE,
                extra={BUSINESS_KEY: business_name},
            ),
        )
        logger.info("interest form: entry stored")
        return InterestOutcome(saved=True)

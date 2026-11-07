"""Short-lived exact-request evidence; never a minimum-budget or delivery guarantee."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from qualify_api.ads.promotions import fingerprint

PIPELINE = "ad-exact-validation-v1"


def context(source: Any, form: Any) -> dict[str, Any]:
    return {
        "source": {
            key: str(getattr(source, key))
            for key in (
                "publish_attempt_id",
                "content_draft_id",
                "connection_id",
                "brand_id",
                "source_media_id",
                "instagram_user_id",
                "meta_ad_account_id",
                "currency",
                "timezone_name",
                "credential_version",
                "linked_page_id",
            )
        },
        "form_hash": fingerprint(json.loads(json.dumps(asdict(form), default=str))),
    }


def payloads_for_validation(
    source: Any, form: Any, actor: Any, requested: datetime, offset: int | None
) -> dict[str, Any]:
    from uuid import UUID

    from qualify_api.ads.promotions import Promotion, step_payload
    from qualify_api.ads.wizard_workflow import _request

    tenant = form.enhancements.tenant_id
    request = _request(tenant, source, form, actor, "validation", requested, currency_offset=offset)
    draft = Promotion(
        UUID(int=0), request.snapshot(), ids={"campaigns": "0", "adsets": "0", "adcreatives": "0"}
    )
    campaign = step_payload(draft, "campaigns")
    adset = step_payload(draft, "adsets")
    adset.pop("campaign_id")
    adset["campaign_spec"] = campaign
    creative = step_payload(draft, "adcreatives")
    ad = step_payload(draft, "ads")
    ad.pop("adset_id")
    ad["adset_spec"], ad["creative"] = adset, creative
    return {"campaigns": campaign, "adsets": adset, "adcreatives": creative, "ads": ad}


def receipt(
    source: Any,
    form: Any,
    actor: Any,
    now: datetime,
    *,
    requested: datetime,
    offset: int,
    payloads: dict[str, Any],
) -> dict[str, Any]:
    return {
        **context(source, form),
        "actor": str(actor),
        "observed_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "pipeline": PIPELINE,
        "validated_resources": ["campaigns", "adsets", "adcreatives", "ads"],
        "no_known_payment_block": True,
        "currency_offset": offset,
        "approved_budget_minor": form.budget_minor,
        "meta_budget": form.budget_minor * offset // 100,
        "requested_at": requested.isoformat(),
        "payload_hashes": {key: fingerprint(value) for key, value in payloads.items()},
    }


def valid_receipt(value: Any, source: Any, form: Any, now: datetime, actor: Any = None) -> bool:
    try:
        observed = datetime.fromisoformat(value["observed_at"])
        expires = datetime.fromisoformat(value["expires_at"])
        requested = datetime.fromisoformat(value["requested_at"])
        offset = value["currency_offset"]
        payloads = payloads_for_validation(source, form, actor, requested, offset)
        return (
            isinstance(value, dict)
            and value.get("pipeline") == PIPELINE
            and value.get("source") == context(source, form)["source"]
            and value.get("form_hash") == context(source, form)["form_hash"]
            and actor is not None
            and value.get("actor") == str(actor)
            and type(offset) is int
            and offset == 1
            and value.get("approved_budget_minor") == form.budget_minor
            and value.get("meta_budget") == form.budget_minor * offset // 100
            and form.budget_minor * offset % 100 == 0
            and value.get("payload_hashes")
            == {key: fingerprint(payload) for key, payload in payloads.items()}
            and value.get("validated_resources") == ["campaigns", "adsets", "adcreatives", "ads"]
            and value.get("no_known_payment_block") is True
            and observed.utcoffset() is not None
            and expires.utcoffset() is not None
            and observed <= now < expires <= observed + timedelta(minutes=5)
            and requested.utcoffset() is not None
            and observed - timedelta(minutes=5) <= requested <= observed
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return False

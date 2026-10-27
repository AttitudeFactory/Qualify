"""Public application origin for transactional email links (m-24842840)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from ipaddress import ip_address
from urllib.parse import urlsplit

from qualify_api.mail import MailNotConfigured


def public_app_url(env: Mapping[str, str] | None = None) -> str:
    """Use deployment configuration; never send a local fallback in production."""
    values = os.environ if env is None else env
    production = values.get("QUALIFY_DEPLOY_ENV", "").strip().lower() == "production"
    url = (
        values.get("QUALIFY_PUBLIC_URL", "").strip() or values.get("REFLEX_DEPLOY_URL", "").strip()
    )
    if not url:
        if production:
            raise MailNotConfigured("QUALIFY_PUBLIC_URL is required for production mail links")
        return "http://localhost:3000"
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    local = host == "localhost" or host.endswith(".localhost")
    try:
        address = ip_address(host)
        local = local or address.is_loopback or address.is_unspecified
    except ValueError:
        pass
    if (
        parsed.scheme not in ("http", "https")
        or not host
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (production and (parsed.scheme != "https" or local))
    ):
        raise MailNotConfigured(
            "production mail links need a public HTTPS application URL"
            if production
            else "invalid public application URL for mail"
        )
    return url.rstrip("/")

"""Pinterest application settings; customer grants never come from environment tokens."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class PinterestSettings:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str
    state_secret: str = field(repr=False)
    state_ttl_seconds: int = 600

    def __post_init__(self) -> None:
        parsed = urlsplit(self.redirect_uri)
        local = parsed.hostname in {"localhost", "127.0.0.1"}
        if (
            not self.client_id
            or not self.client_secret
            or len(self.state_secret) < 32
            or (parsed.scheme != "https" and not (local and parsed.scheme == "http"))
            or not parsed.hostname
            or parsed.username
            or parsed.query
            or parsed.fragment
            or parsed.path != "/api/connections/pinterest/callback"
        ):
            raise ValueError("Pinterest application settings are incomplete or invalid")

    @classmethod
    def from_env(cls) -> PinterestSettings:
        return cls(
            os.getenv("PINTEREST_CLIENT_ID", ""),
            os.getenv("PINTEREST_CLIENT_SECRET", ""),
            os.getenv("PINTEREST_REDIRECT_URI", ""),
            os.getenv("PINTEREST_STATE_SECRET", "") or os.getenv("QUALIFY_OAUTH_STATE_SECRET", ""),
        )

    @classmethod
    def is_configured(cls) -> bool:
        try:
            cls.from_env()
        except ValueError:
            return False
        return bool(os.getenv("PINTEREST_FERNET_KEY") or os.getenv("QUALIFY_DEV_FERNET_KEY"))

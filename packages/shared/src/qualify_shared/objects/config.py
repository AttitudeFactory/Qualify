"""R2 connection settings, read from the environment.

Mirrors `MetaOAuthSettings` (`qualify_api.config`) on purpose: a frozen dataclass with a
`from_env()` classmethod, so configuration is data that can be constructed in a test without
touching the process environment.

**There is no dev fallback, and that is the point.** `MetaOAuthSettings` can afford
`dev-app-id` defaults because a wrong Meta credential fails loudly at Meta. An object store
is different: a default endpoint or bucket would let a forgotten override *succeed* against
the wrong bucket, which is indistinguishable from working until someone looks for the file.
So every field is required and `from_env()` raises naming the missing variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# R2 speaks S3 with a fixed pseudo-region; both values are properties of the provider, not
# deployment choices, so they are constants rather than settings.
R2_REGION_NAME = "auto"
R2_SIGNATURE_VERSION = "s3v4"

_REQUIRED_VARS = (
    "QUALIFY_R2_ENDPOINT_URL",
    "QUALIFY_R2_ACCESS_KEY_ID",
    "QUALIFY_R2_SECRET_ACCESS_KEY",
    "QUALIFY_R2_BUCKET",
)


class R2ConfigurationError(Exception):
    """R2 settings are absent or incomplete. Never carries the value of a secret."""


@dataclass(frozen=True)
class R2Settings:
    """Everything needed to reach the bucket, as data."""

    endpoint_url: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    region_name: str = R2_REGION_NAME
    signature_version: str = R2_SIGNATURE_VERSION

    def __repr__(self) -> str:  # a settings object routinely reaches a traceback
        return (
            f"<R2Settings bucket={self.bucket!r} "
            f"endpoint_url={self.endpoint_url!r} secret=redacted>"
        )

    @classmethod
    def from_env(cls) -> R2Settings:
        # TEST-ONLY (m-24955929): with `QUALIFY_OBJECT_STORE_DIR` every `R2ObjectStore`
        # is a local directory (`objects/local_dir.py`) and needs no credentials — and
        # none are read, so a test run can never reach the real bucket by mistake.
        from qualify_shared.objects.local_dir import local_store_dir  # noqa: PLC0415

        local = local_store_dir()
        if local:
            return cls(
                endpoint_url=f"local-dir://{local}",
                access_key_id="local",
                secret_access_key="local",
                bucket="local",
            )
        missing = [name for name in _REQUIRED_VARS if not os.environ.get(name)]
        if missing:
            raise R2ConfigurationError(f"missing R2 configuration: {', '.join(missing)}")
        return cls(
            endpoint_url=os.environ["QUALIFY_R2_ENDPOINT_URL"],
            access_key_id=os.environ["QUALIFY_R2_ACCESS_KEY_ID"],
            secret_access_key=os.environ["QUALIFY_R2_SECRET_ACCESS_KEY"],
            bucket=os.environ["QUALIFY_R2_BUCKET"],
        )

"""The sanctioned door to the object plane (ADR 28c).

`R2ObjectStore` is intentionally NOT re-exported here. Importing it pulls in the lazy boto3
factory module, and keeping it off the package surface makes the import that reaches the real
client visible at every call site (`from qualify_shared.objects.s3 import R2ObjectStore`)
rather than hidden behind a convenience alias.
"""

from qualify_shared.objects.config import R2ConfigurationError, R2Settings
from qualify_shared.objects.gate import (
    MAX_MEDIA_BYTES,
    ObjectGate,
    ObjectSizeExceeded,
    ObjectStore,
    UnsizedStream,
)
from qualify_shared.objects.keys import (
    TenantPrefixViolation,
    media_key,
    require_tenant_prefix,
    tenant_prefix,
)

__all__ = [
    "MAX_MEDIA_BYTES",
    "ObjectGate",
    "ObjectSizeExceeded",
    "ObjectStore",
    "R2ConfigurationError",
    "R2Settings",
    "TenantPrefixViolation",
    "UnsizedStream",
    "media_key",
    "require_tenant_prefix",
    "tenant_prefix",
]

"""The sanctioned door to the object plane (ADR 28c).

`R2ObjectStore` is intentionally NOT re-exported here. Importing it pulls in the lazy boto3
factory module, and keeping it off the package surface makes the import that reaches the real
client visible at every call site (`from qualify_shared.objects.s3 import R2ObjectStore`)
rather than hidden behind a convenience alias.
"""

from qualify_shared.objects.config import R2ConfigurationError, R2Settings
from qualify_shared.objects.gate import (
    MAX_MEDIA_BYTES,
    PURGEABLE_ROOTS,
    GalleryObject,
    ObjectGate,
    ObjectSizeExceeded,
    ObjectStore,
    PrefixDeletion,
    StoredObject,
    UnsizedStream,
)
from qualify_shared.objects.keys import (
    GALLERY_ROOT,
    TenantPrefixViolation,
    gallery_media_key,
    gallery_media_prefix,
    gallery_root,
    is_object_store_key,
    media_key,
    require_tenant_object,
    require_tenant_prefix,
    tenant_prefix,
    tenant_roots,
)

__all__ = [
    "GALLERY_ROOT",
    "MAX_MEDIA_BYTES",
    "PURGEABLE_ROOTS",
    "GalleryObject",
    "ObjectGate",
    "ObjectSizeExceeded",
    "ObjectStore",
    "PrefixDeletion",
    "R2ConfigurationError",
    "R2Settings",
    "StoredObject",
    "TenantPrefixViolation",
    "UnsizedStream",
    "gallery_media_key",
    "gallery_media_prefix",
    "gallery_root",
    "is_object_store_key",
    "media_key",
    "require_tenant_object",
    "require_tenant_prefix",
    "tenant_prefix",
    "tenant_roots",
]

"""Vendor adapters behind the ``GenerationProvider`` seam.

Business code imports :mod:`qualify_creative.providers`, never a vendor SDK; the
adapters here are the only modules allowed to touch one, and each imports its SDK
lazily inside the method that needs it.
"""

from qualify_creative.adapters.anthropic_copy import AnthropicCopyAdapter, CopyRefused
from qualify_creative.adapters.byteplus_ark import (
    ArkAPIError,
    ArkError,
    ArkTaskFailed,
    ArkTaskTimeout,
    SeedanceVideoAdapter,
    SeedreamImageAdapter,
)
from qualify_creative.adapters.byteplus_omnihuman import (
    OmniHumanError,
    OmniHumanTimeout,
    OmniHumanVideoAdapter,
)
from qualify_creative.adapters.byteplus_speech import (
    SeedSpeechClient,
    SeedSpeechError,
    SeedSpeechVoiceoverAdapter,
)

__all__ = [
    "AnthropicCopyAdapter",
    "ArkAPIError",
    "ArkError",
    "ArkTaskFailed",
    "ArkTaskTimeout",
    "CopyRefused",
    "OmniHumanError",
    "OmniHumanTimeout",
    "OmniHumanVideoAdapter",
    "SeedSpeechClient",
    "SeedSpeechError",
    "SeedSpeechVoiceoverAdapter",
    "SeedanceVideoAdapter",
    "SeedreamImageAdapter",
]

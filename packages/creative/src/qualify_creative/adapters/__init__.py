"""Vendor adapters behind the ``GenerationProvider`` seam.

Business code imports :mod:`qualify_creative.providers`, never a vendor SDK; the
adapters here are the only modules allowed to touch one, and each imports its SDK
lazily inside the method that needs it.
"""

from qualify_creative.adapters.anthropic_copy import AnthropicCopyAdapter, CopyRefused

__all__ = ["AnthropicCopyAdapter", "CopyRefused"]

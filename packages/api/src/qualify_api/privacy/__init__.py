"""What a tenant's text may carry that must not leave the tenant (m-24854323, OL2-7 of
docs/epica-prellenado-brand-kit-alta.md §7.2): pure functions, no I/O."""

from qualify_api.privacy.phones import (
    IDENTIFIER_KEYS,
    MASK_BODY,
    mask_phones,
    mask_phones_in,
    whatsapp_numbers,
)

__all__ = ["IDENTIFIER_KEYS", "MASK_BODY", "mask_phones", "mask_phones_in", "whatsapp_numbers"]

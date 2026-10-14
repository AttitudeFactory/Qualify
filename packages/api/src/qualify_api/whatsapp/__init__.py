"""WhatsApp Business Platform (Cloud API) module — WA-03 slice.

Plan: `docs/plan-modulo-whatsapp-cloud-api.md` §6. What exists after WA-03 is the
**receiving end only**: the webhook settings object. The HTTP pair lives in
`http/whatsapp_routes.py` and records every signature-valid delivery into the generic
Meta webhook intake (`qualify_api.webhooks`, QUA-147) — no WhatsApp-specific table,
queue or worker is needed for that. No Graph client (WA-06) and no handler in
`webhooks.processor` (WA-07) yet; the typed view that handler will consume is
`qualify_shared.social.wa_shapes`. WA-04 added the schema that handler writes to:
migration 0057 and its ORM mirrors in `whatsapp/models.py`.

Token discipline is inherited whole: the module never sees a WhatsApp access token
(there is none to see until WA-02/WA-05 store the system-user token through
`oauth_credentials`), and the only secret it reads is the app secret, for HMAC.
"""

from qualify_api.whatsapp.config import WhatsAppWebhookSettings
from qualify_api.whatsapp.models import (
    WhatsAppOutboxItem,
    WhatsAppPhoneNumber,
    WhatsAppThreadState,
)

__all__ = [
    "WhatsAppOutboxItem",
    "WhatsAppPhoneNumber",
    "WhatsAppThreadState",
    "WhatsAppWebhookSettings",
]

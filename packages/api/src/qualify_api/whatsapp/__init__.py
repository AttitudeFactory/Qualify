"""WhatsApp Business Platform (Cloud API) module — WA-03 slice.

Plan: `docs/plan-modulo-whatsapp-cloud-api.md` §6. What exists after WA-03 is the
**receiving end only**: a webhook settings object, the signature check and a sink
that logs identifier-only summaries. No tables (WA-04), no Graph client (WA-06),
no persistence (WA-07) yet — this slice exists so the production callback
`/api/whatsapp/webhook` can be registered in Meta's panel and the WhatsApp Business
Account fields subscribed before the rest lands.

Token discipline is inherited whole: the module never sees a WhatsApp access token
(there is none to see until WA-02/WA-05 store the system-user token through
`oauth_credentials`), and the only secret it reads is the app secret, for HMAC.
"""

from qualify_api.whatsapp.config import WhatsAppWebhookSettings
from qualify_api.whatsapp.sink import WhatsAppEventSink, log_only_sink

__all__ = ["WhatsAppEventSink", "WhatsAppWebhookSettings", "log_only_sink"]

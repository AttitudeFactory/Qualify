"""WhatsApp Business Platform (Cloud API) module — WA-03 slice.

Plan: `docs/plan-modulo-whatsapp-cloud-api.md` §6. What exists after WA-03 is the
**receiving end only**: the webhook settings object. The HTTP pair lives in
`http/whatsapp_routes.py` and records every signature-valid delivery into the generic
Meta webhook intake (`qualify_api.webhooks`, QUA-147) — no WhatsApp-specific table,
queue or worker is needed for that. WA-06 adds the **sending end**: `client.py`
(`WhatsAppClient` Protocol + `HttpWhatsAppClient`, doc-derived shapes, limits validated
before any request). WA-04 added the schema the inbound handler writes to: migration
0057 and its ORM mirrors in `whatsapp/models.py`. No handler in `webhooks.processor`
(WA-07) yet; the typed view that handler will consume is `qualify_shared.social.wa_shapes`.

Token discipline is inherited whole: the module never sees a WhatsApp access token, and
the only secret it reads is the app secret, for HMAC. The client receives an
`AuthenticatedClient` from `CredentialResolver.client_for(connection_id, scheme="Bearer")`.
The two exceptions hold the token in memory only: `connect.py` (WA-05, the administrative
connect command — reads the system-user token from the environment once, verifies it,
encrypts it into `oauth_credentials` and upserts `whatsapp_phone_numbers` via
`phone_numbers.py`) and the dev-only `smoke.py`.
"""

from qualify_api.whatsapp.client import (
    BusinessProfile,
    BusinessProfileUpdate,
    ButtonSpec,
    Command,
    ConversationalAutomation,
    HttpWhatsAppClient,
    ListRow,
    ListSection,
    MediaInfo,
    PhoneNumberInfo,
    QrCode,
    WhatsAppApiError,
    WhatsAppClient,
)
from qualify_api.whatsapp.config import WhatsAppWebhookSettings
from qualify_api.whatsapp.connect import ConnectOutcome, connect_whatsapp_number
from qualify_api.whatsapp.models import (
    WhatsAppMenu,
    WhatsAppMenuVersion,
    WhatsAppOutboxItem,
    WhatsAppPhoneNumber,
    WhatsAppThreadState,
)
from qualify_api.whatsapp.phone_numbers import (
    PhoneNumberUpsert,
    PostgresWhatsAppPhoneNumberRepository,
    WhatsAppPhoneNumberRepository,
)

__all__ = [
    "BusinessProfile",
    "BusinessProfileUpdate",
    "ButtonSpec",
    "Command",
    "ConnectOutcome",
    "ConversationalAutomation",
    "HttpWhatsAppClient",
    "ListRow",
    "ListSection",
    "MediaInfo",
    "PhoneNumberInfo",
    "PhoneNumberUpsert",
    "PostgresWhatsAppPhoneNumberRepository",
    "QrCode",
    "WhatsAppApiError",
    "WhatsAppClient",
    "WhatsAppMenu",
    "WhatsAppMenuVersion",
    "WhatsAppOutboxItem",
    "WhatsAppPhoneNumber",
    "WhatsAppPhoneNumberRepository",
    "WhatsAppThreadState",
    "WhatsAppWebhookSettings",
    "connect_whatsapp_number",
]

# Version 17.0

This changelog was updated with the following changes:

* September 19, 2023: Added [User Accounts entry](#user-accounts)
* December 19, 2023: Moved Offline Conversions API information from Marketing API to Graph API
* February 6, 2024: Added affected endpoints for [Ad Strategies](#campaigns)

## Graph API

**Released** May 23, 2023 | **Available until** September 12, 2025 | [Blog Post](/blog/post/2023/05/23/introducing-facebook-graph-and-marketing-api-v17/)

### Instant Articles

As of April 20, 2023, the [Instant Articles API](/docs/instant-articles) no longer returns data. All Instant Articles API endpoints are not available on v17 or later and will be removed for all versions on August 21, 2023.

### Offline Conversions API

#### Deprecation of Offline Conversions API

*Applies to v17.0+.*

Starting with Graph API v17.0, the Offline Conversions API will no longer support offline events. Graph API v16.0 is the last version that supports offline events. We anticipate that the Offline Conversions API will be discontinued in the third quarter of 2024.

In February 2023, we announced that the Conversions API now fully supports offline events. We recommend that advertisers use the Conversions API for new integrations. We recommend that advertisers with Offline Conversions API integrations [convert their integration into a Conversions API integration](/docs/marketing-api/conversions-api/offline-events) before the third quarter of 2024 and not update their Offline Conversions API until they have successfully done so. Learn more about [the Conversions API](/docs/marketing-api/conversions-api).

The following endpoint is affected:

* [`POST /{offline_event_set_id}/events`](/docs/graph-api/reference/offline-conversion-data-set/events)

### ThreatExchange

The [`/malware_analyses` endpoint](/docs/threat-exchange/reference/apis/threat-indicator/) is deprecated. It is not available on v17 or later and will be removed for all versions on August 21, 2023.

### User Accounts

**This entry was added on September 19, 2023.**

*Applies to v17.0 and later versions. Will apply to all versions on September 15, 2023 (**UPDATE: No longer applies to all versions. See [September 15, 2023 out-of-cycle change](/docs/graph-api/changelog/non-versioned-changes/nvc-2023#september-15--2023).**)*

The `GET /{user-id}/accounts` (aka `GET /me/accounts`) endpoint no longer returns Facebook pages that have been linked to a Meta business account, unless the app user has granted the business\_management permission to the app and has a role on the linked business account.

### WhatsApp

See the [WhatsApp Business Platform changelog](/docs/whatsapp/business-platform/changelog#may-23--2023).

## Marketing API

**Released** May 23, 2023 | **Available until** May 14, 2024 | [Blog Post](/blog/post/2023/05/23/introducing-facebook-graph-and-marketing-api-v17/)

Marketing API [version auto-upgrade](/docs/marketing-api/versions#version-auto-upgrade) will release on May 14, 2024.

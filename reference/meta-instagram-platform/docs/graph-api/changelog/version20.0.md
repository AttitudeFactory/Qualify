# Version 20.0

## Graph API

**Released** May 21, 2024 | **Available until** TBD | [Blog Post](/blog/post/2024/05/21/introducing-facebook-graph-and-marketing-api-v20/)

### Comments

*Applies to v20.0. Applies to all versions August 19, 2024.*

Changed the `permalink_url` field on the [Comment](/docs/graph-api/reference/comment) node. This field will not be returned in API responses for comments on posts on pages if the calling app has **only** the [Page Public Content Access](/docs/features-reference/page-public-content-access) feature.

### Error Codes

*Applies to v20.0+.*

The API will now return error code `200` instead of error code `2` when the calling app's user does not have permission to access a given field on a given object.

### Instagram Graph API

#### Instagram User Insights

*Applies to v20.0+. Will apply to all versions on August 19, 2024.*

The `last_14_days`, `last_30_days`, `last_90_days` and `prev_month` timeframes will no longer be supported for the `reached_audience_demographics` and `engaged_audience_demographics` metrics.

The following endpoints and metrics are affected:

* [`GET /{ig-user-id}/insights`](/docs/instagram-api/reference/ig-user/insights)
  + `engaged_audience_demographics`
  + `reached_audience_demographics`

### Messenger Platform

The Booking button is no longer supported in Messenger API calls. This change does not affect other templates and buttons, and businesses can still manage bookings using Meta Business Suite. We recommend reviewing your current integrations and adjusting your applications as necessary to ensure a smooth transition for your users.

### WhatsApp Flows

See [WhatsApp Flows changelog](/docs/whatsapp/flows/changelogs).

## Marketing API

**Released** May 21, 2024 | **Available until** May 6, 2025 | [Blog Post](/blog/post/2024/05/21/introducing-facebook-graph-and-marketing-api-v20/)

### Auction Ads

#### Campaign Optimization of Impressions

*Applies to v20.0+. Will apply to all versions August 19, 2024.*

The `optimization_goal` parameter will no longer accept the impressions value in combination with:

* The legacy `POST_ENGAGEMENT` objective
* The `ON_POST` destination\_type

**Note:** Optimizing for reach is still available.

The following endpoints are affected:

* [`POST /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-account/adsets)

#### Frequency Controls

*Applies to v20.0+. Will apply to all versions August 19, 2024.*

The `frequency_control_specs` parameter should no longer be sent in an API call if the `optimization_goal` is set to Ad Recall Lift, Link Click Optimization, Post Engagement, or 2-second Video Views. Any campaigns of this type that are still running will be disabled beginning August 19, 2024.

Writes to this field are only available in ad sets where `REACH` and `THRUPLAY` are the performance goal.

The following endpoints are affected:

* [`POST /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-account/adsets)

### Offline Conversions API

#### Deprecation of Remaining Endpoints

*Applies to v20.0+.*

The Offline Conversions API will be discontinued in May 2025. It was previously due to be deprecated in the third quarter of 2024. As we announced in [the v17.0 changelog](/docs/graph-api/changelog/version17.0#offline-conversions-api), the Offline Conversions API no longer supports offline events. Graph API v16.0 is the last version that supports offline events. The Offline Conversions API will be discontinued when v16.0 expires in May 2025.

Between now and May 2025, we will be deprecating the remaining Offline Conversions API endpoints on Marketing API v20.0.

The following endpoints are affected:

* [`POST/GET/DELETE /{offline_event_set_id}`](/docs/graph-api/reference/offline-conversion-data-set/events)
* [`POST/GET /{offline_event_set_id}/uploads`](/docs/graph-api/reference/offline-conversion-data-set/uploads/)
* [`POST /{offline_event_set_id}/validate`](/docs/graph-api/reference/offline-conversion-data-set/validate/)
* `POST /{offline_event_set_id}/ad_account`
* [`GET /{offline_event_set_id}/stats`](/docs/graph-api/reference/offline-conversion-data-set/stats/)
* [`GET /{offline_event_set_id}/shared_agencies`](/docs/graph-api/reference/offline-conversion-data-set/shared_agencies/)
* [`POST/GET /{offline_event_set_id}/agencies`](/docs/graph-api/reference/offline-conversion-data-set/agencies/)
* [`GET /{offline_event_set_id}/adaccounts`](/docs/graph-api/reference/offline-conversion-data-set/adaccounts/)
* [`GET /{offline_event_set_id}/customconversions`](/docs/graph-api/reference/offline-conversion-data-set/customconversions/)
* [`GET /{offline_event_set_id}/audiences`](/docs/graph-api/reference/offline-conversion-data-set/audiences/)
* [`GET /{offline_event_set_id}/shared_accounts`](/docs/graph-api/reference/offline-conversion-data-set/shared_accounts/)
* [`GET /{ad_account_id}/offline_conversion_data_sets`](/docs/marketing-api/reference/ad-account/adsets)
* [`POST/GET /{business_id}/offline_conversion_data_sets`](/docs/marketing-api/reference/business/offline_conversion_data_sets/)
* `POST/GET/DELETE /{business_asset_group_id}/contained_offline_conversion_data_sets`

In February 2023, we announced that the Conversions API now fully supports offline events. We recommend that advertisers use the Conversions API for new integrations. We recommend that advertisers with Offline Conversions API integrations [convert their integration into a Conversions API integration](/docs/marketing-api/conversions-api/offline-events) before May 2025 and not update their Offline Conversions API until they have successfully done so. Learn more about [the Conversions API](/docs/marketing-api/conversions-api).

### Messaging Ads

#### Sponsored Messages

*Applies to v20.0+. Will apply to all versions August 19, 2024.*

Creation of the sponsored messages ad type will no longer be available. This change will not affect other messaging ads ad types.

The following endpoints are affected:

* [`POST /{ad-account-id}/adcreatives`](/docs/marketing-api/reference/ad-account/adcreatives)

# Version 19.0

## Graph API

**Released** January 23, 2024 | **Available until** May 21, 2026 | [Blog Post](/blog/post/2024/01/23/introducing-facebook-graph-and-marketing-api-v19/)

### Groups API

*Applies to v19.0. Will apply to all versions April 22, 2024.*

Deprecated the following [Groups API](/docs/groups-api/reference) permissions and features:

* [publish\_to\_groups](/docs/permissions/#p)
* [groups\_access\_member\_info](/docs/permissions/#g)
* [Groups API](/docs/features-reference/groups-api)

You can verify if a given Groups API endpoint requires one of these permissions or features by making a version 19 request on the endpoint (`https://graph.facebook.com/v19.0/...`).

In addition, we have deprecated the ability for group admins to install apps on the group, even if they have an admin or developer role on the app.

These permissions, features, and abilities will be removed April 22, 2024.

### WhatsApp Flows

See [WhatsApp Flows changelog](/docs/whatsapp/flows/changelogs).

## Marketing API

**Released** January 23, 2024 | **Available until** February 4, 2025 | [Blog Post](/blog/post/2024/01/23/introducing-facebook-graph-and-marketing-api-v19/)

### Insights

#### Ads Insights

*Applies to v19.0+.*

* The `age_targeting`, `gender_targeting`, `labels`, and `location` insights metrics will no longer be available.
* The `estimated_ad_recall_rate_lower_bound`, `estimated_ad_recall_rate_upper_bound`, `estimated_ad_recallers_lower_bound`, and `estimated_ad_recallers_upper_bound` insights metrics will no longer be available.

The following endpoints are affected:

* [`GET /{ad-set-id}/insights`](/docs/marketing-api/reference/ad-campaign/insights)
* [`GET /{ad-account-id}/insights`](/docs/marketing-api/reference/ad-account/insights)
* [`GET /{ad-id}/insights`](/docs/marketing-api/reference/adgroup/insights)
* [`GET /{campaign-id}/insights`](/docs/marketing-api/reference/ad-campaign-group/insights)
* [`POST /{ad-set-id}/insights`](/docs/marketing-api/reference/ads-insights)
* [`POST /{ad-account-id}/insights`](/docs/marketing-api/reference/ad-account/insights)
* [`POST /{ad-id}/insights`](/docs/marketing-api/reference/adgroup/insights)
* [`POST /{campaign-id}/insights`](/docs/marketing-api/reference/ad-campaign-group/insights)

### Objectives

#### Ad Copies

*Applies to v19.0+.*

When creating a copy of an ad you must only use Outcome-Driven Ad Experience objectives. Attempting to use legacy objectives will result in an error.

The following endpoints are affected:

* [`POST /{adgroup-id}/copies`](/docs/marketing-api/reference/adgroup/copies)
* [`POST /{ad-campaign-id}/copies`](/docs/marketing-api/reference/ad-campaign/copies)
* [`POST /{ad-campaign-group-id}/copies`](/docs/marketing-api/reference/ad-campaign-group/copies)

### Targeting

#### Target Expansion

*Applies to v19.0+. Will apply to all versions on April 22, 2024.*

* The `targeting_optimization` field will not be accepted for campaigns that are optimized for link clicks or landing page views. This also applies to previous optimizations that were included in Advantage Detailed Targeting with no option to opt-out including conversions, value, app installs, app events and conversations.
* For all optimizations that are opted into Advantage Detailed Targeting with no option to opt-out we will automatically set the `targeting_as_signal` field to either 1 or 3 based on the set of objectives and optimizations.
* The `targeting_as_signal` field should be either null or 0 for campaigns that are optimized for impressions, video views, reach, engagement, ad recall lift or lead, otherwise an error will be received.

The following endpoints are affected:

* [`POST /act_{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-account/adsets/)
* [`POST /{adset-id}`](/docs/marketing-api/reference/ad-campaign)
* [`GET /{adset-id}/delivery_estimate`](/docs/marketing-api/reference/ad-campaign/delivery_estimate)
* [`GET /act_{ad-account-id}/delivery_estimate`](/docs/marketing-api/reference/ad-account/delivery_estimate)

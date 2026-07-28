# Version 23.0

## Graph API

**Released** May 29, 2025 | **Available until** TBD | [Blog post](/blog/post/2025/05/29/introducing-graph-api-v23-and-marketing-api-v23/)

### WhatsApp Business Platform

* Added a new Cloud API error code for help diagnosing messaging errors. See [WhatsApp Business platform changelog](/docs/whatsapp/business-platform/changelog).
* Added four new Marketing Messages Lite API error codes for help diagnosing messaging errors. See [Marketing Messages Lite API changelog](/docs/whatsapp/marketing-messages-lite-api/changelog).

## Marketing API

**Released** May 29, 2025 | **Available until** June 9, 2026 | [Blog post](/blog/post/2025/05/29/introducing-graph-api-v23-and-marketing-api-v23/)

### Ad Campaigns

#### Advantage+ Shopping Campaigns and Advantage+ App Campaigns

*Applies to v23.0.+ Will apply to all versions with the release of v25.0.*

The `advantage_state` field in `advantage_state_info` is a read-only field that indicates if a campaign has reached an optimal level of automation. Beginning with v25.0, the `smart_promotion_type` field will no longer be available for creating ad campaigns.

The following endpoints are affected:

* [`GET /{ad-campaign-id}`](/docs/marketing-api/reference/ad-campaign-group)
* [`GET /{ad-account-id}/campaigns`](/docs/marketing-api/reference/ad-account/campaigns)

### Audiences

#### Advanced Targeting

*Applies to v23.0+.*

Age range and gender settings can now be used as suggestions in ad sets using individual\_setting's age and gender parameters inside targeting\_automation.

**Note:** When using suggestions, your ads will reach people outside of the setting when it's likely to improve performance of the ads.

The following endpoints are affected:

* [`GET /{ad-account-id}/delivery_estimate`](/docs/marketing-api/reference/ad-account/delivery_estimate)
* [`POST /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-account/adsets)
* [`POST /{adset-id}`](/docs/marketing-api/reference/ad-campaign)
* [`POST /{adset-id}/copies`](/docs/marketing-api/reference/ad-campaign/copies)

#### Advantage+ Audience

*Applies to v23.0+.*

Ad sets are now opted-in to Advantage+ audience by default if you're using the default or relaxed setup. You can opt-out in the audience settings when creating or updating an ad set.

This behavior applies only when creating a new ad set; updating an existing ad set will not exhibit this behavior on any version.

The following endpoints are affected:

* [`GET /{ad-account-id}/delivery_estimate`](/docs/marketing-api/reference/ad-account/delivery_estimate)
* [`POST /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-account/adsets)
* [`POST /{adset-id}`](/docs/marketing-api/reference/ad-campaign)
* [`POST /{adset-id}/copies`](/docs/marketing-api/reference/ad-campaign/copies)

### Bidding

#### Reservation

*Applies to v23.0+.*

Beginning with v23.0, the `instagram_destination_id` field will return the `ig_user_id` rather than the `instagram_actor_id`. The `instagram_actor_id` is also no longer supported in the `destination_ids` parameter; update your API calls to use the `ig_user_id` instead.

The following endpoints are affected:

* [`GET /{rf-prediction-id}`](/docs/marketing-api/reference/reach-frequency-prediction)
* [`GET /{ad-account-id}/reachfrequencypredictions`](/docs/marketing-api/reference/ad-account/reachfrequencypredictions)
* [`POST /{ad-account-id}/reachfrequencypredictions`](/docs/marketing-api/reference/ad-account/reachfrequencypredictions)

### Product Item

#### Videos

*Applies to v23.0+.*

The `videos` field has been added to allow for querying of the properties of videos associated with product items.

The following endpoints are affected:

* [`GET /{product-item-id}`](/docs/marketing-api/reference/product-item/)

### Special Ad Catagories

#### Ad Sets for Special Ad Category Campaigns

*Applies to v23.0. Will Apply to all versions August 27, 2025.*

The `is_sac_cfca_terms_certified` field should no longer be added to an ad set as the rollout of these requirements will not proceed.

The following endpoints are affected:

* [`POST /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-campaign)
* [`POST /{ad_set_id}`](/docs/marketing-api/reference/ad-campaign)

#### Custom Audiences

*Applies to v23.0. Will Apply to all versions August 27, 2025.*

The `is_eligible_for_sac_campaigns` field should no longer be added to an ad set as the rollout of these requirements will not proceed.

The following endpoints are affected:

* [`GET /{custom_audience_id}`](/docs/marketing-api/reference/custom-audience#Reading)

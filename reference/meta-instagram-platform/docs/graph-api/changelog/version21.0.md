# Version 21.0

## Graph API

**Released** October 2, 2024 | **Available until** TBD | [Blog post](https://developers.facebook.com/blog/post/2024/10/02/introducing-graph-api-v21-and-marketing-api-v21/)

### Instagram Platform

#### Media Insights

*Applies to v21.0+. Will apply to all versions on January 8, 2025.*

The video media metric `video_views` will no longer be supported.

The following endpoints and metrics are affected:

* [`GET /{ig-media-id}/insights`](/docs/instagram-platform/instagram-graph-api/reference/ig-media/insights)
  + `video_views`

#### User Insights

*Applies to v21.0+. Will apply to all versions on January 8, 2025.*

The `email_contacts`, `get_direction_clicks`, `profile_views`, `text_message_clicks`, `website_clicks`, and `phone_call_clicks` time series metrics will no longer be supported.

The following endpoints and metrics are affected:

* [`GET /{ig-user-id}/insights`](/docs/instagram-platform/instagram-graph-api/reference/ig-user/insights)
  + `email_contacts`
  + `get_direction_clicks`
  + `profile_views`
  + `text_message_clicks`
  + `website_clicks`
  + `phone_call_clicks`

### Messaging Events API

* Messaging Events API will be deprecated in September 2025. To prepare for this deprecation, Messaging Events API will no longer be supported in any future releases of Graph API, starting with version 21.0, as of September 24, 2024.
* Partners who choose not to update to the latest Graph API will still be able to access Messaging Events API by calling Graph API version 20.0 or prior until the official product deprecation in September 2025.
* For Partners who do not update to the latest Graph API, we recommend they use the Conversions API for new integrations. Learn more about the [Conversions API](https://developers.facebook.com/docs/marketing-api/conversions-api/business-messaging).

The following endpoints are affected:

* `POST /{app_id}/page_activities`

### WhatsApp

See the WhatsApp Business Platform [changelog](/docs/whatsapp/business-platform/changelog).

## Marketing API

**Released** October 2, 2024 | **Available until** TBD | [Blog post](https://developers.facebook.com/blog/post/2024/10/02/introducing-graph-api-v21-and-marketing-api-v21/)

### Objectives

#### Outcome-Driven Ad Experiences

*Applies to v21.0+.*

Beginning with v21.0, you will no longer be able to create new ad sets or ads with non-Outcome-Driven Ad Experience (ODAX) objectives. Existing ad campaigns using older objectives can continue to run for now, but we encourage you to transition all your campaigns to the ODAX objectives. See the [Simplifying campaign objectives with Outcome-Driven Ad Experiences](https://developers.facebook.com/blog/post/2021/12/21/simplifying-campaign-objectives-outcome-driven-ad-experiences) blog entry and the [Outcome-Driven Ad Experiences documentation](/docs/marketing-api/reference/ad-campaign/#odax) for more information.

The following endpoints are affected:

* [`POST /{ad_account_id}/campaigns`](/docs/marketing-api/reference/ad-account/campaigns)
* [`POST /{ad_account_id}/ads`](/docs/marketing-api/reference/ad-account/ads)
* [`POST /{ad_account_id}/adsets`](/docs/marketing-api/reference/ad-campaign)
* [`POST /{campaign_id}`](/docs/marketing-api/reference/ad-campaign-group)
* [`POST /{ad_group_id}`](/docs/marketing-api/reference/ad-group)

### Standard Enhancements

#### Image Expansion

*Applies to v21.0+.*

For single media ads, the [Image Expansion feature](/docs/marketing-api/creative/generative-ai-features#image-expansion) will be included as part of Standard Enhancements. Therefore, if creating an ad or an ad creative opted-in to Image Expansion, please refer to this [link](/docs/marketing-api/advantage-catalog-ads/standard-enhancements/) for instructions to set `standard_enhancements` as a field inside the `creative_features_spec`.

The following endpoints are affected:

* [`POST /{ad_account_id}/adcreatives`](/docs/marketing-api/reference/ad-account/adcreatives)
* [`POST /{ad_account_id}/ads`](/docs/marketing-api/reference/ad-account/ads)
* [`GET /{ad_id}/previews`](/docs/marketing-api/reference/adgroup/previews)
* [`GET /{ad_account_id}/generatepreviews`](/docs/marketing-api/generatepreview)

### Version 22 Upcoming Change

### Product Catalog — Enforcing Country Override Specific Fields

*Applies to v22.0*

This change applies to advertisers using country and language feeds to localize their product data. It standardizes which fields should be provided in a country feed versus a language feed (or a country and language feed via API) to help advertisers set up their product data in the most efficient way. Price, sale price, unit price, base price, status (visibility), and availability must now only be provided in a country feed. This helps ensure customers see the correct localized product data. If your language feed currently contains the price, sale\_price, base\_price, status or availability fields, move them to your country feed before the Graph API v22.0 release in Q1 2025 to ensure that the localized data continues to be uploaded to your products past this date.

**Endpoint:** POST /{product-catalog-id}/localized\_items\_batch — https://developers.facebook.com/docs/marketing-api/reference/product-catalog/localized\_items\_batch/

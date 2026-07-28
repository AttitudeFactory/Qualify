# Version 22.0

## Graph API

**Released** January 21, 2025 | **Available until** TBD | [Blog post](/blog/post/2025/01/21/introducing-graph-api-v22-and-marketing-api-v22/)

### Instagram Platform

#### Insights APIs

*Applies to all versions.*

[Insights APIs for both media and user objects](https://developers.facebook.com/docs/instagram-platform/insights) are now available for apps that have implemented Instagram API with Instagram Login.

#### Insights metrics

Introducing the following metrics field for media and user insights:

* `views`

##### Metric Deprecations

*Applies to v22.0+. Will apply to all versions April 21, 2025.*

* `clips_replays_count` on media insights
* `ig_reels_aggregated_all_plays_count` on media insights
* `impressions` on media and user insights
* `plays` on media insights

**Note:** API requests with the impressions metric will continue to return data for media created on or before July 1, 2024 for v21.0 and older. API requests made after April 21, 2025 for media created on or after July 2, 2024 will return an error.

#### v1.0 Endpoint Deprecations

*Applies to v22.0+. Will apply to all versions ~~April 21, 2025~~ May 20, 2025.*


The [Instagram v1.0 API](https://developers.facebook.com/docs/marketing-api/reference) is deprecated.

The following endpoints are affected:

* `GET /{instagram-user-id}`
* `GET /{instagram-user-id}/agencies`
* `GET /{instagram-user-id}/upcoming-events`
* `GET /{instagram-user-id}/authorized-adaccounts`
* `POST /{instagram-user-id}/upcoming-events`
* `POST /{instagram-user-id}/authorized-adaccounts`
* `GET /{instagram-media-id}`
* `GET /{instagram-media-id}/comments`
* `GET /{instagram-carousel-id}`
* `GET /{instagram-carousel-id}/comments`
* `GET /{instagram-comment-id}`
* `GET /{instagram-comment-id}/replies`
* `POST /{instagram-media-id}/comments`
* `POST /{instagram-carousel-id}/comments`
* `POST /{instagram-comment-id}/replies`
* `POST /{instagram-comment-id}`
* `DELETE /{instagram-comment-id}`
* `GET /{page-id}/instagram-accounts`
* `GET /{page-id}/page-backed-instagram-accounts`
* `GET /{business-id}/owned-instagram-accounts`
* `GET /{business-id}/instagram-accounts`
* `GET /{business-asset-group-id}/contained-instagram-accounts`
* `GET /{fb-business-user-id}/assigned-instagram-accounts`
* `GET /{fb-user-id}/assigned-instagram-accounts`
* `GET /{fb-system-user-id}/assigned-instagram-accounts`
* `GET /{ad account id}/instagram-accounts`
* `GET /{ad account id}/connected-instagram-accounts-with-iabp`
* `POST /{page-id}/page-backed-instagram-accounts`
* `DELETE /{business-id}/instagram-accounts`

Please migrate your API calls to the
[Instagram Platform endpoints.](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login)

### Pages

*Applies to v22.0+.*

Page recommendations have been deprecated for v22.0 and future versions. Attempting to read a recommendation, or get recommendations on a page, will return error code `12`, and Page ratings webhooks will no longer be sent.

Affected endoints:

* [`GET /<PAGE_ID>/ratings`](/docs/graph-api/reference/page/ratings/)
* [`GET /<RECOMMENDATION_ID>`](/docs/graph-api/reference/recommendation/)

Affected webhooks:

* [Page ratings](/docs/graph-api/webhooks/reference/page/#ratings)

## Marketing API

**Released** January 21, 2025 | **Available until** February 19, 2026 | [Blog post](/blog/post/2025/01/21/introducing-graph-api-v22-and-marketing-api-v22/)

### Ad Creatives

*Applies to v22.0+. Will apply to all versions September 9, 2025.*

#### Field Deprecations

The `instagram_actor_id` field for the following endpoints is deprecated:

* [`POST /{ad-account-id}/adcreatives`](/docs/marketing-api/reference/adcreative)
* [`POST /{ad-account-id}/ads`](/docs/marketing-api/reference/ad-account/ads/)
* [`POST /{ads-id}`](/docs/marketing-api/reference/adgroup)
* [`POST /{ad-account-id}/asyncadrequestsets`](/docs/marketing-api/reference/ad-account/asyncadrequestsets)
* [`GET /{ad-account_id}/generatepreviews`](/docs/marketing-api/reference/ad-account/generatepreviews)
* [`GET /generatepreviews`](/docs/marketing-api/reference/generatepreviews)
* [`GET /adcreative`](/docs/marketing-api/reference/ad-creative)
* [`GET /adcreative/object_story_spec`](/docs/marketing-api/reference/ad-creative-object-story-spec)

Please migrate your API calls to use the new `instagram_user_id` field.

The `effective_instagram_story_id` field has been deprecated for the [`GET /adcreative` endpoint](/docs/marketing-api/reference/ad-creative#fields). Use the `effective_instagram_media_id` field instead.

The `instagram_story_id` field has been deprecated for the [`GET /adcreative` endpoint](/docs/marketing-api/reference/ad-creative#fields). Use the `source_instagram_media_id` field instead.

### Advantage+ Creative

#### Standard Enhancements

*Applies to v22.0+.*

[Opting ads in to](/docs/marketing-api/advantage-catalog-ads/standard-enhancements) and [previewing ads](/docs/marketing-api/advantage-catalog-ads/creative-preview) using the `STANDARD_ENHANCEMENTS` bundle is no longer supported.

The following endpoints are affected:

* [`POST /{ad-account-id}/adcreatives`](/docs/marketing-api/reference/ad-account/adcreatives)
* [`POST /{ad-account-id}/ads`](/docs/marketing-api/reference/ad-account/ads)
* [`GET /{ad-id}/previews`](/docs/marketing-api/reference/adgroup/previews)
* [`GET /{ad-account-id}/generatepreviews`](/docs/marketing-api/generatepreview)

### Asset Feed Spec

#### Segment Asset Customization

*Applies to v22.0+.*

[Segment Asset Customization](/docs/marketing-api/dynamic-creative/segment-asset-customization) is no longer supported.

### Audiences

#### Detailed Targeting - Employer Exclusions

*Applies to all versions.*

An employer exclusion can now be created at the ad account level, which will be applied to all active campaigns.

The following endpoints are affected:

* [`POST /{ad-account-id}/account_controls`](/docs/marketing-api/reference/ad-account/account_controls)
* [`GET /{ad-account-id}/account_controls`](/docs/marketing-api/reference/ad-account/account_controls)

#### Detailed Targeting - Exclusions

*Applies to v22.0+. Will apply to all versions April 21, 2025.*

* When creating or updating an ad set, an error message will be shown when adding any new detailed targeting exclusions that are not within audience control exclusions at the account level.
* When duplicating an ad set, detailed targeting exclusions (except audience control exclusions at the account level) will be removed in the new campaign.
* When trying to get a delivery estimate, only employer exclusions will be allowed for detailed targeting.

As a result of this change, custom audiences will be deprecated within the `exclusions` field. You can still continue using custom audience exclusions by using the `excluded_custom_audiences` field instead. For more details see [Advanced Targeting: Custom Audiences](/docs/marketing-api/audiences/reference/advanced-targeting/#custom_audiences).

The following endpoints are affected:

* [`POST /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-account/adsets)
* [`POST /{adset-id}`](/docs/marketing-api/reference/ad-campaign)
* [`POST /{adset-id}/copies`](/docs/marketing-api/reference/ad-campaign/copies)
* [`GET /{ad-account-id}/delivery_estimate`](/docs/marketing-api/reference/ad-account/delivery_estimate)

#### Reach People Interested in Selected Cities and Regions

*Applies to v22.0+.*

Expands location targeting beyond an ad campaign's target cities or regions to deliver ads to people who have shown interest in a location.

The following endpoints are affected:

* [`POST /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-account/adsets)
* [`POST /{adset-id}`](/docs/marketing-api/reference/ad-campaign)
* [`GET /{adset-id}`](/docs/marketing-api/reference/ad-campaign)
* [`GET /{ad-account-id}/delivery_estimate`](/docs/marketing-api/reference/ad-account/delivery_estimate)

### Commerce Platform

#### Promotions API – field deprecation

*Applies to v22.0+.*

The `promotions` field has been deprecated and replaced by the `promotion_details` field. Please discontinue using the `promotions` field, as it does not contain complete information. Please migrate your API calls to the new `promotion_details` field.

The following endpoint is affected:

* [`GET /{commerce-order-id}/promotion_details`](/docs/graph-api/reference/commerce-order/promotion_details/)

### Instagram Endpoints

*Applies to v22.0+. Will apply to all versions April 21, 2025.*

The Instagram endpoints supported by the Marketing API have been deprecated.

The following endpoints are affected:

* [`DELETE /{instagram-comment-id}`](/docs/marketing-api/reference/instagram-comment)
* [`GET /{instagram-carousel-id}`](/docs/marketing-api/reference/instagram-carousel)
* [`GET /{instagram-carousel-id}/comments`](/docs/marketing-api/reference/instagram-carousel/comments)
* [`GET /{instagram-comment-id}`](/docs/marketing-api/reference/instagram-comment)
* [`GET /{instagram-comment-id}/replies`](/docs/marketing-api/reference/instagram-comment/replies)
* [`GET /{instagram-media-id}`](/docs/marketing-api/reference/instagram-media)
* [`GET /{instagram-media-id}/comments`](/docs/marketing-api/reference/instagram-media/comments)
* [`GET /{instagram-user-id}`](/docs/marketing-api/reference/instagram-user)
* [`GET /{instagram-user-id}/agencies`](/docs/marketing-api/reference/instagram-user/agencies)
* [`GET /{instagram-user-id}/ar_effects`](https://developers.facebook.com/docs/marketing-api/reference/instagram-user/ar_effects/)
* [`GET /{instagram-user-id}/authorized_adaccounts`](/docs/marketing-api/reference/instagram-user/authorized_adaccounts)
* [`GET /{instagram-user-id}/upcoming_events`](/docs/marketing-api/reference/instagram-user/upcoming_events)
* [`POST /{instagram-user-id}/authorized_adaccounts`](/docs/marketing-api/reference/instagram-user/authorized_adaccounts)
* [`POST /{instagram-carousel-id}/comments`](/docs/marketing-api/reference/instagram-carousel/comments)
* [`POST /{instagram-comment-id}`](/docs/marketing-api/reference/instagram-comment)
* [`POST /{instagram-comment-id}/replies`](/docs/marketing-api/reference/instagram-comment/replies)
* [`POST /{instagram-media-id}`](/docs/marketing-api/reference/instagram-media)
* [`POST /{instagram-user-id}/upcoming_events`](/docs/marketing-api/reference/instagram-user/upcoming_events)

Please migrate your API calls to use the following [Instagram Platform endpoints](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login):

* [`IG User`](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user)
* [`IG Media`](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media)
* [`IG Media Children`](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/children)
* [`IG Comment`](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-comment)
* [`IG Comment Replies`](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-comment/replies)

### Special Ad Categories

We are providing an update regarding the previously considered restrictions on customer list custom audiences (CLCAs) for advertisers offering housing, employment, and financial products and services in or targeting audiences in the United States.

The rollout of these previously announced restrictions will not proceed.

Certain customer list custom audiences will become ineligible for usage in ad sets of housing, employment, and financial products and services, including credit, campaigns beginning March 2025. Learn more about the update [here](https://www.facebook.com/business/help/1452187872132363) and whether the restrictions apply to you.

#### Ad Sets for Special Ad Category Campaigns

*Applies to v22.0+. Will apply to all versions March 2025.*

Starting with v22.0, you will be unable to create or update ad sets if their targeting options contain one or more ineligible customer list custom audiences. You will need to either [certify](https://www.facebook.com/legal/customer-list-custom-audience-certification) if eligible or remove any such audiences to successfully create or update the ad set. Starting early April 2025, existing campaigns/ad sets using customer list custom audiences which do not follow the requirements may be paused. If this happens, you will see errors in Ads Manager and the Marketing API with instructions.

The `is_sac_cfca_terms_certified` field will be added to the ad set API. You will be required to use this field to certify that any customer list custom audiences being used in an ad set of a housing, employment, and financial products and services, including credit, campaign comply with [Meta’s CLCA certification](https://www.facebook.com/legal/customer-list-custom-audience-certification).

This change affects the following endpoints when creating or updating ad sets:

* [`POST /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-account/adsets)
* [`POST /{ad-set-id}`](/docs/marketing-api/reference/ad-campaign)

#### Custom Audiences

*Applies to all versions.*

Starting on January 6, 2025, you can use the new `is_eligible_for_sac_campaigns` field to identify whether a custom audience can be used in ad sets of Special Ad Category campaigns. You must provide the intended `special_ad_categories` and `special_ad_category_countries` of the Special Ad Category campaign using the audience, as well as the `ad_account_id` which will use the audience to create or edit the ad set.

This change affects the following endpoints:

* [`GET /{custom-audience-id}`](/docs/marketing-api/reference/custom-audience)

See [Special Ad Categories](https://developers.facebook.com/docs/marketing-api/audiences/special-ad-category) for more information about these changes.

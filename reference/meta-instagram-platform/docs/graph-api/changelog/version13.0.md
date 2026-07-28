# Version 13.0

## Graph API

**Released** February 8, 2022 | **Available until** TBD | [Blog post](/blog/post/2022/02/08/introducing-facebook-graph-marketing-api-v13/)

### Instagram Graph API

#### IG Media

Version 13 will be the last version to allow [`video_title`](/docs/instagram-api/reference/ig-media#fields) field requests on [IG Media](/docs/instagram-api/reference/ig-media) without returning an error. As a reminder, the current API behavior outlined in our [October 5th, 2021](https://developers.facebook.com/blog/post/2021/10/07/instagram-video-updates-developer-community/) blog post is as follows:

* [`media_product_type`]((/docs/instagram-api/reference/ig-media#fields)) field returns `FEED` for all versions
* [`video_title`](/docs/instagram-api/reference/ig-media#fields) field is omitted from responses for all versions
* Instagram Webhooks [`comments`](/docs/instagram-api/guides/webhooks#instagram-fields) and [`mentions`](/docs/instagram-api/guides/webhooks#instagram-fields) fields are supported for all versions

The behavior above applies to all IG Media, including IG Media created with the Instagram TV app, regardless of creation date.

#### User Insights

*Applies to v13.0+*

The following [IG User Insights](/docs/instagram-api/reference/ig-user/insights) metrics no longer support [`since`](/docs/instagram-api/reference/ig-user/insights#query-string-parameters) and [`until`](/docs/instagram-api/reference/ig-user/insights#query-string-parameters) parameters, and responses will not include the [`end_time`](/docs/instagram-api/reference/ig-user/insights#sample-response) JSON property.

* [`audience_city`](/docs/instagram-api/reference/ig-user/insights#metrics-and-periods)
* [`audience_country`](/docs/instagram-api/reference/ig-user/insights#metrics-and-periods)
* [`audience_gender_age`](/docs/instagram-api/reference/ig-user/insights#metrics-and-periods)
* [`audience_locale`](/docs/instagram-api/reference/ig-user/insights#metrics-and-periods)

## Marketing API

**Released** February 8, 2022 | **Available until** January 25, 2023 | [Blog post](/blog/post/2022/02/08/introducing-facebook-graph-marketing-api-v13/)

### Ad Creative

#### Placement Asset Customization Ads

*Applies to v13.0+.*

The [`asset_feed_spec`](/docs/marketing-api/reference/ad-asset-feed-spec/) node of the [POST /{ad-account-id}/adcreatives](/docs/marketing-api/reference/ad-creative#Creating) endpoint will now allow the creation of carousel ads with [Placement Asset Customization ads](/docs/marketing-api/dynamic-creative/placement-asset-customization).

### Ads Library API

#### Ads Archive

*Applies to v13.0+.*

The following query edges and fields on the [`GET /ads_archive`](/docs/graph-api/reference/ads_archive/) endpoint have been deprecated and replaced:

Old Edge/Field | New Edge/Field || `funding_entity` | `bylines` |
| `region_distribution` | `delivery_by_region` |
| `potential_reach_min` | `estimated_audience_size_min` |
| `potential_reach_max` | `estimated_audience_size_max` |
| `potential_reach` | `estimated_audience_size` |

The following return parameters on the [`GET /ads_archive`](/docs/graph-api/reference/ads_archive/) endpoint have been deprecated and replaced:

Old Edge/Field | New Edge/Field || `ad_creative_body` | `ad_creative_bodies` |
| `ad_creative_link_caption` | `ad_creative_link_captions` |
| `ad_creative_link_description` | `ad_creative_link_descriptions` |
| `ad_creative_link_title` | `ad_creative_link_titles` |
| `funding_entity` | `bylines` |
| `region_distribution` | `delivery_by_region` |

### Ad Sets

#### Lookalike Expansion

*Applies to v13.0+. Will apply to all versions May 9, 2022.*

For newly created ad sets that optimize for value, conversions, or app events, lookalike expansion will be turned on by default and cannot be disabled. When getting an ad set that optimizes for value, conversions, or app events, we will return a new lookalike property in the `targeting_optimization_types` map that indicates lookalike expansion is enabled and complements the existing `detailed_targeting` property for the detailed targeting expansion.

This change affects the following endpoints:

* [`POST /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-campaign#Creating)
* [`GET /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-campaign#Reading)

### Conversions API

#### Customer Information Parameters

*Applies to v13.0+.*

There are new requirements for the combinations of [customer information parameters](https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/customer-information-parameters) that are considered valid for an event. An event will be considered invalid if it only includes parameters consisting of one of the following combinations or a subset thereof:

* `ct` + `country` + `st` + `zp` + `ge` + `client_user_agent`
* `db` + `client_user_agent`
* `fn` + `ge`
* `ln` + `ge`

To ensure your events do not throw an error, we recommend that you review the [Conversions API Best Practices](https://developers.facebook.com/docs/marketing-api/conversions-api/best-practices).

This change affects the following endpoints:

* [`POST /{pixel-id}/events`](/docs/marketing-api/conversions-api/using-the-api#send)
* [`POST /{offline_dataset_id}/events`](/docs/marketing-api/conversions-api/using-the-api#send)

### Commerce Platform

#### Shipping Profiles API

*Applies to v13.0+.*

The `handling_time` field of the [`GET /{cms-id}/shipping_profiles`](/docs/commerce-platform/order-management/shipping-profiles-api) endpoint has been moved from the `shipping_profile` object to the `address_category` object.

### Catalog

#### Feed API

*Applies to v13.0+.*

The product feed upload error code XML\_JUNK\_AFTER\_DOCUMENT has been renamed to DATA\_OUTSIDE\_XML\_TAGS. This is a name change only.

The following endpoint is affected:

* [`GET /{feed_upload_session_id}`](https://developers.facebook.com/docs/marketing-api/reference/product-catalog/product_feeds/)

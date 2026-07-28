# Version 18.0

## Graph API

**Released** September 12, 2023 | **Available until** January 26, 2026 | [Blog Post](/blog/post/2023/09/12/introducing-facebook-graph-and-marketing-api-v18/)

### Instagram Graph API

#### Deprecation of Media and User Insights

*Applies to v18.0+. Will apply to all versions on December 11, 2023.*

Duplicative and legacy Instagram insight metrics are being deprecated. Please see documentation for the endpoints and [Instagram Insights](/docs/instagram-api/guides/insights) for more information on which metrics to use in their place.

The following endpoints and metrics are affected:

* [`GET /{ig-user-id}/insights`](/docs/instagram-api/reference/ig-user/insights)
  + `AUDIENCE_GENDER_AGE`
  + `AUDIENCE_LOCALE`
  + `AUDIENCE_COUNTRY`
  + `AUDIENCE_CITY`
* [`GET /{ig-media-id}/insights`](/docs/instagram-api/reference/ig-media/insights)
  + `CAROUSEL_ALBUM_IMPRESSIONS`
  + `CAROUSEL_ALBUM_REACH`
  + `CAROUSEL_ALBUM_ENGAGEMENT`
  + `CAROUSEL_ALBUM_SAVED`
  + `CAROUSEL_ALBUM_VIDEO_VIEWS`
  + `TAPS_FORWARD`
  + `TAPS_BACK`
  + `EXITS`
  + `ENGAGEMENT`

**Note:** `total_interactions`, which is listed as an alternative for some of the deprecated metrics, is currently only available using version 18.0 and does not work with older versions. When querying older versions before Dec 11, 2023, please use the `engagement` metric.`total_interactions`, which is listed as an alternative for some of the deprecated metrics, is currently only available using version 18.0 and does not work with older versions. When querying older versions before Dec 11, 2023, please use the `engagement` metric.

### Server-Sent Events

[Server-Sent Events](/docs/graph-api/server-sent-events) are deprecated and will be removed December 31, 2023.

### WhatsApp

See the [WhatsApp Business Platform changelog](/docs/whatsapp/business-platform/changelog).

## Marketing API

**Released** September 12, 2023 | **Available until** August 13, 2024 | [Blog Post](/blog/post/2023/09/12/introducing-facebook-graph-and-marketing-api-v18/)

### Catalog API

#### Credit Cards

*Applies to v18.0+.*

The `{ad-account-id}/credit_cards` endpoint is no longer supported.

### Reach and Frequency

#### Reach and Frequency Campaigns

*Applies to v18.0+.*

**Objective**

* Target frequency can now be used for `REACH` and `VIDEO_VIEWS` objectives in reach and frequency campaigns.
* The `objective` parameter will no longer accept `TRAFFIC` unless the `rf_prediction_id_to_share` parameter is set to a valid prediction ID.

**Optimizations**

* Reach and frequency campaigns can now use the `REACH` optimization.
* The `optimization_goal` parameter will no longer accept `POST_ENGAGEMENT` or `LINK_CLICKS` unless the `rf_prediction_id_to_share` parameter is set to a valid prediction ID.
* The `frequency_cap` parameter will no longer accept any value greater than `0` if the `optimization_goal` parameter is set to `AD_RECALL_LIFT`. `AD_RECALL_LIFT` predictions will be generated without applying any frequency cap.

The following endpoints are affected:

* [`POST /act_{ad-account-id}/reachfrequencypredictions`](/docs/marketing-api/reference/reach-frequency-prediction)

### Targeting

#### Location Targeting

*Applies to v18.0+. Will apply to all versions December 11, 2023.*

When no `location_types` is sent in the API call, it will default to `['home', 'recent']`.

The following endpoints are affected:

* [`GET /act_{ad-account-id}/reachestimate`](/docs/marketing-api/reference/ad-account/reachestimate/)
* [`GET /act_{ad-account-id}/delivery_estimate`](/docs/marketing-api/reference/ad-account/delivery_estimate/)
* [`POST /act_{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-campaign)
* [`POST /{adset-id}`](/docs/marketing-api/reference/ad-campaign)

#### Location Targeting Deprecation

*Applies to v18.0+.*

All options other than `['home','recent']` will be deprecated for `location_types`. Trying to use any options other than `['home', 'recent']` will result in an error.

The following endpoints are affected:

* [`GET /act_{ad-account-id}/reachestimate`](/docs/marketing-api/reference/ad-account/reachestimate/)
* [`GET /act_{ad-account-id}/delivery_estimate`](/docs/marketing-api/reference/ad-account/delivery_estimate/)
* [`POST /act_{ad-account-id}/saved_audiences`](/docs/marketing-api/reference/saved-audience/)
* [`POST /act_{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-campaign)
* [`POST /{adset-id}`](/docs/marketing-api/reference/ad-campaign)
* [`POST /{saved-audience-id}`](/docs/marketing-api/reference/saved-audience/)

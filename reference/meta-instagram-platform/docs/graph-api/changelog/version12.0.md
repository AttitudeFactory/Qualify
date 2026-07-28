# Version 12.0

## Graph API

**Released** September 14, 2021 | **Available until** TBD | [Blog post](/blog/post/2021/09/14/introducing-facebook-graph-api-v12-marketing-api-v12/)

---

### App Insights

#### Endpoint Deprecation

*Applies to v12.0+*.

The App Insights API is deprecated. Affected endpoints:

* [`GET /{application-id}/app_insights`](/docs/graph-api/reference/application/)

---

### Errors

#### Endpoints that now throw errors

*Applies to v12.0+. Will apply to all versions December 13, 2021.*

The Graph API default behavior is to throw an error when an app requests a field or edge that returns an associated node or nodes, but lacks the appropriate permissions required by the associated nodes. Fields and edges on the endpoints listed below did not follow this protocol and instead were omitted from API responses when the calling app lacked appropriate permissions. Starting with version 12.0, these fields and edges will now conform to the default behavior. This change will apply to all versions on December 13, 2021.

* [`GET /{application-id}/authorized_adaccounts`](/docs/graph-api/reference/application/authorized_adaccounts/)
* [`GET /{atlas-fb-conversion-event-id}/fb_ads_conversion`](/docs/graph-api/reference/atlas-fb-conversion-event/)
* [`GET /{business-unit-id}/ad_accounts`](/docs/graph-api/reference/business-unit/ad_accounts/)
* [`GET /{business-unit-id}/atlas_sales_accesses`](/docs/graph-api/reference/business-unit/atlas_sales_accesses/)
* [`GET /{canvas-product-set-id}/storefront_setting`](/docs/graph-api/reference/canvasproductset)
* [`GET /{commerce-merchant-settings-id}/instagram_channel`](/docs/graph-api/reference/commerce-merchant-settings/)
* [`GET /{commerce-store-id}/merchant_settings`](/docs/graph-api/reference/commerce-store/)
* [`GET /{destination-id}/augmented_realities_metadata`](/docs/graph-api/reference/destination/augmented_realities_metadata/)
* [`GET /{destination-id}/videos_metadata`](/docs/graph-api/reference/destination/videos_metadata/)
* [`GET /{event-id}/ticket_tiers`](/docs/graph-api/reference/event/ticket_tiers/)
* [`GET /{flight-id}/augmented_realities_metadata`](/docs/graph-api/reference/flight/augmented_realities_metadata/)
* [`GET /{flight-id}/videos_metadata`](/docs/graph-api/reference/flight/videos_metadata/)
* [`GET /{live-encoder-id}/current_broadcast`](/docs/graph-api/reference/live-encoder/)
* [`GET /{live-video-id}/copyright`](/docs/graph-api/reference/live-video/)
* [`GET /{page-id}/admin_notes`](/docs/graph-api/reference/page/admin_notes/)
* [`GET /{page-id}/businessprojects`](/docs/graph-api/reference/page/businessprojects/)
* [`GET /{page-id}/connected_instagram_account`](/docs/graph-api/reference/page)
* [`GET /{page-id}/connected_page_backed_instagram_account`](/docs/graph-api/reference/page)
* [`GET /{page-id}/insights_exports`](/docs/graph-api/reference/page/insights_exports/)
* [`GET /{page-id}/instagram_business_account`](/docs/graph-api/reference/page)
* [`GET /{ig-comment-id}/user`](https://developers.facebook.com/docs/instagram-api/reference/ig-comment/)
* [`GET /{ig-media-id}/owner`](https://developers.facebook.com/docs/instagram-api/reference/ig-media)
* [`GET /{ig-user-id}/mentioned_comment`](https://developers.facebook.com/docs/instagram-api/reference/ig-user/)
* [`GET /{user-id}/adaccounts`](/docs/graph-api/reference/user/adaccounts)
* [`GET /{user-id}/assigned_ad_accounts`](/docs/graph-api/reference/user/assigned_ad_accounts)
* [`GET /{user-id}/context`](/docs/graph-api/reference/user)
* [`GET /{user-id}/personal_ad_accounts`](/docs/graph-api/reference/user/personal_ad_accounts)
* [`GET /{video-copyright-id}/update_records`](/docs/graph-api/reference/video-copyright/update_records/)

---

### Instagram Messaging API

#### New User Profile Fields

*Applies to v12.0+*

Added four new fields to the [`GET /{ig-scoped-id}`](/docs/messenger-platform/instagram/features/user-profile) endpoint:

* `is_verified_user`
* `follower_count`
* `is_user_follow_business`
* `is_business_follow_user`

---

### Live Video API

#### Scheduled Live Videos

*Will apply to all versions December 13, 2021.*

UPDATE: This deprecation has been delayed.

Scheduling live videos is no longer available. The `planned_start_time` parameter for the `POST /ID/live_videos` endpoint is deprecated. Calls using this parameter will return an error.\_

Affected endpoints:

* [`POST /{group-id}/live_videos`](/docs/graph-api/reference/group/live_videos#creating)
* [`POST /{page-id}/live_videos`](/docs/graph-api/reference/page/live_videos#creating)
* [`POST /{user-id}/live_videos`](/docs/graph-api/reference/user/live_videos#creating)

---

### Messenger Platform

Multiple changes have been introduced that affect several Messenger APIs and webhooks. Please refer to the [Messenger Platform changelog](/docs/messenger-platform/changelog#sept-14--2021) for a summary of these changes.

---

### Video API

#### New Fields

*Applies to v12.0+.*

Added two new fields to the [`GET /{video-id}`](https://developers.facebook.com/docs/graph-api/reference/video) endpoint:

* `post_views`
* `views`

---

### Workplace

#### Reported Content

*Applies to v12.0+.*

The `reported_object_id` field for the `GET /company/reported_content` endpoint is deprecated. Calls to this field will return no data. Use the new `GET /reported_content/reporters` endpoint instead.

Added six new endpoints:

* `/REPORTED-CONTENT-ID`
* `GET /reported_content/reporters`
* `POST /REPORTED-CONTENT-ID/allow_content`
* `POST /REPORTED-CONTENT-ID/delete_content`
* `POST /REPORTED-CONTENT-ID/quarantine_content`
* `POST /REPORTED-CONTENT-ID/unquarantine_content`

## Marketing API

**Released** September 14, 2021 | **Available until** August 9, 2022 | [Blog post](/blog/post/2021/09/14/introducing-facebook-graph-api-v12-marketing-api-v12/)

---

### Ad Sets

#### Targeting

*Applies to v12.0+. Will apply to all versions December 13, 2021.*

When optimizing for Value, Conversions, or App Events, detailed targeting inclusions will not affect the potential reach and may go beyond detailed targeting inclusions to improve performance. The new `targeting_optimization_types` parameter will indicate which targeting options are used as a signal for optimization.

The following endpoints will be effected:

* [`GET /{adset-id}`](/docs/marketing-api/reference/ad-campaign)
* [`GET /{adset-id}/delivery_estimate`](/docs/marketing-api/reference/ad-campaign/delivery_estimate)

The [`POST /{adset-id}`](=/docs/marketing-api/reference/ad-campaign) endpoint will return an error for updates to newly created ad sets with Value, Conversions or App Events as the optimization goals within Conversions objective campaigns using the `targeting_optimization` field. Existing ad sets will continue allowing changes to the field.

The [`POST /{ad-account-id}/adsets`](/docs/marketing-api/reference/ad-account/adsets) endpoint will return an error if the `targeting_optimization` field is passed when creating a new ad set using Value, Conversions, or App Events as the optimization goals within Conversions objective campaigns. The `targeting_as_signal` field will be ignored when passed during ad set creation.

---

### Business Management API

#### System User App Role Requirements

*Applies to v12.0+. Will apply to all version December 13, 2021.*

A [system user](/docs/marketing-api/system-users) can now only be granted a [role](/docs/development/build-and-test/app-roles) on app if both the system user and the app belong to the same business. On December 13, 2021, app roles will be revoked for any system user who has a role on an app that does not belong to the same business as the system user.

If your app needs to access data using a system user and access token belonging to another business, use the [Business On Behalf Of API](/docs/marketing-api/business-manager/guides/on-behalf-of/) instead.

---

### Errors

#### Endpoints that now throw errors

*Applies to v12.0+. Will apply to all versions December 13, 2021.*

The Marketing API default behavior is to throw an error when an app requests a field or edge that returns an associated node or nodes, but lacks the appropriate permissions required by the associated nodes. Fields and edges on the endpoints listed below did not follow this protocol and instead were omitted from API responses when the calling app lacked appropriate permissions. Starting with version 12.0, these fields and edges will now conform to the default behavior. This change will apply to all versions on December 13, 2021.

* [`GET /{ad-account-id}/ad_saved_keywords`](/docs/marketing-api/reference/ad-account/ad_saved_keywords/)
* [`GET /{ads-pixel-id}/shared_accounts`](/docs/marketing-api/reference/ads-pixel/shared_accounts/)
* [`GET /{ad-study-cell-id}/adaccounts`](/docs/marketing-api/reference/ad-study-cell/adaccounts/)
* [`GET /{business-id}/client_ad_accounts`](/docs/marketing-api/reference/business/client_ad_accounts/)
* [`GET /{business-id}/collaborative_ads_managed_partner_business_info`](/docs/marketing-api/reference/business)
* [`GET /{business-id}/extendedcreditapplications`](/docs/marketing-api/reference/business/extendedcreditapplications/)
* [`GET /{business-id}/owned_ad_accounts`](docs/marketing-api/reference/business/owned_ad_accounts/)
* [`GET /{business-user-id}/assigned_ad_accounts`](/docs/marketing-api/reference/business-user/assigned_ad_accounts/)
* [`GET /{custom-audience-id}/external_event_source`](/docs/marketing-api/reference/custom-audience)
* [`GET /{custom-conversion-id}/pixel`](/docs/marketing-api/reference/custom-conversion)
* [`GET /{extended-credit-invoice-group-id}/ad_accounts`](/docs/marketing-api/reference/extended-credit-invoice-group/ad_accounts/)
* [`GET /{hotel-id}/augmented_realities_metadata`](/docs/marketing-api/reference/hotel/augmented_realities_metadata/)
* [`GET /{hotel-id}/videos_metadata`](/docs/marketing-api/reference/hotel/videos_metadata/)
* [`GET /{instagram-user-id}/authorized_adaccounts`](/docs/marketing-api/reference/instagram-user/authorized_adaccounts/)
* [`GET /{lead-gen-data-id}/context_card`](/docs/marketing-api/reference/leadgendata)
* [`GET /{lead-gen-data-id}/thank_you_page`](/docs/marketing-api/reference/leadgendata)
* [`GET /{offline-conversion-data-set-id}/adaccounts`](/docs/graph-api/reference/offline-conversion-data-set/adaccounts)
* [`GET /{offline-conversion-data-set-upload-id}/pull_sessions`](/docs/graph-api/reference/offline-conversion-data-set-upload/pull_sessions/)
* [`GET /{product-catalog-id}/auto_markets`](/docs/marketing-api/reference/product-catalog/auto_markets/)
* [`GET /{product-catalog-id}/autos`](/docs/marketing-api/reference/product-catalog/autos)
* [`GET /{product-catalog-id}/commerce_merchant_settings`](/docs/marketing-api/reference/product-catalog#Reading)
* [`GET /Produ{product-catalog-id}ctCatalog/media_titles`](/docs/marketing-api/reference/product-catalog/media_titles/)
* [`GET /{product-catalog-id}/services`](/docs/marketing-api/reference/product-catalog/services/)
* [`GET /{product-feed-id}/auto_markets`](/docs/marketing-api/reference/product-feed/auto_markets/)
* [`GET /{product-feed-id}/autos`](/docs/marketing-api/reference/product-feed/autos/)
* [`GET /{product-feed-id}/media_titles`](/docs/marketing-api/reference/product-feed/media_titles/)
* [`GET /{product-set-id}/media_titles`](/docs/marketing-api/reference/product-set/media_titles/)
* [`GET /{system-user-id}/assigned_ad_accounts`](/docs/marketing-api/reference/system-user/assigned_ad_accounts/)
* [`GET /{vehicle-id}/augmented_realities_metadata`](/docs/marketing-api/reference/vehicle/augmented_realities_metadata/)
* [`GET /{vehicle-id}/videos_metadata`](/docs/marketing-api/reference/vehicle/videos_metadata/)

---

### Conversions API

#### Change to access tokens

*Applies to v12.0+*

Access tokens generated under the [Conversions API settings tab in Events Manager](https://developers.facebook.com/docs/marketing-api/conversions-api/get-started#access-token) are no longer restricted to using the newest Graph API version that was available at the time of token generation. Starting with v12.0, newly created access tokens can be used with all available Graph API versions.

Please note that calls made with these tokens to a deprecated Graph API version will automatically resolve to the oldest available version. This behavior only applies to Graph API endpoints. Marketing API endpoints, including the Conversions API, will not resolve to the oldest available version and will instead throw an exception.

---

### Catalog API

#### Deprecation of review\_status field

*Applies to v12.0+*

The `review_status` field on the Product Item node is deprecated. This field has been unreliable and is no longer used in our internal system. Starting with version 12.0, `review_status` will not be accepted as a valid field. We recommend that you use the `channels_to_integrity_status` field instead. Please note that for version 11.0 and earlier, the `review_status` field will always return an empty string.

This change affects the following endpoints:

* [`GET /{catalog_id}/products?filter={"review_status":{"eq":{enum}}}`](/docs/marketing-api/reference/product-catalog/products/)
* [`GET /{catalog_id}/products?fields=["name","review_status"]`](/docs/marketing-api/reference/product-catalog/products/)

#### Catalog permissions

*Applies to v12.0+. Will apply to all versions December 13, 2021.*

If a user does not have business administrator permissions on the business associated with a catalog, they will not be able to modify catalog permissions.

The following edges are affected:

* [`POST /{product-catalog-id}/assigned_users`](/docs/marketing-api/reference/product-catalog/assigned_users)
* [`DELETE /{product-catalog-id}/assigned_users`](/docs/marketing-api/reference/product-catalog/assigned_users)
* [`POST /{product-catalog-id}/agencies`](/docs/marketing-api/reference/product-catalog)
* [`DELETE /{product-catalog-id}/agencies`](/docs/marketing-api/reference/product-catalog)

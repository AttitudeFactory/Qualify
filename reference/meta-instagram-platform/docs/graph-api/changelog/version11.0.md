# Version 11.0

## Graph API

**Released** June 8, 2021 | **Available until** September 14, 2023 | [Blog post](/blog/post/2021/06/08/introducing-facebook-graph-api-v11-marketing-api-v11/)

---

### Consumer Apps

#### Access Levels

*Applies to all versions.*

In the coming weeks, [access levels](/docs/graph-api/overview/access-levels) will apply to all existing [Consumer](/docs/development/create-an-app/app-dashboard/app-types#consumer) apps. For these apps, [permissions](/docs/permissions/reference) and [features](/docs/apps/features-reference) already approved through the [App Review](/docs/app-review) process will be automatically approved for Advanced Access. All other permissions and features will automatically be approved for Standard Access.

Access levels will also apply to all newly created apps in the coming weeks. Newly created apps will automatically be approved for Advanced Access for the [email](docs/permissions/reference/email) and [public\_profile](docs/permissions/reference/public_profile) permissions. However, both permissions will be set to Standard Access by default and must manually be set to Advanced Access before they can be requested from app users who do not have roles on the apps.

---

### Developer Support

We have released the [Facebook for Business Status tool](http://l.facebook.com/l.php?u=http%3A%2F%2Fstatus.fb.com%2F&h=AUDPj9RsxldiEXCHWr6xpUjd2v56j4MbLYjvSbWm5rSUX7FVC3oBVC1mjDD3Q8JM1L4TbX4fg3eezkxZkvGUESJDfDJI2CgZQ7aFYogT9vlynJj4FYhRDf5ZpptZmTwScc2LQrsDZhqpFDO0) to monitor the health of platform and business products such as Ads Manager, WhatsApp Business, and Facebook Developer Platform.

---

### Facebook Analytics

#### Deprecation

*Applies to all versions.*

Facebook Analytics will no longer be available after June 30, 2021. Additionally, we are deprecating the [App Dashboard Plugin for Marketing API](https://developers.facebook.com/docs/development/create-an-app/app-dashboard#marketing-api-stats). For more information visit the [Business Help Center](https://www.facebook.com/business/help/966883707418907).

The following [Application Node](https://developers.facebook.com/docs/graph-api/reference/application/) fields are no longer available:

* `analytics_config`
* `analytics_platform_metrics_config`
* `permissible_ad_accounts`

The following endpoints are no longer available:

* `GET Application/analytics_cohort_query`
* `GET Application/analytics_entity_user_config`
* `GET Application/analytics_event_types`
* `GET Application/analytics_funnel_query`
* `GET Application/analytics_query`
* `GET Application/analytics_segments`

---

### Instagram Basic Display API

#### Access Token Debugger

*Applies to all versions.*

The [access token debugger](/tools/debug/accesstoken/) tool now only returns an [app-scoped ID](#asid) when debugging a token.


#### API Versioning

*Applies to all versions.*

The API now supports [versioned](/docs/instagram-basic-display-api/overview#versions) calls. To query a specific API version include the version number in the query path after the base URL. For example:

`https://graph.instagram.com/v11.0/{node-id}/{edge-name}`

[Un-versioned requests](/docs/apps/versions#unversioned_calls) (missing the version number) resolve to the version specified in the calling app's **App Dashboard** > **Settings** > **Advanced** > **Upgrade API Version** setting.


#### App Scoped User IDs

*Applies to version 11.0+.*

App-scoped user IDs (ASIDs) have been introduced. ASIDs will replace raw user IDs in approximately two years, when version 10.0 is deprecated, so we recommend that you begin mapping your app users' raw IDs to their ASID equivalents.

* All versions support raw user ID based queries.
* Only version 11.0+ calls support ASID based queries.
* Version 11.0+ calls will receive ASIDs in responses, even when querying raw user IDs.


#### Time-based Pagination

*Applies to v11.0+*.

Added [`since`](/docs/instagram-basic-display-api/reference/user/media#query-string-parameters) and [`until`](/docs/instagram-basic-display-api/reference/user/media#query-string-parameters) parameters to the [`GET /{user-id}/media`](/docs/instagram-basic-display-api/reference/user/media#reading) endpoint to support [time-based pagination](/docs/graph-api/using-graph-api#time).

---

### Instagram Graph API

#### Like Counts

*Applies to v11.0+. Will apply to all versions September 7, 2021.*

If indirectly querying an [IG Media](/docs/instagram-api/reference/ig-media) through another endpoint or field expansion, the [`like_count`](/docs/instagram-api/reference/ig-media#fields) field will be omitted from API responses if the media owner has hidden like counts on it. Directly querying the IG Media (which can only be done by the IG Media owner) will return the actual like count, however, even if like counts have been hidden.


#### Time-based Pagination

*Applies to v11.0+*.

Added [`since`](/docs/instagram-api/reference/ig-media/#query-string-parameters) and [`until`](/docs/instagram-api/reference/ig-media/#query-string-parameters) parameters to the [`GET /{ig-user-id}/media`](/docs/instagram-api/reference/ig-user/media#reading) endpoint to support [time-based pagination](/docs/graph-api/using-graph-api#time).

---

### Instant Experiences

#### Templates

*Applies to v11.0+.*

[Instant Experience Templates](https://developers.facebook.com/docs/marketing-api/guides/instant-experiences/#templates) have moved out of of beta and are now available to all developers.

---

### Messenger Platform

#### Messaging Postbacks Webhook

*Applies to v11.0+.*

The `mid` field has been added to the [`messaging_postbacks`](/docs/messenger-platform/reference/webhook-events/messaging_postbacks) webhook to allow apps to get the Message ID.


#### Deprecation of Airline Templates

*Applies to v11.0+. Will apply to all versions on Dec 6, 2021.*

Calls to `POST /{page-id}/messages` that include any [airline templates](https://developers.facebook.com/docs/messenger-platform/send-messages/template/airline) (`template_type` of types [airline\_boardingpass](https://developers.facebook.com/docs/messenger-platform/reference/templates/airline-boarding-pass), [airline\_checkin](https://developers.facebook.com/docs/messenger-platform/reference/templates/airline-checkin), [airline\_itinerary](https://developers.facebook.com/docs/messenger-platform/reference/templates/airline-itinerary), [airline\_update](https://developers.facebook.com/docs/messenger-platform/reference/templates/airline-flight-update)) will fail.

---

### oEmbed

#### New oEmbed Read Feature

*Applies to all versions.*

The oEmbed [product](/docs/development/create-an-app/app-dashboard#products-2) has been replaced with a new [oEmbed Read](/docs/apps/features-reference/oembed_read) feature. If you implemented the oEmbed product before June 8, 2021, you have until September 7, 2021 to complete [App Review](/docs/app-review) for the oEmbed Read feature. If you have not been approved for the oEmbed Read feature by September 7, 2021, your oEmbed implementations will fail to load.

---

### Pages API

#### Comment IDs

*Applies to v11.0+. Will apply to all versions on September 7, 2021.*

The [`id` field for comments](https://developers.facebook.com/docs/graph-api/reference/v10.0/object/comments) will not be returned for any apps that only use the Page Public Content Access feature to query Pages endpoints. These include the `id` fields `/PAGEPOST-ID/comments` or `/COMMENT-ID/comments`. To get the `id` fields for comments for [comments on Page posts](https://developers.facebook.com/docs/graph-api/reference/object/comments/) the app user must be able to perform the [MODERATE task](https://developers.facebook.com/docs/pages/overview/permissions-features#tasks) on the Page being queried.

#### New Page Experience

Over the coming months, all classic Pages will be migrated to the [New Pages Experience](/docs/pages/new-pages-experience). Use the [`has_transitioned_to_new_page_experience` Page field](/docs/graph-api/reference/page) to determine if a Page has been migrated. After all Pages have been migrated, the classic Pages experience will no longer be available.

Most Pages API endpoints support both classic and NPE Pages. Endpoints that support NPE Pages display a "New Pages Experience" section in their references.

The following endpoints do not support NPE pages:

* `/PAGE-ID/likes`
* `/PAGE-ID/global_brand_children`
* `/PAGE-ID/locations`
* `/PAGE-ID/tabs`
* `/PAGE-ID/visitor_posts`

Several Page fields are not available for NPE and will return `null`, a different data set or an error when called. Please visit our [New Pages Experience Overview](/docs/pages/new-pages-experience/overview) for a list of these Page fields.

---

### Permissions

#### user\_likes

*Applies to all versions.*

The allowed usage for the [user\_likes](/docs/permissions/reference/user_likes) permission has been updated. Starting September 7, 2021, apps that have already been approved for this permission but that violate its new usage description will have their approval revoked.

* **Old allowed usage:** Meaningfully improve the quality of a user's experience in your app (must be clear to the user how their data is used to provide that experience).
* **New allowed usage:** Provide a personalized experience by correlating or surfacing content related to the person’s likes. This includes curating content at scale to customize apps with large amounts of content and to enable people to share their likes with others, such as in the case of dating and music apps.

#### user\_posts

*Applies to all versions.*

The allowed usage for the [user\_posts](/docs/permissions/reference/user_posts) permission has been updated. Starting September 7, 2021, apps that have already been approved for this permission but that violate its new usage description will have their approval revoked.

* **Old allowed usage:** Meaningfully improve the quality of a user's experience in your app (must be clear to the user how their data is used to provide that experience).
* **New allowed usage:** Enable people to create physical or digital books or albums of their timelines, and to share memories from their timeline on Facebook or on other social apps.

---

### SDK

Please visit the [iOS SDK Changelog](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Ffacebook%2Ffacebook-ios-sdk%2Fblob%2Fmaster%2FCHANGELOG.md&h=AUDjf1KKK-xyVcX2VriM6OYEIvxQICXpDsv6y_hqe_eeRQG0gS3V3-UAmYmlqrVdtFjSsvng1SNDfDHskEHH60JGy6ArD2MjsBvqXspu8xYGZEefjm_9vWwyK_lFmYao12gWsv1YXq6t0kLo), [Android SDK Changelog](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Ffacebook%2Ffacebook-android-sdk%2Fblob%2Fmaster%2FCHANGELOG.md&h=AUAfXBglWM4JXpRdqI0KF-Bpyux_CxdhpfnNJ4bzDEIjGRmpVzA-BzyB8wIVRHLRuqeInDTICJip5mpeMoqp92n9WAlwhGKVIVYfi6zKKeuZVNmcegICuy1el_6Uc9KpeO8C8Mp_Tv4ZIZg3) and [Unity SDK Changelog](/docs/unity/change-log) to learn about important upcoming changes to these SDKs.

## Marketing API

**Released** June 8, 2021 | **Available until** February 23, 2022 | [Blog post](/blog/post/2021/06/08/introducing-facebook-graph-api-v11-marketing-api-v11/)

---

### Audiences

#### Custom Audiences, Lookalike Audiences, and Saved Audiences Deletion

*Applies to all versions.*

Beginning June 8, 2021 and going forward, any Custom Audience, Lookalike Audience, or Saved Audience that has not been used in any active ad set in over two years will be flagged as an "Expiring Audience". Then, the audience is scheduled to be deleted 90 days after being marked as an "Expiring Audience".

Developers will be able to filter for the "Expiring Audience" status using the `operation_status` field and see the audience's estimated time deletion in the system using the `delete_time` field. Developers can choose to either proactively delete the audience or use the audience in an active ad set to prevent deletion.
Once an audience is deleted, advertisers will not be able to reactivate the audience.

**For Custom Audiences (except Customer List Custom Audiences), Lookalike Audiences, or Saved Audiences:**

* If advertisers wish for the flagged audiences to be automatically deleted beginning Sept 6, 2021 there is no action they need to take. However, if advertisers wish, they can also proactively delete the audience prior to the automatic deletion date.
* For flagged audiences advertisers wish to maintain, they should plan to use these in an active ad set prior to Sept 6, 2021 to prevent the audience from being deleted.

**For Customer List Custom Audiences:**

* We store these on behalf of advertisers in accordance with their instructions. If advertisers do not take any action to use flagged audiences in an active ad set before Sept 6, 2021, we will consider this an instruction for us to delete the flagged audience.

The following endpoints and fields will be affected:

* [`GET /{custom-audience-id}`](/docs/marketing-api/reference/custom-audience)
* [`GET /act_{ad-account-id}/customaudiences?filtering`](/docs/marketing-api/reference/ad-account/customaudiences/)
* `GET /act_{ad-account-id}/saved_audiences?filtering`
* [`GET /{saved-audience-id}`](/docs/marketing-api/reference/saved-audience/)

See [Audiences Overview: Custom Audiences Deletion Changes](/docs/marketing-api/audiences/overview#custom-audiences-deletion) for more information on these updates.

---

### Business API

*Applies to all versions.*

We are temporarily limiting access to the following endpoints. Only apps that have successfully called these endpoints within the last 30 days will continue to have access.

* [`POST /BUSINESS-ID/client_ad_accounts`](https://developers.facebook.com/docs/marketing-api/reference/business/client_ad_accounts/#Creating)
* [`POST /ADACCOUNT-ID/agencies`](https://developers.facebook.com/docs/marketing-api/reference/ad-account/agencies/#Creating)

All other apps will receive an error when making calls to these endpoints.

---

### Catalog API

#### Deprecation of Product Inventory Field

*Applies to 11.0+.*

The `inventory` field will be deprecated and replaced with a new `quantity_to_sell_on_facebook` field. While we will continue to support the `inventory` field for the near term, we recommend that you use the new `quantity_to_sell_on_facebook` field instead.

The following endpoints are affected:

* [`GET /{product-item-id}`](/docs/marketing-api/reference/product-item)
* [`GET /{catalog-id}/products`](/docs/marketing-api/reference/product-catalog/products/)
* [`POST /{product-item-id}`](/docs/marketing-api/reference/product-item)
* [`POST /{catalog-id}/items_batch`](/docs/marketing-api/reference/product-catalog/products/)

See Quantity to Sell and [Supported Fields for Products - Dynamic Ads & Commerce](/docs/marketing-api/catalog/reference/#da-commerce) for more information on this update.


#### Deletion of Non-Empty Product Groups

*Applies to 11.0+. Will apply to all versions on Sept. 7, 2021.*

We will no longer allow deletion of non-empty product groups by default. Non-empty product groups can be deleted by applying `deletion_method=delete_items` to the deletion request. This will delete both the product group and its items.

The following endpoint is affected:

* [`DELETE /<product_group_id>`](https://developers.facebook.com/docs/marketing-api/reference/product-group/#Deleting)


#### Deletion of Live Product Sets

*Applies to 11.0+. Will apply to all versions on Sept. 7, 2021.*

We will no longer allow deletion of a catalog with live product sets by default. To enable deletion of a catalog that contains a live product set, set the catalog's `allow_delete_catalog_with_live_product_set` parameter to `true`.

This change affects the following endpoint:

* [`DELETE /<product_catalog_id>`](/docs/marketing-api/reference/product-catalog)


#### New Diagnostics Endpoint

*Applies to 11.0+.*

We have added a new endpoint [`GET /{product_catalog_id}/diagnostics`](/docs/marketing-api/reference/product-catalog/diagnostics/). This endpoint can be used to retrieve diagnostics data for a given catalog, such as issues that prevent products from showing in channels and opportunities that could improve product discoverability.

---

### Commerce API

#### Order Total Estimated Payment Details

*Applies to 11.0+. Will apply to all versions on Sept. 7, 2021.*

We are changing the way estimated payment details are reported in order totals for calls to the [`{commerce-order-id}/?fields=estimated_payment_details`](/docs/commerce-platform/order-management/order-api) endpoint. Previously, if an order was not fulfilled, an estimated tax was used, and for fulfilled orders, the fulfilled tax was used. Starting with version 11.0, this endpoint will always use the estimated tax. Note that details about the fulfilled tax can be accessed using `{commerce-order-id}/items?fields=tax_details`.

---

### Conversion Lift

#### Metrics Changes

*Applies to v11.0+. Will apply to all versions on Sept. 7, 2021.*

Metrics returned from the `GET /{objective-id}/?fields=result` field have changed.

The following metrics have been added:

* `conversions_incremental_share`
* `conversions_CPiC`
* `conversions_multicell_confidence`
* `conversions_multicell_rank`
* `sales_incremental_share`
* `sales_multicell_confidence`
* `sales_multicell_rank`
* `buyers_incremental_share`
* `buyers_CPiB`
* `buyers_multicell_confidence`
* `buyers_multicell_rank`

The following metrics have been removed:

* `advancedBuyers.control`
* `ancedBuyers.informativeMultiCellBayesianConfidence`
* `advancedBuyers.lift`
* `advancedBuyers.test`
* `advancedConversions.control`
* `advancedConversions.informativeMultiCellBayesianConfidence`
* `advancedConversions.lift`
* `advancedConversions.test`
* `advancedSales.control`
* `advancedSales.informativeMultiCellBayesianConfidence`
* `advancedSales.lift`
* `advancedSales.test`
* `buyers.baseline`
* `buyers.bayesianCILower`
* `buyers.bayesianCIUpper`
* `buyers.control`
* `buyers.delta`
* `buyers.incremental`
* `buyers.isStatSig`
* `buyers.lift`
* `buyers.multiCellBayesianConfidence`
* `buyers.reachedPercent`
* `buyers.singleCellBayesianConfidence`
* `conversions.baseline`
* `conversions.bayesianCILower`
* `conversions.bayesianCIUpper`
* `conversions.control`
* `conversions.delta`
* `conversions.incremental`
* `conversions.isStatSig`
* `conversions.lift`
* `conversions.multiCellBayesianConfidence`
* `conversions.reachedPercent`
* `conversions.singleCellBayesianConfidence`
* `frequency`
* `incrementalROAS`
* `sales.baseline`
* `sales.bayesianCILower`
* `sales.bayesianCIUpper`
* `sales.control`
* `sales.delta`
* `sales.incremental`
* `sales.isStatSig`
* `sales.lift`
* `sales.multiCellBayesianConfidence`
* `sales.singleCellBayesianConfidence`

The following metrics have been renamed:

Old Name | New Name || `advancedBuyers.baseline` | `buyers_not_exposed` |
| `advancedBuyers.bayesianCILower` | `buyers_incremental_lower` |
| `advancedBuyers.bayesianCIUpper` | `buyers_incremental_upper` |
| `advancedBuyers.incremental` | `buyers_incremental` |
| `advancedBuyers.informativeMultiCellPairwiseBayesianConfidence` | `buyers_multicell_confidence` |
| `advancedBuyers.informativeSingleCellBayesianConfidence` | `buyers_confidence` |
| `advancedBuyers.scaled` | `buyers_control_scaled` |
| `advancedConversions.baseline` | `conversions_not_exposed` |
| `advancedConversions.bayesianCILower` | `conversions_incremental_lower` |
| `advancedConversions.bayesianCIUpper` | `conversions_incremental_upper` |
| `advancedConversions.incremental` | `conversions_incremental` |
| `advancedConversions.informativeMultiCellPairwiseBayesianConfidence` | `conversions_multicell_confidence` |
| `advancedConversions.informativeSingleCellBayesianConfidence` | `conversions_confidence` |
| `advancedConversions.scaled` | `conversions_control_scaled` |
| `advancedSales.baseline` | `sales_not_exposed` |
| `advancedSales.bayesianCILower` | `sales_incremental_lower` |
| `advancedSales.bayesianCIUpper` | `sales_incremental_upper` |
| `advancedSales.incremental` | `sales_incremental` |
| `advancedSales.informativeMultiCellPairwiseBayesianConfidence` | `sales_multicell_confidence` |
| `advancedSales.informativeSingleCellBayesianConfidence` | `sales_confidence` |
| `advancedSales.scaled` | `sales_control_scaled` |
| `buyers.pValue` | `buyers_raw_pValue` |
| `buyers.reached` | `buyers_exposed` |
| `buyers.scaled` | `buyers_control_raw_scaled` |
| `buyers.test` | `buyers_test` |
| `conversions.pValue` | `conversions_raw_pValue` |
| `conversions.reached` | `conversions_exposed` |
| `conversions.scaled` | `conversions_control_raw_scaled` |
| `conversions.test` | `conversions_test` |
| `IncrementalROAS` | `sales_ROAS` |
| `sales.pValue` | `sales_raw_pValue` |
| `sales.reached` | `sales_exposed` |
| `sales.scaled` | `sales_control_raw_scaled` |
| `sales.test` | `sales_test` |

A complete list of the available metrics can be seen in the [Facebook Lift Metrics Glossary](https://www.facebook.com/business/help/1092662031214127).

---

### Insights API

#### Deprecation of Store Visit Metrics

*Applies to 11.0+. Will apply to all versions on Sept. 6, 2021.*

The `store_visits_actions` and `cost_per_store_visit_actions` metrics are deprecated.

The following endpoints are affected:

* [`GET /{adaccount-id}/insights`](/docs/marketing-api/reference/ad-account/insights/)
* [`GET /{campaign-id}/insights`](/docs/marketing-api/reference/ad-campaign-group/insights/)
* [`GET /{adset-id}/insights`](/docs/marketing-api/reference/ad-campaign/insights/)
* [`GET /{ad-id}/insights`](/docs/marketing-api/reference/adgroup/insights/)
* [`POST /{adaccount-id}/insights`](/docs/marketing-api/reference/ad-account/insights/)
* [`POST /{campaign-id}/insights`](/docs/marketing-api/reference/ad-campaign-group/insights/)
* [`POST /{adset-id}/insights`](/docs/marketing-api/reference/ad-campaign/insights/)
* [`POST /{ad-id}/insights`](/docs/marketing-api/reference/adgroup/insights/)

---

### Offer Ads API

#### Deprecation of Offer Ads API Endpoints

*Applies to v11.0+. Will apply to all versions on Sept 7, 2021.*

As part of our ongoing effort to increase product stability, Facebook will be ending its support for our Offer Ads product on June 8, 2021. Standard [Facebook Ads](https://www.facebook.com/business/help/621956575422138) are the recommended substitute for distributing your in-store and or online discounts. Discount information, redemption location(s), expiration date, and promotional codes are advised to be placed directly in the [Ad Level](https://www.facebook.com/business/help/2829711350595695?id=649869995454285) creative.

The following endpoints are deprecated:

* [`GET /{page-id}/nativeoffers`](/docs/graph-api/reference/page/nativeoffers/)
* [`POST /[page-id}/nativeoffers`](/docs/graph-api/reference/page/nativeoffers/)
* `GET /pagename/nativeoffers`
* [`GET /{native-offer-id}`](/docs/graph-api/reference/native-offer)
* [`GET /{native-offer-id}/views`](/docs/graph-api/reference/native-offer/views)
* [`POST /{native-offer-id}/codes`](/docs/graph-api/reference/native-offer/codes)
* [`POST /{native-offer-id}/nativeofferviews`](/docs/graph-api/reference/native-offer/nativeofferviews)
* `GET /{offer-id}/comments`
* `GET /{offer-id}/sharedposts`
* `GET /{offer-id}/likes`

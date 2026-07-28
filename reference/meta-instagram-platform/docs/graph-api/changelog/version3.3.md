# Version 3.3

**Released** April 30, 2019 | **Available until** August 3, 2021 | [Blog Post](https://developers.facebook.com/blog/post/2019/04/30/graph-api-v3.3/)

* [Access Tokens](#access-tokens)
* [API](#api)
* [Facebook Login For Devices](#facebook-login-for-devices)
* [General](#general)
* [Groups](#groups)
* [Instagram Graph API](#instagram-graph-api)
* [Live Videos](#live-videos)
* [Messenger](#messenger)
* [Pages API](#pages)

## Access Tokens

*This change applies to v3.3+, and will apply to all versions on July 29, 2019.*

* Unencrypted User and Page access tokens, which were deprecated in 2012, will no longer be accepted by any of our APIs.

## API

*This change applies on April 30, 2019.*

* Due to the `favorite_requests-id` deprecation, the option to save and view favorites in the Graph Explorer tool is no longer unavailable.

## General

*This change applies to v3.3+.*

* [`GET /me/permissions`](/docs/graph-api/using-graph-api#me) — This endpoint will now return one of three states, `granted`, `declined`, or `expired`.

## Facebook Login for Devices

*This change applies to v3.3+.*

* `POST /{device-id}/login_status` — This endpoint will now return an HTTP 200 status code instead of HTTP 500. Continue to check the error subcode for the user's login status.

## Groups

*This change applies to v3.3+.*

* `POST /{group-id}` — The `group_type` parameter has been renamed to `purpose`. This aligns the parameter name with its matching `purpose` field on Group nodes.

## Instagram Graph API

*These changes apply to v3.3+, and will apply to all versions July 29, 2019.*

* The Instagram account rate limit now uses a new [Business Use Case rate limiting system for Instagram Graph API](/docs/graph-api/overview/rate-limiting#instagram-rate-limiting). This new limit is determined by analyzing the number of impressions on the Instagram account. Please note that your rate limit will no longer be determined by the number of users on the app. If the app is owned by business, it has its own ratio limit quota that is not shared with other apps accessing the same Instagram account. If an app is not owned by a business, the app competes with other apps for the same Instagram account.

## Live Videos

*This change applies to v3.3+, and will apply to all versions on July 29, 2019.*

* **Webhooks** — The `live_video` Webhooks field on the User object has been deprecated.

## Messenger

*Introducing two new non-versioned features.*

* A new Page control allows a Page admin to opt into a Page messaging rate limit to prevent the Page from being transitioned into a [High-mps Page](/docs/messenger-platform/reference/send-api/#high-mps).
* A sample e-commerce Messenger App, [Original Coast Clothing](/docs/messenger-platform/getting-started/sample-apps/original-coast-clothing), showcases Messenger automation features. This app includes a how-to guide and open-source code to deploy on your server.

*These changes apply to v3.3+, and will apply to all versions July 29, 2019.*

* `POST /{page-id}/broadcast_messages` — The [Broadcast API](/docs/messenger-platform/reference/broadcast-api/) now requires only the Page-level subscription feature. The App-level `pages_messaging_subscriptions` permission is deprecated.

* `GET {page_id}/insights` — The [Messaging Insights API](/docs/messenger-platform/reference/messaging-insights-api/) `page_messages_active_threads_unique` and `page_messages_reported_conversations_by_report_type_unique` metrics are deprecated.

*These changes apply to v3.3+, and will apply to all versions June 30, 2020.*

* `POST /{object-id}/private_replies` and `GET /{conversation-id}` — The [Conversation API](/docs/graph-api/reference/v3.3/conversation) and [Private Reply](/docs/graph-api/reference/v3.3/object/private_replies) endpoints now require the `pages_messaging` permission as the `read_page_mailboxes` permission is deprecated. Apps previously approved for `read_page_mailboxes` need to go through [App Review](/docs/apps/review) for `pages_messaging` permissions approval.

## Pages API

*These changes apply to v3.3+.*

* The Page `promotable_posts` edge is deprecated. Call `{page-id}/feed` and filter by `is_eligible_for_promotion` field for published Page posts. Call the [`{page-id}/ads_posts` field](/docs/graph-api/reference/page/ads_posts/) for unpublished posts including `ads_posts` type, which are hidden posts created from the Ads Posts tool in Ads Manager, and `inline_create` type, which are hidden posts backing published Ads. Call `{page-id}/scheduled_posts` for scheduled posts.

* `GET posts` — The following fields on the `{page_id}/feed`, `{page_id}/published_posts`, `{page_id}/posts`, and `{page_post_id}` nodes are deprecated:

  + `caption`
  + `description`
  + `link`
  + `name`
  + `object_id`
  + `source`
  + `type`

Get these fields' information using the [`attachments` field](/docs/graph-api/reference/v3.3/post) instead. See the mapping in the table below.

Deprecated Field | Maps To || `caption` | `attachments{title}` |
| `description` | `attachments{description}` |
| `link` | `attachments{unshimmed_url}` |
| `name` | `attachments{title}` |
| `object_id` | `attachments{target{id}}` |
| `source` | `attachments{media{source}}` |
| `type` | `attachments{media_type}` If there is no `attachments` or `media_type=link`, the value is the same as [`attachments{type=status}`](/docs/graph-api/reference/story-attachment). |

*These changes apply to v3.3+, and will apply to all versions July 29, 2019.*

* The Page level rate limit now uses a new [Business Use Case rate limiting system for Pages API](/docs/graph-api/overview/rate-limiting#page-level-rate-limiting). This new logic is applied to apps that are owned by a business and use either a Page or system access token. If the app is owned by business, it has its own ratio limit quota that is not shared with other apps accessing the same Page. If an app is not owned by a business, the app competes with other apps for the same Page.

*These changes apply to v3.3+, and will apply to all versions June 30, 2020.*

* The [Pages for Webhooks](/docs/pages/realtime/) `conversations` field is deprecated. Use the existing [Messenger Webhooks](/docs/messenger-platform/webhook) `messages` field instead.

## Marketing API

**Released** April 30, 2019 | **Available Until** - Deprecation Extension - January 13, 2020

### New Features

We made Marketing API improvements for `STORE_VISITS`, which is also known as *Store Traffic* in Facebook UIs. With this `optimization_goal`, we deliver your ads with the goal of driving store traffic to locations you specify by given Facebook Pages. **Note: This API is under limited availability. Please contact your Facebook Representative for access.**

* You can now use an asynchronous request to create a Page Set. This enables you to create large page sets with more than 1,000 locations without experiencing timeouts. Previously, you could only make synchronous requests.
* We now include a `metadata` field. With this field, you can specify `fixed_radius` to provide absolute distances from your locations. Or, you can specify `audience` and Facebook automatically calculates a radius around your location to reach this number of people. Facebook tries to deliver your ad to an audience in this radius.

For more details, see [Store Visits, Create a Pageset](/docs/marketing-api/guides/dynamic-ad/store-visits#pageset).

### Ads Management

* Deprecated `custom_overlay_spec` field in `link_data`, `photo_data`, and `video_data` in the `object_story_spec` field for ad creatives. Text overlays on top of images and videos resulted in poorer ad performance compared to ads without text overlays. As of November 2018, you could no longer create image or video ads with this feature. As of this release, if you have ads with text overlays specified in your `object_story_spec`, we deliver your ads without the overlay. This impacts:

  + `POST /{ad_account_ID}/creatives`
  + `GET /{creative-id}?fields=object_story_spec`

* Default `use_flexible_image_aspect_ratio` to `true`. This field is only for *single image ads*, not for carousel ads.
  If you set this to `true`, when the image's aspect ratio, or width:height ratio, is between 1.91:1 and 1:1, we render the entire image. If the image is taller than the aspect ratio of 1:1, we automatically crop it to 1:1 and render the cropped image.

  If the image is wider than the aspect ratio 1.91:1, we automatically crop it to 1.91:1 and render the cropped image.

  If you set this to `false`, or provide no value, when the image's aspect ratio, or width:height ratio, is 1.91:1, we render the entire image.
  If the image aspect ratio is not 1.91:1, we automatically crop it to the 1.91:1 aspect ratio and render the cropped image.

  This field only applies to images if you don't provide a `cropping_spec`. If you do provide a `cropping_spec`, we ignore this field. We don't support this for Event ads, Offer ads, dynamic ads, ads with image overlays, and ads using stock images. This impacts:

  + `POST /{ad_account_ID}/creatives`
  + `GET {ad_creative_ID}`
  + `POST {ad_account_ID}/ads`
  + `POST {ad_ID}`

* Deprecated `191x100` `cropping_spec` for all placements. The recommended crop key will be `100x100`. This impacts:

  + `POST /{ad_account_ID}/creatives`
  + `GET {ad_creative_ID}`
  + `POST {ad_account_ID}/ads`
  + `POST {ad_ID}`
* Default optimization for campaigns with `VIDEO_VIEWS` objective is `THRUPLAY`. This impacts:

  + `POST {ad_account_ID}/adsets`

* Deprecated `VIDEO_VIEWS` as a valid optimization for ad campaigns with the `APP_INSTALL` or `POST_ENGAGEMENT` objective. This optimization goal is also commonly known as 10-Second video views.
* Added `event` to the pixel automatic event `/stats` response. This provides an additional way to group response data with stats based on the detection method for an event. This impacts `GET {ads-pixel-ID}/stats/aggregation=event_detection_method`.

### Catalog

* We now require `ads_management` permissions scope for all users trying to *create, update, or delete catalogs and any objects related to a catalog, such as a hotel*. As of v3.3, we require this and any public version of the API will require this in 90 days. This impacts [Catalog](/docs/marketing-api/dynamic-product-ads/product-catalog) and all dynamic ads that rely on catalogs, such as [Hotel ads](/docs/marketing-api/dynamic-ads-for-hotels/catalog), [Automotive Inventory ads](/docs/marketing-api/dynamic-ads-auto/auto-catalog) and [Real Estate ads](/docs/marketing-api/dynamic-ads-for-real-estate). This impacts:

  + `POST {catalog_ID}/batch`
  + `GET {catalog_ID}/check_batch_request_status`
  + `GET {catalog_ID}/product_feeds`
  + `POST {catalog_ID}/product_set_batch`
  + `GET {catalog_ID}/home_listings`
  + `GET {catalog_ID}/hotels`
  + `GET {catalog_ID}/hotel_rooms_batch`
  + `POST {catalog_ID}/hotel_rooms_batch`
  + `GET {catalog_ID}/pricing_variables_batch`
  + `POST {catalog_ID}/pricing_variables_batch`
  + `GET {catalog_ID}/products`
  + `GET {catalog_ID}/vehicles`
  + `GET` requests for all other vertical-specific catalog objects
  + `GET {product_set_ID}/products`
  + `GET {product_set_ID}/home_listings`
  + `GET {product_set_ID}/hotels`
  + `GET {product_set_ID}/vehicles`
  + `GET` requests for all other vertical-specific product set objects
  + `GET {product_feed_ID}/products`
  + `GET {product_feed_ID}/home_listings`
  + `GET {product_feed_ID}/hotels`
  + `GET {product_feed_ID}/vehicles`
  + `GET` requests for any other vertical-specific product feed objects
  + `GET {business_ID}/owned_product_catalogs`
  + `GET {business_ID}/client_product_catalogs`
  + `GET {product_feed_upload_ID}/errors`
  + `GET {product_catalog_ID}/smart_pixel_settings`
  + `GET {product_feed_ID}/rules`
  + `POST {canvas_ID}/product_set`
  + `GET {application_ID}/da_checks`
  + `GET {pixel_ID}/da_checks`

* Deprecated user permissions endpoints for managing access to catalogs. For background information, see [Business Manager API, Product Catalogs](/docs/marketing-api/businessmanager/assets#product_catalog):

  + `GET catalog_ID/userpermissions` to read permissions granted to people for the catalog
  + `POST catalog_ID/userpermissions` to grant permissions
  + `DELETE {catalog_id}/userpermissions` to revoke permissions

  We replace these endpoints with new endpoints:

  + `GET catalog_ID/assigned_users?business={business_id}` to read permissions granted to users to access this catalog
  + `POST {catalog_id}/assigned_users?business={business_id}` to grant permissions
  + `DELETE {catalog_id}/assigned_users?business={business_id}` to revoke permissions

* Deprecated Batch API v2.8 for catalogs. This goes into effect in early Q3, 2019. To keep your current upload feed structure, you can continue using `/batch` instead of moving to `/items_batch` and keep your field names consistent. To do so, switch to API version 2.9 or above. For more information, see [Catalog Batch API](/docs/marketing-api/using-products-batch-api).

### Ads Insights and Measurement

* Changed rate limits at the ad account level to better reflect the actual volumne of API calls needed. We now compute the rate limit quota based on your Marketing API access tier and the business for your app. This goes into effect 90 days after the release of v3.3 for all public versions. See [Marketing API, Access and Authentication](/docs/marketing-api/access). This change impacts all ads Insights API endpoints including:

  + `GET {ad_account_ID}/insights`
  + `GET {ad_campaign_ID}/insights`
  + `GET {adset_ID}/insights`
  + `GET {ad_ID}/insights`
  + `POST {ad_account_ID}/insights`
  + `POST {ad_campaign_ID}/insights`
  + `POST {adset_ID}/insights`
  + `POST {ad_ID}/insights`

* Deprecated several Insights API metrics, including `action_type` breakdowns. This impacts the following endpoints:

  + `GET {ad_account_ID}/insights`
  + `GET {ad_campaign_ID}/insights`
  + `GET {adset_ID}/insights`
  + `GET {ad_ID}/insights`
  + `POST {ad_account_ID}/insights`
  + `POST {ad_campaign_ID}/insights`
  + `POST {adset_ID}/insights`
  + `POST {ad_ID}/insights`

  The following are deprecated metrics and breakdowns plus some recommended alternates:

  + Deprecated `app_custom_event.fb_mobile_purchase` from the metric `mobile_app_purchase_roas`. You can find a replacement metric at `omni_purchase`, action type `purchase_roas` metric.
  + Deprecated `offsite_conversion.fb_pixel_purchase` from the metric `website_purchase_roas`. You can find a replacement metric at `omni_purchase`, action type `purchase_roas` metric.

  The following action types are entirely deprecated from all Insights API metrics:

  + `offline_conversion`
  + `onsite_conversion.messaging_reply` — You can replace with a custom formula as `onsite_conversion.messaging_first_reply` divided by `onsite_conversion.messaging_conversation_started`
  + `receive_offer`
  + `commerce_event`
  + `commerce_event.add_to_cart`
  + `commerce_event.purchase`
  + `commerce_event.message_to_buy`
  + `commerce_event.other`
  + `commerce_event.view_content`

### Business Manager API

* Deprecated the `role_based` field `permitted_role` in Business Manager API. The following endpoint is impacted: `POST {business-id}/owned_businesses`.
* Deprecated `{business_ID}/creditcards`. Instead you should use `GET {credit_card_ID}`.

### Upgrading to Marketing API v3.3

A few reminders for our developer community:

* *All versions prior to Marketing API v3.2 will be deprecated on **May 14, 2019***.
* All apps need to be on at least v3.3.
* Developers should specify `/v3.3/` in your URLs when you call the API.
* To see details of changes in v3.3, see the [Graph API v3.3 Changelog](https://developers.facebook.com/docs/graph-api/changelog/version3.3).
* SDK developers should view our latest [Java SDK](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Ffacebook%2Ffacebook-java-business-sdk&h=AUAqLg5ofWuZKJoOMJgryj51i1F1ez6BZNcjXgk5BZEJZ8-0dsfaixiUugtQGG4K_sG7dBxpJAovNKXu2MwSeXi82Hk0FHjJv2CjSISPsGwV1kDN22oAyjwJ1PHbmQ8Hx80uNe9kbXTs1wG8), [PHP SDK](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Ffacebook%2Ffacebook-php-business-sdk&h=AUAuTswO74_N2t0PusoBlfrcUMOhY2A60jiibm_4zyGInvFFq4KXqNeUkyTD-u1iW4LjAv9010-ELc_EfuMnjO2wTViz0FPaeIZnt6iVPf44aynZcp3z5VRjUuvkdUd0OU2bS72facDbupir), [Python SDK](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Ffacebook%2Ffacebook-python-business-sdk&h=AUBzJD1sSDtyPnUS5UGY8lYQSdTlZpF8AeK10xk0kbZbK82F9gEvfhyoHr8ekdOOnFaSqY65eI-cVyCRu89-d3nzsC_26Yvvvd_BvUqRse0m2VwGL1SkzMFw93XuTTPaKYQqdgAogG_7Uup2), or [Ruby SDK](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Ffacebook%2Ffacebook-ruby-business-sdk&h=AUCjGsHe3WVjhk37QNmWXw5jwI-hsc3myf9cM38VpAB_xr1906DTFvCkY8Wcna_XGCp41rLcp7yBZJkf3lpV7mRLagvt8BouUcoVfRUSYoNGU3PHpePVD5lNwLGtk9h6Q72qGrEJt7eLPneK).

# Version 3.2

**Released** October 23, 2018 | **Available until** May 4, 2021 | [Blog Post](https://developers.facebook.com/blog/post/2018/10/23/introducing-graph-api-v3.2-marketing-api-v3.2-facebook-login-messenger-app-updates/)

* [Application](#application)
* [Instagram Graph API](#instagram-graph-api)
* [Page Insights](#page-insights)
* [Pages](#pages)
* [Video Polls](#video-polls)

## Application

*These changes apply to v3.2+.*

`GET /{app-id}` — Reading an app's statistics now requires that app's access token. This affects the following fields:

* `daily_active_users`
* `daily_active_users_rank`
* `weekly_active_users`
* `monthly_active_users`
* `monthly_active_users_rank`

## Instagram Graph API

*These changes apply to v3.2+.*

The `/{instagram-media-id}/comments` edge now returns `GET` results in reverse chronological order instead of chronological order.

## Page Insights

*These changes apply to v3.2+, and will apply to all versions on January 21, 2019.*

Period parameters have been changed to `day` from `lifetime` for the following metrics. The `lifetime` period parameter will return an empty dataset.

* `page_fans`
* `page_fans_city`
* `page_fans_country`
* `page_fans_gender_age`
* `page_fans_locale`

## Pages

*These changes apply to v3.2+*

The Page field `crossposting_pages` is deprecated.

The Page `userpermissions` edge is deprecated.

The Pages Webhooks `subscribed_apps` has a new parameter, `subscribed_fields`, to read existing webhooks fields and required when assigning new webhooks fields. Use this new parameter to assign webhooks at the Page level rather than the app level. Due to this change, apps must now have the permissions required for each field requested. For example, if the `leadgen` webhook field is requested the app must have the `leads_retrieval` permission.

## Video Polls

*These changes apply to v3.2+*

You can now create and manage Video Polls on Live Videos and VODs. The following endpoints have been added:

* [`/{video-id}/polls`](/docs/graph-api/reference/video/polls)
* [`/{live-video-id}/polls`](/docs/graph-api/reference/live-video/polls)
* [`/{video-poll-id}`](/docs/graph-api/reference/video-poll/)
* [`/{video-poll-id}/options`](/docs/graph-api/reference/video-poll/poll_options/)
* [`/{video-poll-option-id}`](/docs/graph-api/reference/video-poll-option/)

Refer to the [Live Polls API documentation](/docs/videos/live-video/live-polls-api) for usage instructions.

## Marketing API

**Released** October 23, 2018 | **Available Until** August 13, 2019 | [Blog Post](https://developers.facebook.com/ads/blog/post/2018/10/23/marketing-api-v32/)

### New Features

We are introducing a new ads run status where a campaign, ad set, or ad can be set to `WITH_ISSUES` if it can't be delivered, for any reason. Together with this new run status, we introduce `ISSUES_INFO`, which provides more detail with the `error_code` that prevented your ads from delivering.

new ads run status where a campaign, ad set, or ad can be set to WITH\_ISSUES if it can't be delivered for any reason.

### Ads Management

* You can now only create a Dynamic Creative ad groups only under a Dynamic Creative ad campaign by specifying `is_dynamic_creative`. The following endpoint is impacted: `POST /{ad-account-id}/adsets`.

* Deprecated `asset_feed_id` from `GET` and `POST` used in [Dynamic Creative](/docs/marketing-api/asset-feed). This impacts:

  + `POST {adaccount_ID}/adasset_feeds`,
  + `POST {adaccount_ID}/adcreatives`, if you use `asset_feed_id` as a parameter,
  + `GET {asset_feed_ID}/`

  Instead of using these APIs, you should use `asset_feed_spec` in ad creative to specify all the assets such as images and text to use in your Dynamic Creative ads. See [Dynamic Creative](/docs/marketing-api/asset-feed).

* Deprecated language asset feeds used to optimize different languages which display in your ad's creative. See [Optimize Languages](/docs/marketing-api/dyn-language-optimization). We deprecated the following endpoints:

  + `GET /{adaccount_ID}/adlanguage_assets`,
  + `POST /{adaccount_ID}/adlanguage_assets`,
  + `GET {asset_feed_ID}/`.

  Instead, you should use `asset_feed_spec` to specify different languages. For more information, see [Optimize Languages](/docs/marketing-api/dyn-language-optimization).

* Changed the API for language asset feeds to use asset customization rules instead of group rules. This provides you a more unified way to create and optimize languages which display in unique ad creative per impression. This impacts:

  + `GET /?fields=asset_feed_spec` now returns `asset_customization_rules` associated with your languages instead of `groups`,
  + `customization_spec` now supports `locales`, which enables you to display different languages based on locales.

  For more information, see [Optimize Languages](/docs/marketing-api/dyn-language-optimization).

* Deprecated the ability to read `objective_source` from ad objects. This impacts:

  + `GET {ad_account_ID}/ads`,
  + `GET {ad_ID}`.

* Deprecated `CLICKS` as an `optimization_goal` when you create a new ad set. You also cannot change `optimization_goal` to `CLICKS` for existing ad sets. Doing either will return an error. This impacts:

  + `POST {ad_account_ID}/adsets`,
  + `POST {adset_ID}`.

* Deprecated reading the `objective_source` field from ads. The following endpoints are impacted:

  + `GET /{adaccount_ID}/ads`,
  + `GET /{ad_ID}`.

* As part of deprecations in the Insights API for cost per metrics, the following metrics are no longer available in [Ads Rules Engine](/docs/marketing-api/ad-rules-getting-started). The following fields are deprecated with no planned replacement, see [Ads Help, About New Standard Events and Changes to Conversion Metrics](https://www.facebook.com/business/help/264025764224228):

  + `cost_per_offline_add_payment_info`,
  + `cost_per_offline_add_to_cart`,
  + `cost_per_offline_add_to_wishlist`,
  + `cost_per_offline_initiate_checkout`,
  + `cost_per_offline_view_content`,
  + `cost_per_offline_lead`,
  + `cost_per_offline_purchase`,
  + `cost_per_offline_complete_registration`, and
  + `cost_per_offline_search`.

  For more details, see [Marketing API 3.2, Breaking Changes, Insights](#ads-insights-and-measurement)

* Deprecated the field `rtb_flag` from `targeting`. This also deprecates the field from `GET /{adset_ID}` and `GET /{ad_account_ID}/adsets`.
* Deprecated `metadata` edge from ad groups. The following endpoints will be affected: `GET /{adgroup_id}`.

### Dynamic Ads

Product sets now must contain at least one product for use in Dynamic Ads, product catalogs. From now on if you try to create a set with no products, we return an error. This impacts `product_catalog_ID/product-set`.

### Ads Insights and Measurement

We deprecated cost per engagement metrics, conversion pixel metrics, composite metrics and cost per event metrics, noted below. The following endpoints are affected:

* `GET {adaccount-id}/insights`,
* `GET {campaign-id}/insights`,
* `GET {adset-id}/insights`,
* `GET {ad-id}/insights`,
* `POST {adaccount-id}/insights`,
* `POST {campaign-id}/insights`,
* `POST {adset-id}/insights`,
* `POST {ad-id}/insights`.

Deprecated ads-related metrics under Insights API in order to simplify reporting and support reporting based on our new eight standard events. This deprecates:

* `actions`:

  + `offsite_conversion`
  + `app_custom_event`
  + `offsite_conversion.add_to_cart`
  + `offsite_conversion.checkout`
  + `offsite_conversion.key_page_view`
  + `offsite_conversion.lead`
  + `offsite_conversion.other`
  + `offsite_conversion.registration`
* `action_values`:

  + `offsite_conversion`
  + `offsite_conversion.add_to_cart`
  + `offsite_conversion.checkout`
  + `offsite_conversion.key_page_view`
  + `offsite_conversion.lead`
  + `offsite_conversion.other`
  + `offsite_conversion.registration`
* `cost_per_action_type`:

  + `offsite_conversion`
  + `app_custom_event`
  + `offsite_conversion.add_to_cart`
  + `offsite_conversion.checkout`
  + `offsite_conversion.key_page_view`
  + `offsite_conversion.lead`
  + `offsite_conversion.other`
  + `offsite_conversion.registration`
  + `comment`
  + `post_reaction`
  + `post_like`
  + `post`
  + `photo_view`
  + `checkin`
  + `app_custom_event.fb_mobile_achievement_unlocked`
  + `app_custom_event.fb_mobile_add_payment_info`
  + `app_custom_event.fb_mobile_add_to_cart`
  + `app_custom_event.fb_mobile_add_to_wishlist`
  + `app_custom_event.fb_mobile_initiated_checkout`
  + `app_custom_event.fb_mobile_content_view`
  + `app_custom_event.fb_mobile_spent_credits`
  + `app_custom_event.fb_mobile_level_achieved`
  + `app_custom_event.fb_mobile_purchase`
  + `app_custom_event.fb_mobile_rate`
  + `app_custom_event.fb_mobile_complete_registration`
  + `app_custom_event.fb_mobile_search`
  + `app_custom_event.fb_mobile_activate_app`
  + `app_custom_event.fb_mobile_tutorial_completion`
  + `offline_conversion.add_payment_info`
  + `offline_conversion.add_to_wishlist`
  + `offline_conversion.initiate_checkout`
  + `offline_conversion.view_content`
  + `offline_conversion.lead`
  + `offline_conversion.purchase`
  + `offline_conversion.complete_registration`
  + `offline_conversion.search`
  + `offsite_conversion.fb_pixel_search`
  + `offsite_conversion.fb_pixel_add_payment_info`
  + `offsite_conversion.fb_pixel_add_to_cart`
  + `offsite_conversion.fb_pixel_add_to_wishlist`
  + `offsite_conversion.fb_pixel_initiate_checkout`
  + `offsite_conversion.fb_pixel_view_content`
  + `offsite_conversion.fb_pixel_lead`
  + `offsite_conversion.fb_pixel_purchase`
  + `offsite_conversion.fb_pixel_complete_registration`
  + `onsite_conversion.add_to_cart`
  + `onsite_conversion.purchase`
  + `onsite_conversion.view_content`
  + `app_install`
  + `mobile_app_install`
  + `app_custom_event.other`
* `cost_per_unique_action_types`:

  + `app_custom_event.fb_mobile_activate_app`
  + `app_custom_event.fb_mobile_content_view`
  + `app_custom_event.fb_mobile_tutorial_completion`
  + `app_custom_event.fb_mobile_achievement_unlocked`
  + `app_custom_event.fb_mobile_add_payment_info`
  + `app_custom_event.fb_mobile_add_to_cart`
  + `app_custom_event.fb_mobile_add_to_wishlist`
  + `app_custom_event.fb_mobile_initiated_checkout`
  + `app_custom_event.fb_mobile_spent_credits`
  + `app_custom_event.fb_mobile_level_achieved`
  + `app_custom_event.fb_mobile_purchase`,
  + `app_custom_event.fb_mobile_rate`
  + `app_custom_event.fb_mobile_complete_registration`
  + `app_custom_event.fb_mobile_search`
  + `app_custom_event.other`
  + `offline_conversion.add_payment_info`
  + `offline_conversion.add_to_wishlist`
  + `offline_conversion.initiate_checkout`
  + `offline_conversion.lead`
  + `offline_conversion.purchase`
  + `offline_conversion.search`
  + `offline_conversion.view_content`
  + `offsite_conversion.fb_pixel_add_payment_info`
  + `offsite_conversion.fb_pixel_add_to_cart`
  + `offsite_conversion.fb_pixel_add_to_wishlist`
  + `offsite_conversion.fb_pixel_complete_registration`
  + `offsite_conversion.fb_pixel_initiate_checkout`
  + `offsite_conversion.fb_pixel_lead`
  + `offsite_conversion.fb_pixel_purchase`
  + `offsite_conversion.fb_pixel_search`
  + `offsite_conversion.fb_pixel_view_content`
  + `app_install`
  + `mobile_app_install`
  + `onsite_conversion.add_to_cart`
  + `onsite_conversion.purchase`
  + `onsite_conversion.view_content`
  + `comment`
  + `post_reaction`
  + `post_like`
  + `post`
  + `photo_view`
  + `checkin`
  + `app_custom_event`
  + `offsite_conversion.add_to_cart`
  + `offsite_conversion.checkout`
  + `offsite_conversion.key_page_view`
  + `offsite_conversion.lead`
  + `offsite_conversion.other`
  + `offsite_conversion.registration`
  + `offsite_conversion`
* `catalog_segment_value`:

  + `offsite_conversion.add_to_cart`
  + `offsite_conversion.checkout`
  + `offsite_conversion.fb_pixel_lead`
  + `offsite_conversion.other`
  + `offsite_conversion.registration`
* `total_action_value`

Deprecated the `active_iterative_split_test_config_id` field used in split testing from `GET /{adset-id}`.

### Business Manager API

Deprecated `/userpermissions`. You should use `business_users`, `system_users` or `pending_users` instead, See [Business Manager API, Managing People and Roles](/docs/marketing-api/business-manager-api#users). This impacts:

* `GET {ad-account-id}/userpermissions`
* `POST {ad-account-id}/userpermissions`
* `DELETE {ad-account-id}/userpermissions`

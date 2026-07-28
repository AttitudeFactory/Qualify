# Version 4.0

**Released** July 29, 2019 | **Available until** November 2, 2021 | [Blog Post](https://developers.facebook.com/ads/blog/post/2019/07/29/introducing-graph-api-v4-marketing-api-v4/)

* [Access Tokens](#access-tokens)
* [Applications](#applications)
* [Canvas](#canvas)
* [Currencies](#currencies)
* [Global User IDs](#global-user-ids)
* [Marketing API](#marketing-api)
* [Messenger](#messenger)
* [Page Public Content Access](#page-public-content-access)
* [Pages API](#pages-api)
* [Versioning](#versioning)
* [Webhooks](#webhooks)

## Access Tokens

*This change applies to v4.0+ and will apply to all versions on October 29, 2019.*

A small subset of User access tokens are no longer valid. Any API requests made using these tokens will fail. If your app has been affected, a dev alert has been sent to you. Query the `/token_deprecation_check` endpoint to see if any of your User access tokens are affected. Users who's access tokens are invalidated will need to re-authenticate.

## Applications

*This change applies to v4.0+.*

* `GET /{application-id}/picture` — This endpoint has been deprecated.

## Canvas

*The change applies immediately for all apps created after July 29 2019, and on August 29 2019 for all existing apps.*

The `user` field will no longer be included in [Signed Request](/docs/reference/login/signed-request/) objects.

## Currencies

*This change applies to v4.0+*

Endpoints that return amounts in a specific country's currency now comply with the [Unicode Common Locale Data Repository](http://l.facebook.com/l.php?u=http%3A%2F%2Fcldr.unicode.org%2F&h=AUCmRcRKRnHAf1CTpfdYYIafx2pZZ1zgJxvYqfyndyld7t6eLoQ4k00tr--zdMLjDz0mZWrimUwV9tNqY0akdUt6ldn42wJlaxegvPdJQwXEzvf00X365IG7Pf2V57tRrNwzOw4ba7cCfjlE) standard. If an endpoint returns an amount in a specific country's currency, but the calling app is outside of that country, the country's ISO country code will be prefixed to the currency's symbol. For example, if an endpoint returns amounts in US dollars but the app making the request is in Australia (which also uses the $ symbol), the endpoint will respond with `US$99` instead of `$99`.

## Global User IDs

*This change applies to v4.0+ and will apply to all versions on October 29, 2019.*

Parameters that accept User IDs will only accept app-scoped User IDs and no longer accept global User IDs unless the User is known to the app by their global ID. This applies to all endpoints.

## Messenger

### M.me Links

*The following change is a non-versioned features.*

[M.me links](https://developers.facebook.com/docs/messenger-platform/discovery/m-me-links/) now reopen the 24hr window within existing threads. When a person clicks an m.me link that contains a ref parameter and is taken into an existing thread, it will now reopen the 24hr standard messaging window. This will allow apps powering Pages to reply to people based on the context that the ref parameter provides.

### Rate Limiting

*This change applies to v4.0+ and will apply to all versions on October 29, 2019.*

Page [rate limiting](https://developers.facebook.com/docs/messenger-platform/send-messages/#limits) is now tied to the number of people a Page can send messages to.

### Deprecations

*The following features and endpoints are deprecated on v4.0+.*

* `POST` [`/me/message_creatives`](https://developers.facebook.com/docs/messenger-platform/send-messages/broadcast-messages/)
* `POST` [`/me/broadcast_messages`](https://developers.facebook.com/docs/messenger-platform/send-messages/broadcast-messages/)
* `POST` [`/me/broadcast_reach_estimations`](https://developers.facebook.com/docs/messenger-platform/send-messages/broadcast-messages/estimate-reach/)
* [Open Graph Template](https://developers.facebook.com/docs/messenger-platform/send-messages/template/open-graph/)
* [Vertical List Template](https://developers.facebook.com/docs/messenger-platform/send-messages/template/list/)

*The following features are deprecated on v4.0+ and will be removed from all versions on October 29th, 2019.*

* [Location Quick Reply Button](https://developers.facebook.com/docs/messenger-platform/send-messages/quick-replies/#locations)
* [Messenger Share Button](https://developers.facebook.com/docs/messenger-platform/reference/buttons/share/)
* [Messenger Codes API](https://developers.facebook.com/docs/messenger-platform/discovery/messenger-codes/)

## Pages API

### Instagram Endpoint Permissions

*This change applies to v4.0+ and will apply to all versions on October 29, 2019.*

For an app to access the pages associated with an Instagram User or media owner, one of the following permissions is now required:

* [ads\_management](/docs/apps/review/login-permissions#ads-management)
* [ads\_read](/docs/apps/review/login-permissions#ads-read)
* [instagram\_basic](/docs/apps/review/login-permissions#instagram-basic)
* [manage\_pages](/docs/apps/review/login-permissions#manage-pages)

Affected endpoints include but are not limited to:

* `GET /{page-id}/instagram_accounts`
* `GET /{page-id}/page_backed_instagram_accounts`

### Deprecations

*This change applies to v4.0+ and will apply to all versions on October 29, 2019.*

The following endpoint is deprecated:

* [`POST /{page-id}/roles`](/docs/graph-api/reference/page/roles)

## Page Public Content Access

*This change applies to all versions.*

Apps temporarily approved for [Page Public Content Access](/docs/apps/review/feature#reference-PAGES_ACCESS) must undergo [App Review](/docs/apps/review) in order to continue using the feature.

## Versioning

*This change affects v4.0+.*

Starting with v4.0 we will use a whole number versioning system for Graph API releases.

## Webhooks

### Page Feed

*This change applies to v4.0+.*

The `like` webhooks field for Page Feed has been deprecated. Page likes will now be delivered by the `reactions` webhooks field.

### Performance Improvements

*This change applies to all versions.*

We have implemented a number of backend changes which should significantly improve the speed and success rate of webhooks notifications, and reduce the number of duplicate notifications you may receive.

## Marketing API

**Released** July 29, 2019 | **Available Until** March 31, 2020

### New Features

In August of 2019 we will introduce Business Asset Groups. Large advertisers or agencies with large numbers of assets and users can efficiently manage their businesses with this API. Advertisers can logically group assets and users, which enables them to assign permissions at scale. See [Business Asset Groups](/docs/marketing-api/businessmanager/assets).

We will have these new `GET`, `POST` and `DELETE` endpoints:

### Business Asset Groups

* `GET /{business_ID}/business_asset_groups`
* `GET /{business_scoped_user_ID}/business_asset_groups`

### Users

* `GET /{business_asset_group_ID}/assigned_users`
* `POST /{business_asset_group_ID}/assigned_users`
* `DELETE /{business_asset_group_ID}/assigned_users`

### Pages

* `GET /{business_asset_group_ID}/contained_pages`
* `POST /{business_asset_group_ID}/contained_pages`
* `DELETE /{business_asset_group_ID}/contained_pages`

### Ad Accounts

* `GET /{business_asset_group_ID}/contained_adaccounts`
* `POST /{business_asset_group_ID}/contained_adaccounts`
* `DELETE /{business_asset_group_ID}/contained_adaccounts`

### Product Catalogs

* `GET /{business_asset_group_ID}/contained_product_catalogs`
* `POST /{business_asset_group_ID}/contained_product_catalogs`
* `DELETE /{business_asset_group_ID}/contained_product_catalogs`

### Instagram Accounts

* `GET /{business_asset_group_ID}/contained_instagram_accounts`
* `POST /{business_asset_group_ID}/contained_instagram_accounts`
* `DELETE /{business_asset_group_ID}/contained_instagram_accounts`

### Pixels

* `GET /{business_asset_group_ID}/contained_pixels`
* `POST /{business_asset_group_ID}/contained_pixels`
* `DELETE /{business_asset_group_ID}/contained_pixels`

### Offline Conversion Data

* `GET /{business_asset_group_ID}/contained_offline_conversion_data_sets`
* `POST /{business_asset_group_ID}/contained_offline_conversion_data_sets`
* `DELETE /{business_asset_group_ID}/contained_offline_conversion_data_sets`

### Apps

* `GET /{business_asset_group_ID}/contained_applications`
* `POST /{business_asset_group_ID}/contained_applications`
* `DELETE /{business_asset_group_ID}/contained_applications`

### Custom Conversions

* `GET /{business_asset_group_ID}/contained_custom_conversions`
* `POST /{business_asset_group_ID}/contained_custom_conversions`
* `DELETE /{business_asset_group_ID}/contained_custom_conversions`

### Post-Processing for Ad Creation and Edits

In the past, ads buying could cause system timeout, out of memory errors or delays. To scale the system, we decoupled logic that requires significant computation and that causes transient errors to an separate workflow called *post-processing*. Now when you create or edits ads, it is more resilient to transient errors.

To represent a post processing phase after a request is received, we introduce a new ads run status `IN_PROCESS` in Marketing API 4.0. This new status applies to:

* `{campaign_ID}`,
* `{ad_set_ID}`,
* `{ad_ID}` and
* `{ad_creative_ID}`.

For more information, see [Using the API, Post-Processing](/docs/marketing-api/using-the-api#post).

### New Run Status

We added a new run status, `IN_PROCESS` which applies to ad campaigns, ad sets, ads and ad creatives. The status means Facebook is processing the ad object.

* Once we finish, the ad object can be `ACTIVE` or `PAUSED` for campaigns, ad sets, or ad creatives, or
* `PENDING_REVIEW` for ads. If we find any errors during processing, we set the ad to `WITH_ISSUES`.

### New Breakdown

We added a new breakdown in Facebook Ads Insights API. You can now group insights data by mobile web and mobile app. The old breakdown showed all mobile data together irrespective of whether it came from mobile web or mobile app traffic. The impacted endpoints are:

* `GET {adaccount_ID}/insights`,
* `GET {campaign_ID}/insights`,
* `GET {adset_ID}/insights`,
* `GET {ad_ID}/insights`,
* `POST {adaccount_ID}/insights`,
* `POST {campaign_ID}/insights`,
* `POST {adset_ID}/insights`,
* `POST {ad_ID}/insights`.

### New Error in `issues_info`

Introduced a new error type to issues\_info. The error type can be *soft* or *hard*. Hard errors block delivery and we set your ad to `WITH_ISSUES`. Soft errors do not block ads delivery. Ad objects with this new error can be in any non-deleted ad status. The impacted endpoints are:

* `GET {ad_creative_ID}?fields=issues_info`,
* `GET {ad_campaign_ID}?fields=issues_info`,
* `GET {adset_ID}?fields=issues_info`, and
* `GET {ad_ID}?fields=issues_info`.

### Breaking Changes

### Ads Management

* Updated the the rate limit for several areas under Marketing API. This includes:

  + **Lead Ads** - Updated the the rate limit on Lead Ads API for retrieving lead data. The rate limit is 200 \* 24 \* the number of leads created for a Facebook Page in the past 30 days. This applies to v4.0 and above. See [Lead Ads](/docs/marketing-api/guides/lead-ads/retrieving).
  + `ads_archive` - Any app can retrieve in a continuous 24-hour period: 45500 \* 24 items. This applies to `ads_archive`.
  + **Insights API** - You can retrieve, for each ad account, in a one-hour time period:

    - Standard Tier Apps: 190000 items + 400 \* Number of Active ads - 0.001 \* User Errors.
    - Dev Tier Apps: 60 items + 400 \* Number of Active ads - 0.001 \* User Errors.
  + `ads_management` - You can retrieve for each ad account in a one-hour time period:

    - Standard Tier Apps: 100000 + 40 \* Number of Active ads.
    - Dev Tier Apps: 300 + 40 \* Number of Active ads.
  + `custom_audience` - Per each ad account in a one-hour time period:

    - Standard Tier Apps: Minimum of 190000 + 40 \* Number of Active custom audiences. Maximum of 700000.
    - Dev Tier Apps: Minimum of 5000 + 40 \* Number of Active custom audiences. Maximum of 700000.
* Updated the privacy policies for Instagram user and media data. To access Instagram users or media your app needs `instagram_basic`, `ads_read`, `ads_management` or `manage_pages` permissions for the ad account associated with the user or media. The affected endpoints include, but are not limited to:

  + `POST {ad_account_ID}/adcreatives`,
  + `POST {ad_account_ID}/ads`,
  + `GET {ad_creative_ID}`,
  + `GET {ad_ID}`,
  + `GET {ad_ID}`, and
  + `GET {ad_account_ID}/instagram_accounts`.

  Beyond Marketing API, this also impacts the Pages API and APIs to access Instagram users, see [Graph API Changelog, 4.0](/docs/graph-api/changelog/version4.0).
* Renamed *suggested videos* in the API `video_feeds`. This impacts `POST {ad-account_ID}/adsets`.
* Deprecated `GET` for `best_creative`. This impacts GET `{adset_ID}?fields=best_creative`.
* Renamed the campaign optimization goal `REPLIES` to `CONVERSATIONS`. This impacts `POST {ad_account_ID}/adsets`.
* Renamed the campaign optimization goal `REPLIES` to `CONVERSATIONS`. This impacts `POST {ad_account_ID}/adsets`.
* Deprecated `POST` or `DELETE` of `/users` on ad accounts. This impacts these endpoints:

  + `POST /{ad_account_ID}/users`
  + `DELETE /{ad_account_ID}/users`

* Changed the ad account level rate limit to better reflect the volume of API calls. We now compute the rate limit quota based on your Marketing API access tier and the business owning your app. This change applies to all Marketing API endpoints, such as:

  + `GET {ad_account_ID}`
  + `GET {ad_campaign_ID}`
  + `GET {ad_set_ID}`
  + `GET {ad_ID}`
  + `GET {ad_account_ID}/customaudiences`
  + `POST {ad_account_ID}/campaigns`
  + `POST {custom_audience_id}`

  For more information, see [Rate Limiting](/docs/graph-api/overview/rate-limiting).

### Business Management

* We now require `business_management` permission to access the `business` field on ad accounts and product catalogs. You can read this field to determine if you have permissions to the account or catalog through a particular business. This change applies to all versions on October 29th, 2019. This impacts:

  + `GET /{user_ID}/adaccounts`
  + `GET /{user_ID}/productcatalogs`
* Deprecated the ad monetization property `userpermissions` edge. This impacts:

  + `GET {ad_monetization_property_ID}/userpermissions`
  + `POST {ad_monetization_property_ID}/userpermissions`
  + `DELETE {ad_monetization_property_ID}/userpermissions`
* Deprecated the offline conversion data set `userpermissions` edge. This impacts:

  + `GET {offline_conversion_data_set_ID}/userpermissions`
  + `POST {offline_conversion_data_set_ID}/userpermissions`
  + `DELETE {offline_conversion_data_set_ID}/userpermissions`
* We no longer show individual user Facebook IDs for people who are business admins when you call `GET {ad_account_ID}/users`. To show business admins, use `GET{ad_account_ID/assigned_users}`.
* Deprecated the `{app_ID}/userpermissions` edge. This impacts `POST {app_ID}/userpermissions`.

### Ads Insights

Deprecated `video_avg_percent_watched_actions` from the Insights API. This impacts:

* `GET {adaccount_ID}/insights`,
* `GET {campaign_ID}/insights`,
* `GET {adset_ID}/insights`,
* `GET {ad_ID}/insights`,
* `POST {adaccount_ID}/insights`,
* `POST {campaign_ID}/insights`,
* `POST {adset_ID}/insights`,
* `POST {ad_ID}/insights`.

### Upgrading to Marketing API v4.0

A few reminders for our developer community:

* Developers should specify `/v4.0/` in your URLs when you call the API.
* To see details of all changes in v4.0, see the [Graph API v4.0 Changelog](https://developers.facebook.com/docs/graph-api/changelog/version4.0).
* SDK developers should view our latest [Java SDK](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Ffacebook%2Ffacebook-java-business-sdk&h=AUBZnj3QnwILPqvB9TmxonTFnU1iTK5ddoR3xO8ZHHzUfGcKKK1xOGc7wACGCXe5eAQ4GN2fzMRHbveM34Hr7ECs1tC4Db_LaShP_plMCNofERRoqX5bF9YSRnNtfBti7-7vruIW_VJ87gZ0), [PHP SDK](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Ffacebook%2Ffacebook-php-business-sdk&h=AUCsT7uXPRfJq-_10NvcujgK6t-VMXjaIvQxiYJwd7JvZ9FH4xCET-jzHqdBEXvU0e76vyWTyYTngaFEinPQcPihQAEBasALQvTSrKChJs36Vi8v4s8nXdr75QKlB15kvsWXxwVq7ZlbIl_w), [Python SDK](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Ffacebook%2Ffacebook-python-business-sdk&h=AUDuVAI8CcOvFMbHl7joCofWLmRLu4go-OIgLc4xnzBCExPfOuSBPPJMmGUCro3wqakRIRGQqyWEaxv-0TkxbkEBdn7BVO6TGsYkJv8wSXdf77iAGnTwBvsdNa6_ladKHAqVV5irFwVEDUJ9), or [Ruby SDK](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Ffacebook%2Ffacebook-ruby-business-sdk&h=AUAtY_V6_eixOa3u2xeGAUz0VTWweprgPxxxWA-w4wDfHVV9b0Fkc4_Ziul5AiX-wqfSouLu9MrSJw7ZT8mZWZOh6GLiW-p8oOy8rsZ4phrcYFOxt9RlfI-6zejqKdMR9Jaap8YD7yMbVpNO).

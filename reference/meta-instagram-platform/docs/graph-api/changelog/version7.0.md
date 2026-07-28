# Version 7.0

## Graph API

**Released** May 5, 2020 | **Available until** August 4, 2022 | [Blog post](/blog/post/2020/05/05/introducing-graph-api-v7-marketing-api-v7/)

### Facebook Business Extension, v2

*This change applies to all versions.*

Two new fields have been added to the Facebook Business Extension, v2.

* **Ad Account ID** (`ad_account_id`) — Represents the ad account ID selected by the user inside FBE. This ad account can be used to manage ads if your app has `ads_management` permissions.
* **Catalog ID** (`catalog_id`) — The catalog ID selected by the user inside FBE. This ID can be used to manage their product catalog.

### Instagram

#### Hashtag Search

*This change applies to v7.0+.*

You can now request the `timestamp` field on [IG Media](/docs/instagram-api/reference/ig-media/) returned by [`GET /{ig-hashtag-id}/top_media`](/docs/instagram-api/reference/ig-hashtag/top-media#reading) and [`GET /{ig-hashtag-id}/recent_media`](/docs/instagram-api/reference/ig-hashtag/recent-media#reading) [Hashtag Search](/docs/instagram-api/guides/hashtag-search) queries. For example: `GET /{ig-hashtag-id}/top_media?fields=timestamp`.

### Messenger

#### Customer Chat Plugin

*This change applies to v7.0+ and will apply to all versions on Nov 2, 2020.*

When a new conversation is started or an existing conversation continued via the [Customer Chat Plugin](/docs/messenger-platform/discovery/customer-chat-plugin), the initial `messaging_postbacks` and `messaging_referrals` webhook notifications will contain an anonymous `user_ref` ID for the user instead of the user's [Page-Scoped ID](/docs/pages/overview#psids) (PSID). Once the user sends a message, subsequent webhook notifications will contain the user's PSID.

#### Page Messenger Profiles

*This change applies to v7.0+.*

The `home_url` property on [Page Messenger Profiles](/docs/messenger-platform/reference/messenger-profile-api) has been deprecated for all operations (`GET`, `POST`, and `DELETE`).

### Open Graph

#### Deprecations

*This change applies to v7.0 and will apply to all versions on Aug 3, 2020.*

* [`GET /{open-graph-action-type-id}`](/docs/graph-api/reference/open-graph-action-type/#Reading)
* `POST /{user-id}/{open-graph-action-type-id}`

### Pages

#### App-Scoped User IDs

*These changes apply to v7.0+ and will apply to all version on May 5, 2021.*

On May 1st, 2018, the Pages API began returning [Page-Scoped User IDs (PSID) instead of App-Scoped User IDs (ASID)](/docs/pages/overview#psids) for all new apps. Apps created before this date [continued to receive ASIDs](/docs/pages/support/psid-api#overview) unless they opted-in to receive PSIDs. All apps will now receive PSIDs from the Pages API.

The [Page-Scoped ID API](/docs/pages/support/psid-api) allows you to map ASIDs to their PSID equivalents. The API is deprecated in v7.0+, but can be used with older versions until May 5th, 2021.

#### Deprecations

*These changes apply to v7.0+ and will apply to all versions on Aug 3, 2020.*

The following endpoints are deprecated:

* [`GET /{page-id}/featured_videos_collection`](/docs/graph-api/reference/page/featured_videos_collection/)
* [`POST /{page-id}/albums`](/docs/graph-api/reference/page/albums/)

#### Permissions

The [`manage_pages`](/docs/permissions/reference/manage_pages) permission has been deprecated and replaced with 4 new permissions:

* [`pages_manage_ads`](/docs/permissions/reference/pages_manage_ads)
* [`pages_manage_metadata`](/docs/permissions/reference/pages_manage_metadata)
* [`pages_read_engagement`](/docs/permissions/reference/pages_read_engagement)
* [`pages_read_user_content`](/docs/permissions/reference/pages_read_user_content)

The [`publish_pages`](/docs/permissions/reference/publish_pages) permission has been deprecated and replaced with 2 new permissions:

* [`pages_manage_posts`](/docs/permissions/reference/pages_manage_posts)
* [`pages_manage_engagement`](/docs/permissions/reference/pages_manage_engagement)

Apps that have already been approved for [`manage_pages`](/docs/permissions/reference/manage_pages) or [`publish_pages`](/docs/permissions/reference/publish_pages), or both, will be migrated to the new permissions by June 1, 2020.

For apps that have been submitted but not yet reviewed for [`manage_pages`](/docs/permissions/reference/manage_pages) or [`publish_pages`](/docs/permissions/reference/publish_pages), or both, the review process will continue as normal. Once approved, apps will be migrated to the new permissions by June 1, 2020.

To apply, or resubmit, for Page permissions before June 1, 2020, select the permissions you see in your app dashboard, either [`manage_pages`](/docs/permissions/reference/manage_pages) or [`publish_pages`](/docs/permissions/reference/publish_pages), or both, or the new permissions. Your app will automatically be migrated to the new permissions by June 1, 2020, if necessary.

After June 1, 2020, [`manage_pages`](/docs/permissions/reference/manage_pages) and [`publish_pages`](/docs/permissions/reference/publish_pages) will no longer be available in the **App Review** > **Permissions and Features** selection in the App Dashboard.

The [`manage_pages`](/docs/permissions/reference/manage_pages) and [`publish_pages`](/docs/permissions/reference/publish_pages) permissions will be fully deprecated in May of 2022. Changes to your code must be applied before this date.

### SDKs

Please visit the [iOS SDK Changelog](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Ffacebook%2Ffacebook-ios-sdk%2Fblob%2Fmaster%2FCHANGELOG.md%3Ffbclid%3DIwAR026Yf5fUsITVD9v87xiyaG5f65oAkY5i-_PlvDooenfMI78hMrSsm5gHA&h=AUDlGNtKuIEggNC-S_jp5dG8pMzpMGkwcElx2OGDj5BnZot2oex91HUr6QgDB1jhSJvjByX0_XugXtwvBWvD656Q-Bmg9zdH06U6OBupcpy5Q8XQHkGIL0rr6wu598JSdwlKz8QRvA2pkzm5) and the [Android SDK Changelog](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Ffacebook%2Ffacebook-android-sdk%2Fblob%2Fmaster%2FCHANGELOG.md%3Ffbclid%3DIwAR2qA09RHTxdRurE_8kSBjOqC-Chm1UsJwR-ehMn7mAomsjCdFeEasXjYcA&h=AUDt9VYRFgIJH0EkhJvy9VbeNaE_nZsJGPassoV2F6rpZQrHd7Ki0sgAQ239xMxeFAKYu84mKwU9XeC0VHNlJ8kwC7E5IcJRlM-etG5nlp599v6rvY1Os84n18Bx0o8Eys6X4QOsQ2ZBPwh1) to learn of important upcoming changes to these SDKs.

### User

#### Deprecations

*These changes apply to v7.0+ and will apply to all versions on Aug 3, 2020.*

The following endpoints are deprecated:

* [`GET /{user-id}/books`](/docs/graph-api/reference/user/books/)
* [`GET /{user-id}/games`](/docs/graph-api/reference/user/games/)
* [`GET /{user-id}/movies`](/docs/graph-api/reference/user/movies/)
* [`GET /{user-id}/television`](/docs/graph-api/reference/user/television/)

## Marketing API

**Released** May 5, 2020 | **Available until** March 3, 2021 | [Blog post](/blog/post/2020/05/05/introducing-graph-api-v7-marketing-api-v7/)

### Ad Campaigns

#### Campaign Budget Optimization

*This change applies to v7.0+.*

For a specific ad campaign, you can no longer set both `lifetime_budget` and `spend_cap` at the same time. You can only select `lifetime_budget`.

A campaign lifetime budget is spread out over the course of your campaign. When you use `lifetime_budget` at the campaign level, the spend cap information is already included. Therefore, there is no reason to add a second spend cap.

You can continue using `spend_cap` for campaigns not using [Campaign Budget Optimization](/docs/marketing-api/bidding/guides/campaign-budget-optimization).

#### Special Ad Category

*This change applies to v7.0+.*

The `special_ad_category` parameter on the [`POST /act_<AD_ACCOUNT_ID>/campaigns`](/docs/marketing-api/reference/ad-account/campaigns/#Creating) endpoint has been deprecated and replaced with a new `special_ad_categories` parameter.

The new `special_ad_categories` parameter is **required** and accepts an array. If you get the `special_ad_category` parameter, it will still return a string, but you should use `GET /{campaign-id}?fields=special_ad_categories` to get an array back.

For details, see [Special Ad Category](https://developers.facebook.com/docs/marketing-api/audiences/special-ad-category/).

Learn more about [Special Ad Categories, Ads Help Center](https://www.facebook.com/business/help/298000447747885?helpref=faq_content).

#### Deprecations

*This change applies to v7.0+.*

The `budget_rebalance_flag` parameter has been deprecated. We recommend that you use [Campaign Budget Optimization](/docs/marketing-api/bidding/guides/campaign-budget-optimization) instead.

### Atlas Ad Campaigns

#### Deprecations

*This change applies to v7.0+.*

* `GET /{atlas-ad-campaign-id}/cumulative_edited_date`

### Product Catalog

#### Deprecations

*This change applies to v7.0+.*

The `cpas_parent_catalog_settings` parameter on the [`POST /PRODUCT_CATALOG_ID`](/docs/marketing-api/reference/product-catalog) edge is deprecated for third-party apps.

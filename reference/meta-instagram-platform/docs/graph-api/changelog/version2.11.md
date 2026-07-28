# Version 2.11

[Graph API](#gapi) | [Marketing API](#mapi)

Changelog entries are categorized in the following way:

* **New Features** — New products or services, including new nodes, edges, and fields.
* **Changes** — Changes to existing products or services (not including **Deprecations**).
* **Deprecations** — Existing products or services that are being removed.
* **90-Day Breaking Changes** — Changes and deprecations that will take effect 90 days after the version release date.

**New Features**, **Changes**, and **Deprecations** only affect this version. **90-Day Breaking Changes** affect all versions.

[Breaking Changes](/docs/graph-api/changelog/breaking-changes) are not included here since they are not tied to specific releases.

---

## Graph API

**Released** November 7, 2017 | **Available until** January 28, 2020 | [Blog Post](/blog/post/2017/11/07/graphapi-v2.11/)

* [New Features](#gapi-new)
* [Changes](#gapi-change)
* [Deprecations](#gapi-deprecate)
* [90-Day Breaking Changes](#gapi-90)

---

### New Features

* [Pages](#gapi-new-pages)

#### Pages

* **@Mentions** — Pages can publicly @mention Users who have interacted with Posts by using `POST /comment_id/comments?message=hello @[userid]`. Pages can only @mention Users who have authored or commented on Posts.

* **[`/page/feed`](/docs/graph-api/reference/v2.11/page/feed)** — The following `link` subfields are no longer deprecated for links owned by the posting page. To verify link ownership use the `ownership_permissions{can_customize_link_posts}` field on the `url` node. This action requires a valid Page access token. `caption` remains fully deprecated.

  + `description`
  + `name`
  + `picture`
  + `thumbnail`

---

### Changes

* [Events](#gapi-change-events)
* [General](#gapi-change-general)
* [Pages](#gapi-change-pages)
* [Webhooks](#gapi-change-webhooks)

#### Events

* **`/event/videos`** — This edge has been removed.

#### General

* **HTTPS** — We have enabled the `includeSubdomains` HSTS directive on facebook.com. This forces web browsers to use HTTPS when making any requests to facebook.com or any of its subdomains. This should not adversely affect Graph API requests made by any of your apps.

#### Pages

* **`/page`** — The following edges now require a Page access token for specific operations:

  + `GET /page/agencies`
  + `GET /page/canvases`
  + `GET /page/instagram_accounts`
  + `GET /page/leadgen_forms`
  + `GET /page/page_backed_instagram_accounts`
  + `GET /page/promotable_posts`
  + `GET /page/userpermissions`
  + `POST /page/agencies`
  + `POST /page/page_backed_instagram_accounts`
  + `POST /page/userpermissions`

#### Webhooks

* **Page Topic** — `sender_name` and `sender_id` have been replaced with a single `from` property in `feed` subscriptions.

---

### Deprecations

* [Pages](#gapi-deprecate-pages)
* [Webhooks](#gapi-deprecate-webhooks)

#### Pages

* **Conversations API** — The `thread_key` and `thread_id` fields are deprecated for `GET` operations on the `/page/conversations` edge and for the Webhooks Page topic's `messages` field.

#### Webhooks

* **User Topic** — The following fields have been deprecated. Use their `_https` equivalents instead.

  + `pic`
  + `pic_big`
  + `pic_small`
  + `pic_square`
  + `picture`

---

### 90-Day Breaking Changes

* [App Links](#gapi-90-app-links)
* [Groups](#gapi-90-groups)
* [Messenger Platform](#gapi-90-messenger-platform)
* [Pages](#gapi-90-pages)

#### App Links

* **Mobile Hosting API** — `POST` operations for the `/app/app_link_hosts` edge will be deprecated and the [web-based App Links tool](/quickstarts/?platform=app-links-host) will be removed. `GET` operations on existing App Links will continue working normally.

#### Groups

* **`/group/videos`** — This edge now requires a User access token with `user_managed_groups` or `user_groups` permissions to return video information.

#### Messenger Platform

* **Built-In NLP** — If you have enabled Built-In NLP and use the API to subscribe Pages to your app, you will now have to [manually enable NLP](/docs/messenger-platform/built-in-nlp#enabling_nlp_graph_api) for each newly subscribed Page by using the `/page/nlp_configs` edge.

#### Pages

* **`/page/*`** — User information will not be included in `GET` responses for any objects owned by (on) a Page unless the request is made with a Page access token. This affects all nodes and edges that return data for objects owned by a Page.
* **`/page/insights`** — This edge will require a Page access token of the page in question for all metrics.

* **`/page/tabs`** — Creating [custom tabs](/docs/pages/tabs) with `POST` operations will only be available to Pages with 2000 or more fans, or pages managed by apps that are on the allow list. Existing custom tabs will be unaffected.

* **`/page/tagged`** — This edge will require a Page access token.

## Marketing API

**Released** November 7, 2017 | **Available Until** Aug 7, 2018 | [Blog Post](/ads/blog/post/2017/11/07/marketing-api-v211/)

* [New Features](#mapi-new)
* [Breaking Changes](#mapi-break)
* [Deprecations](#mapi-deprecate)
* [Immediate Deprecations](#imm-deprecate)

---

### New Features

#### Business Manager API Redesign

We now have a new relationship which represents clients and agencies. In the past we also had no `user`; we handled all access and invitations to a business and it's assets through `bid/userpermissions` which caused performance issues. Highlights of the new API include:

* **Business-scoped Users** - The new user is tied to a particular business and has permissions scoped to this business. Users can manage their profile, permissions, and asset access that is associated with that business.
* **Invitations** - Invite people to access a business through new endpoints. Check and update the status of user invitations at these endpoints.
* **Asset Categories** - Split different types of assets into categories and provide separate endpoints for each category. This makes it easier to paginate results when you read assets. It also reduce performance issues if you manage thousands of assets for a business. For the redesign we added several new endpoints.

To access users on business:

* `BUSINESS_ID/business_users`
* `BUSINESS_ID/system_users`
* `BUSINESS_ID/pending_users`

To access assets assigned to users:

* `BUSINESS_USER_ID/assigned_pages`
* `BUSINESS_USER_ID/assigned_ad_accounts`
* `BUSINESS_USER_ID/assigned_product_catalogs`
* `SYSTEM_USER_ID/assigned_pages`
* `SYSTEM_USER_ID/assigned_ad_accounts`
* `SYSTEM_USER_ID/assigned_product_catalogs`
* `PENDING_USER_ID/assigned_pages`
* `PENDING_USER_ID/assigned_ad_accounts`
* `PENDING_USER_ID/assigned_product_catalogs`

To access business pages:

* `BUSINESS_ID/owned_pages` - To get a list of Pages the business owns
* `BUSINESS_ID/client_pages` - To get a list of Pages of the clients of the business
* `BUSINESS_ID/pending_owned_pages` - To get a list of Pages the business owns that are pending approval
* `BUSINESS_ID/pending_client_pages` - To get a list of Pages belonging to clients of a business that are pending approval

To access business ad accounts:

* `BUSINESS_ID/owned_ad_accounts` - To get a list of ad accounts the business owns
* `BUSINESS_ID/client_ad_accounts` - To get a list of ad accounts of the clients of the business
* `BUSINESS_ID/pending_owned_ad_accounts` - To get a list of ad accounts the business owns that are pending approval
* `BUSINESS_ID/pending_client_ad_accounts` - To get a list of ad accounts of the clients of the business that are pending approval

To access business product catalogs

* `BUSINESS_ID/owned_product_catalogs` - To get a list of product catalogs the business owns
* `BUSINESS_ID/client_product_catalogs` - To get a list of product catalogs belonging to clients of the business

To access business apps:

* `BUSINESS_ID/owned_apps` - To get a list of apps the business owns
* `BUSINESS_ID/client_apps` - To get a list of apps of the clients of the business
* `BUSINESS_ID/pending_client_apps` - To get a list of apps belonging to clients of a business that are pending approval

For more information, see [Business Manager, API](/docs/marketing-api/business-manager-api), [Business Manager, System User](/docs/marketing-api/businessmanager/systemuser), [Business Asset Management API](/docs/marketing-api/businessmanager), and [Business Manager API, Best Practices](/docs/marketing-api/businessmanager/bestpractice).

#### Carousel Ads, Real-time Location

You can now create a carousel ad with an attachment that shows a real-time location. Added the options `type=REALTIME` and `location_source_id = PAGE_ID` in `place_data` for `AD_CREATIVE_ID/object_story_spec`. This is available at `object_story_spec` field in:

* `POST /AD_ACCOUNT_ID/adcreatives`
* `GET CREATIVE_ID`

#### Store Visits, Target Geographical Locations

You can now target geographic areas beyond a radius around a store location. We added `geo_locations` parameter in the `targeting_specs` field when you create an ad set with store visits as your objective. **Under limited availability, see your Facebook Representative to access.** See [Store Visits Objective](/docs/marketing-api/guides/dynamic-ad/store-visits)

* `POST AD_ACCOUNT_ID/adsets` has the new option.
* Supports all geographical areas in [Targeting Specs, Locations](/docs/marketing-api/targeting-specs#location) except targeting by `country_groups` and targeting the `travel_in` location type.
* Creating ads with `STORE_VISITS` objective available on a limited basis, see [Store Visits](/docs/marketing-api/guides/dynamic-ad/store-visits#dla_create_set)

#### Ad Set, Destination Types

This reflects the type of destination an ad links to; in other words, where someone goes when they click on an ad or call-to-action in an ad. This provides a consistent destination type for all ads in an ad set, so that ads only contain different types of ad creative. See [Ad Set, Destination Type](/docs/marketing-api/adset/destination_type).

* Added `destination_type` for ad sets
* Available at `/ADSET_ID`

#### Key Performance Indicator

Added the new field `kpi_type` to `AD_ACCOUNT_ID/CAMPAIGN_ID` which describes the type of key performance indicator you want to track for the campaign or ad objects in the campaign. For see insights data by `kpi_type` in `kpi_results` make these calls:

* `GET CAMPAIGN_ID/insights`
* `GET ADSET_ID/insights`
* `GET AD_ID/insights`

For more information, see [Ad Campaign, Reference](/docs/marketing-api/reference/ad-campaign-group).

---

### Breaking Changes

#### Ads Management

* **Invalidate ads targeting** `right_hand_column` - Ads targeting this position with invalid creatives for `right_hand_column` on `AD_ACCOUNT_ID/adsets` returns an error. We do not allow `right_hand_column`-only placement with video, collection, or canvas ads format. For `right_hand_column`-only placement, you can only use single-image and carousel formats.
* **Changed** `GET VERSION/RF_PREDICTION_ID/pause_periods` - To return `Array` now, not `String` to enable easier handling.

#### Business Manager API

* **Renamed fields** — The `admin_system_user` field has been renamed to `admin`, and the `system_user` field has been renamed to `employee`. This affects the following edges:

  + `/{business-id}/userpermissions`
  + `/{business-id}/system_users`

---

### Deprecations

#### Ads Management

**Deprecated optimizations for** `VIDEO_VIEWS` - Campaigns with the `VIDEO_VIEWS` objective can no longer use `CLICKS`, `IMPRESSIONS`, `PAGE_ENGAGEMENT`, `POST_ENGAGEMENT`, or `REACH` as optimization goals:

* Creating ad sets with these optimization goals returns an error.
* Duplicating ad sets with the `REACH` optimization goal, automatically converts to the `VIDEO_VIEWS` optimization goal.
* Duplicating ad sets with `CLICKS`, `IMPRESSIONS`, `PAGE_ENGAGEMENT`, or `POST_ENGAGEMENT` as the optimization goal returns an error. This is because creating or duplicating an ad in an existing ad set tries to reuse any of these optimization goals.

Edges impacted by this change:

* `POST ACCOUNT_ID/adsets`
* `POST AD_ACCOUNT_ID/ads`
* `POST CAMPAIGN_ID/copies`
* `POST ADSET_ID/copies`
* `POST AD_ID/copies`

**Deprecated** `reach` - As a `optimization_goal` for the brand awareness objective. Removed for or `/adset`; it is available for ad recall optimization only. This avoids confusion for anyone using reach as a dedicated objective.

**Deprecated the optimization** `BRAND_AWARENESS` - Replaced by `AD_RECALL_LIFT`. This reflects a new, more efficient, ads delivery model. The new optimization goal supports mixed creative, such as static and video ads in the same ad set and manual bidding. `BRAND_AWARENESS` is no longer available at:

* `POST /ADSET_ID`
* `GET /ADSET_ID`
* `POST /AD_ACCOUNT_ID/adsets`

**Deprecated** `frequency_cap` - Including `lifetime_frequency_cap` and `frequency_cap_reset_period` fields on:

* `POST AD_ACCOUNT_ID/adsets`
* `GET /ADSET_ID`
* `POST /ADSET_ID`

Use `frequency_control_specs` instead.

**Deprecated cost-per-action** `POST_ENGAGEMENT` - You can no longer use `POST_ENGAGEMENT` as a `billing_event` for this objective. This better aligns ads delivery and measurement. This impacts the endpoint: `/AD_SET_ID`.

#### Ads Insights and Measurement

**Deprecated** `video_15_sec_watched_actions` on:

* `GET AD_ACCOUNT_ID/insights`
* `GET CAMPAIGN_ID/insights`
* `GET ADSET_ID/insights`
* `GET AD_ID/insights`
* `POST AD_ACCOUNT_ID/insights`
* `POST CAMPAIGN_ID/insights`
* `POST ADSET_ID/insights`
* `POST AD_ID/insights`

**Deprecated** `recurrence_value` - From Advanced Measurement API. The field was also known under Atlas API as report schedule. We replaced it with `recurrence_values`. See [Advanced Measurement, Report Schedules](/docs/marketing-api/advanced-measurement).

#### Business Management

Deprecated endpoints for the redesign of Business Manager API:

* `BUSINESS_ID/userpermissions`
* `BUSINESS_ID/business_persona`
* `business_persona_id`

Deprecated endpoints for managing your assets:

* `BUSINESS_ID/pages`
* `BUSINESS_ID/adaccounts`
* `BUSINESS_ID/product_catalogs`
* `BUSINESS_ID/apps`

To access assets, use `BUSINESS_ID/owned_ASSET` or `BUSINESS_ID/client_ASSET`

Deprecated endpoints for managing assets belonging to another business:

* `BUSINESS_ID/assigned_ad_accounts`
* `BUSINESS_ID/assigned_pages`
* `BUSINESS_ID/assigned_product_catalogs`

Instead, use `BUSINESS_USER_ID/assigned_ASSET`

### Immediate Deprecations

*These deprecations affect all API versions and will take effect on November 14, 2017.*

#### Event Ads and Link Ads

**Deprecated** creating and editing Event Ads or Link Ads that are not connected to a valid page. The following format is no longer valid and returns an error.

Signatures that are being deprecated:

* Event Ads
  + Objective: `EVENT_RESPONSES`
  + Creative fields: `body`, `object_id`
* Link Ads
  + Objective: `LINK_CLICKS`
  + Creative fields: `title`, `body`, `object_url` (`image_file` or `image_hash`)

Supported signatures

* Event Ads
  + Objective: `EVENT_RESPONSES`
  + Creative fields: `object_story_id` or `object_story_spec`
* Link Ads
  + Objective: `LINK_CLICKS`
  + Creative fields: `object_story_id` or `object_story_spec`

Existing Event and Link Ads that you created earlier continue to run, but you can't modify the ad's creative or create new ads once this change goes in effect otherwise you receive errors. See [Event and Local Ads](/docs/marketing-api/guides/event-ads) and [Ad, Reference](/docs/marketing-api/reference/adgroup/).

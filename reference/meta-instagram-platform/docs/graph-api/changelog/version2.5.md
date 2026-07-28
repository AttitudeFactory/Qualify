## Version 2.5

[Graph API](#gapi-v2-5) | [Marketing API](#mapi-v2-5)

### Graph API v2.5

**Released** October 7, 2015 | **Available until** April 12, 2018

This version expired April 12, 2018. Please use the [API Upgrade Tool](https://developers.facebook.com/tools/api_versioning/) to upgrade your apps before this date. Learn more about upgrading your apps in the [Upgrade Guide](/docs/apps/upgrading/).

### New Features

* [Pages](#gapi-new-pages)
* [Videos](#gapi-new-videos)

#### Pages

* **Permissions**

  + `GET {user_id}/accounts` now requires either `manage_pages` or `pages_show_list`; the latter is a new permission in v2.5.
  + `POST {page_id}/call_to_actions` and `POST/DELETE {call-to-action-id}` require the new permission `pages_manage_cta` that we introduce in v2.5.

* **Managing Call-to-Actions** - Pages can now manage call to actions on a Page:

  + `GET page/call_to_actions` or `GET {call-to-action-id}` to read a call to action.
  + `POST page/call_to_actions` to add a call to action to a page.
  + `POST {call-to-action-id}` to update.
  + `DELETE {call-to-action-id}` to delete a Page's call to action.

* **Place Node** - The following field has been added to the `Place` node:

  + `overall_rating` - This provides the average rating based on public reviews of a place.

#### Videos

* **Video Upload** - The following parameters have been added:

  + `slideshow_spec` - Generate slide show videos by uploading images.
  + `secret` - Published video will not appear on Facebook Newsfeed, Timeline, or Page video tabs and is not searchable. A video can be viewed and shared using a permalink only. For page users only.
  + `social_actions` - Enable or prohibit the use of Facebook social actions such as likes, comments, and sharing on an hidden video. For page users only.

* **Video Editing** - The following parameters have been added:

  + `publish_to_videos_tab` - Distribute video items publicly to the Page's Videos tab, but not News Feed or Timeline.
  + `publish_to_news_feed` - Distribute video items publicly to News Feed, Page Timeline, and a Page's Videos tab.

---

### Changes

* [Pages](#gapi-changes-pages)
* [Posts](#gapi-changes-posts)
* [Users](#gapi-changes-users)
* [Webhooks](#gapi-changes-webhooks)

#### Pages

* **Tagged Posts Endpoint** - `GET /{page-id}/tagged` will include all public posts in which the page has been tagged. A page access token with `manage_pages` permission is required.

#### Posts

* **`story_tags`** - Now returns an array, not an object.

#### Users

* **`GET /{user-id}?fields=address` returns an error** - The `address` field, which was available in previous versions and returned an empty value, will return an error as of v2.5.

#### Webhooks (Formerly Real Time Updates)

* **Automatically Disable Subscriptions** - We now automatically disable Webhooks subscriptions if the callback URL fails for 7 days straight. You can re-enable it with a `POST` request to `/subscriptions`. This change does not apply to payments subscriptions.
* **Updating Existing Subscriptions** - Existing Webhooks subscriptions may be modified via the `/subscriptions` API. `POST /subscriptions` will amend the subscription for the given topic without overwriting existing fields. You can delete specific fields from your subscription by including a fields param when calling `DELETE /subscriptions`.

---

### Deprecations

* No deprecations.

---

### 90 Day Breaking Changes

* [Pages](#gapi-90-pages)
* [Webhooks](#gapi-90-webhooks)

#### Pages

* **Page Tab Apps URI Format** - Page Tab Apps URI format `https://www.facebook.com/{vanity}?v={app_id}` will no longer work 90 days after this release. Please use `https://www.facebook.com/{vanity}?sk={app_id}` or `https://www.facebook.com/{vanity}/{app_id}`.

#### Webhooks

* **New Real Time Updates via HTTPS Only** - New subscriptions cannot be created with a non-HTTPS callback URL. This affects `User`, `Page`, `App`, and `Payment` updates.

### Marketing API V2.5

**Released** October 7, 2015 | **Available until** July 13, 2016

* [New Features](#mapi-new)
* [Changes](#mapi-change)
* [Deprecations](#mapi-deprecate)
* [90-Day Breaking Changes](#mapi-90)

---

### New Features

* [Ads](#mapi-new-ads)

#### Ads

* **Ad, Ad set, and Campaign object read path additions:**

  + `effective_status` to reflect the real Ad delivery status. For example for an active adset in a paused campaign, the `effective_status` of this adset is `CAMPAIGN_PAUSED`.
  + `configured_status` to reflect the status specified by user.

* **Insights** - The following metrics have been added:

  + `inline_link_clicks`
  + `cost_per_inline_link_click`
  + `inline_post_engagement`
  + `cost_per_inline_post_engagement`

* **Lead Ads** - Advertisers will now be able to collect contact information and other qualifiers from potential customers via a Facebook ad.

---

### Changes

* [Ad Account](#mapi-change-ads)

#### Ad Account

* **Admin Name** - Default the `name` of the first visible admin to current user if not specified.
* **Campaign** -The following objective names have changed:

  + `WEBSITE_CLICKS` to `LINK_CLICKS`
  + `WEBSITE_CONVERSIONS` to `CONVERSIONS`

* **DPA** - Enforce [Terms of Service](https://business.facebook.com/legal/product_catalog_terms/) for all Product Catalogues and Dynamic Product Ads users. Advertisers implicitly accept by creating their first catalog through [Business Manager](https://business.facebook.com/). For API developers, Terms of Service need to be accepted through BM when the product catalog is first created.
* **Local Awareness Ads**

> * Require `page_id` in `promoted_object` at the `/adset` level for Local Awareness Ads
> * No longer require `custom_locations` for location targeting, and also allow sub-national, single country targeting. Now all location types (except for country) must be within the same country.

* **Consistent naming for three-level campaign structure between API and UI**. This changes naming at endpoint, params, fields, and enum level. For the full list of changes, refer [here](/docs/marketing-api/reference/v2.5_rename).

> * Change `/adcampaign_groups` to `/campaigns`
> * Change `/adcampaigns` to `/adsets`
> * Change `/adgroups` to `/ads`
> * In the write path, change campaign\_group\_status, campaign\_status, adgroup\_status to `status`

* **Targeting**

> * Response for call to `/search?type=adgeolocation` will contain only the 'City' instead of 'City, State'
> * Change `{cpc, cpm, cpa}_{min, max, median}`, such as `cpc_min` fields in [/reachestimate](/docs/marketing-api/reachestimate/v2.5) to `bid_amount_min`, `bid_amount_median`, `bid_amount_max`. Change `bid_for` to `optimize_for`

---

### Deprecations

* **[Premium Self Serve](/docs/marketing-api/premium-via-api)**
  + The last day to book a PSS (or [homepage](/docs/marketing-api/premium-via-api)) campaign will be November 15th
  + The last day PSS (or [homepage](/docs/marketing-api/premium-via-api)) campaigns can run will be December 31st 2015.

* **Account**

> * Remove `friendly_name`

* **Adset**

> * Remove `USE_NEW_APP_CLICK`
> * Remove `buying_type`

* **Campaign**

> * Remove ability to create campaign with `Objective='NONE'`. 'NONE' is still a valid read-only objective. You can continue to edit existing campaigns.
> * Remove `REACHBLOCK`, `DEPRECATED_REACH_BLOCK` from campaign `buying_type`. For older campaigns using these two `buying_type`, the API will return `RESERVED` for `REACHBLOCK` and `FIXED_PRICE` for `DEPRECATED_REACH_BLOCK`. `FIXED_CPM` is replaced with `FIXED_PRICE`.

* **Insights**

> * Remove filter on `adgroup_id`, `campaign_id`, or `campaign_group_id`. Instead use `ad.id`, `adset.id` and `campaign.id`
> * **Note** Prior to 2.6 We decided to extend the timeline to deprecate Clicks(All) and CPC metrics until the deprecation of API v2.6. In 2.5, removed `cpc` and `clicks` fields in Insights API. Newly added related metrics include `inline_link_clicks`, `cost_per_inline_link_click`, `inline_post_engagement`, `cost_per_inline_post_engagement`. Please note clicks(all) historically counted any engagement taken within the ad unit as a click. Thus, clicks(all) won't be a simple addition of `link_clicks` and `post_engagement`. The newly added fields are available in v2.4 and v2.5.

* **Reach Estimate** - Require `optimize_for` at the `/reachestimate` endpoint.
* **Targeting**

> * Remove `want_localized_name` param for `/search?type=adgeolocation`.
> * Remove `/search?type=adcity` and `adregion`, use `/search?type=adgeolocation` instead.
> * Remove `engagement_specs` and `excluded_engagement_specs` from targeting spec. The [similar video remarketing functionality](/docs/marketing-api/guides/videoads/v2.5#remarketing) is supported through `/customaudiences` endpoint.
>
> Deprecate or make private certain targeting options:
>
> * Instead of being returned in `/search`, private categories will now be returned in `/act_{AD_ACCOUNT_ID}/broadtargetingcategories` or `/act_{AD_ACCOUNT_ID}/partnercategories`.
> * Deprecated categories will no longer be returned.
> * Updates to ad set targeting using private or deprecated categories will error. It's recommended to query the validation endpoint before updating the ad set targeting to identify which targeting options to remove.

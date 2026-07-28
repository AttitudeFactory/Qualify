## Version 2.7

[Graph API](#gapi-v2-7) | [Marketing API](#mapi-v2-7)

Changelog entries are categorized in the following way:

* **New Features** — New products or services, including new nodes, edges, and fields.
* **Changes** — Changes to existing products or services (not including **Deprecations**).
* **Deprecations** — Existing products or services that are being removed.
* **90-Day Breaking Changes** — Changes and deprecations that will take effect 90 days after the version release date.

**New Features**, **Changes**, and **Deprecations** only affect this version. **90-Day Breaking Changes** affect all versions.

[Breaking Changes](/docs/graph-api/changelog/breaking-changes) are not included here since they are not tied to specific releases.

---

### Graph API v2.7

**Released** July 13, 2016 | **Available until** October 5, 2018

* [New Features](#gapi-new-v2-7)
* [Changes](#gapi-change-v2-7)
* [Deprecations](#gapi-deprecate-v2-7)
* [90-Day Breaking Changes](#gapi-90-break-v2-7)

---

### New Features v2.7

* [Pages](#gapi-new-pages-v2-7)
* [Videos](#gapi-new-videos-v2-7)

#### Pages

* **Metrics** - The following metrics have been added. These counts include breakdowns by `organic`, `paid`, `source`, and `time` and lifetime breakdown by user demographic info.

  + `follow`
  + `unfollow`

* **Webhooks** The following field has been added:

  + `is_webhooks_subscribed` - Returns the status of a Webhooks subscription from the Page node. This field can be retrieved via `GET` or updated with a `POST` on `/{page-id}`.

#### Videos

* **Geotargeting Support** - We now support geotargeting and gating via the `targeting` param on `POST /{video-id}` and `POST /{page-id}/live_videos`. This can also be extended to supporting restrictions by excluded locales through the API.
* **`Video` Node Fields** - The following fields have been added to the `Video` node:

  + `copyright_monitoring_status`
  + `feed_type`

---

### Changes v2.7

* [Business Manager API](#gapi-change-bizmanager-v2-7)
* [Pages](#gapi-change-pages-v2-7)

#### Business Manager API

* **Permissions**: Your app now needs the `business_management` extended permission to access Business Manager. `ads_management` or the `manage_pages` permissions will no longer allow access. Facebook will migrate existing apps with these permissions to the new permission. Apps using this permission for the first time need to go through review. Please see [Permissions](/docs/facebook-login/permissions/overview) and [Business Manager API, Prerequisites](/docs/marketing-api/businessmanager/) for more information.

#### Pages

* **`GET /{page-id}/tagged`** - This edge now returns posts in which the Page has been tagged. This is a change in behavior from previous versions that only returned posts directed to the Page.
* **Page Insights** - [Page metrics insights](https://developers.facebook.com/docs/graph-api/reference/v2.9/insights) must now be explicitly specified when making Page Insights related requests. The default behavior of returning all metrics when none are specified is no longer supported.

---

### Deprecations v2.7

* No deprecations.

---

### 90-Day Breaking Changes v2.7

* [Open Graph](#gapi-90-og-v2-7)

#### Open Graph

* **`GET /{open-graph-object-id}/`** - The `url` field has been removed from this node.

### Marketing API v2.7

**Released** July 13, 2016 | **Available until** April 25, 2017

* [New Features](#mapi-new-v2-7)
* [Changes](#mapi-change-v2-7)
* [Deprecations](#mapi-deprecate-v2-7)
* [90-Day Breaking Changes](#mapi-90-v2-7)

---

### New Features v2.7

* No New Features.

---

### Changes v2.7

* [Ads](#mapi-change-ads-v2-7)
* [Daily Budget Logic](#mapi-change-budget-v2-7)
* [Insights](#mapi-change-insights-v2-7)

#### Ads

* **Placements**: We have made improvements to our design of `placement`, so that advertisers can more easily identify and select placement options that will serve them best. Instead of having `page_types` as the only dimension, advertisers can select placements across different dimensions, such as device type including `desktop` or `mobile`, publisher such as `facebook`, `instagram`, or `audience_network`, and placements of each publisher. Only Facebook has multiple placements currently. The field `page_types` will still be included in read results, but cannot be used to create or update placements in v2.7. More details in [Targeting Spec](/docs/marketing-api/targeting-specs).
* **Ad Creative**: With 2.7 `object_story_id` will be `null` for an ad creative created with an `object_story_spec`. The `effective_object_story_id` will always be the `object_story_id` regardless of `object_story_spec`. More details in [Ad Creative](/docs/marketing-api/reference/ad-creative).

#### Daily Budget Logic

* We changed the logic around ads delivery which impacts the interpretation of the daily ad budget limits. Starting with v2.7, you may be charged up to **125%** of your daily budget on certain days. For example, if your daily budget is $10.00, you may be charged up to $12.50. However, your weekly spend will NOT exceed 7 times the daily amount, or $70.00 in this example. We will prorate this for partial weeks. Learn more in our documentation for the [Ad Set Budget](/docs/marketing-api/adset/budget-limits/). Starting with v2.7, an ad set with a daily\_budget cannot be updated to have lifetime\_budget later, and vice versa.

#### Insights

* **Placement** - As a related change, on the `/insights` endpoints, we've introduced two new breakdowns options: `publisher_platform` and `platform_position`. Along with the existing `impression_device` breakdown, you can get performance metrics with these placement dimensions. See [Insights Breakdowns](/docs/marketing-api/insights/breakdowns/) for more details.
* **Insights Integer Field** - For Insights API, integer values were too big and overflowed with int32. We changed all int32 field values into numeric strings to keep them consistent with other Marketing API fields with currency values. With v2.7, numeric values in int32 are quoted in responses. In v2.5 for backwards compatibility, numeric values in int32 will be shown as a number. More details in our [Ads Insights](/docs/marketing-api/reference/ads-insights) documentation.

---

### Deprecations v2.7

* [Ad Accounts](#mapi-deprecate-ads-v2-7)

#### Ad Accounts

* `Adaccount POST`\*\* - The following has been deprecated:

  + `AD_ACCOUNT_ID/adaccount POST`
  + To update an account make a `POST` request to `/adaccount` directly.

#### 90 Day Breaking Changes v2.7

* No 90-day breaking changes.

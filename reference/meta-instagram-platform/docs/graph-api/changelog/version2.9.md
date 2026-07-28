# Version 2.9

[Graph API](#gapi-v2-9) | [Marketing API](#mapi-v2-9)

Changelog entries are categorized in the following way:

* **New Features** — New products or services, including new nodes, edges, and fields.
* **Changes** — Changes to existing products or services (not including **Deprecations**).
* **Deprecations** — Existing products or services that are being removed.
* **90-Day Breaking Changes** — Changes and deprecations that will take effect 90 days after the version release date.

**New Features**, **Changes**, and **Deprecations** only affect this version. **90-Day Breaking Changes** affect all versions.

[Breaking Changes](/docs/graph-api/changelog/breaking-changes) are not included here since they are not tied to specific releases.

---

## Graph API

**Released** April 18, 2017 | **Available until** July 18, 2019

* [New Features](#gapi-new-v2-9)
* [Changes](#gapi-changes-v2-9)
* [Deprecations](#gapi-deprecate-v2-9)
* [90-Day Breaking Changes](#gapi-90-v2-9)

---

### New Features

* [General](#gapi-new-general-v2-9)
* [Pages](#gapi-new-pages-v2-9)
* [Permissions](#gapi-new-permissions-v2-9)
* [Places Graph](#gapi-new-places-v2-9)
* [Video APIs](#gapi-new-video-v2-9)
* [Webhooks](#gapi-new-webhooks-v2-9)

#### General

* **Read After Write** - Graph API `POST` requests now support returning specified values of an object during the same request as a write, saving a round trip for clients. If a `fields` parameter is specified ([explanation of the syntax](/docs/graph-api/using-graph-api/#fieldexpansion)), the request will first do the write, then read the created or updated object, selecting fields using the `fields` parameter, as the response. Read-after-write is now enabled for all versions of the Graph API. Visit our [docs page](docs/graph-api/using-graph-api/#read-after-write) to learn more.
* **New `short_names` Field on the User Object** - The following field has been added to the `user` endpoint:

  + `short_name` - `first_name` assumes the universally friendly way to refer to a person is by their first name. However, in many cultures (especially Chinese, Japanese, Korean, Thai, Indic, and a few others), it's inappropriate to address people by their first name. The new short\_name method understands the culture-specific rules for how to address a person with a short name. So, for a viewer in the US, they'll continue to see friends in China, Japan, Korea, and India addressed by their first name, but their friends in East and South Asia will see friends with full names.

#### Pages

* **Business App Page Mapping** - The `user` node has two new edges, `ids_for_pages` and `ids_for_apps`, for de-referencing a person's ID for an app or a page. The `ids_for_pages` edge returns other IDs that person has for pages owned by the same business. Similarly, the `ids_for_apps` edge returns other IDs that person has for apps owned by the same business. See [Connecting with People Across Apps and Bots in Messenger](/docs/facebook-login/connecting-accounts).
* **Page POST Support to Add Pages to Crosspost Videos** - Approve and accept a crossposting relationships request from another page by `POST /{page_id}/crossposting_pages`.
* **Webhooks IDs Are Serialized as Strings** - Numeric IDs are converted to strings in this webhooks update.

#### Permissions

* **Granular Permissions** - This new feature gives people more control over managed object permissions. During the login step, if a permission related to pages, business, or groups is granted, the user will have the option to select which managed objects the permission applies to. This means that you might see fewer pages, businesses and groups. Users can manage the following permissions at a granular level:

  + [`business_management`](/docs/facebook-login/permissions/#reference-business_management)
  + [`manage_pages`](/docs/facebook-login/permissions/#reference-manage_pages)
  + [`pages_manage_cta`](/docs/facebook-login/permissions/#reference-pages_manage_cta)
  + [`pages_manage_instant_articles`](/docs/facebook-login/permissions/#reference-pages_manage_instant_articles)
  + [`pages_messaging`](/docs/facebook-login/permissions/#reference-pages_messaging)
  + [`pages_messaging_payments`](/docs/facebook-login/permissions/#reference-pages_messaging_payments)
  + [`pages_messaging_phone_number`](/docs/facebook-login/permissions/#reference-pages_messaging_phone_number)
  + [`pages_messaging_subscriptions`](/docs/facebook-login/permissions/#preference-ages_messaging_subscriptions)
  + [`pages_show_list`](/docs/facebook-login/permissions/#reference-pages_show_list)
  + [`publish_pages`](/docs/facebook-login/permissions/#reference-publish_pages)
  + [`read_page_mailboxes`](/docs/facebook-login/permissions/#reference-read_page_mailboxes)
  + [`user_managed_groups`](/docs/facebook-login/permissions/#reference-user_managed_groups)

#### Places Graph

* **Current Place** - The following fields have been added:

  + `GET /current_place/results` - Helps determine what place a person is currently at by using location signals. User permission is required.
  + `POST /current_place/feedback` - Allows you to provide feedback about whether they were actually there. For more information, see [Places Graph](/docs/places)

* **`GET /search?type=place`** - The following parameters have been added:

  + [`categories`](/docs/places/web/search) - Search by category.
  + [`matched_categories`](/docs/places/web/search) - Indicate which categories the resulting place matches. Must be used with `categories`.

#### Video APIs

* **Time Spent in Video Metrics for Page** - The following metrics have been added. For more information, see [Insights Metric /{object-id}/insights/{metric}](/docs/graph-api/reference/v2.8/insights).

  + `page_video_view_time`- The time spent on videos on the page.
  + `post_video_view_time_by_country_id` - The time spent on videos on the page by country.

#### Webhooks

* **Apps Can Receive Changed Values for User's Profile Updates with Webhooks Updates** - When a user changes a field, your app can receive the new value as part of the update, saving the step of checking the value. Previously, whenever a user changed one of their fields, we would notify the app of the field that changed without sending the new value.
* **Documentation** - Webhooks now has reference documentation for topics and fields you can subscribe to. This documentation is on Facebook Developers site under [Webhooks Reference](/docs/graph-api/webhooks/reference) in the [Graph API](/docs/graph-api).
* **Sample Sender Tool** - The new tool makes it easier for developers to test out the Webhooks update structure before subscribing to the topic. In the past, developers had to subscribe to a field and then try to trigger the update by making a change through Facebook. For example, an app might need to know when a user (users that installed the app and granted needed permissions) changes their profile picture. The app would subscribe to the profile picture field in the Webhooks framework. However, to test how this works, you had to change the profile picture on some user that had installed the app to see the structure of the update we send. The sample sender tool allows apps to test the update structure without having to make an unnecessary change. You can find the sample sender tool in the webhooks section of your app's dashboard.
* **Versioning** - Webhooks versions are now the same as Graph API. Any existing Webhooks subscriptions will be running on the oldest supported version of the app. Previously, Webhooks subscriptions didn't support versioning. The only way to make changes was by making breaking changes. For more information on Webhooks versions, see [Versioning](/docs/apps/versions).

---

### Changes

* [General](#gapi-changes-general-v2-9)
* [Pages](#gapi-changes-pages-v2-9)
* [Posts](#gapi-changes-posts-v2-9)
* [Videos API](#gapi-changes-videos-v2-9)
* [Webhooks](#gapi-changes-webhooks-v2-9)

#### General

* The Batch API returns an error rather than a null response for aborted request items in the Batch API. For more information, see [Graph API, Making Batch Requests](/docs/graph-api/making-multiple-requests).
* **`GET /{url}/share`** - The `share` endpoint has been removed and replaced with:

  + `engagement` field with subfields:
    - `comment_count`
    - `comment_plugin_count`
    - `reaction_count`
    - `share_count`

#### Pages

* **`/{page-id}/feed`** - Backdated posts are included in the `{page_id}/feed` request if the `backdated_time` of the post is within the `since` and `until` time range. The `created_time` is the actual creation time. (See [changes to Posts](#gapi-changes-posts) below.)
* [**`page-restaurant-services`**](/docs/graph-api/reference/page-restaurant-services/) - All fields now return `false` or `true` instead of `0` or `1`.

* **`overall_star_rating`** — If there are 0 or a small number of ratings, the [`overall_star_rating` field](https://developers.facebook.com/docs/graph-api/reference/page) will not be returned.

* **`GET /{post-id}`** - The following field has been added to this endpoint:
  + `promotable_id` - Previously, certain posts could not be promoted, only their contents. In such cases, the `id` field would return the contents ID, rather than the ID for the post. Posts now always return their own ID in the `id` field, and a new field, `promotable_id`, is added to the `GET {post-id}` endpoint to be used when promoting the post.

#### Posts

* Backdating a post will no longer update the post's `created_time` value. Instead, it will duplicate the original, but with `created_time` and `backdated_time` set to the new value. The original post will keep its old `created_time` value and gain the new `backdated_time` and value. Finally, `GET {post-id}/feed` will no longer return the original post, but instead will return the newly created duplicate.

#### Video API

* Expose dash preview URL for live video instead of RTMP URL.
* **`GET /{page_id}/crosspost_pending_approval_pages`** - List all the Pages your Page has sent crossposting requests, but that have not accepted yet.
* **`GET /{page_id}/crosspost_whitelisted_pages`** - List all the pages you have given crossposting permission.
* **`POST /{video_id}/allow_crossposting_for_pages = [{"page_id": {page_id}, "allow": {true/false}]`** - Allow or disallow the permission for certain Pages in your crossposting allow list to crosspost a specific video.
* **`POST /{page_id}/crossposting_pages=[{"page_id": {page_id}, "allow": false, "action": "EXPIRE_ALL_CROSSPOSTS_ON_SHARED_ASSETS"}]`** - Remove pages from your crossposting allow list and expire all previously crossposted content.
* **`POST /{page_id}/crossposting_pages=[{"page_id": {page_id}, "allow": false, "action": "NO_ACTION"}]`** - Remove pages from your crossposting allow list without affecting previously crossposted content.

#### Webhooks

* **`GET /{app-id}/subscriptions`** - This endpoint now returns versions for fields. Before Webhooks versioning was introduced, the endpoint returned only a list of subscribed fields. Now the endpoints return the list of fields with their respective versions.

---

### Deprecations

* [Messages](#gapi-deprecate-messages-v2-9)

#### Messages

* **`GET /{message-id}`** - The following field has been deprecated:
  + `subject`

* **`GET /{thread-id}`** - The following field has been deprecated:
  + `tags`

---

### 90-Day Breaking Changes

* [Links](#gapi-90-links-v2-9)
* [Video](#gapi-90-video-v2-9)
* [Webhooks](#gapi-90-webhooks-v2-9)

#### Links

* The following fields are deprecated for edges and dialogs that allow attaching links to posts:

  + `caption`
  + `description`
  + `name`
  + `picture`
  + `thumbnail`

* The edges and dialogs for which these are deprecated include:

  + `POST /{event-id}/feed`
  + `POST /{group-id}/feed`
  + `POST /{page-id}/feed`
  + `POST /{user-id}/feed`
  + `share` and `feed` dialogs

#### Video

* **Insights Edge** - All `paid` and `organic` metrics are deprecated.

#### Webhooks

* The following Webhooks fields from the user topic are deprecated:

  + `about_me`
  + `birthday_date`
  + `contact_email`
  + `current_location`
  + `education_history`
  + `hometown_location`
  + `sex`
  + `statuses`
  + `tv`
  + `work_history`

* Instead use:

  + `about`
  + `birthday`
  + `education`
  + `email`
  + `gender`
  + `hometown`
  + `location`
  + `status`
  + `television`
  + `work`

## Marketing API

**Released** April 18, 2017 | **Available until** Novembr 6, 2017

* [New Features](#mapi-new)
* [Changes](#mapi-change)
* [Deprecations](#mapi-deprecate)
* [90-Day Breaking Changes](#mapi-90)

---

### New Features

* [Ad Creative](#mapi-new-creative)
* [Dynamic Ads](#mapi-new-da)
* [Ads Manangement](#mapi-new-manage)
* [Ads Placement](#mapi-new-placement)

#### Ad Creative

* **Create Canvas campaigns on Facebook through Marketing API.** - By using sight, sound, and motion, the video format allows advertisers to effectively drive both brand and direct response objectives. See [Marketing API, Canvas Ads](/docs/marketing-api/guides/canvas-ads).

#### Dynamic Ads

* **Dynamic Ads Catalog Quality** - We are introducing new APIs to help you successfully run Dynamic Ads: Checks and Quality APIs. With Checks API you can verify that your source of signals provide enough information to deliver the right ads with Dynamic Ads. With Quality API, you can check and verify that your catalog and feed have enough information of sufficient quality to deliver Dynamic Ads. For more information, see [Dynamic Ads, Catalog and Signals Quality](/docs/marketing-api/dynamic-ad/catalog-and-signals-quality).
* **Multi-Images for Single Item** - Show multiple images of the same item in Dynamic Ads in carousel format. We now support up to 20 images from a catalog to represent a single item in the carousel format for Dynamic Ads. This enables you to show a single item such as hotel or destination with multiple images. To support this we offer new options: `force_single_link = true` and `show_multiple_images = true`. For details, see [Dynamic Ads, Ads Management, Creative Template](/docs/marketing-api/dynamic-product-ads/ads-management#adtemplate).

#### Ads Management

* **Ad Copy** - You can now duplicate your existing campaigns, ad sets, and ads using our Ad Copy API's. This way, you don't need to re-create ads from scratch each time; instead, you can duplicate ones that work & create ads template shells. See [Ad Creative, Placement, and Preview](/docs/marketing-api/buying-api/ad-units#ad-copies).
* **Estimated Daily Reach** - We have a new endpoint `/delivery_estimate` at the ad account and ad set levels. This endpoint enables you to get the bid estimates and an outcome prediction with daily reach and conversions for a given ad set. See [Targeting, Estimated Daily Reach](/docs/marketing-api/buying-api/targeting).
* **Rules Engine API** — Use the rules engine API's to manage your ads more easily, efficiently and intelligently, based on business rules that you set. The rules engine uses a push-based model, so instead of having to constantly query our API's to get up-to-date info on your ads, we proactively send you push notifications and perform your specified actions when rule conditions are met. More details about the rules engine API [here](/docs/marketing-apis/rules-api-draft).
* **Batch API** - Group requests and send them asynchronously. Group several Graph API calls into one HTTP request, and execute them asynchronously without having to block. You can also specify dependencies between related operations. Facebook processes each independent operation in parallel processes and your dependent operations sequentially. See [Asynchronous and Batch Requests, Batch API](/docs/marketing-api/asyncrequests).

#### Ads Placement

* **Effective Ad Placement** - You can specify ad placements in the target spec, however you may not have known if Facebook actually delivered your ad to all the placements. If you selected invalid placements for a given objective, Facebook did not deliver on this placement. In the past, you had to run ads and experiment to determine the actual outcome. With the `effective_` placement APIs, you can determine the actual ads placements delivered by Facebook for your selected placement and given advertising objective. Through recommendations API, you can also learn why some placements are filtered out. See [Targeting, Advanced, Effective Placement](/docs/marketing-api/targeting-specs).

---

### Changes

* [Ads Management](#mapi-change-manage)

#### Ads Management

* **Suggested Video Placement** - This was part of Feed placement for Facebook; you opted in to this placement automatically if you used to Feed placement. As of 2.9, we separate Suggested Video placement from the Feed placement so you can opt out of Suggested Video placement even if you opt in to Feed placement. For 2.8 and earlier, if you used Feed placement for Facebook, we will no longer automatically deliver your ads to Suggested Video when you opt in to Feed placement.

---

### Deprecations

* [Ads Management](#mapi-deprecate-manage)
* [Ad Creatives](#mapi-deprecate-creative)
* [Dynamic Ads](#mapi-deprecate-dynamic)
* [Insights](#mapi-deprecate-insights)
* [Signals and Targeting](#mapi-deprecate-target)

### Ads Management

* **Local Awareness Objective** - We deprecated the campaign objective `LOCAL_AWARENESS`. As of 2.9 we will not accept `LOCAL_AWARENESS` as an objective to create new campaigns. Drive local awareness for single location adsets with `REACH` campaigns. We no longer support `LOCAL_AWARENESS` for multiple locations. If you have existing campaigns with this objective, you can still read or edit it and you can create new adsets and ads in it. If you copy campaigns from existing campaigns, the type of campaign determines if you can copy it. With `LOCAL_AWARENESS` single location we copy it with `REACH` specified. For `LOCAL_AWARENESS` and multiple locations you cannot copy the campaign.

* **Mobile Ads Objectives** - To simplify our mobile ads objectives, the following objectives are deprecated:
  + `CanvasAppEngagement`, `CAE`
  + `CanvasAppInstalls`, `CAI`
  + `MobileAppInstalls`, `MAI`
  + `MobileAppEngagement`, `MAE`

* Instead use:
  + `CAE` adsets by `LINK_CLICKS` campaigns, you need to use `LINK_CLICKS` to create campaigns for CAE ads.
  + `MAE` adsets with `LINK_CLICKS` or `CONVERSIONS` objective campaigns, you need to change to `LINK_CLICKS` or `CONVERSIONS` to create campaigns for MAE ads.
  + `CAI` ad sets with `APP_INSTALLS`, you should use `APP_INSTALLS` to create campaigns for CAI ads.
  + `MAI` with `APP_INSTALLS`, you should to use `APP_INSTALLS` to create campaigns for MAI ads.

* **Mobile Ads Objectives, Compatability** - When you duplicate `CAE`, `MAE`, `CAI` and `MAI` campaigns with Marketing API or Facebook tools, we automatically translate these deprecated objectives into their 2.9 equivalents:

  + `MAI` or `CAI` campaigns convert to `APP_INSTALLS` objective.
  + `CAE` campaigns convert to `LINK_CLICKS` campaigns.
  + `MAE` campaigns convert to `LINK_LICKS` or `CONVERSIONS` campaigns based on the optimizations you provide for ad sets in the campaign. If there is any child adsets optimized for `OFFSITE_CONVERSION`, we convert your `MAE` campaign to a `CONVERSIONS` campaign, otherwise we translate your `MAE` campaign to a `LINK_CLICKS` campaign.

* **Blocked Categories** - We are deprecating some Audience Network, Instream Video, and Instant Article categories in favor of more unified categories across these placements. These categories enable you to prevent ads displaying with certain objectionable content, such as gambling, alcohol and so on. The following categories are deprecated:

  + `politics`
  + `religion`
* The following categories are available:

  + For Instant Articles and Audience Network:
    - `debated_social_issues`
    - `mature_audiences`
    - `tragedy_and_conflict`
    - `dating`
    - `gambling`
  + For Instream Videos:
    - `debated_social_issues`
    - `mature_audiences`
    - `tragedy_and_conflict`

#### Ad Creatives

* `SUPPLEMENTAL_MEDIA_ID` is deprecated from ad creatives at the ad account and ad levels. You are no longer able to read this field.
* `ACTION_SPEC` is deprecated from ad creatives. This was used with sponsored stories which we no longer support.
* `actor_image_hash`, `actor_image_url` and `actor_name` fields in ad creative are deprecated in 2.9 and 2.8. They were used with `action_spec` which we also deprecated.
* `link_title` and `link_description` in `call_to_action` from ad creatives is deprecated. To set titles and descriptions for ad creative, use `name` and `description` in `link_data`, or `title` and `link_description` in `video_data`.
* `run_status=3` - You were able to delete ad creative with this field and value. This caused confusion so we've renamed `run_status` to `status` and the value from Int to the String value `DELETED`. To delete ad creative use `status=DELETED`.
* `COVER_PHOTO_ID` from `GET` on creative endpoints `{creative_id}` and `{ad_account_id}/adcreatives` is deprecated. This was rarely used and available for internal and limited use only.
* `image_url` or `image_hash` - You can now only provide one of these in `video_data` for ad creative's `object_story_spec`. See [Ad Creative, Reference](/docs/marketing-api/reference/ad-creative).
* `OBJECT_INSTAGRAM_ID` from `GET` for creative endpoints is deprecated, including `{creative_id}` and `AD_ACCOUNT_ID/adcreatives`. This field was not intended for external use.
* `instagram_story_id` was used to fetch Instagram post IDs in ad creative in v2.8 and earlier. If you used this field when you provided ad creative, we threw an exception, but ignored this parameter and passed back results with `instagram_story_id`. If you used the response, you would get an error. To resolve this issue, we rename `instagram_story_id` to `effective_instagram_story_id` and you should not use this field to provide ad creative.

#### Dynamic Ads

* **No Identical Product Sets** - We no longer allow product sets that are identical to another product set from the same catalog. If you try to create an identical product set from the same catalog, our API will return a `FacebookApiException` with code `10803` containing the ID of the identical product set.
* `quoted_fields` in `POST /{product_feed_id}` deprecated. In v2.6 we removed `quoted_fields` under `POST /{product_feed_id/product_feeds}`. As part of additional cleanup we are now also deprecating this.
* `POST {catalog-id}/batch` endpoint endpoint now returns `STRING` as part of ongoing improvements to Dynamic Ads product catalogs.
* **Failure for Audience Updates** - If you're using Dynamic Ads and try to update an audience for these ads, your request fails with an error. To make changes, you need to delete the audience associated with your Dynamic Ads and create a new one. See [Dynamic Ads, Audiences](/docs/marketing-api/dynamic-product-ads/product-audiences) and [Custom Audiences](/docs/marketing-api/reference/custom-audience)
* `template_url_spec` replaces `template_url`. This enables you to perform click tracking and place context-specific URLs beyond Product Catalog URLs into your Ads. For example, include someone's selected check-in and check-out dates in your ad. See [Dynamic Ads, Ads Management](/docs/marketing-api/dynamic-product-ads/ads-management).

#### Signals and Targeting

* **Renaming for Event Sources** - In the past, when you created or queryed custom conversions, you used fields labeled `pixel_id`, `pixel_rule` and `pixel_aggregation_rule`. Since we are adding support for offline conversion data and custom conversion data from apps, we are relabeling the fields to express the expanded scope. These fields are now known as `event_source_id`, `rule` and `aggregation_rule`.
* **Conversion Tracking Pixel** - This was deprecated February 15, 2017. As part of this, we have removed all edges and nodes for creating, updating, reading, or referencing the Conversion Tracking Pixel for all versions of the API.
* `friends_of_connection` associated with event IDs is deprecated as an ads targeting option. This means you cannot target friends of people who accepted your Facebook event invitation.

* `delivery_estimate` Support - We made Reach Estimate changes to support the newly launched `delivery_estimate`:

  + Removed `bid_estimations` field from `/reach_estimates` endpoint and moved all of the documented functionality over to `/delivery_estimate`
  + `/AD_ID/reachestimate` has been deprecated. To access this information use `/ADSET_ID/delivery_estimate`.
  + Removed the `data` field.

#### Insights

* **`date_preset` Deprecations** - We are deprecating several `date_preset` values which we are replacing with new values. The new values are designed to be easier to use and in alignment with advertiser expectations, and will no longer include data from the current day. For example, a request made on Feb 8th and using "the last 7 days" date range preset will result in a report that encompasses Feb 1 through 11:59 p.m. on Feb 7 inclusive, and excludes Feb 8th. These values are deprecated:

  + `last_3_days`, replaced by `last_3d`
  + `last_7_days` replaced by `last_7d`
  + `last_14_days` replaced by `last_14d`
  + `last_28_days` replaced by `last_28d`
  + `last_30_days` replaced by `last_30d`
  + `last_90_days` replaced by `last_90d`
  + `last_week` replaced by `last_week_sun_sat` and `last_week_mon_sun`
  + `this_week` replaced by `this_week_sun_today` and `this_week_mon_today`
  + `last_3_months` has been deprecated.
  + **For version 2.8 and earlier, we support both these new values and the old date preset values.**

* **Default `date_preset`** - If you made an Insights query without `date_preset` we defaulted to `last_30_days` which included activity from today from 12:00AM in an ad account's timezone. As of 2.9 this defaults to `last_30d`. This includes the complete previous 30 days, ending at 11:59 PM last night, in your account's time zone, and not including today.
* `video_complete_watched_actions` is deprecated. It provided the same information as `video_30_sec_watched_actions`.
* `unique_impression` and `unique_social_impressions` are deprecated. Please use `reach` and `social_reach` instead.
* `newsfeed_clicks`, `newsfeed_impressions`, `newsfeed_avg_position`, `video_avg_sec_watched_actions`, `video_avg_pct_watched_actions` are outdated metrics being deprecated.
* The following are deprecated under `action_type:`: `follow`, `gift_sale`, `video_play`, and `vote`.
* `click_to_play_video` is now accessible via the `action_video_type` breakdown.
* `placement` breakdown field for delivery data is deprecated from Insights API. Only `["publisher_platform", "platform_position"]` are supported in 2.9. In 2.8, we still support both `["placement"]` or `["publisher_platform", "platform_position"]` as breakdowns.
* `attribution_spec` - In the past, you used two separate fields for click-through and view-through attribution windows in Insights API. You should now use `attribution_spec` to set both of them. When you set `attribution_spec` you override any existing settings. If you had set both click-through and view-through, when you set `attribution_spec` to `event_type = CLICK_THROUGH` you only remove view-through attribution.

### 90-Day Breaking Changes

No 90-Day Breaking Changes.

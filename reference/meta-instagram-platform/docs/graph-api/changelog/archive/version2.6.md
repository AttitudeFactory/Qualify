## Version 2.6

[Graph API](#gapi-v2-6) | [Marketing API](#mapi-v2-6)

Changelog entries are categorized in the following way:

* **New Features** — New products or services, including new nodes, edges, and fields.
* **Changes** — Changes to existing products or services (not including **Deprecations**).
* **Deprecations** — Existing products or services that are being removed.
* **90-Day Breaking Changes** — Changes and deprecations that will take effect 90 days after the version release date.

**New Features**, **Changes**, and **Deprecations** only affect this version. **90-Day Breaking Changes** affect all versions.

[Breaking Changes](/docs/graph-api/changelog/breaking-changes) are not included here since they are not tied to specific releases.

---

### Graph API Version 2.6

**Released** April 12, 2016 | **Available until** July 13, 2018

* [New Features](#gapi-new-v2-6)
* [Changes](#gapi-change-v2-6)
* [Deprecations](#gapi-deprecate-v2-6)
* [90-Day Breaking Changes](#gapi-90-v2-6)

---

### New Features

* [Pages](#gapi-new-pages-v2-6)
* [Video API](#gapi-new-video-v2-6)

#### Pages

* **Notes on Users** - Page admins can take notes on Users. Please see the `admin_notes` edge [reference docs](https://developers.facebook.com/docs/graph-api/reference/page-admin-note/) on the Page node for more information.

* **Labels on Users** - Page admins can create labels for Users. Please see the `labels` edge [reference docs](https://developers.facebook.com/docs/graph-api/reference/user) on the User node for more information.

* **Send Messages to Users Using Page-Scoped ID or Phone Number** - Pages can now send text, attachments, and template messages to users through their page-scoped-ids or phone numbers.
  + The `pages_messaging` permission to send and receive messages on behalf of a Page.
  + The `pages_messaging_phone_number` permission to send messages on behalf of Pages using a phone number as an ID.

#### Video APIs

* **Live API** - Post and manage Live Videos. Access to these endpoints requires approval. Please see our [Live API documentation](https://developers.facebook.com/docs/graph-api/reference/live-video) for more information.
* **Video Node** - The following fields have been added. Please see [the Video node reference docs](https://developers.facebook.com/docs/graph-api/reference/video) for more details.

  + `live_status`. The current broadcast state of the video. Values include: `LIVE`, `LIVE_STOPPED`, `VOD`. If this field is null, it means the video was never broadcast.
  + `live_audience_count` - The number of unique viewers who watched the video when it was live.
  + `content_tags` - Add tags to a video.

* **Rights Manager API** - We've introduced a new Rights Manager API that allows a copyright owner to claim ownership for videos and manage copyright matching rules. To use the API, please enroll via the [Rights Manager Enrollment](https://l.facebook.com/l.php?u=https%3A%2F%2Frightsmanager.fb.com%2F&h=AUCpa6-H3Xrp7gILCbCQsJMt9dLMfcVDvJq5cQfNQxoqiDuEilxBEdkYHAw7ZZPh60zBJVpkMvBGl23J_aiaRIe5VtMcNoXEbALFO5uPd_wS_3Iq7MwLH5RYEvgWU-aSVZrU2u_RMP1cHEKv) website. Please see our documentation for the [Rights Manager API](/docs/graph-api/rights-manager-api) for more information about the API and the enrollment process.

* **Crossposted Videos** - Pages can now [create posts](/docs/graph-api/video-uploads#crosspostedvideos) from videos they own without the need to re-upload the videos again. The major benefit of this is that you can see consolidated insights for a video and a breakdown of metrics across the multiple posts created from the video. Please see the `is_crossposting_eligible` and `crossposted_video_id` field in [the Video node](/docs/graph-api/reference/video/) and the `videos_you_can_use` field on [the Page node](/docs/graph-api/reference/page) for more information. The `videos_you_can_use` field tells you if a Page owner has granted permission for you to cross-post it

* **Video Insights** - The following edge has been added to the Video node:

  + `video_insights` - Contains aggregated video insights from all crossposts across Pages. See the [`video_insights`](/docs/graph-api/reference/v2.6/video/video_insights) edge for more information. We have also added Daily Video Metrics, Minutes Watched, and 10s metrics to insights edge on the [Post Node](/docs/graph-api/reference/post).

#### Messenger APIs

* **Webhooks** - The following fields have been added. Please see our [implementation guide](/docs/messenger-platform/implementation#setup) for more information.

  + `messages` - Receive inbound messages.
  + `message_deliveries` - Receive delivery confirmations.
  + `messaging_optins` - Receive authentiation events.
  + `messaging_postbacks` - Receive postback from buttons on Structured Messages.

* **Messenger Plugin** - We've added a new web plugin to authenticate people into the Messenger Platform. People can now interact with your business over Messenger. Please see our [implementation guide](/docs/messenger-platform/implementation#send_to_messenger_plugin) for more information.
* **Message Us Plugin** - We've added a new web plugin to enable people to start a chat directly with a Page. Please see our [implementation guide](/docs/messenger-platform/implementation#message_us_plugin) for more information.
* **Send/Receive API** - The Send/Receive API is part of the Messenger Platform. It can be used to send and receive messages between people and Pages. Please see our [implementation guide](/docs/messenger-platform/implementation#Conversation).

#### Sharing for Devices

* **Sharing for Devices** - We're launching a new Sharing for Devices API that lets you share easily from a device to Facebook. Please see our documentation on [Sharing for Devices](/docs/sharing/for-devices) for more information.

#### Photos

* **Reactions API** - We've added a new reactions edge for objects that were previously likable. As an example, please see the [Photo edge for reactions](/docs/graph-api/reference/photo/reactions/).

---

### Changes

* [Pages](#gapi-change-pages-v2-6)

#### Pages

* The `likes` field on the Page node has been renamed to `fan_count`.

* You can no longer login as a Page. Please see our [Pages documentation](/docs/pages/publishing) to learn more about posting as a Page.

---

### Deprecations

* [6 Month Deprecations](#gapi-deprecate-6-v2-6)
* [Apps](#gapi-deprecate-apps-v2-6)
* [Devices](#gapi-deprecate-devices-v2-6)
* [Pages](#gapi-deprecate-pages-v2-6)

#### 6 Month Deprecations

* **Feed Dialog** - Applications using the Feed Dialog will be required to have the `publish_actions` permission to have access to the returned `post_id`. The `post_id` will only be returned if the share generates a story on a person's timeline or in a group. This will take effect on October 11th.

#### Apps

* **Insights** - The following metric has been deprecated:

  + `facebook_login_total_users`

#### Devices

* **Device Authentication** - The following endpoint has been deprecated:

  + `oauth/device` - This affects devices that use this endpoint to generate access tokens. Please use the `device/login` and `device/login_status` endpoints instead. See [our documentation on logging in with devices](/docs/facebook-login/for-devices) for more information.

#### Pages

* The following Pages Insights have been deprecated. Each of these has been replaced by another way to query a similar set of insights. Please see our documentation on [Page Views](/docs/graph-api/reference/insights#page_views) for more information. The new insights start with the `page_views` prefix.

  + `page_visits_by_age_gender_logged_in_unique`
  + `page_visits_by_internal_referer_logged_in_unique`
  + `page_visits_by_profile_tab_logged_in_unique`
  + `page_visits_by_profile_tab_total`
  + `page_visits_by_site_logged_in_unique`
  + `page_visits_logged_in_total`
  + `page_visits_logged_in_unique`
  + `page_visits_total`

---

### Breaking Changes

* [Apps](#gapi-break-apps-v2-6)
* [Games](#gapi-break-games-v2-6)

#### Apps

* **Role Visibility** - Starting with the release of v2.6, an application can no longer see all of the roles that a developer has on other apps. This change also applies to previous versions.

#### Games

* **Game Groups Beta** - The Game Groups Beta feature, also known as App Groups, is deprecated as a 6 month deprecation. Effective May 1, no new apps may use the Game Groups API. Final deprecation effective on October 18th.

### 90-Day Breaking Changes

* [Pages](#gapi-90-pages-v2-6)
* [Webhooks](#gapi-90-webhooks-v2-6)

#### Pages

* **Rate Limits Changes for Page-related Requests** - If you make a request with a Page Access Token, the limits will scale with the number of people engaging with the page. This change will take effect July 11th.

#### Webhooks

* **All Callback Subscriptions Must Use HTTPS** - When we launched Graph API v2.5 last October we began requiring new Webhooks (formerly known as Real Time Updates) subscriptions to be configured for HTTPS. With v2.6, this is now required for all new Dynamic Pricing and Deauthorization endpoints as well. Beginning 90 days from today, we will require *all* callback subscriptions to be configured for HTTPS. At that point, we will stop sending updates to non-HTTPS endpoints, regardless of when they were created. This applies to Webhooks, Webhooks for Payments, Dynamic Pricing, and Deauthorization. You can update your subscriptions on your [app dashboard](/apps).

### Marketing API

**Released** April 12, 2016 | **Available until** October 5, 2016

* [New Features](#mapi-new-v2-6)
* [Changes](#mapi-change-v2-6)
* [Deprecations](#mapi-deprecate-v2-6)
* [90-Day Breaking Changes](#mapi-90-v2-6)

---

### New Features

* No New Features.

---

### Changes

* [Ads Management](#mapi-change-ads-manage-v2-6)
* [Dynamic Ads](#mapi-change-dynamic-v2-6)
* [Insights](#mapi-change-insight-v2-6)
* [Lead Ads](#mapi-change-lead-v2-6)
* [Targeting](#mapi-change-target-v2-6)

#### Ads Management

* Deprecated the `connectionobjects` API which retrieved all object types and replace it with other APIs that return specific object types. This greatly improves the performance and maintainability. More details [here](/docs/marketing-api/connectionobjects/v2.6). The new API is at these endpoints:

  + Pages: `user_id/accounts`
  + Events: `user_id/promotable_events`
  + Apps: `adaccount_id/advertisable_applications`
  + Domains: `user_id/promotable_domains`

* Sharing a Custom Audience (CA) to Ad Accounts can be done through `<CUSTOM_AUDIENCE_ID>/adaccounts` API. When a custom audience is shared to a AdAccount, there is a permission setting for sharing it with `targeting` only or with `targeting_and_insights` option. Targeting means a recipient ad account can target ads to the audience, insights means the recipient ad account can also use insights tool to view the audience demographics. The default has changed from `targeting` only to `targeting_and_insights` in 2.6.

#### Dynamic Ads

* Changed Product Catalog Sales Objective ad set's default `optimization_goal` to `OFFSITE_CONVERSIONS`.
* Default to carousel format. In order to opt-out of carousel format, specify `force_single_link=true` in `object_story_spec`.
* Return an error if no username/password provided for (S)FTP urls when scheduling the product feed. Empty username/password is allowed. e.g. username:"".

#### Insights

* Changed the default for `date_preset` value from `lifetime` to `last_30_days` and `fields` value from all fields to `impressions,spend`. Both of these defaults apply to `/insights` for all object levels.
* The `fields` parameter no longer accepts breakdowns such as `age` or `gender`. Now you should specified this in `breakdowns` parameter in query. This includes: `age`, `country`, `gender`, `frequency_value`, `hourly_stats_aggregated_by_advertiser_time_zone`, `hourly_stats_aggregated_by_audience_time_zone`, `impression_device`, `place_page_id`, `placement`, `product_id`, and `region`. This applies to `/insights` for all object levels.
* Ads Insights API will throw error if `since` specified in `time_range` is in the future. Also replace `until` by today if `until` is in the future.

#### Lead Ads

* When querying to retrieve qualifier information for a Lead Ads form, the `label` and `question` values of the qualifier are interchanged for Custom Questions. We are fixing this so that moving forward content under `label` and `question` will be returned correctly.

#### Targeting

* The `user_device` field is changing to a new format. The old format contains underscores combining brand and marketing name, like `['samsung_galaxy_s6']`. The new format contains the device marketing name only, like `['galaxy s6']`. Valid values can be retrieved from `/search?type=adTargetingCategory&class=user_device`. All read requests will be automatically transformed to new format. All writes require the new format.

  + Note that because the values for `user_device` are different, `/reachestimate` calls must be made to an object's corresponding version. For example, if an ad set was created in version `v2.5` while targeting `user_device` using the old format, the `/reachestimate` call for that ad set will return inaccurate values unless it's also made under `v2.5`.

---

### Deprecations

* [Dynamic Ads](#mapi-deprecate-dynamic-v2-6)

#### Dynamic Ads

* The following fields have been deprecated:
* `product_ad_behavior` field at the Ad Set level, which is used by Dynamic Ads. Instead we now default all new Ad Sets to `FALL_BACK_TO_FB_RECOMMENDATIONS`. That means Facebook will automatically choose the highest-performing products from the creative's Product Set to show people who have browsed products that are not in the Product Set.
* `{page_id}/rtb_dynamic_posts` for DPA. Use `[<OBJECT_STORY_ID>]/dynamic_posts` instead.
* `max_product_count` since Facebook now automatically optimizes the number of products to show for Dynamic Product ads. In order to opt-out of carousel format, specify `force_single_link=true` in `object_story_spec`.
* `row_number` and `column_number` fields on product feed upload error `/<UPLOAD_ID>/errors`, they are available on error samples now.

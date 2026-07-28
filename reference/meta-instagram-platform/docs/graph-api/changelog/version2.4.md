# Version 2.4

[Graph API](#gapi-v2-4) | [Marketing API](#mapi-v2-4)

## Graph API

**Released** July 8, 2015 | **Available until** October 9, 2017

### New Features

#### Page Video Insights

In v2.4 we expose a set of new Page Video metrics, such as `page_video_views_paid`, `page_video_views_autoplayed`, and `page_video_views_organic` available from the Graph API via `GET /v2.4/{page_id}/insights/?metric={metric}`. These metrics require the `read_insights` permission.

#### New Video Features

The `Video` node now contains the following fields in `GET|POST` operations to `/v2.4/{video_id}`:

* `content_category` which supports categorizing a video during video upload, and can be used for suggested videos. Content categories include: Business, Comedy, Lifestyle, etc and a full list of categories can be viewed on the `Video` node [docs page](/docs/graph-api/video-uploads).
* `unpublished_content_type` will expose 3 new types (Scheduled, Draft, and Ads\_Post) which will help coordinate how the video is posted.
* `expiration` and `expiration_type` allows the video expiration time to be set, along with the type (hide, delete).
* `embeddable` boolean flag is now available to control if 3rd party websites can embed your video.

#### Accessing Timeline Posts

We've simplified how you access content on a person's Timeline. Instead of handling different object types for statues and links, the API now returns a standardized Post node with attachments which represent the type of content that was shared. For more details view the [User reference docs](/docs/graph-api/reference/user).

### Changes

#### Permission related changes

* Operations that reference the `admin_creator` object of a Post in now requires a Page access token.
* `POST /v2.4/{page_id}/offers` and `DELETE /v2.4/{offer_id}` now require a Page access token with `manage_pages` and `publish_pages` permissions.
* `GET /v2.4/{page_id}/milestones`, `POST /v2.4/{milestone_id}`, and `DELETE /v2.4/{milestone_id}` now require a Page access token with `manage_pages` and `publish_pages` permission.

#### Changes to Pages APIs

* Calls made to the `Page` node `GET /v2.4/{page_id}/promotable_posts` now require a user access token with `ads_management` permission or a Page access token.
* The `global_brand_parent_page` object has been renamed to `global_brand_root_id`.
* `GET /v2.4/{global_brand_default_page_id/insights` will now return only insights of the default Page insight data, instead of the insights for the Global Brand hierarchy. Use the Root Page ID to retrieve the integrated insights of the whole hierarchy.
* `GET|POST /v2.4/{page_id}/promotable_posts` has renamed the field `is_inline` to `include_inline`.
* The maximum limit for Page related objects is now set to `limit=100`. This will impact `GET` operations made on the `feed`, `posts`, and `promotable_posts` edges.

#### Event Ordering

The default pagination ordering of `GET {user-id}/events` now begins with the newest event first, and is ordered in reverse chronological order.

#### Improved Filtering

Graph API v2.4 now supports filtering of `GET /v2.4/{user_id}/accounts` with new boolean fields:

* `is_promotable` filter results by ones that can be promoted.
* `is_business` filter results associated with a Business Manager.
* `is_place` Include Place as results filter.

#### Declarative Fields

To try to improve performance on mobile networks, Nodes and Edges in v2.4 requires that you explicitly request the field(s) you need for your `GET` requests. For example, `GET /v2.4/me/feed` no longer includes likes and comments by default, but `GET /v2.4/me/feed?fields=comments,likes` will return the data. For more details see the [docs](/docs/graph-api/using-graph-api/) on how to request specific fields.

### Deprecations

#### 2-year deprecations

* `GET /v2.4/{id}/links` and `GET /v2.4/{id}/statuses` will no longer be available beginning in v2.4. As an alternative, we suggest using `GET /v2.4/{id}/feed`.
* `GET|POST /v2.4/{page_id}/?fields=global_brand_parent_page` is being deprecated in this version and replaced by `/v2.4/{page_id}/?fields=global_brand_root_id`.
* `GET|POST /v2.4/{page_id}/global_brand_default_page_id/global_brand_children` will no longer function in v2.4. As an alternative, please use the root page ID.
* `GET /v2.4/{page_id}/promotable_posts` will no longer support the filter and type params in v2.4. For example, a call to `GET /v2.4/{page_id}/promotable_posts?type=STATUS` will return an empty result set.
* The `Event` node no longer supports `GET` operations on the endpoints `/v2.4/{event_id}/invited`, `/v2.4/{event_id}/likes`, or `/v2.4/{event_id}/sharedposts`.

#### 90-day deprecations (effective Tuesday, October 6, 2015)

* The `GET /v2.4/{user_id}/home`, `GET /v2.4/{user_id}/inbox`, and `GET /v2.4/{user_id}/notifications` operations as well as `read_stream`, `read_mailbox`, and `manage_notifications` permissions are deprecated in v2.4.
* the `user_groups` permission has been deprecated. Developers may continue to use the `user_managed_groups` permission to access the groups a person is the administrator of. This information is still accessed via the `/v2.4/{user_id}/groups` edge which is still available in v2.4.
* `GET /v2.4/{event_id}/?fields=privacy` is deprecated in v2.4.
* `GET /v2.4/{event_id}/?fields=feed_targeting` is deprecated in v2.4.
* `GET /v2.4/{event_id}/?fields=is_date_only` is deprecated in v2.4.

From October 6, 2015 onwards, in all previous API versions, these endpoints will return empty arrays, the permissions will be ignored if requested in the Login Dialog, and will not be returned in calls to the `/v2.4/me/permissions` endpoint.

### Marketing API

**Released** July 8, 2015 | **Available until** April 11, 2016

Version `v2.3` (formerly known as Ads API) will be available until October 7, 2015. Before that date, you should migrate your API calls to `v2.4`.

### New Features

#### [Labels API](/docs/marketing-api/reference/ad-label)

A new API that lets developers tag campaigns/adsets/ads/creatives with arbitrary strings (“labels”) and organize/group their ad objects. The Labels API also allows querying adobjects by labels, including AND/OR queries, and query aggregated Insights by label. Now it is possible to answer questions like “how many clicks did all adsets with the 'US-country' label get?”

#### Other

Added a new field 'app\_install\_state' in the ad set's targeting which takes a enum value of {installed, not\_installed}. This field is intended to make inclusion/exclusion targeting for apps easier. The field can be used for any objective, but will only take effect if a promoted object is present.

### Changes

* Optimization simplification: We're simplifying how the optimization is specified in the data model by decoupling the bid fields into 3 separate fields. With this simplification, we should be able to significantly reduce the confusion around optimization specification in both the API and our UIs. See [optimization simplification](/docs/marketing-api/optimization_simplification) for more details.
* The new fields on the ad set are:
* `optimization_goal`: What the advertiser is optimizing for (video\_views, link\_clicks, etc...)
* `billing_event` (**required**): What the advertiser is paying by (pay per impression, pay per link click, pay per video view etc...)
* `bid_amount`: The value the advertiser is bidding per optimization goal
* `rtb_flag` which should be used in favor of bid\_type=CPM\_RTB.
* The new fields on the ad are:
* `bid_amount`: The value the advertiser is bidding per optimization goal
* The removed fields on the ad set are:
* `bid_info`: will be removed on all write paths but can still be read. Use ad set's bid\_amount field instead.
* `bid_type`
* The removed fields on the ad are:
* `bid_info`: will be removed on all write paths but can still be read. Use ad's `bid_amount` field instead.
* `conversion_specs`: will be removed on all write paths but can still be read. Use ad set's optimization\_goal field instead.
* `is_autobid`
* Updating CPC to focus on link clicks - in order to make our advertisers' campaigns on Facebook more effective, we are updating the definition of cost per click (CPC). Today, when an advertiser runs a CPC ad, Facebook counts any action taken within the ad unit as a click: a like, a comment, a share, “continue reading”, a video view, a link click, etc. Starting v2.4, we are updating our definition of CPC ads to separate link clicks from engagement clicks (including likes and comments), and CPC will only include link clicks. To continue to optimize for likes, comments, shares, etc. as well as link clicks, advertisers can use billing\_event=POST\_ENGAGEMENT and optimization\_goal=POST\_ENGAGEMENT (or in `v2.3` terms, CPA for Page Post Engagement).
* Legacy ad sets bidding the `v2.3`- definition of CPC will be represented in `v2.4` as having `billing_event=POST_ENGAGEMENT` and `optimization_goal=POST_ENGAGEMENT`
* Old statistics APIs are being deprecated in favor of [Insights Edge](/docs/marketing-api/insights): With the launch of the Insights edge, we now have a single, consistent Insights API that advertisers can use to get all their metrics in one place. The Insights edge supports both sync and async queries, plus has new features like hourly breakdowns. With v2.4, [stats](/docs/marketing-api/adstatistics), [conversion stats](/docs/marketing-api/conversionstatistics) and [report stats](/docs/marketing-api/adreportstats) APIs are deprecated.
* Ads insights placement breakdown result will merge desktop\_non\_feed and desktop\_right\_hand into desktop\_right\_hand
* Targeting
* Split `page_types` into an array of single items, e.g. Instead of `page_types:['desktop-and-mobile-and-external']` you would specify: `page_types=['desktopfeed', 'rightcolumn', 'mobilefeed', 'mobileexternal']`. The previously available groupings of page\_types and validations remain the same.
* Note that the previous definition of `['mobile']` or `['mobilefeed-and-external']` must now be replaced with `['mobilefeed', 'mobileexternal']`
* When not specifying a placement in `targeting` of an ad set, by default Facebook will include Audience Network `page_types`, and may include other `page_types` without notice in the future.
* Deprecate `conjunctive_user_adclusters` and `excluded_user_adclusters` in favor of [flexible targeting](/docs/marketing-api/targeting-specs/#flexible)
* Deprecate [ad tags](/docs/marketing-api/adtag) API in favor of new [ad labels](/docs/marketing-api/reference/ad-label)
* Additional invalidations based on bid-budget ratios, please see [ad set documentation](/docs/marketing-api/reference/ad-campaign/v2.4) for more details.
* The 'Authorized Advertiser Emails and System User IDs' to set permissions on an app via App settings > Advanced. You must instead use an Ad account ID in the 'Authorized Ad Account IDs' field, or delegate access via Business Manager. `act_{AD_ACCOUNT_ID}/connectionobjects` will no longer return connections based on advertiser email.
* Deprecate the [conversion pixel](/docs/marketing-api/offsite-pixels) `status` field. Developers should instead use `last_firing_time`
* `subtype` will become a required parameter in [custom audience](/docs/marketing-api/custom-audience-targeting) and [lookalike creation](/docs/marketing-api/lookalike-audience-targeting/)
* Ad account TOS list returns enum string instead of FBID. Instead of `{ "tos_accepted": { "206760949512025": 1, "215449065224656": 1 }`, return `"tos_accepted": {"web_custom_audience_tos": 1, "custom_audience_tos": 1 }`
* Remove `daily_spend_limit` from ad account
* Campaign `spend_cap` type change from uint32 to numeric string
* Ad set `DAILY_BUDGET, BUDGET_REMAINING, LIFETIME_BUDGET` type change from uint32 to numeric string

For the full list of Graph API changes, refer to the [Graph API changelog](/docs/apps/changelog).

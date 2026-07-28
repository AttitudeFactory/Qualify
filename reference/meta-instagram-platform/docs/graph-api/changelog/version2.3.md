## Version 2.3

[Graph API](#gapi-v2-3) | [Marketing API](#mapi-v2-3)

### Graph API

**Released** March 25, 2015 | **Available until** July 10, 2017

### New Features

* **`user_posts` Permission** - We have a new permission user\_posts that allows an app to access the posts on a person's Timeline. This includes the someone's own posts, posts they are tagged in and posts other people make on their Timeline. Previously, this content was accessible with the `read_stream` permission. The `user_posts` permission is automatically granted to anyone who previously had `read_stream` permission.
* **`all_mutual_friends` Edge** - This Social context edge enables apps to access the full list of mutual friends between two people who use the app. This includes mutual friends who use the app, as well as limited information about those who don't.

> Both users for whom you're calling this endpoint must have granted the `user_friends` permission.
>
> If you calling this endpoint for someone not listed in your app's `Roles section` you must submit your app for review by Facebook via App Review.
>
> Although this edge is new to Graph API v2.3, to make it easier for you to migrate we also added this edge to v2.0, v2.1, and v2.2.

* **Debug Mode** - Provides extra information about an API call in the response. This can help you debug possible problems and is now in [Graph API Explorer](/tools/explorer/), as well as the iOS and Android SDKs. For more information see [Graph API Debug Mode](/docs/graph-api/using-graph-api#debugging).
* **New Pages Features**

> * **Real-time Updates** - As of March 25, 2015 We now send content in Page real-time updates (RTUs). Previously, only the object's ID was in the RTU payload. Now we include content in addition to the ID including: statuses, posts, shares, photos, videos, milestones, likes and comments. In order for the app to receive these types of updates, you must have enabled the "Realtime Updates v2.0 Behavior" migration in your app's dashboard.
> * **Page Reviews** now support real-time updates. Apps can subscribe to the `ratings` property to receive a ping every time a public review is posted on pages the app is subscribed to. In order for the app to receive this type of update, you must have enabled the "Realtime Updates v2.0 Behavior" migration in your app's dashboard.
> * **Page Posts, `admin_creator`** - All Page Posts now include a new `admin_creator` field that contains the `id` and `name` of the Page Admin that created the post. This is visible when you use a Page access token, or the user access token of a person who has a role on the Page.
> * **New Page Fields** -`GET|POST /v2.3/{page-id}` now supports fetching and updating these fields: `emails`, `food_styles`, `public_transit`, `general_manager`, `attire`, `culinary_team`, `restaurant_services`, `restaurant_specialties`, and `start_info`.
> * **New Page Settings** - `GET|POST /v2.3/{page-id}/settings` now supports four new settings: `REVIEW_POSTS_BY_OTHER`, `COUNTRY_RESTRICTIONS`, `AGE_RESTRICTIONS`, and `PROFANITY_FILTER`.

* **[Videos New Features](/docs/graph-api/video-uploads)**

> * **Larger Videos with Resumable Upload** - We now support larger video sizes uploads up to **1.5GB** or **45 minutes** long with resumable video upload. See [Video Upload with Graph API](/docs/graph-api/video-uploads).

* **File URL Parameter** - At all `/v2.3/{object_id}/videos` edges you can create a new Video object from the web by providng the `file_url` parameter.

> * **Resumable, Chunked Upload** - All `/v2.3/{object_id}/videos` edges support resumable, chunked uploads. For more information, see [Video Upload with Graph API](/docs/graph-api/video-uploads).

* **Video Playlists** - You can now create and manage video playlists for Pages by using `GET|POST|DELETE` on the `/v2.3/{page_id}/videolist` edge. you can also add videos to a playlist by `POST /v2.3/{videolist_id}/videos` and `GET` the videos of a playlist.
* **Page's Featured Video** - You can now set and get the featured\_video of a page using `GET|POST /v2.3/{page_id}/featured_videos_collection`.

> * **Publish Fields** - All Video nodes objects at `/v2.3/{video_id}` now return the new fields: `published`, a boolean which indicates if the video is currently published, and `scheduled_publish_time`.
> * **Custom Thumbnail** - You can now upload and manage custom video thumbnails as JPEGs or PNGs with `GET|POST /v2.3/{video_id}/thumbnail`. See [Graph API Reference, Video Thumbnail](/docs/graph-api/reference/video-thumbnail/).
> * **Targeting Restrictions** - `POST /v2.3/{page-id}/videos` now supports targeting restrictions by country, locale, age range, gender, zipcode, timezone and excludin locations.
> * **Delete** - `DELETE /v2.3/{video_id}` removes videos. This is supported if you have edit permissions on the video object.
> * **New Read and Write Fields** - The Video node now supports retrieving and modifying additional fields: `backdated_time`, and `backdated_time_granularity`.
> * **Subtitles, Localized Captions** - `GET|POST /v2.3/{video-id}` now supports supplying and retrieving subtitles and localized captions.
> * **Visibility of Video** - With `POST /v2.3/{page_id}/videos` you can control where the video is seen with `no_story` and `backdated_post.hide_from_newsfeed` parameters. These parameters target visibility on feeds and page timelines.

### Marketing API

Formerly known as Ads API v2.3

### Changes from v2.2 to v2.3

* **[Page Plugin](/docs/plugins/page-plugin)** - Is the new name for Like Box Social Plugin and it has a new design.
* **[Comments Plugins](/docs/plugins/comments/)** Has a new design and it now supports Comment Mirroring (private beta).
* **`Requests` are now `GameRequests`** - Previously this term and object-type created confusion for non-game app developers, and the intended usage of these objects are to invite others to a game Non-game apps should use [App Invites](/docs/app-invites). The `/v2.3/{user-id}/apprequests` edge is now limited to game apps. See [Games, Requests](/docs/games/requests).
* **`read_custom_friendlists`** - Is the new name for `read_friendlists` Login permission. This is to clarify that the permission grants access to a person's custom friendlists, not the full list of that person's friends.
* **Changes to Page APIs**:

> * **`publish_pages` Permission** - This new permission is required to publish as a Page. Previously `publish_actions` was required. People who granted `manage_pages` and `publish_actions` before v2.3 have automatically been granted `publish_pages`. If anyone logs in via v2.3, you'll need to request `publish_pages` explicitly in addition to `manage_pages`.
> * **Page Publish Operations** - now accept the type of access token the requests are made with. This includes publishing posts, likes and comments. When a user access token of a Page admin is in the request such as `POST /v2.3/{page-id}/feed`, the action occurs with the voice of the user, instead of the Page. To publish as the Page, you must now use the Page access token.
> * **Removing Comments on Page posts** - As a Page admin with `DELETE /v2.3/{comment-id}` now requires a Page access token.
> * **`POST /v2.3/{page-id}`** - Now requires country as sub-parameter if you update the `location` field without specifying the `city_id` sub-parameter. The state sub-parameter is also required if country sub-parameter is 'United States'.
> * **Countries** - The country subfield of the `feed_targeting` field on a Page post is renamed `countries` when you make a `POST|GET /v2.3/{page-id}/{post-id}`.
> * **Page Field Updates** - `POST /v2.3/{page-id}` - Now supports complete field updates for: hours, parking, payment\_options.
>   Previously, the update behavior on these fields was to replace a specific key/value pair that was specified as part of the POST, leaving all other keys intact, but the new functionality of a POST on one of these fields will replace all key/value pairs with what is posted.
> * **Premium Video Metrics** - Insights for Page Premium Video Posts are now deprecated.
> * **`page_consumptions_by_consumption_type` insight now returns data for a local page instead of a parent** - In earlier versions of the insights API for a Page, asking for this insight would return data for a parent of a local page. In v2.3, we now return the data for only that local page.

* **Picture Error** - For the Link, Post, Thread, Comment, Status, and AppRequest nodes, and other nodes which don't have a picture, the `/v2.3/{object}/picture` edge now returns an error message. Before, the API returned a placeholder image of a 'question mark' for the picture edge requested on these nodes.
* **[Oauth Access Token] Format** - The response format of `https://www.facebook.com/v2.3/oauth/access_token` returned when you exchange a code for an `access_token` now return valid JSON instead of being URL encoded. The new format of this response is `{"access_token": {TOKEN}, "token_type":{TYPE}, "expires_in":{TIME}}`. We made this update to be compliant with section 5.1 of RFC 6749.
* **Consistent Place Data** - Content objects tagged with a place now share a consistent place data structure which contains the ID, name, and the geolocation of the place. This includes [Events](/docs/graph-api/reference/event), [Photos](/docs/graph-api/reference/photo), [Videos](/docs/graph-api/reference/video), [Statuses](/docs/graph-api/reference/status) and [Albums](/docs/graph-api/reference/album). As a result, the venue and location fields have been removed from the Event node. Developers should access the place field instead.

> In addition, if someone tags a [Photo](/docs/graph-api/reference/photo), [Video](/docs/graph-api/reference/video), [Status](/docs/graph-api/reference/status), or [Album](/docs/graph-api/reference/album) at an event, that object will contain an `event` field.

* **Serialized Empty Arrays** - All Graph API endpoints now consistently serialize empty arrays as `[]` and empty objects as `{}`. Previously, some empty objects were incorrectly serialized as empty arrays.
* **Default Result Limit** - All edges will now return 25 results per
  page by default when the `limit` param is not specified.
* **Ads API now Marketing API** - We recently renamed the Facebook Ads API to the Facebook Marketing API. For details on Marketing API changes see the [Marketing API v2.3 Changelog](/docs/marketing-api/changelog).

### 90-day deprecations (effective Tuesday, June 23, 2015)

* **Edges and Permissions** - `/v2.3/{user_id}/interests` and `/v2.3/{user_id}/activities` edges as well as `user_interests` and `user_activities` permissions are deprecated in v2.3.

> From June 23, 2015 onwards, in all previous API versions, these endpoints will return empty arrays, the permissions will be ignored if requested in the Login Dialog, and will not be returned in calls to the `/v2.3/me/permissions` endpoint.

* **Page RSS Feed endpoint** - at `https://www.facebook.com/feeds/page.php` is now deprecated and will stop returning data from June 23, 2015. Developers should call the Graph API's `/v2.3/{page_id}/feed` endpoint instead. This returns JSON rather than RSS/XML.
* **Social Plugins** - The following are now deprecated and will no longer render after June 23, 2015:

> * Facepile Plugin
> * Recommendations Feed Plugin
> * Activity Feed Plugin
> * Like Box Social Plugin

### Marketing API v2.3

**Released** March 25, 2015 | **Available until** October 8, 2015

Version `v2.2` will be available till July 8, 2015. Before that date, you should migrate your API calls to `v2.3`.

### New Features

#### [New Insights Edge](/docs/marketing-api/insights)

A new `/insights` edge consolidates functionality among `/stats`, `/conversions`, and `/reportstats` edges. It provides a single, consistent interface for ad insights. This edge is provided with every ad object node, including Business Manager. It provides functionality such as grouping results by any level, sorting, filtering on any field, and real time updates for asynchronous jobs.

#### [Chunked Ad Video Upload](/docs/marketing-api/advideo)

The new preferred way to upload ad videos is to do it chunk by chunk. When you upload an ad video, especially large ones, this method greatly increases the stability of video uploads. The previous one-step video uploading API still works, but we suggest you to switch to the new method for all videos.

#### R&F

* [Ad Sequencing in R&F Campaigns](/docs/marketing-api/reachandfrequency/#sequencing)
* Added `interval_frequency_cap_reset_period` to R&F which allows you to set a custom period of time that a frequency is applied to. Previously the cap was applied to the entire duration of the campaign.
* Lowered the minimum audience from 1.5M people to 300K people and minimum reach to 200K people. This means that if you select a target audience with 300K people, the minimum number of people we require you to reach within that audience is 200K.

#### Video

* API support for [video remarketing](/docs/marketing-api/guides/videoads/#remarketing)
* Video available for page like, website conversions, local awareness, and mobile app install objectives
* Added [CPV bidding](/docs/marketing-api/cost-per-action-ads)

#### Leads Ads

Introduced new [lead ad](/docs/marketing-api/guides/lead-ads) unit designed to capture leads within Facebook's native platforms.

#### Carousel Ads

* Carousel ads now allow for a minimum of 2 objects
* Added additional [insights for Carousel ads](/docs/marketing-api/guides/carousel-ads/#stats)

# Carousel end card now optional

#### Other

* Campaign spend cap
* Added auto bidding (is\_autobid) to ad set object
* For Global Pages, targeting a child Page will truly target the child Page and no longer target the entire hierarchy of pages.
* Added `CALL_NOW` and `MESSAGE_PAGE` call to action for [local awareness ads](/docs/marketing-api/guides/local-awareness)

### Changes

The following summarizes all changes. For more information on upgrading, including code samples, see [Facebook Marketing API Upgrade Guide](/docs/reference/ads-api/upgrading).

#### Ad Account

* The `amount_spent`, `balance`, `daily_spend_limit`, and `spend_cap` fields for an ad account are changed from integers to numeric strings.
* The `business` field of `/act_{AD_ACCOUNT_ID}` and `/{USER_ID}/adaccounts` is now a JSON object.
* 10 [ad account capabilities](/docs/marketing-api/adaccount#capabilities) are deprecated. You would not see those capabilities of your ad account. They are:
* 'AD\_SET\_PROMOTED\_OBJECT\_APP'
* 'AD\_SET\_PROMOTED\_OBJECT\_OFFER'
* 'AD\_SET\_PROMOTED\_OBJECT\_PAGE'
* 'AD\_SET\_PROMOTED\_OBJECT\_PIXEL'
* 'HAS\_AD\_SET\_TARGETING'
* 'MOBILE\_ADVERTISER\_ID\_UPLOAD'
* 'MOBILE\_APP\_REENGAGEMENT\_ADS'
* 'MOBILE\_APP\_VIDEO\_ADS'
* 'NEKO\_DESKTOP\_CANVAS\_APP\_ADS'
* 'NEW\_CAMPAIGN\_STRUCTURE'

#### Pixels and Audiences

* The field `name` is required while creating a Custom Audience pixel for an ad account using the `/act_{AD_ACCOUNT_ID}/adspixels` endpoint.
* The field `pixel_id` is required while creating website custom audiences using the `/act_{AD_ACCOUNT_ID}/customaudiences` endpoint.

#### Ad Campaign, Ad Set, and Ad

* An HTTP DELETE request to ad campaign, ad set, or ad will change its status to `DELETED`.
* You need to specify the timezone of the `start_time` and `end_time` fields when updating an ad set.
* When specifying a `promoted_object` in an ad set for an offer ad, you will provide the `page_id` instead of the `offer_id`.
* The `bid_info` field of ad set or ad will not be available if `is_autobid` of the ad set is true.
* The `creative_ids` field of an ad is no longer available.
* The `objective` field of an ad is no longer available.
* The `multi_share_optimized` field defaults to `true` now. You use this field when you create a [Multi Product Ad](/docs/marketing-api/guides/multi-product-ads) with `/{PAGE_ID}/feed` or `object_story_spec` in `/act_{AD_ACCOUNT_ID}/adcreatives`.

#### Business Manager

* The endpoint `/{APP_SCOPED_SYSTEM_USER_ID}/ads_access_token` is replaced by `/{APP_SCOPED_SYSTEM_USER_ID}/access_tokens`, for [Business Manager System User](/docs/marketing-api/businessmanager/systemuser) access token management.

#### Reach Estimate and Targeting

* [Reach Estimate APIs](/docs/marketing-api/reachestimate), like all the other Marketing APIs, should be called with a user access token, instead of a Page access token.
* The field `params` is removed from the response of targeting description obtained with `/{AD_GROUP_ID}/targetingsentencelines`
* Both the placement options `mobile` and `mobilefeed-and-external` places ads on News Feed on mobile as well as on [Audience Network](/docs/audience-network/). The new option `mobilefeed` is for News Feed on mobile only. You specify the placement option with `page_types` field of [targeting specs](/docs/marketing-api/targeting-specs/).

### Affected Endpoints

* /{APP\_SCOPED\_SYSTEM\_USER\_ID}/ads\_access\_token
* /act\_{AD\_ACCOUNT\_ID}
* /act\_{AD\_ACCOUNT\_ID}/adcreatives
* /act\_{AD\_ACCOUNT\_ID}/adgroups
* /act\_{AD\_ACCOUNT\_ID}/adcampaigns
* /act\_{AD\_ACCOUNT\_ID}/adspixels
* /act\_{AD\_ACCOUNT\_ID}/customaudiences
* /act\_{AD\_ACCOUNT\_ID}/reachestimate
* /act\_{AD\_ACCOUNT\_ID}/targetingsentencelines
* /{USER\_ID}/adaccounts
* /{CAMPAIGN\_GROUP\_ID}
* /{CAMPAIGN\_GROUP\_ID}/adgroups
* /{AD\_SET\_ID}
* /{AD\_SET\_ID}/adgroups
* /{AD\_ID}
* /{AD\_ID}/targetingsentencelines
* /{PAGE\_ID}/feed

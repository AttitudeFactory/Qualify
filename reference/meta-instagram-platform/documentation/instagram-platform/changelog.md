# Changelog for Instagram Platform



This changelog refers to changes made for the Instagram APIs.

### Related Changelogs

* [Graph API Changelog](https://developers.facebook.com/docs/graph-api/changelog)
* [Marketing API Changelog](https://developers.facebook.com/documentation/ads-commerce/marketing-api/marketing-api-changelog)
* [Messenger Platform Changelog](https://developers.facebook.com/documentation/business-messaging/messenger-platform/changelog) (includes Instagram Messaging)

## June 22, 2026

### AI Info Label

_Applies to all versions._

The [Content Publishing API](https://developers.facebook.com/documentation/instagram-platform/content-publishing) now supports self-disclosure of AI-generated content at publish time. Set the new `is_ai_generated` parameter to `true` when [creating a media container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#creating) to apply the AI info label. For carousels, set `is_ai_generated` on the carousel container only. Available in both Instagram API with Facebook Login and Instagram API with Instagram Login. `is_ai_generated` field is also now available on the [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) endpoint.

**Endpoints**

* `POST /&#123;ig_user_id&#125;/media` with the `is_ai_generated` parameter
* `GET /&#123;ig_media_id&#125;?fields=is_ai_generated`

### New Story Insights Metrics

_Applies to all versions._

Introducing a new `link_clicks` metric on the [IG Media Insights](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights) endpoint for **Story media**, returning the number of taps on links in your story (such as link stickers). Only available in Instagram API with Facebook Login.

**Endpoint**

* `GET /&#123;ig_media_id&#125;/insights?metric=link_clicks`

## June 1, 2026

### Instagram Audio API

_Applies to all versions._

Introducing the [**Instagram Audio API**](https://developers.facebook.com/docs/instagram-platform/content-publishing/audio-api) for apps using Facebook Login. The API lets your app search for and retrieve audio — original sounds from Reels and royalty-free music from Meta&#039;s Sound Collection — and attach it to Reels at creation time.

This release also adds an ads use case for discovering replacement audio for Instagram Reels ads: when a Reel contains copyrighted music, your app can find royalty-free Sound Collection tracks to replace it. To apply a discovered track to a Reels ad, see [IG Audio Swap for Instagram Reels Ads](https://developers.facebook.com/documentation/ads-commerce/marketing-api/out-of-cycle-changes/occ-2026#ig-audio-swap-for-instagram-reels-ads).

**Endpoints**

* `GET /ig_audio?audio_type=&#123;music\|original_sound&#125;` — Search or retrieve trending audio
* `GET /&#123;ig_audio_id&#125;` — Get metadata for a specific audio asset
* `GET /ig_audio?product=ADS&amp;purpose=AUDIO_COPYRIGHT_REPLACEMENT&amp;audio_replacement_mode=&#123;auto\|search\|default&#125;&amp;ig_media_id=&#123;ig_media_id&#125;` — Discover replacement audio for Reels ads

### New IG Media Field

_Applies to all versions._

A new field is now available on the [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) endpoint:

* `media_audio_type` — The type of audio used in the media: `MUSIC` (licensed music from Meta&#039;s catalog) or `ORIGINAL_SOUND` (original audio). Returned for video media such as Reels.

**Endpoint**

* `GET /&#123;ig_media_id&#125;?fields=media_audio_type`

## May 15, 2026

### oEmbed API
*Applies to all versions.*

You can now call Instagram oEmbed API without an access token. See [Embed an Instagram Post](https://developers.facebook.com/documentation/instagram-platform/oembed) for more details.

## May 6, 2026

[Sending multiple images](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api) is now out of beta and available to all accounts.

## April 22, 2026

### New Media Engagement Fields

_Applies to all versions._

Three new fields are now available on the [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) endpoint for apps using Facebook Login, giving deeper insight into how content is being distributed:

* `reposts_count` — Number of times the media has been reposted by other users
* `saved_count` — Number of times the media has been saved
* `shares_count` — Number of times the media has been shared

**Endpoint**

* `GET /&#123;ig_media_id&#125;?fields=reposts_count,saved_count,shares_count`

### Aggregated Metrics

_Applies to all versions._

Introducing three new aggregated metrics that provide comprehensive engagement totals across all surfaces, including boosted media and Facebook crossposted content. These values match what users see in the Instagram Insights Dashboard and are available through both the [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) and [Insights](https://developers.facebook.com/documentation/instagram-platform/insights) endpoints:

* `total_like_count` / `total_likes` — Aggregated likes across Instagram, Facebook, and promoted media
* `total_comments_count` / `total_comments` — Aggregated comments across all surfaces
* `total_views_count` / `total_views` — Aggregated views across all surfaces (video media only)

**Endpoints**

* `GET /&#123;ig_media_id&#125;?fields=total_like_count,total_comments_count,total_views_count`
* `GET /&#123;ig_media_id&#125;/insights?metric=total_likes,total_comments,total_views`

### Enhanced Views Metrics

_Applies to all versions._

* **`facebook_views` expansion:** The [`facebook_views`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights) metric now supports Feed post, Reels, and Story media types, and coverage has expanded to include both crossposted plays and cross-app recommended plays.
* **Cross-platform `view_count`:** The `view_count` field now returns combined Instagram and Facebook views for crossposted video content when looking up another user&#039;s public media via the Business Discovery API.

**Endpoints**

* `GET /&#123;ig_media_id&#125;/insights?metric=facebook_views`
* `GET /&#123;ig_user_id&#125;?fields=business_discovery.username(&#123;username&#125;).media&#123;view_count&#125;`

### Collaborative Media API

_Applies to all versions._

Introducing the [**Collaborative Media API**](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/collaboration) on the [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user). The API lets your app retrieve all media where your app user is an accepted collaborator, making it easier to track and measure performance of collaborative content across partnerships.

**Endpoints**

* `GET /&lt;IG_USER_ID&gt;/collaborative_media` — Fetch all collaborative media for the app user
* `GET /&lt;IG_USER_ID&gt;?fields=collaborative_media_search.media_id(&lt;IG_MEDIA_ID&gt;)` — Search for a specific collaborative media

### Partnership Ads Label

_Applies to all versions._

The [Content Publishing API](https://developers.facebook.com/documentation/instagram-platform/content-publishing#partnership-ads-label) now supports adding the &quot;Paid partnership&quot; disclosure label at publish time, eliminating the need to manually add partnership labels after publishing. Two new parameters have been added to the [create media](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#query-string-parameters) endpoint:

* `branded_content_sponsor_ids` — Tag up to 2 brand partners by their Instagram user ID
* `is_paid_partnership` — Enable the &quot;Paid partnership&quot; label with or without naming specific brands

**Endpoint**

* `POST /&lt;IG_USER_ID&gt;/media` with `branded_content_sponsor_ids` and `is_paid_partnership` parameters

See the updated [post-level permissioning guidance](https://developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/partnership-ads/post-level-permissioning#allow-brand-partnerships) for details on brand approval flows.

### Like Media and Comments API

_Applies to all versions._

Introducing the [**Like Media and Comments API**](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/user-likes) on the [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user). The API lets your app like and unlike Instagram media and comments on behalf of your app users, enabling engagement workflows such as responding to comments on business posts or engaging with collaborative content.

**Endpoints**

* `POST /&lt;IG_USER_ID&gt;/likes` with `media_id=&#123;media_id&#125;` or `comment_id=&#123;comment_id&#125;` — Like a Feed post, Reel, comment, or reply
* `DELETE /&lt;IG_USER_ID&gt;/likes` with `media_id=&#123;media_id&#125;` or `comment_id=&#123;comment_id&#125;` — Unlike a Feed post, Reel, comment, or reply

The new `instagram_manage_engagement` permission is required. Stories and content from private accounts are not supported.

## March 30, 2026

### Creator Marketplace
_Applies to all versions._

The Creator Marketplace API now includes several new capabilities for discovering and evaluating creators:  

* **Rate limit increase:** Account-level rate limits for the Discovery API have increased from 240 to 1,000 queries per user per hour, enabling faster, higher-volume creator search.
* **Profile picture URL:** A new `profile_picture_url` field is available when querying creator profiles.
* **Past partnership ads media:** You can now query a creator&#039;s historical partnership ads media that the creator owns.  
* **New filters:** Three new filtering options — follower growth (top growth in last 30 days), latest activity (recently posted creators), and device type (iOS/Android audience filtering).

See [Creator Marketplace API](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/creator-marketplace) documentation for more information.

### Partnership Ads
_Applies to all versions._

* **Username filtering on ad permissions:** The `/&#123;business-account-id&#125;/branded_content_ad_permissions` endpoint now supports filtering by `creator_username`, allowing you to search and retrieve ad permissions for a specific creator. See [Account-Level Permissioning](https://developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/partnership-ads/account-level-permissioning) for more information.
* **Ad code generation:** Creators can now generate partnership ad codes through the API, enabling automated workflows for branded content authorization. See [Ad Codes](https://developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/partnership-ads/ad-codes) for more information.

## March 13, 2026

The Instagram Direct Send API now supports sending the images with attachment IDs (in addition to image URLs) which resolves the problem of timeouts when uploading multiple large high-quality images from slow servers. You can use the attachment API to upload the images one at a time and reuse the attachment IDs to send the same image to multiple users. See the [updated dev docs](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api).

## February 6, 2026

Added support for the `enable_fb_login` parameter in Instagram OAuth authorization requests. This allows developers to control whether the Facebook Login option is shown on the Instagram login page prior to authorization. The default value is `true`. See [Business Login for Instagram](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login) for more information.

## December 19, 2025
### Instagram PDF Attachment

You can now upload and send PDF file attachment in Instagram Direct using [Facebook Graph API](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/send-message) for Instagram accounts linked with a Facebook page OR the [Instagram API](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api) for Intagram-only accounts.

## December 12, 2025

The Instagram Messaging webhook now includes link sticker URLs when users reply to stories via direct message. A new `link_sticker_url` field has been added to the `reply_to.story` object in webhook payloads.

This new field can be used to trigger different messaging automations based on Link Sticker URL in the story.

## December 3, 2025

### Accept/Decline Collaboration Invites

_Applies to all versions._

Introducing [**Accept/Decline Collaboration Invites**](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/collaboration) in [Instagram API with Facebook Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login) on the [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user). The API provides the following capabilites:

* Query all the IG Media(s) where the app user&#039;s Instagram user has been invited for collaboration
* Accept/Decline a collaboration invite using `media_id` of the tagged IG Media

**Endpoints**

* `GET /&lt;IG_USER_ID&gt;/collaboration_invites`
* `POST /&lt;IG_USER_ID&gt;/collaboration_invites`

`instagram_basic` permission is required to access these endpoints.

### Insights Metrics

_Applies to all versions._

Introducing the following metrics fields for media insights:

* `reels_skip_rate`

* `reposts`

Introducing the following metrics fields for user insights:

* `reposts`

Additional views metric for Reels crossposted to Facebook:

* `crossposted_views`

* `facebook_views`

Currently, the IG Insights API only returns metrics native to Instagram. However, certain media type like Reels can be crossposted to Facebook, and the aggregation of the views on both platforms shows up on the native Instagram app. Now, `crossposted_views` returns the total number of views for reels that are crossposted to Facebook across both platforms. `facebook_views` returns the total number of views specifically from Facebook.

This change does not affect the Business Discovery API. For media accessed via this API, `view_count` will continue to reflect only Instagram views and will not include aggregated crossposted views.

### Supporting Trial Reels in the Content Publishing API

_Applies to all versions._

Introducing **Trial Reels Support** in [Instagram API with Facebook Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login) and [Instagram API with Instagram Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login) for the [Content Publishing API](https://developers.facebook.com/documentation/instagram-platform/content-publishing).

`trial_params` is optional and part of the [create media](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#creating) endpoint. Users will be able to specify a Trial Reel configuration to create and publish Trial Reels directly from the Instagram API.

### Delete Instagram Media

_Applies to all versions._

```
DELETE /&#123;ig_media_id&#125;
```

The new API lets your app delete Instagram posts, carousels, reels and stories from your app user’s Instagram account with a new required permission `instagram_manage_contents`.

Read more about the Instagram Media Delete API [**here**](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media).

## November 10, 2025

We now support an [Instagram Professional account messaging itself](https://developers.facebook.com/documentation/instagram-platform/self-messaging).

## November 3, 2025

You can now send a collection of images in Instagram Direct. See the [updated dev docs](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api).
**Warning:** November 3, 2025: Multi-image sending is a Beta feature that will be rolled out incrementally over a few weeks . While the feature is rolled out, some Instagram accounts may get an error response [`2534068`](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api#send-images) to indicate that the feature is not yet available for that account.

## September 23, 2025

Businesses can now display typing indicators and mark_seen indicators in a conversation to let message recipients know that the business has seen and are processing their message, using [Sender Actions](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api/sender-actions).

## Sept 10, 2025

_Applies to all versions._

Introducing the new `message_edit` webhook subscription supporting both use cases of both Business Login for Instagram and Facebook Login for Business. Sample `message_edit` webhook can be found [here](https://developers.facebook.com/documentation/instagram-platform/webhooks/examples?locale=en_US#message-edit)

## June 16, 2025

_Applies to all versions._

Introducing the new `view_count` field on the [IG Media endpoint](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#fields). This field is only available using the [Business Discovery API](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/business_discovery) for Instagram Reels.

## June 14, 2025

### Business Login for Instagram

_Applies to all versions._

Introducing the `force_reauth` parameter for Business Login for Instagram. When included in the login flow, this parameter fixes the broken login experience by forcing the app user to reauthenticate even if the user is already logged into Instagram.

We recommend adding the `force_reauth` parameter to your app&#039;s Business Login for Instagram flow, especially if your app users log in on mobile devices.

#### Deprecation

_Applies to all versions._

The following parameters have been deprecated for Business Login for Instagram:

* `enable_fb_login`
* `force_authentication`

## April 8, 2025

### Meta oEmbed Read Feature

_Applies to all versions._

Introducing the new [**Meta oEmbed Read**](https://developers.facebook.com/docs/features-reference/meta-oembed-read) feature that is replacing the existing oEmbed Read feature. The current [oEmbed Read feature](https://developers.facebook.com/docs/features-reference/oembed-read) will be deprecated on November 3, 2025.

* Apps created after April 8, 2025 that implement oEmbed will use the new Meta oEmbed Read feature.
* Existing apps that already use the current oEmbed Read feature will be automatically updated to the new Meta oEmbed Read feature by November 3, 2025.

Read the [oEmbed Updates blog post](https://developers.facebook.com/blog/post/2025/04/08/oembed-updates/) from Meta to learn more.

### oEmbed Response Updates

_Applies to all versions._

The `author_name`, `author_url`, `thumbnail_url`, `thumbnail_width`, and `thumbnail_height` fields will be removed from the Facebook post, Facebook video, and Instagram post oEmbed response. The Facebook page post oEmbed endpoint will be deprecated. These changes will apply across all API versions on November 3, 2025.

## January 21, 2025

#### Insights APIs

_Applies to all versions._

[Insights APIs for both media and user objects](https://developers.facebook.com/documentation/instagram-platform/insights) are now available for apps that have implemented Instagram API with Instagram Login.

#### Insights metrics

Introducing the following metrics field for media and user insights:

* `views`

##### Metric Deprecations

_Applies to v22.0+. Will apply to all versions April 21, 2025._

* `clips_replays_count` on media insights
* `ig_reels_aggregated_all_plays_count` on media insights
* `impressions` on media and user insights
* `plays` on media insights

**Note:** API requests with the impressions metric will continue to return data for media created on or before July 1, 2024 for v21.0 and older. API requests made after April 21, 2025 for media created on or after July 2, 2024 will return an error.

#### v1.0 Endpoint Deprecations

*Applies to v22.0+. Will apply to all versions April 21, 2025 May 20, 2025.
*

The [Instagram v1.0 API](https://developers.facebook.com/documentation/ads-commerce/marketing-api/reference) is deprecated.

The following endpoints are affected:

* `GET /&#123;instagram-user-id&#125;`
* `GET /&#123;instagram-user-id&#125;/agencies`
* `GET /&#123;instagram-user-id&#125;/upcoming-events`
* `GET /&#123;instagram-user-id&#125;/authorized-adaccounts`
* `POST /&#123;instagram-user-id&#125;/upcoming-events`
* `POST /&#123;instagram-user-id&#125;/authorized-adaccounts`
* `GET /&#123;instagram-media-id&#125;`
* `GET /&#123;instagram-media-id&#125;/comments`
* `GET /&#123;instagram-carousel-id&#125;`
* `GET /&#123;instagram-carousel-id&#125;/comments`
* `GET /&#123;instagram-comment-id&#125;`
* `GET /&#123;instagram-comment-id&#125;/replies`
* `POST /&#123;instagram-media-id&#125;/comments`
* `POST /&#123;instagram-carousel-id&#125;/comments`
* `POST /&#123;instagram-comment-id&#125;/replies`
* `POST /&#123;instagram-comment-id&#125;`
* `DELETE /&#123;instagram-comment-id&#125;`
* `GET /&#123;page-id&#125;/instagram-accounts`
* `GET /&#123;page-id&#125;/page-backed-instagram-accounts`
* `GET /&#123;business-id&#125;/owned-instagram-accounts`
* `GET /&#123;business-id&#125;/instagram-accounts`
* `GET /&#123;business-asset-group-id&#125;/contained-instagram-accounts`
* `GET /&#123;fb-business-user-id&#125;/assigned-instagram-accounts`
* `GET /&#123;fb-user-id&#125;/assigned-instagram-accounts`
* `GET /&#123;fb-system-user-id&#125;/assigned-instagram-accounts`
* `GET /&#123;ad account id&#125;/instagram-accounts`
* `GET /&#123;ad account id&#125;/connected-instagram-accounts-with-iabp`
* `POST /&#123;page-id&#125;/page-backed-instagram-accounts`
* `DELETE /&#123;business-id&#125;/instagram-accounts`

Please migrate your API calls to the
[Instagram Platform endpoints.](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login)

## December 4, 2024

#### Instagram Basic Display API
_Applies to all versions._

The Instagram Basic Display API has been deprecated. All requests to the Instagram Basic Display API will return an error message. We recommend that you migrate your app to the
[**Instagram API**](https://developers.facebook.com/documentation/instagram-platform)
to avoid any disruption to your services.

[Visit our **News for Developers blog post** to learn more.](https://developers.facebook.com/blog/post/2024/09/04/update-on-instagram-basic-display-api/)

## October 3, 2024

Welcome Message Flows now available for Instagram API with Instagram Login. [Learn more.](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/welcome-message-ads)

## October 2, 2024

#### Media Insights
*Applies to v21.0+. Will apply to all versions on January 8, 2025.*

The video media metric `video_views` will no longer be supported.

The following endpoints and metrics are affected:

* [`GET /&#123;ig-media-id&#125;/insights`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights)
    * `video_views`

#### User Insights
*Applies to v21.0+. Will apply to all versions on January 8, 2025.*

The `email_contacts`, `get_direction_clicks`, `profile_views`, `text_message_clicks`, `website_clicks`, and `phone_call_clicks` time series metrics will no longer be supported.

The following endpoints and metrics are affected:

* [`GET /&#123;ig-user-id&#125;/insights`](https://developers.facebook.com/documentation/instagram-platform/api-reference/instagram-user/insights)
    * `email_contacts`
    * `get_direction_clicks`
    * `profile_views`
    * `text_message_clicks`
    * `website_clicks`
    * `phone_call_clicks`


## September 17, 2024

### New `scope` values
_Applies to all versions._

To ensure consistency between `scope` values and permission names, we are introducing new `scope` values for the Instagram API with Instagram login. The new `scope` values are:

* `instagram_business_basic`
* `instagram_business_content_publish`
* `instagram_business_manage_comments`
* `instagram_business_manage_messages`

These will replace the existing `business_basic`, `business_content_publish`, `business_manage_comments` and `business_manage_messages` values, respectively.

Please note that the old `scope` values will be deprecated on **January 27, 2025**. It is essential to update your code before this date to avoid any disruption in your app&#039;s functionality. Failure to do so will result in your app being unable to call the Instagram endpoints.

_Correction: Deprecation date moved from December 17, 2024 to January 27, 2025._

## July 23, 2024

### Launch of the new Instagram API with Instagram Login

[Components of this new Instagram API:](https://developers.facebook.com/documentation/instagram-platform/overview)

* A Facebook Page will no longer be required
* The host URL for API calls is `graph.instagram.com`
* New permissions for this API:
    * `instagram_business_basic`
    * `instagram_business_content_publish`
    * `instagram_business_manage_comments`
    * `instagram_business_manage_messages`
* The Messenger API will no longer be used to send Instagram messages
* New apps will add the new **Instagram** product when creating a Meta app
* Existing apps can add the new **Instagram** product in the App Dashboard

[Visit our migration guide to learn if this new Instagram API with Instagram Login is right for you](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/migration-guide).

## June 11, 2024

#### Instagram Comment Webhooks
_Applies to all versions._

In addition to the `ad_id` and `ad_title`, the `original_media_id` will be returned in the `media` object of the `comments` field&#039;s `value` object when a person comments on a [boosted Instagram post or Instagram ads post](https://help.instagram.com/1067656009937668). For more information, refer to [Set Up Webhooks for Instagram](https://developers.facebook.com/documentation/instagram-platform/webhooks).

## May 21, 2024

#### Instagram User Insights
*Applies to v20.0+. Will apply to all versions on August 19, 2024.*

The `last_14_days`, `last_30_days`, `last_90_days` and `prev_month` timeframes will no longer be supported for the `reached_audience_demographics` and `engaged_audience_demographics` metrics.

The following endpoints and metrics are affected:

* [`GET /&#123;ig-user-id&#125;/insights`](https://developers.facebook.com/documentation/instagram-platform/api-reference/instagram-user/insights)
    * `engaged_audience_demographics`
    * `reached_audience_demographics`


## September 12, 2023

#### Deprecation of Media and User Insights
*Applies to v18.0+. Will apply to all versions on December 11, 2023.*

Duplicative and legacy Instagram insight metrics are being deprecated. Please see documentation for the endpoints and [Instagram Insights](https://developers.facebook.com/documentation/instagram-platform/insights) for more information on which metrics to use in their place.

The following endpoints and metrics are affected:

* [`GET /&#123;ig-user-id&#125;/insights`](https://developers.facebook.com/documentation/instagram-platform/api-reference/instagram-user/insights)
    * `AUDIENCE_GENDER_AGE`
    * `AUDIENCE_LOCALE`
    * `AUDIENCE_COUNTRY`
    * `AUDIENCE_CITY`
* [`GET /&#123;ig-media-id&#125;/insights`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights)
    * `CAROUSEL_ALBUM_IMPRESSIONS`
    * `CAROUSEL_ALBUM_REACH`
    * `CAROUSEL_ALBUM_ENGAGEMENT`
    * `CAROUSEL_ALBUM_SAVED`
    * `CAROUSEL_ALBUM_VIDEO_VIEWS`
    * `TAPS_FORWARD`
    * `TAPS_BACK`
    * `EXITS`
    * `ENGAGEMENT`

**Note:** `total_interactions`, which is listed as an alternative for some of the deprecated metrics, is currently only available using version 18.0 and does not work with older versions. When querying older versions before Dec 11, 2023, please use the `engagement` metric.`total_interactions`, which is listed as an alternative for some of the deprecated metrics, is currently only available using version 18.0 and does not work with older versions. When querying older versions before Dec 11, 2023, please use the `engagement` metric.


## November 9, 2022

#### Instagram Webhooks
_Applies to all versions._

The `ad_id` and `ad_title` will be returned in the `media` object of the `comments` field&#039;s `value` object when a person comments on a [boosted Instagram post  or Instagram ads post](https://help.instagram.com/1067656009937668).

## October 31st

#### Reels – Product Tags

_Applies to all versions._

Instagram Product Tagging API for Reels is made available. You can tag up to 30 products when publishing a reel.

## June 28, 2022

#### Reels

_Applies to all versions._

Reels are now supported. To publish a video as a reel, set the `media_type` parameter to `REELS` when creating a [single media post](https://developers.facebook.com/documentation/instagram-platform/content-publishing#single-media-posts) container. Refer to the [`POST /ig-user/media endpoint`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#creating) reference to learn which parameters can be used with reels as well as requirements for reels videos.

**Note:** Beginning November 9, 2023, the `VIDEO` value for `media_type` will no longer be supported. Use the `REELS` media type to publish a video to your feed.

## June 27, 2022

#### Legacy Instagram API Documentation

_Applies to all versions._

The [Legacy Instagram API developer documentation](https://www.instagram.com/developer/) has been removed and now redirects to the [Instagram Platform](https://developers.facebook.com/documentation/instagram-platform) developer documentation.

## June 20, 2022

#### Product Tagging

_Applies to all versions._

You can now create and manage [Instagram Shopping Product Tags](https://help.instagram.com/2022466637835789) on an Instagram Business&#039;s published media. Refer to the [Product Tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging) guide to learn how.

## May 27, 2022

#### Product Variants

_Applies to all versions._

For partners in the [Product Tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging) beta, all [product variants](https://developers.facebook.com/documentation/ads-commerce/catalog/guides/product-variants) that match a query&#039;s search criteria will now be returned when [searching a catalog for products](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging#get-eligible-products).

## March 15, 2022

#### Carousel Posts

_Applies to all versions._

You can now use the Instagram API to publish posts containing multiple images and videos ([carousel posts](https://developers.facebook.com/documentation/instagram-platform/content-publishing#carousel-posts)). Refer to the [Content Publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing) guide for complete publishing steps.

If your app has already been approved for [permissions](https://developers.facebook.com/documentation/instagram-platform/content-publishing#permissions) required for content publishing, it does not need to undergo [App Review](https://developers.facebook.com/docs/app-review) again to take advantage of this functionality.

## November 9, 2021

#### Live Videos
_Applies to all versions._

You can now use the Instagram API to get live video IG Media being broadcast by your app users, get comments on those videos, and use the Instagram Messaging API to send private replies (direct messages) to the comment authors. To support this functionality, the following changes have been made:

- a new [GET /ig-user/live_media](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/live_media#reading) edge can return live video [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) being broadcast by your app user at the time of the request
- the `media` field on an [IG Comment](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) now returns and object containing both the ID (`id`) and published location (`media_product_type`) of the media upon which the comment was made
- a new [`live_comments`](https://developers.facebook.com/docs/graph-api/webhooks/reference/instagram#live_comments) Instagram Webhooks field can send notifications containing live comments made on your app users&#039; live videos as they are being broadcast

Please refer to the [Instagram Messaging API](https://developers.facebook.com/documentation/business-messaging/instagram-messaging) private replies documentation to learn how to send [private replies](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/private-replies) to users who have commented on your app users&#039; live video IG Media.

## October 20, 2021

#### IG Comments
_Applies to all versions._

Two new [fields](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment#fields) have been added to [IG Comments](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment):

* `from` — returns an object containing the [IGSID](https://developers.facebook.com/docs/messenger-platform/instagram/overview#igsid) (`id`) and username (`username`) of the comment creator.
* `parent_id` — returns the ID of the parent IG Comment if this comment was created on another IG Comment (i.e. a reply to another comment).

#### Instagram Webhooks
_Applies to all versions._

The `comments` Instagram webhooks [field](https://developers.facebook.com/docs/graph-api/webhooks/reference/instagram#comments) now includes the following properties in the `value` field object:

- `from.id` — [IGSID](https://developers.facebook.com/docs/messenger-platform/instagram/overview#igsid) of the Instagram user who created the comment.
- `from.username` — Username of the Instagram user who created the comment
- `media.id` — ID of the IG Media upon which the comment was made.
- `media.media_product_type` — Surface (published location) of the IG Media upon which the comment was made.
- `parent_id` — ID of parent IG Comment if this comment was created on another IG Comment (i.e. a reply to another comment).

## October 5, 2021

The following changes apply to Instagram TV videos created on or after October 5, 2021. Instagram TV videos created before this date are exempt from these changes.

* the `media_product_type` [field](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#fields) will return `FEED` instead of `IGTV`
* the `video_title` [field](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#fields) will not be returned
* [Instagram Webhooks](https://developers.facebook.com/documentation/instagram-platform/webhooks) `comments` and `mentions` fields are now supported

On January 3, 2022, the changes above will apply to all API versions and all Instagram TV videos, regardless of video creation date. This means that starting January 3, 2022, apps using older API versions will be able to query Instagram TV videos (read support was introduced in v10.0 and limited to v10.0+).

Starting with v14.0, the `video_title` field will no longer be supported and the API will throw an error if the field is requested.

## June 8, 2021

#### Like Counts

_Applies to v11.0+. Will apply to all versions September 7, 2021._

If indirectly querying an [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) through another endpoint or field expansion, the [`like_count`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#fields) field will be omitted from API responses if the media owner has hidden like counts on it. Directly querying the IG Media (which can only be done by the IG Media owner) will return the actual like count, however, even if like counts have been hidden.

#### Time-based Pagination

_Applies to v11.0+_.

Added [`since`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#query-string-parameters) and [`until`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#query-string-parameters) parameters to the [`GET /&#123;ig-user-id&#125;/media`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#reading) endpoint to support [time-based pagination](https://developers.facebook.com/docs/graph-api/using-graph-api#time).

## May 26, 2021

If indirectly querying an IG Media through another endpoint, the [like_count](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#fields) field will now return `0` if the app user does not [own](https://developers.facebook.com/documentation/instagram-platform/overview#authorization) the media and the media owner has [hidden](https://www.facebook.com/help/instagram/113355287252104) like counts on it. Directly querying the IG Media, which can only be done by the IG Media owner, will return the actual like count, even if the owner has hidden like counts on the media.

## May 4, 2021

Made a minor change to how we calculate the [`online_followers`](https://developers.facebook.com/documentation/instagram-platform/api-reference/instagram-user/insights#metrics-and-periods) metric on IG Users.

## April 14, 2021

Story [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights#metrics) interactions performed by users in Japan are no longer included in some `replies` metric calculations:

* For stories created by users in Japan, the `replies` metric will now return a value of `0`.
* For stories created by users outside Japan, the `replies` metric will return the number of replies, but replies made by users in Japan will not be included in the calculation.

## April 12, 2021

Fixed a minor bug with reach [metrics](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights#metrics) on story IG Media.

## April 9, 2021

- The `status` field on an [IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) now returns an [error subcode](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/error-codes) if the container&#039;s `error_code` field value is `ERROR`.
- The [IG Media Insights](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights) `video_views` metric now supports albums and will return the sum of `video_views` on all videos in the album instead of `0`.

## March 16, 2021

IGTV media is [now supported in v10.0+](https://developers.facebook.com/blog/post/2021/03/15/igtv-media-mmetrics-instagram-graph-api/). This applies to all endpoints except those used for content publishing and webhooks. To support this change, new `media_product_type` and `video_title` fields have been added to the [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) node. IGTV media must have been shared to Instagram at the time of publish (**Post a Preview** or **Share Preview** to Feed enabled) in order to be accessible via the API.

## Januray 26, 2021

The Content Publishing beta has ended and all developers can now publish media on Instagram Professional accounts. Refer to the [Content Publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing) guide for usage details.

## December 2, 2020

In compliance with the European Union&#039;s [ePrivacy Directive](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A02002L0058-20091219), messaging-related Story [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) interactions performed by users in the European Economic Area (EEA) after December 1, 2020, will no longer be included in some metric calculations:

- For Stories created by users in the EEA, the [`replies`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights#metrics) metric will now return a value of `0`.
- For Stories created by users outside the EEA, the [`replies`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights#metrics) metric will return the number of replies, but replies made my users in the EEA will not be included in its calculation.

This change applies to all versions.

## November 10, 2020

- **IG User Insights** — The [`follower_count`](https://developers.facebook.com/documentation/instagram-platform/api-reference/instagram-user/insights) values now align more closely with their corresponding values displayed in the Instagram app. In addition, [`follower_count`](https://developers.facebook.com/documentation/instagram-platform/api-reference/instagram-user/insights) now returns a maximum of 30 days of data instead of 2 years. This change applies to v9.0+ and will apply to all versions May 9, 2021.

## May 5, 2020

- **Hashtag Search** — _This change applies to v7.0+_ — You can now request the `timestamp` field on [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) returned by [`GET /&#123;ig-hashtag-id&#125;/top_media`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-hashtag/top-media#reading) and [`GET /&#123;ig-hashtag-id&#125;/recent_media`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-hashtag/recent-media#reading) [Hashtag Search](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/hashtag-search) queries. For example: `GET /&#123;ig-hashtag-id&#125;/top_media?fields=timestamp`.

## December 3, 2019

- **Insights** — To align API behavior with Instagram app behavior, insights on [IG Users](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) are now only available on IG Users that have 100 or more followers.

## August 13, 2019

- **Business Discovery** — The [Business Discovery API](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/business_discovery) can now be used to get data about other Instagram Creator accounts.

## May 22, 2019

- **Instagram Creator Accounts** — The API now supports [Instagram Creator Accounts](https://help.instagram.com/1158274571010880), with two exceptions. (1) The [Content Publishing API](https://developers.facebook.com/documentation/instagram-platform/content-publishing) cannot be used by Instagram Creators, and (2) the [Business Discovery API](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/business-discovery) can be used by Creators but can only target Businesses.

## May 9, 2019

- **Webhooks** — The `story_insights` field now requires the `instagram_manage_insights` permission instead of `instagram_manage_comments`.

## October 31, 2018

- **Hashtag Search API** — You can now search for media tagged with specific hashtags by using our new [Hashtag Search API](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/hashtag-search). `#spooky`!

## October 23, 2018

- `/&#123;ig-media-id&#125;/comments` edge — `GET` requests made using API version 3.1 or older will have results returned in chronological order. Requests made using version 3.2+ will have results returned in reverse chronological order.

## June 7, 2018

- `/&#123;ig-media-id&#125;` node — You can now use field expansion to get the `permalink` field on media objects.

## May 1, 2018

- **Business Verification** — In order to use the Instagram Graph API, all apps must undergo [Business Verification](https://developers.facebook.com/docs/apps/review), which is part of the App Review process and now required for all Instagram Graph API endpoints. Apps previously reviewed before May 1st, 2018, have to be reviewed again, and have until August 1st, 2018 to do so, or lose access to the API.

## April 24, 2018

- `/&#123;ig-comment-id&#125;` node:

-  Added a new `username` field.
-  For `GET` requests, the `user` field will not be included in responses unless the User making the request owns the Comment; instead, we will return `username` for all commenters. This also applies to queries on Comments made through other APIs, such as the Mentions API.

- `/&#123;ig-media-id&#125;` node:

- Added a new `username` field.
- For `GET` requests, the `owner` field will not be included in responses unless the User making the request owns the media object; instead, we will return `username` for all commenters. This also applies to queries on media objects made through other APIs, such as the Mentions API.

## April 23, 2018

- **Insights API** — Insights will now include ad activity generated through the API, Facebook ads interfaces, and Instagram&#039;s Promote feature. This affects the following metrics:

- `impressions`
- `reach`

## March 13, 2018

- **Content Publishing API** — Beta partners can now use the `/&#123;ig-user-id&#125;/media` edge to tag [locations](https://developers.facebook.com/documentation/instagram-platform/content-publishing#publish-with-locations) and public Instagram [users](https://developers.facebook.com/documentation/instagram-platform/content-publishing#publish-with-tagged-users) when publishing photos.

## March 8, 2018

- **Public fields** — The `timestamp` field on the `/&#123;ig-media-id&#125;` node is now a public field and can be returned via field expansion.

## February 22, 2018

- **Public fields** — The `/&#123;ig-user-id&#125;`, `/&#123;ig-comment-id&#125;`, and `/&#123;ig-media-id&#125;` nodes will now return all public fields when accessed through an edge via field expansion. Refer to each node&#039;s reference document to see which fields are public.

## February 8, 2018

- **Content Publishing API** — Beta partners can now include hashtags when publishing photos via the `/&#123;ig-user-id&#125;/media` edge. `#crazywildebeest` FTW!

# IG Media



Represents an Instagram album, photo, or video (uploaded video, live video, reel, or story).

**Warning:** If you are migrating from Marketing API Instagram Ads endpoints to Instagram Platform endpoints, be aware that some field names are different.

Introducing the following field:

* `legacy_instagram_media_id`

The following Marketing API Instagram Ads endpoint fields are not supported:

* `filter_name`
* `location`
* `location_name`
* `latitude`
* `longitude`

## Creating

This operation is not supported.

## Reading &#123;#reading&#125;

**`GET /&lt;IG_MEDIA_ID&gt;`**

Gets [fields](#fields) and [edges](#edges) on Instagram media.

### Requirements

|  | Instagram API with Instagram Login | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User access token | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic` | * `instagram_basic`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;&lt;br&gt;If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to your app user&#039;s Instagram professional account, your app will also need one of:&lt;br&gt;&lt;br&gt;* `ads_management`&lt;br&gt;* `ads_read` |

### Limitations

- Fields such as `comments_count` and `like_count` return engagement on the target Instagram media only and don&#039;t include data from other surfaces. For example, `comments_count` returns the number of comments on a photo, but not comments on ads that contain that photo. Use `total_comments_count` and `total_like_count` to get aggregated counts that include engagement from promoted/boosted/ad media. Crossposted Facebook post&#039;s count may be included if that post is accessible by the session user.
- Captions don&#039;t include the `&#064;` symbol unless the app user is also able to perform admin-equivalent [tasks](https://developers.facebook.com/documentation/pages-api/overview#tasks) on the app.
- Some fields, such as `permalink`, cannot be used on photos within albums (children).
- Live video Instagram Media can only be read while they are being broadcast.
- This API returns only data for media owned by Instagram professional accounts. It can not be used to get data for media owned by personal Instagram accounts.
- The `reposts_count`, `saved_count`, `shares_count`, `total_like_count`, `total_comments_count`, and `total_views_count` fields are not available for carousel child media and are only returned for top-level media objects. The media owner can disable showing likes, comments, views, reposts, and shares — in these cases, the corresponding fields are not returned.

### Request Syntax

```curl
GET https://&lt;HOST_URL&gt;/&lt;API_VERSION&gt;/&lt;IG_MEDIA_ID&gt; \
  ?fields=&lt;LIST_OF_FIELDS&gt; \
  &amp;access_token=&lt;ACCESS_TOKEN&gt;
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&lt;API_VERSION&gt;`&lt;br&gt;&lt;br&gt;**The latest version is:** v25.0&lt;br&gt; | The API version your app is using. If not specified in your API calls this will be the latest version at the time you created your Meta app or, if that version is no longer available, the oldest version available.[Learn more about versioning.](https://developers.facebook.com/docs/graph-api/guides/versioning)&lt;br&gt; |
| `&lt;HOST_URL&gt;` | The [host URL](#requirements) your app is using to query the endpoint. |
| `&lt;IG_MEDIA_ID&gt;` | **Required.** ID for the media to be published. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `&lt;ACCESS_TOKEN&gt;` | **Required.** The app user&#039;s Facebook or Instagram User access token. |
| `fields` | `&lt;LIST_OF_FIELDS&gt;` | Comma-separated list of [fields](#fields) you want returned. |

### Fields

Public fields can be read via field expansion.

| Field | Description |
| --- | --- |
| `alt_text`&lt;br&gt;Public | Descriptive text for images, for accessibility. |
| `boost_ads_list` | Offers an overview of all Instagram ad information associated with the organic media for ads with `ACTIVE` status. It includes relative ad ID and ad delivery status. Available for Instagram API with Facebook Login only. |
| `boost_eligibility_info` | The field provides information about boosting eligibility of a Instagram instagram media as an ad and additional details if not eligible.  Available for Instagram API with Facebook Login only. |
| `caption`&lt;br&gt;Public | Caption. Excludes album children. The `&#064;` symbol is excluded, unless the app user can perform admin-equivalent [tasks](https://developers.facebook.com/documentation/pages-api/overview#tasks) on the Facebook Page connected to the Instagram account used to create the caption.  Available for Instagram API with Facebook Login only. |
| `comments_count`&lt;br&gt;Public | Count of comments on the media. Excludes comments on album child media and the media&#039;s caption. Includes replies on comments. |
| `copyright_check_information.status` | Returns `status` and `matches_found` objects&lt;br&gt;&lt;br&gt;\| status objects \| Description \|&lt;br&gt;\| --- \| --- \|&lt;br&gt;\| `status` \| * `completed` – the detection process has finished&lt;br&gt;* `error` – an error occurred during the detection process&lt;br&gt;* `in_progress` – the detection process is ongoing&lt;br&gt;* `not_started` – the detection process has not started \|&lt;br&gt;\| `matches_found` \| Set to one of the following:&lt;br&gt;&lt;br&gt;* `false` if the video **does not violate** copyright,&lt;br&gt;* `true` if the video **does violate** copyright \|&lt;br&gt;&lt;br&gt;If a video **is violating copyright**, the `copyright_matches` is returned with an array of objects about the copyrighted material, when the violation is occurring in the video, and the actions take to mitigate the violation.&lt;br&gt;&lt;br&gt;\| copyright_matches objects \| Description \|&lt;br&gt;\| --- \| --- \|&lt;br&gt;\| `author` \| the author of the copyrighted video \|&lt;br&gt;\| `content_title` \| the name of the copyrighted video \|&lt;br&gt;\| `matched_segments` \| An array of objects with the following key-value pairs:&lt;br&gt;&lt;br&gt;* `duration_in_seconds` – the number of seconds the content violates copyright&lt;br&gt;* `segment_type` – either `AUDIO` or `VIDEO`&lt;br&gt;* `start_time_in_seconds` – set to the start time of the video \|&lt;br&gt;\| `owner_copyright_policy` \| Objects returned include:&lt;br&gt;&lt;br&gt;* `name` – The name for the copyright owners&#039; policy&lt;br&gt;* `actions` – An array of `action` objects with the mitigations steps taken defined by the copyright owner&#039;s policy. May include different mitigations steps for different locations.&lt;br&gt;    * `action` – The mitigation action taken against the video violating copyright. Different mitigation steps can be taken for different countries. Can be one of the following values:&lt;br&gt;        * `BLOCK` – The video is blocked from the audiences listed in the `geos` array&lt;br&gt;        * `MUTE` - The video is muted for audiences listed in the `geos` array \| |
| `id`&lt;br&gt;Public | Media ID. |
| `is_ai_generated` | Indicates if the media has an AI label. Excludes album children. |
| `is_comment_enabled` | Indicates if comments are enabled or disabled. Excludes album children. |
| `is_shared_to_feed`&lt;br&gt;Public | For Reels only. When `true`, indicates that the reel can appear in both the **Feed** and **Reels** tabs. When `false`, indicates that the reel can only appear in the **Reels** tab.&lt;br&gt;&lt;br&gt;**Warning:** Neither value determines whether the reel actually appears in the **Reels** tab because the reel may not meet eligibilty requirements or may not be selected by our algorithm. See [reel specifications](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#reel-specifications) for eligibility critera. |
| `legacy_instagram_media_id` | The ID for Instagram media that was created for Marketing API endpoints for v21.0 and older. |
| `like_count` | Count of likes on the media, including replies on comments. Excludes likes on album child media and likes on promoted posts created from the media.&lt;br&gt;&lt;br&gt;If queried indirectly through another endpoint or field expansion the `like_count` field is omitted if the media owner has hidden like counts. |
| `media_audio_type`&lt;br&gt;Public | The type of audio used in the media. Can be `MUSIC` or `ORIGINAL_SOUND`. Returned only for video media such as Reels; not returned for other media types (for example, photos and carousels). |
| `media_product_type`&lt;br&gt;Public | Surface where the media is published. Can be `AD`, `FEED`, `STORY` or `REELS`.  Available for Instagram API with Facebook Login only. |
| `media_type`&lt;br&gt;Public | Media type. Can be `CAROUSEL_ALBUM`, `IMAGE`, or `VIDEO`. |
| `media_url`&lt;br&gt;Public | The URL for the media.&lt;br&gt;&lt;br&gt;**Warning:** The `media_url` field is omitted from responses if the media contains copyrighted material or has been flagged for a copyright violation.  Examples of copyrighted material can include audio on Reels. |
| `owner`&lt;br&gt;Public | Instagram user ID who created the media. Only returned if the app user making the query also created the media; otherwise, `username` field is returned instead. |
| `permalink`&lt;br&gt;Public | Permanent URL to the media. |
| `shortcode`&lt;br&gt;Public | Shortcode to the media. |
| `thumbnail_url`&lt;br&gt;Public | Media thumbnail URL. Only available on `VIDEO` media. |
| `timestamp`&lt;br&gt;Public | [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601)-formatted creation date in UTC (default is UTC ±00:00). |
| `username`&lt;br&gt;Public | Username of user who created the media. |
| `view_count`&lt;br&gt;Public | View count for Instagram Reels, which includes both **paid and organic metrics.** For content crossposted to Facebook, this returns combined Instagram and Facebook view counts if the Facebook post is accessible by the session user.&lt;br&gt;&lt;br&gt;Available for [Business Discovery API](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/business-discovery) only. |
| `reposts_count`&lt;br&gt;Public | Number of times the media has been reposted. Available for FEED and REELS media. Not accessible through hashtag API endpoints. Available for Instagram API with Facebook Login only. |
| `saved_count` | Number of times the media has been saved. Available for FEED and REELS media. Only accessible by the media owner or an accepted collaborator. Not accessible through Business Discovery, tagged/mentioned media, or hashtag API endpoints. Available for Instagram API with Facebook Login only. |
| `shares_count` | Number of times the media has been shared. Available for FEED and REELS media. Not accessible through Business Discovery or hashtag API endpoints. Available for Instagram API with Facebook Login only. |
| `total_comments_count`&lt;br&gt;Public | Total number of comments on the media across all surfaces, including comments on associated promoted/boosted media. Not accessible through hashtag API endpoints. Available for Instagram API with Facebook Login only. |
| `total_like_count`&lt;br&gt;Public | Total number of likes on the media across all surfaces, including likes on associated promoted/boosted media. Not accessible through hashtag API endpoints. Available for Instagram API with Facebook Login only. |
| `total_views_count` | Total view count of video content across all surfaces, including views from promoted/boosted media and replays. Only available for video media. Not accessible through Business Discovery or hashtag API endpoints. For Business Discovery, use `view_count` instead. Available for Instagram API with Facebook Login only. |

### Edges

Public edges can be returned through field expansion.

| Edge | Description |
| --- | --- |
| [`children`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-media/children)&lt;br&gt;Public. | Represents a collection of [Instagram Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects on an album [Instagram Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media). |
| [`collaborators`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-media/collaborators) | Represents a list of users who are added as collaborators on an [Instagram Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object.  Available for Instagram API with Facebook Login only. |
| [`comments`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-media/comments) | Represents a collection of [Instagram Comments](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) on an [Instagram Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object. |
| [`insights`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights) | Represents social interaction metrics on an [Instagram Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object. |

### cURL Example

#### Example request

```curl
curl -X GET \
  &#039;https://graph.instagram.com/v25.0/17895695668004550?fields=id,media_type,media_url,owner,timestamp&amp;access_token=IGQVJ...&#039;
```

#### Example response

```json
&#123;
  &quot;id&quot;: &quot;17918920912340654&quot;,
  &quot;media_type&quot;: &quot;IMAGE&quot;,
  &quot;media_url&quot;: &quot;https://sconten...&quot;,
  &quot;owner&quot;: &#123;
    &quot;id&quot;: &quot;17841405309211844&quot;
  &#125;,
  &quot;timestamp&quot;: &quot;2019-09-26T22:36:43+0000&quot;
&#125;
```

## Updating

**`POST /&lt;IG_MEDIA_ID&gt;`**

Enable or disable comments on an Instagram Media.

### Requirements

|  | Instagram API with Instagram Login | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User access token | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_comments` | * `instagram_basic`&lt;br&gt;* `instagram_manage_comments`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;&lt;br&gt;If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need one of:&lt;br&gt;&lt;br&gt;* `ads_management`&lt;br&gt;* `ads_read` |

### Limitations

Live video Instagram Media not supported.

### Request Syntax

```curl
POST https://&lt;HOST_URL&gt;/&lt;API_VERSION&gt;/&lt;IG_MEDIA_ID&gt;
  ?comment_enabled=&lt;BOOL&gt;
  &amp;access_token=&lt;ACCESS_TOKEN&gt;
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&lt;API_VERSION&gt;`&lt;br&gt;&lt;br&gt;**The latest version is:** v25.0&lt;br&gt; | The API version your app is using. If not specified in your API calls this will be the latest version at the time you created your Meta app or, if that version is no longer available, the oldest version available.[Learn more about versioning.](https://developers.facebook.com/docs/graph-api/guides/versioning)&lt;br&gt; |
| `&lt;HOST_URL&gt;` | The [host URL](#requirements) your app is using to query the endpoint. |
| `&lt;IG_MEDIA_ID&gt;` | **Required.** ID for the media to be published. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `&lt;ACCESS_TOKEN&gt;` | **Required.** App user&#039;s [user access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens). |
| `comment_enabled` | `&lt;BOOL&gt;` | **Required.** Set to `true` to enable comments or `false` to disable comments. |

### cURL Example

#### Example request

```curl
curl -i -X POST \
 &quot;https://graph.instagram.com/v25.0/17918920912340654?comment_enabled=true&amp;access_token=EAAOc...&quot;
```

#### Example response

```json
&#123;
  &quot;success&quot;: true
&#125;
```

## Deleting &#123;#delete&#125;

**`DELETE /&lt;IG_MEDIA_ID&gt;`**

Delete Instagram Media.

### Requirements
|  | Instagram API with Facebook Login |
| --- | --- |
| **Access Tokens** | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.facebook.com` |
| **Login Type** | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_basic`&lt;br&gt;* `instagram_manage_contents` |

### Limitations

This api only supports Instagram API with Facebook login only. Non-ad posts, Stories, Reels and entire carousel albums are supported. To delete media inside carousel albums, the entire carousel album must be deleted by specifying the carousel container media id. Individually deleting media within a carousel is not supported.

### Request Syntax

```curl
POST https://graph.facebook.com/&lt;API_VERSION&gt;/&lt;IG_MEDIA_ID&gt;
  ?access_token=&lt;ACCESS_TOKEN&gt;
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&lt;API_VERSION&gt;`&lt;br&gt;&lt;br&gt;**The latest version is:** v25.0&lt;br&gt; | The API version your app is using. If not specified in your API calls this will be the latest version at the time you created your Meta app or, if that version is no longer available, the oldest version available.[Learn more about versioning.](https://developers.facebook.com/docs/graph-api/guides/versioning)&lt;br&gt; |
| `&lt;IG_MEDIA_ID&gt;` | **Required.** ID for the media to be published. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `&lt;ACCESS_TOKEN&gt;` | **Required.** App user&#039;s [user access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens). |

### cURL Example

#### Example request

```curl
curl -i -X DELETE \
 &quot;https://graph.facebook.com/v25.0/17918920912340654?comment_enabled=true&amp;access_token=EAAOc...&quot;
```

#### Example response (Success)

```json
&#123;
  &quot;success&quot;: true,
  &quot;deleted_id&quot;: &quot;17918920912340654&quot;
&#125;
```

#### Example response (Failure, Media Type Not Supported)

```json
&#123;
  &quot;error&quot;: &#123;
   &quot;message&quot;: &quot;Fatal&quot;,
   &quot;type&quot;: &quot;OAuthException&quot;,
   &quot;code&quot;: -1,
   &quot;error_subcode&quot;: 2207073,
   &quot;is_transient&quot;: false,
   &quot;error_user_title&quot;: &quot;Media Type Not Supported&quot;,
   &quot;error_user_msg&quot;: &quot;The media type is not supported for this endpoint&quot;,
   &quot;fbtrace_id&quot;: &quot;Api-OlNdfcpOwIu6hNaT5Kw&quot;
  &#125;,
&#125;
```

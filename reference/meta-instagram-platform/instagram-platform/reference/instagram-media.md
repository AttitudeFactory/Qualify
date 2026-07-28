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

## Reading {#reading}

**`GET /<IG_MEDIA_ID>`**

Gets [fields](#fields) and [edges](#edges) on Instagram media.

### Requirements

|  | Instagram API with Instagram Login | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User access token | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic` | * `instagram_basic`<br>* `pages_read_engagement`<br><br>If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to your app user's Instagram professional account, your app will also need one of:<br><br>* `ads_management`<br>* `ads_read` |

### Limitations

- Fields such as `comments_count` and `like_count` return engagement on the target Instagram media only and don't include data from other surfaces. For example, `comments_count` returns the number of comments on a photo, but not comments on ads that contain that photo. Use `total_comments_count` and `total_like_count` to get aggregated counts that include engagement from promoted/boosted/ad media. Crossposted Facebook post's count may be included if that post is accessible by the session user.
- Captions don't include the `@` symbol unless the app user is also able to perform admin-equivalent [tasks](https://developers.facebook.com/documentation/pages-api/overview#tasks) on the app.
- Some fields, such as `permalink`, cannot be used on photos within albums (children).
- Live video Instagram Media can only be read while they are being broadcast.
- This API returns only data for media owned by Instagram professional accounts. It can not be used to get data for media owned by personal Instagram accounts.
- The `reposts_count`, `saved_count`, `shares_count`, `total_like_count`, `total_comments_count`, and `total_views_count` fields are not available for carousel child media and are only returned for top-level media objects. The media owner can disable showing likes, comments, views, reposts, and shares — in these cases, the corresponding fields are not returned.

### Request Syntax

```curl
GET https://<HOST_URL>/<API_VERSION>/<IG_MEDIA_ID> \
  ?fields=<LIST_OF_FIELDS> \
  &access_token=<ACCESS_TOKEN>
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `<API_VERSION>`<br><br>**The latest version is:** v25.0<br> | The API version your app is using. If not specified in your API calls this will be the latest version at the time you created your Meta app or, if that version is no longer available, the oldest version available.[Learn more about versioning.](https://developers.facebook.com/docs/graph-api/guides/versioning)<br> |
| `<HOST_URL>` | The [host URL](#requirements) your app is using to query the endpoint. |
| `<IG_MEDIA_ID>` | **Required.** ID for the media to be published. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `<ACCESS_TOKEN>` | **Required.** The app user's Facebook or Instagram User access token. |
| `fields` | `<LIST_OF_FIELDS>` | Comma-separated list of [fields](#fields) you want returned. |

### Fields

Public fields can be read via field expansion.

| Field | Description |
| --- | --- |
| `alt_text`<br>Public | Descriptive text for images, for accessibility. |
| `boost_ads_list` | Offers an overview of all Instagram ad information associated with the organic media for ads with `ACTIVE` status. It includes relative ad ID and ad delivery status. Available for Instagram API with Facebook Login only. |
| `boost_eligibility_info` | The field provides information about boosting eligibility of a Instagram instagram media as an ad and additional details if not eligible.  Available for Instagram API with Facebook Login only. |
| `caption`<br>Public | Caption. Excludes album children. The `@` symbol is excluded, unless the app user can perform admin-equivalent [tasks](https://developers.facebook.com/documentation/pages-api/overview#tasks) on the Facebook Page connected to the Instagram account used to create the caption.  Available for Instagram API with Facebook Login only. |
| `comments_count`<br>Public | Count of comments on the media. Excludes comments on album child media and the media's caption. Includes replies on comments. |
| `copyright_check_information.status` | Returns `status` and `matches_found` objects<br><br>\| status objects \| Description \|<br>\| --- \| --- \|<br>\| `status` \| * `completed` – the detection process has finished<br>* `error` – an error occurred during the detection process<br>* `in_progress` – the detection process is ongoing<br>* `not_started` – the detection process has not started \|<br>\| `matches_found` \| Set to one of the following:<br><br>* `false` if the video **does not violate** copyright,<br>* `true` if the video **does violate** copyright \|<br><br>If a video **is violating copyright**, the `copyright_matches` is returned with an array of objects about the copyrighted material, when the violation is occurring in the video, and the actions take to mitigate the violation.<br><br>\| copyright_matches objects \| Description \|<br>\| --- \| --- \|<br>\| `author` \| the author of the copyrighted video \|<br>\| `content_title` \| the name of the copyrighted video \|<br>\| `matched_segments` \| An array of objects with the following key-value pairs:<br><br>* `duration_in_seconds` – the number of seconds the content violates copyright<br>* `segment_type` – either `AUDIO` or `VIDEO`<br>* `start_time_in_seconds` – set to the start time of the video \|<br>\| `owner_copyright_policy` \| Objects returned include:<br><br>* `name` – The name for the copyright owners' policy<br>* `actions` – An array of `action` objects with the mitigations steps taken defined by the copyright owner's policy. May include different mitigations steps for different locations.<br>    * `action` – The mitigation action taken against the video violating copyright. Different mitigation steps can be taken for different countries. Can be one of the following values:<br>        * `BLOCK` – The video is blocked from the audiences listed in the `geos` array<br>        * `MUTE` - The video is muted for audiences listed in the `geos` array \| |
| `id`<br>Public | Media ID. |
| `is_ai_generated` | Indicates if the media has an AI label. Excludes album children. |
| `is_comment_enabled` | Indicates if comments are enabled or disabled. Excludes album children. |
| `is_shared_to_feed`<br>Public | For Reels only. When `true`, indicates that the reel can appear in both the **Feed** and **Reels** tabs. When `false`, indicates that the reel can only appear in the **Reels** tab.<br><br>**Warning:** Neither value determines whether the reel actually appears in the **Reels** tab because the reel may not meet eligibilty requirements or may not be selected by our algorithm. See [reel specifications](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#reel-specifications) for eligibility critera. |
| `legacy_instagram_media_id` | The ID for Instagram media that was created for Marketing API endpoints for v21.0 and older. |
| `like_count` | Count of likes on the media, including replies on comments. Excludes likes on album child media and likes on promoted posts created from the media.<br><br>If queried indirectly through another endpoint or field expansion the `like_count` field is omitted if the media owner has hidden like counts. |
| `media_audio_type`<br>Public | The type of audio used in the media. Can be `MUSIC` or `ORIGINAL_SOUND`. Returned only for video media such as Reels; not returned for other media types (for example, photos and carousels). |
| `media_product_type`<br>Public | Surface where the media is published. Can be `AD`, `FEED`, `STORY` or `REELS`.  Available for Instagram API with Facebook Login only. |
| `media_type`<br>Public | Media type. Can be `CAROUSEL_ALBUM`, `IMAGE`, or `VIDEO`. |
| `media_url`<br>Public | The URL for the media.<br><br>**Warning:** The `media_url` field is omitted from responses if the media contains copyrighted material or has been flagged for a copyright violation.  Examples of copyrighted material can include audio on Reels. |
| `owner`<br>Public | Instagram user ID who created the media. Only returned if the app user making the query also created the media; otherwise, `username` field is returned instead. |
| `permalink`<br>Public | Permanent URL to the media. |
| `shortcode`<br>Public | Shortcode to the media. |
| `thumbnail_url`<br>Public | Media thumbnail URL. Only available on `VIDEO` media. |
| `timestamp`<br>Public | [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601)-formatted creation date in UTC (default is UTC ±00:00). |
| `username`<br>Public | Username of user who created the media. |
| `view_count`<br>Public | View count for Instagram Reels, which includes both **paid and organic metrics.** For content crossposted to Facebook, this returns combined Instagram and Facebook view counts if the Facebook post is accessible by the session user.<br><br>Available for [Business Discovery API](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/business-discovery) only. |
| `reposts_count`<br>Public | Number of times the media has been reposted. Available for FEED and REELS media. Not accessible through hashtag API endpoints. Available for Instagram API with Facebook Login only. |
| `saved_count` | Number of times the media has been saved. Available for FEED and REELS media. Only accessible by the media owner or an accepted collaborator. Not accessible through Business Discovery, tagged/mentioned media, or hashtag API endpoints. Available for Instagram API with Facebook Login only. |
| `shares_count` | Number of times the media has been shared. Available for FEED and REELS media. Not accessible through Business Discovery or hashtag API endpoints. Available for Instagram API with Facebook Login only. |
| `total_comments_count`<br>Public | Total number of comments on the media across all surfaces, including comments on associated promoted/boosted media. Not accessible through hashtag API endpoints. Available for Instagram API with Facebook Login only. |
| `total_like_count`<br>Public | Total number of likes on the media across all surfaces, including likes on associated promoted/boosted media. Not accessible through hashtag API endpoints. Available for Instagram API with Facebook Login only. |
| `total_views_count` | Total view count of video content across all surfaces, including views from promoted/boosted media and replays. Only available for video media. Not accessible through Business Discovery or hashtag API endpoints. For Business Discovery, use `view_count` instead. Available for Instagram API with Facebook Login only. |

### Edges

Public edges can be returned through field expansion.

| Edge | Description |
| --- | --- |
| [`children`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-media/children)<br>Public. | Represents a collection of [Instagram Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects on an album [Instagram Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media). |
| [`collaborators`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-media/collaborators) | Represents a list of users who are added as collaborators on an [Instagram Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object.  Available for Instagram API with Facebook Login only. |
| [`comments`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-media/comments) | Represents a collection of [Instagram Comments](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) on an [Instagram Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object. |
| [`insights`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights) | Represents social interaction metrics on an [Instagram Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object. |

### cURL Example

#### Example request

```curl
curl -X GET \
  'https://graph.instagram.com/v25.0/17895695668004550?fields=id,media_type,media_url,owner,timestamp&access_token=IGQVJ...'
```

#### Example response

```json
{
  "id": "17918920912340654",
  "media_type": "IMAGE",
  "media_url": "https://sconten...",
  "owner": {
    "id": "17841405309211844"
  },
  "timestamp": "2019-09-26T22:36:43+0000"
}
```

## Updating

**`POST /<IG_MEDIA_ID>`**

Enable or disable comments on an Instagram Media.

### Requirements

|  | Instagram API with Instagram Login | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User access token | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`<br>* `instagram_business_manage_comments` | * `instagram_basic`<br>* `instagram_manage_comments`<br>* `pages_read_engagement`<br><br>If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need one of:<br><br>* `ads_management`<br>* `ads_read` |

### Limitations

Live video Instagram Media not supported.

### Request Syntax

```curl
POST https://<HOST_URL>/<API_VERSION>/<IG_MEDIA_ID>
  ?comment_enabled=<BOOL>
  &access_token=<ACCESS_TOKEN>
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `<API_VERSION>`<br><br>**The latest version is:** v25.0<br> | The API version your app is using. If not specified in your API calls this will be the latest version at the time you created your Meta app or, if that version is no longer available, the oldest version available.[Learn more about versioning.](https://developers.facebook.com/docs/graph-api/guides/versioning)<br> |
| `<HOST_URL>` | The [host URL](#requirements) your app is using to query the endpoint. |
| `<IG_MEDIA_ID>` | **Required.** ID for the media to be published. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `<ACCESS_TOKEN>` | **Required.** App user's [user access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens). |
| `comment_enabled` | `<BOOL>` | **Required.** Set to `true` to enable comments or `false` to disable comments. |

### cURL Example

#### Example request

```curl
curl -i -X POST \
 "https://graph.instagram.com/v25.0/17918920912340654?comment_enabled=true&access_token=EAAOc..."
```

#### Example response

```json
{
  "success": true
}
```

## Deleting {#delete}

**`DELETE /<IG_MEDIA_ID>`**

Delete Instagram Media.

### Requirements
|  | Instagram API with Facebook Login |
| --- | --- |
| **Access Tokens** | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.facebook.com` |
| **Login Type** | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_basic`<br>* `instagram_manage_contents` |

### Limitations

This api only supports Instagram API with Facebook login only. Non-ad posts, Stories, Reels and entire carousel albums are supported. To delete media inside carousel albums, the entire carousel album must be deleted by specifying the carousel container media id. Individually deleting media within a carousel is not supported.

### Request Syntax

```curl
POST https://graph.facebook.com/<API_VERSION>/<IG_MEDIA_ID>
  ?access_token=<ACCESS_TOKEN>
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `<API_VERSION>`<br><br>**The latest version is:** v25.0<br> | The API version your app is using. If not specified in your API calls this will be the latest version at the time you created your Meta app or, if that version is no longer available, the oldest version available.[Learn more about versioning.](https://developers.facebook.com/docs/graph-api/guides/versioning)<br> |
| `<IG_MEDIA_ID>` | **Required.** ID for the media to be published. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `<ACCESS_TOKEN>` | **Required.** App user's [user access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens). |

### cURL Example

#### Example request

```curl
curl -i -X DELETE \
 "https://graph.facebook.com/v25.0/17918920912340654?comment_enabled=true&access_token=EAAOc..."
```

#### Example response (Success)

```json
{
  "success": true,
  "deleted_id": "17918920912340654"
}
```

#### Example response (Failure, Media Type Not Supported)

```json
{
  "error": {
   "message": "Fatal",
   "type": "OAuthException",
   "code": -1,
   "error_subcode": 2207073,
   "is_transient": false,
   "error_user_title": "Media Type Not Supported",
   "error_user_msg": "The media type is not supported for this endpoint",
   "fbtrace_id": "Api-OlNdfcpOwIu6hNaT5Kw"
  },
}
```

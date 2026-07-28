# IG Hashtag Recent Media



Represents a collection of the most recently published photo and video [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects that have been tagged with a hashtag.

Available for the Instagram API with Facebook Login.

## Creating

This operation is not supported.

## Reading

Returns a list of the most recently published photo and video [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects published with a specific hashtag.

### Requirements

| Type | Description |
| --- | --- |
| [Features](https://developers.facebook.com/docs/apps/review/feature) | [`Instagram Public Content Access`](https://developers.facebook.com/docs/apps/review/feature#reference-INSTAGRAM_PUBLIC_CONTENT_ACCESS) |
| [Permissions](https://developers.facebook.com/docs/apps/review/login-permissions) | [`instagram_basic`](https://developers.facebook.com/docs/facebook-login/permissions#reference-instagram_basic)&lt;br&gt;&lt;br&gt;If the token is from a User whose Page role was granted via the Business Manager, one of the following permissions is also required: `ads_management`, `business_management`, or `read_pages_engagement`. |
| [Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens) | A User access token of a Facebook User who has been [approved for tasks on the connected Facebook Page](https://developers.facebook.com/documentation/instagram-platform/overview#authentication). |

### Limitations

- Only returns public photos and videos.
- Only returns media objects published within 24 hours of query execution.
- Will not return promoted/boosted/ads media.
- Responses are paginated with a maximum `limit` of 50 results per page.
- Responses will not always be in chronological order.
- You can query a maximum of 30 unique hashtags [within a 7 day period](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/recently_searched_hashtags).
- You cannot request the `username` field on returned media objects.
- This endpoint only returns an `after` cursor for paginated results; a `before` cursor will not be included. In addition, the `after` cursor value will always be the same for each page, but it can still be used to get the next page of results in the result set.

### Syntax

`GET /&lt;IG_HASHTAG_ID&gt;/recent_media?user_id=&lt;USER_ID&gt;&amp;fields=&lt;LIST_OF_FIELDS&gt;`

### Parameters &#123;#returnable-fields&#125;

| Parameter | Description |
| --- | --- |
| `fields` | A comma-separated list of fields on a media object&lt;br&gt;&lt;br&gt;\| Value \| Description \|&lt;br&gt;\| --- \| --- \|&lt;br&gt;\| `caption` \| The caption for the media object \|&lt;br&gt;\| `children` \| Media objects in a carousel Album [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media), if applicable \|&lt;br&gt;\| `comments_count` \| The number of comments on the media object \|&lt;br&gt;\| `id` \| The ID for the media object \|&lt;br&gt;\| `like_count` \| The number of likes for the media object. Will be omitted if the media owner has hidden like counts in it \|&lt;br&gt;\| `media_type` \| The type of media: `CAROUSEL_ALBUM`, `IMAGE`, or `VIDEO`. \|&lt;br&gt;\| `media_url` \| The URL for the media object. Not returned for Album [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) \|&lt;br&gt;\| `permalink` \| The permalink for the media object \|&lt;br&gt;\| `timestamp` \| Unix timestamp for when the media object was published \| |
| `user_id` | The ID for person querying the data |

#### Example Request

```
GET graph.facebook.com/17873440459141021/recent_media
  ?user_id=17841405309211844
  &amp;fields=id,media_type,comments_count,like_count
```

### Response

An array of [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects. Excess results will be paginated.

#### Sample Response

```
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;id&quot;: &quot;17880997618081620&quot;,
      &quot;media_type&quot;: &quot;IMAGE&quot;,
      &quot;comments_count&quot;: 84,
      &quot;like_count&quot;: 177
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17871527143187462&quot;
      &quot;media_type&quot;: &quot;IMAGE&quot;,
      &quot;comments_count&quot;: 24,
      &quot;like_count&quot;: 57
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17896450804038745&quot;
      &quot;media_type&quot;: &quot;IMAGE&quot;,
      &quot;comments_count&quot;: 19,
      &quot;like_count&quot;: 36
    &#125;
  ],
  &quot;paging&quot;:
    &#123;
      &quot;cursors&quot;:
        &#123;
          &quot;after&quot;: &quot;NTAyYmE4...&quot;
        &#125;,
      &quot;next&quot;: &quot;https://graph.facebook.com/...&quot;
    &#125;
&#125;
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

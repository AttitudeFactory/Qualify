# IG Hashtag Top Media



Represents a collection of the most popular photo and video [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects that have been tagged with a hashtag.

Popularity is determined by a mix of views and viewer interaction using the same methodology that determines the top posts when [searching for a hashtag](https://www.instagram.com/explore/tags/halloween/) on [www.instagram.com](https://www.instagram.com).

Available for the Instagram API with Facebook Login.

## Creating

This operation is not supported.

## Reading

Returns the most popular photo and video [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects that have been tagged with the hashtag.

### Requirements

| Type | Description |
| --- | --- |
| [Features](https://developers.facebook.com/docs/apps/review/feature) | [`Instagram Public Content Access`](https://developers.facebook.com/docs/apps/review/feature#reference-INSTAGRAM_PUBLIC_CONTENT_ACCESS) |
| [Permissions](https://developers.facebook.com/docs/apps/review/login-permissions) | [`instagram_basic`](https://developers.facebook.com/docs/facebook-login/permissions#reference-instagram_basic)&lt;br&gt;&lt;br&gt;If the token is from a User whose Page role was granted via the Business Manager, one of the following permissions is also required: `ads_management`, `business_management`, or `pages_read_engagement`. |
| [Tokens](https://developers.facebook.com/documentation/instagram-platform/overview#access-tokens) | A User access token of a Facebook User who has been [approved for tasks on the connected Facebook Page](https://developers.facebook.com/documentation/instagram-platform/overview#access-tokens). |

### Limitations

- This edge only returns public photos and videos.
- Will not return promoted/boosted/ads media.
- Responses are paginated with a maximum `limit` of 50 results per page.
- You can query a maximum of 30 unique hashtags [within a 7 day period](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/recently_searched_hashtags).
- You cannot request the `username` field on returned media objects.
- This endpoint only returns an `after` cursor for paginated results; a `before` cursor will not be included. In addition, the `after` cursor value will always be the same for each page, but it can still be used to get the next page of results in the result set.

### Syntax

`GET /&lt;IG_HASHTAG_ID&gt;/top_media?user_id=&lt;IG_USER_ID&gt;&amp;fields=&lt;LIST_OF_FIELDS&gt;`

#### Query String Parameters

- `&lt;IG_USER_ID&gt;` (required) — The ID of the Instagram Business or Creator Account performing the query.
- `&lt;LIST_OF_FIELDS&gt;` — A comma-separated list of fields you want returned. See [Returnable Fields](#returnable-fields).

#### Response

An array of [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects. Excess results will be paginated.

#### Returnable Fields &#123;#returnable-fields&#125;

You can use the `fields` parameter to request the following fields on returned media objects:

* `caption`
* `children` (only returned for Album [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media))
* `comments_count`
* `id`
* `like_count` – field will be omitted if media owner has hidden like counts in it.)
* `media_type`
* `media_url` (not returned for Album [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media))
* `permalink`
* `timestamp`

#### Example Request

```
GET graph.facebook.com/17873440459141021/top_media
  ?user_id=17841405309211844
  &amp;fields=id,media_type,comments_count,like_count
```

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
    &#125;,
    ... // Results truncated for clarity
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

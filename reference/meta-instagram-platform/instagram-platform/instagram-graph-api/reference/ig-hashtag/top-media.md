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
| [Permissions](https://developers.facebook.com/docs/apps/review/login-permissions) | [`instagram_basic`](https://developers.facebook.com/docs/facebook-login/permissions#reference-instagram_basic)<br><br>If the token is from a User whose Page role was granted via the Business Manager, one of the following permissions is also required: `ads_management`, `business_management`, or `pages_read_engagement`. |
| [Tokens](https://developers.facebook.com/documentation/instagram-platform/overview#access-tokens) | A User access token of a Facebook User who has been [approved for tasks on the connected Facebook Page](https://developers.facebook.com/documentation/instagram-platform/overview#access-tokens). |

### Limitations

- This edge only returns public photos and videos.
- Will not return promoted/boosted/ads media.
- Responses are paginated with a maximum `limit` of 50 results per page.
- You can query a maximum of 30 unique hashtags [within a 7 day period](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/recently_searched_hashtags).
- You cannot request the `username` field on returned media objects.
- This endpoint only returns an `after` cursor for paginated results; a `before` cursor will not be included. In addition, the `after` cursor value will always be the same for each page, but it can still be used to get the next page of results in the result set.

### Syntax

`GET /<IG_HASHTAG_ID>/top_media?user_id=<IG_USER_ID>&fields=<LIST_OF_FIELDS>`

#### Query String Parameters

- `<IG_USER_ID>` (required) — The ID of the Instagram Business or Creator Account performing the query.
- `<LIST_OF_FIELDS>` — A comma-separated list of fields you want returned. See [Returnable Fields](#returnable-fields).

#### Response

An array of [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects. Excess results will be paginated.

#### Returnable Fields {#returnable-fields}

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
  &fields=id,media_type,comments_count,like_count
```

#### Sample Response

```
{
  "data": [
    {
      "id": "17880997618081620",
      "media_type": "IMAGE",
      "comments_count": 84,
      "like_count": 177
    },
    {
      "id": "17871527143187462"
      "media_type": "IMAGE",
      "comments_count": 24,
      "like_count": 57
    },
    {
      "id": "17896450804038745"
      "media_type": "IMAGE",
      "comments_count": 19,
      "like_count": 36
    },
    ... // Results truncated for clarity
  ],
  "paging":
    {
      "cursors":
        {
          "after": "NTAyYmE4..."
        },
      "next": "https://graph.facebook.com/..."
    }
}
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

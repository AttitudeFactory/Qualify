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
| [Permissions](https://developers.facebook.com/docs/apps/review/login-permissions) | [`instagram_basic`](https://developers.facebook.com/docs/facebook-login/permissions#reference-instagram_basic)<br><br>If the token is from a User whose Page role was granted via the Business Manager, one of the following permissions is also required: `ads_management`, `business_management`, or `read_pages_engagement`. |
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

`GET /<IG_HASHTAG_ID>/recent_media?user_id=<USER_ID>&fields=<LIST_OF_FIELDS>`

### Parameters {#returnable-fields}

| Parameter | Description |
| --- | --- |
| `fields` | A comma-separated list of fields on a media object<br><br>\| Value \| Description \|<br>\| --- \| --- \|<br>\| `caption` \| The caption for the media object \|<br>\| `children` \| Media objects in a carousel Album [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media), if applicable \|<br>\| `comments_count` \| The number of comments on the media object \|<br>\| `id` \| The ID for the media object \|<br>\| `like_count` \| The number of likes for the media object. Will be omitted if the media owner has hidden like counts in it \|<br>\| `media_type` \| The type of media: `CAROUSEL_ALBUM`, `IMAGE`, or `VIDEO`. \|<br>\| `media_url` \| The URL for the media object. Not returned for Album [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) \|<br>\| `permalink` \| The permalink for the media object \|<br>\| `timestamp` \| Unix timestamp for when the media object was published \| |
| `user_id` | The ID for person querying the data |

#### Example Request

```
GET graph.facebook.com/17873440459141021/recent_media
  ?user_id=17841405309211844
  &fields=id,media_type,comments_count,like_count
```

### Response

An array of [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects. Excess results will be paginated.

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
    }
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

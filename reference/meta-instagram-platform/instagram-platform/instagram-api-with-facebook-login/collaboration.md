# Collaboration



## Collaboration Invites

You can list media collaboration invites from Instagram users. You are able to accept or decline a collaboration invite.

### Fetch Collaboration Invites

Get a list of pending collaboration invites for an Instagram User. These invites are essentially Instagram Media objects (attributes) tagged for collaboration.

Each Media object (attributes) comprises Media ID, Media Owner Instagram Username, Media Caption and Media URL for an Instagram User

**`GET /<IG_USER_ID>/collaboration_invites`**

#### Limitations

* Collaborator tagging supports Feed Image, Reels and Carousel objects.
* Stories is not supported.
* Rate limit applies to 300 calls per Instagram User per day (24 hours).

#### Requirements

| Type | Description |
| --- | --- |
| [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) | [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) – The Instagram User must be tagged for collaboration of Instagram Media(s) by other Instagram User(s). |
| [Permissions](https://developers.facebook.com/docs/permissions) | `instagram_basic` |

#### Example Request

```html
curl -i -X GET \
"https://graph.facebook.com/v23.0/<IG_USER_ID>/collaboration_invites?access_token=<USER-ACCESS-TOKEN>"
```

#### Sample Response

```json
{
  "data": [
    {
      "media_id": "18078920227752107",
      "media_owner_username": "katrina",
      "caption": "Making memories all over the map",
      "media_url": "<media-url-1>"
    },
    {
      "media_id": "17938817952064413",
      "media_owner_username": "john",
      "caption": "Good vibes happen on the tides",
      "media_url": "<media-url-2>"
    },
    {
      "media_id": "17981928557731507",
      "media_owner_username": "amanda",
      "caption": "Less perfection, more authenticity",
      "media_url": "<media-url-3>"
    }
  ],
  "paging": {
    "cursors": {
      "before": "QVFIU000NzlGS3BndGdrTzgzb0xoNy1kXzljVGRDRFhlUTNQTjJZARTZAVWWlaQW1RcHN5WUZAtUXQzTnU3dEZAENnoxWkdtOWlaNDA0LXBUcDNXOG90dzR2WXJn",
      "after": "QVFIU1lic1ZAkRllCLTktY2wyUzdfb3VaWUdiNUF3TmRacWFaY1k1d2YweWZA4LXpsLUowcjVzaGl2cXljdmlNeG91bEVwVG93RnBKU3IwSW5Xdzh6MFhzZAUFn"
    }
  }
}
```

#### Path Parameters

| Placeholder | Value |
| --- | --- |
| `<API_VERSION>` | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `<IG_USER_ID>`<br>*Required string* | The ID for your app user's Instagram User. |

#### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token`<br><br>*Required string<br>* | `<USER_ACCESS_TOKEN>` | Your app user's [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |
| `limit`<br><br>*Optional int* | `<LIMIT>` (eg. `15`) | Paging limit - Number of items returned in a paged response. Default is 10. |
| `after`<br>*Optional string* | `<AFTER_CURSOR_STRING>` | Cursor string to iterate forwards from the current page |
| `before`<br><br>*Optional string* | `<BEFORE_CURSOR_STRING>` | Cursor string to iterate backwards from the current page |

#### Response Fields

| Field Name | Description |
| --- | --- |
| `media_id` | The ID of the Instagram Media object tagged for collaboration |
| `media_owner_username` | The ID of the Instagram User who invited the app user's Instagram account for collaboration |
| `caption` | Caption of the tagged Instagram Media |
| `media_url` | Viewable CDN URL of the tagged Instagram Media |

### Accept Or Decline Collaboration Invite

Accept or Decline a pending collaboration invite for an Instagram User for an Instagram post by other Instagram User(s).

Requires API params include API Version, Instagram User ID, invited Media ID and a boolean flag to indicate accept or decline.

**`POST /<IG_USER_ID>/collaboration_invites`**

#### Limitations

* Accept/Decline collaborations supports Feed Image, Reels and Carousel objects.
* Stories is not supported.
* Rate limit applies to 50 calls per Instagram User per day (24 hours).

#### Requirements

| Type | Description |
| --- | --- |
| [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) | [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) – The Instagram User must be tagged for collaboration of Instagram Media(s) by other Instagram User(s). |
| [Permissions](https://developers.facebook.com/docs/permissions) | `instagram_basic` |

#### Example Request

```html
curl -i -X POST \
"https://graph.facebook.com/v23.0/<IG_USER_ID>/collaboration_invites?media_id=<IG_MEDIA_ID>&accept=true&access_token=<USER-ACCESS-TOKEN>
```

#### Sample Response

```json
{
  "success": true
}
```

#### Path Parameters

| Placeholder | Value |
| --- | --- |
| `<API_VERSION>` | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `<IG_USER_ID>`<br>*Required string * | The ID for your app user's Instagram User. |

#### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token`<br>*Required string* | `<USER_ACCESS_TOKEN>` | Your app user's [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |
| `media_id`<br><br>*Required string* | `<IG_MEDIA_ID>` | The ID of the invited Instagram Media |
| `accept`<br>*Required boolean* | `boolean` | Flag to accept/decline the invite.<br><br>* `true` to accept the invite<br>* `false` to decline the invite |

#### Response Fields

| Field Name | Description |
| --- | --- |
| `success` | Boolean flag to indicate whether the accept/decline succeeded |

## Collaborative Media

The Collaborative Media endpoints allow developers to retrieve media where an Instagram user is an accepted collaborator. This enables businesses and creators to track and measure the performance of collaborative content directly through the API.

### Collaborative Media List

Retrieve a list of all media where the Instagram user is an **accepted collaborator**. This does **not** include media that the user owns directly — only media created by other users where the user has been added and accepted as a collaborator.

**`GET /<IG_USER_ID>/collaborative_media`**

#### Limitations

* Collaborative media supports Feed Image, Reels and Carousel objects.
* Stories is not supported.
* You must be an accepted collaborator.
* If the original media owner removes you as a collaborator, you can no longer access the media.

#### Requirements

| Type | Description |
| --- | --- |
| [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) | [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| [Permissions](https://developers.facebook.com/docs/permissions) | `instagram_basic` — granted by one of the collaborators on the media. |

#### Example Request

```html
curl -i -X GET \
"https://graph.facebook.com/v23.0/<IG_USER_ID>/collaborative_media?fields=id,caption,media_type,timestamp,permalink,total_like_count,total_comments_count&access_token=<USER-ACCESS-TOKEN>"
```

#### Sample Response

```json
{
  "data": [
    {
      "id": "17895695608903510",
      "caption": "Collab post with @Instagram",
      "media_type": "VIDEO",
      "timestamp": "2026-02-15T10:30:00+0000",
      "permalink": "https://www.instagram.com/reel/ABC123/",
      "total_like_count": 1502,
      "total_comments_count": 234
    }
  ],
  "paging": {
    "cursors": {
      "before": "...",
      "after": "..."
    },
    "next": "..."
  }
}
```

#### Path Parameters

| Placeholder | Value |
| --- | --- |
| `<API_VERSION>` | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `<IG_USER_ID>`<br>*Required string* | The ID for your app user's Instagram User. |

#### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token`<br><br>*Required string* | `<USER_ACCESS_TOKEN>` | Your app user's [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |
| `fields`<br><br>*Optional string* | `<FIELD_LIST>` | Comma-separated list of fields to return. See **Supported Fields on Collaborative Media** below. |
| `limit`<br><br>*Optional int* | `<LIMIT>` (eg. `15`) | Paging limit. |
| `after`<br>*Optional string* | `<AFTER_CURSOR_STRING>` | Cursor string to iterate forwards from the current page |
| `before`<br><br>*Optional string* | `<BEFORE_CURSOR_STRING>` | Cursor string to iterate backwards from the current page |

### Collaborative Media Search

Look up a specific collaborative media by ID and retrieve its details. This is useful when you already know the media ID and want to fetch its data without paginating through all collaborative media.

**`GET /<IG_USER_ID>?fields=collaborative_media_search.media_id(<IG_MEDIA_ID>)`**

#### Notes

* The specified media must **not** be owned by the requesting user. Use the standard `GET /<IG_MEDIA_ID>` endpoint for your own media.
* The requesting user must be an **accepted collaborator** on the specified media.

#### Requirements

| Type | Description |
| --- | --- |
| [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) | [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| [Permissions](https://developers.facebook.com/docs/permissions) | `instagram_basic` — granted by one of the collaborators on the media. |

#### Example Request

```html
curl -i -X GET \
"https://graph.facebook.com/v23.0/<IG_USER_ID>?fields=collaborative_media_search.media_id(17895695608903510){id,caption}&access_token=<USER-ACCESS-TOKEN>"
```

#### Sample Response

```json
{
  "collaborative_media_search": {
    "id": "17895695608903510",
    "caption": "Collab post with @Instagram"
  },
  "id": "<IG_USER_ID>"
}
```

#### Path Parameters

| Placeholder | Value |
| --- | --- |
| `<API_VERSION>` | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `<IG_USER_ID>`<br>*Required string* | The ID for your app user's Instagram User. |

#### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token`<br>*Required string* | `<USER_ACCESS_TOKEN>` | Your app user's [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |
| `fields`<br><br>*Required string* | `collaborative_media_search.media_id(<IG_MEDIA_ID>)` | The media ID to look up. You can append `{field1,field2,...}` to select specific fields. |

### Supported Fields on Collaborative Media

The standard IG Media fields are available when accessing collaborative media through the `GET /<IG_USER_ID>/collaborative_media` and `GET /<IG_USER_ID>?fields=collaborative_media_search.media_id(...)` endpoints. This includes the following fields:

* `id`
* `caption`
* `comments_count`
* `like_count`
* `media_product_type`
* `media_type`
* `media_url`
* `permalink`
* `thumbnail_url`
* `username`
* `timestamp`
* `total_like_count`
* `total_comments_count`
* `reposts_count`
* `saved_count`
* `shares_count`
* `total_views_count`

#### Limitations

* These fields are **not available for carousel child media**. They are only returned for top-level media objects.
* The media owner can disable showing likes, comments, views, reposts, and shares. In these cases, the corresponding fields are not returned.

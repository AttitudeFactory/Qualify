# Collaboration



## Collaboration Invites

You can list media collaboration invites from Instagram users. You are able to accept or decline a collaboration invite.

### Fetch Collaboration Invites

Get a list of pending collaboration invites for an Instagram User. These invites are essentially Instagram Media objects (attributes) tagged for collaboration.

Each Media object (attributes) comprises Media ID, Media Owner Instagram Username, Media Caption and Media URL for an Instagram User

**`GET /&lt;IG_USER_ID&gt;/collaboration_invites`**

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
&quot;https://graph.facebook.com/v23.0/&lt;IG_USER_ID&gt;/collaboration_invites?access_token=&lt;USER-ACCESS-TOKEN&gt;&quot;
```

#### Sample Response

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;media_id&quot;: &quot;18078920227752107&quot;,
      &quot;media_owner_username&quot;: &quot;katrina&quot;,
      &quot;caption&quot;: &quot;Making memories all over the map&quot;,
      &quot;media_url&quot;: &quot;&lt;media-url-1&gt;&quot;
    &#125;,
    &#123;
      &quot;media_id&quot;: &quot;17938817952064413&quot;,
      &quot;media_owner_username&quot;: &quot;john&quot;,
      &quot;caption&quot;: &quot;Good vibes happen on the tides&quot;,
      &quot;media_url&quot;: &quot;&lt;media-url-2&gt;&quot;
    &#125;,
    &#123;
      &quot;media_id&quot;: &quot;17981928557731507&quot;,
      &quot;media_owner_username&quot;: &quot;amanda&quot;,
      &quot;caption&quot;: &quot;Less perfection, more authenticity&quot;,
      &quot;media_url&quot;: &quot;&lt;media-url-3&gt;&quot;
    &#125;
  ],
  &quot;paging&quot;: &#123;
    &quot;cursors&quot;: &#123;
      &quot;before&quot;: &quot;QVFIU000NzlGS3BndGdrTzgzb0xoNy1kXzljVGRDRFhlUTNQTjJZARTZAVWWlaQW1RcHN5WUZAtUXQzTnU3dEZAENnoxWkdtOWlaNDA0LXBUcDNXOG90dzR2WXJn&quot;,
      &quot;after&quot;: &quot;QVFIU1lic1ZAkRllCLTktY2wyUzdfb3VaWUdiNUF3TmRacWFaY1k1d2YweWZA4LXpsLUowcjVzaGl2cXljdmlNeG91bEVwVG93RnBKU3IwSW5Xdzh6MFhzZAUFn&quot;
    &#125;
  &#125;
&#125;
```

#### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&lt;API_VERSION&gt;` | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `&lt;IG_USER_ID&gt;`&lt;br&gt;*Required string* | The ID for your app user&#039;s Instagram User. |

#### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token`&lt;br&gt;&lt;br&gt;*Required string&lt;br&gt;* | `&lt;USER_ACCESS_TOKEN&gt;` | Your app user&#039;s [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |
| `limit`&lt;br&gt;&lt;br&gt;*Optional int* | `&lt;LIMIT&gt;` (eg. `15`) | Paging limit - Number of items returned in a paged response. Default is 10. |
| `after`&lt;br&gt;*Optional string* | `&lt;AFTER_CURSOR_STRING&gt;` | Cursor string to iterate forwards from the current page |
| `before`&lt;br&gt;&lt;br&gt;*Optional string* | `&lt;BEFORE_CURSOR_STRING&gt;` | Cursor string to iterate backwards from the current page |

#### Response Fields

| Field Name | Description |
| --- | --- |
| `media_id` | The ID of the Instagram Media object tagged for collaboration |
| `media_owner_username` | The ID of the Instagram User who invited the app user&#039;s Instagram account for collaboration |
| `caption` | Caption of the tagged Instagram Media |
| `media_url` | Viewable CDN URL of the tagged Instagram Media |

### Accept Or Decline Collaboration Invite

Accept or Decline a pending collaboration invite for an Instagram User for an Instagram post by other Instagram User(s).

Requires API params include API Version, Instagram User ID, invited Media ID and a boolean flag to indicate accept or decline.

**`POST /&lt;IG_USER_ID&gt;/collaboration_invites`**

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
&quot;https://graph.facebook.com/v23.0/&lt;IG_USER_ID&gt;/collaboration_invites?media_id=&lt;IG_MEDIA_ID&gt;&amp;accept=true&amp;access_token=&lt;USER-ACCESS-TOKEN&gt;
```

#### Sample Response

```json
&#123;
  &quot;success&quot;: true
&#125;
```

#### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&lt;API_VERSION&gt;` | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `&lt;IG_USER_ID&gt;`&lt;br&gt;*Required string * | The ID for your app user&#039;s Instagram User. |

#### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token`&lt;br&gt;*Required string* | `&lt;USER_ACCESS_TOKEN&gt;` | Your app user&#039;s [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |
| `media_id`&lt;br&gt;&lt;br&gt;*Required string* | `&lt;IG_MEDIA_ID&gt;` | The ID of the invited Instagram Media |
| `accept`&lt;br&gt;*Required boolean* | `boolean` | Flag to accept/decline the invite.&lt;br&gt;&lt;br&gt;* `true` to accept the invite&lt;br&gt;* `false` to decline the invite |

#### Response Fields

| Field Name | Description |
| --- | --- |
| `success` | Boolean flag to indicate whether the accept/decline succeeded |

## Collaborative Media

The Collaborative Media endpoints allow developers to retrieve media where an Instagram user is an accepted collaborator. This enables businesses and creators to track and measure the performance of collaborative content directly through the API.

### Collaborative Media List

Retrieve a list of all media where the Instagram user is an **accepted collaborator**. This does **not** include media that the user owns directly — only media created by other users where the user has been added and accepted as a collaborator.

**`GET /&lt;IG_USER_ID&gt;/collaborative_media`**

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
&quot;https://graph.facebook.com/v23.0/&lt;IG_USER_ID&gt;/collaborative_media?fields=id,caption,media_type,timestamp,permalink,total_like_count,total_comments_count&amp;access_token=&lt;USER-ACCESS-TOKEN&gt;&quot;
```

#### Sample Response

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;id&quot;: &quot;17895695608903510&quot;,
      &quot;caption&quot;: &quot;Collab post with &#064;Instagram&quot;,
      &quot;media_type&quot;: &quot;VIDEO&quot;,
      &quot;timestamp&quot;: &quot;2026-02-15T10:30:00+0000&quot;,
      &quot;permalink&quot;: &quot;https://www.instagram.com/reel/ABC123/&quot;,
      &quot;total_like_count&quot;: 1502,
      &quot;total_comments_count&quot;: 234
    &#125;
  ],
  &quot;paging&quot;: &#123;
    &quot;cursors&quot;: &#123;
      &quot;before&quot;: &quot;...&quot;,
      &quot;after&quot;: &quot;...&quot;
    &#125;,
    &quot;next&quot;: &quot;...&quot;
  &#125;
&#125;
```

#### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&lt;API_VERSION&gt;` | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `&lt;IG_USER_ID&gt;`&lt;br&gt;*Required string* | The ID for your app user&#039;s Instagram User. |

#### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token`&lt;br&gt;&lt;br&gt;*Required string* | `&lt;USER_ACCESS_TOKEN&gt;` | Your app user&#039;s [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |
| `fields`&lt;br&gt;&lt;br&gt;*Optional string* | `&lt;FIELD_LIST&gt;` | Comma-separated list of fields to return. See **Supported Fields on Collaborative Media** below. |
| `limit`&lt;br&gt;&lt;br&gt;*Optional int* | `&lt;LIMIT&gt;` (eg. `15`) | Paging limit. |
| `after`&lt;br&gt;*Optional string* | `&lt;AFTER_CURSOR_STRING&gt;` | Cursor string to iterate forwards from the current page |
| `before`&lt;br&gt;&lt;br&gt;*Optional string* | `&lt;BEFORE_CURSOR_STRING&gt;` | Cursor string to iterate backwards from the current page |

### Collaborative Media Search

Look up a specific collaborative media by ID and retrieve its details. This is useful when you already know the media ID and want to fetch its data without paginating through all collaborative media.

**`GET /&lt;IG_USER_ID&gt;?fields=collaborative_media_search.media_id(&lt;IG_MEDIA_ID&gt;)`**

#### Notes

* The specified media must **not** be owned by the requesting user. Use the standard `GET /&lt;IG_MEDIA_ID&gt;` endpoint for your own media.
* The requesting user must be an **accepted collaborator** on the specified media.

#### Requirements

| Type | Description |
| --- | --- |
| [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) | [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| [Permissions](https://developers.facebook.com/docs/permissions) | `instagram_basic` — granted by one of the collaborators on the media. |

#### Example Request

```html
curl -i -X GET \
&quot;https://graph.facebook.com/v23.0/&lt;IG_USER_ID&gt;?fields=collaborative_media_search.media_id(17895695608903510)&#123;id,caption&#125;&amp;access_token=&lt;USER-ACCESS-TOKEN&gt;&quot;
```

#### Sample Response

```json
&#123;
  &quot;collaborative_media_search&quot;: &#123;
    &quot;id&quot;: &quot;17895695608903510&quot;,
    &quot;caption&quot;: &quot;Collab post with &#064;Instagram&quot;
  &#125;,
  &quot;id&quot;: &quot;&lt;IG_USER_ID&gt;&quot;
&#125;
```

#### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&lt;API_VERSION&gt;` | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `&lt;IG_USER_ID&gt;`&lt;br&gt;*Required string* | The ID for your app user&#039;s Instagram User. |

#### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token`&lt;br&gt;*Required string* | `&lt;USER_ACCESS_TOKEN&gt;` | Your app user&#039;s [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |
| `fields`&lt;br&gt;&lt;br&gt;*Required string* | `collaborative_media_search.media_id(&lt;IG_MEDIA_ID&gt;)` | The media ID to look up. You can append `&#123;field1,field2,...&#125;` to select specific fields. |

### Supported Fields on Collaborative Media

The standard IG Media fields are available when accessing collaborative media through the `GET /&lt;IG_USER_ID&gt;/collaborative_media` and `GET /&lt;IG_USER_ID&gt;?fields=collaborative_media_search.media_id(...)` endpoints. This includes the following fields:

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

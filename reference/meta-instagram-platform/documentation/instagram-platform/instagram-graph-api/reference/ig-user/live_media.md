# IG User Live Media



Represents a collection of live video [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) on an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user).

## Creating

This operation is not supported.

## Reading

**`GET /&#123;ig-user-id&#125;/live_media`**

Get a collection of live video [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) on an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user).

### Limitations

Only live video IG Media being broadcast at the time of the request will be returned.

### Time-based Pagination

This endpoint supports [time-based pagination](https://developers.facebook.com/docs/graph-api/using-graph-api#time). Include `since` and `until` query-string paramaters with Unix timestamp or `strtotime` data values to define a time range.

### Requirements

| Type | Requirement |
| --- | --- |
| Access Tokens | User |
| [Permissions](https://developers.facebook.com/docs/permissions) | `instagram_basic`&lt;br&gt;`pages_read_engagement`&lt;br&gt;&lt;br&gt;If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need one of:&lt;br&gt;&lt;br&gt;`ads_management`&lt;br&gt;`ads_read` |

### Request Syntax

```
GET https://graph.facebook.com/&#123;api-version&#125;/&#123;ig-user-id&#125;/live_media
  ?access_token=&#123;access-token&#125;
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&#123;api-version&#125;`  &lt;br&gt;*String* | API version |
| `&#123;ig-user-id&#125;`  &lt;br&gt;**Required**  &lt;br&gt;*String* | App user&#039;s app-scoped user ID. |

### Query String Parameters

| Key | Value |
| --- | --- |
| `access_token`  &lt;br&gt;**Required**  &lt;br&gt;*String* | App user&#039;s User |
| `fields`  &lt;br&gt;*Comma-separated list* | Comma-separated list of IG Media [fields](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#fields) you want returned for each live IG Media in the result set. |
| `since`  &lt;br&gt;*timestamp* | A Unix timestamp or `strtotime` data value that points to the start of a range of time-based data. See [time-based pagination](https://developers.facebook.com/docs/graph-api/using-graph-api#time). |
| `until`  &lt;br&gt;*timestamp* | A Unix timestamp or `strtotime` data value that points to the end of a range of time-based data. See [time-based pagination](https://developers.facebook.com/docs/graph-api/using-graph-api#time). |

### Response

A JSON-formatted object containing the data you requested.

```json
&#123;
  &quot;data&quot;: [],
  &quot;paging&quot;: &#123;&#125;
&#125;
```

#### Response Contents

| Property | Value |
| --- | --- |
| `data` | An array of [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) on an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user). |
| `paging` | An object containing [paging](https://developers.facebook.com/docs/graph-api/using-graph-api#paging) cursors and next/previous data set retrievial URLs. |

### cURL Example

#### Request

```curl
curl -X GET \
  &#039;https://graph.facebook.com/v25.0/17841405822304914/live_media?fields=id,media_type,media_product_type,owner,username,comments&amp;access_token=IGQVJ...&#039;
```

#### Response

```json
&#123;
   &quot;id&quot;:&quot;90010498116233&quot;,
   &quot;media_type&quot;:&quot;BROADCAST&quot;,
   &quot;media_product_type&quot;:&quot;LIVE&quot;,
   &quot;owner&quot;:&#123;
      &quot;id&quot;:&quot;17841405822304914&quot;
   &#125;,
   &quot;username&quot;:&quot;jayposiris&quot;,
   &quot;comments&quot;:&#123;
      &quot;data&quot;:[
        &#123;
            &quot;hidden&quot;: false,
            &quot;id&quot;: &quot;17907364514064687&quot;,
            &quot;like_count&quot;: 0,
            &quot;media&quot;: &#123;
                &quot;id&quot;: &quot;17892642502701087&quot;
            &#125;,
            &quot;text&quot;: &quot;&#064;jayposiris&quot;,
            &quot;timestamp&quot;: &quot;2021-08-17T21:23:07+0000&quot;,
            &quot;username&quot;: &quot;bztest0316_11&quot;,
            &quot;from&quot;: &#123;
                &quot;id&quot;: &quot;5895605157123796&quot;,
                &quot;username&quot;: &quot;bztest0316_11&quot;
            &#125;
        &#125;
      ]
   &#125;
&#125;
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

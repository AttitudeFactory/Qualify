# Instagram (IG) Hashtag



Represents an Instagram hashtag.

### Limitations

* Only available for Facebook Login for Business

## Creating

This operation is not supported.

## Reading

**`GET /&lt;IG_HASHTAG_ID&gt;`**

Returns [Fields](#fields) and [Edges](#edges) on an IG Hashtag.

### Limitations

You can query a maximum of 30 unique hashtags [within a 7 day period](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/recently_searched_hashtags).

### Requirements

| Type | Description |
| --- | --- |
| [Features](https://developers.facebook.com/docs/feature-reference) | `Instagram Public Content Access` |
| [Permissions](https://developers.facebook.com/docs/permissions) | `instagram_basic`&lt;br&gt;&lt;br&gt;If the token is from a User whose Page role was granted via the Business Manager, one of the following permissions is also required: `ads_management`, `business_management`, or `pages_read_engagement`. |
| Tokens | The app user&#039;s User access token. |

### Request Syntax

```
GET https://graph.facebook.com/&lt;IG_HASHTAG_ID&gt;
  ?fields=&#123;fields&#125;
  &amp;access_token=&#123;access-token&#125;
```

### Query String Parameters

Include the following query string parameters to augment the request.

| Key | Value |
| --- | --- |
| `access_token`  &lt;br&gt;**Required**  &lt;br&gt;*String* | The app user&#039;s Instagram User Access Token. |
| `fields`  &lt;br&gt;*Comma-separated list* | A comma-separated list of [Fields](#fields) and [Edges](#edges) you want returned. If omitted, default fields will be returned. |

### Fields

You can use the `fields` query string parameter to request the following Fields on an IG Hashtag.

| Field Name | Description |
| --- | --- |
| `id` | The hashtag&#039;s ID (included by default). IDs are static and global. |
| `name` | The hashtag&#039;s name, without the leading hash symbol. |

### Edges

You can request the following edges as path parameters or by using the `fields` query string parameter.

| Edge | Description |
| --- | --- |
| [`recent_media`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-hashtag/recent-media#reading) | Get a list of the most recently published photo and video [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects published with a specific hashtag. |
| [`top_media`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-hashtag/top-media#reading) | Returns the most popular photo and video [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects that have been tagged with the hashtag. |

### Response

A JSON-formatted object containing default and requested [Fields](#fields).

```json
&#123;
  &quot;&lt;FIELD_NAME&gt;&quot;:&quot;&lt;FIELD_VALUE&quot;,
  ...
&#125;
```

### Sample Request

```
GET https://graph.facebook.com/17841593698074073
  ?fields=id,name
  &amp;access_token=EAADd...
```

### Sample Response

```
&#123;
  &quot;id&quot;: &quot;17841593698074073&quot;,
  &quot;name&quot;: &quot;coke&quot;
&#125;
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

# Instagram (IG) Hashtag



Represents an Instagram hashtag.

### Limitations

* Only available for Facebook Login for Business

## Creating

This operation is not supported.

## Reading

**`GET /<IG_HASHTAG_ID>`**

Returns [Fields](#fields) and [Edges](#edges) on an IG Hashtag.

### Limitations

You can query a maximum of 30 unique hashtags [within a 7 day period](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/recently_searched_hashtags).

### Requirements

| Type | Description |
| --- | --- |
| [Features](https://developers.facebook.com/docs/feature-reference) | `Instagram Public Content Access` |
| [Permissions](https://developers.facebook.com/docs/permissions) | `instagram_basic`<br><br>If the token is from a User whose Page role was granted via the Business Manager, one of the following permissions is also required: `ads_management`, `business_management`, or `pages_read_engagement`. |
| Tokens | The app user's User access token. |

### Request Syntax

```
GET https://graph.facebook.com/<IG_HASHTAG_ID>
  ?fields={fields}
  &access_token={access-token}
```

### Query String Parameters

Include the following query string parameters to augment the request.

| Key | Value |
| --- | --- |
| `access_token`  <br>**Required**  <br>*String* | The app user's Instagram User Access Token. |
| `fields`  <br>*Comma-separated list* | A comma-separated list of [Fields](#fields) and [Edges](#edges) you want returned. If omitted, default fields will be returned. |

### Fields

You can use the `fields` query string parameter to request the following Fields on an IG Hashtag.

| Field Name | Description |
| --- | --- |
| `id` | The hashtag's ID (included by default). IDs are static and global. |
| `name` | The hashtag's name, without the leading hash symbol. |

### Edges

You can request the following edges as path parameters or by using the `fields` query string parameter.

| Edge | Description |
| --- | --- |
| [`recent_media`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-hashtag/recent-media#reading) | Get a list of the most recently published photo and video [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects published with a specific hashtag. |
| [`top_media`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-hashtag/top-media#reading) | Returns the most popular photo and video [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects that have been tagged with the hashtag. |

### Response

A JSON-formatted object containing default and requested [Fields](#fields).

```json
{
  "<FIELD_NAME>":"<FIELD_VALUE",
  ...
}
```

### Sample Request

```
GET https://graph.facebook.com/17841593698074073
  ?fields=id,name
  &access_token=EAADd...
```

### Sample Response

```
{
  "id": "17841593698074073",
  "name": "coke"
}
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

# Tags



Represents a collection of [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects in which your app user's [Instagram professional account](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) has been tagged by another Instagram user.

## Creating

This operation is not supported.

## Reading

**`GET /<IG_USER_ID>/tags`**

Returns a list of [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects in which an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) has been tagged by another Instagram user.

### Limitations

Private [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects will not be returned.

### Requirements

| Type | Description |
| --- | --- |
| Access Tokens | User |
| [Features](https://developers.facebook.com/docs/feature-reference) | Not applicable. |
| [Permissions](https://developers.facebook.com/docs/permissions#i) | `instagram_basic`<br>`instagram_manage_comments`<br>`pages_read_engagement`<br><br>If the token is from a User whose Page role was granted via the Business Manager, one of the following permissions is also required: `ads_management` or `ads_read`. |
| [Tasks](https://developers.facebook.com/documentation/instagram-platform/overview#tasks) | The app user must be able to perform appropriate Tasks on the Page based on the Permissions requested by the app. |

### Request Syntax

```
GET https://graph.facebook.com/<IG_USER_ID>/tags
  ?fields=<LIST_OF_FIELDS>
  &access_token=<ACCESS_TOKEN>
```

### Query String Parameters

Include the following query string parameters to augment the request.

| Key | Value |
| --- | --- |
| `access_token`  <br>**Required**  <br>*String* | The app user's Instagram User Access Token. |
| `fields`  <br>*Comma-separated list* | A comma-separated list of [Fields](#fields) and [Edges](#edges) you want included in the response. If omitted, default fields will be returned. |

### Fields

Use the `fields` query string parameter to specify fields you want included on any returned [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#read) objects.

### Edges

Use the `fields` query string parameter to specify Edges you want included on any returned [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#read) objects.

### Response

A JSON-formatted object containing [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects.

```json
{
  "<FIELD>":"<VALUE>",
  ...
}
```

### Pagination

This edge supports [cursor-based pagination](https://developers.facebook.com/docs/graph-api/using-graph-api#paging) so the response will include `before` and `after` cursors if the response contains multiple pages of data. Unlike standard cursor-based pagination, however, the response will not include `previous` or `next` fields, so you will have to use the `before` and `after` cursors to construct `previous` and `next` query strings manually in order to page through the returned data set.

### Sample Request

```
GET graph.facebook.com/17841405822304914/tags
    ?fields=id,username
    &access_token=EAADd...
```

### Sample Response

```
{
  "data": [
    {
      "id": "18038...",
      "username": "keldo..."
    },
    {
      "id": "17930...",
      "username": "ashla..."
    },
    {
      "id": "17931...",
      "username": "jaypo..."
    }
  ]
}
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

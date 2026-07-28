# IG User Live Media



Represents a collection of live video [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) on an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user).

## Creating

This operation is not supported.

## Reading

**`GET /{ig-user-id}/live_media`**

Get a collection of live video [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) on an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user).

### Limitations

Only live video IG Media being broadcast at the time of the request will be returned.

### Time-based Pagination

This endpoint supports [time-based pagination](https://developers.facebook.com/docs/graph-api/using-graph-api#time). Include `since` and `until` query-string paramaters with Unix timestamp or `strtotime` data values to define a time range.

### Requirements

| Type | Requirement |
| --- | --- |
| Access Tokens | User |
| [Permissions](https://developers.facebook.com/docs/permissions) | `instagram_basic`<br>`pages_read_engagement`<br><br>If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need one of:<br><br>`ads_management`<br>`ads_read` |

### Request Syntax

```
GET https://graph.facebook.com/{api-version}/{ig-user-id}/live_media
  ?access_token={access-token}
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `{api-version}`  <br>*String* | API version |
| `{ig-user-id}`  <br>**Required**  <br>*String* | App user's app-scoped user ID. |

### Query String Parameters

| Key | Value |
| --- | --- |
| `access_token`  <br>**Required**  <br>*String* | App user's User |
| `fields`  <br>*Comma-separated list* | Comma-separated list of IG Media [fields](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#fields) you want returned for each live IG Media in the result set. |
| `since`  <br>*timestamp* | A Unix timestamp or `strtotime` data value that points to the start of a range of time-based data. See [time-based pagination](https://developers.facebook.com/docs/graph-api/using-graph-api#time). |
| `until`  <br>*timestamp* | A Unix timestamp or `strtotime` data value that points to the end of a range of time-based data. See [time-based pagination](https://developers.facebook.com/docs/graph-api/using-graph-api#time). |

### Response

A JSON-formatted object containing the data you requested.

```json
{
  "data": [],
  "paging": {}
}
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
  'https://graph.facebook.com/v25.0/17841405822304914/live_media?fields=id,media_type,media_product_type,owner,username,comments&access_token=IGQVJ...'
```

#### Response

```json
{
   "id":"90010498116233",
   "media_type":"BROADCAST",
   "media_product_type":"LIVE",
   "owner":{
      "id":"17841405822304914"
   },
   "username":"jayposiris",
   "comments":{
      "data":[
        {
            "hidden": false,
            "id": "17907364514064687",
            "like_count": 0,
            "media": {
                "id": "17892642502701087"
            },
            "text": "@jayposiris",
            "timestamp": "2021-08-17T21:23:07+0000",
            "username": "bztest0316_11",
            "from": {
                "id": "5895605157123796",
                "username": "bztest0316_11"
            }
        }
      ]
   }
}
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

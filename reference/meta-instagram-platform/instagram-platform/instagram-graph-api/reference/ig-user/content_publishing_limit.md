# IG User Content Publishing Limit



Represents an [IG User's](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) current [content publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing) usage.

### Requirements

|  | Instagram API with Instagram Login | Instagram  API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User user access token | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`<br>* `instagram_business_content_publish` | * `instagram_basic`<br>* `instagram_content_publish`<br>* `pages_read_engagement`<br><br>If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need one of:<br><br>* `ads_management`<br>* `ads_read` |

## Creating

This operation is not supported.

## Reading

**`GET /<IG_USER_ID>/content_publishing_limit`**

Get the number of times an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) has published and [IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) within a given time period. Refer to the [Content Publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing) guide for complete publishing steps.

### Request Syntax

```http
GET https://graph.facebook.com/<API_VERSION>/<IG_USER_ID>/content_publishing_limit
  ?fields=<LIST_OF_FIELDS>
  &since=<UNIX_TIMESTAMP>
  &access_token=<ACCESS_TOKEN>
```

### Query String Parameters

| Placeholder | Value Description |
| --- | --- |
| `<ACCESS_TOKEN>`  <br>**Required**  <br>*String* | The app user's User Access Token. |
| `<LIST_OF_FIELDS>`  <br>*Comma-separated list* | A comma-separated list of [fields](#fields) you want returned. If omitted, the `quota_usage` field will be returned by default. |
| `<UNIX_TIMESTAMP>`  <br>*Unix timestamp* | A Unix timestamp no older than 24 hours. |

### Fields

| Field | Value Description |
| --- | --- |
| `config`  <br>*Object* | Returns these values:<br><br>* `quota_total` — The maximum number of [IG Containers](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) the app user can publish within the `quota_duration` time period (currently `50`).<br>* `quota_duration` — The period of time in seconds against which the `quota_total` is calculated (currently `86400` seconds, or 24 hours). |
| `quota_usage`  <br>*Comma-separated list* | The number of times the app user has published an [IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) since the time specified in the `since` query string parameter. If the `since` parameter is omitted, this value will be the number of times the app user has published a container within the last 24 hours. This field is returned by default if the `fields` query string parameter is omitted from the query. |

### Example Request

```curl
curl -X GET \
  'https://graph.facebook.com/v25.0/17841405822304914/content_publishing_limit?fields=quota_usage,rate_limit_settings&since=1609969714&access_token=IGQVJ...'
```

### Example Response

```json
{
  "data": [
    {
      "quota_usage": 2,
      "config": {
        "quota_total": 50,
        "quota_duration": 86400
      }
    }
  ]
}
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

# IG User Content Publishing Limit



Represents an [IG User&#039;s](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) current [content publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing) usage.

### Requirements

|  | Instagram API with Instagram Login | Instagram  API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User user access token | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`&lt;br&gt;* `instagram_business_content_publish` | * `instagram_basic`&lt;br&gt;* `instagram_content_publish`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;&lt;br&gt;If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need one of:&lt;br&gt;&lt;br&gt;* `ads_management`&lt;br&gt;* `ads_read` |

## Creating

This operation is not supported.

## Reading

**`GET /&lt;IG_USER_ID&gt;/content_publishing_limit`**

Get the number of times an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) has published and [IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) within a given time period. Refer to the [Content Publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing) guide for complete publishing steps.

### Request Syntax

```http
GET https://graph.facebook.com/&lt;API_VERSION&gt;/&lt;IG_USER_ID&gt;/content_publishing_limit
  ?fields=&lt;LIST_OF_FIELDS&gt;
  &amp;since=&lt;UNIX_TIMESTAMP&gt;
  &amp;access_token=&lt;ACCESS_TOKEN&gt;
```

### Query String Parameters

| Placeholder | Value Description |
| --- | --- |
| `&lt;ACCESS_TOKEN&gt;`  &lt;br&gt;**Required**  &lt;br&gt;*String* | The app user&#039;s User Access Token. |
| `&lt;LIST_OF_FIELDS&gt;`  &lt;br&gt;*Comma-separated list* | A comma-separated list of [fields](#fields) you want returned. If omitted, the `quota_usage` field will be returned by default. |
| `&lt;UNIX_TIMESTAMP&gt;`  &lt;br&gt;*Unix timestamp* | A Unix timestamp no older than 24 hours. |

### Fields

| Field | Value Description |
| --- | --- |
| `config`  &lt;br&gt;*Object* | Returns these values:&lt;br&gt;&lt;br&gt;* `quota_total` — The maximum number of [IG Containers](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) the app user can publish within the `quota_duration` time period (currently `50`).&lt;br&gt;* `quota_duration` — The period of time in seconds against which the `quota_total` is calculated (currently `86400` seconds, or 24 hours). |
| `quota_usage`  &lt;br&gt;*Comma-separated list* | The number of times the app user has published an [IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) since the time specified in the `since` query string parameter. If the `since` parameter is omitted, this value will be the number of times the app user has published a container within the last 24 hours. This field is returned by default if the `fields` query string parameter is omitted from the query. |

### Example Request

```curl
curl -X GET \
  &#039;https://graph.facebook.com/v25.0/17841405822304914/content_publishing_limit?fields=quota_usage,rate_limit_settings&amp;since=1609969714&amp;access_token=IGQVJ...&#039;
```

### Example Response

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;quota_usage&quot;: 2,
      &quot;config&quot;: &#123;
        &quot;quota_total&quot;: 50,
        &quot;quota_duration&quot;: 86400
      &#125;
    &#125;
  ]
&#125;
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

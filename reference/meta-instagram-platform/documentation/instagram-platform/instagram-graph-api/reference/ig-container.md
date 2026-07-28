# Instagram (IG) Container



Represents a media container for publishing an Instagram media object.

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

**`GET &lt;HOST_URL&gt;/&lt;IG_CONTAINER_ID&gt;`**

Get [fields](#fields) and [edges](#edges) on an IG Container.

### Request Syntax

```
GET &lt;HOST_URL&gt;/&lt;API_VERSION&gt;/&lt;IG_CONTAINER_ID&gt;
  ?fields=&lt;LIST_OF_FIELDS&gt;
  &amp;access_token=&lt;ACCESS_TOKEN&gt;
```

### Query String Parameters

| Parameter | Value |
| --- | --- |
| `access_token`  &lt;br&gt;**Required**  &lt;br&gt;*String* | The app user&#039;s [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |
| `fields`  &lt;br&gt;*Comma-separated list* | A comma-separated list of [fields](#fields) and [edges](#edges) you want returned. If omitted, default fields will be returned. |

### Fields

| Field Name | Description |
| --- | --- |
| `copyright_check_status` | Used to determine if an uploaded video is violating copyright. Key-values pairs return include:&lt;br&gt;&lt;br&gt;* `matches_found` set to one of the following:&lt;br&gt;    * `true` – the video is violating copyright&lt;br&gt;    * `false` – the video is not violating copyright&lt;br&gt;* `status` set to one of the following:&lt;br&gt;    * `completed` – the detection process has finished&lt;br&gt;    * `error` – an error occurred during the detection process&lt;br&gt;    * `in_progress` – the detection process is ongoing&lt;br&gt;    * `not_started` – the detection process has not started |
| `id` | Instagram Container ID, represented in code examples as `&lt;IG_CONTAINER_ID&gt;` |
| `status` | Publishing status. If `status_code` is `ERROR`, this value will be an [error subcode](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/error-codes). |
| `status_code` | The container&#039;s publishing status. Possible values:&lt;br&gt;&lt;br&gt;- `EXPIRED` — The container was not published within 24 hours and has expired.&lt;br&gt;- `ERROR` — The container failed to complete the publishing process.&lt;br&gt;- `FINISHED` — The container and its media object are ready to be published.&lt;br&gt;- `IN_PROGRESS` — The container is still in the publishing process.&lt;br&gt;- `PUBLISHED` — The container&#039;s media object has been published. |

### Edges

There are no edges on this node.

### Response

A JSON-formatted object containing default and requested [fields](#fields).

```json
&#123;
  &quot;&lt;FIELD&gt;&quot;:&quot;&lt;VALUE&gt;&quot;,
  ...
&#125;
```

### Example Request

```curl
curl -X GET \
  &#039;https://graph.instagram.com/17889615691921648?fields=status_code&amp;access_token=IGQVJ...&#039;
```

### Sample Response

```json
&#123;
  &quot;status_code&quot;: &quot;FINISHED&quot;,
  &quot;id&quot;: &quot;17889615691921648&quot;
&#125;
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

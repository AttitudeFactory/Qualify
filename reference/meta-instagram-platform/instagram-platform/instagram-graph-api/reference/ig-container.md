# Instagram (IG) Container



Represents a media container for publishing an Instagram media object.

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

**`GET <HOST_URL>/<IG_CONTAINER_ID>`**

Get [fields](#fields) and [edges](#edges) on an IG Container.

### Request Syntax

```
GET <HOST_URL>/<API_VERSION>/<IG_CONTAINER_ID>
  ?fields=<LIST_OF_FIELDS>
  &access_token=<ACCESS_TOKEN>
```

### Query String Parameters

| Parameter | Value |
| --- | --- |
| `access_token`  <br>**Required**  <br>*String* | The app user's [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |
| `fields`  <br>*Comma-separated list* | A comma-separated list of [fields](#fields) and [edges](#edges) you want returned. If omitted, default fields will be returned. |

### Fields

| Field Name | Description |
| --- | --- |
| `copyright_check_status` | Used to determine if an uploaded video is violating copyright. Key-values pairs return include:<br><br>* `matches_found` set to one of the following:<br>    * `true` – the video is violating copyright<br>    * `false` – the video is not violating copyright<br>* `status` set to one of the following:<br>    * `completed` – the detection process has finished<br>    * `error` – an error occurred during the detection process<br>    * `in_progress` – the detection process is ongoing<br>    * `not_started` – the detection process has not started |
| `id` | Instagram Container ID, represented in code examples as `<IG_CONTAINER_ID>` |
| `status` | Publishing status. If `status_code` is `ERROR`, this value will be an [error subcode](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/error-codes). |
| `status_code` | The container's publishing status. Possible values:<br><br>- `EXPIRED` — The container was not published within 24 hours and has expired.<br>- `ERROR` — The container failed to complete the publishing process.<br>- `FINISHED` — The container and its media object are ready to be published.<br>- `IN_PROGRESS` — The container is still in the publishing process.<br>- `PUBLISHED` — The container's media object has been published. |

### Edges

There are no edges on this node.

### Response

A JSON-formatted object containing default and requested [fields](#fields).

```json
{
  "<FIELD>":"<VALUE>",
  ...
}
```

### Example Request

```curl
curl -X GET \
  'https://graph.instagram.com/17889615691921648?fields=status_code&access_token=IGQVJ...'
```

### Sample Response

```json
{
  "status_code": "FINISHED",
  "id": "17889615691921648"
}
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

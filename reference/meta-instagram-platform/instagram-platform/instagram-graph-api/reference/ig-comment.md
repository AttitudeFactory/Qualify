# Instagram (IG) Comment



Represents a comment on an [Instagram media object](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media).

**Warning:** If you are migrating from Marketing API Instagram Ads endpoints to Instagram Platform endpoints, be aware that some field names are different.

Introducing the following fields:

* `legacy_instagram_comment_id`

The following fields are not supported:

* `comment_type`
* `mentioned_instagram_users`

### Requirements

|  | Instagram API with Instagram Login | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User access token | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`<br>* `instagram_business_manage_comments` | * `instagram_basic`<br>* `instagram_manage_comments`<br>* `pages_read_engagement`<br><br>If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need one of:<br><br>* `ads_management`<br>* `ads_read` |

## Creating

This operation is not supported.

## Reading

**`GET <HOST_URL>/<IG_COMMENT_ID>?fields=<LIST_OF_FIELDS>`**

Get [fields](#fields) and [edges](#edges) on an IG Comment.

### Limitations

* Requests cannot be performed on comments discovered through the Mentions API unless the request is made by the comment owner. Instead, use the Mentioned Comment node.
* Comments on age-gated media are not returned.
* Comments created by IG Users who have been restricted by the app user will not be returned unless the IG Users are unrestricted and the Comments are approved.
* Comments on live video IG Media can only be read while the IG Media upon which the comment was created is being broadcast.

### Request Syntax

```
GET https://<HOST_URL>/<API_VERSION>/<IG_COMMENT_ID>
  ?fields=<LIST_OF_FIELDS>
  &access_token=<ACCESS_TOKEN>
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `<API_VERSION>` | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `<HOST_URL>` | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `<IG_COMMENT_ID>` | **Required.** IG Comment ID. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `<ACCESS_TOKEN>` | **Required.** App user's [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |
| `fields` | `<LIST_OF_FIELDS>` | Comma-separated list of IG Comment [fields](#fields) you want returned for each IG Comment in the result set. |

### Fields

| Field Name | Description |
| --- | --- |
| `from` | An object containing:<br><br>* `id` — The [Instagram-scoped ID (IGSID)](https://developers.facebook.com/documentation/instagram-platform/overview#igsid) of the Instagram user who created the IG Comment.<br>* `username` — Username of the Instagram user who created the IG Comment. |
| `hidden` | Indicates if comment has been hidden (`true`) or not (`false`). |
| `id` | IG Comment ID. |
| `like_count` | Number of likes on the IG Comment. |
| `legacy_instagram_comment_id` | The ID for Instagram comment that was created for Marketing API endpoints for v21.0 and older. |
| `media` | An object containing:<br><br>* `id` — ID of the [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) upon which the IG Comment was made.<br>* `media_product_type` — Published surface of the [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) (i.e. where the IG Media appears) upon which the IG Comment was made. |
| `parent_id` | ID of the parent IG Comment if this comment was created on another IG Comment (i.e. a reply to another comment. |
| `replies` | A list of replies (IG Comments) made on the IG Comment. |
| `text` | IG Comment text. |
| `timestamp` | ISO 8601 formatted timestamp indicating when IG Comment was created.<br><br>Example: `2017-05-19T23:27:28+0000`. |
| `user` | ID of IG User who created the IG Comment. Only returned if the app user created the IG Comment, otherwise `username` will be returned instead. |
| `username` | Username of Instagram user who created the IG Comment.<br><br>**Warning:** Starting August 27, 2024, the `instagram_manage_comments` permission (if your app uses Facebook login) and  `instagram_business_manage_comments` permission (if your app uses Instagram login) will be required to access the `username` field of an Instagram user who commented on media of an app user's Instagram professional account. |

### Edges

| Edge | Description |
| --- | --- |
| [`replies`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment/replies) | Get a list of IG Comments on the IG Comment; Create an IG Comment on an IG Comment. |

### Response

A JSON-formatted object containing default and requested [fields](#fields) and [edges](#edges).

```json
{
  "<FIELD>":"<VALUE>",
  ...
}
```

### cURL Example

#### Request

```curl
curl -i -X GET \
 "https://graph.instagram.com/v25.0/17881770991003328?fields=hidden%2Cmedia%2Ctimestamp&access_token=EAAOc..."
```

#### Response

```json
{
  "hidden": false,
  "media": {
    "id": "17856134461174448"
  },
  "timestamp": "2017-05-19T23:27:28+0000",
  "id": "17881770991003328"
}
```

## Updating

### Hiding/Unhiding a Comment {#hiding}

`POST <HOST_URL>/<IG_COMMENT_ID>?hide=<BOOLEAN>`

#### Query String Parameters

- `hide` (required) — Set to `true` to hide the comment, or `false` to show the comment.

#### Limitations

- Comments made by media object owners on their own media objects will always be displayed, even if the comments have been set to `hide=true`.
- Comments on live video IG Media are not supported.

#### Access token

A user access token from the user who owns the media object that was commented on.

#### Example Request

Hiding a comment:

```
POST graph.instagram.com
  /17873440459141021?hide=true
```

#### Example Response

```
{
  "success": true
}
```

## Deleting

### Deleting a Comment {#deleting}

`DELETE <HOST_URL>/<IG_COMMENT_ID>`

#### Access token

A User access token from a User who created the comment.

#### Limitations

- A comment can only be deleted by the owner of the object upon which the comment was made, even if the user attempting to delete the comment is the comment's author.
- Comments on live video IG Media are not supported.

#### Example Request

```
DELETE graph.instagram.com
  /17873440459141021
```

#### Example Response

```
{
  "success": true
}
```

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
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_comments` | * `instagram_basic`&lt;br&gt;* `instagram_manage_comments`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;&lt;br&gt;If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need one of:&lt;br&gt;&lt;br&gt;* `ads_management`&lt;br&gt;* `ads_read` |

## Creating

This operation is not supported.

## Reading

**`GET &lt;HOST_URL&gt;/&lt;IG_COMMENT_ID&gt;?fields=&lt;LIST_OF_FIELDS&gt;`**

Get [fields](#fields) and [edges](#edges) on an IG Comment.

### Limitations

* Requests cannot be performed on comments discovered through the Mentions API unless the request is made by the comment owner. Instead, use the Mentioned Comment node.
* Comments on age-gated media are not returned.
* Comments created by IG Users who have been restricted by the app user will not be returned unless the IG Users are unrestricted and the Comments are approved.
* Comments on live video IG Media can only be read while the IG Media upon which the comment was created is being broadcast.

### Request Syntax

```
GET https://&lt;HOST_URL&gt;/&lt;API_VERSION&gt;/&lt;IG_COMMENT_ID&gt;
  ?fields=&lt;LIST_OF_FIELDS&gt;
  &amp;access_token=&lt;ACCESS_TOKEN&gt;
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&lt;API_VERSION&gt;` | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `&lt;HOST_URL&gt;` | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `&lt;IG_COMMENT_ID&gt;` | **Required.** IG Comment ID. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `&lt;ACCESS_TOKEN&gt;` | **Required.** App user&#039;s [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |
| `fields` | `&lt;LIST_OF_FIELDS&gt;` | Comma-separated list of IG Comment [fields](#fields) you want returned for each IG Comment in the result set. |

### Fields

| Field Name | Description |
| --- | --- |
| `from` | An object containing:&lt;br&gt;&lt;br&gt;* `id` — The [Instagram-scoped ID (IGSID)](https://developers.facebook.com/documentation/instagram-platform/overview#igsid) of the Instagram user who created the IG Comment.&lt;br&gt;* `username` — Username of the Instagram user who created the IG Comment. |
| `hidden` | Indicates if comment has been hidden (`true`) or not (`false`). |
| `id` | IG Comment ID. |
| `like_count` | Number of likes on the IG Comment. |
| `legacy_instagram_comment_id` | The ID for Instagram comment that was created for Marketing API endpoints for v21.0 and older. |
| `media` | An object containing:&lt;br&gt;&lt;br&gt;* `id` — ID of the [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) upon which the IG Comment was made.&lt;br&gt;* `media_product_type` — Published surface of the [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) (i.e. where the IG Media appears) upon which the IG Comment was made. |
| `parent_id` | ID of the parent IG Comment if this comment was created on another IG Comment (i.e. a reply to another comment. |
| `replies` | A list of replies (IG Comments) made on the IG Comment. |
| `text` | IG Comment text. |
| `timestamp` | ISO 8601 formatted timestamp indicating when IG Comment was created.&lt;br&gt;&lt;br&gt;Example: `2017-05-19T23:27:28+0000`. |
| `user` | ID of IG User who created the IG Comment. Only returned if the app user created the IG Comment, otherwise `username` will be returned instead. |
| `username` | Username of Instagram user who created the IG Comment.&lt;br&gt;&lt;br&gt;**Warning:** Starting August 27, 2024, the `instagram_manage_comments` permission (if your app uses Facebook login) and  `instagram_business_manage_comments` permission (if your app uses Instagram login) will be required to access the `username` field of an Instagram user who commented on media of an app user&#039;s Instagram professional account. |

### Edges

| Edge | Description |
| --- | --- |
| [`replies`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment/replies) | Get a list of IG Comments on the IG Comment; Create an IG Comment on an IG Comment. |

### Response

A JSON-formatted object containing default and requested [fields](#fields) and [edges](#edges).

```json
&#123;
  &quot;&lt;FIELD&gt;&quot;:&quot;&lt;VALUE&gt;&quot;,
  ...
&#125;
```

### cURL Example

#### Request

```curl
curl -i -X GET \
 &quot;https://graph.instagram.com/v25.0/17881770991003328?fields=hidden%2Cmedia%2Ctimestamp&amp;access_token=EAAOc...&quot;
```

#### Response

```json
&#123;
  &quot;hidden&quot;: false,
  &quot;media&quot;: &#123;
    &quot;id&quot;: &quot;17856134461174448&quot;
  &#125;,
  &quot;timestamp&quot;: &quot;2017-05-19T23:27:28+0000&quot;,
  &quot;id&quot;: &quot;17881770991003328&quot;
&#125;
```

## Updating

### Hiding/Unhiding a Comment &#123;#hiding&#125;

`POST &lt;HOST_URL&gt;/&lt;IG_COMMENT_ID&gt;?hide=&lt;BOOLEAN&gt;`

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
&#123;
  &quot;success&quot;: true
&#125;
```

## Deleting

### Deleting a Comment &#123;#deleting&#125;

`DELETE &lt;HOST_URL&gt;/&lt;IG_COMMENT_ID&gt;`

#### Access token

A User access token from a User who created the comment.

#### Limitations

- A comment can only be deleted by the owner of the object upon which the comment was made, even if the user attempting to delete the comment is the comment&#039;s author.
- Comments on live video IG Media are not supported.

#### Example Request

```
DELETE graph.instagram.com
  /17873440459141021
```

#### Example Response

```
&#123;
  &quot;success&quot;: true
&#125;
```

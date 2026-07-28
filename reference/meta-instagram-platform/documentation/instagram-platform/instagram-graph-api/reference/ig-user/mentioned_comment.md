# IG User Mentioned Comment



Returns data on an [IG Comment](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) in which an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) has been &#064;mentioned by another Instagram user.

## Creating

This operation is not supported.

## Reading

**`GET /&#123;ig-user-id&#125;?fields=mentioned_comment.comment_id`**

Returns data on an [IG Comment](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) in which an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) has been &#064;mentioned by another Instagram user.

### Limitations

This endpoint will return an error if comments have been disabled on the [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) on which the [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) has been &#064;mentioned.

### Requirements

| Type | Description |
| --- | --- |
| [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) | [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| [Permissions](https://developers.facebook.com/docs/apps/review/login-permissions) | [`instagram_basic`](https://developers.facebook.com/docs/permissions/reference/instagram_basic)  &lt;br&gt;[`instagram_manage_comments`](https://developers.facebook.com/docs/permissions/reference/instagram_manage_comments)  &lt;br&gt;[`pages_read_engagement`](https://developers.facebook.com/docs/permissions/reference/pages_read_engagement)  &lt;br&gt;&lt;br&gt;If the app user was granted a role on the Page via the Business Manager, you will also need one of:&lt;br&gt;&lt;br&gt;[`ads_management`](https://developers.facebook.com/docs/permissions/reference/ads_management)  &lt;br&gt;`ads_read` |
| [Tasks](https://developers.facebook.com/documentation/instagram-platform/overview#tasks) | `MANAGE`, `CREATE_CONTENT`, or `MODERATE` |

### Request Syntax

```http
GET https://graph.facebook.com/v25.0/&#123;ig-user-id&#125;
  ?fields=mentioned_comment.comment_id(&#123;comment-id&#125;)&#123;&#123;fields&#125;&#125;
  &amp;access_token=&#123;access-token&#125;
```

### Query String Parameters

| Parameter | Value |
| --- | --- |
| `&#123;access_token&#125;`  &lt;br&gt;**Required**  &lt;br&gt;*String* | The app user&#039;s User Access Token. |
| `&#123;comment-id&#125;`  &lt;br&gt;**Required**  &lt;br&gt;*String* | The ID of the IG Comment in which the IG User has been &#064;mentioned. The ID is included in the [Webhook notification](https://developers.facebook.com/documentation/instagram-platform/webhooks#reply-comment-mention) payload. |
| `&#123;fields&#125;`  &lt;br&gt;*Comma-separated list* | A comma-separated list of IG Comment [Fields](#fields) you want returned.  If omitted, default fields will be returned. |

### Fields

| Field | Description |
| --- | --- |
| `id`  &lt;br&gt;**Default**  &lt;br&gt;*String* | ID of the IG Comment. |
| `like_count`  &lt;br&gt;*String* | Number of times the IG Comment has been liked. |
| `media`  &lt;br&gt;*String* | ID of the IG Media on which the IG Comment was made. Use [Field Expansion](#field-expansion) to get additional fields on the returned IG Media entity. |
| `text`  &lt;br&gt;**Default**  &lt;br&gt;*String* | Text of the IG Comment. |
| `timestamp`  &lt;br&gt;**Default**  &lt;br&gt;*String* | IG Comment creation date formatted in ISO 8601. |

### Response

### Sample Request

```curl
curl -X GET \
  &#039;https://graph.facebook.com/v25.0/17841405309211844?fields=mentioned_comment.comment_id(17873440459141021)&#123;timestamp,like_count,text,id&#125;&amp;access_token=IGQVJ...&#039;
```

#### Sample Response

```json
&#123;
  &quot;mentioned_comment&quot;: &#123;
    &quot;timestamp&quot;: &quot;2017-05-03T16:09:08+0000&quot;,
    &quot;like_count&quot;: 185,
    &quot;text&quot;: &quot;Shout out to &#064;metricsaurus&quot;,
    &quot;id&quot;: &quot;17873440459141021&quot;
  &#125;,
  &quot;id&quot;: &quot;17841405309211844&quot;
&#125;
```

### Field Expansion

You can expand the `media` field with a list of [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) fields to get additional data on the IG Media entity on which the comment was made. For example:

```http
media&#123;id,media_url&#125;
```

**Warning:** **v10.0 and older calls until September 7, 2021:** The [`like_count`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#fields) field on an IG Media will return `0` if the media [owner](https://developers.facebook.com/documentation/instagram-platform/overview#authorization) has [hidden](https://www.facebook.com/help/instagram/113355287252104) like counts on it.

**v11.0+ calls, and all versions on September 7, 2021:** If indirectly querying an [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) through another endpoint or field expansion, the [`like_count`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#fields) field will be omitted from API responses if the media owner has hidden like counts on it. Directly querying the IG Media (which can only be done by the IG Media owner) will return the actual like count, however, even if like counts have been hidden.

#### Sample Field Expansion Request

```curl
curl -X GET \
  &#039;https://graph.facebook.com/v25.0/17841405309211844?fields=mentioned_comment.comment_id(17873440459141021)&#123;timestamp,like_count,text,media&#123;id,media_url&#125;&#125;&amp;access_token=IGQVJ...&#039;
```

#### Sample Field Expansion Response

```json
&#123;
  &quot;mentioned_comment&quot;: &#123;
    &quot;timestamp&quot;: &quot;2017-05-03T16:09:08+0000&quot;,
    &quot;like_count&quot;: 185,
    &quot;text&quot;: &quot;Shout out to &#064;metricsaurus&quot;,
    &quot;id&quot;: &quot;17873440459141021&quot;,
    &quot;media&quot;: &#123;
      &quot;id&quot;: &quot;17895695668004550&quot;,
      &quot;media_url&quot;: &quot;https://scont...&quot;
    &#125;
  &#125;,
  &quot;id&quot;: &quot;17841405309211844&quot;
&#125;
```

### Pagination

If you are using field expansion to access an edge that supports [cursor-based pagination](https://developers.facebook.com/docs/graph-api/using-graph-api#paging), the response will include `before` and `after` cursors if the response contains multiple pages of data. Unlike standard cursor-based pagination, however, the response will not include `previous` or `next` fields, so you will have to use the `before` and `after` cursors to construct `previous` and `next` query strings manually in order to page through the returned data set.

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

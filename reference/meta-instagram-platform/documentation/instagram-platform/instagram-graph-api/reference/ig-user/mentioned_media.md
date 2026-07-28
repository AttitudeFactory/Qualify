# Mentioned Media



Returns data on an [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) in which an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) has been &#064;mentioned in a caption by another Instagram user.  

## Creating

This operation is not supported.

## Reading

**`GET /&#123;ig-user-id&#125;?fields=mentioned_media.media_id`**

Returns data on an [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) in which an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) has been &#064;mentioned in a caption by another Instagram user.

### Limitations

* Mentions on Stories are not supported.
* Commenting on photos in which you were tagged is not supported.
* Webhooks will not be sent if the Media upon which the comment or &#064;mention appears was created by an account that is set to private.

### Requirements

| Type | Description |
| --- | --- |
| [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) | [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| [Permissions](https://developers.facebook.com/docs/apps/review/login-permissions) | [`instagram_basic`](https://developers.facebook.com/docs/permissions/reference/instagram_basic)  &lt;br&gt;[`instagram_manage_comments`](https://developers.facebook.com/docs/permissions/reference/instagram_manage_comments)  &lt;br&gt;[`pages_read_engagement`](https://developers.facebook.com/docs/permissions/reference/pages_read_engagement)  &lt;br&gt;&lt;br&gt;If the app user was granted a role on the Page via the Business Manager, you will also need one of:&lt;br&gt;&lt;br&gt;[`ads_management`](https://developers.facebook.com/docs/permissions/reference/ads_management)  &lt;br&gt;`ads_read` |
| [Tasks](https://developers.facebook.com/documentation/instagram-platform/overview#tasks) | `MANAGE`, `CREATE_CONTENT`, or `MODERATE` |

### Request Syntax

```http
GET https://graph.facebook.com/v25.0/&#123;ig-user-id&#125;
  ?fields=mentioned_media.media_id(&#123;media-id&#125;)&#123;&#123;fields&#125;&#125;
  &amp;access_token=&#123;access-token&#125;
```

### Query String Parameters

| Parameter | Value |
| --- | --- |
| `&#123;access_token&#125;`  &lt;br&gt;**Required**  &lt;br&gt;*String* | The app user&#039;s User Access Token. |
| `&#123;fields&#125;`  &lt;br&gt;*Comma-separated list* | A comma-separated list of IG Media [Fields](#fields) you want returned.  If omitted, default Fields will be returned. |
| `&#123;media-id&#125;`  &lt;br&gt;**Required**  &lt;br&gt;*String* | The ID of the IG Media in which the IG User has been &#064;mentioned in a caption. The ID is included in the [Webhook notification](https://developers.facebook.com/documentation/instagram-platform/webhooks#reply-comment-mention) payload. |

### Fields

| Field | Description |
| --- | --- |
| `caption`  &lt;br&gt;*String* | The caption text. Captions that &#064;mention an IG User will not include the `&#064;` symbol unless the app user created the IG Media object upon which the caption was made. |
| `comments`  &lt;br&gt;*Object* | A list of IG Comments on the IG Media. If using Field Expansion to get the comment text, text that &#064;mentions an IG User will not include the `&#064;` symbol unless the app user created the IG Media object upon which the caption was made. |
| `comments_count`  &lt;br&gt;*String* | Number of IG Comments on the IG Media. |
| `id`  &lt;br&gt;**Default**  &lt;br&gt;*String* | ID of the IG Media. |
| `like_count`  &lt;br&gt;*String* | Count of likes on the media. Excludes likes on album child media and likes on promoted posts created from the media. Includes replies on comments.&lt;br&gt;&lt;br&gt;* **v10.0 and older calls:** value will be `0` if the media owner has [hidden](https://www.facebook.com/help/instagram/113355287252104) like counts it.&lt;br&gt;* **v11.0+ calls:** field will be omitted if media owner has hidden like counts in it&lt;br&gt;Value will be `0` if the media owner has [hidden](https://www.facebook.com/help/instagram/113355287252104) like counts it. |
| `media_type`  &lt;br&gt;*String* | The IG Media&#039;s type: `CAROUSEL_ALBUM`, `IMAGE`, `STORY`, or `VIDEO`. |
| `media_url`  &lt;br&gt;*String* | URL of the published IG Media. |
| `owner`  &lt;br&gt;*String* | ID of the IG User who created the IG Media. Only returned if the app user created the IG Media object, otherwise the `username` field will be returned instead. |
| `timestamp`  &lt;br&gt;*String* | Creation date of IG Media formatted in ISO 8601. |
| `username`  &lt;br&gt;*String* | Username of the IG User who created the IG Media. |

### Sample Request

```curl
curl -X GET \
  &#039;https://graph.facebook.com/v25.0/17841405309211844?fields=mentioned_media.media_id(17873440459141021)&#123;caption,media_type&#125;&amp;access_token=IGQVJ...&#039;
```

### Sample Response

```json
&#123;
  &quot;mentioned_media&quot;: &#123;
    &quot;caption&quot;: &quot;metricsaurus headquarters!&quot;,
    &quot;media_type&quot;: &quot;IMAGE&quot;,
    &quot;id&quot;: &quot;17873440459141021&quot;
  &#125;,
  &quot;id&quot;: &quot;17841405309211844&quot;
&#125;
```

Note that in the sample above, the API has stripped out the leading `&#064;` symbol from the original caption (&#064;metricsaurus headquarters!) because the app user did not create the caption.

### Pagination

If you are using field expansion to access an edge that supports [cursor-based pagination](https://developers.facebook.com/docs/graph-api/using-graph-api#paging), the response will include `before` and `after` cursors if the response contains multiple pages of data. Unlike standard cursor-based pagination, however, the response will not include `previous` or `next` fields, so you will have to use the `before` and `after` cursors to construct `previous` and `next` query strings manually in order to page through the returned data set.

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

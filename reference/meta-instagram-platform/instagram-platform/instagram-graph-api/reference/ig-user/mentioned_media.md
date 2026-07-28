# Mentioned Media



Returns data on an [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) in which an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) has been @mentioned in a caption by another Instagram user.  

## Creating

This operation is not supported.

## Reading

**`GET /{ig-user-id}?fields=mentioned_media.media_id`**

Returns data on an [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) in which an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) has been @mentioned in a caption by another Instagram user.

### Limitations

* Mentions on Stories are not supported.
* Commenting on photos in which you were tagged is not supported.
* Webhooks will not be sent if the Media upon which the comment or @mention appears was created by an account that is set to private.

### Requirements

| Type | Description |
| --- | --- |
| [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) | [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| [Permissions](https://developers.facebook.com/docs/apps/review/login-permissions) | [`instagram_basic`](https://developers.facebook.com/docs/permissions/reference/instagram_basic)  <br>[`instagram_manage_comments`](https://developers.facebook.com/docs/permissions/reference/instagram_manage_comments)  <br>[`pages_read_engagement`](https://developers.facebook.com/docs/permissions/reference/pages_read_engagement)  <br><br>If the app user was granted a role on the Page via the Business Manager, you will also need one of:<br><br>[`ads_management`](https://developers.facebook.com/docs/permissions/reference/ads_management)  <br>`ads_read` |
| [Tasks](https://developers.facebook.com/documentation/instagram-platform/overview#tasks) | `MANAGE`, `CREATE_CONTENT`, or `MODERATE` |

### Request Syntax

```http
GET https://graph.facebook.com/v25.0/{ig-user-id}
  ?fields=mentioned_media.media_id({media-id}){{fields}}
  &access_token={access-token}
```

### Query String Parameters

| Parameter | Value |
| --- | --- |
| `{access_token}`  <br>**Required**  <br>*String* | The app user's User Access Token. |
| `{fields}`  <br>*Comma-separated list* | A comma-separated list of IG Media [Fields](#fields) you want returned.  If omitted, default Fields will be returned. |
| `{media-id}`  <br>**Required**  <br>*String* | The ID of the IG Media in which the IG User has been @mentioned in a caption. The ID is included in the [Webhook notification](https://developers.facebook.com/documentation/instagram-platform/webhooks#reply-comment-mention) payload. |

### Fields

| Field | Description |
| --- | --- |
| `caption`  <br>*String* | The caption text. Captions that @mention an IG User will not include the `@` symbol unless the app user created the IG Media object upon which the caption was made. |
| `comments`  <br>*Object* | A list of IG Comments on the IG Media. If using Field Expansion to get the comment text, text that @mentions an IG User will not include the `@` symbol unless the app user created the IG Media object upon which the caption was made. |
| `comments_count`  <br>*String* | Number of IG Comments on the IG Media. |
| `id`  <br>**Default**  <br>*String* | ID of the IG Media. |
| `like_count`  <br>*String* | Count of likes on the media. Excludes likes on album child media and likes on promoted posts created from the media. Includes replies on comments.<br><br>* **v10.0 and older calls:** value will be `0` if the media owner has [hidden](https://www.facebook.com/help/instagram/113355287252104) like counts it.<br>* **v11.0+ calls:** field will be omitted if media owner has hidden like counts in it<br>Value will be `0` if the media owner has [hidden](https://www.facebook.com/help/instagram/113355287252104) like counts it. |
| `media_type`  <br>*String* | The IG Media's type: `CAROUSEL_ALBUM`, `IMAGE`, `STORY`, or `VIDEO`. |
| `media_url`  <br>*String* | URL of the published IG Media. |
| `owner`  <br>*String* | ID of the IG User who created the IG Media. Only returned if the app user created the IG Media object, otherwise the `username` field will be returned instead. |
| `timestamp`  <br>*String* | Creation date of IG Media formatted in ISO 8601. |
| `username`  <br>*String* | Username of the IG User who created the IG Media. |

### Sample Request

```curl
curl -X GET \
  'https://graph.facebook.com/v25.0/17841405309211844?fields=mentioned_media.media_id(17873440459141021){caption,media_type}&access_token=IGQVJ...'
```

### Sample Response

```json
{
  "mentioned_media": {
    "caption": "metricsaurus headquarters!",
    "media_type": "IMAGE",
    "id": "17873440459141021"
  },
  "id": "17841405309211844"
}
```

Note that in the sample above, the API has stripped out the leading `@` symbol from the original caption (@metricsaurus headquarters!) because the app user did not create the caption.

### Pagination

If you are using field expansion to access an edge that supports [cursor-based pagination](https://developers.facebook.com/docs/graph-api/using-graph-api#paging), the response will include `before` and `after` cursors if the response contains multiple pages of data. Unlike standard cursor-based pagination, however, the response will not include `previous` or `next` fields, so you will have to use the `before` and `after` cursors to construct `previous` and `next` query strings manually in order to page through the returned data set.

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

# IG User Media Publish



Publish an [IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) on an Instagram Business [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user). Refer to the [Content Publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing) guide for complete publishing steps.

## Creating

**`POST /&#123;ig-user-id&#125;/media_publish`**

Publish an [IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) object on an Instagram Business [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user).

### Limitations

* An Instagram professional account can only publish 50 posts within a 24 hour moving period
* If the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted Instagram Business account requires [Page Publishing Authorization](https://www.facebook.com/business/m/one-sheeters/page-publishing-authorization) (PPA), PPA must be completed or the request will fail.
* If the Page connected to the targeted Instagram Business account requires two-factor authentication, the Facebook User must also have performed two-factor authentication or the request will fail.

### Requirements

| Type | Description |
| --- | --- |
| [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) | [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| [Business Roles](https://www.facebook.com/business/help/442345745885606) | If publishing containers for [product tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging), the app user must have an admin role on the [Business Manager](https://business.facebook.com/) that owns the IG User&#039;s [Instagram Shop](https://help.instagram.com/1187859655048322). |
| [Instagram Shop](https://help.instagram.com/1187859655048322/) | If publishing containers for [product tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging), the IG User must have an approved [Instagram Shop](https://help.instagram.com/1187859655048322/) with a product catalog containing products. |
| [Permissions](https://developers.facebook.com/docs/apps/review/login-permissions) | [`instagram_basic`](https://developers.facebook.com/docs/facebook-login/permissions#reference-instagram_basic)  &lt;br&gt;[`instagram_content_publish`](https://developers.facebook.com/docs/permissions/reference/instagram_content_publish)  &lt;br&gt;&lt;br&gt;If the app user was granted a role on the Page via the Business Manager, you will also need one of:&lt;br&gt;&lt;br&gt;[`ads_management`](https://developers.facebook.com/docs/permissions/reference/ads_management)  &lt;br&gt;`ads_read`&lt;br&gt;&lt;br&gt;If publishing containers for [product tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging), you will also need:&lt;br&gt;&lt;br&gt;[`catalog_management`](https://developers.facebook.com/docs/permissions/reference/catalog_management)  &lt;br&gt;[`instagram_shopping_tag_products`](https://developers.facebook.com/docs/permissions/reference/instagram_shopping_tag_products) |
| [Tasks](https://developers.facebook.com/documentation/instagram-platform/overview#tasks) | The app user whose token is used in the request must be able to perform `MANAGE` or `CREATE_CONTENT` tasks on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted Instagram account. |

### Request Syntax

```http
POST https://graph.facebook.com/&#123;api-version&#125;/&#123;ig-user-id&#125;/media_publish
  ?creation_id=&#123;creation-id&#125;
  &amp;access_token=&#123;access-token&#125;
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&#123;api-version&#125;`  &lt;br&gt;*String* | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `&#123;ig-user-id&#125;`  &lt;br&gt;**Required**  &lt;br&gt;*String* | App user&#039;s app-scoped user ID. |

### Query String Parameters

| Key | Placeholder | Description |
| --- | --- | --- |
| `access_token`&lt;br&gt;&lt;br&gt;Required | `&#123;access-token&#125;` | The app user&#039;s [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |
| `creation_id`&lt;br&gt;&lt;br&gt;Required | `&#123;creation-id&#125;` | The ID of the [IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) to be published. |

### Sample Request

```
POST graph.facebook.com
  /17841405822304914/media_publish
    ?creation_id=17889455560051444
```

### Sample Response

```json
&#123;
  &quot;id&quot;: &quot;17920238422030506&quot;
&#125;
```

## Reading

This operation is not supported.

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

# IG User Media Publish



Publish an [IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) on an Instagram Business [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user). Refer to the [Content Publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing) guide for complete publishing steps.

## Creating

**`POST /{ig-user-id}/media_publish`**

Publish an [IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) object on an Instagram Business [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user).

### Limitations

* An Instagram professional account can only publish 50 posts within a 24 hour moving period
* If the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted Instagram Business account requires [Page Publishing Authorization](https://www.facebook.com/business/m/one-sheeters/page-publishing-authorization) (PPA), PPA must be completed or the request will fail.
* If the Page connected to the targeted Instagram Business account requires two-factor authentication, the Facebook User must also have performed two-factor authentication or the request will fail.

### Requirements

| Type | Description |
| --- | --- |
| [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) | [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| [Business Roles](https://www.facebook.com/business/help/442345745885606) | If publishing containers for [product tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging), the app user must have an admin role on the [Business Manager](https://business.facebook.com/) that owns the IG User's [Instagram Shop](https://help.instagram.com/1187859655048322). |
| [Instagram Shop](https://help.instagram.com/1187859655048322/) | If publishing containers for [product tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging), the IG User must have an approved [Instagram Shop](https://help.instagram.com/1187859655048322/) with a product catalog containing products. |
| [Permissions](https://developers.facebook.com/docs/apps/review/login-permissions) | [`instagram_basic`](https://developers.facebook.com/docs/facebook-login/permissions#reference-instagram_basic)  <br>[`instagram_content_publish`](https://developers.facebook.com/docs/permissions/reference/instagram_content_publish)  <br><br>If the app user was granted a role on the Page via the Business Manager, you will also need one of:<br><br>[`ads_management`](https://developers.facebook.com/docs/permissions/reference/ads_management)  <br>`ads_read`<br><br>If publishing containers for [product tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging), you will also need:<br><br>[`catalog_management`](https://developers.facebook.com/docs/permissions/reference/catalog_management)  <br>[`instagram_shopping_tag_products`](https://developers.facebook.com/docs/permissions/reference/instagram_shopping_tag_products) |
| [Tasks](https://developers.facebook.com/documentation/instagram-platform/overview#tasks) | The app user whose token is used in the request must be able to perform `MANAGE` or `CREATE_CONTENT` tasks on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted Instagram account. |

### Request Syntax

```http
POST https://graph.facebook.com/{api-version}/{ig-user-id}/media_publish
  ?creation_id={creation-id}
  &access_token={access-token}
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `{api-version}`  <br>*String* | API [version](https://developers.facebook.com/docs/graph-api/guides/versioning). |
| `{ig-user-id}`  <br>**Required**  <br>*String* | App user's app-scoped user ID. |

### Query String Parameters

| Key | Placeholder | Description |
| --- | --- | --- |
| `access_token`<br><br>Required | `{access-token}` | The app user's [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) access token. |
| `creation_id`<br><br>Required | `{creation-id}` | The ID of the [IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) to be published. |

### Sample Request

```
POST graph.facebook.com
  /17841405822304914/media_publish
    ?creation_id=17889455560051444
```

### Sample Response

```json
{
  "id": "17920238422030506"
}
```

## Reading

This operation is not supported.

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

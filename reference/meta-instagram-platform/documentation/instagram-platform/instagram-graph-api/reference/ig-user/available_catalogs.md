# IG User Available Catalogs



Represents a collection of product catalogs in an [IG User&#039;s](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) [Instagram Shop](https://help.instagram.com/1187859655048322/). See [Product Tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging) guide for complete usage details.

Available for the Instagram API with Facebook Login.

## Creating

This operation is not supported.

## Reading

**`GET /&lt;IG_USER_ID&gt;/available_catalogs`**

Get the product catalog in an [IG User&#039;s](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) [Instagram Shop](https://help.instagram.com/1187859655048322/).

### Limitations

* Instagram Creator accounts are not supported.
* Stories, Instagram TV, Reels, Live, and Mentions are not supported.
* Only returns data on a single catalog because Instagram Shops are limited to a single catalog.
* Collaborative catalogs (shopping partner or affiliate creator catalogs) are not supported.

### Requirements

| Type | Requirement |
| --- | --- |
| Access Tokens | User |
| [Business Roles](https://www.facebook.com/business/help/442345745885606) | The app user must have an admin role on the [Business Manager](https://business.facebook.com/) that owns the IG User&#039;s [Instagram Shop](https://help.instagram.com/1187859655048322). |
| [Instagram Shop](https://help.instagram.com/1187859655048322/) | The IG User must have an approved [Instagram Shop](https://help.instagram.com/1187859655048322/) with a product catalog containing products. |
| [Permissions](https://developers.facebook.com/docs/permissions) | `catalog_management`&lt;br&gt;`instagram_basic`&lt;br&gt;`instagram_shopping_tag_products`&lt;br&gt;&lt;br&gt;If the app user was granted a role via the Business Manager on the [Facebook Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need one of:&lt;br&gt;&lt;br&gt;`ads_management`&lt;br&gt;`ads_read` |

### Request Syntax

```
GET https://graph.facebook.com/&lt;API_VERSION&gt;/&lt;IG_USER_ID&gt;/available_catalogs
  ?fields=&lt;LIST_OF_FIELDS&gt;
  &amp;access_token=&lt;ACCESS_TOKEN&gt;
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&lt;API_VERSION&gt;` | API version |
| `&lt;IG_USER_ID&gt;` | **Required.** App user&#039;s app-scoped user ID. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `&lt;ACCESS_TOKEN&gt;` | **Required.** App user&#039;s User access token. |
| `fields` | `&lt;LIST_OF_FIELDS&gt;` | Comma-separated list of catalog [fields]( #response-contents) you want returned for each catalog in the result set. |

### Response

A JSON-formatted object containing the data you requested.

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;catalog_id&quot;: &quot;&#123;catalog-id&#125;&quot;,
      &quot;catalog_name&quot;: &quot;&#123;catalog-name&#125;&quot;,
      &quot;shop_name&quot;: &quot;&#123;shop-name&#125;&quot;,
      &quot;product_count&quot;: &#123;product-count&#125;
    &#125;
  ]
&#125;
```

#### Response Contents

| Property | Value |
| --- | --- |
| `catalog_id` | Catalog ID. |
| `catalog_name` | Catalog name. |
| `shop_name` | Shop name. |
| `product_count` | Number of products in catalog. Includes all products regardless of review status. |

### cURL Example

#### Request

```curl
curl -i -X GET \
 &quot;https://graph.facebook.com/v25.0/90010177253934/available_catalogs?access_token=EAAOc...&quot;
```

#### Response

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;catalog_id&quot;: &quot;960179311066902&quot;,
      &quot;catalog_name&quot;: &quot;Jay&#039;s Favorite Snacks&quot;,
      &quot;shop_name&quot;: &quot;Jay&#039;s Bespoke&quot;,
      &quot;product_count&quot;: 11
    &#125;
  ]
&#125;
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

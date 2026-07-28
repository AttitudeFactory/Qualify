# IG User Available Catalogs



Represents a collection of product catalogs in an [IG User's](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) [Instagram Shop](https://help.instagram.com/1187859655048322/). See [Product Tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging) guide for complete usage details.

Available for the Instagram API with Facebook Login.

## Creating

This operation is not supported.

## Reading

**`GET /<IG_USER_ID>/available_catalogs`**

Get the product catalog in an [IG User's](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) [Instagram Shop](https://help.instagram.com/1187859655048322/).

### Limitations

* Instagram Creator accounts are not supported.
* Stories, Instagram TV, Reels, Live, and Mentions are not supported.
* Only returns data on a single catalog because Instagram Shops are limited to a single catalog.
* Collaborative catalogs (shopping partner or affiliate creator catalogs) are not supported.

### Requirements

| Type | Requirement |
| --- | --- |
| Access Tokens | User |
| [Business Roles](https://www.facebook.com/business/help/442345745885606) | The app user must have an admin role on the [Business Manager](https://business.facebook.com/) that owns the IG User's [Instagram Shop](https://help.instagram.com/1187859655048322). |
| [Instagram Shop](https://help.instagram.com/1187859655048322/) | The IG User must have an approved [Instagram Shop](https://help.instagram.com/1187859655048322/) with a product catalog containing products. |
| [Permissions](https://developers.facebook.com/docs/permissions) | `catalog_management`<br>`instagram_basic`<br>`instagram_shopping_tag_products`<br><br>If the app user was granted a role via the Business Manager on the [Facebook Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need one of:<br><br>`ads_management`<br>`ads_read` |

### Request Syntax

```
GET https://graph.facebook.com/<API_VERSION>/<IG_USER_ID>/available_catalogs
  ?fields=<LIST_OF_FIELDS>
  &access_token=<ACCESS_TOKEN>
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `<API_VERSION>` | API version |
| `<IG_USER_ID>` | **Required.** App user's app-scoped user ID. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `<ACCESS_TOKEN>` | **Required.** App user's User access token. |
| `fields` | `<LIST_OF_FIELDS>` | Comma-separated list of catalog [fields]( #response-contents) you want returned for each catalog in the result set. |

### Response

A JSON-formatted object containing the data you requested.

```json
{
  "data": [
    {
      "catalog_id": "{catalog-id}",
      "catalog_name": "{catalog-name}",
      "shop_name": "{shop-name}",
      "product_count": {product-count}
    }
  ]
}
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
 "https://graph.facebook.com/v25.0/90010177253934/available_catalogs?access_token=EAAOc..."
```

#### Response

```json
{
  "data": [
    {
      "catalog_id": "960179311066902",
      "catalog_name": "Jay's Favorite Snacks",
      "shop_name": "Jay's Bespoke",
      "product_count": 11
    }
  ]
}
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

# IG User Catalog Product Search



Represents products and product variants that match a given search string in an [IG User's](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) [Instagram Shop](https://help.instagram.com/1187859655048322/) product catalog. See [Product Tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging) guide for complete usage details.

Available for Instagram Graph API only.

## Creating

This operation is not supported.

## Reading

**`GET /<IG_USER_ID>/catalog_product_search`**

Get a collection of products that match a given search string within the targeted [IG User's](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) [Instagram Shop](https://help.instagram.com/1187859655048322/) catalog.

### Limitations

* Instagram Creator accounts are not supported.
* Stories, Instagram TV, Reels, Live, and Mentions are not supported.
* Products with a `review_status` of `rejected` will be returned, however, IG Media cannot be tagged with rejected products.
* Although the API will not return an error when publishing a post tagged with an unapproved product, the tag will not appear on the published post until the product has been approved. Therefore, we recommend that you only allow your app users to publish posts with tags whose products have a `review_status` of `approved`. This field is returned for each product by default when you get an app user's eligible products.

### Requirements

| Type | Requirement |
| --- | --- |
| [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens) | [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| [Business Roles](https://www.facebook.com/business/help/442345745885606) | The app user must have an admin role on the [Business Manager](https://business.facebook.com/) that owns the IG User's [Instagram Shop](https://help.instagram.com/1187859655048322). |
| [Instagram Shop](https://help.instagram.com/1187859655048322/) | The IG User must have an approved [Instagram Shop](https://help.instagram.com/1187859655048322/) with a product catalog containing products. |
| [Permissions](https://developers.facebook.com/docs/permissions/reference) | [`catalog_management`](https://developers.facebook.com/docs/permissions/reference/catalog_management)  <br>[`instagram_basic`](https://developers.facebook.com/docs/permissions/reference/instagram_basic)  <br>[`instagram_shopping_tag_products`](https://developers.facebook.com/docs/permissions/reference/instagram_shopping_tag_products)  <br><br>If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need one of:<br><br>[`ads_management`](https://developers.facebook.com/docs/permissions/reference/ads_management)  <br>`ads_read` |

### Request Syntax

```
GET https://graph.facebook.com/<API_VERSION>/<IG_USER_ID>/catalog_product_search
  ?catalog_id=<CATALOG_ID>
  &q=<QUERY_STRING>
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
| `catalog_id` | `<CATALOG_ID>` | **Required.** ID of catalog to search. |
| `q` | `<QUERY_STRING>` | A string to search for in each product's name or SKU number (SKU numbers can be added in the **Content ID** column in the catalog management interface). If no string is specified, all tag-eligible products will be returned. |

### Response

A JSON-formatted object containing an array of tag-eligible products and their metadata. Supports [cursor-based pagination](https://developers.facebook.com/docs/graph-api/results#cursors).

```json
{
  "data": [
    {
      "product_id": {product-id},
      "merchant_id": {merchant-id},
      "product_name": "{product-name}",
      "image_url": "{image-url}",
      "retailer_id": "{retailer-id}",
      "review_status": "{review-status}",
      "is_checkout_flow": {is-checkout-flow}
    }
  ]
}
```

#### Response Contents

| Property | Value |
| --- | --- |
| `product_id ` | Product ID. |
| `merchant_id` | Merchant ID. |
| `product_name` | Product name. |
| `image_url` | Product image URL. |
| `retailer_id` | Retailer ID. |
| `review_status` | Review status. Values can be `approved`, `outdated`, `pending`, `rejected`. An approved product can appear in the app user's [Instagram Shop](https://help.instagram.com/1187859655048322/), but an approved status does not indicate product availability (e.g, the product could be out of stock). Only tags associated with products that have a `review_status` of `approved` can appear on published posts. |
| `is_checkout_flow` | If `true`, product can be purchased directly in the Instagram app. If `false`, product must be purchased in the app user's app/website. |
| `product_variants` | Product IDs (`product_id`) and variant names (`variant_name`) of [product variants](https://developers.facebook.com/documentation/ads-commerce/catalog/guides/product-variants). |

### cURL Example

#### Request

```curl
curl -i -X GET \
 "https://graph.facebook.com/v25.0/90010177253934/catalog_product_search?catalog_id=960179311066902&q=gummy&access_token=EAAOc"
```

#### Response

```json
{
  "data": [
    {
      "product_id": 3231775643511089,
      "merchant_id": 90010177253934,
      "product_name": "Gummy Wombats",
      "image_url": "https://scont...",
      "retailer_id": "oh59p9vzei",
      "review_status": "approved",
      "is_checkout_flow": true,
      "product_variants": [
            {
              "product_id": 5209223099160494
            },
            {
              "product_id": 7478222675582505,
              "variant_name": "Green Gummy Wombats"
            }
          ]
    }
  ]
}
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

# IG User Catalog Product Search



Represents products and product variants that match a given search string in an [IG User&#039;s](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) [Instagram Shop](https://help.instagram.com/1187859655048322/) product catalog. See [Product Tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging) guide for complete usage details.

Available for Instagram Graph API only.

## Creating

This operation is not supported.

## Reading

**`GET /&lt;IG_USER_ID&gt;/catalog_product_search`**

Get a collection of products that match a given search string within the targeted [IG User&#039;s](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) [Instagram Shop](https://help.instagram.com/1187859655048322/) catalog.

### Limitations

* Instagram Creator accounts are not supported.
* Stories, Instagram TV, Reels, Live, and Mentions are not supported.
* Products with a `review_status` of `rejected` will be returned, however, IG Media cannot be tagged with rejected products.
* Although the API will not return an error when publishing a post tagged with an unapproved product, the tag will not appear on the published post until the product has been approved. Therefore, we recommend that you only allow your app users to publish posts with tags whose products have a `review_status` of `approved`. This field is returned for each product by default when you get an app user&#039;s eligible products.

### Requirements

| Type | Requirement |
| --- | --- |
| [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens) | [User](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| [Business Roles](https://www.facebook.com/business/help/442345745885606) | The app user must have an admin role on the [Business Manager](https://business.facebook.com/) that owns the IG User&#039;s [Instagram Shop](https://help.instagram.com/1187859655048322). |
| [Instagram Shop](https://help.instagram.com/1187859655048322/) | The IG User must have an approved [Instagram Shop](https://help.instagram.com/1187859655048322/) with a product catalog containing products. |
| [Permissions](https://developers.facebook.com/docs/permissions/reference) | [`catalog_management`](https://developers.facebook.com/docs/permissions/reference/catalog_management)  &lt;br&gt;[`instagram_basic`](https://developers.facebook.com/docs/permissions/reference/instagram_basic)  &lt;br&gt;[`instagram_shopping_tag_products`](https://developers.facebook.com/docs/permissions/reference/instagram_shopping_tag_products)  &lt;br&gt;&lt;br&gt;If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need one of:&lt;br&gt;&lt;br&gt;[`ads_management`](https://developers.facebook.com/docs/permissions/reference/ads_management)  &lt;br&gt;`ads_read` |

### Request Syntax

```
GET https://graph.facebook.com/&lt;API_VERSION&gt;/&lt;IG_USER_ID&gt;/catalog_product_search
  ?catalog_id=&lt;CATALOG_ID&gt;
  &amp;q=&lt;QUERY_STRING&gt;
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
| `catalog_id` | `&lt;CATALOG_ID&gt;` | **Required.** ID of catalog to search. |
| `q` | `&lt;QUERY_STRING&gt;` | A string to search for in each product&#039;s name or SKU number (SKU numbers can be added in the **Content ID** column in the catalog management interface). If no string is specified, all tag-eligible products will be returned. |

### Response

A JSON-formatted object containing an array of tag-eligible products and their metadata. Supports [cursor-based pagination](https://developers.facebook.com/docs/graph-api/results#cursors).

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;product_id&quot;: &#123;product-id&#125;,
      &quot;merchant_id&quot;: &#123;merchant-id&#125;,
      &quot;product_name&quot;: &quot;&#123;product-name&#125;&quot;,
      &quot;image_url&quot;: &quot;&#123;image-url&#125;&quot;,
      &quot;retailer_id&quot;: &quot;&#123;retailer-id&#125;&quot;,
      &quot;review_status&quot;: &quot;&#123;review-status&#125;&quot;,
      &quot;is_checkout_flow&quot;: &#123;is-checkout-flow&#125;
    &#125;
  ]
&#125;
```

#### Response Contents

| Property | Value |
| --- | --- |
| `product_id ` | Product ID. |
| `merchant_id` | Merchant ID. |
| `product_name` | Product name. |
| `image_url` | Product image URL. |
| `retailer_id` | Retailer ID. |
| `review_status` | Review status. Values can be `approved`, `outdated`, `pending`, `rejected`. An approved product can appear in the app user&#039;s [Instagram Shop](https://help.instagram.com/1187859655048322/), but an approved status does not indicate product availability (e.g, the product could be out of stock). Only tags associated with products that have a `review_status` of `approved` can appear on published posts. |
| `is_checkout_flow` | If `true`, product can be purchased directly in the Instagram app. If `false`, product must be purchased in the app user&#039;s app/website. |
| `product_variants` | Product IDs (`product_id`) and variant names (`variant_name`) of [product variants](https://developers.facebook.com/documentation/ads-commerce/catalog/guides/product-variants). |

### cURL Example

#### Request

```curl
curl -i -X GET \
 &quot;https://graph.facebook.com/v25.0/90010177253934/catalog_product_search?catalog_id=960179311066902&amp;q=gummy&amp;access_token=EAAOc&quot;
```

#### Response

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;product_id&quot;: 3231775643511089,
      &quot;merchant_id&quot;: 90010177253934,
      &quot;product_name&quot;: &quot;Gummy Wombats&quot;,
      &quot;image_url&quot;: &quot;https://scont...&quot;,
      &quot;retailer_id&quot;: &quot;oh59p9vzei&quot;,
      &quot;review_status&quot;: &quot;approved&quot;,
      &quot;is_checkout_flow&quot;: true,
      &quot;product_variants&quot;: [
            &#123;
              &quot;product_id&quot;: 5209223099160494
            &#125;,
            &#123;
              &quot;product_id&quot;: 7478222675582505,
              &quot;variant_name&quot;: &quot;Green Gummy Wombats&quot;
            &#125;
          ]
    &#125;
  ]
&#125;
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

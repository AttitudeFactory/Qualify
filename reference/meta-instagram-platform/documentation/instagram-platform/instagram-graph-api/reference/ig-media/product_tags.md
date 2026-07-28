# IG Media Product Tags



Represents product tags on an [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media). See [Product Tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging) guide for complete usage details.

Available for the Instagram API with Facebook Login.

## Creating

**`POST /&lt;IG_MEDIA_ID&gt;/product_tags`**

Create or update product tags on an existing [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media).

### Limitations

* Instagram Creator accounts are not supported.
* Stories, Instagram TV, Live, and Mentions are not supported.
* Tagging media is additive until the tag limit has been reached (20 for feed posts, 30 for Reels). If the targeted media has already been tagged by a product in the request, the old tag&#039;s `x` and `y` values will be updated with their new values (a new tag will not be added).

### Requirements

| Type | Requirement |
| --- | --- |
| Access Tokens | User |
| [Business Roles](https://www.facebook.com/business/help/442345745885606) | The app user must have an admin role on the [Business Manager](https://business.facebook.com/) that owns the IG User&#039;s [Instagram Shop](https://help.instagram.com/1187859655048322). |
| [Instagram Shop](https://help.instagram.com/1187859655048322/) | The IG User that owns the IG Media must have an approved [Instagram Shop](https://help.instagram.com/1187859655048322/) with a product catalog containing products. |
| [Permissions](https://developers.facebook.com/docs/permissions) | * `ad_reads`&lt;br&gt;* [`catalog_management`&lt;br&gt;* `instagram_basic`&lt;br&gt;* `instagram_shopping_tag_products`&lt;br&gt;&lt;br&gt;If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need:&lt;br&gt;&lt;br&gt;`ads_management` |

### Request Syntax

```
POST https://graph.facebook.com/&lt;API_VERSION&gt;/&lt;IG_MEDIA_ID&gt;/product_tags
  ?updated_tags=&lt;LIST_OF_UPDATED_TAGS&gt;
  &amp;access_token=&lt;ACCESS_TOKEN&gt;
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&lt;API_VERSION&gt;` | API version |
| `&lt;IG_MEDIA_ID&gt;` | **Required.** IG Media ID. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `&lt;ACCESS_TOKEN&gt;` | **Required.** App user&#039;s User access token. |
| `updated_tags` | `&lt;LIST_OF_UPDATED_TAGS&gt;` | **Required. Applies only to images and videos**. An array of objects specifying which product tags to tag the image or video with (maximum of 20 for Feed posts, maximum of 30 for Reels; tags and product IDs must be unique). Each object should have the following information:&lt;br&gt;&lt;br&gt;- `product_id` — **Required.** Product ID.&lt;br&gt;- `x` — **Images only.** An optional float that indicates percentage distance from left edge of the published media image. Value must be within `0.0`–`1.0` range.&lt;br&gt;- `y` — **Images only.** An optional float that indicates percentage distance from top edge of the published media image. Value must be within `0.0`–`1.0` range.&lt;br&gt;&lt;br&gt;For example:&lt;br&gt;&lt;br&gt;`[&#123;product_id:&#039;3231775643511089&#039;,x:0.5,y:0.8&#125;]` |

### Response

An object indicating success or failure.

```json
&#123;
  &quot;success&quot;: &#123;success&#125;
&#125;
```

#### Response Contents

| Property | Value |
| --- | --- |
| `success` | Returns `true` if able to update the IG Media&#039;s product tags, otherwise returns `false`. |

### cURL Example

#### Request

```curl
curl -i -X POST \
 &quot;https://graph.facebook.com/v25.0/90010778325754/product_tags?updated_tags=%5B%0A%20%20%7B%0A%20%20%20%20product_id%3A&#039;3859448974125379&#039;%2C%0A%20%20%20%20x%3A%200.5%2C%0A%20%20%20%20y%3A%200.8%0A%20%20%7D%0A%5D&amp;access_token=EAAOc...&quot;
```

For reference, here is the HTML-decoded POST payload string:

```html
https://graph.facebook.com/v25.0/90010778325754/product_tags?updated_tags=[
  &#123;
    product_id:&#039;3859448974125379&#039;,
    x: 0.5,
    y: 0.8
  &#125;
]&amp;access_token=EAAOc...
```

#### Response

```json
&#123;
  &quot;success&quot;: true
&#125;
```

## Reading

**`GET /&lt;IG_MEDIA_ID&gt;/product_tags`**

Get a collection of product tags on an [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media). See the [Product Tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging) guide for complete product tagging steps.

### Limitations

* Instagram Creator accounts are not supported.
* Stories, Instagram TV, Reels, Live, and Mentions are not supported.

### Requirements

| Type | Requirement |
| --- | --- |
| Access Tokens | User |
| [Business Roles](https://www.facebook.com/business/help/442345745885606) | The app user must have an admin role on the [Business Manager](https://business.facebook.com/) that owns the IG User&#039;s [Instagram Shop](https://help.instagram.com/1187859655048322). |
| [Instagram Shop](https://help.instagram.com/1187859655048322/) | The IG User that owns the IG Media must have an approved [Instagram Shop](https://help.instagram.com/1187859655048322/) with a product catalog containing products. |
| [Permissions](https://developers.facebook.com/docs/permissions) | * `ad_reads`&lt;br&gt;* `catalog_management`&lt;br&gt;* `instagram_basic`&lt;br&gt;* `instagram_shopping_tag_products`&lt;br&gt;&lt;br&gt;If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need:&lt;br&gt;&lt;br&gt;* `ads_management` |

### Request Syntax

```
GET https://graph.facebook.com/&lt;API_VERSION&gt;/&lt;IG_MEDIA_ID&gt;/product_tags
  ?access_token=&lt;ACCESS_TOKEN&gt;
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&lt;API_VERSION&gt;` | API version |
| `&lt;IG_MEDIA_ID&gt;` | **Required.** IG Media ID. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `&lt;ACCESS_TOKEN&gt;` | **Required.** App user&#039;s User access token. |

### Response

A JSON-formatted object containing an array of product tags on an IG Media. Responses can include the following product tag fields:

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;product_id&quot;: &#123;product-id&#125;,
      &quot;merchant_id&quot;: &#123;merchant-id&#125;,
      &quot;name&quot;: &quot;&#123;name&#125;&quot;,
      &quot;price_string&quot;: &quot;&#123;price-string&#125;&quot;,
      &quot;image_url&quot;: &quot;&#123;image-url&#125;&quot;,
      &quot;review_status&quot;: &quot;&#123;review-status&#125;&quot;,
      &quot;is_checkout&quot;: &#123;is-checkout&#125;,
      &quot;stripped_price_string&quot;: &quot;&#123;stripped-price-string&#125;&quot;,
      &quot;string_sale_price_string&quot;: &quot;&#123;string-sale-price-string&#125;&quot;,
      &quot;x&quot;: &#123;x&#125;,
      &quot;y&quot;: &#123;y&#125;
    &#125;
  ]
&#125;
```

#### Response Contents

| Property | Value |
| --- | --- |
| `product_id` | Product ID. |
| `merchant_id` | Merchant ID. |
| `name` | Product name. |
| `price_string` | Price string. |
| `image_url` | Product image URL. |
| `review_status` | Product review status. Values can be:&lt;br&gt;&lt;br&gt;* `approved` — Product is approved.&lt;br&gt;* `rejected` — Product was rejected&lt;br&gt;* `pending` — Still undergoing review.&lt;br&gt;* `outdated` — Product was approved but has been edited and requires reapproval.&lt;br&gt;* `&quot;&quot;` — No review status. |
| `is_checkout` | If `true`, product can be purchased directly through the Instagram app. If `false`, product can only be purchased on the merchant&#039;s website. |
| `stripped_price_string` | Product short price string (price displayed in constrained spaces, such as `$100` instead of `100 USD`). |
| `string_sale_price_string` | Product sale price. |
| `x` | A float that indicates percentage distance from left edge of media image. Value within `0.0`–`1.0` range. |
| `y` | A float that indicates percentage distance from top edge of media image. Value within `0.0`–`1.0` range. |

### cURL Example

#### Request

```curl
curl -i -X GET \
 &quot;https://graph.facebook.com/v25.0/90010778325754/product_tags?access_token=EAAOc...&quot;
```

#### Response

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;product_id&quot;: 3231775643511089,
      &quot;merchant_id&quot;: 90010177253934,
      &quot;name&quot;: &quot;Gummy Bears&quot;,
      &quot;price_string&quot;: &quot;$3.50&quot;,
      &quot;image_url&quot;: &quot;https://scont...&quot;,
      &quot;review_status&quot;: &quot;approved&quot;,
      &quot;is_checkout&quot;: true,
      &quot;stripped_price_string&quot;: &quot;$3.50&quot;,
      &quot;stripped_sale_price_string&quot;: &quot;$3&quot;,
      &quot;x&quot;: 0.5,
      &quot;y&quot;: 0.80000001192093
    &#125;
  ]
&#125;
```

## Updating

See [Creating](#creating).

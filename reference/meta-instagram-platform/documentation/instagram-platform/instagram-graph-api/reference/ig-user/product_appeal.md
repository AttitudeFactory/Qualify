# IG User Product Appeal



Represents a rejected product&#039;s appeal status. See [Product Tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging) guide for complete usage details.

## Creating

**`POST /&#123;ig-user-id&#125;/product_appeal`**

Appeal a rejected product.

### Limitations

* Instagram Creator accounts are not supported.
* Stories, Instagram TV, Reels, Live, and Mentions are not supported.

### Requirements

| Type | Requirement |
| --- | --- |
| Access Tokens | User |
| [Business Roles](https://www.facebook.com/business/help/442345745885606) | The app user must have an admin role on the [Business Manager](https://business.facebook.com/) that owns the IG User&#039;s [Instagram Shop](https://help.instagram.com/1187859655048322). |
| [Instagram Shop](https://help.instagram.com/1187859655048322/) | The IG User must have an approved [Instagram Shop](https://help.instagram.com/1187859655048322/) with a product catalog containing products. |
| [Permissions](https://developers.facebook.com/docs/permissions) | `catalog_management`&lt;br&gt;`instagram_basic`&lt;br&gt;`instagram_shopping_tag_products`&lt;br&gt;&lt;br&gt;If the app user was granted a role via the Business Manager on the Facebook Page connected to the targeted IG User, you will also need one of:&lt;br&gt;&lt;br&gt;`ads_management`&lt;br&gt;`ads_read` |

### Request Syntax

```
POST https://graph.facebook.com/&#123;api-version&#125;/&#123;ig-user-id&#125;/product_appeal
  ?appeal_reason=&#123;appeal-reason&#125;
  &amp;product_id=&#123;product-id&#125;
  &amp;access_token=&#123;access-token&#125;
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&#123;api-version&#125;` | API version |
| `&#123;ig-user-id&#125;` | **Required.** App user&#039;s app-scoped user ID. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `&#123;access-token&#125;` | **Required.** App user&#039;s User access token. |
| `appeal_reason` | `&#123;appeal-reason&#125;` | **Required.** Explanation of why the product should be approved. |
| `product_id` | `&#123;product-id&#125;` | **Required.** Product ID. |

### Response

An object indicating success or failure. Response does not indicate appeal outcome.

```json
&#123;
  &quot;success&quot;: &#123;success&#125;
&#125;
```

#### Response Contents

| Property | Value |
| --- | --- |
| `success` | Indicates if API accepted request (`true`) or did not accept request (`false`). Response does not indicate appeal outcome. |

### cURL Example

#### Request

```curl
curl -i -X POST \
 &quot;https://graph.facebook.com/v25.0/90010177253934/product_appeal?appeal_reason=product%20is%20a%20toy%20and%20not%20a%20real%20weapon&amp;product_id=4382881195057752&amp;access_token=EAAOc...&quot;
```

#### Response

```json
&#123;
  &quot;success&quot;: true
&#125;
```

## Reading

**`GET /&#123;ig-user-id&#125;/product_appeal`**

Get appeal status of a rejected product.

### Limitations

* Instagram Creator accounts are not supported.
* Stories, Instagram TV, Reels, Live, and Mentions are not supported.

### Requirements

| Type | Requirement |
| --- | --- |
| Access tokens | User |
| [Business Roles](https://www.facebook.com/business/help/442345745885606) | The app user must have an admin role on the [Business Manager](https://business.facebook.com/) that owns the IG User&#039;s [Instagram Shop](https://help.instagram.com/1187859655048322). |
| [Instagram Shop](https://help.instagram.com/1187859655048322/) | The IG User must have an approved [Instagram Shop](https://help.instagram.com/1187859655048322/) with a product catalog containing products. |
| [Permissions](https://developers.facebook.com/docs/permissions) | `catalog_management`&lt;br&gt;`instagram_basic`&lt;br&gt;`instagram_shopping_tag_products`&lt;br&gt;&lt;br&gt;If the app user was granted a role via the Business Manager on the Facebook Page connected to the targeted IG User, you will also need one of:&lt;br&gt;&lt;br&gt;* `ads_management`&lt;br&gt;* `ads_read` |

### Request Syntax

```
GET https://graph.facebook.com/&#123;api-version&#125;/&#123;ig-user-id&#125;/product_appeal
  ?product_id=&#123;product-id&#125;
  &amp;access_token=&#123;access-token&#125;
```

### Path Parameters

| Placeholder | Value |
| --- | --- |
| `&#123;api-version&#125;` | API version |
| `&#123;ig-user-id&#125;` | **Required.** App user&#039;s app-scoped user ID. |

### Query String Parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `&#123;access-token&#125;` | **Required.** App user&#039;s User access token. |
| `product_id` | `&#123;product-id&#125;` | **Required.** Product ID. |

### Response

A JSON-formatted object containing an array of appeal status metadata.

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;eligible_for_appeal&quot;: &#123;eligible-for-appeal&#125;,
      &quot;product_id&quot;: &#123;product-id&#125;,
      &quot;review_status&quot;: &quot;&#123;review-status&#125;&quot;
    &#125;
  ]
&#125;
```

#### Response Contents

| Property | Value |
| --- | --- |
| `eligible_for_appeal` | Indicates if decision can be appealed (yes if `true`, no if `false`). |
| `product_id` | Product ID. |
| `review_status` | Review status. Value can be:&lt;br&gt;&lt;br&gt;* `approved` — Product is approved.&lt;br&gt;* `rejected` — Product was rejected&lt;br&gt;* `pending` — Still undergoing review.&lt;br&gt;* `outdated` — Product was approved but has been edited and requires reapproval.&lt;br&gt;* `&quot;&quot;` — No review status.&lt;br&gt;* `no_review` — No review status. |

### cURL Example

#### Request

```curl
curl -i -X GET \
 &quot;https://graph.facebook.com/v25.0/90010177253934/product_appeal?product_id=4029274203846188&amp;access_token=EAAOc...&quot;
```

#### Response

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;product_id&quot;: 4029274203846188,
      &quot;review_status&quot;: &quot;approved&quot;,
      &quot;eligible_for_appeal&quot;: false
    &#125;
  ]
&#125;
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

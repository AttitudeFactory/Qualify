Graph API Version

[v25.0](#)

# Canvas Product Set

## Reading

A product set inside the canvas

### Flagged custom conversions

If a custom conversion is flagged, the `is_unavailable` field will be set to `true`.

```
{
  "is_unavailable": true,
  "id": "30141209892193360"
}
```

#### To resolve flagged custom conversions

If any of your custom conversions are flagged for suggesting information that is not allowed under our terms, you may want to consider the following options:

To resolve a flagged custom conversion in a new campaign creation:

* **Create new custom conversion**: Use a new custom conversion and make sure that it does not include information that is not allowed under our terms.
* **Choose a different custom conversion**: Select a different existing custom conversion and make sure it does not include information that is not allowed under our terms.

To resolve a flagged custom conversion in an existing campaign:

* **Duplicate your campaign and select an existing custom conversion**: If you have a running campaign that is flagged due to a flagged custom conversion, consider duplicating the campaign and selecting a different custom conversion that is not flagged before publishing the new duplicated campaign. **Note:** Once the campaign is published, you cannot remove or select a different custom conversion.

#### Request a review

If you believe your custom conversion has been flagged in error and doesn't include non-permitted information, you can request a review via Ads Manager under the campaigns table, or in Events Manager under the custom conversions page.

* `storefront_settings`

### Example

### Parameters

This endpoint doesn't have any parameters.

### Fields

| Field | Description |
| --- | --- |
| `id`  numeric string | The id of the element |
| `bottom_padding`  numeric string | The padding below the element |
| `element_group_key`  string | The element group key to bundle multiple elements in editing |
| `element_type`  enum | The type of the element  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `image_overlay_spec`  [AdCreativeLinkDataImageOverlaySpec](https://developers.facebook.com/docs/marketing-api/reference/ad-creative-link-data-image-overlay-spec/) | How to render overlays over a product item |
| `item_description`  string | A token to represent which field from the product to show in the product description |
| `item_headline`  string | A token to represent which field from the product to show in the product headline |
| `max_products`  unsigned int32 | Maximum number of products to show |
| `name`  string | The name of the element  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `product_set_id`  numeric string | The product set id which contains a subset of products within a product catalog |
| `retailer_item_ids`  list<string> | An array of items that should be shown first in the product set element. If this is not set then products will be dynamically chosen |
| `show_in_feed`  bool | A flag that products should be shown in feed unit |
| `top_padding`  numeric string | The padding above the element |

### Error Codes

| Error | Description |
| --- | --- |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

### Create a Collection Ads Product Set

To create a product set used in Collection ads from a set of products in Dynamic Ads:

`curl
-F 'canvas_product_set={
"bottom_padding": 8,
"max_items": 50,
"name": "Collection Product Set Name",
"product_set_id": "PRODUCT_SET_ID",
"show_in_feed": true,
"item_headline": "See more at {{product.brand | titleize}}",
"item_description": "{{product.price}}",
"retailer_item_ids": [
"RETAILER_ID_1",
"RETAILER_ID_2",
"RETAILER_ID_3",
"RETAILER_ID_4",
],
"top_padding": 24
}' \
-F 'access_token=ACCESS_TOKEN' \
https://graph.facebook.com/VERSION/PAGE_ID/canvas_elements`

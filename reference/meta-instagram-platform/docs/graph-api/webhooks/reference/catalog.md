Graph API Version

[v25.0](#)

# Catalog (`catalog`)

Category of updates relating to product catalog changes and events.

## `items_batch`

CatalogItemsBatchField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `catalog_id`  numeric string | catalog\_id |
| `handle`  string | The handle returned here can be used to check the status of the submitted request via the [/check\_batch\_request\_status](https://developers.facebook.com/docs/marketing-api/reference/product-catalog/check_batch_request_status/) API endpoint. |
| `status`  string | Status of a batch request. Possible values are:  Finished - The action was completed successfully; individual requests with errors were not saved. |

## `product_feed`

CatalogProductFeedField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `catalog_id`  numeric string | catalog\_id |
| `product_feed_id`  numeric string | product\_feed\_id |
| `status`  string | Status of a Product Feed. Possible values are:  Finished - The action was completed successfully |

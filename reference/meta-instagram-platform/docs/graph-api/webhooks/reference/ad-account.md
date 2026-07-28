Graph API Version

[v25.0](#)

# Ad Account (`ad_account`)

List of Ad account fields you can subscribe to.

## `ads_async_creation_request`

AdAccountAdsAsyncCreationRequestField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `status`  enum | status |
| `result`  object | result |
| `result_id`  numeric string | result\_id |
| `error_code`  unsigned int32 | error\_code |
| `error_message`  string | error\_message |

## `creative_fatigue`

AdAccountCreativeFatigueField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `ad_account_id`  numeric string | ad\_account\_id |
| `adgroup_id`  numeric string | adgroup\_id |
| `creative_fatigue_level`  string | creative\_fatigue\_level |
| `creative_fatigue_message`  string | creative\_fatigue\_message |

## `ad_recommendations`

AdAccountGuidanceField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `ad_account_id`  numeric string | ad\_account\_id |
| `ad_object_ids`  list<numeric string> | ad\_object\_ids |
| `recommendation_type`  enum | recommendation\_type |
| `recommendation_signature`  string | recommendation\_signature |
| `recommendation_message`  string | recommendation\_message |
| `recommendation_stage`  string | recommendation stage |
| `recommendation_hash`  string | recommendation hash |

## `in_process_ad_objects`

AdAccountInProcessAdObjectsField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Data of the ad object exit in\_process status |
| `id`  numeric string | id of the ad object |
| `level`  string | Level of the ad object, including 'CREATIVE', 'AD', 'AD\_SET', 'CAMPAIGN'. |
| `status_name`  string | Status of current ad object transition to |

## `product_set_issue`

AdAccountProductSetIssueField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Product Set Issue Details |
| `ad_account_id`  numeric string | ID of [Ad Account](https://developers.facebook.com/docs/marketing-api/reference/ad-account) |
| `product_set_id`  numeric string | ID of [Product Set](https://developers.facebook.com/docs/marketing-api/reference/product-catalog/product_sets/) |
| `type`  enum | An enum of the product set issue type |
| `description`  string | Detailed explanation of the specific issue related to the product set. |
| `recommended_action`  string | Suggested actions to resolve the issue described. |

## `with_issues_ad_objects`

AdAccountWithIssuesAdObjectsField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Data of the ad object set to WITH\_ISSUES |
| `id`  numeric string | ID of the ad object |
| `level`  string | Level of the ad object, including 'AD', 'AD\_SET', 'CAMPAIGN'. |
| `error_code`  numeric string | Error code of the issue |
| `error_summary`  string | Error summary of the issue |
| `error_message`  string | Error message of the issue |

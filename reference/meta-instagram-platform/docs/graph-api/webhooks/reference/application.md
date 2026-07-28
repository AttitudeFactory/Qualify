Graph API Version

[v25.0](#)

# Application (`application`)

Category of updates that are sent to a specific app

## `ad_account`

ApplicationAdAccountField, which is used to get status of AdAccount from Webhooks.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Result values |
| `id`  string | ID of the AdAccount |
| `account_status`  unsigned int32 | Account Status of AdAccount |
| `disable_reason`  unsigned int32 | Disabled reason of AdAccount |
| `business`  string | ID of the Business |

## `ads_rules_engine`

The ads\_rules\_engine field of the Webhooks application topic.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Result values |
| `rule_id`  id | ID of the rule associated with the ad object |
| `account_id`  id | ID of the ad account that owns the rule |
| `object_id`  id | ID of the ad object that passed rule evaluation |
| `object_type`  enum {CAMPAIGN, ADSET, AD} | The type of the ad object |
| `trigger_type`  enum {METADATA\_CREATION, METADATA\_UPDATE, STATS\_MILESTONE, STATS\_CHANGE, DELIVERY\_INSIGHTS\_CHANGE} | The type of the trigger |
| `trigger_field`  string | Field that passed rule evaluation |
| `current_value`  string | Current value of the trigger field |

## `async_requests`

The async\_requests field of the Webhooks application topic

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | The result values. |
| `category`  string | Category. |
| `verb`  enum {complete, fail} | Status of the async job. |
| `report_id`  id | Report run id. |

## `dev_alerts`

ApplicationDevAlertsField

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | value |
| `notification_id`  numeric string | notification\_id |
| `date`  datetime | date |
| `header`  string | header |
| `subtitle`  string | subtitle |

## `group_install`

The group\_install field for the Webhooks group topic

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | The contents of the update |
| `group_id`  numeric string | Group ID on which application was installed or uninstalled |
| `update_time`  datetime | The time of update |
| `verb`  enum {add, block, edit, edited, delete, follow, hide, mute, remove, unblock, unhide, update} | The type of action taken |
| `actor_id`  numeric string | Admin who installed or uninstalled the application |

## `oe_reseller_onboarding_request_created`

The node for the webhook called during oe reseller create.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | The data storing the id. |
| `id`  numeric string | The associated oe request id, that can be used to query more information |

## `plugin_comment`

The plugin\_comment field of the Webhooks application topic

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  [Comment](/docs/graph-api/reference/comment/) | The result value. |
| `id`  token with structure: Comment ID | The comment ID |
| `from`  User|Page | The profile that made this comment |
| `message`  string | The comment text |
| `created_time`  datetime | The time this comment was made |

## `plugin_comment_reply`

The plugin\_comment\_reply field of the Webhooks application topic

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  [Comment](/docs/graph-api/reference/comment/) | The result value. |
| `id`  token with structure: Comment ID | The comment ID |
| `from`  User|Page | The profile that made this comment |
| `message`  string | The comment text |
| `created_time`  datetime | The time this comment was made |
| `parent`  [Comment](/docs/graph-api/reference/comment/) | For comment replies, the comment this is a reply to |

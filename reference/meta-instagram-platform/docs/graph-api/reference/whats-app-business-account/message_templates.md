Graph API Version

[v25.0](#)

# Whats App Business Account Message Templates

Represents a collection of templates on a [WhatsApp Business Account](/docs/graph-api/reference/whats-app-business-account/). See [Templates](/docs/whatsapp/business-management-api/message-templates).

## Reading

Get a list of templates on a WhatsApp Business Account.

### Requirements

Type | Description || Access Tokens | [User](/docs/whatsapp/business-management-api/get-started#user-access-tokens), [System User](/docs/whatsapp/access-tokens#system-user-access-tokens), or [Business Integration System User](/docs/whatsapp/access-tokens#business-integration-system-user-access-tokens) |
| Permissions | [whatsapp\_business\_management](/docs/permissions#w) |

### Request Syntax

```
GET /<WHATSAPP_BUSINESS_ACCOUNT_ID>/message_templates
  ?category=<CATEGORY>,
  &content=<CONTENT>,
  &language=<LANGUAGE>,
  &name=<NAME>,
  &name_or_content=<NAME_OR_CONTENT>,
  &quality_score=<QUALITY_SCORE>,
  &status=<STATUS>
```

### Path Parameters

Placeholder | Value || `<WHATSAPP_BUSINESS_ACCOUNT_ID>` | WhatsApp Business Account ID. |

### Response

A list of [WhatsApp Message Template](/docs/graph-api/reference/whats-app-business-hsm/) nodes.

### Sample Request

```
curl 'https://graph.facebook.com/v16.0/102290129340398/message_templates?category=utility' \
-H 'Authorization: Bearer EAAJB...'
```

### Sample Response

```
{
  "data": [
    {
      "name": "order_delivery_update",
      "components": [
        {
          "type": "HEADER",
          "format": "LOCATION"
        },
        {
          "type": "BODY",
          "text": "Good news {{1}}! Your order #{{2}} is on its way to the location above. Thank you for your order!",
          "example": {
            "body_text": [
              [
                "Mark",
                "566701"
              ]
            ]
          }
        },
        {
          "type": "FOOTER",
          "text": "To stop receiving delivery updates, tap the button below."
        },
        {
          "type": "BUTTONS",
          "buttons": [
            {
              "type": "QUICK_REPLY",
              "text": "Stop Delivery Updates"
            }
          ]
        }
      ],
      "language": "en_US",
      "status": "APPROVED",
      "category": "UTILITY",
      "id": "1667192013751005"
    },
    ...
  ],
  "paging": {
    "cursors": {
      "before": "MAZDZD",
      "after": "MjQZD"
    }
  }
}
```

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `category`  array<enum {ACCOUNT\_UPDATE, PAYMENT\_UPDATE, PERSONAL\_FINANCE\_UPDATE, SHIPPING\_UPDATE, RESERVATION\_UPDATE, ISSUE\_RESOLUTION, APPOINTMENT\_UPDATE, TRANSPORTATION\_UPDATE, TICKET\_UPDATE, ALERT\_UPDATE, AUTO\_REPLY, TRANSACTIONAL, OTP, UTILITY, MARKETING, AUTHENTICATION, FREE\_SERVICE}> | The category for a template |
| `content`  string | The content for a template |
| `language`  array<string> | A list of supported languages that are available for each template |
| `name`  string | The name for a message template |
| `name_or_content`  string | Returns a list of message templates where the value for `name` or `content` match this value |
| `quality_score`  array<enum {GREEN, YELLOW, RED, UNKNOWN}> | The quality score for a template |
| `since`  datetime/timestamp | Query param to fetch templates based on last\_updated\_time since a given unix timestamp |
| `status`  array<enum {APPROVED, IN\_APPEAL, PENDING, REJECTED, PENDING\_DELETION, DELETED, DISABLED, PAUSED, LIMIT\_EXCEEDED, ARCHIVED}> | The review status for a template |
| `until`  datetime/timestamp | Query param to fetch templates based on last\_updated\_time until a given unix timestamp |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {},
    "summary": {}
}
```

#### `data`

A list of [WhatsAppMessageTemplate](/docs/graph-api/reference/whats-app-business-hsm/) nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

#### `summary`

Aggregated information about the edge, such as counts. Specify the fields to fetch in the summary param (like `summary=total_count`).

| Field | Description |
| --- | --- |
| `total_count`  unsigned int32 | The total number of message templates that belong to a WhatsApp Business Account |
| `message_template_count`  int32 | The current number of message templates that belong to the WhatsApp Business Account |
| `message_template_limit`  int32 | The maximum number of message templates that can belong to a WhatsApp Business Account |
| `are_translations_complete`  bool | The status for template translations |

### Error Codes

| Error | Description |
| --- | --- |
| 80008 | There have been too many calls to this WhatsApp Business account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 100 | Invalid parameter |
| 200 | Permissions error |
| 190 | Invalid OAuth 2.0 Access Token |

## Creating

You can make a POST request to `message_templates` edge from the following paths:

* [`/{whats_app_business_account_id}/message_templates`](/docs/graph-api/reference/whats-app-business-account/message_templates/)

When posting to this edge, a [WhatsAppMessageTemplate](/docs/graph-api/reference/whats-app-business-hsm/) will be created.

Type | Description || Access Tokens | [User](/docs/whatsapp/business-management-api/get-started#user-access-tokens), [System User](/docs/whatsapp/access-tokens#system-user-access-tokens), or [Business Integration System User](/docs/whatsapp/access-tokens#business-integration-system-user-access-tokens) |
| Permissions | [whatsapp\_business\_management](/docs/permissions#w) |

### Request Syntax

```
POST /<WHATSAPP_BUSINESS_ACCOUNT_ID>/message_templates
```

### Path Parameters

Placeholder | Value || `<WHATSAPP_BUSINESS_ACCOUNT_ID>` | ID of the WhatsApp Business Account to create the template on. |

### Post Body

See [Parameters](#parameters-2) for property descriptions.

```
{
  "allow_category_change": <ALLOW_CATEGORY_CHANGE>,
  "name": "<NAME>",
  "language": "<LANGUAGE>",
  "category": "<CATEGORY>",
  "components": [<COMPONENTS>]
}
```

### Response

See [Return Type](#return-type).

### Sample Request

```
curl 'https://graph.facebook.com/v25.0/102290129340398/message_templates' \
-H 'Content-Type: application/json' \
-H 'Authorization: Bearer EAAJB...' \
-d '
{
  "name": "seasonal_promotion",
  "language": "en",
  "category": "MARKETING",
  "components": [
    {
      "type": "HEADER",
      "format": "TEXT",
      "text": "Our {{1}} is on!",
      "example": {
        "header_text": [
          "Summer Sale"
        ]
      }
    },
    {
      "type": "BODY",
      "text": "Shop now through {{1}} and use code {{2}} to get {{3}} off of all merchandise.",
      "example": {
        "body_text": [
          [
            "the end of August","25OFF","25%"
          ]
        ]
      }
    },
    {
      "type": "FOOTER",
      "text": "Use the buttons below to manage your marketing subscriptions"
    },
    {
      "type":"BUTTONS",
      "buttons": [
        {
          "type": "QUICK_REPLY",
          "text": "Unsubcribe from Promos"
        },
        {
          "type":"QUICK_REPLY",
          "text": "Unsubscribe from All"
        }
      ]
    }
  ]
}'
```

### Sample Response

```
{
    "id": "594425479261596",
    "status": "PENDING",
    "category": "MARKETING"
}
```

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `allow_category_change`  boolean | Set to `true` to allow us to assign a category based on our [template guidelines](/docs/whatsapp/updates-to-pricing/new-template-guidelines) and the template's contents. This can prevent the template `status` from immediately being set to `REJECTED` upon creation due to miscategorization.  If omitted, template will not be auto-assigned a category and its status may be set to `REJECTED` if determined to be miscategorized.  See [Template Categories](/docs/whatsapp/business-management-api/message-templates/#categories). |
| `category`  enum {UTILITY, MARKETING, AUTHENTICATION} | Template category. See [Template Categories](/docs/whatsapp/business-management-api/message-templates/#categories). |
| `components`  array<JSON object> | Array of components that make up the template. See [Template Components](/docs/whatsapp/business-management-api/message-templates/components).  For types `HEADER`, `BODY`, `FOOTER`, `text` is required. |
| `type`  enum {GREETING, HEADER, BODY, FOOTER, BUTTONS, CAROUSEL, ALBUM, LIMITED\_TIME\_OFFER, CALL\_PERMISSION\_REQUEST, TAP\_TARGET\_CONFIGURATION, ATTACHMENT} | Component type.  Required |
| `format`  enum {TEXT, IMAGE, DOCUMENT, VIDEO, LOCATION, GIF, COLLECTION} | Component format. |
| `text`  string | **Required for components with type `HEADER`,`BODY`**  Component text. |
| `buttons`  array<JSON object> | Button components to be used in the template. |
| `type`  enum {QUICK\_REPLY, URL, PHONE\_NUMBER, OTP, MPM, CATALOG, FLOW, VOICE\_CALL, VIDEO\_CALL, POSTBACK, BOOKING\_STATUS, PAYMENT\_REQUEST, REQUEST\_CONTACT\_INFO} | Button type.  Required |
| `text`  string | Button text. |
| `url`  URI | url |
| `phone_number`  phone number string | phone\_number |
| `example`  array<string> | example |
| `flow_id`  int64 | flow\_id |
| `zero_tap_terms_accepted`  boolean | zero\_tap\_terms\_accepted |
| `flow_action`  enum {NAVIGATE, DATA\_EXCHANGE} | flow\_action |
| `navigate_screen`  string | navigate\_screen |
| `supported_apps`  array<JSON object> | supported\_apps |
| `package_name`  string | package\_name  Required |
| `signature_hash`  string | signature\_hash  Required |
| `ttl_minutes`  int64 | ttl\_minutes |
| `flow_name`  string | flow\_name |
| `flow_json`  string | flow\_json |
| `icon`  enum {DOCUMENT, PROMOTION, REVIEW} | icon |
| `endpoint_uri`  URI | endpoint\_uri |
| `example`  JSON object | Placeholder examples. Templates will not be approved without examples. |
| `header_text`  array<string> | header\_text |
| `body_text`  array<array<string>> | body\_text |
| `header_handle`  array<string> | header\_handle |
| `header_text_named_params`  array<JSON object> | header\_text\_named\_params |
| `param_name`  string | param\_name  Required |
| `example`  string | example  Required |
| `body_text_named_params`  array<JSON object> | body\_text\_named\_params |
| `param_name`  string | param\_name  Required |
| `example`  string | example  Required |
| `creative_sourcing_spec`  JSON object | Defines the ACO dimensions specification the Biz can opt in or out of. |
| `associated_product_set_id`  numeric string | The associated product set id |
| `is_primary_device_delivery_only`  boolean | is\_primary\_device\_delivery only |
| `language`  string | Template [location and locale code](/docs/whatsapp/business-management-api/message-templates/supported-languages). |
| `library_template_body_inputs`  JSON object | Optional data during creation of a template from a library template. These are optional fields for the body component. |
| `add_contact_number`  boolean | add\_contact\_number |
| `add_learn_more_link`  boolean | add\_learn\_more\_link |
| `add_security_recommendation`  boolean | add\_security\_recommendation |
| `add_track_package_link`  boolean | add\_track\_package\_link |
| `code_expiration_minutes`  int64 | code\_expiration\_minutes |
| `library_template_button_inputs`  array<JSON object> | Optional data during creation of a template from a library template. These are optional fields for the button component. |
| `type`  enum {QUICK\_REPLY, URL, PHONE\_NUMBER, OTP, MPM, CATALOG, FLOW, VOICE\_CALL, VIDEO\_CALL, POSTBACK, BOOKING\_STATUS, PAYMENT\_REQUEST, REQUEST\_CONTACT\_INFO} | type  Required |
| `phone_number`  string | phone\_number |
| `url`  JSON object | url |
| `base_url`  string | base\_url  Required |
| `url_suffix_example`  string | url\_suffix\_example |
| `otp_type`  enum {COPY\_CODE, ONE\_TAP, ZERO\_TAP, NO\_BUTTONS} | otp\_type |
| `zero_tap_terms_accepted`  boolean | zero\_tap\_terms\_accepted |
| `supported_apps`  array<JSON object> | supported\_apps |
| `package_name`  string | package\_name  Required |
| `signature_hash`  string | signature\_hash  Required |
| `booking_url`  JSON object | booking\_url |
| `base_url`  string | base\_url  Required |
| `url_suffix_example`  string | url\_suffix\_example |
| `booking_management_url`  JSON object | booking\_management\_url |
| `base_url`  string | base\_url  Required |
| `url_suffix_example`  string | url\_suffix\_example |
| `notes`  JSON object | notes |
| `text`  string | text  Required |
| `positional_params`  array<string> | positional\_params |
| `named_params`  array<JSON object> | named\_params |
| `param_name`  string | param\_name  Required |
| `example`  string | example  Required |
| `library_template_name`  string | library\_template\_name |
| `message_send_ttl_seconds`  int64 | Time to live for message template sent. If users are offline for more than TTL duration after message template is sent, we will retry the delivery for a period of time known as a time-to-live, TTL, or the message validity period.  TTL can be configured for certain message types. See [Time-To-Live](/docs/whatsapp/business-management-api/message-templates#time-to-live--ttl---customization--defaults--min-max-values--and-compatibility). |
| `name`  string | Template name.  Required |
| `optimization_spec`  JSON object | optimization\_spec |
| `bid_strategy`  enum {COST\_CAP, LOWEST\_COST\_WITH\_BID\_CAP, LOWEST\_COST\_WITH\_MIN\_ROAS, LOWEST\_COST\_WITHOUT\_CAP} | bid\_strategy |
| `start_time`  string | start\_time |
| `end_time`  string | end\_time |
| `lifetime_budget`  int64 | lifetime\_budget |
| `daily_budget`  int64 | daily\_budget |
| `bid_amount`  int64 | bid\_amount |
| `bid_country_multiplier_overrides`  JSON object {enum {AC, AD, AE, AF, AG, AI, AL, AM, AN, AO, AQ, AR, AS, AT, AU, AW, AX, AZ, BA, BB, BD, BE, BF, BG, BH, BI, BJ, BL, BM, BN, BO, BQ, BR, BS, BT, BV, BW, BY, BZ, CA, CC, CD, CF, CG, CH, CI, CK, CL, CM, CN, CO, CR, CU, CV, CW, CX, CY, CZ, DE, DJ, DK, DM, DO, DZ, EC, EE, EG, EH, ER, ES, ET, FI, FJ, FK, FM, FO, FR, GA, GB, GD, GE, GF, GG, GH, GI, GL, GM, GN, GP, GQ, GR, GS, GT, GU, GW, GY, HK, HM, HN, HR, HT, HU, ID, IE, IL, IM, IN, IO, IQ, IR, IS, IT, JE, JM, JO, JP, KE, KG, KH, KI, KM, KN, KP, KR, KW, KY, KZ, LA, LB, LC, LI, LK, LR, LS, LT, LU, LV, LY, MA, MC, MD, ME, MF, MG, MH, MK, ML, MM, MN, MO, MP, MQ, MR, MS, MT, MU, MV, MW, MX, MY, MZ, NA, NC, NE, NF, NG, NI, NL, NO, NP, NR, NU, NZ, OM, PA, PE, PF, PG, PH, PK, PL, PM, PN, PR, PS, PT, PW, PY, QA, RE, RO, RS, RU, RW, SA, SB, SC, SD, SE, SG, SH, SI, SJ, SK, SL, SM, SN, SO, SR, SS, ST, SV, SX, SY, SZ, TC, TD, TF, TG, TH, TJ, TK, TL, TM, TN, TO, TR, TT, TV, TW, TZ, UA, UG, UM, US, UY, UZ, VA, VC, VE, VG, VI, VN, VU, WF, WS, XK, YE, YT, ZA, ZM, ZW} : float} | bid\_country\_multiplier\_overrides |
| `optimization_goal`  enum {LINK\_CLICKS, OFFSITE\_CONVERSIONS, REACH, VALUE} | optimization\_goal |
| `status`  enum {ACTIVE, ARCHIVED, DELETED, PAUSED} | status |
| `whatsapp_business_phone_number_id`  numeric string | whatsapp\_business\_phone\_number\_id |
| `targeting`  JSON object | targeting |
| `custom_audiences`  array<numeric string> | custom\_audiences  Required |
| `excluded_custom_audiences`  array<numeric string> | excluded\_custom\_audiences |
| `promoted_object`  JSON object | promoted\_object |
| `pixel_id`  string | pixel\_id |
| `custom_event_type`  enum {ADD\_PAYMENT\_INFO, ADD\_TO\_CART, ADD\_TO\_WISHLIST, COMPLETE\_REGISTRATION, CONTENT\_VIEW, INITIATED\_CHECKOUT, LEAD, LEVEL\_ACHIEVED, PURCHASE, RATE, SUBSCRIBE, TUTORIAL\_COMPLETION} | custom\_event\_type |
| `application_id`  string | application\_id |
| `attribution_spec`  array<JSON object> | attribution\_spec |
| `event_type`  enum {CLICK\_THROUGH} | event\_type  Required |
| `window_days`  int64 | window\_days  Required |
| `adset_schedule`  array<JSON object> | adset\_schedule |
| `start_minute`  int64 | start\_minute  Required |
| `end_minute`  int64 | end\_minute  Required |
| `days`  array<int64> | days  Required |
| `timezone_type`  enum {ADVERTISER, USER} | timezone\_type |
| `parameter_format`  enum {NAMED, POSITIONAL} | The parameter format of the template |
| `product_set_id`  numeric string | [Coming soon] This will let you connect a product set (from your catalog) to the template and send messages without needing to specify products in the send API call. Our product recommendation engine will select the products your customers are most interested in and likely to convert. This feature is called Dynamic Product Message. Note: This is still in development. |
| `sub_category`  enum {ORDER\_DETAILS, ORDER\_STATUS, RICH\_ORDER\_STATUS} | Sub category of the template |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`id`: numeric string,

`status`: enum,

`category`: enum,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 80008 | There have been too many calls to this WhatsApp Business account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 131009 | Parameter value is not valid |
| 192 | Invalid phone number |
| 200 | Permissions error |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 200002 | HSM Template creation failed |
| 139000 | Blocked by Integrity |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can dissociate a [WhatsAppMessageTemplate](/docs/graph-api/reference/whats-app-business-hsm/) from a [WhatsAppBusinessAccount](/docs/graph-api/reference/whats-app-business-account/) by making a DELETE request to [`/{whats_app_business_account_id}/message_templates`](/docs/graph-api/reference/whats-app-business-account/message_templates/).

Type | Description || Access Tokens | [User](/docs/whatsapp/business-management-api/get-started#user-access-tokens), [System User](/docs/whatsapp/access-tokens#system-user-access-tokens), or [Business Integration System User](/docs/whatsapp/access-tokens#business-integration-system-user-access-tokens) |
| Permissions | [whatsapp\_business\_management](/docs/permissions#w) |

### Request Syntax

```
DELETE /<WHATSAPP_BUSINESS_ACCOUNT_ID>/message_templates
```

### Path Parameters

Placeholder | Value || `<WHATSAPP_BUSINESS_ACCOUNT_ID>` | ID of the WhatsApp Business Account that owns the template. |

### Response

See [Return Type](#return-type-2).

### Sample Request

```
curl -X DELETE 'https://graph.facebook.com/v25.0/102290129340398/message_templates?name=order_confirmation' \
-H 'Authorization: Bearer EAAJB...'
```

### Sample Response

```
{
  "success": true
}
```

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `hsm_id`  numeric string | ID of template to be deleted. Required with name if deleting a specific template by ID. |
| `hsm_ids`  array<numeric string> | IDs of all the templates for bulk deletion. Required if you wish to delete templates in bulk |
| `name`  string | Name of template to be deleted. Deletes templates matching the name in all languages |

### Return Type

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 200 | Permissions error |
| 190 | Invalid OAuth 2.0 Access Token |
| 80008 | There have been too many calls to this WhatsApp Business account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |

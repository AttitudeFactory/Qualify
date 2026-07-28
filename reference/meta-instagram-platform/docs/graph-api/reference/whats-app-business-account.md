Graph API Version

[v25.0](#)

# WhatsApp Business Account

Represents phone numbers that belong to a specific WhatsApp Business Account (WABA).

To find the ID of a WhatsApp Business Account, go to [**Business Manager**](https://business.facebook.com/) > **Business Settings** > **Accounts** > **WhatsApp Business Accounts**. Find the account you want to use and click on it. A panel opens, with information about the account, including the ID.


For more information on how to use the API, see [WhatsApp Business Management API](/docs/whatsapp/business-account-management-api).

The following API calls are subject to [Business Use Case Rate Limits](/docs/graph-api/overview/rate-limiting/#wa-biz-api):

* `GET`, `POST`, and `DELETE` calls to `/{whats-app-business-account-id}/assigned_users`
* `GET` calls to `/{whats-app-business-account-id}`

## Reading

Returns the account information of a WhatsApp Business Account

### Example

Requirements

* whatsapp\_business\_management permission
* whatsapp\_business\_messaging permission
* public\_profile permission
* WhatsApp Business Account (WABA) ID
* USER ACCESS TOKEN

Request

cURLAndroid SDKObjective-C

```
curl -i -X GET \
 "https://graph.facebook.com/LATEST-VERSION/WHATSAPP-BUSINESS-ACCOUNT-ID?access_token=USER-ACCESS-TOKEN"
```

```
GraphRequest request = GraphRequest.newGraphPathRequest(
  accessToken,
  "/WHATSAPP-BUSINESS-ACCOUNT-ID",
  new GraphRequest.Callback() {
    @Override
    public void onCompleted(GraphResponse response) {
      // Insert your code here
    }
});

request.executeAsync();
```

```
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
    initWithGraphPath:@"/WHATSAPP-BUSINESS-ACCOUNT-ID"
           parameters:nil
           HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection, id result, NSError *error) {
    // Insert your code here
}];
```

Response

```
{
  "id": "WHATSAPP-BUSINESS-ACCOUNT-ID",
  "name": "Test WhatsApp Business Account",
  "timezone_id": "1",
  "message_template_namespace": "MESSAGE-TEMPLATE-NAMESPACE"
}
```

### Parameters

This endpoint doesn't have any parameters.

### Fields

| Field | Description |
| --- | --- |
| `analytics`  [WABAAnalytics](https://developers.facebook.com/docs/graph-api/reference/waba-analytics/) | Used to designate which analytics metrics you want returned. See [Analytics](/docs/whatsapp/business-management-api/analytics). |
| `business_verification_status`  enum {expired, failed, ineligible, not\_verified, pending, pending\_need\_more\_info, pending\_submission, rejected, revoked, verified} | Current status of business verification of Meta Business Account which owns this WhatsApp Business Account |
| `country`  string | country of the WhatsApp Business Account's owning Meta Business account |
| `currency`  string | The currency in which the payment transactions for the WhatsApp Business Account will be processed  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `health_status`  WhatsAppBusinessHealthStatusForMessageSend | Health status of the WABA in regards to whether the WABA, Business, and App can send a message |
| `is_enabled_for_insights`  bool | If `true`, indicates the WhatsApp Business Account enabled template analytics. See [Analytics](/docs/whatsapp/business-management-api/analytics). |
| `is_shared_with_partners`  bool | is\_shared\_with\_partners |
| `marketing_messages_lite_api_status`  enum | WhatsApp Business Account's status for onboarding onto Marketing Messages Lite.  Values can be:  `INELIGIBLE` — Indicates the WABA has not met all eligibility requirements.  `ELIGIBLE`— Indicates WABA has met all eligibility requirements  `ONBOARDED` — Indicates the WABA is eligible to use MM Lite API and:   * the owning business has signed MM Lite Terms of Service * the WABA has a valid payment method attached * the WABA is linked to an Ad account   `UNKNOWN`— Indicates an unknown status. Please contact support for assistance. |
| `marketing_messages_onboarding_status`  enum | Onboarding status of the WhatsApp Business account into Marketing Messages Lite API.  Values can be:  `INELIGIBLE_ON_BEHALF_OF_WABA` — The WhatsApp Business Account (“WABA”) uses the [“OBO”](/docs/whatsapp/overview/business-accounts#on-behalf-of--obo--model) model which is not supported. You must either first [transfer ownership](/docs/whatsapp/solution-providers/support/transferring-wabas-to-customers/) of the WABA to the customer or onboard using the [Intent API](/docs/whatsapp/marketing-messages-lite-api/for-solution-providers#-recommended--onboard-a-business-to-mm-lite-api-using-the-intent-api).  `INELIGIBLE_INACTIVE_OR_RESTRICTED` — The WhatsApp Business Account is inactive or is restricted from messaging due to a [policy enforcement issue](/docs/whatsapp/overview/policy-enforcement).  `INELIGIBLE_COUNTRY_NOT_SUPPORTED` — The WhatsApp Business Account is in a [region](/docs/whatsapp/marketing-messages-lite-api/get-started#geographic-availability-of-features) that does not support the MM Lite API.  `INELIGIBLE_USING_WHATSAPP_BUSINESS_APP` — The WhatsApp Business phone number is being used within the [WhatsApp Business](https://l.facebook.com/l.php?u=https%3A%2F%2Fbusiness.whatsapp.com%2F&h=AUDJsk6hAV_FUdnJHfOxvwk9qVPFJgYqW79TBU_ZqL8FcQo7z7F4leIIqv9q8gQiGG6ajmvkdSzWYDGGZG49ik-VbTfXZTr-CcjVHIIWbZywHfBtfdFHyNWi8rfJsDXcWf73JQqbgChu2o4o) app.  `ELIGIBLE` — WhatsApp Business Account is eligible to [onboard](/docs/whatsapp/marketing-messages-lite-api/onboarding#self-onboard-to-mm-lite-api) and use the MM Lite API.  `PENDING_VALID_PAYMENT_METHOD` — The WhatsApp Business Account requires setting up a [valid payment method](https://www.facebook.com/business/help/2225184664363779).  `PENDING_INTERNAL_SETUP` — WhatsApp Business Account is in the configuration process of using the MM Lite API and requires no further action from the business customer or partner.  The automated setup process is estimated to take less than ten minutes. Subscribe to the [account\_update](/docs/whatsapp/cloud-api/webhooks/reference/account_update) webhook and listen for the `AD_ACCOUNT_LINKED` event.  Submit a [support ticket](https://business.facebook.com/direct-support) if the setup process takes more than ten minutes and you have not received a webhook.  `ONBOARDED` — The WhatsApp Business Account has successfully onboarded and is ready to use the MM Lite API. |
| `message_template_namespace`  string | Namespace string for the message templates that belong to the WhatsApp Business Account  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `name`  string | User-friendly name to differentiate WhatsApp Business Accounts  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `on_behalf_of_business_info`  WABAOnBehalfOfComputedInfo | The "on behalf of" information for the WhatsApp Business Account |
| `ownership_type`  enum | Ownership type of the WhatsApp Business Account |
| `primary_funding_id`  numeric string | Primary funding ID for the WhatsApp Business Account paid service |
| `purchase_order_number`  string | The purchase order number supplied by the business for payment management purposes |
| `status`  string | WhatsApp Business Account status. **Default:** ACTIVE |
| `timezone_id`  string | The timezone of the WhatsApp Business Account  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `whatsapp_business_manager_messaging_limit`  enum {TIER\_100K, TIER\_10K, TIER\_250, TIER\_2K, TIER\_50, TIER\_UNLIMITED, UNTIERED} | Maximum number of unique WhatsApp user phone numbers that your Business Manager account can message, outside of a customer service window, within a moving 24-hour period. This limit is shared across all WhatsApp phone numbers owned by your business. |

### Edges

| Edge | Description |
| --- | --- |
| [`activities`](/docs/graph-api/reference/whats-app-business-account/activities/)  Edge<WhatsAppBusinessActivityHistory> | activities |
| [`call_analytics`](/docs/graph-api/reference/whats-app-business-account/call_analytics/)  Edge<WABACallAnalytics> | Analytics data of the WhatsApp Business Account for calling |
| [`conversation_analytics`](/docs/graph-api/reference/whats-app-business-account/conversation_analytics/)  Edge<WABAConversationAnalytics> | Analytics data of the WhatsApp Business Account with conversation based pricing |
| [`dataset`](/docs/graph-api/reference/whats-app-business-account/dataset/)  Edge<Dataset> | ID of the dataset |
| [`message_template_previews`](/docs/graph-api/reference/whats-app-business-account/message_template_previews/)  Edge<WhatsAppBusinessAccountMessageTemplatePreview> | Retrieves a preview of a message template based on the provided configuration |
| [`message_templates`](/docs/graph-api/reference/whats-app-business-account/message_templates/)  Edge<WhatsAppBusinessHSM> | Message templates that belong to the WhatsApp Business Account |
| [`payment_configuration`](/docs/graph-api/reference/whats-app-business-account/payment_configuration/)  Edge<WhatsAppBusinessAccountPaymentConfiguration> | Fetch payment configuration attached to the WhatsApp Business Account. |
| [`payment_configurations`](/docs/graph-api/reference/whats-app-business-account/payment_configurations/)  Edge<WhatsAppBusinessAccountPaymentConfigurations> | Fetch all payment configurations attached to the WhatsApp Business Account. |
| [`phone_numbers`](/docs/graph-api/reference/whats-app-business-account/phone_numbers/)  Edge<WhatsAppBusinessAccountToNumberCurrentStatus> | The phone numbers that belong to the WhatsApp Business Account |
| [`pricing_analytics`](/docs/graph-api/reference/whats-app-business-account/pricing_analytics/)  Edge<WABAPricingAnalytics> | Pricing analytics data of the WhatsApp Business Account with per message pricing |
| [`product_catalogs`](/docs/graph-api/reference/whats-app-business-account/product_catalogs/)  Edge<ProductCatalog> | product\_catalogs |
| [`solutions`](/docs/graph-api/reference/whats-app-business-account/solutions/)  Edge<WhatsAppBusinessSolution> | Partner solutions that this WhatsApp Business Account is linked to |
| [`subscribed_apps`](/docs/graph-api/reference/whats-app-business-account/subscribed_apps/)  Edge<WhatsAppApplication> | List of apps that are subscribed to webhooks updates for this WABA |
| [`template_groups`](/docs/graph-api/reference/whats-app-business-account/template_groups/)  Edge<BusinessMessagingTemplateGroup> | Retrieve list of existing template groups associated with WhatsApp Business Account |

### Error Codes

| Error | Description |
| --- | --- |
| 80008 | There have been too many calls to this WhatsApp Business account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 200008 | WhatsApp Business Account has no linked phone numbers. |
| 100 | Invalid parameter |
| 200 | Permissions error |
| 2500 | Error parsing graph query |
| 131031 | Business Account locked |
| 190 | Invalid OAuth 2.0 Access Token |
| 131000 | Something went wrong |
| 200005 | Template Insights are not available yet for this WhatsApp Business account |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

## Supported values

### Currencies

Supported values for currency codes can be found in [currencies](https://developers.facebook.com/docs/marketing-api/currencies).

### Time Zones

Supported values for time zones can be found in [timezone ids](https://developers.facebook.com/docs/marketing-api/reference/ad-account/timezone-ids/v10.0).

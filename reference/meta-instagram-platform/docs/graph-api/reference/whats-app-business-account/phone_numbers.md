Graph API Version

[v25.0](#)

# Whats App Business Account Phone Numbers

Represents a collection of WhatsApp business phone numbers associated with a WhatsApp Business Account (WABA).

## Reading

You can't perform this operation on this endpoint.

## Creating

Create a business phone number on a WABA, or migrate a phone number from one a source WABA to a destination WABA.

### Requirements

Type | Description || [Access Tokens](/docs/facebook-login/guides/access-tokens) | [User](/docs/facebook-login/access-tokens#usertokens) or [System User](https://www.facebook.com/business/help/503306463479099). |
| [Permissions](/docs/permissions/reference) | [whatsapp\_business\_management](/docs/permissions/reference/whatsapp_business_management)  [whatsapp\_business\_messaging](/docs/permissions/reference/whatsapp_business_messaging) |

### Example Request

cURLAndroid SDKObjective-C

```
curl -i -X POST \
 "https://graph.facebook.com/LATEST-VERSION/WHATSAPP-BUSINESS-ACCOUNT-ID/phone_numbers?
  cc=COUNTRY-CODE&
  phone_number=PHONE-NUMBER&
  migrate_phone_number=true&
  access_token=USER-ACCESS-TOKEN"
```

```
GraphRequest request = GraphRequest.newPostRequest(
  accessToken,
  "/WHATSAPP-BUSINESS-ACCOUNT-ID/phone_numbers",
  new JSONObject("{\"cc\":\"COUNTRY-CODE\",\"phone_number\":\"PHONE-NUMBER\",\"migrate_phone_number\":true}"),
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
    initWithGraphPath:@"/WHATSAPP-BUSINESS-ACCOUNT-ID/phone_numbers"
           parameters:@{ @"cc": @"COUNTRY-CODE",@"phone_number": @"PHONE-NUMBER",@"migrate_phone_number": @"true",}
           HTTPMethod:@"POST"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection, id result, NSError *error) {
    // Insert your code here
}];
```

### Example Response

```
{
  "id": "<BUSINESS_PHONE_NUMBER_ID>"
}
```

You can make a POST request to `phone_numbers` edge from the following paths:

* [`/{whats_app_business_account_id}/phone_numbers`](/docs/graph-api/reference/whats-app-business-account/phone_numbers/)

When posting to this edge, a [WhatsAppBusinessPhoneNumber](/docs/graph-api/reference/whats-app-business-account-to-number-current-status/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `cc`  string | Country dial code of the phone number (for example, `1`). |
| `migrate_phone_number`  boolean | Set to `true` to migrate a registered WhatsApp Business Phone Number from one WhatsApp Business Account to another. |
| `phone_number`  string | Phone number without the country code or plus symbol (`+`). |
| `preverified_id`  string | Preverified ID related to this phone number |
| `verified_name`  string | Name of the business as it appears in the WhatsApp app or WhatsApp Business app profile. |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 300 | Edit failure |
| 200000 | Cannot add phone number to WhatsApp Business Account |
| 200 | Permissions error |
| 104 | Incorrect signature |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

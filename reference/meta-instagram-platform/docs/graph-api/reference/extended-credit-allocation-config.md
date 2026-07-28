Graph API Version

[v25.0](#)

# Extended Credit Allocation Config

## Reading

Represents a relationship between two business portfolio for the purpose of sharing credit line between them.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bextended-credit-allocation-config-id%7D&version=v25.0)

```
GET /v25.0/{extended-credit-allocation-config-id} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{extended-credit-allocation-config-id}',
    '{access-token}'
  );
} catch(Facebook\Exceptions\FacebookResponseException $e) {
  echo 'Graph returned an error: ' . $e->getMessage();
  exit;
} catch(Facebook\Exceptions\FacebookSDKException $e) {
  echo 'Facebook SDK returned an error: ' . $e->getMessage();
  exit;
}
$graphNode = $response->getGraphNode();
/* handle the result */
```

```
/* make the API call */
FB.api(
    "/{extended-credit-allocation-config-id}",
    function (response) {
      if (response && !response.error) {
        /* handle the result */
      }
    }
);
```

```
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/{extended-credit-allocation-config-id}",
    null,
    HttpMethod.GET,
    new GraphRequest.Callback() {
        public void onCompleted(GraphResponse response) {
            /* handle the result */
        }
    }
).executeAsync();
```

```
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/{extended-credit-allocation-config-id}"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

If you want to learn how to use the Graph API, read our [Using Graph API guide](/docs/graph-api/using-graph-api/).

### Parameters

This endpoint doesn't have any parameters.

### Fields

| Field | Description |
| --- | --- |
| `id`  numeric string | ID  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `currency_amount`  CurrencyAmount | The currency amount this allocation is for. If amount is zero then this allocation could be inactive or simply an authorization. Default: 0 |
| `liability_type`  enum | The liability terms of this business relationship |
| `owning_business`  [Business](https://developers.facebook.com/docs/marketing-api/reference/business/) | The business owning the credential that credit is being requested from |
| `owning_credential`  [ExtendedCredit](https://developers.facebook.com/docs/marketing-api/reference/extended-credit/) | Extended credit object that will be providing credit |
| `partition_type`  enum | Fixed partition or unrestricted credit partition |
| `receiving_business`  [Business](https://developers.facebook.com/docs/marketing-api/reference/business/) | The business that will be receiving the allocation |
| `receiving_credential`  [ExtendedCredit](https://developers.facebook.com/docs/marketing-api/reference/extended-credit/) | Extended credit object that will be receiving credit |
| `request_status`  enum | If this allocation is pending acceptance from another party |
| `send_bill_to`  enum | Determines where invoices are sent by default. This is an indication of who will receive invoices in this business relationship, but invoices can also be sent to separately configured email address. AGENCY will result in invoices sent to the receiving party while ADVERTISER will result in invoices sent to the owning party |

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

## Creating

You can make a POST request to `owning_credit_allocation_configs` edge from the following paths:

* [`/{extended_credit_id}/owning_credit_allocation_configs`](/docs/marketing-api/reference/extended-credit/owning_credit_allocation_configs/)

When posting to this edge, an [ExtendedCreditAllocationConfig](/docs/graph-api/reference/extended-credit-allocation-config/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `amount`  Positive float | The amount of this allocation. You should only set it if the credit allocation type is FIXED |
| `liability_type`  enum {, Normal, Sequential, MSA} | The terms that will be applicable to ad account under the receiving party using this credit line. Sequential: https://www.facebook.com/legal/sequential\_invoicing\_terms, Normal: https://www.facebook.com/terms\_ads\_invoicing.php |
| `partition_type`  enum {FIXED, AUTH, FIXED\_WITHOUT\_PARTITION} | Fixed partition or unrestricted credit partition |
| `receiving_business_id`  numeric string or integer | The business that you are going to allocate credit to  Required |
| `send_bill_to`  enum {, Agency, Advertiser} | Whether invoices will by default go to the credit line owner or the receiving party. AGENCY will send to the receiving party, ADVERTISER to the owner |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

`requires_additional_approval`: enum,

}

### Error Codes

| Error | Description |
| --- | --- |
| 4000 | A credit allocation already exists between your business and the designated business. |
| 200 | Permissions error |
| 100 | Invalid parameter |

You can make a POST request to `whatsapp_credit_sharing_and_attach` edge from the following paths:

* [`/{extended_credit_id}/whatsapp_credit_sharing_and_attach`](/docs/marketing-api/reference/extended-credit/whatsapp_credit_sharing_and_attach/)

When posting to this edge, an [ExtendedCreditAllocationConfig](/docs/graph-api/reference/extended-credit-allocation-config/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `waba_currency`  string | The ISO-4217-3 currency code  Required |
| `waba_id`  numeric string or integer | Id of the WhatsApp Business Account you are sharing credit line with  Required |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`allocation_config_id`: numeric string,

`waba_id`: numeric string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 200 | Permissions error |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can dissociate an [ExtendedCreditAllocationConfig](/docs/graph-api/reference/extended-credit-allocation-config/) from an [ExtendedCreditAllocationConfig](/docs/graph-api/reference/extended-credit-allocation-config/) by making a DELETE request to [`/{extended_credit_allocation_config_id}/ExtendedCreditOwningCreditAllocationConfigs`](/docs/graph-api/reference/extended-credit-allocation-config/extendedcreditowningcreditallocationconfigs/).

### Parameters

This endpoint doesn't have any parameters.

### Return Type

Struct {

`success`: bool,

}

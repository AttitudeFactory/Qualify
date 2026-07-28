Graph API Version

[v25.0](#)

# Whats App Business Account Product Catalogs

## Reading

Returns the product catalog connected to the WhatsApp Business Account

### Example

Requirements

* whatsapp\_business\_management permission
* whatsapp\_business\_messaging permission
* catalog\_management permission
* public\_profile permission
* WHATSAPP BUSINESS ACCOUNT ID
* USER ACCESS TOKEN

Request

cURLAndroid SDKObjective-C

```
curl -i -X GET \
 "https://graph.facebook.com/LATEST-VERSION/WHATSAPP-BUSINESS-ACCOUNT-ID/product_catalogs?access_token=USERS-ACCESS-TOKEN"
```

```
GraphRequest request = GraphRequest.newGraphPathRequest(
  accessToken,
  "/WHATSAPP-BUSINESS-ACCOUNT-ID/product_catalogs",
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
    initWithGraphPath:@"/WHATSAPP-BUSINESS-ACCOUNT-ID/product_catalogs"
           parameters:nil
           HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection, id result, NSError *error) {
    // Insert your code here
}];
```

Response

```
{
  "data": [
  ]
}
```

### Parameters

This endpoint doesn't have any parameters.

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": []
}
```

#### `data`

A list of [ProductCatalog](/docs/marketing-api/reference/product-catalog/) nodes.

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 200 | Permissions error |
| 80008 | There have been too many calls to this WhatsApp Business account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 2500 | Error parsing graph query |

## Creating

You can make a POST request to `product_catalogs` edge from the following paths:

* [`/{whats_app_business_account_id}/product_catalogs`](/docs/graph-api/reference/whats-app-business-account/product_catalogs/)

When posting to this edge, no Graph object will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `catalog_id`  numeric string | catalog\_id  Required |

### Return Type

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

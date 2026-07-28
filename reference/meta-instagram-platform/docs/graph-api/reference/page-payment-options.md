Graph API Version

[v25.0](#)

# Page Payment Options

Page payment options in the Graph API. Used for Facebook Pages.

## Reading

Information about payment options accepted by the business

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_PagePaymentOptions%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_PagePaymentOptions} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_PagePaymentOptions}',
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
    "...?fields={fieldname_of_type_PagePaymentOptions}",
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
    "...?fields={fieldname_of_type_PagePaymentOptions}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_PagePaymentOptions}"
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
| `amex`  unsigned int32 | Whether the business accepts American Express as a payment option  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `cash_only`  unsigned int32 | Whether the business accepts cash only as a payment option  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `discover`  unsigned int32 | Whether the business accepts Discover as a payment option  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `mastercard`  unsigned int32 | Whether the business accepts MasterCard as a payment option  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `visa`  unsigned int32 | Whether the business accepts Visa as a payment option  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

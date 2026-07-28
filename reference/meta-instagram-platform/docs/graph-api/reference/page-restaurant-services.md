Graph API Version

[v25.0](#)

# Page Restaurant Services

Services that a Resturant that's represented as a Facebook Page might provide

## Reading

Services the restaurant provides. Applicable to Restaurants

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_PageRestaurantServices%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_PageRestaurantServices} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_PageRestaurantServices}',
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
    "...?fields={fieldname_of_type_PageRestaurantServices}",
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
    "...?fields={fieldname_of_type_PageRestaurantServices}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_PageRestaurantServices}"
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
| `catering`  bool | Whether the restaurant has catering service  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `delivery`  bool | Whether the restaurant has delivery service  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `groups`  bool | Whether the restaurant is group-friendly  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `kids`  bool | Whether the restaurant is kids-friendly  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `outdoor`  bool | Whether the restaurant has outdoor seating  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `pickup`  bool | Whether the restaurant has pickup service  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `reserve`  bool | Whether the restaurant takes reservations  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `takeout`  bool | Whether the restaurant has takeout service  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `waiter`  bool | Whether the restaurant has waiters  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `walkins`  bool | Whether the restaurant welcomes walkins  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

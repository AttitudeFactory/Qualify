Graph API Version

[v25.0](#)

# Page Restaurant Specialties

Specialties of a restaurant that is represented by a Facebook Page

## Reading

Services the restaurant provides. Applicable to Restaurants

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_PageRestaurantSpecialties%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_PageRestaurantSpecialties} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_PageRestaurantSpecialties}',
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
    "...?fields={fieldname_of_type_PageRestaurantSpecialties}",
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
    "...?fields={fieldname_of_type_PageRestaurantSpecialties}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_PageRestaurantSpecialties}"
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
| `breakfast`  unsigned int32 | Whether the restaurant serves breakfast  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `coffee`  unsigned int32 | Whether the restaurant serves coffee  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `dinner`  unsigned int32 | Whether the restaurant serves dinner  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `drinks`  unsigned int32 | Whether the restaurant serves drinks  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `lunch`  unsigned int32 | Whether the restaurant serves lunch  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

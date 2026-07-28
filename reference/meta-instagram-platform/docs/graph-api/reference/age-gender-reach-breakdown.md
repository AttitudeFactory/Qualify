Graph API Version

[v25.0](#)

# Age Gender Reach Breakdown

## Reading

The ad reach demographic breakdown in a single country.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_AgeGenderReachBreakdown%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_AgeGenderReachBreakdown} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_AgeGenderReachBreakdown}',
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
    "...?fields={fieldname_of_type_AgeGenderReachBreakdown}",
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
    "...?fields={fieldname_of_type_AgeGenderReachBreakdown}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_AgeGenderReachBreakdown}"
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
| `age_range`  string | The age range of [Accounts Center accounts](https://www.facebook.com/business/help/283579896000936) reached by the ad. Can be one of 18-24, 25-34, 35-44, 45-54, 55-64, 65+.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `female`  int32 | The number of [Accounts Center accounts](https://www.facebook.com/business/help/283579896000936) reached by the ad with a gender identified as female.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `male`  int32 | The number of [Accounts Center accounts](https://www.facebook.com/business/help/283579896000936) reached by the ad with a gender identified as male.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `unknown`  int32 | The number of [Accounts Center accounts](https://www.facebook.com/business/help/283579896000936) reached by the ad with a gender not identified as either female or male.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

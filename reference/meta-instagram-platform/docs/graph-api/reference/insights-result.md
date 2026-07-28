Graph API Version

[v25.0](#)

# Insights Result

## Reading

The result of an Insights query

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_InsightsResult%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_InsightsResult} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_InsightsResult}',
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
    "...?fields={fieldname_of_type_InsightsResult}",
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
    "...?fields={fieldname_of_type_InsightsResult}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_InsightsResult}"
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
| `id`  token with structure: ID | ID of the query |
| `description`  string | Long description of the metric  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `description_from_api_doc`  string | The description of the metric, retrieved from the API doc(https://developers.facebook.com/docs/graph-api/reference/insights) |
| `name`  string | The Insights metric requested  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `period`  enum | The period of time used for the aggregation  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `title`  string | Short description of the metric  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `values`  [list<InsightsValue>](https://developers.facebook.com/docs/graph-api/reference/insights-value/) | The different values for this metric  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

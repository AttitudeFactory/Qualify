Graph API Version

[v25.0](#)

# Application App Event Type Parameters

## Reading

A parameter that has been logged with an App Event. Localized descriptions are provided for predefined parameters.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_ApplicationAppEventTypeParameters%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_ApplicationAppEventTypeParameters} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_ApplicationAppEventTypeParameters}',
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
    "...?fields={fieldname_of_type_ApplicationAppEventTypeParameters}",
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
    "...?fields={fieldname_of_type_ApplicationAppEventTypeParameters}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_ApplicationAppEventTypeParameters}"
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
| `description`  string | Localized description for predefined parameters  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `display_name`  string | Localized name for predefined parameters  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `known_parameter_values`  [list<ApplicationAppEventTypeParameterValues>](https://developers.facebook.com/docs/graph-api/reference/application-app-event-type-parameter-values/) | Localized description of predefiend parameter values  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `parameter_name`  string | String used to represent parameter across the wire  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

Graph API Version

[v25.0](#)

# Page Tab

This is the Graph API endpoint for reading information about Page Tabs.

## Reading

Page app tabs information

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_Tab%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_Tab} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_Tab}',
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
    "...?fields={fieldname_of_type_Tab}",
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
    "...?fields={fieldname_of_type_Tab}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_Tab}"
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
| `id`  string | A concatenation of the Page ID, /tabs/ and the tab app ID prefixed with app\_: {page-id}/tabs/app\_{app-id}  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `application`  [Application](https://developers.facebook.com/docs/graph-api/reference/application/) | The app that is in the tab  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `custom_image_url`  string | URL for an image to be used as a custom icon  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `custom_name`  string | Name to be used for the tab  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `image_url`  string | The location of the tab thumbnail image  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `is_non_connection_landing_tab`  bool | A flag to identify whether the tab is a custom landing tab for users who are not connected to this Page  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `is_permanent`  bool | A flag to identify whether the tab can be removed from the Page  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `link`  string | A link directly to this Page tab  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `name`  string | The tab name, which can be different from the name of the app it links to  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `position`  unsigned int32 | Where this tab is located in the list of tabs  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

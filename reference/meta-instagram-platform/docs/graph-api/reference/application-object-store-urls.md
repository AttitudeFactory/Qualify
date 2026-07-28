Graph API Version

[v25.0](#)

# Application Object Store URLs

## Reading

Mobile store URLs for a Facebook App

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_ApplicationObjectStoreURLs%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_ApplicationObjectStoreURLs} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_ApplicationObjectStoreURLs}',
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
    "...?fields={fieldname_of_type_ApplicationObjectStoreURLs}",
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
    "...?fields={fieldname_of_type_ApplicationObjectStoreURLs}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_ApplicationObjectStoreURLs}"
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
| `amazon_app_store`  string | URL for the app in the Amazon App store  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `fb_canvas`  string | URL for the Facebook Canvas app  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `fb_gameroom`  string | URL for the app in Facebook Gameroom  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `google_play`  string | URL for the app in the Google Play store  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `instant_game`  string | URL for the Instant Game  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `itunes`  string | URL for the app in the iTunes store  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `itunes_ipad`  string | URL for the iPad app in the iTunes store  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `windows_10_store`  string | URL for the app in the Windows 10 store  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

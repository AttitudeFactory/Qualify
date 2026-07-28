Graph API Version

[v25.0](#)

# Has Lead Access

## Reading

API endpoint used to check that a user and/or app has the permissions needed to download leads. `leads_retrieval` permission is required to call this API.

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage_id%7D%3Ffields%3Dhas_lead_access.user_id%2528%257Buser_id%257D%2529&version=v25.0)

```
GET v25.0/{page_id}?fields=has_lead_access.user_id({user_id}) HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '{page_id}?fields=has_lead_access.user_id({user_id})',
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
    "{page_id}?fields=has_lead_access.user_id({user_id})",
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
    "{page_id}?fields=has_lead_access.user_id({user_id})",
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
                               initWithGraphPath:@"{page_id}?fields=has_lead_access.user_id({user_id})"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

Optionally, this endpoint can also be called with `app_id`.

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage_id%7D%3Ffields%3Dhas_lead_access.user_id%2528%257Buser_id%257D%2529.app_id%2528%257Bapp_id%257D%2529&version=v25.0)

```
GET v25.0/{page_id}?fields=has_lead_access.user_id({user_id}).app_id({app_id}) HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '{page_id}?fields=has_lead_access.user_id({user_id}).app_id({app_id})',
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
    "{page_id}?fields=has_lead_access.user_id({user_id}).app_id({app_id})",
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
    "{page_id}?fields=has_lead_access.user_id({user_id}).app_id({app_id})",
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
                               initWithGraphPath:@"{page_id}?fields=has_lead_access.user_id({user_id}).app_id({app_id})"
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
| `app_has_leads_permission`  bool | Whether or not the app has lead retrieval permission  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `can_access_lead`  bool | Is lead retrieval possible with the given parameters  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `enabled_lead_access_manager`  bool | Is Lead Access Manager enabled  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `failure_reason`  string | Why lead retrieval is not allowed  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `failure_resolution`  string | How to resolve the lead retrieval failure  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `is_page_admin`  bool | Is the user a page admin  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `page_id`  numeric string | The unique identifier of the page for which the permission/privacy status is being checked  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `user_has_leads_permission`  bool | Whether or not the user has lead permission on the page  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `user_id`  numeric string | The unique identifier of the Facebook user for which the permission/privacy status is being checked  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

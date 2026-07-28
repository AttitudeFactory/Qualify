Graph API Version

[v25.0](#)

# Graph API Reference [`/{app-id}`](/docs/graph-api/reference/app/)`/permissions`

The permissions that have been approved via login review.

[Learn more about Login Review](/docs/facebook-login/review)

## Reading

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=app%2Fpermissions&version=v25.0)

```
GET /v25.0/app/permissions HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/app/permissions',
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
    "/app/permissions",
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
    "/app/permissions",
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
                               initWithGraphPath:@"/app/permissions"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Permissions

* An app access token is required to retrieve permissions approved for that app.

### Fields

This edge returns a list of objects representing each permission that has been granted:

Name | Description | Type || `permission` | The name of the permission. | `string` |
| `status` | Indicates whether the permission is granted, or if it was declined by the user. | `enum{live}` |

## Publishing

You can't publish using this edge.

## Deleting

You can’t delete using this edge.

## Updating

You can't update using this edge.

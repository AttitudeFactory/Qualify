This document refers to a feature that was removed after [Graph API v3.2.](/docs/graph-api/reference/v3.2/user/friends)

Graph API Version

[v25.0](#)

# Graph API Reference [`/{user-id}`](/docs/graph-api/reference/user/)`/friends`

A person's friends.

## Reading

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=me%2Ffriends&version=v25.0)

```
GET /v25.0/me/friends HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/me/friends',
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
    "/me/friends",
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
    "/me/friends",
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
                               initWithGraphPath:@"/me/friends"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Permissions

* A user access token with `user_friends` permission is required to view the current person's friends.
* This will only return any friends who have used (via Facebook Login) the app making the request.
* If a friend of the person declines the `user_friends` permission, that friend will not show up in the friend list for this person.

### Modifiers

You can append another person's `id` to the edge in order to determine whether that person is friends with the root node user:

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK

```
GET /v25.0/{user-id-a}/friends/{user-id-b} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{user-id-a}/friends/{user-id-b}',
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
    "/{user-id-a}/friends/{user-id-b}",
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
    "/{user-id-a}/friends/{user-id-b}",
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
                               initWithGraphPath:@"/{user-id-a}/friends/{user-id-b}"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

If `user-a` is friends with `user-b` in the above request, the response will contain the [User object](/docs/graph-api/reference/user/) for `user-b`. If they are not friends, it will return an empty dataset.

### Fields

An array of [User objects](/docs/graph-api/reference/user/) representing the person's friends with this additional field:

| Name | Description | Type |
| --- | --- | --- |
| `summary` | An object containing summary info about this edge. | `object` |
| `total_count` | The total number of friends that this person has on Facebook. | `int` |

## Publishing

You can't publish using this edge.

## Deleting

You can't delete using this edge.

## Updating

You can't update using this edge.

Graph API Version

[v25.0](#)

# `/{object-id}/sharedposts`

This reference describes the `/sharedposts` edge that is common to multiple Graph API nodes. The structure and operations are the same for each node. The following objects have a `sharedposts` edge:

* PagePost
* Post
* User

## Reading

#### Permissions

* A user access token with `user_posts` permission, for someone who is able to view the post after privacy settings are taken into account. A post will be returned if either (a) the app created the post or (b) the creator of the post has granted `user_posts` permission to the app.

#### Feature Permissions

Name | Description || Page Public Content Access | This is a required [feature permission](https://developers.facebook.com/docs/apps/review/feature/#reference-PAGES_ACCESS). |

#### Limitations

* The `/{album-id}/sharedposts` is not available.
* The `GET /{photo-id}/sharedposts` endpoint is deprecated in v8.0+.

#### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bobject-id%7D%2Fsharedposts&version=v25.0)

```
GET /v25.0/{object-id}/sharedposts HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{object-id}/sharedposts',
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
    "/{object-id}/sharedposts",
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
    "/{object-id}/sharedposts",
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
                               initWithGraphPath:@"/{object-id}/sharedposts"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

#### Fields

A list of [Post objects](/docs/graph-api/reference/post) representing each of the shares.

## Publishing

You cannot publish shares of an object using the Graph API.

## Deleting

You cannot delete shares of an object using the Graph API.

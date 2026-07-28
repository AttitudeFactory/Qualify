Graph API Version

[v25.0](#)

# [`/{user-id}`](/docs/graph-api/reference/user/)`/taggable_friends`

This endpoint is deprecated.

A list of friends that can be tagged or mentioned in stories published to Facebook.

The places in which a tagging token returned by the `/me/taggable_friends` edge can be used include:

* [`/{user-id}/feed`](/docs/graph-api/reference/user/feed/#publish)
* [Open Graph story tagging](/docs/opengraph/using-actions/#people)
* [Open Graph story mentions](/docs/opengraph/using-actions/#mentions)

## Reading

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=me%2Ftaggable_friends&version=v25.0)

```
GET /v25.0/me/taggable_friends HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/me/taggable_friends',
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
    "/me/taggable_friends",
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
    "/me/taggable_friends",
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
                               initWithGraphPath:@"/me/taggable_friends"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Permissions

* A user access token with `user_friends` permission is required.
* Usage of the this edge [requires review of your app](/docs/apps/review) before it can be used by non-developers.

### Fields

A list of taggable friends:

Name | Description | Type || `id` | A tagging token which can only be used in order to tag this friend, and for no other purpose. This token should not be considered a stable ID, and cannot be used to identify the friend outside the context of tagging them in stories. | `string` |
| `name` | The friend's name. | `string` |
| `picture` | The friend's profile photo. | `object` |
| `url` | The URL of the profile photo. | `string` |
| `is_silhouette` | Indicates whether the profile photo is the default 'silhouette' picture, or has been replaced. | `bool` |
| `height` | Picture height in pixels. `height` and `width` are only returned when specified as modifiers. | `int` |
| `width` | Picture width in pixels. | `int` |

## Publishing

You can't publish using this edge.

## Deleting

You can't delete using this edge.

## Updating

You can't update using this edge.

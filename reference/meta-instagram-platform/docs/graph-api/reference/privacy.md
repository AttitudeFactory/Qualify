Graph API Version

[v25.0](#)

# Privacy

The Privacy node is returned as part of a number of different types of nodes as a `privacy` field. Examples include [posts](/docs/graph-api/reference/post), [photos](/docs/graph-api/reference/photo) and [videos](/docs/graph-api/reference/video).

## Reading

Privacy info of a shared object

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_Privacy%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_Privacy} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_Privacy}',
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
    "...?fields={fieldname_of_type_Privacy}",
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
    "...?fields={fieldname_of_type_Privacy}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_Privacy}"
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
| `allow`  token with structure: FriendList and User ID | The IDs of the specific users or friend lists that can see the object (as a comma-separated string).  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `deny`  token with structure: FriendList and User ID | The IDs of the specific users or friend lists that cannot see the object (as a comma-separate string).  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `description`  string | A description of the privacy settings. For custom settings, it can contain names of users, networks and friend lists.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `friends`  enum | Which category of users can see the object. This field is only set when the 'value' field is CUSTOM.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `networks`  string | The ID of the network that can see the object, or 1 for all of the user's networks.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `value`  enum | The privacy value for the object.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

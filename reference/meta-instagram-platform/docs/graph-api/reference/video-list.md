Graph API Version

[v25.0](#)

# Video List

## Reading

A playlist for videos

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Feature Permissions

| Name | Description |
| --- | --- |
| Page Public Content Access | This [feature permission](/docs/apps/review/feature/) may be required. |

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bvideo-list-id%7D&version=v25.0)

```
GET /v25.0/{video-list-id} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{video-list-id}',
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
    "/{video-list-id}",
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
    "/{video-list-id}",
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
                               initWithGraphPath:@"/{video-list-id}"
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
| `id`  numeric string | Video playlist ID  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `creation_time`  datetime | The time when the playlist was created |
| `description`  string | Description of the playlist |
| `last_modified`  datetime | The time when the contents of the playlist was last changed |
| `owner`  User|Page | Owner of the playlist |
| `season_number`  int32 | Number of Season which this episode belongs to |
| `thumbnail`  string | Thumbnail of the playlist |
| `title`  string | Title of the playlist  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `videos_count`  int32 | Number of Videos in the playlist |

### Edges

| Edge | Description |
| --- | --- |
| [`videos`](/docs/graph-api/reference/video-list/videos/)  Edge<Video> | Videos in the playlist |

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

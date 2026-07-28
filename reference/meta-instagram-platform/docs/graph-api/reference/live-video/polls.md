Graph API Version

[v25.0](#)

# Live Video Polls

Represents a collection of [VideoPolls](/docs/graph-api/reference/video-poll) on a [LiveVideo](/docs/graph-api/reference/live-video).

## Reading

Gets a list of [VideoPolls](/docs/graph-api/reference/video-poll) on a [LiveVideo](/docs/graph-api/reference/live-video).

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Blive-video-id%7D%2Fpolls&version=v25.0)

```
GET /v25.0/{live-video-id}/polls HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{live-video-id}/polls',
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
    "/{live-video-id}/polls",
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
    "/{live-video-id}/polls",
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
                               initWithGraphPath:@"/{live-video-id}/polls"
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

Reading from this edge will return a JSON formatted result:

```
{
    "data": []
}
```

#### `data`

A list of [VideoPoll](/docs/graph-api/reference/video-poll/) nodes.

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

## Creating

You can make a POST request to `polls` edge from the following paths:

* [`/{live_video_id}/polls`](/docs/graph-api/reference/live-video/polls/)

When posting to this edge, a [VideoPoll](/docs/graph-api/reference/video-poll/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `correct_option`  int64 | Number of the correct option (in order, starting from 1) |
| `options`  array<string> | Text options for users to select in order  Required |
| `question`  string | Question text  Required |
| `show_results`  boolean | True to show the results after voting, otherwise false |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

`option_ids`: List [

numeric string

],

}

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

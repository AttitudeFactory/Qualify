Graph API Version

[v25.0](#)

# Video Poll

## Reading

Embedded video poll

### Feature Permissions

| Name | Description |
| --- | --- |
| Live video API | This [feature permission](/docs/videos/live-video-api/) may be required. |

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bvideo-poll-id%7D&version=v25.0)

```
GET /v25.0/{video-poll-id} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{video-poll-id}',
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
    "/{video-poll-id}",
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
    "/{video-poll-id}",
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
                               initWithGraphPath:@"/{video-poll-id}"
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
| `id`  numeric string | The poll ID  [Core](https://developers.facebook.com/docs/apps/versions/#coreextended)[Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `question`  string | The poll question text |
| `show_results`  bool | True if this is a Live poll and voting is open and the results show after voting |
| `status`  enum {closed, voting\_open, results\_open} | Live poll status |

### Edges

| Edge | Description |
| --- | --- |
| [`poll_options`](/docs/graph-api/reference/video-poll/poll_options/)  Edge<VideoPollOption> | Options available on this poll |

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

You can update a [VideoPoll](/docs/graph-api/reference/video-poll/) by making a POST request to [`/{video_poll_id}`](/docs/graph-api/reference/video-poll/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `action`  enum {ATTACH\_TO\_VIDEO, CLOSE, SHOW\_VOTING, SHOW\_RESULTS, DELETE\_POLL} | Change state for the poll  Required |
| `show_results`  boolean | True if the viewer sees results after voting, false if they do not |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

## Deleting

You can't perform this operation on this endpoint.

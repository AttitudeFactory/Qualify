Graph API Version

[v25.0](#)

# Page Upcoming Change

## Reading

Notification of page upcoming changes.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-upcoming-change-id%7D&version=v25.0)

```
GET /v25.0/{page-upcoming-change-id} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-upcoming-change-id}',
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
    "/{page-upcoming-change-id}",
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
    "/{page-upcoming-change-id}",
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
                               initWithGraphPath:@"/{page-upcoming-change-id}"
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
| `id`  numeric string | The ID of the upcoming change |
| `change_type`  enum | The type of the upcoming change  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `effective_time`  datetime | The time when the upcoming change will become effective  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `page`  [Page](https://developers.facebook.com/docs/graph-api/reference/page/) | The associated page of this upcoming change  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `proposal`  [PageChangeProposal](https://developers.facebook.com/docs/graph-api/reference/page-change-proposal/) | The proposal associated with the change, only valid when change\_type is knowledge\_proposal  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `timer_status`  enum | The status of the timer associated with this change  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

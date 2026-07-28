Graph API Version

[v25.0](#)

# IGUser Insights

## Reading

Instagram user insights data

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Big-user-id%7D%2Finsights&version=v25.0)

```
GET /v25.0/{ig-user-id}/insights HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{ig-user-id}/insights',
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
    "/{ig-user-id}/insights",
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
    "/{ig-user-id}/insights",
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
                               initWithGraphPath:@"/{ig-user-id}/insights"
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

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `metric`  list<enum{reach, follower\_count, website\_clicks, profile\_views, online\_followers, accounts\_engaged, total\_interactions, likes, comments, shares, saves, replies, engaged\_audience\_demographics, reached\_audience\_demographics, follower\_demographics, follows\_and\_unfollows, profile\_links\_taps, views, threads\_likes, threads\_replies, reposts, quotes, threads\_followers, threads\_follower\_demographics, content\_views, threads\_views, threads\_clicks, threads\_reposts}> | The list of metrics that needs to be fetched  Required |
| `period`  list<enum{day, week, days\_28, month, lifetime, total\_over\_range}> | The aggregation period  Required |
| `since`  datetime/timestamp | Lower bound of the time range to consider |
| `until`  datetime | Upper bound of the time range to consider |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of InstagramInsightsResult nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 3006 | Not enough users |
| 80002 | There have been too many calls to this Instagram account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 190 | Invalid OAuth 2.0 Access Token |
| 200 | Permissions error |
| 102 | Session key invalid or no longer valid |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

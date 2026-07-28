Graph API Version

[v25.0](#)

# Ad Set Ads

## Reading

The ads under this ad set.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDKcURL[Graph API Explorer](/tools/explorer/?method=GET&path=%3CAD_SET_ID%3E%2Fads%3Ffields%3Dname%252Cid&version=v25.0)

```
GET /v25.0/<AD_SET_ID>/ads?fields=name%2Cid HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/<AD_SET_ID>/ads?fields=name%2Cid',
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
    "/<AD_SET_ID>/ads",
    {
        "fields": "name,id"
    },
    function (response) {
      if (response && !response.error) {
        /* handle the result */
      }
    }
);
```

```
Bundle params = new Bundle();
params.putString("fields", "name,id");
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/<AD_SET_ID>/ads",
    params,
    HttpMethod.GET,
    new GraphRequest.Callback() {
        public void onCompleted(GraphResponse response) {
            /* handle the result */
        }
    }
).executeAsync();
```

```
NSDictionary *params = @{
  @"fields": @"name,id",
};
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/<AD_SET_ID>/ads"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

```
curl -X GET -G \
  -d 'fields="name,id"' \
  -d 'access_token=<ACCESS_TOKEN>' \
  https://graph.facebook.com/v25.0/<AD_SET_ID>/ads
```

If you want to learn how to use the Graph API, read our [Using Graph API guide](/docs/graph-api/using-graph-api/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `date_preset`  enum{today, yesterday, this\_month, last\_month, this\_quarter, maximum, data\_maximum, last\_3d, last\_7d, last\_14d, last\_28d, last\_30d, last\_90d, last\_week\_mon\_sun, last\_week\_sun\_sat, last\_quarter, last\_year, this\_week\_mon\_today, this\_week\_sun\_today, this\_year} | Date ranges container for benchmarking comparison |
| `effective_status`  list<string> | Filter ads by effective status. When unset, defaults to not return deleted or archived ads. |
| `time_range`  {'since':YYYY-MM-DD,'until':YYYY-MM-DD} | Date range used to aggregate insights metrics |
| `since`  datetime | A date in the format of "YYYY-MM-DD", which means from the beginning midnight of that day. |
| `until`  datetime | A date in the format of "YYYY-MM-DD", which means to the beginning midnight of the following day. |
| `updated_since`  integer | filter by updated time |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {},
    "summary": {}
}
```

#### `data`

A list of [Ad](/docs/graph-api/reference/adgroup/) nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

#### `summary`

Aggregated information about the edge, such as counts. Specify the fields to fetch in the summary param (like `summary=insights`).

| Field | Description |
| --- | --- |
| `insights`  Edge<AdsInsights> | Analytics summary for all objects |
| `total_count`  unsigned int32 | Total number of objects  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 80004 | There have been too many calls to this ad-account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting#ads-management. |
| 200 | Permissions error |
| 190 | Invalid OAuth 2.0 Access Token |
| 2500 | Error parsing graph query |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

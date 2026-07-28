Graph API Version

[v25.0](#)

# Whats App Business Account Call Analytics

## Reading

Enables one to retrieve the call analytics data for this WhatsApp Business Account

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bwhats-app-business-account-id%7D%2Fcall_analytics&version=v25.0)

```
GET /v25.0/{whats-app-business-account-id}/call_analytics HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{whats-app-business-account-id}/call_analytics',
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
    "/{whats-app-business-account-id}/call_analytics",
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
    "/{whats-app-business-account-id}/call_analytics",
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
                               initWithGraphPath:@"/{whats-app-business-account-id}/call_analytics"
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
| `country_codes`  array<string> | Default value: `[]`  Country codes to receive analytics for |
| `dimensions`  array<enum {UNKNOWN, PHONE, COUNTRY, DIRECTION, TIER}> | Default value: `[]`  Dimensions to receive analytics for |
| `directions`  array<enum {UNKNOWN, BUSINESS\_INITIATED, USER\_INITIATED}> | Default value: `[]`  Call directions to receive analytics for |
| `end`  int64 | End time  Required |
| `granularity`  enum {HALF\_HOUR, DAILY, MONTHLY} | What granularity to receive analytics for  Required |
| `metric_types`  array<enum {UNKNOWN, COUNT, AVERAGE\_DURATION, COST}> | Default value: `[]`  Metric types to receive analytics for |
| `phone_numbers`  array<string> | Default value: `[]`  Phone numbers to receive analytics for |
| `start`  int64 | Start time  Required |
| `tiers`  array<string> | Default value: `[]`  tiers |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of WABACallAnalytics nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

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

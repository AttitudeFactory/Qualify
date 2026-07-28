Graph API Version

[v25.0](#)

# Offline Conversion Data Set Stats

## Reading

Graph API endpoint to get granular stats for a data set aggregated by event time or upload time

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Boffline-conversion-data-set-id%7D%2Fstats&version=v25.0)

```
GET /v25.0/{offline-conversion-data-set-id}/stats HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{offline-conversion-data-set-id}/stats',
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
    "/{offline-conversion-data-set-id}/stats",
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
    "/{offline-conversion-data-set-id}/stats",
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
                               initWithGraphPath:@"/{offline-conversion-data-set-id}/stats"
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
| `aggr_time`  enum{upload\_time, event\_time} | Default value: `event_time`  Metrics aggregated on event time or upload time |
| `end`  integer | Timestamp for range end |
| `granularity`  enum{daily, hourly, six\_hourly} | Default value: `daily`  Granularity of stats returned, either daily or hourly. Hourly granularity not supported for date ranges older than 30 days |
| `skip_empty_values`  boolean | Default value: `false`  Skip records if all numbers are empty |
| `start`  integer | Timestamp for range start |
| `user_timezone_id`  int64 | Timezone ID to convert data into, does not support date ranges older than 30 days. Supported timezones - https://developers.facebook.com/docs/marketing-api/reference/ad-account/timezone-ids/ |

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

A list of OfflineConversionDataSetStats nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

#### `summary`

Aggregated information about the edge, such as counts. Specify the fields to fetch in the summary param (like `summary=attribution_status`).

| Field | Description |
| --- | --- |
| `attribution_status`  enum | Status of attribution over the specified time period. Possible values are no\_attribution, low\_attribution and fine\_attribution  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `count`  integer | Number of events in the specified time period  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `match_rate_approx`  int32 | Approximate match rate percentage for all events in the specified time period  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `usd_amount`  integer | Sum of USD(in cents) of all events in the specified time period  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

### Error Codes

| Error | Description |
| --- | --- |
| 21019 | Offline Conversions API requests are deprecated from v20 onwards. Please use Conversions API for offline signals. v19 is the latest version that supports this Offline Conversions API endpoint and can be used until v19 is deprecated |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

Graph API Version

[v25.0](#)

# Threat Exchange Impact Report

## Reading

Represents a report of a partner of on-platform impact as a result of shared ThreatExchange data, which covers a specific time range on a single collaboration.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bthreat-exchange-impact-report-id%7D&version=v25.0)

```
GET /v25.0/{threat-exchange-impact-report-id} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{threat-exchange-impact-report-id}',
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
    "/{threat-exchange-impact-report-id}",
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
    "/{threat-exchange-impact-report-id}",
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
                               initWithGraphPath:@"/{threat-exchange-impact-report-id}"
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
| `id`  numeric string | The id of the object |
| `creation_time`  datetime | Creation time provided by storage |
| `impact`  list<ThreatExchangeImpactReportItem> | The outcomes on the owner's platform as a result of signals shared in this PrivacyGroup.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `notes`  string | free form notes about the report |
| `num_actionable`  unsigned integer | how much of the reviewed content was actionable. Must be <= reviewed |
| `num_already_actioned`  unsigned integer | how much of the matched content was review. Must be <= matched |
| `num_downloaded`  unsigned integer | the number of signals downloaded for this evaluation |
| `num_matched`  unsigned integer | the number of content (or signals) matched. |
| `num_reviewed`  unsigned integer | how much of the matched content was review. Must be <= matched |
| `report_range_end`  datetime | the end range of the report. Defaults to report time  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `report_range_start`  datetime | the optional starting time range of the report  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `signal_types`  list<enum> | If set, indicates that only these signal types were evaluated |
| `update_time`  datetime | Update time provided by storage |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can update a [ThreatExchangeImpactReport](/docs/graph-api/reference/threat-exchange-impact-report/) by making a POST request to [`/{threat_exchange_impact_report_id}`](/docs/graph-api/reference/threat-exchange-impact-report/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `impact`  array<JSON object> | The outcomes on the owner's platform as a result of signals shared in this PrivacyGroup. |
| `report_end_time`  int64 | the end range of the report. Defaults to creation time. |
| `report_start_time`  int64 | the optional starting time range of the report. Defaults to 6 months before now. |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`success`: bool,

}

## Deleting

You can delete a [ThreatExchangeImpactReport](/docs/graph-api/reference/threat-exchange-impact-report/) by making a DELETE request to [`/{threat_exchange_impact_report_id}`](/docs/graph-api/reference/threat-exchange-impact-report/).

### Parameters

This endpoint doesn't have any parameters.

### Return Type

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

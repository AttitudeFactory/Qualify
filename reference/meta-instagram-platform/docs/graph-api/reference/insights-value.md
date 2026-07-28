Graph API Version

[v25.0](#)

# Insights Value

## Reading

The value for one insights metric given a timestamp

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_InsightsValue%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_InsightsValue} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_InsightsValue}',
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
    "...?fields={fieldname_of_type_InsightsValue}",
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
    "...?fields={fieldname_of_type_InsightsValue}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_InsightsValue}"
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
| `campaign_id`  string | campaign\_id  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `earning_source`  string | earning\_source  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `end_time`  datetime | The time from which the data are aggregated  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `engagement_source`  string | engagement\_source  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `message_type`  string | message\_type  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `messaging_channel`  string | messaging\_channel  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `monetization_tool`  string | monetization\_tool  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `recurring_notifications_entry_point`  string | recurring\_notifications\_entry\_point  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `recurring_notifications_frequency`  string | recurring\_notifications\_frequency  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `recurring_notifications_topic`  string | recurring\_notifications\_topic  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `start_time`  datetime | The start time which the data are aggregated  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `value`  (integer) or (map) or (float) | The value of the aggregated data  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

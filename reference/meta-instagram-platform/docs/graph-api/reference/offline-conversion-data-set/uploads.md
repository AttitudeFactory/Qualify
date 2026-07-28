Graph API Version

[v25.0](#)

# Offline Conversion Data Set Uploads

## Reading

The endpoint which loads all the offline conversion data set uploads from this specific offline conversion data set.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Boffline-conversion-data-set-id%7D%2Fuploads&version=v25.0)

```
GET /v25.0/{offline-conversion-data-set-id}/uploads HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{offline-conversion-data-set-id}/uploads',
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
    "/{offline-conversion-data-set-id}/uploads",
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
    "/{offline-conversion-data-set-id}/uploads",
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
                               initWithGraphPath:@"/{offline-conversion-data-set-id}/uploads"
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
| `end_time`  datetime/timestamp | End of the creation time of the requested upload |
| `order`  enum {ASCENDING, DESCENDING} | Default value: `"DESCENDING"`  The order of the sorted requested uploads |
| `sort_by`  enum {CREATION\_TIME, FIRST\_UPLOAD\_TIME, LAST\_UPLOAD\_TIME, API\_CALLS, EVENT\_TIME\_MIN, EVENT\_TIME\_MAX, IS\_EXCLUDED\_FOR\_LIFT} | Default value: `"LAST_UPLOAD_TIME"`  The field which the requested uploads are sorted by |
| `start_time`  datetime/timestamp | Start of the creation time of the requested upload |
| `upload_tag`  string | Upload tag for the required upload |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of [OfflineConversionDataSetUpload](/docs/graph-api/reference/offline-conversion-data-set-upload/) nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 2635 | You are calling a deprecated version of the Ads API. Please update to the latest version. |
| 100 | Invalid parameter |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

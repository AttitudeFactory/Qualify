Graph API Version

[v25.0](#)

# Application Mobile Sdk Gk

## Reading

ApplicationMobileSdkGk

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bapplication-id%7D%2Fmobile_sdk_gk&version=v25.0)

```
GET /v25.0/{application-id}/mobile_sdk_gk HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{application-id}/mobile_sdk_gk',
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
    "/{application-id}/mobile_sdk_gk",
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
    "/{application-id}/mobile_sdk_gk",
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
                               initWithGraphPath:@"/{application-id}/mobile_sdk_gk"
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
| `device_id`  string | Device ID |
| `extinfo`  Object | Extra Information |
| `0`  string | extinfo version  Required |
| `1`  string | app package name |
| `2`  string | short version (int or string) |
| `3`  string | long version |
| `4`  string | OS version |
| `5`  string | device model name |
| `6`  string | locale |
| `7`  string | timezone abbreviation |
| `8`  string | carrier |
| `9`  int64 | screen width |
| `10`  int64 | screen height |
| `11`  string | screen density (float decimal , or .) |
| `12`  int64 | CPU cores |
| `13`  int64 | external storage size in GB |
| `14`  int64 | free space on external storage in GB |
| `15`  string | device timezone |
| `platform`  enum {ANDROID, IOS} | SDK Platform  Required |
| `sdk_version`  string | SDK version  Required |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of MobileSdkGk nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 200 | Permissions error |
| 190 | Invalid OAuth 2.0 Access Token |
| 2500 | Error parsing graph query |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

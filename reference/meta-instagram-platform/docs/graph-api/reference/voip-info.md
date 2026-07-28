Graph API Version

[v25.0](#)

# VOIP Info

Information about a person's VOIP status

## Reading

Voip info

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_VoipInfo%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_VoipInfo} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_VoipInfo}',
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
    "...?fields={fieldname_of_type_VoipInfo}",
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
    "...?fields={fieldname_of_type_VoipInfo}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_VoipInfo}"
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
| `has_mobile_app`  bool | Does this user have a pushable mobile app install?  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `has_permission`  bool | Does the viewer have permission to call?  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `is_callable`  bool | Is this user currently callable via mobile?  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `is_callable_webrtc`  bool | Is this user currently callable via dekstop?  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `is_pushable`  bool | Does this user have an unmuted push token?  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `reason_code`  unsigned int32 | Reason code if not callable  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `reason_description`  string | Reason description if not callable  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

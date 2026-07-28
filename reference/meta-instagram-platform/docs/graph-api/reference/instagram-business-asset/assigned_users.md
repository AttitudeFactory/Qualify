Graph API Version

[v25.0](#)

# Instagram Business Asset Assigned Users

## Reading

Get a list of business users and their permissions tasks for this Instagram Business Asset

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Binstagram-business-asset-id%7D%2Fassigned_users&version=v25.0)

```
GET /v25.0/{instagram-business-asset-id}/assigned_users HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{instagram-business-asset-id}/assigned_users',
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
    "/{instagram-business-asset-id}/assigned_users",
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
    "/{instagram-business-asset-id}/assigned_users",
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
                               initWithGraphPath:@"/{instagram-business-asset-id}/assigned_users"
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
| `business`  numeric string | business  Required |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of AssignedUser nodes.

The following fields will be added to each node that is returned:

| Field | Description |
| --- | --- |
| `tasks`  list<string> | tasks  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can update an [AssignedUser](/docs/graph-api/reference/assigned-user/) by making a POST request to [`/{instagram_business_asset_id}/assigned_users`](/docs/graph-api/reference/instagram-business-asset/assigned_users/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `tasks`  array<enum {CONTENT, MESSAGES, COMMUNITY\_ACTIVITY, ADVERTISE, ANALYZE}> | Instagram Business Asset tasks to assign to user |
| `user`  UID | Business user  Required |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

## Deleting

You can dissociate an [AssignedUser](/docs/graph-api/reference/assigned-user/) from an [InstagramBusinessAsset](/docs/graph-api/reference/instagram-business-asset/) by making a DELETE request to [`/{instagram_business_asset_id}/assigned_users`](/docs/graph-api/reference/instagram-business-asset/assigned_users/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `user`  UID | user  Required |

### Return Type

Struct {

`success`: bool,

}

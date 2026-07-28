Graph API Version

[v25.0](#)

# IGUser Branded Content Ad Permissions

## Reading

ShadowIGUserBrandedContentAdPermissions

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Big-user-id%7D%2Fbranded_content_ad_permissions&version=v25.0)

```
GET /v25.0/{ig-user-id}/branded_content_ad_permissions HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{ig-user-id}/branded_content_ad_permissions',
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
    "/{ig-user-id}/branded_content_ad_permissions",
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
    "/{ig-user-id}/branded_content_ad_permissions",
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
                               initWithGraphPath:@"/{ig-user-id}/branded_content_ad_permissions"
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
| `creator_username`  string | FIlter for specific creator username |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of IGBCAdsPermission nodes.

The following fields will be added to each node that is returned:

| Field | Description |
| --- | --- |
| `brand_ig_id`  integer | brand\_ig\_id  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `brand_username`  string | brand\_username  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `creator_fb_page_id`  numeric string | creator\_fb\_page\_id  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `creator_ig_id`  integer | creator\_ig\_id  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `creator_username`  string | creator\_username  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `permission_created_time`  integer | permission\_created\_time |
| `permission_status`  string | permission\_status  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `permission_url`  string | permission\_url  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 80002 | There have been too many calls to this Instagram account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 190 | Invalid OAuth 2.0 Access Token |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

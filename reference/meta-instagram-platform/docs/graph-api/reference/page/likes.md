Graph API Version

[v25.0](#)

# Page Likes

This endpoint is not supported for Pages that have been migrated to the [New Pages Experience](https://developers.facebook.com/docs/pages/new-pages-experience).

## Reading

PageLikes

### Requirements

For Pages you own or for which you can perform the `MODERATE` task, you will need:

* A Page access token
* The [`pages_manage_instant_article` permission](/docs/permission/reference/pages_manage_instant_article)

For Page you do not own or which you can not perform the `MODERATE` task, you will need:

* The Page Public Content Access feature

When using the Page Public Content Access feature, use a [system user access token](https://www.facebook.com/business/help/503306463479099) to avoid [rate limiting](/docs/graph-api/overview/rate-limiting#pages) issues.

### Feature Permissions

| Name | Description |
| --- | --- |
| Page Public Content Access | This [feature permission](/docs/apps/review/feature/) may be required. |

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-id%7D%2Flikes&version=v25.0)

```
GET /v25.0/{page-id}/likes HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/likes',
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
    "/{page-id}/likes",
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
    "/{page-id}/likes",
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
                               initWithGraphPath:@"/{page-id}/likes"
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
| `target_id`  numeric string | target\_id |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of [Page](/docs/graph-api/reference/page/) nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 100 | Invalid parameter |
| 190 | Invalid OAuth 2.0 Access Token |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

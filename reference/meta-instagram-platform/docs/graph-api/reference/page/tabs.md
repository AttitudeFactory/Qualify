Graph API Version

[v25.0](#)

# Page Tabs

This endpoint is not supported for Pages that have been migrated to the [New Pages Experience](https://developers.facebook.com/docs/pages/new-pages-experience).

This edge allows you get Page Tabs.

## Reading

Get a list of [Tab](/docs/graph-api/reference/tab/) nodes on a [Page](/docs/graph-api/reference/page/).

### Requirements

You will need the following:

* A Page access token requested by a person who can perform the `MANAGE` task on the Page.
* The [`pages_manage_metadata` permission](https://developers.facebook.com/docs/permissions/reference/pages_manage_metadata)

If a person is not able to perform the task on the Page, you will need the following:

* The Pages Public Content Access feature

When using the Page Public Content Access feature, use a [system user access token](https://www.facebook.com/business/help/503306463479099) to avoid [rate limiting](/docs/graph-api/overview/rate-limiting#pages) issues.

### Limitations

* To ensure tabs lead to high-quality, accurate content, the Page Tabs feature is only available to Pages with 2000 or more likes.

### Feature Permissions

| Name | Description |
| --- | --- |
| Page Public Content Access | This [feature permission](/docs/apps/review/feature/) may be required. |

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-id%7D%2Ftabs&version=v25.0)

```
GET /v25.0/{page-id}/tabs HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/tabs',
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
    "/{page-id}/tabs",
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
    "/{page-id}/tabs",
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
                               initWithGraphPath:@"/{page-id}/tabs"
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
| `tab`  list<string> | SELF\_EXPLANATORY |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of [Tab](/docs/graph-api/reference/tab/) nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 190 | Invalid OAuth 2.0 Access Token |
| 104 | Incorrect signature |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

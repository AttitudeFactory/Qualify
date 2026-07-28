Graph API Version

[v25.0](#)

# Page Roles

## Reading

People who have a role on a Page

### Limitations

* This edge only returns people who do not belong to a business. To find business users, query the [Page Assigned Users edge](https://developers.facebook.com/docs/graph-api/reference/page/assigned_users).

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDKcURL[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-id%7D%2Froles&version=v25.0)

```
GET /v25.0/{page-id}/roles HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/roles',
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
    "/{page-id}/roles",
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
    "/{page-id}/roles",
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
                               initWithGraphPath:@"/{page-id}/roles"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

```
curl -X GET -G \
  -d 'access_token=<ACCESS_TOKEN>' \
  https://graph.facebook.com/v25.0/{page-id}/roles
```

If you want to learn how to use the Graph API, read our [Using Graph API guide](/docs/graph-api/using-graph-api/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `include_deactivated`  boolean | Default value: `false`  Include deactivated accounts in the results |
| `uid`  UID | ID of a person who has a role on the Page |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of [User](/docs/graph-api/reference/user/) nodes.

The following fields will be added to each node that is returned:

| Field | Description |
| --- | --- |
| `is_active`  bool | If the account is active  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `tasks`  list<enum> | Tasks for this person. Can choose from `MANAGE`, `CREATE_CONTENT`, `MODERATE`, `ADVERTISE` and `ANALYZE`  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 100 | Invalid parameter |
| 104 | Incorrect signature |
| 190 | Invalid OAuth 2.0 Access Token |
| 283 | That action requires the extended permission pages\_read\_engagement and/or pages\_read\_user\_content and/or pages\_manage\_ads and/or pages\_manage\_metadata |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

Graph API Version

[v25.0](#)

# Offline Conversion Data Set Agencies

## Reading

Shows all partner businesses the offline event set is shared to

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Boffline-conversion-data-set-id%7D%2Fagencies&version=v25.0)

```
GET /v25.0/{offline-conversion-data-set-id}/agencies HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{offline-conversion-data-set-id}/agencies',
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
    "/{offline-conversion-data-set-id}/agencies",
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
    "/{offline-conversion-data-set-id}/agencies",
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
                               initWithGraphPath:@"/{offline-conversion-data-set-id}/agencies"
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

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {},
    "summary": {}
}
```

#### `data`

A list of [Business](/docs/marketing-api/reference/business/) nodes.

The following fields will be added to each node that is returned:

| Field | Description |
| --- | --- |
| `permitted_roles`  list<string> | Roles that are assignable to users on this asset |

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

#### `summary`

Aggregated information about the edge, such as counts. Specify the fields to fetch in the summary param (like `summary=total_count`).

| Field | Description |
| --- | --- |
| `total_count`  int32 | Total number of objects on this edge  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

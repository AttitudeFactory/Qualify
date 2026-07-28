Graph API Version

[v25.0](#)

# Entity At Text Range

## Reading

Location and identity of an object in some source text

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_EntityAtTextRange%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_EntityAtTextRange} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_EntityAtTextRange}',
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
    "...?fields={fieldname_of_type_EntityAtTextRange}",
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
    "...?fields={fieldname_of_type_EntityAtTextRange}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_EntityAtTextRange}"
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
| `id`  numeric string | ID of the profile  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `length`  unsigned int32 | Number of characters in the text indicating the object  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `name`  string | Name of the object  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `object`  [Profile](https://developers.facebook.com/docs/graph-api/reference/profile/) | The object itself |
| `offset`  unsigned int32 | The character offset in the source text of the text indicating the object  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `type`  enum {user, page, event, group, application} | Type of the object  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

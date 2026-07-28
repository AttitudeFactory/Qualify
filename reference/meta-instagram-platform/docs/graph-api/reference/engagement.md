Graph API Version

[v25.0](#)

# Engagement

This is an API that can deliver the same data as what's used to render social information contained in a like button

## Reading

The social sentence and like count used to render the like plugin

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_Engagement%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_Engagement} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_Engagement}',
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
    "...?fields={fieldname_of_type_Engagement}",
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
    "...?fields={fieldname_of_type_Engagement}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_Engagement}"
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
| `count`  unsigned int32 | Number of people who like this  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `count_string`  string | Abbreviated string representation of count |
| `count_string_with_like`  string | Abbreviated string representation of count if the viewer likes the object |
| `count_string_without_like`  string | Abbreviated string representation of count if the viewer does not like the object |
| `social_sentence`  string | Text that the like button would currently display  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `social_sentence_with_like`  string | Text that the like button would display if the viewer likes the object |
| `social_sentence_without_like`  string | Text that the like button would display if the viewer does not like the object |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

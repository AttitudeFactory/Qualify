Graph API Version

[v25.0](#)

# Branded Content Search

## Reading

BrandedContentSearch

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_BrandedContentSearch%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_BrandedContentSearch} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_BrandedContentSearch}',
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
    "...?fields={fieldname_of_type_BrandedContentSearch}",
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
    "...?fields={fieldname_of_type_BrandedContentSearch}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_BrandedContentSearch}"
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
| `creation_date`  string | The UTC date and time when the Facebook Page or Instagram account posted the branded content.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `creator`  [BrandedContentSearchEntity](https://developers.facebook.com/docs/graph-api/reference/branded-content-search-entity/) | The name of the person, business or entity that posted the branded content. |
| `partners`  [list<BrandedContentSearchEntity>](https://developers.facebook.com/docs/graph-api/reference/branded-content-search-entity/) | The name of the person, business or entity that gave something of value to the creator of the branded content. |
| `type`  enum | The type or format of branded content. Types include a Facebook post, an Instagram post, an Instagram story or an Instagram reel.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `url`  string | String with URL link that displays the branded content.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

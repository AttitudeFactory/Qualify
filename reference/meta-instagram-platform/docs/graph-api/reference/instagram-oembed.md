Graph API Version

[v25.0](#)

# Instagram Oembed

## Reading

InstagramOembed

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=instagram_oembed&version=v25.0)

```
GET /v25.0/instagram_oembed HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/instagram_oembed',
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
    "/instagram_oembed",
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
    "/instagram_oembed",
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
                               initWithGraphPath:@"/instagram_oembed"
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
| `hidecaption`  boolean | If set to true, the embed code hides the caption. Defaults to false if parameter is not included in request. |
| `maxwidth`  int64 | Maximum width of returned media. Must be between 320 and 658. Note that the maxheight parameter is not supported. This is because the embed code is responsive and its height varies depending on its width and length of the caption. |
| `omitscript`  boolean | If set to true, the returned embed HTML code will not include any javascript. |
| `url`  URI | The post's URL.  Required |

### Fields

| Field | Description |
| --- | --- |
| `html`  string | The HTML used to display the post.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `provider_name`  string | Name of the provider (Instagram)  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `provider_url`  string | URL of the provider (Instagram)  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `type`  string | The oEmbed resource type. See https://oembed.com/.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `version`  string | Always 1.0. See https://oembed.com/  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `width`  int32 | The width in pixels required to display the HTML.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 100 | Invalid parameter |
| 190 | Invalid OAuth 2.0 Access Token |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

Graph API Version

[v25.0](#)

# Oembed Page

## Reading

OembedPage

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=oembed_page&version=v25.0)

```
GET /v25.0/oembed_page HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/oembed_page',
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
    "/oembed_page",
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
    "/oembed_page",
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
                               initWithGraphPath:@"/oembed_page"
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
| `adapt_container_width`  boolean | Default value: `true`  Try to fit inside the container width. |
| `hide_cover`  boolean | Default value: `false`  Hide cover photo in the header. |
| `maxheight`  int64 | Maximum height of returned media. |
| `maxwidth`  int64 | Maximum width of returned media. |
| `omitscript`  boolean | Default value: `false`  If set to true, the returned embed HTML code will not include any javascript. |
| `sdklocale`  string | sdklocale |
| `show_facepile`  boolean | Default value: `true`  Show profile photos when friends like this. |
| `show_posts`  boolean | Default value: `true`  show\_posts |
| `small_header`  boolean | Default value: `false`  Use the small header instead. |
| `url`  URI | The page's url.  Required |

### Fields

| Field | Description |
| --- | --- |
| `height`  int32 | The height in pixels required to display the HTML.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `html`  string | The HTML used to display the page.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `provider_name`  string | Name of the provider (Facebook)  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `provider_url`  string | URL of the provider (Facebook)  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `type`  string | The oEmbed resource type. See https://oembed.com/.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `version`  string | Always 1.0. See https://oembed.com/  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `width`  int32 | The width in pixels required to display the HTML.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 100 | Invalid parameter |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

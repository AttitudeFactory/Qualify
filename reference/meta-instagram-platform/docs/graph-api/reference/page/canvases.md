Graph API Version

[v25.0](#)

# Page Canvases

Represents a list of [canvas nodes](/docs/graph-api/reference/canvas/) of a Facebook Page.

## Reading

Return Instant Experiences for the page

### Requirements

To publish canvases on a Page, you need:

* A [Page access token](/docs/facebook-login/access-tokens#pagetokens)
* [`pages_show_list`](docs/permissions/reference/pages_show_list),
  [`pages_manage_posts`](docs/permissions/reference/pages_manage_posts), and
  [`pages_read_user_content`](docs/permissions/reference/pages_read_user_content) permissions

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-id%7D%2Fcanvases&version=v25.0)

```
GET /v25.0/{page-id}/canvases HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/canvases',
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
    "/{page-id}/canvases",
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
    "/{page-id}/canvases",
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
                               initWithGraphPath:@"/{page-id}/canvases"
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
| `is_hidden`  boolean | Used for query hidden or not hidden Instant Experiences |
| `is_published`  boolean | Used for query published or unpublished Instant Experiences |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of [Canvas](/docs/graph-api/reference/canvas/) nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 200 | Permissions error |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 190 | Invalid OAuth 2.0 Access Token |
| 104 | Incorrect signature |
| 283 | That action requires the extended permission pages\_read\_engagement and/or pages\_read\_user\_content and/or pages\_manage\_ads and/or pages\_manage\_metadata |

## Creating

### Requirements

To publish canvases on a Page, you need:

* A [Page access token](/docs/facebook-login/access-tokens#pagetokens)
* [`pages_show_list`](docs/permissions/reference/pages_show_list),
  [`pages_manage_posts`](docs/permissions/reference/pages_manage_posts), and
  [`pages_read_user_content`](docs/permissions/reference/pages_read_user_content) permissions

You can make a POST request to `canvases` edge from the following paths:

* [`/{page_id}/canvases`](/docs/graph-api/reference/page/canvases/)

When posting to this edge, a [Canvas](/docs/graph-api/reference/canvas/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `background_color`  string | Default value: `FFFFFFFF`  Background color of the canvas |
| `body_element_ids`  list<numeric string or integer> | A list of all canvas element ids inside this canvas |
| `enable_swipe_to_open`  boolean | Default value: `false`  Field used to mark if swipe to open is enabled |
| `hero_asset_facebook_post_id`  numeric string or integer | hero\_asset\_facebook\_post\_id |
| `hero_asset_instagram_media_id`  numeric string or integer | hero\_asset\_instagram\_media\_id |
| `is_hidden`  boolean | Field used to mark if the canvas is visible or not |
| `is_published`  boolean | Default value: `false`  Field used to mark the publish state of the canvas |
| `name`  string | Default value: `Untitled Canvas`  Field used to label docs by the editor tool |
| `source_template_id`  numeric string or integer | ID of EntRichMediaDocumentTemplate that the Canvas document is created from |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 105 | The number of parameters exceeded the maximum for this operation |
| 100 | Invalid parameter |
| 200 | Permissions error |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

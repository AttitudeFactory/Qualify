Graph API Version

[v25.0](#)

# Canvas

## Reading

A canvas document

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bcanvas-id%7D&version=v25.0)

```
GET /v25.0/{canvas-id} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{canvas-id}',
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
    "/{canvas-id}",
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
    "/{canvas-id}",
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
                               initWithGraphPath:@"/{canvas-id}"
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
| `id`  numeric string | ID of the canvas |
| `background_color`  string | Background color of the canvas |
| `body_elements`  list<CanvasPhoto|CanvasHeader|CanvasVideo|CanvasText|CanvasCarousel|CanvasButton|CanvasFooter|CanvasStoreLocator|CanvasProductList|CanvasProductSet> | Body element nodes for the canvas |
| `business_id`  numeric string | The business id for the canvas product set element |
| `canvas_link`  string | The canvas link for the canvas |
| `collection_hero_image`  [Photo](https://developers.facebook.com/docs/graph-api/reference/photo/) | First element as photo inside canvas to use as hero media for canvas collection |
| `collection_thumbnails`  list<CanvasCollectionThumbnail> | Canvas elements that can be used as thumbnails for canvas collections |
| `element_payload`  string | Payload that contains all element |
| `fb_body_elements`  list<CanvasPhoto|CanvasHeader|CanvasVideo|CanvasText|CanvasCarousel|CanvasButton|CanvasFooter|CanvasStoreLocator|CanvasProductList|CanvasProductSet|CanvasDynamicProductSet|CanvasTemplateVideo|CanvasDynamicPhoto> | Body element nodes for the canvas, used by FB internal apps and includes elements who's API is not public yet |
| `is_hidden`  bool | The canvas is hidden or not |
| `is_published`  bool | Publish status of the canvas |
| `last_editor`  [User](https://developers.facebook.com/docs/graph-api/reference/user/) | User who last edited this canvas |
| `linked_documents`  [list<Canvas>](https://developers.facebook.com/docs/graph-api/reference/canvas/) | The canvas documents that are reachable via buttons/links in this document |
| `name`  string | Name used to label the canvas  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `owner`  [Page](https://developers.facebook.com/docs/graph-api/reference/page/) | Page that owns this canvas |
| `property_list`  list<string> | List of properties for this canvas |
| `store_url`  string | The associated app store URL for the canvas |
| `style_list`  list<enum> | Canvas level style attributes |
| `tags`  list<string> | Tags associated with Canvas |
| `ui_property_list`  list<string> | List of UI properties to set when viewing this canvas from creation tools |
| `unused_body_elements`  list<CanvasPhoto|CanvasHeader|CanvasVideo|CanvasText|CanvasCarousel|CanvasButton|CanvasFooter|CanvasStoreLocator|CanvasProductList|CanvasProductSet> | Body element nodes that belong to the canvas but are not used |
| `update_time`  int32 | Last updated time of the canvas |
| `use_retailer_item_ids`  bool | HACK: Flag for whether or not the ad creative that uses this Canvas should use retailer\_item\_ids or not |

### Edges

| Edge | Description |
| --- | --- |
| [`preview`](/docs/graph-api/reference/canvas/preview/)  Edge<CanvasPreview> | Get preview HTML embed element |
| [`previews`](/docs/graph-api/reference/canvas/previews/)  Edge<TextWithEntities> | Get preview notifications for the canvas |

### Error Codes

| Error | Description |
| --- | --- |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 100 | Invalid parameter |

## Creating

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

You can update a [Canvas](/docs/graph-api/reference/canvas/) by making a POST request to [`/{canvas_id}`](/docs/graph-api/reference/canvas/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `background_color`  string | Background color of the canvas |
| `body_element_ids`  list<numeric string or integer> | A list of canvas element ids |
| `enable_swipe_to_open`  boolean | Field used to mark if swipe to open is enabled |
| `hero_asset_facebook_post_id`  numeric string or integer | hero\_asset\_facebook\_post\_id |
| `hero_asset_instagram_media_id`  numeric string or integer | hero\_asset\_instagram\_media\_id |
| `is_hidden`  boolean | Field used to hide a (published) canvas |
| `is_published`  boolean | Field used to mark the publish state of the canvas |
| `name`  string | Field used to label the canvas |
| `source_template_id`  numeric string or integer | ID of EntRichMediaDocumentTemplate that the Canvas document is created from |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |

## Deleting

You can't perform this operation on this endpoint.

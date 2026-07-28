Graph API Version

[v25.0](#)

# Page Canvas Elements

## Reading

PageCanvasElements

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-id%7D%2Fcanvas_elements&version=v25.0)

```
GET /v25.0/{page-id}/canvas_elements HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/canvas_elements',
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
    "/{page-id}/canvas_elements",
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
    "/{page-id}/canvas_elements",
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
                               initWithGraphPath:@"/{page-id}/canvas_elements"
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
    "data": []
}
```

#### `data`

A list of [CanvasBodyElement](/docs/graph-api/reference/canvas-body-element/) nodes.

### Error Codes

| Error | Description |
| --- | --- |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |

## Creating

You can make a POST request to `canvas_elements` edge from the following paths:

* [`/{page_id}/canvas_elements`](/docs/graph-api/reference/page/canvas_elements/)

When posting to this edge, a [CanvasBodyElement](/docs/graph-api/reference/canvas-body-element/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `canvas_button`  Object | Create a canvas button that belongs to a page |
| `name`  string | Default value: `Button`  Name of the button |
| `button_color`  string | Default value: `FF000000`  The color of the button |
| `rich_text`  Object | The text inside the button  Required |
| `button_style`  enum {BUTTON\_OUTLINE, BUTTON\_FILLED} | Default value: `BUTTON_OUTLINE`  The style of the button |
| `open_url_action`  Object | the destination url after user clicks the button, by setting this, the canvas button will have action with OPEN URL type |
| `text_alignment`  enum {LEFT, CENTER, RIGHT} | Default value: `CENTER`  The alignment of the text on the button |
| `text_color`  string | Default value: `FF777777`  The color of the text on the button |
| `font_size`  int64 | Default value: `15`  The size of the font for the text on the button |
| `font_family`  string | Default value: `sans-serif`  The font family of the text on the button |
| `line_height`  float | Default value: `1`  The line height of the text on the button |
| `top_padding`  float | Default value: `0`  The padding above the button |
| `deep_link`  string | Deep link destination only for mobile apps (used for mobile install or engagement ads and app link is supported) |
| `bottom_padding`  float | Default value: `0`  The padding below the button |
| `background_color`  string | Default value: `FFFFFFFF`  Background color of the button |
| `canvas_carousel`  Object | Create a canvas carousel that belongs to a page |
| `name`  string | Default value: `Carousel`  Name of the carousel element |
| `child_elements`  list<id> | The child elements of the carousel. Typically, they are canvas photo elements  Required |
| `style`  enum {FIT\_TO\_WIDTH, FIT\_TO\_HEIGHT} | Default value: `FIT_TO_WIDTH`  The presentation style of the carousel |
| `top_padding`  float | Default value: `0`  The padding above the carousel |
| `bottom_padding`  float | Default value: `0`  The padding below the carousel |
| `canvas_existing_post`  Object | canvas\_existing\_post |
| `source_instagram_media_id`  numeric string or integer |  |
| `source_facebook_post_id`  numeric string or integer |  |
| `canvas_footer`  Object | Create a canvas footer that belongs to a page |
| `name`  string | Default value: `Footer`  Name of the footer element |
| `child_elements`  list<id> | The child elements inside a footer, typically, it is a canvas button element.  Required |
| `background_color`  string | Default value: `FFFFFFFF`  Background color of the button |
| `canvas_header`  Object | Create a canvas header that belongs to a page |
| `name`  string | Default value: `"Header"`  Name of the header element |
| `child_elements`  array<numeric string> | The child elements (typically a photo) inside the header |
| `background_color`  string | The background color of the header |
| `canvas_lead_form`  Object | The id of corresponding published lead form |
| `leadgen_data_id`  leadgen\_data ID | Required |
| `name`  string | Default value: `"Lead Gen Form"` |
| `top_padding`  float | Default value: `0` |
| `bottom_padding`  float | Default value: `0` |
| `canvas_photo`  Object | Create a canvas photo that belongs to a page |
| `photo_id`  id | ID of Facebook photo used in the photo element |
| `photo_url`  URI |  |
| `open_url_action`  Object | The action associated with the photo |
| `deep_link`  string | Deep link destination only for mobile apps (used for mobile install or engagement ads and app link is supported) |
| `destination_set_id`  id |  |
| `style`  enum {FIT\_TO\_WIDTH, FIT\_TO\_WIDTH\_EXPANDABLE, FIT\_TO\_HEIGHT} | The presentation style of the photo |
| `name`  string | Default value: `Photo`  Name of the photo element |
| `top_padding`  float | Default value: `0`  The padding above the photo element |
| `bottom_padding`  float | Default value: `0`  The padding below the photo element |
| `product_tags`  list<Object> |  |
| `product_id`  numeric string or integer | Required |
| `coordinates`  list<float> |  |
| `hide_product_prices`  boolean |  |
| `canvas_product_list`  Object | Creat a canvas product list that belongs to a page |
| `name`  string | Default value: `Product` |
| `product_id_list`  list<int64> |  |
| `top_padding`  float | Default value: `0` |
| `bottom_padding`  float | Default value: `0` |
| `item_headline`  string | Default value: |
| `item_description`  string | Default value: |
| `canvas_product_set`  Object | Creat a canvas product set that belongs to a page |
| `name`  string | Default value: `Product`  Name of the product set element |
| `max_items`  int64 | Default value: `50`  Maximum number of products to show |
| `product_set_id`  id | The product set id which contains a subset of products within a product catalog |
| `top_padding`  float | Default value: `0`  The padding above the product set |
| `bottom_padding`  float | Default value: `0`  The padding below the product set |
| `image_overlay_spec`  Object | How to render overlays over a product item |
| `overlay_template`  enum {PILL\_WITH\_TEXT, CIRCLE\_WITH\_TEXT, TRIANGLE\_WITH\_TEXT} | Required |
| `text_type`  enum {PRICE, STRIKETHROUGH\_PRICE, PERCENTAGE\_OFF, CUSTOM, FROM\_PRICE, DISCLAIMER, GUEST\_RATING, STAR\_RATING, SUSTAINABLE, AUTOMATED\_PERSONALIZE} | Required |
| `text_font`  enum {DROID\_SERIF\_REGULAR, LATO\_REGULAR, NUNITO\_SANS\_BOLD, OPEN\_SANS\_BOLD, OPEN\_SANS\_CONDENSED\_BOLD, PT\_SERIF\_BOLD, ROBOTO\_MEDIUM, ROBOTO\_CONDENSED\_REGULAR, NOTO\_SANS\_REGULAR, DYNADS\_HYBRID\_BOLD} | Required |
| `position`  enum {TOP\_LEFT, TOP\_RIGHT, BOTTOM\_LEFT, BOTTOM\_RIGHT} | Required |
| `theme_color`  enum {BACKGROUND\_E50900\_TEXT\_FFFFFF, BACKGROUND\_F78400\_TEXT\_FFFFFF, BACKGROUND\_00AF4C\_TEXT\_FFFFFF, BACKGROUND\_0090FF\_TEXT\_FFFFFF, BACKGROUND\_755DDE\_TEXT\_FFFFFF, BACKGROUND\_F23474\_TEXT\_FFFFFF, BACKGROUND\_595959\_TEXT\_FFFFFF, BACKGROUND\_000000\_TEXT\_FFFFFF, BACKGROUND\_FFFFFF\_TEXT\_C91B00, BACKGROUND\_FFFFFF\_TEXT\_F78400, BACKGROUND\_FFFFFF\_TEXT\_009C2A, BACKGROUND\_FFFFFF\_TEXT\_007AD0, BACKGROUND\_FFFFFF\_TEXT\_755DDE, BACKGROUND\_FFFFFF\_TEXT\_F23474, BACKGROUND\_FFFFFF\_TEXT\_646464, BACKGROUND\_FFFFFF\_TEXT\_000000} | Required |
| `float_with_margin`  boolean |  |
| `text_template_tags`  array<string> |  |
| `custom_text_type`  enum {FREE\_SHIPPING, POPULAR, SALE} |  |
| `item_headline`  string | Default value: |
| `item_description`  string | Default value: |
| `retailer_item_ids`  list<string> |  |
| `show_in_feed`  boolean |  |
| `storefront_setting`  JSON object |  |
| `enable_sections`  boolean | Default value: `false`  enable\_sections |
| `canvas_store_locator`  Object | Create a canvas store locator that belongs to a page |
| `name`  string | Default value: `Store Locator`  Name of the store locator element |
| `typeface`  string | Default value: `HelveticaNeue-Light`  Font used to display info about the store |
| `header_background_color`  string | Default value: `FF000000`  Header background color for the store locator |
| `canvas_template_video`  Object | Create a template video that belongs to a page |
| `name`  string | Default value: `"Automatic Video"` |
| `product_set_id`  numeric string | Required |
| `template_video_spec`  Object | Required |
| `customization`  JSON object {string : string} |  |
| `top_padding`  float | Default value: `0` |
| `bottom_padding`  float | Default value: `0` |
| `canvas_text`  Object | Create a canvas text that belongs to a page |
| `name`  string | Default value: `Text`  Name of the text element |
| `rich_text`  Object | The text content of the text element  Required |
| `text_alignment`  enum {LEFT, CENTER, RIGHT} | Default value: `CENTER`  The alignment of the text |
| `text_color`  string | Default value: `FF777777`  The color of the text |
| `font_size`  int64 | Default value: `15`  The size of the font for the text |
| `font_family`  string | Default value: `sans-serif`  The font family of the text |
| `line_height`  float | Default value: `1`  The line height of the text |
| `top_padding`  float | Default value: `0`  The padding above the text |
| `bottom_padding`  float | Default value: `0`  The padding below the text |
| `background_color`  string | The color of the background for the text |
| `canvas_video`  Object | Create a canvas video that belongs to a page |
| `name`  string | Default value: `Video`  Name of the video element |
| `video_id`  id | ID of Facebook video used in the video element |
| `video_url`  URI |  |
| `style`  enum {FIT\_TO\_WIDTH, FIT\_TO\_HEIGHT} | Default value: `FIT_TO_WIDTH`  The presentation style of the video |
| `top_padding`  float | Default value: `0`  The padding above the video |
| `bottom_padding`  float | Default value: `0`  The padding below the video |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 200 | Permissions error |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 190 | Invalid OAuth 2.0 Access Token |
| 283 | That action requires the extended permission pages\_read\_engagement and/or pages\_read\_user\_content and/or pages\_manage\_ads and/or pages\_manage\_metadata |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

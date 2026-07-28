Graph API Version

[v25.0](#)

# Page Picture

The profile picture of a Facebook Page.

## Reading

Get the profile picture of a Facebook Page.

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Permissions

* The person requesting the Page access token must be able to perform the [`MANAGE` task](/docs/pages/overiew#tasks) on the Page.
* The [`pages_read_engagement` permission.](/docs/pages/overview#permissions)
* The [`pages_show_list` permission.](/docs/pages/overview#permissions)

OR

* An App or User access token.
* The [Pages Public Metadata Access](/docs/pages/overview#features) feature

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDKcURL[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-id%7D%2Fpicture%3Fredirect%3D0&version=v25.0)

```
GET /v25.0/{page-id}/picture?redirect=0 HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/picture?redirect=0',
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
    "/{page-id}/picture",
    {
        "redirect": "0"
    },
    function (response) {
      if (response && !response.error) {
        /* handle the result */
      }
    }
);
```

```
Bundle params = new Bundle();
params.putString("redirect", "0");
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/{page-id}/picture",
    params,
    HttpMethod.GET,
    new GraphRequest.Callback() {
        public void onCompleted(GraphResponse response) {
            /* handle the result */
        }
    }
).executeAsync();
```

```
NSDictionary *params = @{
  @"redirect": @"0",
};
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/{page-id}/picture"
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
  -d 'redirect=0' \
  -d 'access_token=<ACCESS_TOKEN>' \
  https://graph.facebook.com/v25.0/{page-id}/picture
```

If you want to learn how to use the Graph API, read our [Using Graph API guide](/docs/graph-api/using-graph-api/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `height`  integer | The height of this picture in pixels. |
| `redirect`  boolean | Default value: `true`  By default the picture edge will return a picture instead of a JSON response. If you want the picture edge to return JSON that describes the image set `redirect=0` when you make the request. |
| `type`  enum{small, normal, album, large, square} | The size of this picture. It can be one of the following values: small, normal, large, square. |
| `width`  integer | The width of this picture in pixels. |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A single [ProfilePictureSource](/docs/graph-api/reference/profile-picture-source/) node.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 190 | Invalid OAuth 2.0 Access Token |
| 200 | Permissions error |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 100 | Invalid parameter |
| 459 | The session is invalid because the user has been checkpointed |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 104 | Incorrect signature |
| 483 | The session is invalid because the user is in consent app blocking |

## Creating

You can make a POST request to `picture` edge from the following paths:

* [`/{page_id}/picture`](/docs/graph-api/reference/page/picture/)

When posting to this edge, a [ProfilePictureSource](/docs/graph-api/reference/profile-picture-source/) will be created.

### Permissions

* The person requesting the Page access token must be able to perform the [`MANAGE` task](/docs/pages/overiew#tasks) on the Page.
* The [`pages_read_engagement` permission.](/docs/pages/overview#permissions)
* The [`pages_show_list` permission.](/docs/pages/overview#permissions)

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `android_key_hash`  string | Android key hash for the proxied app ID. |
| `burn_media_effect`  boolean | burn\_media\_effect |
| `caption`  UTF-8 string | The caption for a profile pic  Supports Emoji |
| `composer_session_id`  string | Composer session ID |
| `frame_entrypoint`  string | frame\_entrypoint |
| `has_umg`  boolean | Whether or not the picture uploaded has edits made in the unified media gallery |
| `height`  int64 | Height for crop |
| `ios_bundle_id`  string | iOS bundle ID for the proxied app ID. |
| `media_effect_ids`  list<int> | Set of Media Effect IDs that were used on this pic |
| `media_effect_source_object_id`  int | The FBID of the media from which the effects were sourced. |
| `msqrd_mask_id`  string | MSQRD mask ID that was used to create this pic  Deprecated |
| `photo`  numeric string | ID of the photo to use as the profile pic |
| `picture`  URL | URL of the picture to upload |
| `profile_pic_method`  string | Method of the profile pic change for logging |
| `profile_pic_source`  string | Source of the profile pic change for logging |
| `proxied_app_id`  int | ID of the proxied app that performed this action |
| `qn`  string | Waterfall logger session ID |
| `reuse`  boolean | Whether to reuse an existing profile pic |
| `scaled_crop_rect`  Object | Dictionary with fractional (scaled) keys x/y/width/height for crop |
| `x`  float |  |
| `y`  float |  |
| `width`  float |  |
| `height`  float |  |
| `set_profile_photo_shield`  string | Whether to set Women in Emerging Markets Profile Photo Safety Shield on or off |
| `sticker_id`  int | Sticker ID for profile pics with sticker overlays |
| `sticker_source_object_id`  int | The FBID of the source media |
| `suppress_stories`  boolean | suppress\_stories |
| `width`  int64 | Width for crop |
| `x`  int64 | Top-left x-coordinate for crop |
| `y`  int64 | Top-left y-coordinate for crop |

### Return Type

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 240 | Desktop applications cannot call this function for other users |
| 200 | Permissions error |
| 324 | Missing or invalid image file |
| 190 | Invalid OAuth 2.0 Access Token |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

Graph API Version

[v25.0](#)

# Profile Picture Source

## Reading

Profile Picture

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_ProfilePictureSource%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_ProfilePictureSource} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_ProfilePictureSource}',
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
    "...?fields={fieldname_of_type_ProfilePictureSource}",
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
    "...?fields={fieldname_of_type_ProfilePictureSource}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_ProfilePictureSource}"
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
| `bottom`  unsigned int32 | Deprecated  Deprecated |
| `cache_key`  string | A key to identify the profile picture for the purpose of invalidating the image cache |
| `height`  unsigned int32 | Picture height in pixels. Only returned when specified as a modifier  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `is_silhouette`  bool | True if the profile picture is the default 'silhouette' picture  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `left`  unsigned int32 | Deprecated  Deprecated |
| `right`  unsigned int32 | Deprecated  Deprecated |
| `top`  unsigned int32 | Deprecated  Deprecated |
| `url`  string | URL of the profile picture. The URL will expire.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `width`  unsigned int32 | Picture width in pixels. Only returned when specified as a modifier  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can make a POST request to `picture` edge from the following paths:

* [`/{page_id}/picture`](/docs/graph-api/reference/page/picture/)

When posting to this edge, a [ProfilePictureSource](/docs/graph-api/reference/profile-picture-source/) will be created.

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

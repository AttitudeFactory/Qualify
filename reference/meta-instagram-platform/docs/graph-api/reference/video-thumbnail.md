Graph API Version

[v25.0](#)

# Video Thumbnail

Represents a thumbnail image on a [Video](/docs/graph-api/reference/video).

## Reading

Get fields on a VideoThumbnail.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_VideoThumbnail%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_VideoThumbnail} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_VideoThumbnail}',
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
    "...?fields={fieldname_of_type_VideoThumbnail}",
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
    "...?fields={fieldname_of_type_VideoThumbnail}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_VideoThumbnail}"
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
| `id`  numeric string | The ID of the thumbnail  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `height`  unsigned int32 | The height of the thumbnail  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `is_preferred`  bool | Whether this is the preferred thumbnail for the video  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `name`  string | The name of the thumbnail  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `scale`  float | The scale of the thumbnail  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `uri`  string | The URI of the thumbnail  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `width`  unsigned int32 | The width of the thumbnail  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can make a POST request to `thumbnails` edge from the following paths:

* [`/{video_id}/thumbnails`](/docs/graph-api/reference/video/thumbnails/)

When posting to this edge, a [VideoThumbnail](/docs/graph-api/reference/video-thumbnail/) will be created.

Refer to the [`/{video_id}/thumbnails`](/docs/graph-api/reference/video/thumbnails#Creating) edge reference for complete usage details.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `is_preferred`  boolean | Default value: `false`  Set to `true` if this thumbnail is the preferred thumbnail to be shown for this video |
| `source`  image | The source for the thumbnail, an image file  Required |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 200 | Permissions error |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

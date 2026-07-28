This document refers to a feature that was removed after [Graph API v3.2.](/docs/graph-api/reference/v3.2/video)

Graph API Version

[v25.0](#)

# Video `/{video-id}`

An individual video on Facebook.

## Reading

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bvideo-id%7D&version=v25.0)

```
GET /v25.0/{video-id} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{video-id}',
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
    "/{video-id}",
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
    "/{video-id}",
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
                               initWithGraphPath:@"/{video-id}"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Permissions

* You must use a valid Page Access Token or User Access Token for any video with public privacy settings.
* For any videos uploaded by someone, and any videos in which they have been tagged - A user access token for that person with `user_videos` permission.

### Fields

| Property Name | Description | Type |
| --- | --- | --- |
| `id` | The video ID. | `string` |
| `created_time` | The time the video was initially published. | `datetime` |
| `description` | The description of the video. | `string` |
| `embed_html` | The HTML element that may be embedded in a Web page to play the video. | `string` |
| `format` | The different formats of the video. | `list<VideoFormat>` |
| `embed_html` | HTML to embed the video in this format. | `string` |
| `filter` | The filter applied to this video format. | `string` |
| `height` | The height of the video in this format. | `integer` |
| `picture` | The thumbnail for the video in this format. | `string` |
| `width` | The width of the video in this format. | `integer` |
| `event` | Event associated with the video. | [`Event`](/docs/graph-api/reference/event/) |
| `from` | The profile that created the video. | [`Profile`](/docs/graph-api/reference/profile) |
| `icon` | The icon that Facebook displays when videos are published to the feed. | `string` |
| `name` | The video title or caption. | `string` |
| `picture` | The URL for the thumbnail picture of the video. | `string` |
| `place` | Location associated with the video. | [`Page`](/docs/graph-api/reference/page/) |
| `source` | A URL to the raw, playable video file. | `string` |
| `updated_time` | The last time the video or its caption was updated. | `datetime` |

## Publishing

You can publish videos by using the [`/{user-id}/videos`](/docs/graph-api/reference/user/videos/), [`/{event-id}/videos`](/docs/graph-api/reference/event/videos/), and [`/{page-id}/videos`](/docs/graph-api/reference/page/videos/) edges.

## Edges

| Property Name | Description |
| --- | --- |
| [`/likes`](/docs/graph-api/reference/object/likes) | Profiles that like this video. |
| [`/comments`](/docs/graph-api/reference/object/comments) | Comments on this video. |
| [`/sharedposts`](/docs/graph-api/reference/object/sharedposts) | Posts that share this video. |
| [`/captions`](/docs/graph-api/reference/object/captions) | Captions for this video. |

Graph API Version

[v25.0](#)

This edge has been deprecated and can no longer be used.

# Event Videos [`/{event-id}`](/docs/graph-api/reference/event/)`/videos`

Use this endpoint to publish videos to an event. To delete or update an existing video, use the `/{video-id}` node instead.

## Creating

To publish a video to an event, send a `POST` request to the `/{event-id}/videos` edge on `graph-video.facebook.com`.

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK

```
POST /v25.0/{event-id}/videos HTTP/1.1
Host: graph-video.facebook.com

source=%7Bvideo-data%7D
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->post(
    '/{event-id}/videos',
    array (
      'source' => '{video-data}',
    ),
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
    "/{event-id}/videos",
    "POST",
    {
        "source": "{video-data}"
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
params.putString("source", "{video-data}");
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/{event-id}/videos",
    params,
    HttpMethod.POST,
    new GraphRequest.Callback() {
        public void onCompleted(GraphResponse response) {
            /* handle the result */
        }
    }
).executeAsync();
```

```
NSDictionary *params = @{
  @"source": @"{video-data}",
};
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/{event-id}/videos"
                                      parameters:params
                                      HTTPMethod:@"POST"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Limitations

* Videos must be encoded as [`multipart/form-data`](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.w3.org%2FTR%2Fhtml401%2Finteract%2Fforms.html%23h-17.13.4.2&h=AUDR2XwLRSGwKfl0YffzuXkRxJ600AHljW9dxZ25VjrYPAcgOw0jeoiXxPiWh2USt72I8Ki38q4w--PS0FgxJxMkubnP5yeyJhx--xGvnoExxJdmy1MToLYVGiOPd0P1aIFQNrtyINwmO5mV).
* If you upload a video with a multi-part HTTP request or by providing a URL to a video, the video cannot exceed **1 GB** in size and **20 minutes** in duration.
* Resumable video uploads can be up to **1.75GB** and **45 minutes** in duration.

### Supported Formats

3g2, 3gp, 3gpp, asf, avi, dat, divx, dv, f4v, flv, m2ts, m4v, mkv, mod, mov, mp4, mpe, mpeg, mpeg4, mpg, mts, nsv, ogm, ogv, qt, tod, ts, vob, wmv.

### Permissions

As of April 24,2018, the `pubish_actions` permission has been removed. Please see the [Breaking Changes Changelog](https://developers.facebook.com/docs/graph-api/changelog/breaking-changes#login-4-24) for more details. To provide a way for your app users to share content to Facebook, we encourage you to use our  [Sharing products](https://developers.facebook.com/docs/sharing) instead.

This endpoint requires a user access token with the `publish_actions` permission.

### Fields

Name | Description | Type || `id` | The target ID where the video is posted to. | `numeric string` |
| `title` | The title of the video. | `string` |
| `description` | The description of the video, used as the accompanying status message in any feed story. This parameter can contain mentions of other Facebook Pages using the following syntax:   ``` @[page-id] ```   For example the following description would mention the [Facebook Developers](https://www.facebook.com/FacebookDevelopers) page inline:   ``` Test message @[19292868552] tag ```   Usage of this feature is [subject to review](/docs/apps/review) but by using Pages you are an admin of (both to make the API call, and to be used in a mention), and an app you are a developer of, you can test it for yourself before review. | `string` |
| `source` | The video, [encoded as form data](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.w3.org%2FTR%2Fhtml401%2Finteract%2Fforms.html%23h-17.13.4.2&h=AUDdglXDDJzHhUGPl9-a-_h0dwQ7j0EZ76_6WcO4w40iPIoT0NLbLW5m_7VSYHBODd_YRxUukJayeYRaAUpwK3bHsTtXnt5LvGjLUY9Tc7CBU344uog9aGlVx9_4LZYVOIj3gQtHR0hqxYIa). This field is required. | [`multipart/form-data`](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.w3.org%2FTR%2Fhtml401%2Finteract%2Fforms.html%23h-17.13.4.2&h=AUAWjd7KQHVUiUH5cETI59XaKkMVus3iqvOMYVLCbTltpUVOccbmfKcOyJ86SFaLq2rUwjE9Z4nIbxm5WVpixduo4iK8yXc042P_OzajcuCK95Px8JECQvXrnIgfnuODkzcgDL3cBr-Mh7R3) |
| `file_url` | Accessible URL of a video file. Cannot be used with `upload_phase`. | `string` |
| `thumb` | The video thumbnail raw data to be uploaded and associated with a video. | `image` |
| `upload_phase` | Type of chunked upload request. | `enum{start, transfer, finish}` |
| `file_size` | The size of the entire video file in bytes. | `unsigned int32` |
| `start_offset` | Start byte position of the file chunk. | `unsigned int32` |
| `video_file_chunk` | The video file chunk, [encoded as form data](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.w3.org%2FTR%2Fhtml401%2Finteract%2Fforms.html%23h-17.13.4.2&h=AUBoxnJplM9pLIKYyskFFGGWFJijI9TKPs-MXNIGtZOiMpf7qwixWfTHG_tg7zjjm6yi9OMSer0YAgMOZEKk1-WCkTMPAG4-iynNvhWf6qBDwM3fVGe-rcAcS31keg__GJwsqpsq6E7_Ashp). This field is required during `transfer` upload phase. | `multipart/form-data` |
| `upload_session_id` | ID of the chunked upload session. | `numeric string` |

### Response

If successful:

```
Struct {
  id: numeric string,
  upload_session_id: numeric string,
  video_id: numeric string,
  start_offset: numeric string,
  end_offset: numeric string,
  success: bool,
  skip_upload: bool,
}
```

## Reading

You can't read the videos uploaded to an event using this edge.

## Updating

You can't update using this edge.

## Deleting

You can't delete using this edge.

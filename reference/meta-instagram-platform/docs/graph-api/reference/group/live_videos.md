Graph API Version

[v25.0](#)

# Group Live Videos

For more information about the Live Video API, visit our [Live Video Docs](https://developers.facebook.com/docs/live-video-api).

## Creating

You can make a POST request to `live_videos` edge from the following paths:

* `/{group-id}/live_videos`

When posting to this edge, a LiveVideo will be created.

#### Parameters

Name | Description || `app_attribution_tag` numberic string or integer | An attribution tag for live videos which will show on feed. |
| `attribution_app_id` numberic string or integer | Id of the attribution app. |
| `content_tags` list<numberic string> | Tags that describe the contents of the video. Use search endpoint with `type=adinterest` to get possible IDs. Example query:  /search?type=adinterest&q=sunsets |
| `description` UTF-8 string | The description of the live video. Supports Emojis. |
| `encoding_settings` string | Identifier of the encoding settings group the broadcaster is using for this stream. This parameter is currently only in use for live-360 broadcasts. The value to be passed to this parameter is the value of the `identifier` key of the encoding settings preset. Encoding presets can be found by querying the `/broadcaster_encoding_settings` Graph API endpoint (`GET` query). |
| `event_params` integer | Unix timestamp when the broadcaster plans to go live. |
| `fisheye_video_cropped` boolean | Whether the single fisheye video is cropped or not. |
| `front_z_rotation` float | The front z rotation in degrees on the single fisheye video. |
| `game_id` numberic string or integer | Set which game this video is about. Use search endpoint with `type=game` to get possible IDs. Example query:  /search?type=game&=pubg |
| `game_specs` Game Specs Parameter | Set metadata representing which game should be attributed. |
| `is_spherical` boolean | Flag that denotes the broadcast is a 360 live broadcast. |
| `live_encoders` list<numberic string or integer> | Live encoders that will broadcast to this live video. |
| `original_fov` int64 | Original field of view of the camera. |
| `post_surfaces_blacklist` list<enum{1, 2, 3, 4, 5}> | A blacklist of where the post won't show up, for feed only experience. |
| `privacy` Privacy Parameter | Privacy for this live video. |
| `projection` enum{EQUIRECTANGULAR, CUBEMAP} | Flag that denotes expected projection for 360 live streams. The default value is EQUIRECTANGULAR. |
| `save_vod` boolean | Whether or not the video data should be saved for later consumption in VOD format. Default is true. (Note: Can only be set at time of creation) |
| `schedule_custom_profile_image` image | Custom image that will appear in the scheduled live story and lobby. |
| `spatial_audio_format` enum{ambiX\_4} | Denotes the format of the spatial audio stream. When unspecified audio is presumed to be mono or stereo. |
| `status` enum {UNPUBLISHED, LIVE\_NOW, SCHEDULED\_UNPUBLISHED, SCHEDULED\_LIVE, SCHEDULED\_CANCELED} | The status of the broadcast. A `LIVE_NOW` broadcast is currently live and visible to Users. An `UNPUBLISHED` broadcast is in preparation and not visible to other users. An unpublished broadcast may be automatically deleted after several hours in this state. Consider using the scheduled states to create a planned, future broadcast. |
| `stereoscopic_mode` enum {MONO, LEFT\_RIGHT, TOP\_BOTTOM} | Set this flag to the stereoscopic mode for this video. |
| `stop_on_delete_stream` | Set this to `true` if the stream should be stopped when the `deleteStream` RTMP command is received. |
| `title` UTF-8 string | The title of the live video. Supports Emojis. |

#### Return Type

This endpoint supports read-after-write and will read the node represented by `id` in the return type.

```
Struct {
  id: numeric string,
  stream_url: string,
  secure_stream_url: string,
  stream_secondary_urls: List [
    string
  ],
  secure_stream_secondary_urls: List [
    string
  ],
  dash_ingest_url: string,
}
```

#### Validation Rules

Error | Description || 100 | Invalid Parameter |
| 200 | Permissions error |

## Reading

#### Features

Name | Description || Groups API | This is a [feature](https://developers.facebook.com/docs/apps/review/feature#reference-GROUPS_ACCESS) requiring [App Review](https://developers.facebook.com/docs/apps/review/). |

#### Example

Android SDKHTTPObjective-CJavaScript SDKPHP SDK

```
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/{group-id}/live_videos",
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
GET /v7.0/{group-id}/live_videos HTTP/1.1
Host: graph.facebook.com
```

```
// For more complex open graph stories, use `FBSDKShareAPI`
// with `FBSDKShareOpenGraphContent`
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/{group-id}/live_videos"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

```
/* make the API call */
FB.api(
    "/{group-id}/live_videos",
    function (response) {
      if (response && !response.error) {
        /* handle the result */
      }
    }
);
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{group-id}/live_videos',
    'your-access-token'
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

Learn more about the Graph API in our [Using the Graph API Guide](https://developers.facebook.com/docs/graph-api/using-graph-api/).

#### Parameters

Name | Description || `broadcast_status` list<enum {UNPUBLISHED, LIVE, LIVE\_STOPPED, PROCESSING, VOD, SCHEDULED\_UNPUBLISHED, SCHEDULED\_LIVE, SCHEDULED\_EXPIRED, SCHEDULED\_CANCELED}> | Allows you to specify what kind of live videos return. No value returns all status types. |
| `source` enum{target, owner} | Default value: `target`  The source of where the videos should be queried. E.g `target` gets videos broadcast onto a group. Group Live Videos ONLY supports `target`. |

#### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

`data`

A list of [LiveVideo fields](https://developers.facebook.com/docs/graph-api/reference/live-video/).

`paging`

For more details about pagination, see [the Graph API guide](https://developers.facebook.com/docs/graph-api/using-graph-api/#paging).

#### Validation Rules

Error | Description || 200 | Permissions error |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

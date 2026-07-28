Graph API Version

[v25.0](#)

# Page Live Videos

On June 10th, 2024, Meta is launching new requirements that must meet before an account can go live on Facebook. The new requirements are as follows:

* The Facebook account must be at least 60 days old
* The Facebook Page or [professional mode profile](https://www.facebook.com/business/help/2680340558863560) must have at least 100 followers

Visit our
[Help Center
![](https://scontent-eze1-2.xx.fbcdn.net/v/t39.2365-6/310307727_3347317042262105_1088877051262827250_n.png?_nc_cat=107&ccb=1-7&_nc_sid=e280be&_nc_ohc=ML3XjuFMKyAQ7kNvwGv0co8&_nc_oc=Adoopxmt812yNn48i7SLLYOLz6sAWTzD5RjX9oj83GHKOgt9iiB8HRd7SjpITEOTf98&_nc_zt=14&_nc_ht=scontent-eze1-2.xx&_nc_gid=CiFB9KsQn8HipNtF2qpHnA&_nc_ss=7b20f&oh=00_AQBAFmVpNNdkbLsFYlOyGqZiVgI8wh9A9VhrRwqGVZw-mA&oe=6A7D3EA2)](#) to learn more about this change.

## Reading

You can't perform this operation on this endpoint.

## Creating

You can make a POST request to `live_videos` edge from the following paths:

* [`/{page_id}/live_videos`](/docs/graph-api/reference/page/live_videos/)

When posting to this edge, a [LiveVideo](/docs/graph-api/reference/live-video/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `content_tags`  list<numeric string> | Tags that describe the contents of the video. Use search endpoint with `type=adinterest` to get possible IDs.   ```                                                   Example:                                                   ~~~~                                                   /search?type=adinterest&q=couscous                                                   ~~~~ ``` |
| `crossposting_actions`  array<JSON object> | List of desired changes to crossposting for this broadcast. Each change must provide a `page_id` and `action`. Example:  [ {page\_id: 1234, action: 'enable\_crossposting'}, {page\_id: 4567, action: 'enable\_crossposting\_and\_create\_post'} ]  Available action types:   * `enable_crossposting`: Enables crossposting for this broadcast with the Page if it is not currently enabled. No change if crossposting is already enabled with the Page for this broadcast. * `disable_crossposting`: Disables crossposting for this broadcast with the Page if it is currently enabled. No change if crossposting is not already enabled with the Page for this broadcast. * `enable_crossposting_and_create_post`: Same as `enable_crossposting`, but will also create a post as the Page. The post will be created even if crossposting is already enabled for the Page. This option is subject to your [live crossposting relationships](https://www.facebook.com/help/publisher/1385580858214929) and will fail for Pages without the required permission.   When used with a Live Online Event, this will apply to the event. |
| `page_id`  numeric string | page\_id  Required |
| `action`  enum {ENABLE\_CROSSPOSTING, DISABLE\_CROSSPOSTING, ENABLE\_CROSSPOSTING\_AND\_CREATE\_POST} | action  Required |
| `custom_labels`  list<string> | Labels used to describe the video. Unlike content tags, custom labels are not published and only appear in insights data. |
| `description`  string | The description of the live video. |
| `donate_button_charity_id`  numeric string or integer | Specifies the ID of the charity for which a donate button will be added to the live video. |
| `enable_backup_ingest`  boolean | Set this to true to enable a backup ingest url. stop\_on\_delete\_stream defaults to false when set |
| `encoding_settings`  string | Identifier of the encoding settings group the broadcaster is using for this stream. This parameter is currently only in use for live-360 broadcasts. The value to be passed to this parameter is the value of the `identifier` key of the encoding settings preset. Encoding presets can be found by querying the `/broadcaster_encoding_settings` Graph API endpoint (`GET` query). |
| `event_params`  Live Video Event Parameter | Parameters specific to Live Online Event broadcast. If `start_time` (unix timecode) is set, LOE's start time will be updated. Also, `cover` (url) uploads an image to use as the cover photo for the event.  Example: { start\_time: 1641013200, cover: 'https://your.url/image.jpg', } |
| `fisheye_video_cropped`  boolean | Whether the single fisheye video is cropped or not |
| `front_z_rotation`  float | The front z rotation in degrees on the single fisheye video |
| `game_show`  JSON object | Configure this live stream to be a game show |
| `game_type`  enum {KNOCKOUT} | game\_type  Required |
| `is_spherical`  boolean | Flag that denotes the broadcast is a 360 live broadcast. |
| `original_fov`  int64 | Original field of view of the camera |
| `privacy`  Privacy Parameter | Privacy for this live video. |
| `projection`  enum {EQUIRECTANGULAR, CUBEMAP, HALF\_EQUIRECTANGULAR} | Flag that denotes expected projection for 360 live streams. The default value is EQUIRECTANGULAR. |
| `published`  boolean | Set this to false to preview the stream before going live.   ```                                                   Deprecated. Prefer setting the status instead. ``` |
| `schedule_custom_profile_image`  image | Custom image that will appear in the scheduled live story and lobby. |
| `spatial_audio_format`  enum {ambiX\_4} | Denotes the format of the spatial audio stream. When unspecified audio is presumed to be mono or stereo. |
| `status`  enum {UNPUBLISHED, LIVE\_NOW, SCHEDULED\_UNPUBLISHED, SCHEDULED\_LIVE, SCHEDULED\_CANCELED} | The status of the broadcast. A `LIVE_NOW` broadcast is currently live and visible to users. An `UNPUBLISHED` broadcast is in preparation; it's not visible to other users, and it may be automatically deleted after several hours in this state. (Consider using the `SCHEDULED` states to create a planned, future broadcast.) |
| `stereoscopic_mode`  enum {MONO, LEFT\_RIGHT, TOP\_BOTTOM, MULTI\_VIEW} | Set this parameter to the stereoscopic mode for this video. |
| `stop_on_delete_stream`  boolean | Set this to true if stream should be stopped when deleteStream RTMP command received. |
| `targeting`  target | Object that [limits the audience](https://www.facebook.com/help/352402648173466) for this content. Anyone not in these demographics will not be able to view this content.  When used with a Live Online Event, this will apply to the event. |
| `geo_locations`  Object |  |
| `countries`  list<string> |  |
| `regions`  list<Object> |  |
| `key`  int64 |  |
| `cities`  list<Object> |  |
| `key`  int64 |  |
| `zips`  list<Object> |  |
| `key`  string |  |
| `locales`  list<string> |  |
| `excluded_countries`  list<string> |  |
| `excluded_regions`  list<int64> |  |
| `excluded_cities`  list<int64> |  |
| `excluded_zipcodes`  list<string> |  |
| `timezones`  list<int64> |  |
| `age_min`  enum {13, 15, 18, 21, 25} |  |
| `title`  string | The title of the live video. Maximum 254 characters. |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

`stream_url`: string,

`secure_stream_url`: string,

`stream_secondary_urls`: List [

string

],

`secure_stream_secondary_urls`: List [

string

],

`dash_ingest_url`: string,

`dash_ingest_secondary_urls`: List [

string

],

`event_id`: numeric string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 100 | Invalid parameter |
| 190 | Invalid OAuth 2.0 Access Token |
| 102 | Session key invalid or no longer valid |
| 1000 | Invalid time for an event. |
| 1005 | Fail to upload cover photo. |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

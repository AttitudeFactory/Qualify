Graph API Version

[v25.0](#)

# Page Videos

Represents a collection of [Videos](/docs/graph-api/reference/video) for a Page.

## Reading

You can't perform this operation on this endpoint.

## Creating

### Get Started

Refer to the [Video API Publishing guide](/docs/video-api/guides/publishing) to learn how to upload and publish a video.

### Requirements

To create an unpublished video for advertising, you will need:

* A Page access token requested by a person who can perform the `ADVERTISE` task on the Page.
* The `pages_manage_ads` and `pages_show_list` permissions

To create and publish a video, you will need:

* A Page access token requested by a person who can perform the `CREATE_CONTENT` task on the Page.
* The `pages_manage_posts`, `pages_read_engagement`, and `pages_show_list` permissions

You can make a POST request to `videos` edge from the following paths:

* [`/{page_id}/videos`](/docs/graph-api/reference/page/videos/)

When posting to this edge, a [Video](/docs/graph-api/reference/video/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `ad_breaks`  array | Time offsets of ad breaks in milliseconds. Ad breaks are short ads that play within a video. Place new ad breaks or delete existing ones. |
| `audio_story_wave_animation_handle`  string | Everstore handle of wave animation used to burn audio story video |
| `backdated_post`  array | Settings to allow backdated video post.A backdated post needs to be published. |
| `backdated_time`  datetime | The time when the video post was created.  Required |
| `backdated_time_granularity`  enum{year, month, day, hour, min, none} | Default value: `none`  Accuracy of the backdated time. |
| `hide_from_newsfeed`  boolean | Default value: `false`  Whether to hide the video from newsfeed display. |
| `content_category`  enum {BEAUTY\_FASHION, BUSINESS, CARS\_TRUCKS, COMEDY, CUTE\_ANIMALS, ENTERTAINMENT, FAMILY, FOOD\_HEALTH, HOME, LIFESTYLE, MUSIC, NEWS, POLITICS, SCIENCE, SPORTS, TECHNOLOGY, VIDEO\_GAMING, OTHER} | Content category of this video. |
| `content_tags`  list<numeric string> | Tags that describe the contents of the video. Use search endpoint with `type=adinterest` to get possible IDs. Example:   ``` ~~~~ /search?type=adinterest&q=couscous ~~~~ ``` |
| `crossposted_video_id`  numeric string or integer | The video id that the new video post will be reusing |
| `custom_labels`  list<string> | Labels used to describe the video. Unlike content tags, custom labels are not published and only appear in insights data. |
| `description`  UTF-8 string | The text describing a post that may be shown in a story about it. It may include rich text information, such as entities and emojis.  Supports Emoji |
| `direct_share_status`  int64 | The status to allow sponsor directly boost the post. |
| `edit_description_spec`  JSON object | Specification for burned-in text and sticker elements that require screen reader support. Contains information about on-screen text overlays, their positions, timing, and accessibility labels to enable proper screen reader functionality for video content. |
| `screen_readers`  array<JSON object> |  |
| `embeddable`  boolean | Whether the video is embeddable. |
| `end_offset`  int64 | end\_offset |
| `expiration`  Object | Time the video expires and whether it will be removed or hidden. |
| `time`  string |  |
| `type`  enum{expire\_and\_delete, expire\_only} |  |
| `feed_targeting`  feed target | Object that controls [news feed targeting](https://www.facebook.com/help/352402648173466) for this content. Anyone in these demographics will be more likely to see this content, those not will be less likely, but may still see it anyway. Any of the targeting fields shown here can be used, none are required. |
| `geo_locations`  Object |  |
| `countries`  list<string> |  |
| `regions`  list<Object> |  |
| `key`  int64 |  |
| `cities`  list<Object> |  |
| `key`  int64 |  |
| `zips`  list<Object> |  |
| `key`  string |  |
| `locales`  list<string> | Values for targeted locales. Use `type` of `adlocale` to [find Targeting Options](/docs/marketing-api/targeting-search) and use the returned key to specify. |
| `age_min`  int64 | Must be `13` or higher. Default is 0. |
| `age_max`  int64 | Maximum age. |
| `genders`  list<int64> | Target specific genders. `1` targets all male viewers and `2` females. Default is to target both. |
| `college_years`  list<int64> | Array of integers. Represent graduation years from college. |
| `education_statuses`  list<int64> | Array of integers which represent current educational status. Use `1` for high school, `2` for undergraduate, and `3` for alum (or localized equivalents). |
| `interested_in`  list<int64> | Deprecated. Please see the [Graph API Changelog](/docs/graph-api/changelog/breaking-changes#2-7-2018) for more information.  Deprecated |
| `relationship_statuses`  list<int64> | Array of integers for targeting based on relationship status. Use `1` for single, `2` for 'in a relationship', `3` for married, and `4` for engaged. Default is all types. |
| `interests`  list<int64> | One or more IDs of pages to target fans of pages.Use `type` of `page` to get possible IDs as [find Targeting Options](/docs/marketing-api/targeting-search) and use the returned id to specify. |
| `file_size`  int64 | The size of the entire video file in bytes. |
| `file_url`  string | Accessible URL of a video file. Cannot be used with `upload_phase`. |
| `fisheye_video_cropped`  boolean | Whether the single fisheye video is cropped or not |
| `fov`  int64 | 360 video only: Vertical field of view |
| `front_z_rotation`  float | The front z rotation in degrees on the single fisheye video |
| `guide`  list<list<int64>> | 360 video only: Guide keyframes data. An array of keyframes, each of which is an array of 3 or 4 elements in the following order: [video timestamp (seconds), pitch (degrees, -90 ~ 90), yaw (degrees, -180 ~ 180), field of view (degrees, 40 ~ 90, optional)], ordered by video timestamp in strictly ascending order. |
| `guide_enabled`  boolean | 360 video only: Whether Guide is active. |
| `initial_heading`  int64 | 360 video only: Horizontal camera perspective to display when the video begins. |
| `initial_pitch`  int64 | 360 video only: Vertical camera perspective to display when the video begins. |
| `is_voice_clip`  boolean | is\_voice\_clip, used to indicate that if a video is used as audio record |
| `multilingual_data`  list<Object> | The data of multilingual messages and their dialects |
| `multilingual_status_lang`  string |  |
| `multilingual_status`  UTF-8 string | Supports Emoji |
| `no_story`  boolean | If set to `true`, this will suppress feed and timeline story. |
| `original_fov`  int64 | Original field of view of the source camera |
| `original_projection_type`  enum {equirectangular, cubemap, half\_equirectangular} | 360 video only: The original projection type of the 360 video being uploaded. |
| `prompt_id`  string | The prompt id in prompts or purple rain that generated this post |
| `prompt_tracking_string`  string | The prompt tracking string associated with this video post |
| `published`  boolean | Default value: `true`  Whether a post about this video is published. Non-published videos cannot be backdated. |
| `reference_only`  boolean | If set to `true`, this video will not appear anywhere on Facebook and can not be viewed or shared using permalink. After creating copyright for the video, the video can be used as copyright reference video. Default value is `false`. |
| `referenced_sticker_id`  numeric string or integer | Sticker id of the sticker in the post |
| `replace_video_id`  numeric string or integer | The video id your uploaded video about to replace |
| `scheduled_publish_time`  int64 | Time when the page post about this video should go live, this should be between 10 mins and 6 months from the time of publishing the video. |
| `secret`  boolean | If set to `true`, this video will not appear anywhere on Facebook and is not searchable. It can be viewed and shared using permalink and embeds. Default value is false. |
| `social_actions`  boolean | This can be used to enable or prohibit the use of Facebook socialactions (likes, comments, and sharing) on an unlisted video. Default value is false |
| `source`  string | The video, [encoded as form data](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.w3.org%2FTR%2Fhtml401%2Finteract%2Fforms.html%23h-17.13.4.2&h=AUDLdGp3veCQDb1WU9V49zFp_dwQVqy7AN1jRpMswvtd0jW6uT1IS23pfFvOGllnJd3y2NWkMS-INdowf1vS9LErZ9JWGLFFp6VKW969iuwDuZT86MEYznW-B8lXHjvlD7E0PR_KqwPRWuTe). This field is required. |
| `source_instagram_media_id`  numeric string | source\_instagram\_media\_id |
| `specified_dialect`  string | The default dialect of a multilingual post |
| `spherical`  boolean | Default value: `false`  Set if the video was recorded in 360 format. |
| `sponsor_id`  numeric string or integer | Facebook Page id that is tagged as sponsor in the video post |
| `sponsor_relationship`  int64 | Sponsor Relationship, such as Presented By or Paid PartnershipWith |
| `start_offset`  int64 | Start byte position of the file chunk. |
| `swap_mode`  enum {replace} | Type of replacing video request |
| `targeting`  target | Object that [limits the audience](https://www.facebook.com/help/352402648173466) for this content. Anyone not in these demographics will not be able to view this content. This will not override any Page-level demographic restrictions that may be in place. |
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
| `thumb`  image | The video thumbnail raw data to be uploaded and associated with a video. |
| `title`  UTF-8 string | The title of the video.  Supports Emoji |
| `transcode_setting_properties`  string | Properties used in computing transcode settings for the video |
| `universal_video_id`  string | The publishers asset management code for this video. |
| `unpublished_content_type`  enum {SCHEDULED, SCHEDULED\_RECURRING, DRAFT, PUBLISH\_PENDING, ADS\_POST, INLINE\_CREATED, PUBLISHED, REVIEWABLE\_BRANDED\_CONTENT} | Type of unpublished content, such as scheduled, draft or ads\_post. |
| `upload_phase`  enum {start, transfer, finish, cancel} | Type of chunked upload request. |
| `upload_session_id`  numeric string or integer | ID of the chunked upload session. |
| `video_file_chunk`  string | The video file chunk, [encoded as form data](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.w3.org%2FTR%2Fhtml401%2Finteract%2Fforms.html%23h-17.13.4.2&h=AUBQ7IDG3K5Ugnn3A2wIWxcp03ecNO3o-ddml40aL1sOKHPCsUFvVXyseA86oiwm5Thb-55o3o88oSBK3W8gIJB2D9iv-rQC0FR-eKbe4B71AcKcJPeMSz0Z6i3gMLc5nHhOqcOG9OZ2TW9R). This field is required during `transfer` upload phase. |

### Return Type

Struct {

`id`: numeric string,

`upload_session_id`: numeric string,

`video_id`: numeric string,

`start_offset`: numeric string,

`end_offset`: numeric string,

`success`: bool,

`skip_upload`: bool,

`upload_domain`: string,

`region_hint`: string,

`xpv_asset_id`: numeric string,

`is_xpv_single_prod`: bool,

`transcode_bit_rate_bps`: numeric string,

`transcode_dimension`: numeric string,

`should_expand_to_transcode_dimension`: bool,

`action_id`: string,

`gop_size_seconds`: numeric string,

`target_video_codec`: string,

`target_hdr`: string,

`maximum_frame_rate`: numeric string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 6001 | There was a problem uploading your video. Please try again. |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 389 | Unable to fetch video file from URL. |
| 100 | Invalid parameter |
| 6000 | There was a problem uploading your video file. Please try again with another file. |
| 190 | Invalid OAuth 2.0 Access Token |
| 210 | User not visible |
| 382 | The video file you tried to upload is too small. Please try again with a larger file. |

## Updating

Use the [Video endpoint](/docs/graph-api/reference/video) to update a Video.

You can't perform this operation on this endpoint.

## Deleting

Use the [Video endpoint](/docs/graph-api/reference/video) to delete a Video.

You can't perform this operation on this endpoint.

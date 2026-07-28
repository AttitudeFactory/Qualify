Graph API Version

[v25.0](#)

# Photo

Represents an individual photo on Facebook.

## Reading

This represents a Photo on Facebook.

### Permissions

* Any valid access token can read photos on a public Page.
* A page access token can read all photos posted to or posted by that Page.
* The current user's photos can be read if the user has granted the `user_photos` or `user_posts` permission.
* A user access token may read a photo that the current user is tagged in if they have granted the `user_photos` or `user_posts` permission. However, in some cases the photo's owner's privacy settings may not allow your application to access it.
* A User access token for an Admin of a Group can read Group-owned Photos.
* A User access token for an Admin of an Event can read Event-owned Photos if required after April 30, 2018.

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Feature Permissions

| Name | Description |
| --- | --- |
| Page Public Content Access | This [feature permission](/docs/apps/review/feature/) may be required. |

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bphoto-id%7D&version=v25.0)

```
GET /v25.0/{photo-id} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{photo-id}',
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
    "/{photo-id}",
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
    "/{photo-id}",
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
                               initWithGraphPath:@"/{photo-id}"
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
| `id`  numeric string | The photo ID |
| `alt_text`  string | Accessible alternative description for an image |
| `alt_text_custom`  string | User provided accessible alternative description for an image |
| `backdated_time`  datetime | A user-specified time for when this object was created |
| `backdated_time_granularity`  enum | How accurate the backdated time is |
| `can_backdate`  bool | Indicates whether the viewer can backdate the photo |
| `can_delete`  bool | Indicates whether the viewer can delete the photo |
| `can_tag`  bool | Indicates whether the viewer can tag the photo |
| `created_time`  datetime | The time this photo was published  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `event`  [Event](https://developers.facebook.com/docs/graph-api/reference/event/) | If this object has a place, the event associated with the place |
| `from`  User|Page | The profile (user or page) that uploaded this photo |
| `height`  unsigned int32 | The height of this photo in pixels |
| `icon`  string | The icon that Facebook displays when photos are published to News Feed |
| `images`  [list<PlatformImageSource>](https://developers.facebook.com/docs/graph-api/reference/platform-image-source/) | The different stored representations of the photo. Can vary in number based upon the size of the original photo. |
| `link`  string | A link to the photo on Facebook |
| `name`  string | The user-provided caption given to this photo. Corresponds to `caption` when creating photos  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `name_tags`  [list<EntityAtTextRange>](https://developers.facebook.com/docs/graph-api/reference/entity-at-text-range/) | An array containing an array of objects mentioned in the name field which contain the id, name, and type of each object as well as the offset and length which can be used to match it up with its corresponding string in the name field |
| `page_story_id`  string | ID of the page story this corresponds to. May not be on all photos. Applies only to published photos |
| `place`  [Place](https://developers.facebook.com/docs/graph-api/reference/place/) | Place info |
| `position`  unsigned int32 | Deprecated. Returns 0  Deprecated |
| `source`  string | Deprecated. Use `images` instead  Deprecated |
| `target`  [Profile](https://developers.facebook.com/docs/graph-api/reference/profile/) | The target this photo is published to |
| `updated_time`  datetime | The last time the photo was updated |
| `webp_images`  [list<PlatformImageSource>](https://developers.facebook.com/docs/graph-api/reference/platform-image-source/) | The different stored representations of the photo in webp format. Can vary in number based upon the size of the original photo. |
| `width`  unsigned int32 | The width of this photo in pixels |

### Edges

| Edge | Description |
| --- | --- |
| [`insights`](/docs/graph-api/reference/photo/insights/)  Edge<InsightsResult> | Insights data |
| [`likes`](/docs/graph-api/reference/photo/likes/)  Edge<Profile> | People who like this |
| [`picture`](/docs/graph-api/reference/photo/picture/)  Edge<ProfilePictureSource> | Link to the 100px wide representation of this photo |
| [`sponsor_tags`](/docs/graph-api/reference/photo/sponsor_tags/)  Edge<Page> | Sponsor pages tagged in the photo. |

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 200 | Permissions error |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 190 | Invalid OAuth 2.0 Access Token |
| 104 | Incorrect signature |
| 459 | The session is invalid because the user has been checkpointed |

## Creating

Animated photos are not supported, and a photo must be less than 10MB in size.

Note: the `post_id` value is not returned for photos added to Albums.

You can make a POST request to `photos` edge from the following paths:

* [`/{page_id}/photos`](/docs/graph-api/reference/page/photos/)

When posting to this edge, a [Photo](/docs/graph-api/reference/photo/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `aid`  string | Legacy album ID. Deprecated |
| `allow_spherical_photo`  boolean | Default value: `false`  Indicates that we should allow this photo to be treated as a spherical photo. This will not change the behavior unless the server is able to interpret the photo as spherical, such as via Photosphere XMP metadata. Regular non-spherical photos will still be treated as regular photos even if this parameter is true. |
| `alt_text_custom`  string | Accessible alternative description for an image |
| `android_key_hash`  string | Android key hash |
| `application_id`  non-empty string | iTunes App ID. This is used by the native Share dialog that's part of iOS |
| `attempt`  int64 | Default value: `0`  Number of attempts that have been made to upload this photo |
| `audience_exp`  boolean | Default value: `false`  Audience exp |
| `backdated_time`  datetime | A user-specified creation time for this photo |
| `backdated_time_granularity`  enum{year, month, day, hour, min, none} | Default value: `none`  Use only the part of the `backdated_time` parameter to the specified granularity |
| `caption`  UTF-8 string | The description of the photo  Supports Emoji |
| `composer_session_id`  string | Composer session ID |
| `direct_share_status`  int64 | The status to allow sponsor directly boost the post. |
| `feed_targeting`  feed target | Object that controls [News Feed targeting](https://www.facebook.com/help/352402648173466) for this post. Anyone in these groups will be more likely to see this post. People not in these groups will be less likely to see this post, but may still see it anyway. Any of the targeting fields shown here can be used, but none are required. `feed_targeting` applies to Pages only. |
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
| `filter_type`  int64 | Default value: `-1`  Unused? |
| `full_res_is_coming_later`  boolean | Default value: `false`  Full res is coming later |
| `initial_view_heading_override_degrees`  int64 | Manually specify the initial view heading in degrees from 0 to 360. This overrides any value present in the photo embedded metadata or provided in the spherical\_metadata parameter |
| `initial_view_pitch_override_degrees`  int64 | Manually specify the initial view pitch in degrees from -90 to 90. This overrides any value present in the photo embedded metadata or provided in the spherical\_metadata parameter |
| `initial_view_vertical_fov_override_degrees`  int64 | Manually specify the initial view vertical FOV in degrees from 60 to 120. This overrides any value present in the photo embedded metadata or provided in the spherical\_metadata parameter |
| `ios_bundle_id`  string | iOS Bundle ID |
| `is_explicit_location`  boolean | Is this an explicit location? |
| `is_explicit_place`  boolean | If set to `true`, the tag is a place, not a person |
| `location_source_id`  numeric string or integer | ID of a page or a page set that provides location informationto enable Local Extensions |
| `manual_privacy`  boolean | Default value: `false`  Manual privacy |
| `message`  string | Deprecated. Please use the caption param instead. |
| `name`  string | Deprecated. Please use the caption param instead. |
| `nectar_module`  string | Nectar module. Internal apps only |
| `no_story`  boolean | If set to `true`, this will suppress the News Feed story that is automatically generated on a profile when people upload a photo using your app. Useful for adding old photos where you may not want to generate a story |
| `offline_id`  int64 | Default value: `0`  Offline ID |
| `og_action_type_id`  numeric string or integer | The Open Graph action type |
| `og_icon_id`  numeric string or integer | The Open Graph icon |
| `og_object_id`  OG object ID or URL string | The Open Graph object ID |
| `og_phrase`  string | The Open Graph phrase |
| `og_set_profile_badge`  boolean | Default value: `false`  Flag to set if the post should create a profile badge |
| `og_suggestion_mechanism`  string | The Open Graph suggestion |
| `place`  place tag | Page ID of a place associated with the photo |
| `privacy`  Privacy Parameter | Determines the privacy settings of the photo. If not supplied, this defaults to the privacy level granted to the app in the Login dialog. This field cannot be used to set a more open privacy setting than the one granted |
| `profile_id`  int | Deprecated. Use `target_id` instead  Deprecated |
| `provenance_info`  JSON object | provenance\_info |
| `is_gen_ai`  boolean | is\_gen\_ai  Required |
| `provenance_type`  enum {C2PA, IPTC, EXPLICIT, INVISIBLE\_WATERMARK, C2PA\_METADATA\_EDITED, IPTC\_METADATA\_EDITED, EXPLICIT\_IMAGINE, EXPLICIT\_IMAGINE\_ME, EXPLICIT\_RESTYLE, EXPLICIT\_ANIMATE, EXPLICIT\_FACE\_SWAP, EXPLICIT\_WARDROBE, EXPLICIT\_DROP\_IN, EXPLICIT\_AI\_EDIT, EXPLICIT\_AI\_EXPANDER, EXPLICIT\_AI\_CUT, EXPLICIT\_AI\_TRANSITION, EXPLICIT\_MAGIC\_CUT, EXPLICIT\_CLIPGEN, EXPLICIT\_AI\_V2V\_RESTYLE, EXPLICIT\_RESTYLE\_EFFECTS\_MERGE, EXPLICIT\_SUBJECT\_EFFECT, EXPLICIT\_CUTOUT, EXPLICIT\_AI\_REWRITE\_WITH\_META\_AI\_INTENT, EXPLICIT\_AI\_EDIT\_PRESETS\_SHEET, NONE} | provenance\_type  Required |
| `source`  string | source |
| `proxied_app_id`  numeric string or integer | Proxied app ID |
| `published`  boolean | Default value: `true`  Set to `false` if you don't want the photo to be published immediately |
| `qn`  string | Photos waterfall ID |
| `scheduled_publish_time`  int64 | Time at which an unpublished post should be published (Unix timestamp). Applies to Pages only |
| `spherical_metadata`  JSON object | A set of params describing an uploaded spherical photo. This field is not required; if it is not present we will try to generate spherical metadata from the metadata embedded in the image. If it is present, it takes precedence over any embedded metadata. Please click to the left to expand this list and see more information on each parameter. See also the Google Photo Sphere spec for more info on the meaning of the params: https://developers.google.com/streetview/spherical-metadata |
| `ProjectionType`  string | Accepted values include equirectangular (full spherical photo), cylindrical (panorama), and cubestrip (also known as cubemap, e.g. for synthetic or rendered content; stacked vertically with 6 faces).  Required |
| `CroppedAreaImageWidthPixels`  int64 | --- In equirectangular projection: As described in Google Photo Sphere XMP Metadata spec.  --- In cylindrical projection: Very similar to equirectangular. This value should be equal to the actual width of the image, and together with FullPanoWidthPixels, it describes the horizontal FOV of content of the image: HorizontalFOV = 360 \* CroppedAreaImageWidthPixels / FullPanoWidthPixels.  --- In cubestrip projection: This has no relationship to the pixel dimensions of the image. It is simply a representation of the horizontal FOV of the content of the image. HorizontalFOV = CroppedAreaImageWidthPixels / PixelsPerDegree, where PixelsPerDegree is defined by FullPanoWidthPixels.  Required |
| `CroppedAreaImageHeightPixels`  int64 | --- In equirectangular projection: As described in Google Photo Sphere XMP Metadata spec.  --- In cylindrical projection: This value will NOT be equal to the actual height of the image. Instead, together with FullPanoHeightPixels, it describes the vertical FOV of the image: VerticalFOV = 180 \* CroppedAreaImageHeightPixels / FullPanoHeightPixels. In other words, this value is equal to the CroppedAreaImageHeightPixels value that this image would have, if it were projected into equirectangular format while maintaining the same FullPanoWidthPixels.  --- In cubestrip projection: This has no relationship to the pixel dimensions of the image. It is simply a representation of the vertical FOV of the content of the image. VerticalFOV = CroppedAreaImageHeightPixels / PixelsPerDegree, where PixelsPerDegree is defined by FullPanoWidthPixels.  Required |
| `FullPanoWidthPixels`  int64 | --- In equirectangular projection: As described in Google Photo Sphere XMP Metadata spec.  --- In cylindrical projection: Very similar to equirectangular. This value defines a ratio of horizontal pixels to degrees in the space of the image, and in general the pixel to degree ratio in the scope of the metadata object. Concretely, PixelsPerDegree = FullPanoWidthPixels / 360. This is also equivalent to the circumference of the cylinder used to model this projection.  --- In cubestrip projection: This value has no relationship to the pixel dimensions of the image. It only defines the pixel to degree ratio in the scope of the metadata object. It represents the number of pixels in 360 degrees, so pixels per degree is then given by: PixelsPerDegree = FullPanoWidthPixels / 360. As an example, if FullPanoWidthPixels were chosen to be 3600, we would have PixelsPerDegree = 3600 / 360 = 10. An image with a vertical field of view of 65 degrees would then have a CroppedAreaImageHeightPixels value of 65 \* 10 = 650.  Required |
| `FullPanoHeightPixels`  int64 | --- In equirectangular projection: As described in Google Photo Sphere XMP Metadata spec.  --- In cylindrical projection: This value is equal to the FullPanoHeightPixels value that this image would have, if it were projected into equirectangular format while maintaining the same FullPanoWidthPixels. It is always equal to FullPanoWidthPixels / 2.  --- In cubestrip projection: This value has no relationship to the pixel dimensions of the image. It is a second, redundant representation of PixelsPerDegree. FullPanoHeightPixels = 180 \* PixelsPerDegree. It must be consistent with FullPanoWidthPixels: FullPanoHeightPixels = FullPanoWidthPixels / 2.  Required |
| `CroppedAreaLeftPixels`  int64 | Default value: `0`  --- In equirectangular projection: As described in Google Photo Sphere XMP Metadata spec.  --- In cylindrical projection: This value is equal to the CroppedAreaLeftPixels value that this image would have, if it were projected into equirectangular format while maintaining the same FullPanoWidthPixels. It is just a representation of the same angular offset that it represents in equirectangular projection in the Google Photo Sphere spec. Concretely, AngularOffsetFromLeftDegrees = CroppedAreaLeftPixels / PixelsPerDegree, where PixelsPerDegree is defined by FullPanoWidthPixels.  --- In cubestrip projection: This value has no relationship to the pixel dimensions of the image. It is just a representation of the same angular offset that it represents in equirectangular projection in the Google Photo Sphere spec. AngularOffsetFromLeftDegrees = CroppedAreaLeftPixels / PixelsPerDegree, where PixelsPerDegree is defined by FullPanoWidthPixels. |
| `CroppedAreaTopPixels`  int64 | Default value: `0`  --- In equirectangular projection: As described in Google Photo Sphere XMP Metadata spec.  --- In cylindrical projection: This value is equal to the CroppedAreaTopPixels value that this image would have, if it were projected into equirectangular format while maintaining the same FullPanoWidthPixels. It is just a representation of the same angular offset that it represents in equirectangular projection in the Google Photo Sphere spec. Concretely, AngularOffsetFromTopDegrees = CroppedAreaTopPixels / PixelsPerDegree, where PixelsPerDegree is defined by FullPanoWidthPixels.  --- In cubestrip projection: This value has no relationship to the pixel dimensions of the image. It is just a representation of the same angular offset that it represents in equirectangular projection in the Google Photo Sphere spec. AngularOffsetFromTopDegrees = CroppedAreaTopPixels / PixelsPerDegree, where PixelsPerDegree is defined by FullPanoWidthPixels. |
| `PoseHeadingDegrees`  float |  |
| `PosePitchDegrees`  float |  |
| `PoseRollDegrees`  float |  |
| `InitialViewHeadingDegrees`  float |  |
| `InitialViewPitchDegrees`  float |  |
| `InitialViewRollDegrees`  float | This is not currently supported |
| `InitialViewVerticalFOVDegrees`  float | This is deprecated. Please use InitialVerticalFOVDegrees. |
| `InitialVerticalFOVDegrees`  float | You can set the intial vertical FOV of the image. You can set either this field or InitialHorizontalFOVDegrees. |
| `InitialHorizontalFOVDegrees`  float | You can set the intial horizontal FOV of the image. You can set either this field or InitialVerticalFOVDegrees. |
| `PreProcessCropLeftPixels`  int64 |  |
| `PreProcessCropRightPixels`  int64 |  |
| `sponsor_id`  numeric string or integer | Facebook Page id that is tagged as sponsor in the photo post |
| `sponsor_relationship`  int64 | Sponsor Relationship, such as Presented By or Paid PartnershipWith |
| `tags`  list<Object> | Default value: `Vec`  Tags on this photo |
| `x`  float | The x-axis offset for the tag |
| `y`  float | The y-axis offset for the tag |
| `tag_uid`  int | The user\_id of the tagged person |
| `tag_text`  string | Text associated with the tag |
| `target_id`  int | Don't use this. Specifying a `target_id` allows you to post the photo to an object that's not the user in the access token. It only works when posting directly to the `/photos` endpoint. Instead of using this parameter you should be using the edge on an object directly, like `/page/photos`. |
| `targeting`  target | Allows you to target posts to specific audiences. Applies to Pages only |
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
| `temporary`  boolean | Default value: `false`  This is a temporary photo. `published` must be false, and you can't set `scheduled_publish_time` |
| `time_since_original_post`  int64 | Same as `backdated_time` but with a time delta instead of absolute time |
| `uid`  int | Deprecated |
| `unpublished_content_type`  enum {SCHEDULED, SCHEDULED\_RECURRING, DRAFT, PUBLISH\_PENDING, ADS\_POST, INLINE\_CREATED, PUBLISHED, REVIEWABLE\_BRANDED\_CONTENT} | Content type of the unpublished content type |
| `url`  URL | The URL of a photo that is already uploaded to the Internet. You must specify this or a file attachment |
| `user_selected_tags`  boolean | Default value: `false`  User selected tags |
| `vault_image_id`  numeric string or integer | A vault image ID to use for a photo. You can use only one of `url`, a file attachment, `vault_image_id`, or `sync_object_uuid` |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

`post_id`: string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 324 | Missing or invalid image file |
| 200 | Permissions error |
| 190 | Invalid OAuth 2.0 Access Token |
| 100 | Invalid parameter |
| 240 | Desktop applications cannot call this function for other users |
| 283 | That action requires the extended permission pages\_read\_engagement and/or pages\_read\_user\_content and/or pages\_manage\_ads and/or pages\_manage\_metadata |

You can make a POST request to `photos` edge from the following paths:

* [`/{album_id}/photos`](/docs/graph-api/reference/album/photos/)

When posting to this edge, a [Photo](/docs/graph-api/reference/photo/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `aid`  string | Legacy album ID. Deprecated |
| `allow_spherical_photo`  boolean | Default value: `false`  Indicates that we should allow this photo to be treated as a spherical photo. This will not change the behavior unless the server is able to interpret the photo as spherical, such as via Photosphere XMP metadata. Regular non-spherical photos will still be treated as regular photos even if this parameter is true. |
| `alt_text_custom`  string | Accessible alternative description for an image |
| `android_key_hash`  string | Android key hash |
| `application_id`  non-empty string | iTunes App ID. This is used by the native Share dialog that's part of iOS |
| `attempt`  int64 | Default value: `0`  Number of attempts that have been made to upload this photo |
| `audience_exp`  boolean | Default value: `false`  Audience exp |
| `backdated_time`  datetime/timestamp | A user-specified creation time for this photo |
| `backdated_time_granularity`  enum{year, month, day, hour, min, none} | Default value: `none`  Use only the part of the `backdated_time` parameter to the specified granularity |
| `caption`  string | The description of the photo |
| `composer_session_id`  string | Composer session ID |
| `direct_share_status`  int64 | The status to allow sponsor directly boost the post. |
| `feed_targeting`  feed target | Object that controls [News Feed targeting](https://www.facebook.com/help/352402648173466) for this post. Anyone in these groups will be more likely to see this post. People not in these groups will be less likely to see this post, but may still see it anyway. Any of the targeting fields shown here can be used, but none are required. `feed_targeting` applies to Pages only. |
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
| `filter_type`  int64 | Default value: `-1`  Unused? |
| `full_res_is_coming_later`  boolean | Default value: `false`  Full res is coming later |
| `initial_view_heading_override_degrees`  int64 | Manually specify the initial view heading in degrees from 0 to 360. This overrides any value present in the photo embedded metadata or provided in the spherical\_metadata parameter |
| `initial_view_pitch_override_degrees`  int64 | Manually specify the initial view pitch in degrees from -90 to 90. This overrides any value present in the photo embedded metadata or provided in the spherical\_metadata parameter |
| `initial_view_vertical_fov_override_degrees`  int64 | Manually specify the initial view vertical FOV in degrees from 60 to 120. This overrides any value present in the photo embedded metadata or provided in the spherical\_metadata parameter |
| `ios_bundle_id`  string | iOS Bundle ID |
| `is_explicit_location`  boolean | Is this an explicit location? |
| `is_explicit_place`  boolean | If set to `true`, the tag is a place, not a person |
| `manual_privacy`  boolean | Default value: `false`  Manual privacy |
| `message`  string | Deprecated. Please use the caption param instead. |
| `name`  string | Deprecated. Please use the caption param instead. |
| `no_story`  boolean | If set to `true`, this will suppress the News Feed story that is automatically generated on a profile when people upload a photo using your app. Useful for adding old photos where you may not want to generate a story |
| `offline_id`  int64 | Default value: `0`  Offline ID |
| `og_action_type_id`  numeric string | The Open Graph action type |
| `og_icon_id`  numeric string | The Open Graph icon |
| `og_object_id`  OG object ID or URL string | The Open Graph object ID |
| `og_phrase`  string | The Open Graph phrase |
| `og_set_profile_badge`  boolean | Default value: `false`  Flag to set if the post should create a profile badge |
| `og_suggestion_mechanism`  string | The Open Graph suggestion |
| `place`  place tag | Page ID of a place associated with the photo |
| `privacy`  Privacy Parameter | Determines the privacy settings of the photo. If not supplied, this defaults to the privacy level granted to the app in the Login dialog. This field cannot be used to set a more open privacy setting than the one granted |
| `profile_id`  int | Deprecated. Use `target_id` instead  Deprecated |
| `provenance_info`  JSON object | provenance\_info |
| `is_gen_ai`  boolean | is\_gen\_ai  Required |
| `provenance_type`  enum {C2PA, IPTC, EXPLICIT, INVISIBLE\_WATERMARK, C2PA\_METADATA\_EDITED, IPTC\_METADATA\_EDITED, EXPLICIT\_IMAGINE, EXPLICIT\_IMAGINE\_ME, EXPLICIT\_RESTYLE, EXPLICIT\_ANIMATE, EXPLICIT\_FACE\_SWAP, EXPLICIT\_WARDROBE, EXPLICIT\_DROP\_IN, EXPLICIT\_AI\_EDIT, EXPLICIT\_AI\_EXPANDER, EXPLICIT\_AI\_CUT, EXPLICIT\_AI\_TRANSITION, EXPLICIT\_MAGIC\_CUT, EXPLICIT\_CLIPGEN, EXPLICIT\_AI\_V2V\_RESTYLE, EXPLICIT\_RESTYLE\_EFFECTS\_MERGE, EXPLICIT\_SUBJECT\_EFFECT, EXPLICIT\_CUTOUT, EXPLICIT\_AI\_REWRITE\_WITH\_META\_AI\_INTENT, EXPLICIT\_AI\_EDIT\_PRESETS\_SHEET, NONE} | provenance\_type  Required |
| `source`  string | source |
| `proxied_app_id`  numeric string or integer | Proxied app ID |
| `published`  boolean | Default value: `true`  Set to `false` if you don't want the photo to be published immediately |
| `qn`  string | Photos waterfall ID |
| `spherical_metadata`  JSON object | A set of params describing an uploaded spherical photo. This field is not required; if it is not present we will try to generate spherical metadata from the metadata embedded in the image. If it is present, it takes precedence over any embedded metadata. Please click to the left to expand this list and see more information on each parameter. See also the Google Photo Sphere spec for more info on the meaning of the params: https://developers.google.com/streetview/spherical-metadata |
| `ProjectionType`  string | Accepted values include equirectangular (full spherical photo), cylindrical (panorama), and cubestrip (also known as cubemap, e.g. for synthetic or rendered content; stacked vertically with 6 faces).  Required |
| `CroppedAreaImageWidthPixels`  int64 | --- In equirectangular projection: As described in Google Photo Sphere XMP Metadata spec.  --- In cylindrical projection: Very similar to equirectangular. This value should be equal to the actual width of the image, and together with FullPanoWidthPixels, it describes the horizontal FOV of content of the image: HorizontalFOV = 360 \* CroppedAreaImageWidthPixels / FullPanoWidthPixels.  --- In cubestrip projection: This has no relationship to the pixel dimensions of the image. It is simply a representation of the horizontal FOV of the content of the image. HorizontalFOV = CroppedAreaImageWidthPixels / PixelsPerDegree, where PixelsPerDegree is defined by FullPanoWidthPixels.  Required |
| `CroppedAreaImageHeightPixels`  int64 | --- In equirectangular projection: As described in Google Photo Sphere XMP Metadata spec.  --- In cylindrical projection: This value will NOT be equal to the actual height of the image. Instead, together with FullPanoHeightPixels, it describes the vertical FOV of the image: VerticalFOV = 180 \* CroppedAreaImageHeightPixels / FullPanoHeightPixels. In other words, this value is equal to the CroppedAreaImageHeightPixels value that this image would have, if it were projected into equirectangular format while maintaining the same FullPanoWidthPixels.  --- In cubestrip projection: This has no relationship to the pixel dimensions of the image. It is simply a representation of the vertical FOV of the content of the image. VerticalFOV = CroppedAreaImageHeightPixels / PixelsPerDegree, where PixelsPerDegree is defined by FullPanoWidthPixels.  Required |
| `FullPanoWidthPixels`  int64 | --- In equirectangular projection: As described in Google Photo Sphere XMP Metadata spec.  --- In cylindrical projection: Very similar to equirectangular. This value defines a ratio of horizontal pixels to degrees in the space of the image, and in general the pixel to degree ratio in the scope of the metadata object. Concretely, PixelsPerDegree = FullPanoWidthPixels / 360. This is also equivalent to the circumference of the cylinder used to model this projection.  --- In cubestrip projection: This value has no relationship to the pixel dimensions of the image. It only defines the pixel to degree ratio in the scope of the metadata object. It represents the number of pixels in 360 degrees, so pixels per degree is then given by: PixelsPerDegree = FullPanoWidthPixels / 360. As an example, if FullPanoWidthPixels were chosen to be 3600, we would have PixelsPerDegree = 3600 / 360 = 10. An image with a vertical field of view of 65 degrees would then have a CroppedAreaImageHeightPixels value of 65 \* 10 = 650.  Required |
| `FullPanoHeightPixels`  int64 | --- In equirectangular projection: As described in Google Photo Sphere XMP Metadata spec.  --- In cylindrical projection: This value is equal to the FullPanoHeightPixels value that this image would have, if it were projected into equirectangular format while maintaining the same FullPanoWidthPixels. It is always equal to FullPanoWidthPixels / 2.  --- In cubestrip projection: This value has no relationship to the pixel dimensions of the image. It is a second, redundant representation of PixelsPerDegree. FullPanoHeightPixels = 180 \* PixelsPerDegree. It must be consistent with FullPanoWidthPixels: FullPanoHeightPixels = FullPanoWidthPixels / 2.  Required |
| `CroppedAreaLeftPixels`  int64 | Default value: `0`  --- In equirectangular projection: As described in Google Photo Sphere XMP Metadata spec.  --- In cylindrical projection: This value is equal to the CroppedAreaLeftPixels value that this image would have, if it were projected into equirectangular format while maintaining the same FullPanoWidthPixels. It is just a representation of the same angular offset that it represents in equirectangular projection in the Google Photo Sphere spec. Concretely, AngularOffsetFromLeftDegrees = CroppedAreaLeftPixels / PixelsPerDegree, where PixelsPerDegree is defined by FullPanoWidthPixels.  --- In cubestrip projection: This value has no relationship to the pixel dimensions of the image. It is just a representation of the same angular offset that it represents in equirectangular projection in the Google Photo Sphere spec. AngularOffsetFromLeftDegrees = CroppedAreaLeftPixels / PixelsPerDegree, where PixelsPerDegree is defined by FullPanoWidthPixels. |
| `CroppedAreaTopPixels`  int64 | Default value: `0`  --- In equirectangular projection: As described in Google Photo Sphere XMP Metadata spec.  --- In cylindrical projection: This value is equal to the CroppedAreaTopPixels value that this image would have, if it were projected into equirectangular format while maintaining the same FullPanoWidthPixels. It is just a representation of the same angular offset that it represents in equirectangular projection in the Google Photo Sphere spec. Concretely, AngularOffsetFromTopDegrees = CroppedAreaTopPixels / PixelsPerDegree, where PixelsPerDegree is defined by FullPanoWidthPixels.  --- In cubestrip projection: This value has no relationship to the pixel dimensions of the image. It is just a representation of the same angular offset that it represents in equirectangular projection in the Google Photo Sphere spec. AngularOffsetFromTopDegrees = CroppedAreaTopPixels / PixelsPerDegree, where PixelsPerDegree is defined by FullPanoWidthPixels. |
| `PoseHeadingDegrees`  float |  |
| `PosePitchDegrees`  float |  |
| `PoseRollDegrees`  float |  |
| `InitialViewHeadingDegrees`  float |  |
| `InitialViewPitchDegrees`  float |  |
| `InitialViewRollDegrees`  float | This is not currently supported |
| `InitialViewVerticalFOVDegrees`  float | This is deprecated. Please use InitialVerticalFOVDegrees. |
| `InitialVerticalFOVDegrees`  float | You can set the intial vertical FOV of the image. You can set either this field or InitialHorizontalFOVDegrees. |
| `InitialHorizontalFOVDegrees`  float | You can set the intial horizontal FOV of the image. You can set either this field or InitialVerticalFOVDegrees. |
| `PreProcessCropLeftPixels`  int64 |  |
| `PreProcessCropRightPixels`  int64 |  |
| `sponsor_id`  numeric string or integer | Facebook Page id that is tagged as sponsor in the photo post |
| `sponsor_relationship`  int64 | Sponsor Relationship, such as Presented By or Paid PartnershipWith |
| `tags`  list<Object> | Tags on this photo |
| `x`  float | The x-axis offset for the tag |
| `y`  float | The y-axis offset for the tag |
| `tag_uid`  int | The user\_id of the tagged person |
| `tag_text`  string | Text associated with the tag |
| `target_id`  int | Don't use this. Specifying a `target_id` allows you to post the photo to an object that's not the user in the access token. It only works when posting directly to the `/photos` endpoint. Instead of using this parameter you should be using the edge on an object directly, like `/page/photos`. |
| `targeting`  target | Allows you to target posts to specific audiences. Applies to Pages only |
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
| `time_since_original_post`  int64 | Same as `backdated_time` but with a time delta instead of absolute time |
| `uid`  int | Deprecated |
| `unpublished_content_type`  enum {SCHEDULED, SCHEDULED\_RECURRING, DRAFT, PUBLISH\_PENDING, ADS\_POST, INLINE\_CREATED, PUBLISHED, REVIEWABLE\_BRANDED\_CONTENT} | Content type of the unpublished content type |
| `url`  string | The URL of a photo that is already uploaded to the Internet. You must specify this or a file attachment |
| `user_selected_tags`  boolean | Default value: `false`  User selected tags |
| `vault_image_id`  numeric string or integer | A vault image ID to use for a photo. You can use only one of `url`, a file attachment, `vault_image_id`, or `sync_object_uuid` |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

`post_id`: token with structure: Post ID,

}

### Error Codes

| Error | Description |
| --- | --- |
| 190 | Invalid OAuth 2.0 Access Token |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 200 | Permissions error |
| 100 | Invalid parameter |
| 220 | Album or albums not visible |
| 324 | Missing or invalid image file |

## Updating

You can't perform this operation on this endpoint.

## Deleting

An app can delete any photos it published, or a page-management app can delete a Photo published to a page that the app manages.

### Permissions

* To delete a User's photo, a User access token with `publish_actions`[permission](/docs/authentication/permissions/) is required.
* To delete a Page's photo a Page access token and `publish_pages`[permission](/docs/authentication/permissions/) is required.
* To delete a User's photo on a Page a Page access token is required.

You can delete a [Photo](/docs/graph-api/reference/photo/) by making a DELETE request to [`/{photo_id}`](/docs/graph-api/reference/photo/).

### Parameters

This endpoint doesn't have any parameters.

### Return Type

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 190 | Invalid OAuth 2.0 Access Token |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 200 | Permissions error |

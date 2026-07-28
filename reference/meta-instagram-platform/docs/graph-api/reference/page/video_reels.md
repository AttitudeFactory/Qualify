Graph API Version

[v25.0](#)

# Page Video Reels

## Reading

You can't perform this operation on this endpoint.

## Creating

You can make a POST request to `video_reels` edge from the following paths:

* [`/{page_id}/video_reels`](/docs/graph-api/reference/page/video_reels/)

When posting to this edge, no Graph object will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `description`  UTF-8 string | description  Supports Emoji |
| `feed_targeting`  feed target | feed\_targeting |
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
| `is_ai_generated`  boolean | A boolean flag for developers to self-claim whether the video was created with AI |
| `place`  numeric string | place |
| `scheduled_publish_time`  datetime/timestamp | scheduled\_publish\_time |
| `targeting`  target | targeting |
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
| `title`  UTF-8 string | title  Supports Emoji |
| `upload_phase`  enum {START, FINISH} | upload\_phase  Required |
| `video_id`  numeric string or integer | video\_id |
| `video_state`  enum {DRAFT, PUBLISHED, SCHEDULED} | video\_state |

### Return Type

Struct {

`video_id`: numeric string,

`upload_url`: uri,

`success`: bool,

`message`: string,

`post_id`: numeric string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 613 | Calls to this api have exceeded the rate limit. |
| 190 | Invalid OAuth 2.0 Access Token |
| 200 | Permissions error |
| 100 | Invalid parameter |
| 6000 | There was a problem uploading your video file. Please try again with another file. |
| 104 | Incorrect signature |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

Graph API Version

[v25.0](#)

# Page Video Copyrights

## Reading

You can't perform this operation on this endpoint.

## Creating

You can make a POST request to `video_copyrights` edge from the following paths:

* [`/{page_id}/video_copyrights`](/docs/graph-api/reference/page/video_copyrights/)

When posting to this edge, a [VideoCopyright](/docs/graph-api/reference/video-copyright/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `attribution_id`  numeric string or integer | For Rights Manager Lite, please provide ID of the Page where the attribution should link to. Provide 0 if you want to unlink the reference file with its current attribution. For Rights Manager Pro, please provide ID of the attribution to be displayed for valid monitored videos matching this content. |
| `content_category`  enum {episode, movie, web} | A string array representing the reference file's content category |
| `copyright_content_id`  numeric string or integer | This is the ID of the content which needs to be copyrighted. It could be an ID of a video, or an ID of a live video.  Required |
| `excluded_ownership_countries`  list<UTF-8 encoded string> | A string array of [ISO 3166 format country codes](http://l.facebook.com/l.php?u=http%3A%2F%2Fwww.iso.org%2Fiso%2Fcountry_codes%2Fiso_3166_code_lists%2Fcountry_names_and_code_elements.htm&h=AUC7srGBVLb4QdkOJx-SaWBdXFdHBb_9hulzZHGn2HEwCrNyRaQk27BUjohESiC3v5bPU8pddEDpBM03bYLFdAqbmjgDL5TwCKStUJCCXilDcQFheJKJHoXQTgMQyw9hzLre22ozy63kJy1d), where the owner does not own the rights to the content |
| `excluded_ownership_segments`  list<Video Match Segment> | An array of match segments to exclude from the matching algorithm |
| `start_time_in_sec`  float | Required |
| `media_type`  enum {VIDEO\_AND\_AUDIO, VIDEO\_ONLY, AUDIO\_ONLY} | Required |
| `duration_in_sec`  float | Required |
| `segment_source`  enum {PUBLISHER\_DEFINED, PAUSE\_LIVE\_MONITORING, LABEL\_MUTED, PUBLISHER\_MUTED, MUSIC\_RESTRICTION\_MUTED\_STILL\_VIDEO, MUSIC\_RESTRICTION\_MUTED\_MULTI\_TRACK, AUDIO\_LIBRARY\_USAGE, MELODY, INELIGIBLE\_CONTENT} | Default value: `PUBLISHER_DEFINED` |
| `is_reference_disabled`  boolean | If true, stop creating matches for the reference file. |
| `is_reference_video`  boolean | Default value: `false`  True indicates that the content is used only as a reference video, and is not available for consumption on Facebook. |
| `monitoring_type`  enum {VIDEO\_AND\_AUDIO, VIDEO\_ONLY, AUDIO\_ONLY} | Setting to indicate whether the content has copyright ownership on video, audio, or both. |
| `ownership_countries`  list<UTF-8 encoded string> | A string array of [ISO 3166 format country codes](http://l.facebook.com/l.php?u=http%3A%2F%2Fwww.iso.org%2Fiso%2Fcountry_codes%2Fiso_3166_code_lists%2Fcountry_names_and_code_elements.htm&h=AUBuH7O21pGwr-ah8NX6RnxeNeLY8r_RIG18xLrWH0ARYzsuSza_35yl50IHrPt2JoByyZziB7t1kWGnKFPuhRUlKDWj3CTuZ_PzQfHLCPZJnzjwC5vmUG_g1Vydn9hrRaG_Up7ZMjzREZYi), where the owner owns the rights of the content |
| `rule_id`  numeric string or integer | A copyright rule to be applied to the copyrighted content. |
| `tags`  array<string> | The tags/keywords associated with the copyright |
| `whitelisted_ids`  list<numeric string> | A list of page IDs or user IDs, who are allowed to use the copyrighted content. |
| `whitelisted_ig_user_ids`  list<numeric string> | A list of instagram user IDs who are allowed to use the copyrighted content. |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 283 | That action requires the extended permission pages\_read\_engagement and/or pages\_read\_user\_content and/or pages\_manage\_ads and/or pages\_manage\_metadata |
| 100 | Invalid parameter |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

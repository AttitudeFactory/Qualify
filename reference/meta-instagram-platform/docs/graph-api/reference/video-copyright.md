Graph API Version

[v25.0](#)

# Video Copyright

## Reading

A video copyright

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bvideo-copyright-id%7D&version=v25.0)

```
GET /v25.0/{video-copyright-id} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{video-copyright-id}',
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
    "/{video-copyright-id}",
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
    "/{video-copyright-id}",
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
                               initWithGraphPath:@"/{video-copyright-id}"
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
| `id`  numeric string | The video copyright ID  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `content_category`  enum | The content category of the reference file.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `copyright_content_id`  numeric string | The copyright content ID  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `creator`  [User](https://developers.facebook.com/docs/graph-api/reference/user/) | The account that created the copyright  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `excluded_ownership_segments`  list<VideoCopyrightSegment> | The list of audio and video segments excluded from copyright monitoring. This includes both self-defined excluded segments as well as system generated excluded segments. |
| `in_conflict`  bool | Whether the video copyright is in active conflict with another rights owner's video copyright.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `monitoring_status`  enum | Whether the video is monitored successfully for copyright. The status could be NOT\_EXAMINED, COPYRIGHTED, and ERROR.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `monitoring_type`  enum | Whether the video is monitored for VIDEO, AUDIO, or VIDEO\_AND\_AUDIO  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `ownership_countries`  VideoCopyrightGeoGate | Two string arrays of [ISO 3166 format country codes](http://l.facebook.com/l.php?u=http%3A%2F%2Fwww.iso.org%2Fiso%2Fcountry_codes%2Fiso_3166_code_lists%2Fcountry_names_and_code_elements.htm&h=AUCQOVana8_CLBzw9zU_BuPfJMBBFj2e5u0-mAj7OMLyS_GHWR0RDT34akr5U4LjcZItkHeOvWe9Dw_rxrA5BzW3aaQ1rTtxq6U5y7Dx1vvo9mTfDT4B8y37Oggh0rpV4IWajSLifeTF8Wavu71-WJ28ZASPdw). `included_countries` are where the owner owns the rights to the content. `excluded_countries` are where the owner does not own the rights to the content. When both lists are empty, rights ownership is worldwide.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `reference_file`  CopyrightReferenceContainer | The reference file  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `reference_file_disabled`  bool | Whether the reference file is disabled.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `reference_file_disabled_by_ops`  bool | Whether the reference file has been disabled by ops.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `reference_owner_id`  string | The ID of the reference video owner  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `rule_ids`  [list<VideoCopyrightRule>](https://developers.facebook.com/docs/graph-api/reference/video-copyright-rule/) | A list of matching rules applied to the copyrighted content  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `tags`  list<string> | The tags/keywords associated with the copyright |
| `whitelisted_ids`  list<numeric string> | A list of page IDs or user IDs, who are allowed to use the copyrighted content.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

### Edges

| Edge | Description |
| --- | --- |
| [`update_records`](/docs/graph-api/reference/video-copyright/update_records/)  Edge<MediaCopyrightUpdateRecord> | Update records of the copyright |

### Error Codes

| Error | Description |
| --- | --- |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |

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
| `excluded_ownership_countries`  list<UTF-8 encoded string> | A string array of [ISO 3166 format country codes](http://l.facebook.com/l.php?u=http%3A%2F%2Fwww.iso.org%2Fiso%2Fcountry_codes%2Fiso_3166_code_lists%2Fcountry_names_and_code_elements.htm&h=AUBpP_KQgYG80tTiejxECa80EejXjkktiFLAHdkZNbR0pw88Qaz3dimgrldxcChTF1RLEi8q1nINnLPA_DphJU1RU41m98ZCI_KlVJsEDEApT6RC466jepeU8XGp-Z_Z6pITXjG-FCwjw9Sn), where the owner does not own the rights to the content |
| `excluded_ownership_segments`  list<Video Match Segment> | An array of match segments to exclude from the matching algorithm |
| `start_time_in_sec`  float | Required |
| `media_type`  enum {VIDEO\_AND\_AUDIO, VIDEO\_ONLY, AUDIO\_ONLY} | Required |
| `duration_in_sec`  float | Required |
| `segment_source`  enum {PUBLISHER\_DEFINED, PAUSE\_LIVE\_MONITORING, LABEL\_MUTED, PUBLISHER\_MUTED, MUSIC\_RESTRICTION\_MUTED\_STILL\_VIDEO, MUSIC\_RESTRICTION\_MUTED\_MULTI\_TRACK, AUDIO\_LIBRARY\_USAGE, MELODY, INELIGIBLE\_CONTENT} | Default value: `PUBLISHER_DEFINED` |
| `is_reference_disabled`  boolean | If true, stop creating matches for the reference file. |
| `is_reference_video`  boolean | Default value: `false`  True indicates that the content is used only as a reference video, and is not available for consumption on Facebook. |
| `monitoring_type`  enum {VIDEO\_AND\_AUDIO, VIDEO\_ONLY, AUDIO\_ONLY} | Setting to indicate whether the content has copyright ownership on video, audio, or both. |
| `ownership_countries`  list<UTF-8 encoded string> | A string array of [ISO 3166 format country codes](http://l.facebook.com/l.php?u=http%3A%2F%2Fwww.iso.org%2Fiso%2Fcountry_codes%2Fiso_3166_code_lists%2Fcountry_names_and_code_elements.htm&h=AUAv4wCUJpSz1iAAxFQfXrteArPB2aGJVTNhJUlXcNnE6I4OlVNPiXIoleTu8vcFyT6aH_plezyXz_cdIuGEMWuaVH6QkRAabuFq_CHg8xQM21KfKqbFAGU_WFlUelWGHlWAN9YBP7V9KcgLgYZ3nJNFTaMM9w), where the owner owns the rights of the content |
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

You can update a [VideoCopyright](/docs/graph-api/reference/video-copyright/) by making a POST request to [`/{video_copyright_id}`](/docs/graph-api/reference/video-copyright/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `append_excluded_ownership_segments`  boolean | If true, append the excluded ownership segments instead of replacing them |
| `attribution_id`  numeric string or integer | The ID of the attribution to be displayed for valid monitored videos matching this content. |
| `content_category`  enum {episode, movie, web} | The content category of the copyrighted reference file. |
| `excluded_ownership_countries`  list<UTF-8 encoded string> | A string array of [ISO 3166 format country codes](http://l.facebook.com/l.php?u=http%3A%2F%2Fwww.iso.org%2Fiso%2Fcountry_codes%2Fiso_3166_code_lists%2Fcountry_names_and_code_elements.htm&h=AUBOUsP_1XrMCzfS52vMG9xEVeChxOoJ8Q6CWTeDBsk4aYevqSB2WJbwnjlBLtOwZTm3UZBKZfrx_IgTY3HNZF87Y__GDlNwWbhrJW50Q4Cjkl6JCNNSb0JRIT1UIy0LYK9qYTmViVPI8P8G), where the owner does not own the rights to the content |
| `excluded_ownership_segments`  list<Video Match Segment> | An array of match segments to exclude from the matching algorithm. System generated excluded segments may not be replaced. |
| `start_time_in_sec`  float | Required |
| `media_type`  enum {VIDEO\_AND\_AUDIO, VIDEO\_ONLY, AUDIO\_ONLY} | Required |
| `duration_in_sec`  float | Required |
| `segment_source`  enum {PUBLISHER\_DEFINED, PAUSE\_LIVE\_MONITORING, LABEL\_MUTED, PUBLISHER\_MUTED, MUSIC\_RESTRICTION\_MUTED\_STILL\_VIDEO, MUSIC\_RESTRICTION\_MUTED\_MULTI\_TRACK, AUDIO\_LIBRARY\_USAGE, MELODY, INELIGIBLE\_CONTENT} | Default value: `PUBLISHER_DEFINED` |
| `is_reference_disabled`  boolean | If true, stop creating matches for the reference file. |
| `monitoring_type`  enum {VIDEO\_AND\_AUDIO, VIDEO\_ONLY, AUDIO\_ONLY} | Setting to indicate whether the content has copyright ownership on video, audio, or both. |
| `ownership_countries`  list<UTF-8 encoded string> | A string array of [ISO 3166 format country codes](http://l.facebook.com/l.php?u=http%3A%2F%2Fwww.iso.org%2Fiso%2Fcountry_codes%2Fiso_3166_code_lists%2Fcountry_names_and_code_elements.htm&h=AUCHQiFONAcjw6jF3OZ9WY5Xquz62ve-oRaVz0Hq3Qj9uTUTj7wi2ATN_0z8FXo2uSnBDukH9SfLcypJqgoIpRejEtf5a0RguusdcRQhGahIKJqtxIFIA9VODpcCXfc9ZcAngB4rVz0AZgos), where the owner owns the rights to the content |
| `rule_id`  numeric string or integer | A copyright policy to be applied to the copyrighted content. |
| `whitelisted_ids`  list<numeric string> | A list of page IDs or user IDs, who are allowed to use the copyrighted content. |
| `whitelisted_ig_user_ids`  list<numeric string> | A list of Instagram user IDs who are allowed to use the copyrighted content. |

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

## Deleting

You can't perform this operation on this endpoint.

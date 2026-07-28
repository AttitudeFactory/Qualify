Graph API Version

[v25.0](#)

# Story Attachment

## Reading

Attachment on a story or comment

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_StoryAttachment%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_StoryAttachment} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_StoryAttachment}',
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
    "...?fields={fieldname_of_type_StoryAttachment}",
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
    "...?fields={fieldname_of_type_StoryAttachment}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_StoryAttachment}"
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
| `description`  string | Text accompanying the attachment  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `description_tags`  [list<EntityAtTextRange>](https://developers.facebook.com/docs/graph-api/reference/entity-at-text-range/) | Profiles tagged in the text accompanying the attachment  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `media`  [StoryAttachmentMedia](https://developers.facebook.com/docs/graph-api/reference/story-attachment-media/) | Media object (photo, link etc.) contained in the attachment  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `media_type`  string | Type of the media such as (photo, video, link etc) |
| `target`  [StoryAttachmentTarget](https://developers.facebook.com/docs/graph-api/reference/story-attachment-target/) | Object that the attachment links to  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `title`  string | Title of the attachment  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `type`  string | Type of the attachment. Possible types include: `album`, `animated_image_autoplay`, `checkin`, `cover_photo`, `event`, `link`, `multiple`, `music`, `note`, `offer`, `photo`, `profile_media`, `status`, `video`, `video_autoplay`, etc.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `unshimmed_url`  uri | Unshimmed URL of the attachment |
| `url`  uri | URL of the attachment  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

### Edges

| Edge | Description |
| --- | --- |
| [`subattachments`](/docs/graph-api/reference/story-attachment/subattachments/)  Edge<StoryAttachment> | Any subattachments associated with the attachment  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

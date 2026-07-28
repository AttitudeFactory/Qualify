Graph API Version

[v25.0](#)

# Comment

## Reading

A Facebook comment

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Feature Permissions

| Name | Description |
| --- | --- |
| Page Public Content Access | This [feature permission](/docs/apps/review/feature/) may be required. |

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bcomment-id%7D&version=v25.0)

```
GET /v25.0/{comment-id} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{comment-id}',
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
    "/{comment-id}",
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
    "/{comment-id}",
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
                               initWithGraphPath:@"/{comment-id}"
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
| `id`  token with structure: Comment ID | The comment ID |
| `admin_creator`  [User](https://developers.facebook.com/docs/graph-api/reference/user/) | For a comment made by a page, the page admin who wrote it. A page access token is required to access this field. |
| `application`  [Application](https://developers.facebook.com/docs/graph-api/reference/application/) | The app this comment was published by |
| `attachment`  [StoryAttachment](https://developers.facebook.com/docs/graph-api/reference/story-attachment/) | Link or photo attached to the comment |
| `can_comment`  bool | Whether the viewer can reply to this comment |
| `can_hide`  bool | Whether the viewer can hide this comment from everyone except the comment author and the author's friends. This can only be true for comments on Page posts |
| `can_like`  bool | Whether the viewer can like this comment |
| `can_remove`  bool | Whether the viewer can remove this comment |
| `can_reply_privately`  bool | Whether the page viewer can send a private reply to this comment |
| `comment_count`  unsigned int32 | Number of replies to this comment |
| `created_time`  datetime | The time this comment was made  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `from`  User|Page | The profile that made this comment  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `is_hidden`  bool | Whether this comment is hidden from everyone except the comment author and the author's friends |
| `is_private`  bool | Whether the comment is a private comment |
| `like_count`  unsigned int32 | Number of times this comment was liked |
| `live_broadcast_timestamp`  unsigned int32 | Time the comment was made on a live video |
| `message`  string | The comment text  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `message_tags`  [list<EntityAtTextRange>](https://developers.facebook.com/docs/graph-api/reference/entity-at-text-range/) | Profiles tagged in mentions in the message |
| `object` | The object the comment is on |
| `parent`  [Comment](https://developers.facebook.com/docs/graph-api/reference/comment/) | For comment replies, the comment this is a reply to |
| `permalink_url`  uri | The permanent static URL to the comment |
| `private_reply_conversation` | If private reply was sent to this comment, gets private conversation between the page and author of the comment that was started by private reply |
| `user_likes`  bool | Whether the viewer has liked this comment |

### Edges

| Edge | Description |
| --- | --- |
| [`comments`](/docs/graph-api/reference/comment/comments/)  Edge<Comment> | Comments made on this |
| [`likes`](/docs/graph-api/reference/comment/likes/)  Edge<Profile> | People who like this |
| [`reactions`](/docs/graph-api/reference/comment/reactions/)  Edge<Profile> | People who reacted on this |

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 200 | Permissions error |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 190 | Invalid OAuth 2.0 Access Token |
| 283 | That action requires the extended permission pages\_read\_engagement and/or pages\_read\_user\_content and/or pages\_manage\_ads and/or pages\_manage\_metadata |
| 2500 | Error parsing graph query |
| 459 | The session is invalid because the user has been checkpointed |
| 613 | Calls to this api have exceeded the rate limit. |
| 210 | User not visible |

## Creating

You can make a POST request to `comments` edge from the following paths:

* [`/{video_id}/comments`](/docs/graph-api/reference/video/comments/)

When posting to this edge, a [Comment](/docs/graph-api/reference/comment/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `attachment_id`  numeric string or integer | ID for a photo attachment to associate with this |
| `attachment_share_url`  URL | Link to set the comment attachment to. Does not include the url in the message |
| `attachment_url`  URL | Link to set the comment attachment to |
| `is_offline`  boolean | Whether the comment was originally made while offline |
| `message`  UTF-8 string | Same as the text param  Supports Emoji |
| `text`  UTF-8 string | The text of the comment that allows emoji  Supports Emoji |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: token with structure: Comment ID,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 190 | Invalid OAuth 2.0 Access Token |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 200 | Permissions error |
| 1705 | There was an error during posting. |
| 459 | The session is invalid because the user has been checkpointed |

## Updating

You can update a [Comment](/docs/graph-api/reference/comment/) by making a POST request to [`/{comment_id}`](/docs/graph-api/reference/comment/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `attachment_id`  numeric string or integer | ID for a photo attachment to associate with this |
| `attachment_share_url`  URL | Link to set the comment attachment to. Does not include the url in the message. |
| `attachment_url`  URL | Link to set the comment attachment to. |
| `is_hidden`  boolean | Is this comment hidden? Only applicable to Page comments |
| `message`  UTF-8 string | The text in the new comment message  Supports Emoji |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 100 | Invalid parameter |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 190 | Invalid OAuth 2.0 Access Token |
| 210 | User not visible |

## Deleting

You can delete a [Comment](/docs/graph-api/reference/comment/) by making a DELETE request to [`/{comment_id}`](/docs/graph-api/reference/comment/).

### Parameters

This endpoint doesn't have any parameters.

### Return Type

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 200 | Permissions error |
| 100 | Invalid parameter |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 190 | Invalid OAuth 2.0 Access Token |

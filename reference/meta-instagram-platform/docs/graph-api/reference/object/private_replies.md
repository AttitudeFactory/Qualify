This document refers to a feature that was removed after [Graph API v3.2.](/docs/graph-api/reference/v3.2/object/private_replies)

Graph API Version

[v25.0](#)

# `/{object-id}/private_replies`

This edge allows Pages to reply to Post Comments and Visitor Posts with a private Message. It can be used with the following nodes:

* [`Comment`](/docs/graph-api/reference/comment)
* [`Post`](/docs/graph-api/reference/post)

Please note that a comment or post may only be replied to once.

## Reading

You can't read using this edge.

## Publishing

To reply with a private Message:

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK

```
POST /v25.0/{object-id}/private_replies HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->post(
    '/{object-id}/private_replies',
    array (),
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
    "/{object-id}/private_replies",
    "POST",
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
    "/{object-id}/private_replies",
    null,
    HttpMethod.POST,
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
                               initWithGraphPath:@"/{object-id}/private_replies"
                                      parameters:params
                                      HTTPMethod:@"POST"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

Private replies to messages are allowed for only a limited time. The actual limit, usually several months, is subject to change.

### Permissions

This edge requires a Page access token with the following permissions:

* `read_page_mailboxes`

### Fields

| Parameter | Description | Type |
| --- | --- | --- |
| `id` | The ID of the Page Comment or Visitor Post that you are replying to. | `string` |
| `message` | The text of the reply. **This field is required**. | `string` |

### Response

If successful, you will receive a response with the following fields. In addition, this endpoint supports [read-after-write](/docs/graph-api/using-graph-api#read-after-write) and can immediately read the node represented by `id` in the return type.

| Field | Description | Type |
| --- | --- | --- |
| id | The ID of the newly created Message. | `string` |
| user\_id | The `app_scoped_user_id` of the visitor. | `string` |

## Deleting

You can't delete using this edge.

## Updating

You can't update using this edge.

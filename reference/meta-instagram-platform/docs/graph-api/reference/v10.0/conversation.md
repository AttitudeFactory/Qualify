Graph API Version

[v25.0](#)

# Conversation `/{conversation-id}`

A Messenger conversation between a person and a Facebook Page or an Instagram Professional Account.

## Reading

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bconversation-id%7D&version=v25.0)

```
GET /v25.0/{conversation-id} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{conversation-id}',
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
    "/{conversation-id}",
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
    "/{conversation-id}",
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
                               initWithGraphPath:@"/{conversation-id}"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Permissions

* A Page access token requested by a person who can perform the [`MESSAGING` task](/docs/pages/overview-1#tasks) on the Page being queried
* The [`pages_messaging` permission](/docs/apps/review/login-permissions#reference-pages_messaging)
* The [`pages_manage_metadata` permission](/docs/apps/review/login-permissions#reference-pages_manage_metadata)

For Instagram Messaging, you will also need:

* The [`instagram_basic` permission](/docs/apps/review/login-permissions#reference-instagram_basic)
* The [`instagram_manage_messages` permission](/docs/apps/review/login-permissions#reference-instagram_manage_messages)

### Limitations

* When querying this endpoint for Instagram Messaging, all messages for the conversation will be returned. However, you will only be able to query data for the 20 most recent messages in the conversation. If a message is not within the 20 most recent, an error will be returned stating that the message has been deleted.

### Fields

Name | Description || `id` *string* | The ID for the conversation |
| `is_owner` *boolean* | Indicates whether the app making this request is the [thread owner](https://developers.facebook.com/docs/messenger-platform/conversation-routing#conversation-control-and-thread-owner) responsible for replying to the conversation   Note: This field will only be returned if the associated Facebook Page or Instagram account has enabled [Conversation Routing](https://developers.facebook.com/docs/messenger-platform/conversation-routing/) |
| `messages` *string* | Messages within the conversation |
| `participants` *object* `id`   `email`  *Page messaging only*  `name`  *Page messaging only*  `username`  *Instagram Messaging only* | Participants in the conversation   Instagram-Scoped ID or Page-scoped ID for a person or Instagram ID for your Instagram Professional account or the Page ID.  Email for the person or Page   Name for the person or Page   Instagram username for a person or your Instagram Profession account |
| `updated_time` *datetime* | The time when the last message was added to the conversation |

To get information about a specific message within a conversation, send a request to the [Message endpoint](https://developers.facebook.com/docs/graph-api/reference/message).

## Publishing

You can't publish using this edge.

Use the [Messenger Platform](https://developers.facebook.com/docs/messenger-platform/reference/send-api/) to send [Templates](/docs/messenger-platform/send-messages/templates), [Quick Replies](/docs/messenger-platform/send-messages/quick-replies), and more.

## Deleting

You can't delete using this edge.

## Updating

You can't update using this edge.

## Edges

Name | Description | Used to Publish || [`/messages`](/docs/graph-api/reference/conversation/messages/) | List of all messages in the conversation | Replies (by Pages only) |

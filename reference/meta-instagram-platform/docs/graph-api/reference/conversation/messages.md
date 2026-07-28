Graph API Version

[v25.0](#)

# Graph API Reference [`/{conversation-id}`](/docs/graph-api/reference/conversation/)`/messages`

The messages in a conversation between a person and a Facebook Page or Instagram Professional account.

## Reading

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bconversation-id%7D%2Fmessages&version=v25.0)

```
GET /v25.0/{conversation-id}/messages HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{conversation-id}/messages',
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
    "/{conversation-id}/messages",
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
    "/{conversation-id}/messages",
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
                               initWithGraphPath:@"/{conversation-id}/messages"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Permissions

* A Page access token requested by a person who can perform the `MESSAGING` task on the Page
* The `pages_messaging` permission
* For Instagram Messaging, the `instagram_manage_messages` permission is also required

### Fields

Returns an array of [Message objects](https://developers.facebook.com/docs/graph-api/reference/message) with additional fields:

Name | Description | Type || Vector | Vector |

## Send a message

You cannot send a message to this enpoint. Use [Send API](https://developers.facebook.com/docs/messenger-platform/reference/send-api/) instead.

## Delete

You cannot delete this endpoint.

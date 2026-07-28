Graph API Version

[v25.0](#)

# Graph API Reference [`/{message-id}`](/docs/graph-api/reference/message/)`/attachments`

Files attached to a message. This is a Pages-only endpoint.

## Reading

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bmessage-id%7D%2Fattachments&version=v25.0)

```
GET /v25.0/{message-id}/attachments HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{message-id}/attachments',
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
    "/{message-id}/attachments",
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
    "/{message-id}/attachments",
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
                               initWithGraphPath:@"/{message-id}/attachments"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

## Permissions

This edge requires a Page access token with the following permissions:

* `pages_messaging`

Apps in [Development Mode](/docs/apps/managing-development-cycle), are restricted to message people that have a role in the app.

### Fields

Name | Description | Type || `id` | The attachment ID. | `string` |
| `mime_type` | The file MIME type. | `string` |
| `name` | The filename of the attachment. | `string` |
| `size` | The file size in bytes. | `int` |
| `file_url` | The URL of the attachment. | `string` |

## Publishing

You can't publish using this edge.

## Deleting

You can't delete using this edge.

## Updating

You can't update using this edge.

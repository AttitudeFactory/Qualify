Graph API Version

[v25.0](#)

# Page Conversations

## Reading

Get a list of conversations between people and your Page, your Business Page, or your Instagram Professional account.

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Permissions

For Messenger conversations between people and your Page, your app will need:

* A Page access token requested by a person who can perform the [`MESSAGING` task](/docs/pages/overview-1#tasks) on the Page
* The [`pages_manage_metadata`, `pages_read_engagement`, and `pages_messaging` permissions](/docs/pages/overview-1#permissions)

For Instagram Messaging conversations between people and your Instagram Professional account, your app will need:

* A Page access token requested by a person who can perform the [`MESSAGING` task](/docs/pages/overview-1#tasks) on the Page linked to your Instagram Business account
* The `instagram_basic`, `instagram_manage_messages`, and `pages_manage_metadata` permissions
* Your app must be owned by a verified business

### Limitations

* Time-based pagination is not available for the conversations endpoint.

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-id%7D%2Fconversations&version=v25.0)

```
GET /v25.0/{page-id}/conversations HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/conversations',
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
    "/{page-id}/conversations",
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
    "/{page-id}/conversations",
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
                               initWithGraphPath:@"/{page-id}/conversations"
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

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `folder`  string | folder |
| `platform`  enum {INSTAGRAM, MESSENGER} | platform |
| `user_id`  string | user\_id |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of UnifiedThread nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 80006 | There have been too many messenger api calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 200 | Permissions error |
| 100 | Invalid parameter |
| 613 | Calls to this api have exceeded the rate limit. |
| 230 | Permissions disallow message to user |
| 190 | Invalid OAuth 2.0 Access Token |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 104 | Incorrect signature |
| 2500 | Error parsing graph query |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

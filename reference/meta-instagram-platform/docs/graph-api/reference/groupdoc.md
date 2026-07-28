Graph API Version

[v25.0](#)

# Group Doc `/{group-doc-id}`

Represents a doc within a Facebook group. The `/{group-doc-id}` node returns a single doc.

## Reading

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bgroup-doc-id%7D&version=v25.0)

```
GET /v25.0/{group-doc-id} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{group-doc-id}',
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
    "/{group-doc-id}",
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
    "/{group-doc-id}",
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
                               initWithGraphPath:@"/{group-doc-id}"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Fields

Property Name | Description | Type || `id` | The group doc ID. | `string` |
| `from` | The profile that created this doc. | [`User`](/docs/graph-api/reference/user/)`|`[`Page`](/docs/graph-api/reference/page/) |
| `subject` | The title of the doc. | `string` |
| `message` | The body of the doc. This string will contain HTML for any formatting in the doc, and will be HTML encoded. | `string` |
| `icon` | The URL for the doc's icon | `string` |
| `created_time` | When the doc was created. | `datetime` |
| `updated_time` | The last time the doc was changed. | `datetime` |
| `revision` | An ID representing the current doc revision. | `int` |
| `can_edit` | Whether the session user can edit this doc. | `boolean` |
| `can_delete` | Whether the session user can delete this doc (on Facebook.com). | `boolean` |
| `embedded_urls` | URLs for document embeds | `[string]` |

## Publishing

You cannot create docs via the Graph API.

## Deleting

You cannot delete docs via the Graph API.

## Updating

You cannot update docs via the Graph API.

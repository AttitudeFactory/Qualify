Graph API Version

[v25.0](#)

# Test User /{test-user-id}

A test user associated with a Facebook app. Test users are created and associated using the [`/{app-id}/accounts/test-users`](/docs/graph-api/reference/app/accounts/test-users) edge or [in the App Dashboard](/docs/apps/test-users#managetool).

### Related Guides

* [Managing Test Accounts using the App Dashboard](/docs/apps/test-users#managetool)

## Reading

Permissions and fields for read operations on this node are [identical to those of the regular `/{user-id}` node](/docs/graph-api/reference/user#read).

## Publishing and Updating

You can publish to this node to update the test user's password or name.

HTTPPHP SDKAndroid SDKiOS SDK

```
POST /v25.0/{test-user-id} HTTP/1.1
Host: graph.facebook.com

password=newpassword&name=Newname+Smith
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->post(
    '/{test-user-id}',
    array (
      'password' => 'newpassword',
      'name' => 'Newname Smith',
    ),
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
Bundle params = new Bundle();
params.putString("password", "newpassword");
params.putString("name", "Newname Smith");
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/{test-user-id}",
    params,
    HttpMethod.POST,
    new GraphRequest.Callback() {
        public void onCompleted(GraphResponse response) {
            /* handle the result */
        }
    }
).executeAsync();
```

```
NSDictionary *params = @{
  @"password": @"newpassword",
  @"name": @"Newname Smith",
};
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/{test-user-id}"
                                      parameters:params
                                      HTTPMethod:@"POST"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Permissions

* An app access token is required to update these fields for any test users associated with that app.

### Fields

Name | Description | Type || `name` | New name for the test user. | `string` |
| `password` | A new password for the test user. | `string` |

### Response

If update is successful, `true`, otherwise an error message.

## Deleting

You can delete a test user by making a delete operation on this node.

HTTPPHP SDKAndroid SDKiOS SDK

```
DELETE /v25.0/{test-user-id} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->delete(
    '/{test-user-id}',
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
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/{test-user-id}",
    null,
    HttpMethod.DELETE,
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
                               initWithGraphPath:@"/{test-user-id}"
                                      parameters:params
                                      HTTPMethod:@"DELETE"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Permissions

* An app access token for an associated app or the test user's own access token must be used to delete that test user.
* The test user must have been disassociated from all but a single app. You can disassociate test users using the [`/{app-id}/accounts/test-users` edge](/docs/graph-api/reference/app/accounts/test-users#delete).

### Fields

No fields are required to delete.

### Response

If delete is successful, `true`, otherwise an error message.

## Edges

Name | Description || [`/friends`](/docs/graph-api/reference/test-user/friends) | The friends of the test user - this edge can be used to friend two test users. |

Graph API Version

[v25.0](#)

# Test Account

## Reading

A test user account for a Facebook app

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_TestAccount%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_TestAccount} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_TestAccount}',
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
    "...?fields={fieldname_of_type_TestAccount}",
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
    "...?fields={fieldname_of_type_TestAccount}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_TestAccount}"
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
| `id`  numeric string | User ID  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `login_url`  string | A link to log in to Facebook as this test user  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can make a POST request to `accounts` edge from the following paths:

* [`/{application_id}/accounts`](/docs/graph-api/reference/application/accounts/)

When posting to this edge, a [TestAccount](/docs/graph-api/reference/test-account/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `installed`  boolean | Automatically installs the app for the test user once it is created or associated |
| `minor`  boolean | Is this test user a minor |
| `name`  string | The name for the test user. When left blank, a random name will be automatically generated |
| `owner_access_token`  string | When associating existing test users with other apps, this is the app access token of any app that is already associated with the test user. The `{app-id}` in the publishing request in this case should be the app that will is the target to associate with the test user. The API request should also be signed with the app access token of that target app. Required when associating test users, but should not be used when creating new test users |
| `permissions`  List<Permission> | Default value: `Set`  List of permissions that are automatically granted for the app when it is created or associated |
| `type`  enum{test-users} | Type |
| `uid`  int | ID of an existing test user to associate with another app. Required when associating test users, but should not be used when creating new test users |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

`access_token`: string,

`login_url`: string,

`email`: string,

`password`: string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 2900 | Too many test accounts |
| 195 | The name you are trying to use is invalid |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can dissociate a [TestAccount](/docs/graph-api/reference/test-account/) from an [Application](/docs/graph-api/reference/application/) by making a DELETE request to [`/{application_id}/accounts`](/docs/graph-api/reference/application/accounts/).

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `type`  enum {TEST\_USERS} | Account type |
| `uid`  UID | Account UID  Required |

### Return Type

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 2902 | Cannot remove test account from this app |

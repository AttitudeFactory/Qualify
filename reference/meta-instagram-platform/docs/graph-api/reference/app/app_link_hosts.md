Graph API Version

[v25.0](#)

# [`/{app-id}`](/docs/graph-api/reference/app/)`/app_link_hosts`

The [app link objects](/docs/graph-api/reference/app-link-host/) created by this app. [Read more](http://l.facebook.com/l.php?u=http%3A%2F%2Fapplinks.org%2F&h=AUBFDEF0icgRZ_joMVLaTUTKTYuvkvnZxDoYK3wEQmXZTfCy53cNY37dNwQe2qJhIdSjUo9Zr7mUIW3yvfiIMeLyHioZND4HPOg7H48nUudGFw067qY8tmbEgpN_qA8oCOeAfxVaErIEGKIWBpSXKfmu60u5Fg) about what App Links are at our [applinks.org site](http://l.facebook.com/l.php?u=http%3A%2F%2Fapplinks.org%2F&h=AUA9D5-TT0noJUIaiHnw0T_sZ3mynepXL2d_69FJyNeBasMtQSHmMeFNwuH2HW6g-fSCnk2cVPH8A1YhfSp2PgzGa1WUswVYXMf7M_LOvLB56Widy9eLsHj_FQdtdMWxAIt4ttVwynovA-p5VDMrWC1Y1WS2SQ).

## Reading

HTTPPHP SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=app%2Fapp_link_hosts&version=v25.0)

```
GET /v25.0/app/app_link_hosts HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/app/app_link_hosts',
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
    "/app/app_link_hosts",
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
                               initWithGraphPath:@"/app/app_link_hosts"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Permissions

* An app access token for the app is required.

### Response

A list of [App Link Host objects](/docs/graph-api/reference/app-link-host/) is returned.

## Publishing

Publishing is not supported.

## Deleting

You can delete an app link host object using the [`/app-link-host` node](/docs/graph-api/reference/app-link-host/).

## Updating

You can update an app link host object using the [`/app-link-host` node](/docs/graph-api/reference/app-link-host/).

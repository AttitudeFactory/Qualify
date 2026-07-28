Graph API Version

[v25.0](#)

# Graph API Reference [`/{page-id}`](/docs/graph-api/reference/page/)`/screennames`

A list of the other, non-Facebook accounts associated with the brand or entity represented by a Facebook Page.

## Reading

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK

```
GET /v25.0/{page-id}/screennames HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/screennames',
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
    "/{page-id}/screennames",
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
    "/{page-id}/screennames",
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
                               initWithGraphPath:@"/{page-id}/screennames"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Permissions

* This call requires any valid access token.

### Fields

This returns an array of objects representing each account, each with the following fields:

Name | Description | Type || `service_type` | Indicates which service this account is associated with. | `enum{AIM, GADU, ICQ, GTALK, MSN, SKYPE, YAHOO, YAHOO_JP, QQ, NATEON, TWITTER, HYVES, ORKUT, MYSPACE, GROUPWISE, CYWORLD, MIXI, QIP, REDIFF_BOL, VKONTAKTE, EBUDDY, MAILRU, JABBER, ICLOUD, BBM}` |
| `service_name` | A readable representation of `service_type`. | `string` |
| `value` | The account name used on the service. | `string` |

## Publishing

You can't publish this information using the Graph API.

## Deleting

You can't delete this information using the Graph API.

## Updating

You can't update this information using the Graph API.

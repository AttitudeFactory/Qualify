Graph API Version

[v25.0](#)

# Whats App Business HSMWhats App HSMComponent Get

## Reading

Shape Node

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_WhatsAppBusinessHSMWhatsAppHSMComponentGet%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_WhatsAppBusinessHSMWhatsAppHSMComponentGet} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_WhatsAppBusinessHSMWhatsAppHSMComponentGet}',
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
    "...?fields={fieldname_of_type_WhatsAppBusinessHSMWhatsAppHSMComponentGet}",
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
    "...?fields={fieldname_of_type_WhatsAppBusinessHSMWhatsAppHSMComponentGet}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_WhatsAppBusinessHSMWhatsAppHSMComponentGet}"
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
| `add_security_recommendation`  bool | Whether or not a security recommendation is included in the body text.**Only available for Authentication templates**Only available on v18.0+.****  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `buttons`  list<WhatsAppBusinessHSMWhatsAppHSMComponentButtonGet> | Buttons  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `call_permission_request`  WhatsAppBusinessHSMWhatsAppCallPermissionRequestParameterShape | Call Permission Request  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `cards`  list<WhatsAppBusinessHSMWhatsAppHSMComponentCardGet> | cards  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `code_expiration_minutes`  integer | The number of minutes that the authentication code will expire in.**Only available for Authentication templates**Only available on v18.0+.****  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `example`  WhatsAppBusinessHSMWhatsAppHSMComponentExample | Example information for the component  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `format`  enum | Format  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `limited_time_offer`  WhatsAppBusinessHSMWhatsAppLimitedTimeOfferParameterShape | Limited Time Offer component associated with the Template message  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `text`  string | text  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `type`  enum | Type  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

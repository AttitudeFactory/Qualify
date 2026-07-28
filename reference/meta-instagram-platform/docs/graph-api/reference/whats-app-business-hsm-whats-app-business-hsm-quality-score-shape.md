Graph API Version

[v25.0](#)

# Whats App Business HSMWhats App Business HSMQuality Score Shape

## Reading

Quality score shape

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_WhatsAppBusinessHSMWhatsAppBusinessHSMQualityScoreShape%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_WhatsAppBusinessHSMWhatsAppBusinessHSMQualityScoreShape} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_WhatsAppBusinessHSMWhatsAppBusinessHSMQualityScoreShape}',
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
    "...?fields={fieldname_of_type_WhatsAppBusinessHSMWhatsAppBusinessHSMQualityScoreShape}",
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
    "...?fields={fieldname_of_type_WhatsAppBusinessHSMWhatsAppBusinessHSMQualityScoreShape}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_WhatsAppBusinessHSMWhatsAppBusinessHSMQualityScoreShape}"
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
| `date`  integer | Timestamp of the quality score  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `reasons`  list<string> | List of reasons for the score of the HSM  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `score`  enum | Quality score of the template. Values can be:   * `GREEN` — Indicates high quality. The template has received little to no negative feedback from WhatsApp users. The template can be sent. * `YELLOW` — Indicates medium quality. The template has received negative feedback from multiple WhatsApp users, or low read-rates, and may soon become paused or disabled. Message templates with this status can still be sent. * `RED` — Indicates low quality. The template has received negative feedback from multiple WhatsApp users, or low read-rates. The template can be sent, but is in danger of being paused or disabled soon. We recommend that you address the issues that users are reporting. are reporting. * `UNKNOWN` — Indicates a quality score is still pending, because it has yet to receive WhatsApp user feedback or read-rate data. The template can be sent.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

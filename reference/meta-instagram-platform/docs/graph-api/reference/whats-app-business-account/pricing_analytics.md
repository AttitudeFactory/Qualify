Graph API Version

[v25.0](#)

# Whats App Business Account Pricing Analytics

## Reading

WhatsAppBusinessAccountPricingAnalytics

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bwhats-app-business-account-id%7D%2Fpricing_analytics&version=v25.0)

```
GET /v25.0/{whats-app-business-account-id}/pricing_analytics HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{whats-app-business-account-id}/pricing_analytics',
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
    "/{whats-app-business-account-id}/pricing_analytics",
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
    "/{whats-app-business-account-id}/pricing_analytics",
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
                               initWithGraphPath:@"/{whats-app-business-account-id}/pricing_analytics"
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
| `country_codes`  array<string> | Default value: `[]`  country\_codes |
| `dimensions`  array<enum {PHONE, COUNTRY, PRICING\_TYPE, PRICING\_CATEGORY, TIER}> | Default value: `[]`  dimensions |
| `end`  int64 | end  Required |
| `granularity`  enum {HALF\_HOUR, DAILY, MONTHLY} | granularity  Required |
| `metric_types`  array<enum {VOLUME, COST}> | Default value: `[]`  metric\_types |
| `phone_numbers`  array<string> | Default value: `[]`  phone\_numbers |
| `pricing_categories`  array<enum {MARKETING, UTILITY, AUTHENTICATION, SERVICE, AUTHENTICATION\_INTERNATIONAL, GROUP\_MARKETING, GROUP\_UTILITY, GROUP\_SERVICE, MARKETING\_LITE, MARKETING\_LITE\_DYNAMIC, GROUP\_MARKETING\_LITE, AI\_BOT}> | Default value: `[]`  pricing\_categories |
| `pricing_types`  array<enum {REGULAR, FREE\_ENTRY\_POINT, FREE\_CUSTOMER\_SERVICE, FREE\_GROUP\_CUSTOMER\_SERVICE}> | Default value: `[]`  pricing\_types |
| `start`  int64 | start  Required |
| `tiers`  array<string> | Default value: `[]`  tiers |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of WABAPricingAnalytics nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 200008 | WhatsApp Business Account has no linked phone numbers. |
| 100 | Invalid parameter |
| 2500 | Error parsing graph query |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

Graph API Version

[v25.0](#)

# WhatsApp Business Account Analytics

Represents analytics information about a specific WhatsApp Business Account (WABA).

## Reading

WhatsApp Business Account (WABA) Analytics

### Requirements

* whatsapp\_business\_management permission
* whatsapp\_business\_messaging permission

### Request

cURLAndroid SDKObjective-C

```
curl -i -X GET \
"https://graph.facebook.com/LATEST-VERSION/WHATSAPP-BUSINESS-ACCOUNT-ID?fields=analytics.start(1641024000).end(1651094880).granularity(DAY)&
access_token=USER-ACCESS-TOKEN"
```

```
GraphRequest request = GraphRequest.newGraphPathRequest(
  accessToken,
  "/WHATSAPP-BUSINESS-ACCOUNT-ID",
  new GraphRequest.Callback() {
    @Override
    public void onCompleted(GraphResponse response) {
      // Insert your code here
    }
});

Bundle parameters = new Bundle();
parameters.putString("fields", "analytics.start(1641024000).end(1651094880).granularity(DAY)");
request.setParameters(parameters);
request.executeAsync();
```

```
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
    initWithGraphPath:@"/WHATSAPP-BUSINESS-ACCOUNT-ID"
           parameters:@{ @"fields": @"analytics.start(1641024000).end(1651094880).granularity(DAY)",}
           HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection, id result, NSError *error) {
    // Insert your code here
}];
```

### Response

```
{
  "analytics": {
    "phone_numbers": [
      "PHONE-NUMBER"
    ],
    "granularity": "DAY",
    "data_points": [
      {
        "start": 1647327600,
        "end": 1647414000,
        "sent": 1,
        "delivered": 1
      },
      {
        "start": 1648710000,
        "end": 1648796400,
        "sent": 4,
        "delivered": 4
      },
      {
        "start": 1648796400,
        "end": 1648882800,
        "sent": 1,
        "delivered": 1
      },
      {
        "start": 1650265200,
        "end": 1650351600,
        "sent": 1,
        "delivered": 1
      },
      {
        "start": 1650351600,
        "end": 1650438000,
        "sent": 1,
        "delivered": 1
      }
    ]
  },
  "id": "WHATSAPP-BUSINESS-ACCOUNT-ID"
}
```

### Parameters

This endpoint doesn't have any parameters.

### Fields

| Field | Description |
| --- | --- |
| `country_codes`  list<string> | List of ISO 3166 country codes (e.g. US, IN)  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `data_points`  [list<WABAAnalyticsDataPoint>](https://developers.facebook.com/docs/graph-api/reference/waba-analytics-data-point/) | List of analytics data points (e.g. {start: 0, end: 10000, sent: 10, delivered: 9})  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `granularity`  string | Granularity of data (options are half\_hour, day, month)  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `phone_numbers`  list<numeric string> | List of WhatsApp normalized phone numbers (e.g. [16315551000])  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

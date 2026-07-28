Graph API Version

[v25.0](#)

# Application Restriction Info

## Reading

Demographic restrictions for a Facebook App

### Example

To get the restriction settings of your app, send a `GET` request to the `/{app-id}` endpoint with an App access token:

```
curl -i -X GET "https://graph.facebook.com/{app-id}?fields=restrictions&access_token={app-access-token}"
```

On success the following will be returned:

```
{  "restrictions": {
"age": "21+",
"type": "alcohol"
},
"id": "{app-id}"
}
```

### Parameters

This endpoint doesn't have any parameters.

### Fields

| Field | Description |
| --- | --- |
| `age`  string | Age restrictions for the app. Can be one of the following values: 13+, 16+, 17+, 18+, 19+, or 21+  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `age_distribution`  string | Age restrictions by location  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `location`  string | Location restrictions for the app. Facebook uses [2 letter country codes](https://l.facebook.com/l.php?u=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FISO_3166-1_alpha-2&h=AUA-gb-wMks53I6MBnCWhVbk1IVSaJp6SNgcGMlkQECpLtAT6WSegC3FbhDcxVJTSNSRe1UMo4qF-lMOISOp_bMS2QYzWaQQK2GaeqkMLd7AoA_GPMOITiDX_t25ttjnBZ88Op8eSxLzFbSQ).  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `type`  string | Custom category restrictions for the app. Currently can only be set to `alcohol`.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

To update a restriction, use the [`/{app-id}?restrictions={restrictions-json}&allow_cycle_app_secret=true` parameter](/docs/graph-api/reference/application#Updating).


**Note:** This will invalidate all of your User access tokens. Users will need to log back into your app to restore access.

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

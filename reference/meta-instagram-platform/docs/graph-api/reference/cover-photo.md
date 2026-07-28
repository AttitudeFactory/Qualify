Graph API Version

[v25.0](#)

# Cover Photo

## Reading

The cover photo for a Facebook [Event](https://developers.facebook.com/docs/graph-api/reference/event), [Group](https://developers.facebook.com/docs/graph-api/reference/group), or [Page](https://developers.facebook.com/docs/graph-api/reference/page).

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Examples

cURLAndroid SDKObjective-CJava SDK

```
curl -i -X GET "https://graph.facebook.com/COVER-PHOTO-ID?access_token=ACCESS-TOKEN"
```

```
GraphRequest request = GraphRequest.newGraphPathRequest(
  accessToken,
  "/COVER-PHOTO-ID",
  new GraphRequest.Callback() {
    @Override
    public void onCompleted(GraphResponse response) {
      // Insert your code here
    }
});

request.executeAsync();
```

```
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
    initWithGraphPath:@"/COVER-PHOTO-ID"
           parameters:nil
           HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection, id result, NSError *error) {
    // Insert your code here
}];
```

```
FB.api(
  '/COVER-PHOTO-ID',
  'GET',
  {},
  function(response) {
      // Insert your code here
  }
);
```

### Parameters

This endpoint doesn't have any parameters.

### Fields

| Field | Description |
| --- | --- |
| `id`  numeric string | The ID of the cover photo  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `cover_id`  id | Deprecated. Please use the `id` field instead  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `offset_x`  float | When greater than 0% but less than 100%, the cover photo overflows horizontally. The value represents the horizontal manual offset (the amount the user dragged the photo horizontally to show the part of interest) as a percentage of the offset necessary to make the photo fit the space.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `offset_y`  float | When greater than 0% but less than 100%, the cover photo overflows vertically. The value represents the vertical manual offset (the amount the user dragged the photo vertically to show the part of interest) as a percentage of the offset necessary to make the photo fit the space.  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |
| `source`  string | Direct URL for the person's cover photo image  [Default](https://developers.facebook.com/docs/graph-api/using-graph-api/#fields) |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

Graph API Version

[v25.0](#)

# IGUser Media

## Reading

ShadowIGUserMedia

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Big-user-id%7D%2Fmedia&version=v25.0)

```
GET /v25.0/{ig-user-id}/media HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{ig-user-id}/media',
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
    "/{ig-user-id}/media",
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
    "/{ig-user-id}/media",
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
                               initWithGraphPath:@"/{ig-user-id}/media"
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

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of ShadowIGMedia nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 190 | Invalid OAuth 2.0 Access Token |
| 200 | Permissions error |
| 80002 | There have been too many calls to this Instagram account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 102 | Session key invalid or no longer valid |
| 2500 | Error parsing graph query |
| 9005 | Video content was not found. |

## Creating

You can make a POST request to `media` edge from the following paths:

* [`/{ig_user_id}/media`](/docs/graph-api/reference/shadow-ig-user/media/)

When posting to this edge, an [IGUser](/docs/graph-api/reference/shadow-ig-user/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `alt_text`  string | Accessibility of a media |
| `audio_configuration`  string | audio\_configuration |
| `branded_content_sponsor_ids`  array<int64> | A JSON array of IG user IDs to tag as branded content sponsors on the media. |
| `caption`  string | Default value: `""`  Caption for the media to be created |
| `collaborators`  array<string> | Field that adds collaborators to a media |
| `image_url`  string | A URL where the image to be uploaded |
| `is_ai_generated`  boolean | is\_ai\_generated |
| `is_carousel_item`  boolean | is\_carousel\_item |
| `is_paid_partnership`  boolean | Boolean flag indicating whether the post is a paid partnership. When set to true, the post will display a 'Paid partnership' label. Can be used with or without specific sponsor IDs. |
| `location_id`  numeric string | Location id tagged in media |
| `media_type`  string | Default value: `"IMAGE"`  media\_type |
| `product_tags`  array<JSON object> | IG Shopping products tagged in media |
| `share_to_feed`  boolean | share\_to\_feed |
| `thumb_offset`  string | A numberic string for thumbnail offset in video stream to generate thumbmail |
| `user_tags`  array<JSON object> | IG users tagged in media |
| `username`  string | username  Required |
| `x`  float | x |
| `y`  float | y |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node represented by `id` in the return type.

Struct {

`id`: numeric string,

`uri`: string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 9004 | Only photo or video can be accepted as media type. |
| 36003 | The aspect ratio is not supported. |
| 210 | User not visible |
| 110 | Invalid user id |
| 190 | Invalid OAuth 2.0 Access Token |
| 36001 | The image format is not supported. |
| 36004 | The caption was too long. |
| 105 | The number of parameters exceeded the maximum for this operation |
| 200 | Permissions error |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

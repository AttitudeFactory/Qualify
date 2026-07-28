Graph API Version

[v25.0](#)

# IGUser

## Reading

Instagram User object

### Example

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=...%3Ffields%3D%257Bfieldname_of_type_IGUser%257D&version=v25.0)

```
GET v25.0/...?fields={fieldname_of_type_IGUser} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '...?fields={fieldname_of_type_IGUser}',
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
    "...?fields={fieldname_of_type_IGUser}",
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
    "...?fields={fieldname_of_type_IGUser}",
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
                               initWithGraphPath:@"...?fields={fieldname_of_type_IGUser}"
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
| `id`  numeric string | The id of the object |
| `biography`  string | Biography of the user |
| `business_discovery`  [IGUser](https://developers.facebook.com/docs/graph-api/reference/shadow-ig-user/) | Loads business discovery information |
| `followers_count`  integer | Active follower count of the user |
| `follows_count`  integer | Active follows count of the user |
| `has_profile_pic`  bool | has\_profile\_pic |
| `ig_id`  integer | Ig Id of the user |
| `is_published`  bool | is\_published |
| `legacy_instagram_user_id`  numeric string | Legacy Instagram user id still used in some endpoints |
| `media_count`  integer | Filtered media count of the user |
| `mentioned_comment`  ShadowIGComment | Loads the comment if the user is mentioned in it |
| `mentioned_media`  ShadowIGMedia | Loads the media if the user is mentioned in the caption |
| `name`  string | Name of the user |
| `profile_picture_url`  string | The cdn url to query the raw profile picture of the user |
| `shopping_review_status`  enum | Status of the Shopping Merchant Review process for this account |
| `username`  string | Username handle of the user |
| `website`  string | Url in the profile |

### Edges

| Edge | Description |
| --- | --- |
| [`agencies`](/docs/graph-api/reference/shadow-ig-user/agencies/)  Edge<Business> | agencies |
| [`branded_content_ad_permissions`](/docs/graph-api/reference/shadow-ig-user/branded_content_ad_permissions/)  Edge<IGBCAdsPermission> | branded\_content\_ad\_permissions |
| [`branded_content_advertisable_medias`](/docs/graph-api/reference/shadow-ig-user/branded_content_advertisable_medias/)  Edge<BrandedContentShadowIGMediaID> | branded\_content\_advertisable\_medias |
| [`content_publishing_limit`](/docs/graph-api/reference/shadow-ig-user/content_publishing_limit/)  Edge<ContentPublishingLimitResponse> | content\_publishing\_limit |
| [`insights`](/docs/graph-api/reference/shadow-ig-user/insights/)  Edge<InstagramInsightsResult> | Insights data of this IG user |
| [`live_media`](/docs/graph-api/reference/shadow-ig-user/live_media/)  Edge<ShadowIGMedia> | live\_media |
| [`media`](/docs/graph-api/reference/shadow-ig-user/media/)  Edge<ShadowIGMedia> | Timeline media of this IG user |
| [`notification_message_tokens`](/docs/graph-api/reference/shadow-ig-user/notification_message_tokens/)  Edge<UserPageOneTimeOptInTokenSettings> | notification\_message\_tokens |
| [`product_appeal`](/docs/graph-api/reference/shadow-ig-user/product_appeal/)  Edge<IGShoppingProductAppeal> | product\_appeal |
| [`recently_searched_hashtags`](/docs/graph-api/reference/shadow-ig-user/recently_searched_hashtags/)  Edge<ShadowIGHashtag> | Recently searched hashtags through the Graph API by an Instagram User |
| [`stories`](/docs/graph-api/reference/shadow-ig-user/stories/)  Edge<ShadowIGMedia> | Stories of this IG user |
| [`tags`](/docs/graph-api/reference/shadow-ig-user/tags/)  Edge<ShadowIGMedia> | Media that this user is tagged in |
| [`upcoming_events`](/docs/graph-api/reference/shadow-ig-user/upcoming_events/)  Edge<IGUpcomingEvent> | upcoming\_events |

### Error Codes

| Error | Description |
| --- | --- |
| 110 | Invalid user id |
| 100 | Invalid parameter |
| 200 | Permissions error |
| 190 | Invalid OAuth 2.0 Access Token |
| 80002 | There have been too many calls to this Instagram account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 2500 | Error parsing graph query |
| 3006 | Not enough users |
| 102 | Session key invalid or no longer valid |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |

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

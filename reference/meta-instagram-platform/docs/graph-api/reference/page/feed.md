Graph API Version

[v25.0](#)

# Page Feed

Use this endpoint to get and publish to a Page. The Page Feed encompasses any interactions with a Facebook Page including: posts and links published by this Page, visitors to this Page, and public posts in which the Page has been tagged.

### See Also

* The [`/{page-post-id}` endpoint](https://developers.facebook.com/docs/graph-api/reference/pagepost) allows you to update a specific Page post.
* The [`/{page-id}/tagged` endpoint](https://developers.facebook.com/docs/graph-api/reference/page/tagged) **to only retrieve public posts in which the Page has been tagged.**

## Reading

The posts of a Facebook Page.

### New Page Experience

This API is supported for New Page Experience.

### Requirements

The person requesting the access token must be able to perform one of the following tasks on the Page:

* CREATE\_CONTENT – Publish content as the Page on the Page
* MANAGE – Assign and manage Page tasks
* MODERATE
  + Respond to comments on Page posts as the Page
  + Delete comments on Page posts
  + If an Instagram account is connected to the Page, publish content to Instagram from Facebook, respond to and delete comments, send Direct messages, sync business contact info, and create ads.

And have granted the app the following permissions are required:

* The [`pages_read_engagement` permission](/docs/pages/overview-1#permissions)
* The [`pages_read_user_content` permission](/docs/pages/overview-1#permissions)

If you do not own or manage the Page, you will need:

* The [Page Public Content Access Feature](https://developers.facebook.com/docs/apps/review/feature/#reference-PAGES_ACCESS)

When using the Page Public Content Access feature, use a [system user access token](https://www.facebook.com/business/help/503306463479099) to avoid [rate limiting](/docs/graph-api/overview/rate-limiting#pages) issues.

#### Sample Request

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bpage-id%7D%2Ffeed&version=v25.0)

```
GET /v25.0/{page-id}/feed HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '/{page-id}/feed',
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
    "/{page-id}/feed",
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
    "/{page-id}/feed",
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
                               initWithGraphPath:@"/{page-id}/feed"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

#### Sample JSON Response

```
{
  "data": [
    {
      "created_time": "2019-05-17T16:24:04+0000",
      "message": "Become a Facebook developer!",
      "id": "{page-id}_2191966997525824"
    },
    {
      "created_time": "2019-02-26T21:35:42+0000",
      "message": "Hello world!",
      "id": "{page-id}_2072371269485398"
    },
...
    {
      "created_time": "2018-01-26T20:57:22+0000",
      "message": "Friday Funday!",
      "id": "{page-id}_1569752556413941"
    }
  ],
  "paging": {
    "cursors": {
      "before": "Q2c4U1pXNT...",
      "after": "Q2c4U1pXNT..."
    },
    "next": "https://graph.facebook.com/vX.X/{page-id}/feed?access_token={your-page-access-token}&pretty=0&limit=25&after=Q2c4U1pXNT..."
  }
}
```

### Limitations

* **Expired Posts** – If a Post has expired, you will no longer be able to view the content using the Graph API.
* **Maximum Posts**
  + The API will return approximately 600 ranked, published posts per year.
  + You can only read a maximum of 100 feed posts with the `limit` field. If you try to read more than that you will get an error message to not exceed 100.
* **Message CTA** - Posts with message CTAs cannot be accessed using another Page's access token since Pages cannot message other Pages.
* **Publicly Identifiable Information** - User information will not be in included in responses unless you make the request with a Page access token.
* **Published Posts** – Published and unpublished posts will be returned when querying the `/{page-id}/feed` endpoint. Use the 'is\_published` field to return only published posts.
* **Shared Posts** - A Page post which shares a post from another Page or person may not be visible if the original post isn't visible with the access token used.
* **Tagged Posts** - When you use `/{page-id}/tagged` to show the posts that tagged this Page, the results include posts from other Pages only if those Pages are authentic.
* **User Agents** - The available user agents allowed for these Graph API calls are subject to change without notice. If you are experiencing issues, you may want to change to a newer version of your particular user agent.
* **Video Posts** - To get a list of video posts, the person making the request must be an admin of the Page.
* **Reels** To get a list of Reels published to your Page, use the [Page VideoReels edge](/docs/graph-api/reference/page/video_reels).

Limitation: All posts (published and unpublished) will be pulled in the feed endpoint. The only difference is unpublished posts will not be listed in the physical feed. However, there is an is\_published field that can be added to the /feed endpoint to let developers know whether the post listed in the /feed endpoint is published or not

### Fields

Name | Type | Description || `id` | `string` | The ID of the post. |
| `actions` | `object` | Action links on the post, Comment, Like, Share. |
| `admin_creator` | `object` | The admin creator of a Page post. If the Page has only one admin, no data is returned. Requires a Page Access Token and the `business_management` permission. |
| `id` | `int` | ID of the person, app or business. |
| `name` | `string` | Name of the person, app or business. |
| `allowed_advertising_objects` | `string` | The only objectives under which this post can be advertised. |
| `application` | `object` | Information about the app that published this post. |
| `attachments` | `object` | Any attachments that are associated with the story. See the [story attachment node reference](/docs/graph-api/reference/story-attachment) for `attachments` fields. |
| `backdated_time` | `float` | The backdated time for backdate post. For a regular post, this field is set to null. |
| `call_to_action` | `object` | The call to action type used in any Page posts for [mobile app engagement ads](https://developers.facebook.com/docs/app-ads/targeting). |
| `context` | `object` | The call to action type used in any Page posts for [mobile app engagement ads](https://developers.facebook.com/docs/app-ads/targeting). |
| `can_reply_privately` | `boolean` | Whether the Page viewer can send a private reply to this Post. Requires the `read_page_mailboxes` permission. |
| `child_attachments` | `object` | Sub-shares of a multi-link share post. |
| `created_time` | `float` | The time the post was initially published. For a post about a life event, this is the date and time of the life event. |
| `feed_targeting` | `object` | Object that controls [Feed Targeting](https://www.facebook.com/help/352402648173466) for this post. Anyone in these groups are more likely to see this post, others are less likely, but may still see it anyway. Any of the targeting fields shown here can be used, none are required (applies to Pages only). |
| `age_max` | `int` | Maximum age |
| `age_min` | `int` | Must be 13 or higher. Default is 0 |
| `cities` | `int` | Values of targeting cities. Use `type` of `adcity` to [find Targeting Options](/docs/graph-api/reference/targeting/) and use the returned `key` to specify. |
| `college_years` | `int` | Array of integers for graduation year from college. |
| `countries` | `string` | Values of targeting countries. You can specify up to 25 countries. Use [ISO 3166 format codes](http://l.facebook.com/l.php?u=http%3A%2F%2Fwww.iso.org%2Fiso%2Fcountry_codes%2Fiso_3166_code_lists%2Fcountry_names_and_code_elements.htm&h=AUADCDUclJVVIVBctUKKV5hz8CaTbVQnDmr-OtBRu4i012zdcbQp00Bbwoj1FIdFamhxa9-HflytNm_6Wjhu1yzvEZIX8Kxl1BFZHOg2bgIPa_URcTqq68-GkMzaNRjnVXVpOHpkcJoz4aej). |
| `education_statuses` | `int` | Array of integers for targeting based on education level. Use `1` for high school, `2` for undergraduate, and `3` for alum (or localized equivalents). |
| `genders` | `int` | Target specific genders. `1` targets all male viewers and `2` females. Default is to target both. |
| ~~`interested_in`~~ Deprecated. | ~~`int`~~ | ~~Indicates targeting based on the 'interested in' field of the User profile. You can specify an integer of 1 to indicate male, 2 indicates female. Default is all types. Please note 'interested in' targeting is not available in most European countries and Canada due to local laws.~~ |
| `interests` | `int` | One or more IDs of pages to target fans of pages. Use type of page to get possible IDs as Targeting Options and use the returned id to specify. |
| `locales` | `int` | Targeted locales. Use `type` of `adlocale` to [find Targeting Options](/docs/graph-api/reference/targeting/) and use the returned `key` to specify. |
| `regions` | `array` | Values of targeting regions. Use `type` of `adregion` to [find Targeting Options](/docs/graph-api/reference/targeting/) and use the returned `key` to specify. |
| `relationship_statuses` | `int` | Array of integers for targeting based on relationship status. Use `1` for single, `2` for 'in a relationship', `3` for married, and `4` for engaged. Default is all types. |
| `from` | `object` | The `name` and `id` of the Page, group, or event that created the post. If you read this field with a [User access token](/docs/facebook-login/access-tokens), it returns only the current User. |
| `full_picture` | `string` | URL to a full-sized version of the Photo published in the Post or scraped from a link in the Post. If the photo's largest dimension exceeds 720 pixels, it is resized, with the largest dimension set to 720. |
| `icon` | `string` | A link to an icon representing the type of this post. |
| `instagram_eligibility` | `enum{}` | Whether the post can be promoted on Instagram. It returns the enum `eligible` if it can be promoted. Otherwise it returns an enum for why it cannot be promoted:   |  | | --- | | * `ineligible_caption_mentions_not_allowed` * `ineligible_caption_too_long` * `ineligible_media_aspect_ratio` * `ineligible_media_dimension` * `ineligible_media_square_aspect_ratio` * `ineligible_media_square_dimension` * `ineligible_post_type` * `ineligible_unknown_error` * `ineligible_video_length` | |
| `is_eligible_for_promotion` | `boolean` | Indicates whether a post is eligible for promotion. |
| `is_expired` | `boolean` | Whether the post has an expiration time that has passed. |
| `is_hidden` | `boolean` | If this post is marked as hidden (Applies to Pages only). Hiding a post hides it in a Page's timeline however it is still visible in other places on Facebook, for example, a link. |
| `is_instagram_eligible` | `string` | Whether this post can be promoted in Instagram. |
| `is_popular` | `boolean` | Whether the post is popular. Based on whether the total actions as a percentage of reach exceeds a certain threshold. |
| `is_published` | `boolean` | Indicates whether a scheduled post was published (applies to scheduled Page Post only, for users post and instantly published posts this value is always `true`). Note that this value is always `false` for page posts created as part of the Ad Creation process. |
| `is_spherical` | `boolean` | Whether the post is a spherical video post. |
| `message` | `string` | The status message in the post. |
| `message_tags` | `array` | An array of profiles tagged in the `message` text. If you read this field with a User [User access token](/docs/facebook-login/access-tokens), it returns only the current User. |
| `length` | `int` | The length of the tag text, in [unicode code points](https://l.facebook.com/l.php?u=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FCode_point&h=AUBbtoXsc8yDt5mWutK0osoHRFySOPNeQZ2ahGVGbPlInb5qO06jbBAhnhCXLSYvhgAxgDLyHHt1V7kfuCKavRbwjTpWQwoZFyj2J8e1rtGJXFTP4pPuuy-al5sFmMZI6FW_7OwC0Vfyy8T0). |
| `id` | `string` | ID of the profile that was tagged. |
| `name` | `string` | The text used to tag the profile. |
| `offset` | `int` | The location in [unicode code points](https://l.facebook.com/l.php?u=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FCode_point&h=AUDJEOizoApMbmLUvjQoApfUCfL0dyux1rhA5ei6mHMVwLA6eS0YXpuL_6K-7zzi2UL4QmZLMT8oEOdx_UAOwBafZ3uRalSLhPFDCM4IUtbzUymKBYMQzX6lnVJTgrk-omFtG7noNQk1oJS6) of the first character of the tag text in the `message`. |
| `type` | `enum{}` | The tagged profile's type, `user`, `page`, or `group`. |
| `parent_id` | `string` | The ID of a parent post for this post, if it exists. For example, if this story is a 'Your Page was mentioned in a post' story, the `parent_id` is the original post where the mention happened. |
| `permalink_url` | `string` | The permanent static URL to the post on www.facebook.com. Example: <https://www.facebook.com/FacebookForDevelopers/posts/10153449196353553>. |
| `place` | `string` | ID of the [place](/docs/graph-api/reference/place) associated with this post. |
| `privacy` | `object` | The privacy settings of the post. |
| `allow` | `string` | If `value` is `CUSTOM`, this is a comma-separated ID list of Users and friend lists (if any) that can see the post. |
| `deny` | `string` | If `value` is `CUSTOM`, this is a comma-separated ID list of Users and friend lists (if any) that cannot see the post. |
| `description` | `string` | Text that describes the privacy settings, as they would appear on Facebook. |
| `friends` | `enum{}` | If `value` is `CUSTOM`, this indicates which group of friends can see the post. Values include:   |  | | --- | | * `ALL_FRIENDS` * `FRIENDS_OF_FRIENDS` * `SOME_FRIENDS` | |
| `value` | `enum{}` | The actual privacy setting. Values include:   |  | | --- | | * `ALL_FRIENDS` * `CUSTOM` * `EVERYONE` * `FRIENDS_OF_FRIENDS` * `SELF` | |
| `promotable_id` | `string` | ID of post to use for promotion for stories that cannot be promoted directly. |
| `properties` | `object` | A list of properties for any attached video, for example, the length of the video. |
| `name` | `string` | The property name. |
| `text` | `string` | The value of the property. |
| `href` | `string` | Any link associated with the property. |
| `sheduled_publish_time` | `float` | The UNIX timestamp of the scheduled publish time for the post. Date will be between 10 minutes and 75 days from the time of the `POST` request to publish the post. |
| `shares` | `object` | The share count of this post. The share count may include deleted posts and posts you cannot see for privacy reasons. |
| `status_type` | `enum{}` | The type of a status update. Values include:   |  | | --- | | * `added_photos` * `added_video` * `app_created_story` * `approved_friend` * `created_event` * `created_group` * `created_note` * `mobile_status_update` * `published_story` * `shared_story` * `tagged_in_photo` * `wall_post` | |
| `story` | `string` | Text of stories not intentionally generated by Users, such as those generated when a photo has been added. The "Include recent activity stories" migration must be enabled in your app to retrieve this field. |
| `story_tags` | `array` | The list of tags in the post description. |
| `subscribed` | `boolean` | Whether a User is subscribed to the post. |
| `targeting` | `object` | Object that limits the audience for this content. Only audiences in the [specified demographics](https://www.facebook.com/help/352402648173466) can view this content. The demographics are additive. Each additional value adds its audience to the cumulative targeted audience. These values do not override any Page-level demographic restrictions that may be in place. |
| `countries` | `string` | Values of targeting countries as [ISO 3166 format codes](http://l.facebook.com/l.php?u=http%3A%2F%2Fwww.iso.org%2Fiso%2Fcountry_codes%2Fiso_3166_code_lists%2Fcountry_names_and_code_elements.htm&h=AUABXeZu40raT8sOjgW4INmC4aHXgIPf932RDFDBkkO_luZsbBktpNI4-SHtma7oEs7GxKPgLJQxVzw9-AkaiQqAfer4tHC0K-n1GDfMCqfseC2pkVYvAPOoqeqstZA1DnMnVdhed_WUhfvI). |
| `locales` | `int` | Targeted locales. [Targeting Options](/docs/graph-api/reference/targeting/) of the type `adlocale` may be returned. |
| `regions` | `list<int>` | Values for targeted regions. [Targeting Options](/docs/graph-api/reference/targeting/) of the type `adregion` may be returned. |
| `cities` | `list<int>` | Values for excluded cities. [Targeting Options](/docs/marketing-api/targeting-search) of the type `adcity` may be returned. |
| `to` | `object` | Profiles mentioned or targeted in this post. If you read this field with a [User access token](/docs/facebook-login/access-tokens), it returns only the current User. |
| `updated_time` | `float` | The time the post was last updated, which occurs when the post was created, edited, or a User comments on a post, expressed as a UNIX timestamp. |
| `video_buying_eligibility` | `array` | Whether the post can be promoted with different video buying options. It returns an empty list when video is eligible. Otherwise it returns a list of reasons why the post cannot be promoted. |

### Promotable IDs

When finding posts that can be boosted, the `promotable_id` must be used to create ads. In most cases, this id will be identical to the `post_id`. However, this is not always the case. **Note**: once a post is boosted, you must have access to the connected ad account in order to edit the post.

#### Example Request

cURLAndroid SDKObjective-CJava SDKPHP SDK

```
curl -i -X GET \
 "https://graph.facebook.com/{your-page-id}/feed
    ?fields=is_eligible_for_promotion,promotable_id
        &access_token={your-page-access-token}"
```

```
GraphRequest request = GraphRequest.newGraphPathRequest(
  accessToken,
  "/{your-page-id}/feed",
  new GraphRequest.Callback() {
    @Override
    public void onCompleted(GraphResponse response) {
      // Insert your code here
    }
});

Bundle parameters = new Bundle();
parameters.putString("fields", "is_eligible_for_promotion,promotable_id");
request.setParameters(parameters);
request.executeAsync();
```

```
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
    initWithGraphPath:@"/{your-page-id}/feed"
           parameters:@{ @"fields": @"is_eligible_for_promotion,promotable_id",}
           HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection, id result, NSError *error) {
    // Insert your code here
}];
```

```
FB.api(
  '/{your-page-id}/feed',
  'GET',
  {"fields":"is_eligible_for_promotion,promotable_id"},
  function(response) {
      // Insert your code here
  }
);
```

```
try {
  // Returns a `FacebookFacebookResponse` object
  $response = $fb->get(
    '/{your-page-id}/feed?fields=is_eligible_for_promotion,promotable_id',
    '{access-token}'
  );
} catch(FacebookExceptionsFacebookResponseException $e) {
  echo 'Graph returned an error: ' . $e->getMessage();
  exit;
} catch(FacebookExceptionsFacebookSDKException $e) {
  echo 'Facebook SDK returned an error: ' . $e->getMessage();
  exit;
}
$graphNode = $response->getGraphNode();
```

#### Example Response

```
{
  "data": [
    {
      "is_eligible_for_promotion": true,
      "promotable_id": "1353269864728879_1943344825721377",
      "id": "1353269864728879_1943344825721377"
    },
    {
      "is_eligible_for_promotion": true,
      "promotable_id": "1353269864728879_1943313139057879",
      "id": "1353269864728879_1943378089051384"
    },
    {
      "is_eligible_for_promotion": false,
      "promotable_id": "1353269864728879_1942095249179668",
      "id": "1353269864728879_1942095249179668"
    },
...
```

Please visit our [help center](https://www.facebook.com/business/help/1575107409431290/?ref=u2u) to learn why a post may not be boosted.

Please visit our [Post Reference doc](/docs/graph-api/reference/post) for all available post fields.

## Publishing

You can publish to Pages by using this edge. Either `link` or `message` must be supplied.

### New Page Experience

This API is supported for New Page Experience.

### Requirements

If you can perform the [`CREATE_CONTENT` task](https://developers.facebook.com/docs/pages/overview/permissions-features#tasks), you will need:

* A Page access token
* The [`pages_manage_posts` permission](https://developers.facebook.com/docs/permissions/reference/pages_manage_posts)
* The [`pages_read_engagement` permission](https://developers.facebook.com/docs/permissions/reference/pages_read_engagement)
* The [`pages_show_list` permission](https://developers.facebook.com/docs/permissions/reference/pages_show_list)

Posts will appear in the voice of the Page.

### Permissions

* A Page access token requested by someone who can perform the

  [`CREATE_CONTENT` task](#)

  on the Page being queried
* [The `pages_manage_posts` permission](#)

**Note:** If the viewer or app cannot see the url of `link`, the post will fail.

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK

```
POST /v25.0/{page-id}/feed HTTP/1.1
Host: graph.facebook.com

message=This+is+a+test+message
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->post(
    '/{page-id}/feed',
    array (
      'message' => 'This is a test message',
    ),
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
    "/{page-id}/feed",
    "POST",
    {
        "message": "This is a test message"
    },
    function (response) {
      if (response && !response.error) {
        /* handle the result */
      }
    }
);
```

```
Bundle params = new Bundle();
params.putString("message", "This is a test message");
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/{page-id}/feed",
    params,
    HttpMethod.POST,
    new GraphRequest.Callback() {
        public void onCompleted(GraphResponse response) {
            /* handle the result */
        }
    }
).executeAsync();
```

```
NSDictionary *params = @{
  @"message": @"This is a test message",
};
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/{page-id}/feed"
                                      parameters:params
                                      HTTPMethod:@"POST"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

### Response

```
{"id":"post-id"}
```

This endpoint supports [read-after-write](/docs/graph-api/using-graph-api#read-after-write) and can immediately return any fields returned by [read](/docs/graph-api/reference/page/feed#read) operations.

#### Graph Explorer Tool Example

Test in the Graph Explorer Tool using `POST {page-id}/feed`:

![](https://scontent-eze1-2.xx.fbcdn.net/v/t39.2178-6/23668642_407398856346304_2504985490084593664_n.png?_nc_cat=103&ccb=1-7&_nc_sid=34156e&_nc_ohc=7sfe6cF-DjUQ7kNvwFuCsRY&_nc_oc=AdrR6MtT8W5cPLYkIz76CIoy1U6qqqfGnZuOCwAHSGzNZ1NnQsc-NFPPKgLzDxyKItU&_nc_zt=14&_nc_ht=scontent-eze1-2.xx&_nc_gid=0l8Wa-tMgnR_wxN3B9K4YQ&_nc_ss=7b20f&oh=00_AQCQ1mrJudHlPzV0qK0ur8KJnHkOx5gJVR8rgeN1j1MByw&oe=6A68C6E0)

### Fields

Name | Type | Description || `actions` | `array` | The [action links](/docs/opengraph/using-actions/#howto-actionlinks) attached to the post. |
| `link` | `string` | The URL of the action link itself. |
| `name` | `string` | The name or label of the action link. |
| `backdated_time` | `float` | Specifies a time in the past to backdate this post to. |
| `backdated_time_granularity` | `enum{year, month, day, hour, minute}` | Controls the display of how a backdated post appears. For example, if you pick `month` posts will be displayed as `2 months ago` instead of an exact date. |
| `child_attachments` | object | Use to specify multiple links in the post. Minimum 2 and maximum of 5 objects. If you set `multi_share_optimized` to true, you can upload a maximum of 10 objects but Facebook will display the top 5. |
| `description` | `string` | Used to show either a price, discount or website domain. If not specified, the content of the linked page will be extracted and used. This field will typically be truncated after 30 characters. |
| `image_hash` | `string` | Hash of a preview image associated with the link from your [ad image library](/docs/reference/ads-api/adimage) (1:1 aspect ratio and a minimum of 458 x 458 px for best display). Either `picture` or `image_hash` must be specified. |
| `link` | `string` | The URL of a link to attach to the post. This field is required. |
| `name` | `string` | The title of the link preview. If not specified, the title of the linked page will be used. This field will typically be truncated after 35 characters. It is recommended to set a unique `name`, as Facebook interfaces show actions reported on the `name` field. |
| `picture` | `string` | A URL that determines the preview image associated with the link (1:1 aspect ratio and a minimum of 458 x 458 px for best display). Either `picture` or `image_hash` must be specified. |
| `feed_targeting` | `object` | Object that controls [Feed Targeting](https://www.facebook.com/help/352402648173466) for this content. Anyone in these groups will be more likely to see this content, those not will be less likely, but may still see it anyway. Any of the targeting fields shown here can be used, none are required. |
| `age_max` | `int` | Maximum age. Must be 65 or lower. |
| `age_min` | `int` | Must be 13 or higher. Default is 0. |
| `college_years` | `int[]` | Array of integers for graduation year from college. |
| `education_statuses` | `int[]` | Array of integers for targeting based on education level. Use `1` for high school, `2` for undergraduate, and `3` for alum (or localized equivalents). |
| `genders` | `list<unsigned int32>` | Target specific genders. `1` targets all male viewers and `2` females. Default is to target both. |
| `geo_locations` | `object` | This object allows you to specify a number of different geographic locations. Please see our [targeting guide](/docs/graph-api/reference/targeting) for information on this object. |
| `interests` | `int[]` | One or more IDs to target fans. Use `type=audienceinterest` to get possible IDs as [Targeting Options](/docs/graph-api/reference/targeting/) and use the returned id to specify. |
| `locales` | `int` | Targeted locales. Use `type` of `adlocale` to [find Targeting Options](/docs/graph-api/reference/targeting/) and use the returned `key` to specify. |
| `relationship_statuses` | `list<unsigned int32>` | Array of integers for targeting based on relationship status. Use `1` for single, `2` for 'in a relationship', `3` for married, and `4` for engaged. Default is all types. |
| `link` | `string` | The URL of a link to attach to the post. Either `link` or `message` must be supplied. Additional fields associated with `link` are shown below. See the [Custom Links Section](#custom-image) for restrictions. |
| `description` | `string` | Overwrites the description in the link preview |
| `name` | `string` | Overwrites the title of the link preview. |
| `picture` | `string` | Determines the preview image associated with the link. |
| `thumbnail` | `file` | Preview image associated with the link uploaded by you. |
| `message` | `string` | The main body of the post. The message can contain [mentions of Facebook Pages](/docs/pages/mentions), `@[page-id]`. |
| `multi_share_end_card` | `Boolean` | If set to `false`, does not display the end card of a carousel link post when `child_attachments` is used. Default is `true`. |
| `multi_share_optimized` | `Boolean` | If set to `true` and only when the post is used in an ad, Facebook will automatically select the order of links in `child_attachments`. Otherwise, the original ordering of `child_attachments` is preserved. Default value is true. |
| `object_attachment` | `string` | Facebook ID for an existing picture in the person's photo albums to use as the thumbnail image. They must be the owner of the photo, and the photo cannot be part of a message attachment. |
| `place` | `string` | Page ID of a location associated with this post. |
| `published` | `Boolean` | Whether a story is shown about this newly published object. Default is `true` which means the story is displayed in Feed. This field is `not` supported when actions parameter is specified. Unpublished posts can be used in ads. |
| `scheduled_publish_time` | `timestamp` | UNIX timestamp indicating when post should go live. Must be date between 10 minutes and 75 days from the time of the API request. |
| `tags` | `csv[string]` | Comma-separated list of user IDs of people tagged in this post. You cannot specify this field without also specifying a `place`. |
| `targeting` | `object` | Object that [limits the audience](https://www.facebook.com/help/352402648173466) for this content. Anyone not in these demographics will not be able to view this content. This will not override any Page-level demographic restrictions that may be in place. |
| `age_min` | `int` | Value can be 13, 15, 18, 21, or 25. |
| `geo_locations` | `object` | This object allows you to specify a number of different geographic locations. Please see our [targeting guide for information on this object](/docs/graph-api/reference/targeting). |

### Add a Feeling or Activity to a Page Post

Add a feeling or activity and an icon to a page post. `og_action_type_id` and `og_object_id` are required when posting a feeling or activity. `og_icon_id` is optional however if not used an icon will be automatically supplied based on the `og_object_id`.

#### Fields

Name | Description || [`og_action_type_id`](/docs/graph-api/reference/page/feed/feelings#actions) | An [action](/docs/graph-api/reference/page/feed/feelings#actions), i.e., *feeling*, *watching*, etc. |
| [`og_icon_id`](/docs/graph-api/reference/page/feed/feelings#icons) | An [icon](/docs/graph-api/reference/page/feed/feelings#icons) perhaps representing the action type, i.e., a smiley face, a movie icon, etc. |
| [`og_object_id`](/docs/graph-api/reference/page/feed/feelings#objects) | The target of the action, i.e., *happy*, *movie*, etc. This can be a [predefined object](/docs/graph-api/reference/page/feed/feelings#objects) or any `page_id`. |

#### Example Post

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK

```
POST /v25.0/page-id/feed HTTP/1.1
Host: graph.facebook.com

message=This+is+a+test+activity&og_action_type_id=383634835006146&og_object_id=136050896551329&og_icon_id=609297155780549
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->post(
    '/page-id/feed',
    array (
      'message' => 'This is a test activity',
      'og_action_type_id' => '383634835006146',
      'og_object_id' => '136050896551329',
      'og_icon_id' => '609297155780549',
    ),
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
    "/page-id/feed",
    "POST",
    {
        "message": "This is a test activity",
        "og_action_type_id": "383634835006146",
        "og_object_id": "136050896551329",
        "og_icon_id": "609297155780549"
    },
    function (response) {
      if (response && !response.error) {
        /* handle the result */
      }
    }
);
```

```
Bundle params = new Bundle();
params.putString("message", "This is a test activity");
params.putString("og_action_type_id", "383634835006146");
params.putString("og_object_id", "136050896551329");
params.putString("og_icon_id", "609297155780549");
/* make the API call */
new GraphRequest(
    AccessToken.getCurrentAccessToken(),
    "/page-id/feed",
    params,
    HttpMethod.POST,
    new GraphRequest.Callback() {
        public void onCompleted(GraphResponse response) {
            /* handle the result */
        }
    }
).executeAsync();
```

```
NSDictionary *params = @{
  @"message": @"This is a test activity",
  @"og_action_type_id": @"383634835006146",
  @"og_object_id": @"136050896551329",
  @"og_icon_id": @"609297155780549",
};
/* make the API call */
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
                               initWithGraphPath:@"/page-id/feed"
                                      parameters:params
                                      HTTPMethod:@"POST"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

The response will be the `post_id`.

### Unpublished Page Posts

We support the following types of Unpublished Page Posts:

Post Type | Description || [Link](/docs/graph-api/reference/link) | A link Page post is most effective for sharing links to your website. Allows for optional replacement of image and extra text.  Note: A Youtube video link will be a link Page post. |
| [Photo](/docs/graph-api/reference/photo) | A photo Page post with a text description and an optional link as part of the description. |
| [Post](/docs/graph-api/reference/post) | A Page post with a text description. |
| [Video](/docs/graph-api/reference/video) | A video Page post with optional text description. |

Unpublished Page posts are treated the same as published Page posts except that they do not appear in `/feed`.

To see a list of unpublished Page posts, query the `is_published` field.

cURLAndroid SDKObjective-CJava SDKPHP SDK

```
curl -i -X GET \
 "https://graph.facebook.com/{page-id}/feed
 ?fields=is_published
 &access_token={your-page-access-token}"
```

```
GraphRequest request = GraphRequest.newGraphPathRequest(
  accessToken,
  "/{page-id}/feed",
  new GraphRequest.Callback() {
    @Override
    public void onCompleted(GraphResponse response) {
      // Insert your code here
    }
});

Bundle parameters = new Bundle();
parameters.putString("fields", "is_published");
request.setParameters(parameters);
request.executeAsync();
```

```
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
    initWithGraphPath:@"/{page-id}/feed"
           parameters:@{ @"fields": @"is_published",}
           HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection, id result, NSError *error) {
    // Insert your code here
}];
```

```
FB.api(
  '/{page-id}/feed',
  'GET',
  {"fields":"is_published"},
  function(response) {
      // Insert your code here
  }
);
```

```
try {
  // Returns a `FacebookFacebookResponse` object
  $response = $fb->get(
    '/{page-id}/feed?fields=is_published',
    '{access-token}'
  );
} catch(FacebookExceptionsFacebookResponseException $e) {
  echo 'Graph returned an error: ' . $e->getMessage();
  exit;
} catch(FacebookExceptionsFacebookSDKException $e) {
  echo 'Facebook SDK returned an error: ' . $e->getMessage();
  exit;
}
$graphNode = $response->getGraphNode();
```

To view a post on Facebook.com, you can navigate to https://www.facebook.com/{post-id} for most post types, or retrieve the `actions` field of the post, which contains the URL at which a User can like or comment on the post.

### Page Post call\_to\_action

You can enhance your link Page posts with call to action buttons.
The following `call_to_action` field can be added to new link Page Posts.

Name | Type | Description || `call_to_action` | `object` | Object that specifies a Call to Action button. This should be the action you want people to take when they see your post. Clicking on this button will take people to the link you specify. |
| `type` | `string` | Determines the call to action button text. One of allowed values:  `BOOK_TRAVEL`. Call to action shows up as Book Now.  `BUY_NOW`. Call to action shows up as Buy Now. Only used for [desktop app ads for virtual goods](/docs/marketing-api/mobile-app-ads).  `CALL_NOW`. Call to action shows up as Call Now. Only used for [local awareness ads](/docs/marketing-api/guides/local-awareness).  `DOWNLOAD`. Call to action shows up as Download.  `GET_DIRECTIONS`. Call to action shows up as Get Directions. Must specify coordinates on the `link` field. Only used for [local awareness ads](/docs/marketing-api/guides/local-awareness).  `GET_QUOTE`. Call to action shows up as Get Quote for [lead generation](/docs/marketing-api/guides/lead-ads).  `INSTALL_APP`. Call to action shows up as Install Now.  `INSTALL_MOBILE_APP`. Call to action shows up as Install Now. Only used for [mobile app ads](/docs/marketing-api/mobile-app-ads).  `LEARN_MORE`. Call to action shows up as Learn More.  `LIKE_PAGE`. Call to action shows up as Like Page. Only used for ads in Page Likes [objective](/docs/marketing-api/reference/ad-campaign-group).  `LISTEN_MUSIC`. Call to action shows up as Listen Music.  `MESSAGE_PAGE`. Call to action shows up as Send Message. Only used for [local awareness ads](/docs/marketing-api/guides/local-awareness).  `NO_BUTTON`. No call to action shows up.  `OPEN_LINK`. Call to action shows up as Open Link. Only used for ads in Website Clicks [objective](/docs/marketing-api/reference/ad-campaign-group).  `PLAY_GAME`. Call to action shows up as Play Game. Only used for [desktop app ads](/docs/marketing-api/mobile-app-ads).  `SHOP_NOW`. Call to action shows up as Shop Now. Only used for ads in Website Conversions [objective](/docs/marketing-api/reference/ad-campaign-group).  `SIGN_UP`. Call to action shows up as Sign Up.  `SUBSCRIBE`. Call to action shows up as Subscribe for [lead generation](/docs/marketing-api/guides/lead-ads).  `USE_APP`. Call to action shows up as Use App.  `USE_MOBILE_APP`. Only used for [mobile app ads](/docs/marketing-api/mobile-app-ads).  `WATCH_MORE`. Call to action shows up as Watch More.  `WATCH_VIDEO`. Call to action shows up as Watch Video. |

### Custom Link Page Post Image

Post a link to a Page with a customized link image. The story's attachment renders an image retrieved from the link. Currently it is possible to override that image by providing an optional `picture` parameter with a URL to a new image. The `thumbnail` parameter offers similar functionality with the key difference being that the parameter accepts a local image file which is uploaded to Facebook in the API call.

#### Permissions

* A Page access token is required.
* The link must be owned by the posting Page.

To verify link ownership, check the `ownership_permissions{can_customize_link_posts}` field on the `URL` node. You must call this endpoint before posting new links. Without this step, custom link Page posts will not work for un-scraped links. See our [Link Ownership Guide](/docs/sharing/domain-verification) for more information. For versions 2.10 and lower, `picture`, `name`, `thumbnail`, and `description` are deprecated. `caption` is deprecated for all versions.

Parameters | Type | Description || `description` | string | The description of the link (appears beneath the link caption). If not specified, this field is automatically populated by information scraped from the link, typically the title of the page. |
| `name` | string | The name of the link attachment. This field is automatically populated by information scraped from the link. |
| `picture` | string | URL for the image. Image is sourced from the URL supplied in `picture` |
| `thumbnail` | file | Image file to be uploaded. Accepts `.jpg` `.jpeg` `.gif` or `.png`. Image is sourced from the file uploaded in `thumbnail` |

#### Limitations

* The `thumbnail` parameter is only available for link posts on Facebook Pages.
* The `thumbnail` parameter takes higher precedence over the `picture` parameter. If both are supplied the `picture` parameter is unused.
* The `thumbnail` parameter accepts images with extension `.jpg``.jpeg``.gif` or `.png`.
* The `thumbnail` parameter is not supported in batch requests.

### Posting a Link to a Page

Post a link to a Page by sending a POST request to the `/page/feed` edge. Set the `publish` parameter to `1` to publish the post immediately or to `0` to create an unpublished post to be published later.

#### Sample Request

cURLAndroid SDKObjective-CJava SDKPHP SDK

```
curl -i -X POST "https://graph.facebook.com/{your-page-id}/feed
  ?message=Become%20a%20Facebook%20developer!
  &link=https%3A%2F%2Fdevelopers.facebook.com
  &published=1
  &access_token={your-page-access-token}"
```

```
GraphRequest request = GraphRequest.newPostRequest(
  accessToken,
  "/{your-page-id}/feed",
  new JSONObject("{\"message\":\"Become a Facebook developer!\",\"link\":\"https://developers.facebook.com\",\"published\":\"1\"}"),
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
    initWithGraphPath:@"/{your-page-id}/feed"
           parameters:@{ @"message": @"Become a Facebook developer!",@"link": @"https://developers.facebook.com",@"published": @"1",}
           HTTPMethod:@"POST"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection, id result, NSError *error) {
    // Insert your code here
}];
```

```
FB.api(
  '/{your-page-id}/feed',
  'POST',
  {"message":"Become a Facebook developer!","link":"https://developers.facebook.com","published":"1"},
  function(response) {
      // Insert your code here
  }
);
```

```
try {
  // Returns a `FacebookFacebookResponse` object
  $response = $fb->post(
    '/{your-page-id}/feed',
    array (
      'message' => 'Become a Facebook developer!',
      'link' => 'https://developers.facebook.com',
      'published' => '1'
    ),
    '{access-token}'
  );
} catch(FacebookExceptionsFacebookResponseException $e) {
  echo 'Graph returned an error: ' . $e->getMessage();
  exit;
} catch(FacebookExceptionsFacebookSDKException $e) {
  echo 'Facebook SDK returned an error: ' . $e->getMessage();
  exit;
}
$graphNode = $response->getGraphNode();
```

#### Sample Response

```
{"id":"{post-id}"}
```

### Link Page Post with Call to Action

The `call_to_action` field specifies the appropriate action and relevant link. This link should be the same as the `link` parameter of the Page Post. In this call, `title`, `description`, `caption` and `picture` are optional, and when not provided, Facebook will read the equivalent properties from the link's Open Graph meta data. If the linked web page does not have Open Graph meta data, Facebook will try to guess these properties by scraping the web page's content.

#### Sample Request

cURLAndroid SDKObjective-CJava SDKPHP SDK

```
curl -i -X POST "https://graph.facebook.com/{your-page-id}/feed
  ?message=Become a Facebook developer!
  &link=https://developers.facebook.com
  &call_to_action={"type":"SIGN_UP","value":{"link":"https://developers.facebook.com"}}
  &published=1
  &access_token={your-page-access-token}"
```

```
GraphRequest request = GraphRequest.newPostRequest(
  accessToken,
  "/{your-page-id}/feed",
  new JSONObject("{\"message\":\"Become a Facebook developer!\",\"link\":\"https://developers.facebook.com\",\"published\":\"1\",\"call_to_action\":\"{\\\"type\\\":\\\"SIGN_UP\\\",\\\"value\\\":{\\\"link\\\":\\\"https://developers.facebook.com\\\"}}\"}"),
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
    initWithGraphPath:@"/{your-page-id}/feed"
           parameters:@{ @"message": @"Become a Facebook developer!",@"link": @"https://developers.facebook.com",@"published": @"1",@"call_to_action": @"{"type":"SIGN_UP","value":{"link":"https://developers.facebook.com"}}",}
           HTTPMethod:@"POST"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection, id result, NSError *error) {
    // Insert your code here
}];
```

```
FB.api(
  '/{your-page-id}/feed',
  'POST',
  {"message":"Become a Facebook developer!","link":"https://developers.facebook.com","published":"1","call_to_action":"{\"type\":\"SIGN_UP\",\"value\":{\"link\":\"https://developers.facebook.com\"}}"},
  function(response) {
      // Insert your code here
  }
);
```

```
try {
  // Returns a `FacebookFacebookResponse` object
  $response = $fb->post(
    '/{your-page-id}/feed',
    array (
      'message' => 'Become a Facebook developer!',
      'link' => 'https://developers.facebook.com',
      'published' => '1',
      'call_to_action' => '{"type":"SIGN_UP","value":{"link":"https://developers.facebook.com"}}'
    ),
    '{access-token}'
  );
} catch(FacebookExceptionsFacebookResponseException $e) {
  echo 'Graph returned an error: ' . $e->getMessage();
  exit;
} catch(FacebookExceptionsFacebookSDKException $e) {
  echo 'Facebook SDK returned an error: ' . $e->getMessage();
  exit;
}
$graphNode = $response->getGraphNode();
```

#### Sample Response

```
{"id":"{post-id}"}
```

### Link Post with Custom Uploaded Image

#### Using a local file:

```
curl -F 'link=http://www.example.com' \
     -F 'thumbnail=@/local/path/to/file/on/hard/drive/image.jpg' \
     -F 'access_token=page-access-token'\
  https://graph.facebook.com/v2.11/page-id/feed
```

Return Value

```
{"id":"post-id"}
```

#### Using an Image via URL:

```
curl -F 'link=http://www.example.com' \
     -F 'picture=https://www.example.com/path/to/image.jpg' \
     -F 'access_token=page-access-token'\
  https://graph.facebook.com/v2.11/page-id/feed
```

Return Value

```
{"id":"post-id>"}
```

### Photo Page Post

Please visit our [Photo Node Reference](https://developers.facebook.com/docs/graph-api/reference/photo/#Creating) for more information.

### Video Page Post

Please visit our [Page Video Reference](https://developers.facebook.com/docs/graph-api/reference/page/videos/) for more information.

### Page Post Insights

Please visit our [Page Post Insights Reference](/docs/reference/api/insights/#post_impressions) for more information.

## Updating

You can't update using this edge, however you can [update posts using the `/{post-id}` node](/docs/reference/api/post/#updating).

## Deleting

You can't delete using this edge, however you can [delete posts using the `/{post-id}` node](/docs/reference/api/post/).

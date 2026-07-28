# Instagram Media Insights



Represents social interaction metrics on your app user&#039;s Instagram Media object.

## Creating &#123;#create&#125;

This operation is not supported.

## Reading &#123;#read&#125;

**`GET /&lt;INSTAGRAM_MEDIA_ID&gt;/insights`**

Get insights data on an Instagram Media object.

### Limitations

- If insights data you are requesting does not exist or is currently unavailable, the API returns an empty data set instead of `0` for individual metrics.
- Data used to calculate metrics can be delayed up to 48 hours.
- Metrics data is stored for up to 2 years.
- Metrics such as `comments`, `likes`, `views`, and `total_interactions` report organic interaction metrics only; interactions on ads containing a media object are not counted. The `total_likes`, `total_comments`, and `total_views` metrics return aggregated counts that include engagement from promoted/boosted/ad media. These total metrics are available for Instagram API with Facebook Login only. Crossposted Facebook post&#039;s count may be included if that post is accessible by the session user.

#### Album metrics

- Insights data is not available for any media within an [Instagram Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) album.

#### Story media metrics

- Story media metrics are only available for 24 hours.
    * Set up [`Instagram` webhooks](https://developers.facebook.com/documentation/instagram-platform/webhooks) and subscribe to the `story_insights` field to get story insights for a story before they expire. You may receive data after the story expires if the story is added to a highlight. This may return different results for API calls, webhook notifications, and UIs.
- Story media metrics with values less than 5 return an error code `10` with the message `(#10) Not enough viewers for the media to show insights`.
- For Stories created by users in Europe and Japan, the `replies` metric now returns a value of `0`.
- Replies made by users in Europe and Japan are not included in `replies` calculations for story media metrics.

#### Webhooks

- Insights webhook for Instagram API with Instagram Login is not supported.

### Requirements

|  | Instagram API with Instagram Login | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User access token | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_insights` | * `instagram_basic`&lt;br&gt;* `instagram_manage_insights`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;&lt;br&gt;If the app user was granted a role on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to your app user&#039;s Instagram professional account via the Business Manager, your app will also need:&lt;br&gt;&lt;br&gt;* `ads_management`&lt;br&gt;* `ads_read` |

### Request syntax

```html
GET &quot;https://&lt;HOST_URL&gt;/&lt;API_VERSION&gt;/&lt;INSTAGRAM_MEDIA_ID&gt;/insights
  ?metric=&lt;LIST_OF_METRICS&gt;
  &amp;period=&lt;LIST_OF_TIME_PERIODS&gt;
  &amp;breakdown=&lt;LIST_OF_BREAKDOWNS&gt;
  &amp;access_token=&lt;ACCESS_TOKEN&gt;&quot;
```

#### Path parameters

| Placeholder | Value |
| --- | --- |
| `&lt;API_VERSION&gt;`&lt;br&gt;&lt;br&gt;**The latest version is:** v25.0&lt;br&gt; | The API version your app is using. If not specified in your API calls this will be the latest version at the time you created your Meta app or, if that version is no longer available, the oldest version available. [Learn more about versioning.](https://developers.facebook.com/docs/graph-api/guides/versioning)&lt;br&gt; |
| `&lt;HOST_URL&gt;` | The [host URL](#requirements) your app is using to query the endpoint. |
| `&lt;INSTAGRAM_MEDIA_ID&gt;` | **Required.** The [Instagram Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) ID. |

#### Query string parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `&lt;ACCESS_TOKEN&gt;` | **Required.** The app user&#039;s Facebook or Instagram User access token. |
| `breakdown` | `&lt;LIST_OF_BREAKDOWNS&gt;` | Designates how to [break down results into subsets](#breakdowns). |
| `metric` | `&lt;LIST_OF_METRICS&gt;` | **Required.** Comma-separated list of [metrics](#metrics) you want returned. |
| `period` | `&lt;LIST_OF_TIME_PERIODS&gt;` | Comma-separated list of time periods you want returned. Values can be:&lt;br&gt;&lt;br&gt;* `day`&lt;br&gt;* `week`&lt;br&gt;* `days_28`&lt;br&gt;* `month`&lt;br&gt;* `lifetime`&lt;br&gt;* `total_over_range` |

### Metrics

The following table shows the metrics and the media object types the are available on.

| Metric | Media Product Type |
| --- | --- |
| `comments`&lt;br&gt;&lt;br&gt;Number of comments on the media object. | `FEED` (posts)&lt;br&gt;`REELS` |
| `crossposted_views`&lt;br&gt;&lt;br&gt;Total number of times the video IG Media was played, aggregated across Instagram and Facebook. Throws if the media is not shared to Facebook | `REELS` |
| `facebook_views`&lt;br&gt;&lt;br&gt;Total number of times IG Media has been played on Facebook. Throws if the media is not shared to Facebook. For REELS, this can be either plays from crossposted or cross recommended from Instagram to Facebook | `FEED` (posts)&lt;br&gt;`REELS`&lt;br&gt;`STORY` |
| `follows`&lt;br&gt;&lt;br&gt;The number of Instagram users following your app user&#039;s Instagram professional account. | `FEED` (posts)&lt;br&gt;`STORY` |
| `ig_reels_avg_watch_time`&lt;br&gt;&lt;br&gt;The average amount of time spent playing the reel. | `REELS` |
| `ig_reels_video_view_total_time`&lt;br&gt;&lt;br&gt;The total amount of time the reel was played, including any time spent replaying the reel.&lt;br&gt;[Metric in development.](https://business.facebook.com/business/help/metrics-labeling)&lt;br&gt; | `REELS` |
| `impressions`&lt;br&gt;&lt;br&gt;**Warning:** For media created after July 2, 2024, this metric is deprecated.&lt;br&gt;For media created before July 2, 2024, this metric will still be available.&lt;br&gt;&lt;br&gt;Total number of times your app user&#039;s Instagram Media object has been seen. | `FEED` (posts)&lt;br&gt;`STORY` |
| `likes`&lt;br&gt;&lt;br&gt;Number of likes on the media object. | `FEED` (posts)&lt;br&gt;`REELS` |
| `link_clicks`&lt;br&gt;&lt;br&gt;The number of taps on links in your story. | `STORY` |
| `navigation`&lt;br&gt;&lt;br&gt;This is the total number of actions taken from your story. These are made up of metrics like exited, forward, back and next story.&lt;br&gt;&lt;br&gt;**Available breakdown:** `story_navigation_action_type` | `STORY` |
| `profile_activity`&lt;br&gt;&lt;br&gt;The number of actions people take when they visit your profile after engaging with your post.&lt;br&gt;&lt;br&gt;**Available breakdown:** `action_type`  (Available for media created after October 26, 2017.) | `FEED` (posts)&lt;br&gt;`STORY` |
| `profile_visits`&lt;br&gt;&lt;br&gt;The number of times your profile was visited. | `FEED` (posts)&lt;br&gt;`STORY` |
| `reach`&lt;br&gt;&lt;br&gt;Number of unique Instagram users that have seen the reel at least once. Reach is different from impressions, which can include multiple views of a reel by the same account.&lt;br&gt;[Metric is estimated.](https://business.facebook.com/business/help/metrics-labeling)&lt;br&gt; | `FEED` (posts)&lt;br&gt;`REELS`&lt;br&gt;`STORY` |
| `reels_skip_rate`&lt;br&gt;&lt;br&gt;The percentage of views from people who skipped during the first 3 seconds of the reel. This is calculcated as the number of views that skipped the reel during the first 3 seconds divided by the number of intial views. An intial view is when the reel starts to play for the first time in a reel session.&lt;br&gt;&lt;br&gt;[Metric is estimated and in development.](https://business.facebook.com/business/help/metrics-labeling) | `REELS` |
| `replies`&lt;br&gt;&lt;br&gt;Total number of replies ([IG Comments](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment)) on the story [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object. Value does not include replies made by users in some regions. These regions include: Europe starting December 1, 2020 and Japan starting April 14, 2021. If the Story was created by a user in one of these regions, returns a value of `0`. | `STORY` |
| `reposts`&lt;br&gt;&lt;br&gt;The number of reposts on the IG media minus the number of deleted reposts. | `FEED` (posts)&lt;br&gt;`REELS`&lt;br&gt;`STORY` |
| `saved`&lt;br&gt;&lt;br&gt;Number of time your app user&#039;s Instagram media was saved by an Instagram user. | `FEED` (posts)&lt;br&gt;`REELS` |
| `shares`&lt;br&gt;&lt;br&gt;Number of shares of the reel. | `FEED` (posts)&lt;br&gt;`REELS`&lt;br&gt;`STORY` |
| `total_interactions`&lt;br&gt;&lt;br&gt;Number of likes, saves, comments, and shares on the reel, minus the number of unlikes, unsaves, and deleted comments.&lt;br&gt;[Metric in development.](https://business.facebook.com/business/help/metrics-labeling)&lt;br&gt; | `FEED` (posts)&lt;br&gt;`REELS`&lt;br&gt;`STORY` |
| `views`&lt;br&gt;&lt;br&gt;Total number of times IG Media has been played on Instagram.&lt;br&gt;&lt;br&gt;[Metric in development.](https://business.facebook.com/business/help/metrics-labeling)&lt;br&gt; | `FEED` (posts)&lt;br&gt;`REELS`&lt;br&gt;`STORY` |
| `total_comments`&lt;br&gt;&lt;br&gt;Total number of comments on the media across all surfaces, including comments on associated promoted/boosted/ad media. Available for Instagram API with Facebook Login only. | `FEED` (posts)&lt;br&gt;`REELS` |
| `total_likes`&lt;br&gt;&lt;br&gt;Total number of likes on the media across all surfaces, including likes on associated promoted/boosted/ad media. Available for Instagram API with Facebook Login only. | `FEED` (posts)&lt;br&gt;`REELS` |
| `total_views`&lt;br&gt;&lt;br&gt;Total number of times the media has been seen across all surfaces, including views from promoted/boosted/ad media and Facebook. Available for Instagram API with Facebook Login only. | `FEED` (posts)&lt;br&gt;`REELS`&lt;br&gt;`STORY` |

### Breakdowns

You can also include the `breakdown` parameter for specific metrics to divide data into smaller sets based on the specified breakdown value. Values can be:

| `breakdown` value | Response values |
| --- | --- |
| `action_type`&lt;br&gt;&lt;br&gt;**Only compatible with the `profile_activity` metric.**&lt;br&gt;&lt;br&gt;Break down results by the profile component within the native app that viewers tapped or clicked after viewing the app user&#039;s profile. | * `BIO_LINK_CLICKED`&lt;br&gt;* `CALL`&lt;br&gt;* `DIRECTION`&lt;br&gt;* `EMAIL`&lt;br&gt;* `OTHER`&lt;br&gt;* `TEXT` |
| `story_navigation_action_type`&lt;br&gt;&lt;br&gt;**Only compatible with the `navigation` metric.**&lt;br&gt;&lt;br&gt;Break down results by navigation action taken by the viewer upon viewing the media within the native app. Adding all of these action types will give you the total navigation insights. | * `SWIPE_FORWARD` equals &quot;Next Story&quot;&lt;br&gt;* `TAP_BACK` equals &quot;Back&quot;&lt;br&gt;* `TAP_EXIT` equals &quot;Exit&quot;&lt;br&gt;* `TAP_FORWARD` equals &quot;Forward&quot; |

**NOTE:** If you request a metric that doesn&#039;t support breakdowns, the API will return an error (&quot;`An unknown error has occurred.`&quot;), so be careful if requesting multiple metrics in a single query.

### Response syntax

On success your app receives a JSON object containing the results of your query. Results can include the following data, based on your query specifications:

```html
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;name&quot;: &quot;&lt;NAME&gt;&quot;,
      &quot;period&quot;: &quot;&lt;PERIOD&gt;&quot;,
      &quot;values&quot;: [
        &#123;
          &quot;value&quot;: &lt;VALUE&gt;
        &#125;
      ],
      &quot;title&quot;: &quot;&lt;TITLE&gt;&quot;,
      &quot;description&quot;: &quot;&lt;DESCRIPTION&gt;&quot;,
      &quot;total_value&quot;: &#123;
        &quot;value&quot;:&lt;VALUE&gt;,
        &quot;breakdowns&quot;: [
          &#123;
            &quot;dimension_keys&quot;: [
              &quot;&lt;DIMENSION_KEY_1&gt;&quot;,
              &quot;&lt;DIMENSION_KEY_2&gt;&quot;
              ...
            ],
            &quot;results&quot;: [
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;&lt;DIMENSION_VALUE_1&gt;&quot;,
                  &quot;&lt;DIMENSION_VALUE_2&gt;&quot;
                  ...
                ],
                &quot;value&quot;: &lt;VALUE&gt;
              &#125;,
              ...
            ]
          &#125;
        ]
      &#125;,
      &quot;id&quot;: &quot;&lt;ID&gt;&quot;
    &#125;
  ]
&#125;
```

#### Response contents

| Property | Value Type | Description |
| --- | --- | --- |
| `data` | Array | An array containing an object describing your request results. |
| `name` | String | [Metric](#metrics) name. |
| `period` | String | Period requested. Period is automatically set to `lifetime` in the request and cannot be changed, so this value will always be `lifetime`. |
| `values` | Array | An array containing an object describing requested [metric](#metrics) values. |
| `value` | Integer | For `data.values.value`, sum of requested [metric](#metrics) values.&lt;br&gt;&lt;br&gt;For `data.total_value.value`, sum of requested [breakdown](#breakdowns) values.&lt;br&gt;&lt;br&gt;For `data.total_value.breakdowns.results.value`, sum of [breakdown](#breakdowns) set values. |
| `title` | String | [Metric](#metrics) title. |
| `description` | String | [Metric](#metrics) description. |
| `id` | String | A string describing the query&#039;s path parameters. |
| `total_value` | Object | Object describing requested [breakdown](#breakdowns) values (if breakdowns were requested). |
| `breakdowns` | Array | An array of objects describing the [breakdowns](#breakdowns) requested and their results. |
| `dimension_keys` | Array | Array of strings describing [breakdowns](#breakdowns) requested. |
| `results` | Array | An array of objects describing each [breakdown](#breakdowns) set. |
| `dimension_values` | String | An array of strings describing [breakdown](#breakdowns) set values. Values can be mapped to `dimension_keys`. |
| `paging` | Object | An object containing URLs used to request the next set of results. See [Paginated Results](docs/graph-api/results) for more information. |
| `previous` | String | URL to retrieve the previous page of results. See [Paginated Results](docs/graph-api/results) for more information. |
| `next` | String | URL to retrieve the next page of results. See [Paginated Results](docs/graph-api/results) for more information. |

### Examples

#### Sample post metric request

The following is a request from an app that uses Facebook Login.

```curl
curl -i -X GET \
 &quot;https://graph.facebook.com/v25.0/17932174733377207/insights?metric=profile_activity&amp;breakdown=action_type&amp;access_token=EAAOc...&quot;
```

#### Sample post metric response

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;name&quot;: &quot;profile_activity&quot;,
      &quot;period&quot;: &quot;lifetime&quot;,
      &quot;values&quot;: [
        &#123;
          &quot;value&quot;: 4
        &#125;
      ],
      &quot;title&quot;: &quot;Profile activity&quot;,
      &quot;description&quot;: &quot;[IG Insights] This header is the name of a metric that appears on an educational info sheet for a particular post, story, video or promotion. This metric is the sum of all profile actions people take when they engage with this content.&quot;,
      &quot;total_value&quot;: &#123;
        &quot;value&quot;: 4,
        &quot;breakdowns&quot;: [
          &#123;
            &quot;dimension_keys&quot;: [
              &quot;action_type&quot;
            ],
            &quot;results&quot;: [
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;email&quot;
                ],
                &quot;value&quot;: 1
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;text&quot;
                ],
                &quot;value&quot;: 1
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;direction&quot;
                ],
                &quot;value&quot;: 1
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;bio_link_clicked&quot;
                ],
                &quot;value&quot;: 1
              &#125;
            ]
          &#125;
        ]
      &#125;,
      &quot;id&quot;: &quot;17932174733377207/insights/profile_activity/lifetime&quot;
    &#125;
  ]
&#125;
```

#### Sample story metric request

The following is a request from an app that uses Instagram Login.

```curl
curl -i -X GET \
 &quot;https://graph.instagram.com/v25.0/17969782069736348/insights?metric=navigation&amp;breakdown=story_navigation_action_type&amp;access_token=EAAOc...&quot;
```

#### Sample story metric response

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;name&quot;: &quot;navigation&quot;,
      &quot;period&quot;: &quot;lifetime&quot;,
      &quot;values&quot;: [
        &#123;
          &quot;value&quot;: 25
        &#125;
      ],
      &quot;title&quot;: &quot;Navigation&quot;,
      &quot;description&quot;: &quot;This is the total number of actions taken from your story. These are made up of metrics like exited, forward, back and next story.&quot;,
      &quot;total_value&quot;: &#123;
        &quot;value&quot;: 25,
        &quot;breakdowns&quot;: [
          &#123;
            &quot;dimension_keys&quot;: [
              &quot;story_navigation_action_type&quot;
            ],
            &quot;results&quot;: [
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;tap_forward&quot;
                ],
                &quot;value&quot;: 19
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;tap_back&quot;
                ],
                &quot;value&quot;: 4
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;tap_exit&quot;
                ],
                &quot;value&quot;: 1
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;swipe_forward&quot;
                ],
                &quot;value&quot;: 1
              &#125;
            ]
          &#125;
        ]
      &#125;,
      &quot;id&quot;: &quot;17969782069736348/insights/navigation/lifetime&quot;
    &#125;
  ]
&#125;
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

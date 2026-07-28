# Instagram Media Insights



Represents social interaction metrics on your app user's Instagram Media object.

## Creating {#create}

This operation is not supported.

## Reading {#read}

**`GET /<INSTAGRAM_MEDIA_ID>/insights`**

Get insights data on an Instagram Media object.

### Limitations

- If insights data you are requesting does not exist or is currently unavailable, the API returns an empty data set instead of `0` for individual metrics.
- Data used to calculate metrics can be delayed up to 48 hours.
- Metrics data is stored for up to 2 years.
- Metrics such as `comments`, `likes`, `views`, and `total_interactions` report organic interaction metrics only; interactions on ads containing a media object are not counted. The `total_likes`, `total_comments`, and `total_views` metrics return aggregated counts that include engagement from promoted/boosted/ad media. These total metrics are available for Instagram API with Facebook Login only. Crossposted Facebook post's count may be included if that post is accessible by the session user.

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
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`<br>* `instagram_business_manage_insights` | * `instagram_basic`<br>* `instagram_manage_insights`<br>* `pages_read_engagement`<br><br>If the app user was granted a role on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to your app user's Instagram professional account via the Business Manager, your app will also need:<br><br>* `ads_management`<br>* `ads_read` |

### Request syntax

```html
GET "https://<HOST_URL>/<API_VERSION>/<INSTAGRAM_MEDIA_ID>/insights
  ?metric=<LIST_OF_METRICS>
  &period=<LIST_OF_TIME_PERIODS>
  &breakdown=<LIST_OF_BREAKDOWNS>
  &access_token=<ACCESS_TOKEN>"
```

#### Path parameters

| Placeholder | Value |
| --- | --- |
| `<API_VERSION>`<br><br>**The latest version is:** v25.0<br> | The API version your app is using. If not specified in your API calls this will be the latest version at the time you created your Meta app or, if that version is no longer available, the oldest version available. [Learn more about versioning.](https://developers.facebook.com/docs/graph-api/guides/versioning)<br> |
| `<HOST_URL>` | The [host URL](#requirements) your app is using to query the endpoint. |
| `<INSTAGRAM_MEDIA_ID>` | **Required.** The [Instagram Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) ID. |

#### Query string parameters

| Key | Placeholder | Value |
| --- | --- | --- |
| `access_token` | `<ACCESS_TOKEN>` | **Required.** The app user's Facebook or Instagram User access token. |
| `breakdown` | `<LIST_OF_BREAKDOWNS>` | Designates how to [break down results into subsets](#breakdowns). |
| `metric` | `<LIST_OF_METRICS>` | **Required.** Comma-separated list of [metrics](#metrics) you want returned. |
| `period` | `<LIST_OF_TIME_PERIODS>` | Comma-separated list of time periods you want returned. Values can be:<br><br>* `day`<br>* `week`<br>* `days_28`<br>* `month`<br>* `lifetime`<br>* `total_over_range` |

### Metrics

The following table shows the metrics and the media object types the are available on.

| Metric | Media Product Type |
| --- | --- |
| `comments`<br><br>Number of comments on the media object. | `FEED` (posts)<br>`REELS` |
| `crossposted_views`<br><br>Total number of times the video IG Media was played, aggregated across Instagram and Facebook. Throws if the media is not shared to Facebook | `REELS` |
| `facebook_views`<br><br>Total number of times IG Media has been played on Facebook. Throws if the media is not shared to Facebook. For REELS, this can be either plays from crossposted or cross recommended from Instagram to Facebook | `FEED` (posts)<br>`REELS`<br>`STORY` |
| `follows`<br><br>The number of Instagram users following your app user's Instagram professional account. | `FEED` (posts)<br>`STORY` |
| `ig_reels_avg_watch_time`<br><br>The average amount of time spent playing the reel. | `REELS` |
| `ig_reels_video_view_total_time`<br><br>The total amount of time the reel was played, including any time spent replaying the reel.<br>[Metric in development.](https://business.facebook.com/business/help/metrics-labeling)<br> | `REELS` |
| `impressions`<br><br>**Warning:** For media created after July 2, 2024, this metric is deprecated.<br>For media created before July 2, 2024, this metric will still be available.<br><br>Total number of times your app user's Instagram Media object has been seen. | `FEED` (posts)<br>`STORY` |
| `likes`<br><br>Number of likes on the media object. | `FEED` (posts)<br>`REELS` |
| `link_clicks`<br><br>The number of taps on links in your story. | `STORY` |
| `navigation`<br><br>This is the total number of actions taken from your story. These are made up of metrics like exited, forward, back and next story.<br><br>**Available breakdown:** `story_navigation_action_type` | `STORY` |
| `profile_activity`<br><br>The number of actions people take when they visit your profile after engaging with your post.<br><br>**Available breakdown:** `action_type`  (Available for media created after October 26, 2017.) | `FEED` (posts)<br>`STORY` |
| `profile_visits`<br><br>The number of times your profile was visited. | `FEED` (posts)<br>`STORY` |
| `reach`<br><br>Number of unique Instagram users that have seen the reel at least once. Reach is different from impressions, which can include multiple views of a reel by the same account.<br>[Metric is estimated.](https://business.facebook.com/business/help/metrics-labeling)<br> | `FEED` (posts)<br>`REELS`<br>`STORY` |
| `reels_skip_rate`<br><br>The percentage of views from people who skipped during the first 3 seconds of the reel. This is calculcated as the number of views that skipped the reel during the first 3 seconds divided by the number of intial views. An intial view is when the reel starts to play for the first time in a reel session.<br><br>[Metric is estimated and in development.](https://business.facebook.com/business/help/metrics-labeling) | `REELS` |
| `replies`<br><br>Total number of replies ([IG Comments](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment)) on the story [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object. Value does not include replies made by users in some regions. These regions include: Europe starting December 1, 2020 and Japan starting April 14, 2021. If the Story was created by a user in one of these regions, returns a value of `0`. | `STORY` |
| `reposts`<br><br>The number of reposts on the IG media minus the number of deleted reposts. | `FEED` (posts)<br>`REELS`<br>`STORY` |
| `saved`<br><br>Number of time your app user's Instagram media was saved by an Instagram user. | `FEED` (posts)<br>`REELS` |
| `shares`<br><br>Number of shares of the reel. | `FEED` (posts)<br>`REELS`<br>`STORY` |
| `total_interactions`<br><br>Number of likes, saves, comments, and shares on the reel, minus the number of unlikes, unsaves, and deleted comments.<br>[Metric in development.](https://business.facebook.com/business/help/metrics-labeling)<br> | `FEED` (posts)<br>`REELS`<br>`STORY` |
| `views`<br><br>Total number of times IG Media has been played on Instagram.<br><br>[Metric in development.](https://business.facebook.com/business/help/metrics-labeling)<br> | `FEED` (posts)<br>`REELS`<br>`STORY` |
| `total_comments`<br><br>Total number of comments on the media across all surfaces, including comments on associated promoted/boosted/ad media. Available for Instagram API with Facebook Login only. | `FEED` (posts)<br>`REELS` |
| `total_likes`<br><br>Total number of likes on the media across all surfaces, including likes on associated promoted/boosted/ad media. Available for Instagram API with Facebook Login only. | `FEED` (posts)<br>`REELS` |
| `total_views`<br><br>Total number of times the media has been seen across all surfaces, including views from promoted/boosted/ad media and Facebook. Available for Instagram API with Facebook Login only. | `FEED` (posts)<br>`REELS`<br>`STORY` |

### Breakdowns

You can also include the `breakdown` parameter for specific metrics to divide data into smaller sets based on the specified breakdown value. Values can be:

| `breakdown` value | Response values |
| --- | --- |
| `action_type`<br><br>**Only compatible with the `profile_activity` metric.**<br><br>Break down results by the profile component within the native app that viewers tapped or clicked after viewing the app user's profile. | * `BIO_LINK_CLICKED`<br>* `CALL`<br>* `DIRECTION`<br>* `EMAIL`<br>* `OTHER`<br>* `TEXT` |
| `story_navigation_action_type`<br><br>**Only compatible with the `navigation` metric.**<br><br>Break down results by navigation action taken by the viewer upon viewing the media within the native app. Adding all of these action types will give you the total navigation insights. | * `SWIPE_FORWARD` equals "Next Story"<br>* `TAP_BACK` equals "Back"<br>* `TAP_EXIT` equals "Exit"<br>* `TAP_FORWARD` equals "Forward" |

**NOTE:** If you request a metric that doesn't support breakdowns, the API will return an error ("`An unknown error has occurred.`"), so be careful if requesting multiple metrics in a single query.

### Response syntax

On success your app receives a JSON object containing the results of your query. Results can include the following data, based on your query specifications:

```html
{
  "data": [
    {
      "name": "<NAME>",
      "period": "<PERIOD>",
      "values": [
        {
          "value": <VALUE>
        }
      ],
      "title": "<TITLE>",
      "description": "<DESCRIPTION>",
      "total_value": {
        "value":<VALUE>,
        "breakdowns": [
          {
            "dimension_keys": [
              "<DIMENSION_KEY_1>",
              "<DIMENSION_KEY_2>"
              ...
            ],
            "results": [
              {
                "dimension_values": [
                  "<DIMENSION_VALUE_1>",
                  "<DIMENSION_VALUE_2>"
                  ...
                ],
                "value": <VALUE>
              },
              ...
            ]
          }
        ]
      },
      "id": "<ID>"
    }
  ]
}
```

#### Response contents

| Property | Value Type | Description |
| --- | --- | --- |
| `data` | Array | An array containing an object describing your request results. |
| `name` | String | [Metric](#metrics) name. |
| `period` | String | Period requested. Period is automatically set to `lifetime` in the request and cannot be changed, so this value will always be `lifetime`. |
| `values` | Array | An array containing an object describing requested [metric](#metrics) values. |
| `value` | Integer | For `data.values.value`, sum of requested [metric](#metrics) values.<br><br>For `data.total_value.value`, sum of requested [breakdown](#breakdowns) values.<br><br>For `data.total_value.breakdowns.results.value`, sum of [breakdown](#breakdowns) set values. |
| `title` | String | [Metric](#metrics) title. |
| `description` | String | [Metric](#metrics) description. |
| `id` | String | A string describing the query's path parameters. |
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
 "https://graph.facebook.com/v25.0/17932174733377207/insights?metric=profile_activity&breakdown=action_type&access_token=EAAOc..."
```

#### Sample post metric response

```json
{
  "data": [
    {
      "name": "profile_activity",
      "period": "lifetime",
      "values": [
        {
          "value": 4
        }
      ],
      "title": "Profile activity",
      "description": "[IG Insights] This header is the name of a metric that appears on an educational info sheet for a particular post, story, video or promotion. This metric is the sum of all profile actions people take when they engage with this content.",
      "total_value": {
        "value": 4,
        "breakdowns": [
          {
            "dimension_keys": [
              "action_type"
            ],
            "results": [
              {
                "dimension_values": [
                  "email"
                ],
                "value": 1
              },
              {
                "dimension_values": [
                  "text"
                ],
                "value": 1
              },
              {
                "dimension_values": [
                  "direction"
                ],
                "value": 1
              },
              {
                "dimension_values": [
                  "bio_link_clicked"
                ],
                "value": 1
              }
            ]
          }
        ]
      },
      "id": "17932174733377207/insights/profile_activity/lifetime"
    }
  ]
}
```

#### Sample story metric request

The following is a request from an app that uses Instagram Login.

```curl
curl -i -X GET \
 "https://graph.instagram.com/v25.0/17969782069736348/insights?metric=navigation&breakdown=story_navigation_action_type&access_token=EAAOc..."
```

#### Sample story metric response

```json
{
  "data": [
    {
      "name": "navigation",
      "period": "lifetime",
      "values": [
        {
          "value": 25
        }
      ],
      "title": "Navigation",
      "description": "This is the total number of actions taken from your story. These are made up of metrics like exited, forward, back and next story.",
      "total_value": {
        "value": 25,
        "breakdowns": [
          {
            "dimension_keys": [
              "story_navigation_action_type"
            ],
            "results": [
              {
                "dimension_values": [
                  "tap_forward"
                ],
                "value": 19
              },
              {
                "dimension_values": [
                  "tap_back"
                ],
                "value": 4
              },
              {
                "dimension_values": [
                  "tap_exit"
                ],
                "value": 1
              },
              {
                "dimension_values": [
                  "swipe_forward"
                ],
                "value": 1
              }
            ]
          }
        ]
      },
      "id": "17969782069736348/insights/navigation/lifetime"
    }
  ]
}
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

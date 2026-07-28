# Instagram Account Insights



Represents social interaction metrics on your app user's Instagram business or creator account.

In this guide, we use **Instagram user** and **Instagram account** interchangeably.

**Success:** Available for the Instagram API with Facebook Login and Instagram API with Instagram Login.

**Warning:** The following metrics have been deprecated for v22.0 and will be deprecated for all versions on April 21, 2025:

* `impressions`

Introducing the new `views` metric with `total_value` metric type and with breakdowns for `follower_type` and `media_product_type`.

Visit the [Instagram Platform Changelog](https://developers.facebook.com/documentation/instagram-platform/changelog) for more information.

## Creating

This operation is not supported.

## Reading

**`GET /<YOUR_APP_USERS_INSTAGRAM_ACCOUNT_ID>/insights`**

Returns insights on your app user's Instagram business or creator account.

### Requirements

|  | Instagram API with Instagram Login | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User access token | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`<br>* `instagram_business_manage_insights` | * `instagram_basic`<br>* `instagram_manage_insights`<br>* `pages_read_engagement`<br><br>If the app user was granted a role on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to your app user's Instagram professional account via the Business Manager, your app will also need:<br><br>* `ads_management`<br>* `ads_read` |

### Limitations

- `follower_count` and `online_followers` metrics are not available on Instagram business or creator accounts with fewer than 100 followers.
- Insights data for the `online_followers` metric is only available for the last 30 days.
- If insights data you are requesting does not exist or is currently unavailable, the API will return an empty data set instead of `0` for individual metrics.
- Demographic metrics only return the top 45 performers.
- Only viewers for whom we have demographic data are used in demographic metric calculations.
- Summing demographic metric values may result in a value less than the follower count (see previous bullet point).
- Data used to calculate metrics may be delayed up to 48 hours.

### Request Syntax

```html
GET https://<HOST_URL>/<API_VERSION>/<APP_USERS_INSTAGRAM_ACCOUNT_ID>/insights
  ?metric=<COMMA_SEPARATED_LIST_OF_METRICS>
  &period=<PERIOD>
  &timeframe=<TIMEFRAME>
  &metric_type=<METRIC_TYPE>
  &breakdown=<BREAKDOWN_METRIC>
  &since=<START_TIME>
  &until=<STOP_TIME>
  &access_token=<INSTAGRAM_USER_ACCESS_TOKEN>
```

### Host Path Parameters

```html
GET https://<HOST_URL>/<API_VERSION>/<APP_USERS_INSTAGRAM_ACCOUNT_ID>/insights
```

| Placeholder | Value |
| --- | --- |
| `<API_VERSION>`<br>The latest version is: v25.0<br> | The API version your app is using when making calls to Meta servers.<br>[Learn more about API versioning.](https://developers.facebook.com/docs/graph-api/guides/versioning)<br> |
| `<APP_USERS_INSTAGRAM_ACCOUNT_ID>` | **Required.** The ID of your app user's Instagram professional account. |
| `<HOST_URL>` | **Required.** The ID of your app user's Instagram professional account. |

### Parameters

| Key | Value |
| --- | --- |
| `access_token` | **Required.** The app user's Facebook User or Instagram access token. |
| `breakdown` | Designates how to break down result set into subsets.<br><br>*  `contact_button_type` – Divides results by profile component in the native app.<br>*  `follow_type` – Breaks down results by followers or non-followers.<br>* `media_product_type` – Breaks down results by surface where Instagram users view or interact with your app user's media. |
| `metric` | **Required.** Comma-separated list of [Metrics](#metrics) you want returned.<br><br>`<COMMA_SEPARATED_LIST_OF_METRICS>` |
| `metric_type` | Designates if you want the responses aggregated by time period or as a simple total. See [Metric Type](#metric-type). `<METRIC_TYPE>` |
| `period` | **Required.** [Period](#period) aggregation. `<PERIOD>` |
| `since` | Unix timestamp indicating start of range. See [Range](#range).<br>`<START_TIME>` |
| `timeframe` | **Required for demographics-related metrics.** Designates how far to look back for data. See [Timeframe](#timeframe). `<TIMEFRAME>` |
| `until` | Unix timestamp indicating end of range. See [Range](#range).  `<STOP_TIME>` |

### Breakdown

If you request `metric_type=total_value`, you can also specify one or more breakdowns, and the results will be broken down into smaller sets based on the specified breakdown. Values can be:

* `contact_button_type` — Break down results by profile UI component that viewers tapped or clicked. Response values can be:
    * `BOOK_NOW`
    * `CALL`
    * `DIRECTION`
    * `EMAIL`
    * `INSTANT_EXPERIENCE`
    * `TEXT`
    * `UNDEFINED`
* `follow_type` — Break down results by followers or non-followers. Response values can be:
    * `FOLLOWER`
    * `NON_FOLLOWER`
    * `UNKNOWN`
* `media_product_type` — Break down results by the surface where viewers viewed or interacted with the app user's media. Response values can be:
    * `AD`
    * `STORY`
    * `REEL` (same as `REELS`)
    * `CAROUSEL_CONTAINER` and `POST` as subtypes of `FEED`

Refer to the [Metrics](#metrics) table to determine which metrics are compatible with a breakdown. If you request a metric that doesn't support a breakdown, the API will return an error (`"An unknown error has occurred."`), so be careful if requesting multiple metrics in a single query.

If you request `metric_type=time_series`, breakdowns will not be included in the response.

### Metric Type

You can designate how you want results aggregated, either by time period or as a simple total (with breakdowns, if requested). Values can be:

* `time_series` — Tells the API to aggregate results by time period. See [Period](#period).
* `total_value` — Tells the API to return results as a simple total. If breakdowns are included in the request, the result set will be further broken down by the specific breakdowns. See [Breakdown](#breakdown).

### Period

Tells the API which time frame to use when aggregating results. Only compatible with interaction-related metrics.

### Timeframe

Tells the API how far to look back for data when requesting demographic-related metrics. This value overrides the `since` and `until` parameters.

### Range

Assign UNIX timestamps to the `since` and `until` parameters to define a range. The API will only include data created within this range (inclusive). If you do not include these parameters, the API will look back 24 hours.

For demographics-related metrics, the `timeframe` parameter overrides these values. See [Timeframe](#timeframe).

### Metrics

#### Interaction Metrics

| Metric | Period | Timeframe | Breakdown | Metric Type | Description |
| --- | --- | --- | --- | --- | --- |
| `accounts_engaged` | `day` | n/a | n/a | `total_value` | The number of accounts that have interacted with your content, including in ads. Content includes posts, stories, reels, videos and live videos. Interactions can include actions such as likes, saves, comments, shares or replies.<br><br>This metric is estimated. |
| `comments` | `day` | n/a | `media_product_type` | `total_value` | The number of comments on your posts, reels, videos and live videos.<br><br>This metric is [in development](https://business.facebook.com/business/help/metrics-labeling). |
| `engaged_audience_demographics` | `lifetime` | One of:<br><br>`last_14_days`,<br>`last_30_days`,<br>`last_90_days`,<br>`prev_month`,<br>`this_month`,<br>`this_week` | `age`,  <br>`city`,  <br>`country`,  <br>`gender` | `total_value` | The demographic characteristics of the engaged audience, including countries, cities and gender distribution. `this_month` returns the data in the last 30 days and `this_week` returns data in the last 7 days.<br><br>Does not support `since` or `until`. See [Range](#range) for more information.<br><br>Not returned if the IG User has less than 100 engagements during the timeframe.  <br><br>**Note:** The `last_14_days`, `last_30_days`, `last_90_days` and `prev_month` timeframes will no longer be supported beginning with v20.0. See the [changelog](https://developers.facebook.com/documentation/instagram-platform/changelog#may-21--2024) for more information. |
| `follows_and_unfollows` | `day` | n/a | `follow_type` | `total_value` | The number of accounts that followed you and the number of accounts that unfollowed you or left Instagram in the selected time period.<br><br>Not returned if the IG User has less than 100 followers. |
| `follower_demographics` | `lifetime` | One of:<br><br>`last_14_days`,<br>`last_30_days`,<br>`last_90_days`,<br>`prev_month`,<br>`this_month`,<br>`this_week` | `age`,  <br>`city`,  <br>`country`,  <br>`gender` | `total_value` | The demographic characteristics of followers, including countries, cities and gender distribution.<br><br>Does not support `since` or `until`. See [Range](#range) for more information.<br><br>Not returned if the IG User has less than 100 followers. |
| `impressions` **Deprecated for v22.0+ and all versions April 21, 2025.** | `day` | n/a | n/a | `total_value`,<br>`time_series` | The number of times your posts, stories, reels, videos and live videos were on screen, including in ads. |
| `likes` | `day` | n/a | `media_product_type` | `total_value` | The number of likes on your posts, reels, and videos. |
| `profile_links_taps` | `day` | n/a | `contact_button_type` | `total_value` | The number of taps on your business address, call button, email button and text button. |
| `reach` | `day` | n/a | `media_product_type`,<br>`follow_type` | `total_value`,<br>`time_series` | The number of unique accounts that have seen your content, at least once, including in ads. Content includes posts, stories, reels, videos and live videos. Reach is different from impressions, which may include multiple views of your content by the same accounts.<br><br>This metric is estimated. |
| `replies` | `day` | n/a | n/a | `total_value` | The number of replies you received from your story, including text replies and quick reaction replies. |
| `reposts` | `day` | n/a | n/a | `total_value` | The number of reposts of your posts, stories, reels, and videos. |
| `saves` | `day` | n/a | `media_product_type` | `total_value` | The number of saves of your posts, reels, and videos. |
| `shares` | `day` | n/a | `media_product_type` | `total_value` | The number of shares of your posts, stories, reels, videos and live videos. |
| `total_interactions` | `day` | n/a | `media_product_type` | `total_value` | The total number of post interactions, story interactions, reels interactions, video interactions and live video interactions, including any interactions on boosted content. |
| `views` | `day` | n/a | `follower_type`, `media_product_type` | `total_value` | The number of times your content was played or displayed. Content includes reels, posts, stories.<br><br>This metric is [in development](https://business.facebook.com/business/help/metrics-labeling). |

### Response

A JSON object containing the results of your query. Results can include the following data, based on your query specifications:

```json
{
  "data": [
    {
      "name": "{data}",
      "period": "<PERIOD>",
      "title": "{title}",
      "description": "{description}",
      "total_value": {
        "value": {value},
        "breakdowns": [
          {
            "dimension_keys": [
              "{key-1}",
              "{key-2",
              ...
            ],
            "results": [
              {
                "dimension_values": [
                  "{value-1}",
                  "{value-2}",
                  ...
                ],
                "value": {value},
                "end_time": "{end-time}"
              },
              ...
            ]
          }
        ]
      },
      "id": "{id}"
    }
  ],
  "paging": {
    "previous": "{previous}",
    "next": "{next}"
  }
}
```

### Response Contents

| Property | Value Type | Description |
| --- | --- | --- |
| `breakdowns` | Array | An array of objects describing the [breakdowns](#breakdown) requested and their results.<br><br>Only returned if `metric_type=total_values` is requested. |
| `data` | Array | An array of objects describing your results. |
| `description` | String | [Metric](#metrics) description. |
| `dimension_keys` | Array | An array of strings describing [breakdowns](#breakdown) requested in the query. Can be used as keys corresponding to values in individual breakdown sets.<br><br>Only returned if `metric_type=total_values` is requested. |
| `dimension_values` | Array | An array of strings describing [breakdown](#breakdown) set values. Values can be mapped to `dimension_keys`.<br><br>Only returned if `metric_type=total_values` is requested. |
| `end_time` | String | ISO 8601 timestamp with time and offset. For example: `2022-08-01T07:00:00+0000` |
| `id` | String | A string describing the query's path parameters. |
| `name` | String | [Metric](#metrics) requested. |
| `next` | String | URL to retrieve the next page of results. See [Paginated Results](https://developers.facebook.com/docs/graph-api/results) for more information. |
| `paging` | Object | An object containing URLs used to request the next set of results. See [Paginated Results](https://developers.facebook.com/docs/graph-api/results) for more information. |
| `period` | String | [Period](#period) requested. |
| `previous` | String | URL to retrieve the previous page of results. See [Paginated Results](https://developers.facebook.com/docs/graph-api/results) for more information. |
| `results` | Array | An array of objects describing each [breakdown](#breakdown) set.<br><br>Only returned if `metric_type=total_values` is requested. |
| `title` | String | [Metric](#metrics) title. |
| `total_value` | Object | Object describing requested [breakdown](#breakdown) values (if breakdowns were requested). |
| `value` | Integer | For `data.total_value.value`, sum of requested [metric](#metrics) values.<br><br>For `data.total_value.breakdowns.results.value`, sum of [breakdown](#breakdown) set values. Only returned if `metric_type=total_values` is requested. |

## Examples

### Interaction Metrics

```curl
curl -i -X GET \
  "https://graph.facebook.com/v25.0/17841405822304914/insights?metric=reach&period=day&breakdown=media_product_type&metric_type=total_value&since=1658991600&access_token=EAAOc..."
```

#### Response

```json
{
  "data": [
    {
      "name": "reach",
      "period": "day",
      "title": "Accounts reached",
      "description": "The number of unique accounts that have seen your content, at least once, including in ads. Content includes posts, stories, reels, videos and live videos. Reach is different from impressions, which may include multiple views of your content by the same accounts. This metric is estimated and in development.",
      "total_value": {
        "value": 224,
        "breakdowns": [
          {
            "dimension_keys": [
              "media_product_type"
            ],
            "results": [
              {
                "dimension_values": [
                  "CAROUSEL_CONTAINER"
                ],
                "value": 100
              },
              {
                "dimension_values": [
                  "POST"
                ],
                "value": 124
              }
            ]
          }
        ]
      },
      "id": "17841405309211844/insights/reach/day"
    }
  ],
  "paging": {
    "previous": "https://graph.face...",
    "next": "https://graph.face..."
  }
```

### Demographic Metrics

```curl
curl -i -X GET \
  "https://graph.facebook.com/v25.0/17841405822304914/insights?metric=engaged_audience_demographics&period=lifetime&timeframe=last_90_days&breakdowns=country&metric_type=total_value&access_token=EAAOc..."
```

#### Response

```json
{
  "data": [
    {
      "name": "engaged_audience_demographics",
      "period": "lifetime",
      "title": "Engaged audience demographics",
      "description": "The demographic characteristics of the engaged audience, including countries, cities and gender distribution.",
      "total_value": {
        "breakdowns": [
          {
            "dimension_keys": [
              "timeframe",
              "country"
            ],
            "results": [
              {
                "dimension_values": [
                  "LAST_90_DAYS",
                  "AR"
                ],
                "value": 1
              },
              {
                "dimension_values": [
                  "LAST_90_DAYS",
                  "RU"
                ],
                "value": 1
              },
              {
                "dimension_values": [
                  "LAST_90_DAYS",
                  "MA"
                ],
                "value": 1
              },
              {
                "dimension_values": [
                  "LAST_90_DAYS",
                  "LA"
                ],
                "value": 1
              },
              {
                "dimension_values": [
                  "LAST_90_DAYS",
                  "IQ"
                ],
                "value": 2
              },
              {
                "dimension_values": [
                  "LAST_90_DAYS",
                  "MX"
                ],
                "value": 1
              },
              {
                "dimension_values": [
                  "LAST_90_DAYS",
                  "FR"
                ],
                "value": 1
              },
              {
                "dimension_values": [
                  "LAST_90_DAYS",
                  "ES"
                ],
                "value": 3
              },
              {
                "dimension_values": [
                  "LAST_90_DAYS",
                  "NL"
                ],
                "value": 1
              },
              {
                "dimension_values": [
                  "LAST_90_DAYS",
                  "TR"
                ],
                "value": 1
              },
              {
                "dimension_values": [
                  "LAST_90_DAYS",
                  "US"
                ],
                "value": 7
              }
            ]
          }
        ]
      },
      "id": "17841401130346306/insights/engaged_audience_demographics/lifetime"
    }
  ]
}
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

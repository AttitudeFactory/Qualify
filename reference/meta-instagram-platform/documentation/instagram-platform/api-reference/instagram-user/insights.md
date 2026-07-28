# Instagram Account Insights



Represents social interaction metrics on your app user&#039;s Instagram business or creator account.

In this guide, we use **Instagram user** and **Instagram account** interchangeably.

**Success:** Available for the Instagram API with Facebook Login and Instagram API with Instagram Login.

**Warning:** The following metrics have been deprecated for v22.0 and will be deprecated for all versions on April 21, 2025:

* `impressions`

Introducing the new `views` metric with `total_value` metric type and with breakdowns for `follower_type` and `media_product_type`.

Visit the [Instagram Platform Changelog](https://developers.facebook.com/documentation/instagram-platform/changelog) for more information.

## Creating

This operation is not supported.

## Reading

**`GET /&lt;YOUR_APP_USERS_INSTAGRAM_ACCOUNT_ID&gt;/insights`**

Returns insights on your app user&#039;s Instagram business or creator account.

### Requirements

|  | Instagram API with Instagram Login | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User access token | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_insights` | * `instagram_basic`&lt;br&gt;* `instagram_manage_insights`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;&lt;br&gt;If the app user was granted a role on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to your app user&#039;s Instagram professional account via the Business Manager, your app will also need:&lt;br&gt;&lt;br&gt;* `ads_management`&lt;br&gt;* `ads_read` |

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
GET https://&lt;HOST_URL&gt;/&lt;API_VERSION&gt;/&lt;APP_USERS_INSTAGRAM_ACCOUNT_ID&gt;/insights
  ?metric=&lt;COMMA_SEPARATED_LIST_OF_METRICS&gt;
  &amp;period=&lt;PERIOD&gt;
  &amp;timeframe=&lt;TIMEFRAME&gt;
  &amp;metric_type=&lt;METRIC_TYPE&gt;
  &amp;breakdown=&lt;BREAKDOWN_METRIC&gt;
  &amp;since=&lt;START_TIME&gt;
  &amp;until=&lt;STOP_TIME&gt;
  &amp;access_token=&lt;INSTAGRAM_USER_ACCESS_TOKEN&gt;
```

### Host Path Parameters

```html
GET https://&lt;HOST_URL&gt;/&lt;API_VERSION&gt;/&lt;APP_USERS_INSTAGRAM_ACCOUNT_ID&gt;/insights
```

| Placeholder | Value |
| --- | --- |
| `&lt;API_VERSION&gt;`&lt;br&gt;The latest version is: v25.0&lt;br&gt; | The API version your app is using when making calls to Meta servers.&lt;br&gt;[Learn more about API versioning.](https://developers.facebook.com/docs/graph-api/guides/versioning)&lt;br&gt; |
| `&lt;APP_USERS_INSTAGRAM_ACCOUNT_ID&gt;` | **Required.** The ID of your app user&#039;s Instagram professional account. |
| `&lt;HOST_URL&gt;` | **Required.** The ID of your app user&#039;s Instagram professional account. |

### Parameters

| Key | Value |
| --- | --- |
| `access_token` | **Required.** The app user&#039;s Facebook User or Instagram access token. |
| `breakdown` | Designates how to break down result set into subsets.&lt;br&gt;&lt;br&gt;*  `contact_button_type` – Divides results by profile component in the native app.&lt;br&gt;*  `follow_type` – Breaks down results by followers or non-followers.&lt;br&gt;* `media_product_type` – Breaks down results by surface where Instagram users view or interact with your app user&#039;s media. |
| `metric` | **Required.** Comma-separated list of [Metrics](#metrics) you want returned.&lt;br&gt;&lt;br&gt;`&lt;COMMA_SEPARATED_LIST_OF_METRICS&gt;` |
| `metric_type` | Designates if you want the responses aggregated by time period or as a simple total. See [Metric Type](#metric-type). `&lt;METRIC_TYPE&gt;` |
| `period` | **Required.** [Period](#period) aggregation. `&lt;PERIOD&gt;` |
| `since` | Unix timestamp indicating start of range. See [Range](#range).&lt;br&gt;`&lt;START_TIME&gt;` |
| `timeframe` | **Required for demographics-related metrics.** Designates how far to look back for data. See [Timeframe](#timeframe). `&lt;TIMEFRAME&gt;` |
| `until` | Unix timestamp indicating end of range. See [Range](#range).  `&lt;STOP_TIME&gt;` |

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
* `media_product_type` — Break down results by the surface where viewers viewed or interacted with the app user&#039;s media. Response values can be:
    * `AD`
    * `STORY`
    * `REEL` (same as `REELS`)
    * `CAROUSEL_CONTAINER` and `POST` as subtypes of `FEED`

Refer to the [Metrics](#metrics) table to determine which metrics are compatible with a breakdown. If you request a metric that doesn&#039;t support a breakdown, the API will return an error (`&quot;An unknown error has occurred.&quot;`), so be careful if requesting multiple metrics in a single query.

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
| `accounts_engaged` | `day` | n/a | n/a | `total_value` | The number of accounts that have interacted with your content, including in ads. Content includes posts, stories, reels, videos and live videos. Interactions can include actions such as likes, saves, comments, shares or replies.&lt;br&gt;&lt;br&gt;This metric is estimated. |
| `comments` | `day` | n/a | `media_product_type` | `total_value` | The number of comments on your posts, reels, videos and live videos.&lt;br&gt;&lt;br&gt;This metric is [in development](https://business.facebook.com/business/help/metrics-labeling). |
| `engaged_audience_demographics` | `lifetime` | One of:&lt;br&gt;&lt;br&gt;`last_14_days`,&lt;br&gt;`last_30_days`,&lt;br&gt;`last_90_days`,&lt;br&gt;`prev_month`,&lt;br&gt;`this_month`,&lt;br&gt;`this_week` | `age`,  &lt;br&gt;`city`,  &lt;br&gt;`country`,  &lt;br&gt;`gender` | `total_value` | The demographic characteristics of the engaged audience, including countries, cities and gender distribution. `this_month` returns the data in the last 30 days and `this_week` returns data in the last 7 days.&lt;br&gt;&lt;br&gt;Does not support `since` or `until`. See [Range](#range) for more information.&lt;br&gt;&lt;br&gt;Not returned if the IG User has less than 100 engagements during the timeframe.  &lt;br&gt;&lt;br&gt;**Note:** The `last_14_days`, `last_30_days`, `last_90_days` and `prev_month` timeframes will no longer be supported beginning with v20.0. See the [changelog](https://developers.facebook.com/documentation/instagram-platform/changelog#may-21--2024) for more information. |
| `follows_and_unfollows` | `day` | n/a | `follow_type` | `total_value` | The number of accounts that followed you and the number of accounts that unfollowed you or left Instagram in the selected time period.&lt;br&gt;&lt;br&gt;Not returned if the IG User has less than 100 followers. |
| `follower_demographics` | `lifetime` | One of:&lt;br&gt;&lt;br&gt;`last_14_days`,&lt;br&gt;`last_30_days`,&lt;br&gt;`last_90_days`,&lt;br&gt;`prev_month`,&lt;br&gt;`this_month`,&lt;br&gt;`this_week` | `age`,  &lt;br&gt;`city`,  &lt;br&gt;`country`,  &lt;br&gt;`gender` | `total_value` | The demographic characteristics of followers, including countries, cities and gender distribution.&lt;br&gt;&lt;br&gt;Does not support `since` or `until`. See [Range](#range) for more information.&lt;br&gt;&lt;br&gt;Not returned if the IG User has less than 100 followers. |
| `impressions` **Deprecated for v22.0+ and all versions April 21, 2025.** | `day` | n/a | n/a | `total_value`,&lt;br&gt;`time_series` | The number of times your posts, stories, reels, videos and live videos were on screen, including in ads. |
| `likes` | `day` | n/a | `media_product_type` | `total_value` | The number of likes on your posts, reels, and videos. |
| `profile_links_taps` | `day` | n/a | `contact_button_type` | `total_value` | The number of taps on your business address, call button, email button and text button. |
| `reach` | `day` | n/a | `media_product_type`,&lt;br&gt;`follow_type` | `total_value`,&lt;br&gt;`time_series` | The number of unique accounts that have seen your content, at least once, including in ads. Content includes posts, stories, reels, videos and live videos. Reach is different from impressions, which may include multiple views of your content by the same accounts.&lt;br&gt;&lt;br&gt;This metric is estimated. |
| `replies` | `day` | n/a | n/a | `total_value` | The number of replies you received from your story, including text replies and quick reaction replies. |
| `reposts` | `day` | n/a | n/a | `total_value` | The number of reposts of your posts, stories, reels, and videos. |
| `saves` | `day` | n/a | `media_product_type` | `total_value` | The number of saves of your posts, reels, and videos. |
| `shares` | `day` | n/a | `media_product_type` | `total_value` | The number of shares of your posts, stories, reels, videos and live videos. |
| `total_interactions` | `day` | n/a | `media_product_type` | `total_value` | The total number of post interactions, story interactions, reels interactions, video interactions and live video interactions, including any interactions on boosted content. |
| `views` | `day` | n/a | `follower_type`, `media_product_type` | `total_value` | The number of times your content was played or displayed. Content includes reels, posts, stories.&lt;br&gt;&lt;br&gt;This metric is [in development](https://business.facebook.com/business/help/metrics-labeling). |

### Response

A JSON object containing the results of your query. Results can include the following data, based on your query specifications:

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;name&quot;: &quot;&#123;data&#125;&quot;,
      &quot;period&quot;: &quot;&lt;PERIOD&gt;&quot;,
      &quot;title&quot;: &quot;&#123;title&#125;&quot;,
      &quot;description&quot;: &quot;&#123;description&#125;&quot;,
      &quot;total_value&quot;: &#123;
        &quot;value&quot;: &#123;value&#125;,
        &quot;breakdowns&quot;: [
          &#123;
            &quot;dimension_keys&quot;: [
              &quot;&#123;key-1&#125;&quot;,
              &quot;&#123;key-2&quot;,
              ...
            ],
            &quot;results&quot;: [
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;&#123;value-1&#125;&quot;,
                  &quot;&#123;value-2&#125;&quot;,
                  ...
                ],
                &quot;value&quot;: &#123;value&#125;,
                &quot;end_time&quot;: &quot;&#123;end-time&#125;&quot;
              &#125;,
              ...
            ]
          &#125;
        ]
      &#125;,
      &quot;id&quot;: &quot;&#123;id&#125;&quot;
    &#125;
  ],
  &quot;paging&quot;: &#123;
    &quot;previous&quot;: &quot;&#123;previous&#125;&quot;,
    &quot;next&quot;: &quot;&#123;next&#125;&quot;
  &#125;
&#125;
```

### Response Contents

| Property | Value Type | Description |
| --- | --- | --- |
| `breakdowns` | Array | An array of objects describing the [breakdowns](#breakdown) requested and their results.&lt;br&gt;&lt;br&gt;Only returned if `metric_type=total_values` is requested. |
| `data` | Array | An array of objects describing your results. |
| `description` | String | [Metric](#metrics) description. |
| `dimension_keys` | Array | An array of strings describing [breakdowns](#breakdown) requested in the query. Can be used as keys corresponding to values in individual breakdown sets.&lt;br&gt;&lt;br&gt;Only returned if `metric_type=total_values` is requested. |
| `dimension_values` | Array | An array of strings describing [breakdown](#breakdown) set values. Values can be mapped to `dimension_keys`.&lt;br&gt;&lt;br&gt;Only returned if `metric_type=total_values` is requested. |
| `end_time` | String | ISO 8601 timestamp with time and offset. For example: `2022-08-01T07:00:00+0000` |
| `id` | String | A string describing the query&#039;s path parameters. |
| `name` | String | [Metric](#metrics) requested. |
| `next` | String | URL to retrieve the next page of results. See [Paginated Results](https://developers.facebook.com/docs/graph-api/results) for more information. |
| `paging` | Object | An object containing URLs used to request the next set of results. See [Paginated Results](https://developers.facebook.com/docs/graph-api/results) for more information. |
| `period` | String | [Period](#period) requested. |
| `previous` | String | URL to retrieve the previous page of results. See [Paginated Results](https://developers.facebook.com/docs/graph-api/results) for more information. |
| `results` | Array | An array of objects describing each [breakdown](#breakdown) set.&lt;br&gt;&lt;br&gt;Only returned if `metric_type=total_values` is requested. |
| `title` | String | [Metric](#metrics) title. |
| `total_value` | Object | Object describing requested [breakdown](#breakdown) values (if breakdowns were requested). |
| `value` | Integer | For `data.total_value.value`, sum of requested [metric](#metrics) values.&lt;br&gt;&lt;br&gt;For `data.total_value.breakdowns.results.value`, sum of [breakdown](#breakdown) set values. Only returned if `metric_type=total_values` is requested. |

## Examples

### Interaction Metrics

```curl
curl -i -X GET \
  &quot;https://graph.facebook.com/v25.0/17841405822304914/insights?metric=reach&amp;period=day&amp;breakdown=media_product_type&amp;metric_type=total_value&amp;since=1658991600&amp;access_token=EAAOc...&quot;
```

#### Response

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;name&quot;: &quot;reach&quot;,
      &quot;period&quot;: &quot;day&quot;,
      &quot;title&quot;: &quot;Accounts reached&quot;,
      &quot;description&quot;: &quot;The number of unique accounts that have seen your content, at least once, including in ads. Content includes posts, stories, reels, videos and live videos. Reach is different from impressions, which may include multiple views of your content by the same accounts. This metric is estimated and in development.&quot;,
      &quot;total_value&quot;: &#123;
        &quot;value&quot;: 224,
        &quot;breakdowns&quot;: [
          &#123;
            &quot;dimension_keys&quot;: [
              &quot;media_product_type&quot;
            ],
            &quot;results&quot;: [
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;CAROUSEL_CONTAINER&quot;
                ],
                &quot;value&quot;: 100
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;POST&quot;
                ],
                &quot;value&quot;: 124
              &#125;
            ]
          &#125;
        ]
      &#125;,
      &quot;id&quot;: &quot;17841405309211844/insights/reach/day&quot;
    &#125;
  ],
  &quot;paging&quot;: &#123;
    &quot;previous&quot;: &quot;https://graph.face...&quot;,
    &quot;next&quot;: &quot;https://graph.face...&quot;
  &#125;
```

### Demographic Metrics

```curl
curl -i -X GET \
  &quot;https://graph.facebook.com/v25.0/17841405822304914/insights?metric=engaged_audience_demographics&amp;period=lifetime&amp;timeframe=last_90_days&amp;breakdowns=country&amp;metric_type=total_value&amp;access_token=EAAOc...&quot;
```

#### Response

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;name&quot;: &quot;engaged_audience_demographics&quot;,
      &quot;period&quot;: &quot;lifetime&quot;,
      &quot;title&quot;: &quot;Engaged audience demographics&quot;,
      &quot;description&quot;: &quot;The demographic characteristics of the engaged audience, including countries, cities and gender distribution.&quot;,
      &quot;total_value&quot;: &#123;
        &quot;breakdowns&quot;: [
          &#123;
            &quot;dimension_keys&quot;: [
              &quot;timeframe&quot;,
              &quot;country&quot;
            ],
            &quot;results&quot;: [
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;LAST_90_DAYS&quot;,
                  &quot;AR&quot;
                ],
                &quot;value&quot;: 1
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;LAST_90_DAYS&quot;,
                  &quot;RU&quot;
                ],
                &quot;value&quot;: 1
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;LAST_90_DAYS&quot;,
                  &quot;MA&quot;
                ],
                &quot;value&quot;: 1
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;LAST_90_DAYS&quot;,
                  &quot;LA&quot;
                ],
                &quot;value&quot;: 1
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;LAST_90_DAYS&quot;,
                  &quot;IQ&quot;
                ],
                &quot;value&quot;: 2
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;LAST_90_DAYS&quot;,
                  &quot;MX&quot;
                ],
                &quot;value&quot;: 1
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;LAST_90_DAYS&quot;,
                  &quot;FR&quot;
                ],
                &quot;value&quot;: 1
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;LAST_90_DAYS&quot;,
                  &quot;ES&quot;
                ],
                &quot;value&quot;: 3
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;LAST_90_DAYS&quot;,
                  &quot;NL&quot;
                ],
                &quot;value&quot;: 1
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;LAST_90_DAYS&quot;,
                  &quot;TR&quot;
                ],
                &quot;value&quot;: 1
              &#125;,
              &#123;
                &quot;dimension_values&quot;: [
                  &quot;LAST_90_DAYS&quot;,
                  &quot;US&quot;
                ],
                &quot;value&quot;: 7
              &#125;
            ]
          &#125;
        ]
      &#125;,
      &quot;id&quot;: &quot;17841401130346306/insights/engaged_audience_demographics/lifetime&quot;
    &#125;
  ]
&#125;
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

# Insights



This guide shows you how to get insights for your app users&#039; Instagram media and professional accounts using the Instagram Platform.

In this guide we will be using **Instagram user** and **Instagram professional account** interchangeably. An  Instagram User object represents your app user&#039;s Instagram professional account.

**Success:** Instagram Insights are now available for Instagram API with Instagram Login. [Learn more.](https://developers.facebook.com/documentation/instagram-platform/insights)

## Before you start

You will need the following:

### Requirements

This guide assumes you have read the [Instagram Platform Overview](https://developers.facebook.com/documentation/instagram-platform/overview) and implemented the needed components for using this API, such as a Meta login flow and a webhooks server to receive notifications.

|  | Instagram API with Instagram Login | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User access token | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_insights` | * `instagram_basic`&lt;br&gt;* `instagram_manage_insights`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;&lt;br&gt;If the app user was granted a role on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to your app user&#039;s Instagram professional account via the Business Manager, your app will also need:&lt;br&gt;&lt;br&gt;* `ads_management`&lt;br&gt;* `ads_read` |

#### Access Level

* Advanced Access if your app serves Instagram professional accounts you don&#039;t own or manage
* Standard Access if your app serves Instagram professional accounts you own or manage and have added to your app in the App Dashboard

#### Endpoints

* [`GET /&lt;INSTAGRAM_MEDIA_ID&gt;/insights`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights) — Gets metrics on a media object
* [`GET /&lt;INSTAGRAM_ACCOUNT_ID&gt;/insights`](https://developers.facebook.com/documentation/instagram-platform/api-reference/instagram-user/insights) — Gets metrics on an Instagram Business Account or Instagram Creator account.

Refer to each endpoint&#039;s reference documentation for additional metrics, parameters, and permission requirements.

#### UTC

Timestamps in API responses use UTC with zero offset and are formatted using ISO-8601. For example: `2019-04-05T07:56:32+0000`

#### Webhook event subscriptions

- [`story_insights ` – **Only available for Instagram API with Facebook Login.**](https://developers.facebook.com/documentation/instagram-platform/webhooks)

### Limitations

#### Media insights

- Metrics such as `comments`, `likes`, and `views` return engagement on the target Instagram media only and don&#039;t include data from other surfaces. For example, `comments` returns the number of comments on a photo, but not comments on ads that contain that photo. Use `total_comments`, `total_likes`, and `total_views` on the Insights endpoint to get aggregated counts that include engagement from promoted/boosted/ad media. These total metrics are only available for Instagram API with Facebook Login.
- Live video Instagram Media can only be read while they are being broadcast.
- This API returns only data for media owned by Instagram professional accounts. It cannot be used to get data for media owned by personal Instagram accounts.  

#### Account insights

- Some metrics are not available on Instagram accounts with fewer than 100 followers.
- User Metrics data is stored for up to 90 days.
- You can only get insights for a single user at a time.
- You cannot get insights for Facebook Pages.
- If insights data you are requesting does not exist or is currently unavailable the API will return an empty data set instead of `0` for individual metrics.

## Examples

### Instagram account request

The following Instagram API with Facebook Login example is getting the number of `impressions`, `profile_views`, and `reach` for your app user&#039;s Instagram professional account over one 24 hour period.

To get metrics for an Instagram business or creator account, query the [`GET /&lt;INSTAGRAM_USER_ID&gt;/insights`](https://developers.facebook.com/documentation/instagram-platform/api-reference/instagram-user/insights) endpoint with the `metrics` parameter set to a comma-separated list of the metrics, `impressions`, `profile_views`, and `reach`, and the `period` set to `day`.

```
GET graph.facebook.com/17841405822304914/insights
    ?metric=impressions,reach,profile_views
    &amp;period=day
```

#### Sample Response

On success, your app receives an array for each metric that includes, the metric description, ID of the metric, name and title, the time period over which the metric was measured, and values of the metric.

```
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;name&quot;: &quot;impressions&quot;,
      &quot;period&quot;: &quot;day&quot;,
      &quot;values&quot;: [
        &#123;
          &quot;value&quot;: 32,
          &quot;end_time&quot;: &quot;2018-01-11T08:00:00+0000&quot;
        &#125;,
        &#123;
          &quot;value&quot;: 32,
          &quot;end_time&quot;: &quot;2018-01-12T08:00:00+0000&quot;
        &#125;
      ],
      &quot;title&quot;: &quot;Impressions&quot;,
      &quot;description&quot;: &quot;Total number of times the Business Account&#039;s media objects have been viewed&quot;,
      &quot;id&quot;: &quot;instagram_business_account_id/insights/impressions/day&quot;
    &#125;,
    &#123;
      &quot;name&quot;: &quot;reach&quot;,
      &quot;period&quot;: &quot;day&quot;,
      &quot;values&quot;: [
        &#123;
          &quot;value&quot;: 12,
          &quot;end_time&quot;: &quot;2018-01-11T08:00:00+0000&quot;
        &#125;,
        &#123;
          &quot;value&quot;: 12,
          &quot;end_time&quot;: &quot;2018-01-12T08:00:00+0000&quot;
        &#125;
      ],
      &quot;title&quot;: &quot;Reach&quot;,
      &quot;description&quot;: &quot;Total number of times the Business Account&#039;s media objects have been uniquely viewed&quot;,
      &quot;id&quot;: &quot;instagram_business_account_id/insights/reach/day&quot;
    &#125;,
    &#123;
      &quot;name&quot;: &quot;profile_views&quot;,
      &quot;period&quot;: &quot;day&quot;,
      &quot;values&quot;: [
        &#123;
          &quot;value&quot;: 15,
          &quot;end_time&quot;: &quot;2018-01-11T08:00:00+0000&quot;
        &#125;,
        &#123;
          &quot;value&quot;: 15,
          &quot;end_time&quot;: &quot;2018-01-12T08:00:00+0000&quot;
        &#125;
      ],
      &quot;title&quot;: &quot;Profile Views&quot;,
      &quot;description&quot;: &quot;Total number of users who have viewed the Business Account&#039;s profile within the specified period&quot;,
      &quot;id&quot;: &quot;instagram_business_account_id/insights/profile_views/day&quot;
    &#125;
  ]
&#125;
```

### Instagram media request

The following Instagram API with Instagram Login example is getting the number of  `engagement`, `impressions`, and `reach` for your app user&#039;s Instagram media over one 24 hour period.

To get metrics for an Instagram business or creator account&#039;s media, query the [`GET /&lt;INSTAGRAM_MEDIA_ID&gt;/insights`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights) endpoint with the `metrics` parameter set to a comma-separated list of the metrics, `engagement`, `impressions`, and `reach`, and the `period` set to `day`.

```
GET graph.instagram.com/17841491440582230/insights
    ?metric=engagement,impressions,reach
```

#### Sample Response

On success, your app receives an array for each metric that includes, the metric description, ID of the metric, name and title, the time period over which the metric was measured, and values of the metric.

```
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;name&quot;: &quot;engagement&quot;,
      &quot;period&quot;: &quot;lifetime&quot;,
      &quot;values&quot;: [
        &#123;
          &quot;value&quot;: 8
        &#125;
      ],
      &quot;title&quot;: &quot;Engagement&quot;,
      &quot;description&quot;: &quot;Total number of likes and comments on the media object&quot;,
      &quot;id&quot;: &quot;media_id/insights/engagement/lifetime&quot;
    &#125;,
    &#123;
      &quot;name&quot;: &quot;impressions&quot;,
      &quot;period&quot;: &quot;lifetime&quot;,
      &quot;values&quot;: [
        &#123;
          &quot;value&quot;: 13
        &#125;
      ],
      &quot;title&quot;: &quot;Impressions&quot;,
      &quot;description&quot;: &quot;Total number of times the media object has been seen&quot;,
      &quot;id&quot;: &quot;media_id/insights/impressions/lifetime&quot;
    &#125;,
    &#123;
      &quot;name&quot;: &quot;reach&quot;,
      &quot;period&quot;: &quot;lifetime&quot;,
      &quot;values&quot;: [
        &#123;
          &quot;value&quot;: 13
        &#125;
      ],
      &quot;title&quot;: &quot;Reach&quot;,
      &quot;description&quot;: &quot;Total number of unique accounts that have seen the media object&quot;,
      &quot;id&quot;: &quot;media_id/insights/reach/lifetime&quot;
    &#125;
  ]
&#125;
```

## Next Steps

Visit the API Reference to see all available metrics for [Instagram business and creator accounts](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) and their [Instagram Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects.

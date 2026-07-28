# Insights



This guide shows you how to get insights for your app users' Instagram media and professional accounts using the Instagram Platform.

In this guide we will be using **Instagram user** and **Instagram professional account** interchangeably. An  Instagram User object represents your app user's Instagram professional account.

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
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`<br>* `instagram_business_manage_insights` | * `instagram_basic`<br>* `instagram_manage_insights`<br>* `pages_read_engagement`<br><br>If the app user was granted a role on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to your app user's Instagram professional account via the Business Manager, your app will also need:<br><br>* `ads_management`<br>* `ads_read` |

#### Access Level

* Advanced Access if your app serves Instagram professional accounts you don't own or manage
* Standard Access if your app serves Instagram professional accounts you own or manage and have added to your app in the App Dashboard

#### Endpoints

* [`GET /<INSTAGRAM_MEDIA_ID>/insights`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights) — Gets metrics on a media object
* [`GET /<INSTAGRAM_ACCOUNT_ID>/insights`](https://developers.facebook.com/documentation/instagram-platform/api-reference/instagram-user/insights) — Gets metrics on an Instagram Business Account or Instagram Creator account.

Refer to each endpoint's reference documentation for additional metrics, parameters, and permission requirements.

#### UTC

Timestamps in API responses use UTC with zero offset and are formatted using ISO-8601. For example: `2019-04-05T07:56:32+0000`

#### Webhook event subscriptions

- [`story_insights ` – **Only available for Instagram API with Facebook Login.**](https://developers.facebook.com/documentation/instagram-platform/webhooks)

### Limitations

#### Media insights

- Metrics such as `comments`, `likes`, and `views` return engagement on the target Instagram media only and don't include data from other surfaces. For example, `comments` returns the number of comments on a photo, but not comments on ads that contain that photo. Use `total_comments`, `total_likes`, and `total_views` on the Insights endpoint to get aggregated counts that include engagement from promoted/boosted/ad media. These total metrics are only available for Instagram API with Facebook Login.
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

The following Instagram API with Facebook Login example is getting the number of `impressions`, `profile_views`, and `reach` for your app user's Instagram professional account over one 24 hour period.

To get metrics for an Instagram business or creator account, query the [`GET /<INSTAGRAM_USER_ID>/insights`](https://developers.facebook.com/documentation/instagram-platform/api-reference/instagram-user/insights) endpoint with the `metrics` parameter set to a comma-separated list of the metrics, `impressions`, `profile_views`, and `reach`, and the `period` set to `day`.

```
GET graph.facebook.com/17841405822304914/insights
    ?metric=impressions,reach,profile_views
    &period=day
```

#### Sample Response

On success, your app receives an array for each metric that includes, the metric description, ID of the metric, name and title, the time period over which the metric was measured, and values of the metric.

```
{
  "data": [
    {
      "name": "impressions",
      "period": "day",
      "values": [
        {
          "value": 32,
          "end_time": "2018-01-11T08:00:00+0000"
        },
        {
          "value": 32,
          "end_time": "2018-01-12T08:00:00+0000"
        }
      ],
      "title": "Impressions",
      "description": "Total number of times the Business Account's media objects have been viewed",
      "id": "instagram_business_account_id/insights/impressions/day"
    },
    {
      "name": "reach",
      "period": "day",
      "values": [
        {
          "value": 12,
          "end_time": "2018-01-11T08:00:00+0000"
        },
        {
          "value": 12,
          "end_time": "2018-01-12T08:00:00+0000"
        }
      ],
      "title": "Reach",
      "description": "Total number of times the Business Account's media objects have been uniquely viewed",
      "id": "instagram_business_account_id/insights/reach/day"
    },
    {
      "name": "profile_views",
      "period": "day",
      "values": [
        {
          "value": 15,
          "end_time": "2018-01-11T08:00:00+0000"
        },
        {
          "value": 15,
          "end_time": "2018-01-12T08:00:00+0000"
        }
      ],
      "title": "Profile Views",
      "description": "Total number of users who have viewed the Business Account's profile within the specified period",
      "id": "instagram_business_account_id/insights/profile_views/day"
    }
  ]
}
```

### Instagram media request

The following Instagram API with Instagram Login example is getting the number of  `engagement`, `impressions`, and `reach` for your app user's Instagram media over one 24 hour period.

To get metrics for an Instagram business or creator account's media, query the [`GET /<INSTAGRAM_MEDIA_ID>/insights`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights) endpoint with the `metrics` parameter set to a comma-separated list of the metrics, `engagement`, `impressions`, and `reach`, and the `period` set to `day`.

```
GET graph.instagram.com/17841491440582230/insights
    ?metric=engagement,impressions,reach
```

#### Sample Response

On success, your app receives an array for each metric that includes, the metric description, ID of the metric, name and title, the time period over which the metric was measured, and values of the metric.

```
{
  "data": [
    {
      "name": "engagement",
      "period": "lifetime",
      "values": [
        {
          "value": 8
        }
      ],
      "title": "Engagement",
      "description": "Total number of likes and comments on the media object",
      "id": "media_id/insights/engagement/lifetime"
    },
    {
      "name": "impressions",
      "period": "lifetime",
      "values": [
        {
          "value": 13
        }
      ],
      "title": "Impressions",
      "description": "Total number of times the media object has been seen",
      "id": "media_id/insights/impressions/lifetime"
    },
    {
      "name": "reach",
      "period": "lifetime",
      "values": [
        {
          "value": 13
        }
      ],
      "title": "Reach",
      "description": "Total number of unique accounts that have seen the media object",
      "id": "media_id/insights/reach/lifetime"
    }
  ]
}
```

## Next Steps

Visit the API Reference to see all available metrics for [Instagram business and creator accounts](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) and their [Instagram Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects.

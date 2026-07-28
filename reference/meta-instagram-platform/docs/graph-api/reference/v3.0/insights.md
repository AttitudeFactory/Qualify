Graph API Version

[v25.0](#)

# Page Insights

Represents insights for Facebook Pages and Page posts. Refer to our [Pages API documentation](/docs/pages).

By June 15, 2026, a [number of the Page Insights metrics](https://developers.facebook.com/docs/platforminsights/page/deprecated-metrics) will be deprecated for all API versions. The API returns an invalid metric error when calling any of these metrics. [Read our blog to learn more.](https://developers.facebook.com/blog/post/2026/02/18/introducing-graph-api-v25-and-marketing-api-v25/)

## Reading

Get [metrics](#availmetrics) for Pages or Page posts.

### New Page Experience

This endpoint is supported for [New Page Experience](/docs/pages/new-pages-experience/).

### Limitations

* Page Insights data is only available on Pages with 100 or more likes.
* Most metrics will update once every 24 hours.
* Only the last two years of insights data is available.
* The values for `period` are calculated from the initial collection of the data point.
* "Period" in the tables below only refers to the time frame for which the metric can be accessed in an aggregated form.
* The value "lifetime" means the time period for which the insights data is available. By default, this time period is 2 years or shorter.
* Only 90 days of insights can be viewed at one time when using the `since` and `until` parameters.
* When using `since` and `until`, the `since` date data will be included in the first `value` returned.
* Unique impression insights values are calculated independently.
  + Total page reach may not always be exactly equal to the sum of paid and non-paid unique values.
  + Total page reach may not always be exactly equal to the sum of `viral_unique` and `organic_unique`.
* When an organic post is boosted, metrics for paid post impressions will include both organic and paid reach.
* Demographic metrics, such as age, gender, and location, are only returned if there is data for 100 or more people.
* Breakdown metrics for Page post and Page view insights will only return non-zero values.
* Several video related metrics only return accurate values if the person requesting the metric is the Page video post creator.
* If you reshare a video post of another Page and retrieve its insights, the metrics return a value of 0. Metrics that return 0 for resharers are denoted with "Returns 0 for reshared videos" in their description.
* If you neglect to indicate a specific metric or metrics for the endpoint, you will receive an error response with code `3001`, with subcode `1504028` and an error message that states: "No metric was specified to be fetched. Please specify one or more metrics to be fetched and try again."
* Interactions on Reels are not included.

### Requirements

Type | Description || [Access Tokens](/docs/pages/access-tokens) | A Page access token requested by a person who can perform the ANALYZE task on the Page. |
| [Features](/docs/pages/overview#features) | Not applicable. |
| [Permissions](/docs/pages/overview#permissions) | `read_insights`, `pages_read_engagement` |
| [Page Tasks](/docs/pages/overview#tasks) | [ANALYZE](/docs/pages/overview#tasks) |

### Example

#### Single Metric Sample Request

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bobject-id%7D%2Finsights%2F%7Bmetric%7D&version=v25.0)

```
GET v25.0/{object-id}/insights/{metric} HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '{object-id}/insights/{metric}',
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
    "{object-id}/insights/{metric}",
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
    "{object-id}/insights/{metric}",
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
                               initWithGraphPath:@"{object-id}/insights/{metric}"
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

If you want to learn how to use the Graph API, read our [Using Graph API guide](/docs/graph-api/using-graph-api/).

#### Multiple Metric Sample Request

**NOTE:** If your request times out or some metrics are not returned, try reducing the number of metrics in your API request.

HTTPPHP SDKJavaScript SDKAndroid SDKiOS SDK[Graph API Explorer](/tools/explorer/?method=GET&path=%7Bobject-id%7D%2Finsights%3Fmetric%3D%257Bmetric-1%257D%252C%257Bmetric-2%257D%252C%257Bmetric-3%257D%252C...&version=v25.0)

```
GET v25.0/{object-id}/insights?metric={metric-1},{metric-2},{metric-3},... HTTP/1.1
Host: graph.facebook.com
```

```
/* PHP SDK v5.0.0 */
/* make the API call */
try {
  // Returns a `Facebook\FacebookResponse` object
  $response = $fb->get(
    '{object-id}/insights?metric={metric-1},{metric-2},{metric-3},...',
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
    "{object-id}/insights?metric={metric-1},{metric-2},{metric-3},...",
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
    "{object-id}/insights?metric={metric-1},{metric-2},{metric-3},...",
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
                               initWithGraphPath:@"{object-id}/insights?metric={metric-1},{metric-2},{metric-3},..."
                                      parameters:params
                                      HTTPMethod:@"GET"];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection,
                                      id result,
                                      NSError *error) {
    // Handle the result
}];
```

If you want to learn how to use the Graph API, read our [Using Graph API guide](/docs/graph-api/using-graph-api/).

### Metrics

Metric names indicate whether a metric is for a Page or a Page post.

Suffix | Description || `_unique` | Indicates that the metric shows the number of unique users who performed a specific action, for example `page_impressions_unique`. **Metrics generated with the `_unique` suffix are approximate and may not be 100% accurate.** |
| `_login` | Indicates whether a person was logged into Facebook, for example, `page_tab_views_login_top`. |
| `_logout` | Indicates whether a person is logged out of Facebook, for example `page_views_logout`. |
| `_source` | Indicates that the metric will be broken down into a list of referral sources, for example `page_fans_by_like_source`. External referrals are broken down by domain. Internal referrals are broken down by Facebook-specific features such as **Profile**, **Search**, **Requests**, **Suggestions**, **Stream**, etc. In these cases the `value` returned will be an object containing a series of key-value pairs where the key is the source name and the value is the metric for that source. |
| `*` | Indicates that a metric is refreshed several times during the day, for example `page_impressions_unique*`. |

### Page Content

Most of the metrics below can be retrieved using `post_activity_by_action_type`, `post_clicks_by_type`, and `page_consumptions_by_consumption_type`.

| Metric Name | Description | Values for `period` |
| --- | --- | --- |
| `page_tab_views_login_top_unique` | The number of users logged in to Facebook who saw tabs on your Page.  (See [possible types](#tab-types)) | day, week |
| `page_tab_views_login_top` | The number of times users logged into Facebook saw tabs on your Page.  (See [possible types](#tab-types)) | day, week |
| `page_tab_views_logout_top` | The number of times users not logged in to Facebook saw tabs on your Page.  (See [possible types](#tab-types)) | day |

#### Tab Types

Tab types for Page content metrics.

| Name | Description |
| --- | --- |
| `allactivity` | Administrative tab |
| `app` | Custom created tab |
| `info` | About tab view |
| `insights` | Insights tab |
| `likes` | Likes tab |
| `locations` | Map tab |
| `photos` | Photos tab |
| `photos_albums` | Photos tab |
| `photos_stream` | Photos tab |
| `profile` | Pages timeline |
| `profile_info` | Info tab |
| `profile_likes` | Likes tab |
| `profile_photos` | Photos tab |
| `timeline` | Pages timeline |
| `events` | Events tab |
| `videos` | Videos tab |
| `wall` | Timeline |

### Page CTA Clicks

| Metric Name | Description | Values for `period` |
| --- | --- | --- |
| `page_total_actions` | The number of clicks on your Page's contact info and call-to-action button. | day, week, days\_28 |

### Page Engagement

The "like" reaction counts include both "like" and "care" reactions.

| Metric Name | Description | Values for `period` |
| --- | --- | --- |
| `page_post_engagements*` | The number of times people have engaged with your posts through reactions, comments, shares and more. | day, week, days\_28 |
| `page_fan_adds_by_paid_non_paid_unique` | The number of [Accounts Center accounts](/help/283579896000936) that liked your Page for the first time, broken down based on whether the Page like was attributed to paid or organic content. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling). | day |
| `page_lifetime_engaged_followers_unique*` | Someone who follows your Page and who has, in the past 14 days, watched one or more of your live or previously recorded videos for at least 1 minute and/or interacted with your video content at least once, via a comment, share, reaction or like. |  |
| `page_daily_follows*` | Not defined | day |
| `page_daily_follows_unique*` | Not defined This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling). | day, week, days\_28 |
| `page_daily_unfollows_unique*` | The number of [Meta Accounts](https://www.facebook.com/business/help/283579896000936) that unfollowed your Page in the selected time period. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling). | day, week, days\_28 |
| `page_follows*` | The number of followers of your Facebook Page or profile. This is calculated as the number of follows minus the number of unfollows over the lifetime of your Facebook Page or profile. | day |

### Page Impressions

| Metric Name | Description | Values for `period` |
| --- | --- | --- |
| `page_impressions*` | The number of times any content from your Page or about your Page entered a person's screen. This includes posts, stories, ads, as well other content or information on your Page. | day, week, days\_28 |
| `page_impressions_unique*` | Deprecated above Graph API v25: The number of people who had any content from your Page or about your Page enter their screen. This includes posts, check-ins, ads, social information from people who interact with your Page and more. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling). | day, week, days\_28 |
| `page_impressions_paid*` | The number of times any post or story content from your Page or about your Page entered a person's screen through paid distribution such as an ad. | day, week, days\_28 |
| `page_impressions_paid_unique*` | The number of [Accounts Center accounts](https://www.facebook.com/business/help/283579896000936) that saw your ads at least once. Reach is different from impressions, which may include multiple views of your ads by the same Accounts Center accounts. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling). | day, week, days\_28 |
| `page_impressions_viral*` | The number of times any content from your Page or about your Page entered a person's screen with social information attached. Social information displays when a person's friend interacted with you Page or post. This includes when someone's friend likes or follows your Page, engages with a post, shares a photo of your Page and checks into your Page. | day, week, days\_28 |
| `page_impressions_viral_unique*` | This metric counts reach from the organic or paid distribution of your Facebook Page and Page content when they were shown with social information attached. Social information is shown on Feed after someone interacts with your Page, post or story. Reach is only counted once if it occurs from both organic and paid distribution. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling) and [in development](https://www.facebook.com/business/help/metrics-labeling). | day, week, days\_28 |
| `page_impressions_nonviral*` | The number of times any content from your Page entered a person's screen. This does not include content created about your Page with social information attached. Social information displays when a person's friend interacted with you Page or post. This includes when someone's friend likes or follows your Page, engages with a post, shares a photo of your Page and checks into your Page. | day, week, days\_28 |
| `page_impressions_nonviral_unique*` | This metric counts reach from the organic or paid distribution of your Facebook Page and Page content, excluding when they were shown with social information attached. Social information is shown on Feed after someone interacts with your Page, post or story. Reach is only counted once if it occurs from both organic and paid distribution. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling) and [in development](https://www.facebook.com/business/help/metrics-labeling). | day, week, days\_28 |

### Page Media View

Metric Name | Description | Values for period | Available breakdowns || `page_media_view` | The number of times your content was played or displayed. Content includes videos, posts, stories and ads. | day, week, days\_28 | is\_from\_ads, is\_from\_followers |
| `page_total_media_view_unique` | The number of total unique media viewers for FB page | day, week, days\_28 |  |

### Page View

| Metric Name | Description | Values for `period` |
| --- | --- | --- |
| `page_impressions*` | The number of times any content from your Page or about your Page entered a person's screen. This includes posts, stories, ads, as well other content or information on your Page. | day, week, days\_28 |
| `page_impressions_unique*` | Deprecated above Graph API v25: The number of people who had any content from your Page or about your Page enter their screen. This includes posts, check-ins, ads, social information from people who interact with your Page and more. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling). | day, week, days\_28 |
| `page_impressions_paid*` | The number of times any post or story content from your Page or about your Page entered a person's screen through paid distribution such as an ad. | day, week, days\_28 |
| `page_impressions_paid_unique*` | The number of [Accounts Center accounts](https://www.facebook.com/business/help/283579896000936) that saw your ads at least once. Reach is different from impressions, which may include multiple views of your ads by the same Accounts Center accounts. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling). | day, week, days\_28 |
| `page_impressions_viral*` | The number of times any content from your Page or about your Page entered a person's screen with social information attached. Social information displays when a person's friend interacted with you Page or post. This includes when someone's friend likes or follows your Page, engages with a post, shares a photo of your Page and checks into your Page. | day, week, days\_28 |
| `page_impressions_viral_unique*` | This metric counts reach from the organic or paid distribution of your Facebook Page and Page content when they were shown with social information attached. Social information is shown on Feed after someone interacts with your Page, post or story. Reach is only counted once if it occurs from both organic and paid distribution. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling) and [in development](https://www.facebook.com/business/help/metrics-labeling). | day, week, days\_28 |
| `page_impressions_nonviral*` | The number of times any content from your Page entered a person's screen. This does not include content created about your Page with social information attached. Social information displays when a person's friend interacted with you Page or post. This includes when someone's friend likes or follows your Page, engages with a post, shares a photo of your Page and checks into your Page. | day, week, days\_28 |
| `page_impressions_nonviral_unique*` | This metric counts reach from the organic or paid distribution of your Facebook Page and Page content, excluding when they were shown with social information attached. Social information is shown on Feed after someone interacts with your Page, post or story. Reach is only counted once if it occurs from both organic and paid distribution. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling) and [in development](https://www.facebook.com/business/help/metrics-labeling). | day, week, days\_28 |

### Page Posts

| Metric Name | Description | Values for `period` |
| --- | --- | --- |
| `page_posts_impressions*` | The number of times your Page's posts entered a person's screen. Posts include statuses, photos, links, videos and more. | day, week, days\_28 |
| `page_posts_impressions_unique*` | The number of people who had any of your Page's posts enter their screen. Posts include statuses, photos, links, videos and more. | day, week, days\_28 |
| `page_posts_impressions_paid*` | The number of times your Facebook Page and Page content was on screen, attributed to your ads. | day, week, days\_28 |
| `page_posts_impressions_paid_unique*` | The number of [Accounts Center accounts](/help/283579896000936) that saw any posts from your Page at least once, attributed to your ads. | day, week, days\_28 |
| `page_posts_impressions_organic_unique*` | The number of people who had any of your Page's posts enter their screen through unpaid distribution. | day, week, days\_28 |
| `page_posts_served_impressions_organic_unique` | The number of people who were served your Page's posts in their Feed whether it entered their screen or not. Posts include statuses, photos, links, videos and more. | day, week, days\_28 |
| `page_posts_impressions_viral` | The number of times your Page's posts entered a person's screen with social information attached. Social information displays when a person's friend interacted with you Page or post. This includes when someone's friend likes or follows your Page, engages with a post, shares a photo of your Page and checks into your Page. | day, week, days\_28 |
| `page_posts_impressions_viral_unique` | The number of people who had any of your Page's posts enter their screen with social information attached. As a form of organic distribution, social information displays when a person's friend interacted with you Page or post. This includes when someone's friend likes or follows your Page, engages with a post, shares a photo of your Page and checks into your Page. | day, week, days\_28 |
| `page_posts_impressions_nonviral` | The number of times your Page's posts entered a person's screen. This does not include content created about your Page with social information attached. Social information displays when a person's friend interacted with you Page or post. This includes when someone's friend likes or follows your Page, engages with a post, shares a photo of your Page and checks into your Page. | day, week, days\_28 |
| `page_posts_impressions_nonviral_unique*` | The number of people who had any posts by your Page enter their screen. This does not include content created about your Page with social information attached. As a form of organic distribution, social information displays when a person's friend interacted with you Page or post. This includes when someone's friend likes or follows your Page, engages with a post, shares a photo of your Page and checks into your Page. | day, week, days\_28 |

### Page Post Engagement

| Metric Name | Description | Values for `period` |
| --- | --- | --- |
| `post_clicks*` | The number of times people clicked on anywhere in your posts without generating a story. | lifetime |
| `post_clicks_by_type*` | The number of times people clicked on anywhere in your posts without generating a story, by consumption type. | lifetime |

#### Negative Feedback Types

Negative feedback types for `page_negative_feedback_by_type` metrics.

| Name | Description |
| --- | --- |
| `hide_clicks` | Hide this story |
| `hide_all_clicks` | Hide all posts from this page |
| `report_spam_clicks` | Report an object as a spam |
| `unlike_page_clicks` | Unlike a page |

### Page Post Impressions

| Metric Name | Description | Values for `period` |
| --- | --- | --- |
| `post_impressions*` | Deprecated above Graph API v25: The number of times your Page's post entered a person's screen. Posts include statuses, photos, links, videos and more. | lifetime |
| `post_impressions_unique*` | Deprecated above Graph API v25: The number of people who had your Page's post enter their screen. Posts include statuses, photos, links, videos and more. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling). | lifetime |
| `post_impressions_paid*` | The number of times your Page content was on screen, attributed to your ads. | lifetime |
| `post_impressions_paid_unique*` | The number of [Accounts Center accounts](/help/283579896000936) that saw your post at least once, attributed to your ads. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling). | lifetime |
| `post_impressions_fan*` | The number of times your Page content was on screen for accounts that followed or liked your Page. | lifetime |
| `post_impressions_fan_unique*` | Deprecated above Graph API v25: The number of [Meta Accounts](https://www.facebook.com/business/help/283579896000936) that followed or liked your Page. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling). | lifetime |
| `post_impressions_organic*` | The number of times your post was on screen through organic distribution. | lifetime |
| `post_impressions_organic_unique*` | Deprecated above Graph API v25: This metric counts reach from the organic distribution of your Facebook content, including posts, stories and ads. Reach from shares is counted towards organic content only. This includes cases where your content is shared as a story or repost. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling). | lifetime |
| `post_impressions_viral*` | The number of times your Page content was on screen with social information attached. Social information is shown on Feed after someone interacts with your Page, post or story. This metric is [in development](https://www.facebook.com/business/help/metrics-labeling). | lifetime |
| `post_impressions_viral_unique*` | This metric counts reach when your Facebook content was shared as a repost or story. Reach from shares only counts towards organic distribution. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling) and [in development](https://www.facebook.com/business/help/metrics-labeling). | lifetime |
| `post_impressions_nonviral*` | The number of times your Page content was on screen, excluding when your content was shown with social information attached. Social information is shown on Feed after someone interacts with your Page, post or story. This metric is [in development](https://www.facebook.com/business/help/metrics-labeling). | lifetime |
| `post_impressions_nonviral_unique*` | Deprecated above Graph API v25: This metric counts reach from the organic or paid distribution of your Page content, excluding when your content was shown with social information attached. Social information is shown on Feed after someone interacts with your Page, post or story. Reach is only counted once if it occurs from both organic and paid distribution. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling) and [in development](https://www.facebook.com/business/help/metrics-labeling). | lifetime |

### Page Post Media View

Metric Name | Description | Values for period | Available breakdowns || `post_media_view` | The number of times your content was played or displayed. Content includes videos, posts, stories and ads. | lifetime | is\_from\_ads, is\_from\_followers |
| `post_total_media_view_unique` | The number of total unique media viewers for FB post | lifetime |  |

### Page Post Reactions

The "like" reaction counts include both "like" and "care" reactions.

| Metric Name | Description | Values for `period` |
| --- | --- | --- |
| `post_reactions_like_total` | Total "like" reactions of a post. | lifetime |
| `post_reactions_love_total` | Total "love" reactions of a post. | lifetime |
| `post_reactions_wow_total` | Total "wow" reactions of a post. | lifetime |
| `post_reactions_haha_total` | Total "haha" reactions of a post. | lifetime |
| `post_reactions_sorry_total` | Total "sad" reactions of a post. | lifetime |
| `post_reactions_anger_total` | Total "anger" reactions of a post. | lifetime |
| `post_reactions_by_type_total` | Total post reactions by type. | lifetime |

### Page Reactions

The "like" reaction counts include both "like" and "care" reactions.

| Metric Name | Description | Values for `period` |
| --- | --- | --- |
| `page_actions_post_reactions_like_total*` | Daily total post "like" reactions of a page. | day, week, days\_28 |
| `page_actions_post_reactions_love_total*` | Daily total post "love" reactions of a page. | day, week, days\_28 |
| `page_actions_post_reactions_wow_total*` | Daily total post "wow" reactions of a page. | day, week, days\_28 |
| `page_actions_post_reactions_haha_total*` | Daily total post "haha" reactions of a page. | day, week, days\_28 |
| `page_actions_post_reactions_sorry_total*` | Daily total post "sorry" reactions of a page. | day, week, days\_28 |
| `page_actions_post_reactions_anger_total*` | Daily total post "anger" reactions of a page. | day, week, days\_28 |
| `page_actions_post_reactions_total` | Daily total post reactions of a page by type. | day |

### Page User Demographics

| Metric Name | Description | Values for `period` |
| --- | --- | --- |
| `page_fans` | The total number of people who have liked your Page. | day |
| `page_fans_locale` | Aggregated language data about the people who like your Page based on the default language setting selected when accessing Facebook. | day |
| `page_fans_city` | Aggregated Facebook location data, sorted by city, about the people who like your Page. | day |
| `page_fans_country` | The number of people, aggregated per country, that like your Page. Only the 45 countries with the most people that like your Page are included. | day |
| `page_fan_adds` | The number of new people who have liked your Page. | day |
| `page_fan_adds_unique` | The number of new people who have liked your Page. This metric is [estimated](https://www.facebook.com/business/help/metrics-labeling). | day, week, days\_28 |
| `page_fan_removes` | Unlikes of your Page. | day |
| `page_fan_removes_unique*` | Unlikes of your Page. | day, week, days\_28 |

#### Page Like Sources

Source types for `page_fans_by_like_source` and `page_fans_by_like_source_unique` metrics.

| Name | Description |
| --- | --- |
| `Ads` | Page likes that came from people who saw your Page or post in an ad. |
| `News Feed` | Page likes that came from people who saw content posted by your Page or about your Page in News Feed. |
| `Page Suggestions` | Page likes that came from people saw your Page in a list of suggested Pages. |
| `Restored Likes from Reactivated Accounts` | Page likes that came from people who reactivated their Facebook profile. |
| `Search` | Page likes that came from people who saw you Page or post in search. |
| `Your Page` | Page likes that came from people who visited your Page. |

### Page Video Views

| Metric Name | Description | Values for `period` |
| --- | --- | --- |
| `page_video_views` | The number of times your Page's videos played for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_views_by_uploaded_hosted*` | Daily video views on a page-level broken down by all variants of page-uploaded and page-hosted variants. | day, week, days\_28 |
| `page_video_views_paid` | The number of times your Page's promoted videos played for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds. For each impression of a video, we'll count video views separately and exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_views_organic` | The number of times your Page's videos played for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds, by organic reach. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_views_by_paid_non_paid*` | The number of times your Page's videos played for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds, broken down by total, paid, and non-paid. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_views_autoplayed` | The number of times your Page's videos automatically played for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_views_click_to_play` | The number of times your Page's videos played for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds, after people clicked play. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_views_unique` | Deprecated above Graph API v25: The number of people who viewed your Page's videos for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_repeat_views` | The number of times your Page's videos were replayed for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds. | day, week, days\_28 |
| `page_video_complete_views_30s` | The number of times your Page's videos played for at least 30 seconds, or for nearly their total length if they're shorter than 30 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_complete_views_30s_paid` | The number of times your Page's promoted videos played for at least 30 seconds, or for nearly their total length if they're shorter than 30 seconds. For each impression of a video, we'll count video views separately and exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_complete_views_30s_organic` | The number of times your Page's videos played for at least 30 seconds, or for nearly their total length if they're shorter than 30 seconds, by organic reach. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_complete_views_30s_autoplayed` | The number of times your Page's automatically played videos played for at least 30 seconds, or for nearly their total length if they're shorter than 30 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_complete_views_30s_click_to_play` | The number of times your Page's videos played for at least 30 seconds, or for nearly their total length if they're shorter than 30 seconds, after people clicked play. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_complete_views_30s_unique` | The number of people who viewed your Page's videos for at least 30 seconds, or for nearly their total length if they're shorter than 30 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_complete_views_30s_repeat_views` | The number of times your Page's videos replayed for at least 30 seconds, or for nearly their total length if they're shorter than 30 seconds. | day, week, days\_28 |
| `post_video_complete_views_30s_autoplayed` | The number of times your videos automatically played for at least 30 seconds, or for nearly their total length if they're shorter than 30 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. Returns 0 for reshared videos. | lifetime |
| `post_video_complete_views_30s_clicked_to_play` | The number of times your videos played for at least 30 seconds, or for nearly their total length if they're shorter than 30 seconds, after people clicked play. During a single instance of a video playing, we'll exclude any time spent replaying the video. Returns 0 for reshared videos. | lifetime |
| `post_video_complete_views_30s_organic` | The number of times your videos played for at least 30 seconds, or for nearly their total length if they're shorter than 30 seconds, by organic reach. During a single instance of a video playing, we'll exclude any time spent replaying the video. Returns 0 for reshared videos. | lifetime |
| `post_video_complete_views_30s_paid` | The number of times your promoted videos played for at least 30 seconds, or for nearly their total length if they're shorter than 30 seconds. For each impression of a video, we'll count video views separately and exclude any time spent replaying the video. Returns 0 for reshared videos. | lifetime |
| `post_video_complete_views_30s_unique` | The number of people who viewed your videos for at least 30 seconds, or for nearly their total length if they're shorter than 30 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | lifetime |
| `page_video_views_10s` | Deprecated above Graph API v18: The number of times your Page's videos played for at least 10 seconds, or for nearly their total length if they're shorter than 10 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_views_10s_paid` | Deprecated above Graph API v18: The number of times your Page's promoted videos played for at least 10 seconds, or for nearly their total length if they're shorter than 10 seconds. For each impression of a video, we'll count video views separately and exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_views_10s_organic` | Deprecated above Graph API v18: The number of times your Page's videos played for at least 10 seconds, or for nearly their total length if they're shorter than 10 seconds, by organic reach. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_views_10s_autoplayed` | Deprecated above Graph API v18: The number of times your Page's videos automatically played for at least 10 seconds, or for nearly their total length if they're shorter than 10 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_views_10s_click_to_play` | Deprecated above Graph API v18: The number of times your Page's videos played for at least 10 seconds, or for nearly their total length if they're shorter than 10 seconds, after people clicked play. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_views_10s_unique` | Deprecated above Graph API v18: The number of people who viewed your Page's videos for at least 10 seconds, or for nearly their total length if they're shorter than 10 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, week, days\_28 |
| `page_video_views_10s_repeat` | Deprecated above Graph API v18: The number of times your Page's videos replayed for at least 10 seconds, or for nearly their total length if they're shorter than 10 seconds. | day, week, days\_28 |
| `page_video_view_time` | The total time, in milliseconds, people viewed your Page's video. | day |
| `page_uploaded_3s_to_15s_views_rate*` | 3s to 15s Views Rate. Measured across all uploaded video assets. This includes any activity on posts/crossposts or their shares. |  |
| `page_uploaded_views_15s_count*` | Total number of video views for those who watched at least 15 seconds of your Page's video. |  |
| `page_uploaded_views_60s_excludes_shorter_unique_count_by_is_60s_returning_viewer*` | Daily video 60-second unique views on a page for uploaded videos by 60-second returning viewers. This metric counts only for videos that are 60 seconds or longer. 60-second returning viewers are the users who had 60-second view last week and a 60-second view this week. |  |

### Page Views

| Metric Name | Description | Values for `period` |
| --- | --- | --- |
| `page_views_total*` | The number of times a Page's profile has been viewed by logged in and logged out people. | day, week, days\_28 |

### Page Video Posts

| Metric Name | Description | Values for `period` |
| --- | --- | --- |
| `post_video_avg_time_watched` | The average time, in milliseconds, people viewed your videos. Only available for videos created after August 25th 2016. Returns 0 for reshared videos. | lifetime |
| `post_video_complete_views_organic` | The number of times your videos played from the beginning to 97%, or more, of its length, by organic reach. During a single instance of a video playing, we'll exclude any time spent replaying the video. Returns 0 for reshared videos. | lifetime |
| `post_video_complete_views_organic_unique` | The number of people who viewed your videos from the beginning to 97%, or more, of its length, by organic reach. During a single instance of a video playing, we'll exclude any time spent replaying the video. Returns 0 for reshared videos. | lifetime |
| `post_video_complete_views_paid` | The number of times your promoted videos played from the beginning to 97%, or more, of its length. For each impression of a video, we'll count video views separately and exclude any time spent replaying the video. Returns 0 for reshared videos. | lifetime |
| `post_video_complete_views_paid_unique` | The number of people who viewed your promoted videos from the beginning to 97%, or more, of its length. For each impression of a video, we'll count video views separately and exclude any time spent replaying the video. | lifetime |
| `post_video_retention_graph*` | The number of times your videos played at each interval as a percentage of all views. Videos are divided into 40 equal intervals. This metric does not count impressions while the video was live. Retention graphs may show more impressions later in the video than at the beginning. People might start the video in the middle, skip ahead, save, and rewatch it from that point, or other similar behaviors. | lifetime |
| `post_video_retention_graph_clicked_to_play` | The number of times your videos played at each interval as a percentage of all views, after people clicked play. Videos are divided into 40 equal intervals. This metric does not count impressions while the video was live. Retention graphs may show more impressions later in the video than at the beginning. People might start the video in the middle, skip ahead, save, and rewatch it from that point, or other similar behaviors. | lifetime |
| `post_video_retention_graph_autoplayed` | The number of times your videos automatically played at each interval as a percentage of all automatic views. Videos are divided into 40 equal intervals.This metric does not count impressions while the video was live. Retention graphs may show more impressions later in the video than at the beginning. People might start the video in the middle, skip ahead, save, and rewatch it from that point, or other similar behaviors. | lifetime |
| `post_video_views_organic` | The number of times your videos played for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds, by organic reach. During a single instance of a video playing, we'll exclude any time spent replaying the video. | lifetime, day |
| `post_video_views_organic_unique` | The number of people who viewed your videos for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds, by organic reach. During a single instance of a video playing, we'll exclude any time spent replaying the video. | lifetime |
| `post_video_views_paid` | The number of times your promoted videos played for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds. For each impression of a video, we'll count video views separately and exclude any time spent replaying the video. | lifetime, day |
| `post_video_views_paid_unique` | The number of people who viewed your promoted videos for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds. For each impression of a video, we'll count video views separately and exclude any time spent replaying the video. | lifetime |
| `post_video_length` | The length, in milliseconds, of a video post. | lifetime |
| `post_video_views` | The number of times your videos played for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. This includes live views. | lifetime, day |
| `post_video_views_unique` | Deprecated above Graph API v25: The number of people who viewed your videos for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | day, lifetime |
| `post_video_views_autoplayed` | The number of times your videos automatically played for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | lifetime |
| `post_video_views_clicked_to_play` | The number of times your videos played for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds, after people clicked play. During a single instance of a video playing, we'll exclude any time spent replaying the video. | lifetime |
| `post_video_views_15s*` | The number of times your videos played for at least 15 seconds, or for nearly their total length if they're shorter than 15 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | lifetime |
| `post_video_views_60s_excludes_shorter*` | The number of times your videos played for at least 60 seconds. This metric is counted only for videos that are 60 seconds or longer. During a single instance of a video playing, we'll exclude any time spent replaying the video. | lifetime, day |
| `post_video_views_10s` | Deprecated above Graph API v18: The number of times your videos played for at least 10 seconds, or for nearly their total length if they're shorter than 10 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | lifetime, day |
| `post_video_views_10s_unique` | Deprecated above Graph API v18: The number of people who viewed your videos for at least 10 seconds, or for nearly their total length if they're shorter than 10 seconds. For each impression of a video, we'll count video views separately and exclude any time spent replaying the video. | lifetime |
| `post_video_views_10s_autoplayed` | Deprecated above Graph API v18: The number of times your videos played automatically for at least 10 seconds, or for nearly their total length if they're shorter than 10 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | lifetime |
| `post_video_views_10s_clicked_to_play` | Deprecated above Graph API v18: The number of times your videos played for at least 10 seconds, or for nearly their total length if they're shorter than 10 seconds, after people clicked play. During a single instance of a video playing, we'll exclude any time spent replaying the video. | lifetime |
| `post_video_views_10s_organic` | Deprecated above Graph API v18: The number of times your videos played for at least 10 seconds, or for nearly their total length if they're shorter than 10 seconds, by organic reach. During a single instance of a video playing, we'll exclude any time spent replaying the video. | lifetime |
| `post_video_views_10s_paid` | Deprecated above Graph API v18: The number of times your promoted videos played for at least 10 seconds, or for nearly their total length if they're shorter than 10 seconds. For each impression of a video, we'll count video views separately and exclude any time spent replaying the video. | lifetime, day |
| `post_video_views_10s_sound_on` | Deprecated above Graph API v18: The number of times your videos played with sound on for at least 10 seconds, or for nearly their total length if they're shorter than 10 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | lifetime |
| `post_video_views_sound_on` | The number of times your videos played with sound on for at least 3 seconds, or for nearly their total length if they're shorter than 3 seconds. During a single instance of a video playing, we'll exclude any time spent replaying the video. | lifetime |
| `post_video_view_time` | The total time, in milliseconds, your videos played, including videos played for less than 3 seconds and replays. Returns 0 for reshared videos. | lifetime, day |
| `post_video_view_time_organic` | The total time, in milliseconds, your videos played by organic reach. Returns 0 for reshared videos. | lifetime, day |
| `post_video_view_time_by_age_bucket_and_gender` | The total time, in milliseconds, your videos played for your Top Audiences, age and gender. | lifetime |
| `post_video_view_time_by_region_id` | The total time, in milliseconds, your videos played for your Top 45 Locations, Region - Country. | lifetime, day |
| `post_video_views_by_distribution_type` | The number of times your videos played by distribution type; page\_owned and shared. | lifetime |
| `post_video_view_time_by_distribution_type` | The total time, in milliseconds, your videos played by distribution type; page\_owned and shared. | lifetime |
| `post_video_view_time_by_country_id` | The total number of minutes your videos played for your Top 45 Locations; Country. | lifetime |
| `post_video_views_live*` | Lifetime number of people who viewed your video for more than 3 seconds when it was streamed live. | lifetime |
| `post_video_social_actions_count_unique*` | The unique count of the social actions (reactions, comments, shares) on a video post. | lifetime, day |
| `post_video_live_current_viewers*` | The number of viewers currently watching a live video. This metric is only returned for live posts. Returns 0 for was live posts. |  |
| `post_video_15s_to_60s_excludes_shorter_views_rate*` | 15s to 60s Views Rate for a video. This 60s metric is counted only for videos that are 60 seconds or longer. |  |
| `post_video_views_by_live_status*` | Lifetime 3S Video Views broken down by live status: live or VOD |  |

### Stories

Page and Post Stories and "People talking about this".

| Metric Name | Description | Values for `period` |
| --- | --- | --- |
| `post_activity_by_action_type*` | The number of stories created about your Page post, by action type. | lifetime |
| `post_activity_by_action_type_unique*` | The number of people who created a story about your Page post, by action type. | lifetime |

#### Page Story Types

| Name | Description |
| --- | --- |
| `checkin` | Page checkins |
| `coupon` | Offer claims |
| `event` | RSVPing to event |
| `fan` | Page likes |
| `mention` | Page mentions |
| `page post` | Posts by a Page |
| `question` | Question answers |
| `user post` | Posts by people on a Page |
| `other` | Other types |

### Video Ad Breaks

Metric Name | Description | Values for period || `page_daily_video_ad_break_ad_impressions_by_crosspost_status` | The total number of times an ad was shown during ad breaks in crossposted videos. | day |
| `page_daily_video_ad_break_cpm_by_crosspost_status` | The average amount paid by advertisers for 1,000 of impressions of their ads in a crossposted videos. This is a gross number and includes the amount paid to Facebook. | day |
| `page_daily_video_ad_break_earnings_by_crosspost_status` | An estimate of the amount you earned from ad breaks in a crossposted videos, based on the number of impressions and CPM of ads shown. Actual payments may differ if there are content ownership claims or other adjustments. | day |
| `post_video_ad_break_ad_impressions` | The total number of times an ad was shown during ad breaks in your videos. | day, lifetime |
| `post_video_ad_break_earnings` | An estimate of the amount you earned from ad breaks in your videos, based on the number of impressions and CPM of ads shown. Actual payments may differ if there are content ownership claims or other adjustments. | day, lifetime |
| `post_video_ad_break_ad_cpm` | The average amount paid by advertisers for 1,000 impressions of their ads in your videos. This number also includes the amount paid to Facebook. | day, lifetime |
| `creator_monetization_qualified_views` | The number of views of your videos that will receive a payout. To qualify for payout, your Page or profile must generate ad revenue in the current earning period. You must also be following the Partner Monetization Policies and Content Monetization Policies. There are additional factors which may disqualify a view for payout. | day,lifetime |

### Content Monetization

Metric Name | Description | Values for period | Values for breakdown || `content_monetization_earnings` | The amount of money you may have earned from content monetization. The final amount may differ, depending on content reviews, reporting data and copyright claims. Approximate earnings are based on the following and solely determined by Meta:   * Qualified views for eligible public videos. * Total plays for eligible public reels. * Reach, comments, reactions and shares for all of your other eligible public posts excluding Stories.  [This metric is in development.](https://www.facebook.com/business/help/metrics-labeling) | page: day, week, days\_28  post: lifetime, day | page: earning\_source  post: N/A |

### Monetization Approximate Earnings

Metric Name | Description | Values for period | Values for breakdown || `monetization_approximate_earnings` | Your approximate earnings [from these revenue sources](https://www.facebook.com/business/help/194187525195870) except bonuses. Your actual payout may be higher or lower due to pending reviews, content ownership claims or other adjustments | page: day, week, days\_28, month  post: day,lifetime | monetization\_tool |

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `breakdown`  list<A valid breakdown for an insights endpoint> | breakdown |
| `date_preset`  enum{today, yesterday, this\_month, last\_month, this\_quarter, maximum, data\_maximum, last\_3d, last\_7d, last\_14d, last\_28d, last\_30d, last\_90d, last\_week\_mon\_sun, last\_week\_sun\_sat, last\_quarter, last\_year, this\_week\_mon\_today, this\_week\_sun\_today, this\_year} | date\_preset |
| `metric`  list<A valid metric for an insights endpoint> | metric |
| `period`  enum {day, week, days\_28, month, lifetime, total\_over\_range} | period |
| `show_description_from_api_doc`  boolean | Default value: `false`  show\_description\_from\_api\_doc |
| `since`  datetime | since |
| `until`  datetime | until |

### Fields

Reading from this edge will return a JSON formatted result:

```
{
    "data": [],
    "paging": {}
}
```

#### `data`

A list of [InsightsResult](/docs/graph-api/reference/insights-result/) nodes.

#### `paging`

For more details about pagination, see the [Graph API guide](/docs/graph-api/using-graph-api/#paging).

### Error Codes

| Error | Description |
| --- | --- |
| 100 | Invalid parameter |
| 190 | Invalid OAuth 2.0 Access Token |
| 200 | Permissions error |
| 80001 | There have been too many calls to this Page account. Wait a bit and try again. For more info, please refer to https://developers.facebook.com/docs/graph-api/overview/rate-limiting. |
| 3001 | Invalid query |
| 104 | Incorrect signature |
| 2500 | Error parsing graph query |

## Creating

You can't perform this operation on this endpoint.

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

## See Also

* View all your insights in the [Insights Dashboard](https://www.facebook.com/insights).
* Visit the [Insights Results Reference Guide](https://developers.facebook.com/docs/graph-api/reference/insights_result) for more information.

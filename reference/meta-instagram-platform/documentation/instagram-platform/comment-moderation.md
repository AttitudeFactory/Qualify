# Comment Moderation



This guide shows you how to get comments, reply to comments, delete comments, hide/unhide comments, and disable/enable comments on Instagram Media owned by your app users using the Instagram Platform.

In this guide we will be using **Instagram user** and **Instagram professional account** interchangeably. An  Instagram User object represents your app user&#039;s Instagram professional account.

## Requirements

This guide assumes you have read the [Instagram Platform Overview](https://developers.facebook.com/documentation/instagram-platform/overview) and implemented the needed components for using this API, such as a Meta login flow and a webhooks server to receive notifications.

You will need the following:

|  | Instagram API with Instagram Login | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User access token | * [Facebook Page access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_comments` | * `instagram_basic`&lt;br&gt;* `instagram_manage_comments`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;&lt;br&gt;If the app user was granted a role on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to your app user&#039;s Instagram professional account via the Business Manager, your app will also need:&lt;br&gt;&lt;br&gt;* `ads_management`&lt;br&gt;* `ads_read` |
| **Webhooks** | * `comments`&lt;br&gt;* `live_comments` | * `comments`&lt;br&gt;* `live_comments` |

#### Access Level

* Advanced Access if your app serves Instagram professional accounts you don&#039;t own or manage
* Standard Access if your app serves Instagram professional accounts you own or manage and have added to your app in the App Dashboard

#### Endpoints

- [`GET /&lt;IG_MEDIA_ID&gt;/comments`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-media/comments#reading)  — Get comments on an IG Media
- [`GET /&lt;IG_COMMENT_ID&gt;/replies`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment/replies#read) — Get replies on an IG Comment
- [`POST /&lt;IG_COMMENT_ID&gt;/replies`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment/replies#create) — Reply to an  IG Comment
- [`POST /&lt;IG_COMMENT_ID&gt;`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment#update) — Hide/unhide an IG Comment
- [`POST /&lt;IG_MEDIA_ID&gt;`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#update) — Disable/enable comments on an IG Media
- [`DELETE /&lt;IG_COMMENT_ID&gt;`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment#delete) — Delete an IG Comment

##  Get comments

There are two ways to get comments on published Instagram media, an API query or a webhook notification. We strongly recommend using webhooks to prevent rate limiting.

### API Request

To get all the comments on a published Instagram media object, send a `GET` request to the `/&lt;IG_MEDIA_ID&gt;/comments` endpoint.

```html
curl -X GET &quot;https://&lt;HOST_URL&gt;/v25.0/&lt;IG_MEDIA_ID&gt;/comments&quot;
```

On success your app receives a JSON response with an array of objects containing the comment ID, the comment text, and the time the comment was published.

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;timestamp&quot;: &quot;2017-08-31T19:16:02+0000&quot;,
      &quot;text&quot;: &quot;This is awesome!&quot;,
      &quot;id&quot;: &quot;17870913679156914&quot;
    &#125;,
    &#123;
      &quot;timestamp&quot;: &quot;2017-08-31T19:16:02+0000&quot;,
      &quot;text&quot;: &quot;Amazing!&quot;,
      &quot;id&quot;: &quot;17870913679156914&quot;
    &#125;,
    ... // results truncated for brevity
  ]
&#125;
```

### Webhooks

When the `comments` or `live_comments` event is triggered your webhooks server receives a notification that includes the ID for your app user&#039;s published media, and the ID for the comments on that media, and the Instagram-scoped ID for the person who published the comment.

**Note:** When hosting an Instagram Live story, make sure your server can handle the increased load of notifications triggered by `live_comments` webhooks events and that your system can differentiate between `live_comments` and `comments` notifications.

#### Facebook Login for Business

The following payload is returned for apps that have implemented Facebook Login for Business.

```html
[
  &#123;
    &quot;object&quot;: &quot;instagram&quot;,
    &quot;entry&quot;: [
      &#123;
        &quot;id&quot;: &quot;&lt;YOUR_APP_USERS_INSTAGRAM_ACCOUNT_ID&gt;&quot;,      // ID of your app user&#039;s Instagram professional account
        &quot;time&quot;: &lt;TIME_META_SENT_THIS_NOTIFICATION&gt;          // Time Meta sent the notification
        &quot;changes&quot;: [
          &#123;
            &quot;field&quot;: &quot;comments&quot;,
            &quot;value&quot;: &#123;
              &quot;from&quot;: &#123;
                &quot;id&quot;: &quot;&lt;INSTAGRAM_USER_SCOPED_ID&gt;&quot;,         // Instagram-scoped ID of the Instagram user who made the comment
                &quot;username&quot;: &quot;&lt;INSTAGRAM_USER_USERNAME&gt;&quot;     // Username of the Instagram user who made the comment
              &#125;&#039;,
              &quot;comment_id&quot;: &quot;&lt;COMMENT_ID&gt;&quot;,                 // Comment ID of the comment with the mention
              &quot;parent_id&quot;: &quot;&lt;PARENT_COMMENT_ID&gt;&quot;,           // Parent comment ID, included if the comment was made on a comment
              &quot;text&quot;: &quot;&lt;TEXT_ID&gt;&quot;,                          // Comment text, included if comment included text
              &quot;media&quot;: &#123;
                &quot;id&quot;: &quot;&lt;MEDIA_ID&gt;&quot;,                             // Media&#039;s ID that was commented on
                &quot;ad_id&quot;: &quot;&lt;AD_ID&gt;&quot;,                             // Ad&#039;s ID, included if the comment was on an ad post
                &quot;ad_title&quot;: &quot;&lt;AD_TITLE_ID&gt;&quot;,                    // Ad&#039;s title, included if the comment was on an ad post
                &quot;original_media_id&quot;: &quot;&lt;ORIGINAL_MEDIA_ID&gt;&quot;,     // Original media&#039;s ID, included if the comment was on an ad post
                &quot;media_product_type&quot;: &quot;&lt;MEDIA_PRODUCT_ID&gt;&quot;      // Product ID, included if the comment was on a specific product in an ad
              &#125;
            &#125;
          &#125;
        ]
      &#125;
    ]
  &#125;
]
```


#### Business Login for Instagram

The following payload is returned for apps that have implemented Business Login for Instagram.

```html
[
  &#123;
    &quot;object&quot;: &quot;instagram&quot;,
    &quot;entry&quot;: [
      &#123;
        &quot;id&quot;: &quot;&lt;YOUR_APP_USERS_INSTAGRAM_ACCOUNT_ID&gt;&quot;,
        &quot;time&quot;: &lt;TIME_META_SENT_THIS_NOTIFICATION&gt;

    // Comment or live comment payload
        &quot;field&quot;: &quot;comments&quot;,
        &quot;value&quot;: &#123;
          &quot;id&quot;: &quot;&lt;COMMENT_ID&gt;&quot;,
          &quot;from&quot;: &#123;
            &quot;id&quot;: &quot;&lt;INSTAGRAM_SCOPED_USER_ID&gt;&quot;,
            &quot;username&quot;: &quot;&lt;USERNAME&gt;&quot;
          &#125;,
          &quot;text&quot;: &quot;&lt;COMMENT_TEXT&gt;&quot;,
          &quot;media&quot;: &#123;
            &quot;id&quot;: &quot;&lt;MEDIA_ID&gt;&quot;,
            &quot;media_product_type&quot;: &quot;&lt;MEDIA_PRODUCT_TYPE&gt;&quot;
          &#125;
        &#125;
      &#125;
    ]
  &#125;
]
```


Your app can parse the API or webhook notification for comments that match your app user&#039;s criteria then use the comment&#039;s ID to reply to that comment.

## Reply to a comment

To reply to a comment, send a `POST` request to the `/&lt;IG_COMMENT_ID&gt;/replies` endpoint, where `&lt;IG_COMMENT_ID&gt;` is the ID for the comment which you want to reply, with the `message` parameter set to your message text.

#### Sample Request

```html
curl -X POST &quot;https://&lt;HOST_URL&gt;/v25.0/&lt;IG_COMMENT_ID&gt;/replies&quot;
   -H &quot;Content-Type: application/json&quot;
   -d &#039;&#123;
         &quot;message&quot;:&quot;Thanks for sharing!&quot;
       &#125;&#039;
```

On success, your app receives a JSON response with the comment ID for your comment.

```json
&#123;
  &quot;id&quot;: &quot;17873440459141029&quot;
&#125;
```

If your app user has a lot of comments to reply to, you could [batch the replies into a single request](https://developers.facebook.com/docs/graph-api/making-multiple-requests).

## Next steps

Learn how to send a message to the person who commented on your app user&#039;s media post using [Private Replies](https://developers.facebook.com/documentation/instagram-platform/private-replies).

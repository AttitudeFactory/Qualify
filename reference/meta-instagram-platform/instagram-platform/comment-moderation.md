# Comment Moderation



This guide shows you how to get comments, reply to comments, delete comments, hide/unhide comments, and disable/enable comments on Instagram Media owned by your app users using the Instagram Platform.

In this guide we will be using **Instagram user** and **Instagram professional account** interchangeably. An  Instagram User object represents your app user's Instagram professional account.

## Requirements

This guide assumes you have read the [Instagram Platform Overview](https://developers.facebook.com/documentation/instagram-platform/overview) and implemented the needed components for using this API, such as a Meta login flow and a webhooks server to receive notifications.

You will need the following:

|  | Instagram API with Instagram Login | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User access token | * [Facebook Page access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`<br>* `instagram_business_manage_comments` | * `instagram_basic`<br>* `instagram_manage_comments`<br>* `pages_read_engagement`<br><br>If the app user was granted a role on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to your app user's Instagram professional account via the Business Manager, your app will also need:<br><br>* `ads_management`<br>* `ads_read` |
| **Webhooks** | * `comments`<br>* `live_comments` | * `comments`<br>* `live_comments` |

#### Access Level

* Advanced Access if your app serves Instagram professional accounts you don't own or manage
* Standard Access if your app serves Instagram professional accounts you own or manage and have added to your app in the App Dashboard

#### Endpoints

- [`GET /<IG_MEDIA_ID>/comments`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-media/comments#reading)  — Get comments on an IG Media
- [`GET /<IG_COMMENT_ID>/replies`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment/replies#read) — Get replies on an IG Comment
- [`POST /<IG_COMMENT_ID>/replies`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment/replies#create) — Reply to an  IG Comment
- [`POST /<IG_COMMENT_ID>`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment#update) — Hide/unhide an IG Comment
- [`POST /<IG_MEDIA_ID>`](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#update) — Disable/enable comments on an IG Media
- [`DELETE /<IG_COMMENT_ID>`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment#delete) — Delete an IG Comment

##  Get comments

There are two ways to get comments on published Instagram media, an API query or a webhook notification. We strongly recommend using webhooks to prevent rate limiting.

### API Request

To get all the comments on a published Instagram media object, send a `GET` request to the `/<IG_MEDIA_ID>/comments` endpoint.

```html
curl -X GET "https://<HOST_URL>/v25.0/<IG_MEDIA_ID>/comments"
```

On success your app receives a JSON response with an array of objects containing the comment ID, the comment text, and the time the comment was published.

```json
{
  "data": [
    {
      "timestamp": "2017-08-31T19:16:02+0000",
      "text": "This is awesome!",
      "id": "17870913679156914"
    },
    {
      "timestamp": "2017-08-31T19:16:02+0000",
      "text": "Amazing!",
      "id": "17870913679156914"
    },
    ... // results truncated for brevity
  ]
}
```

### Webhooks

When the `comments` or `live_comments` event is triggered your webhooks server receives a notification that includes the ID for your app user's published media, and the ID for the comments on that media, and the Instagram-scoped ID for the person who published the comment.

**Note:** When hosting an Instagram Live story, make sure your server can handle the increased load of notifications triggered by `live_comments` webhooks events and that your system can differentiate between `live_comments` and `comments` notifications.

#### Facebook Login for Business

The following payload is returned for apps that have implemented Facebook Login for Business.

```html
[
  {
    "object": "instagram",
    "entry": [
      {
        "id": "<YOUR_APP_USERS_INSTAGRAM_ACCOUNT_ID>",      // ID of your app user's Instagram professional account
        "time": <TIME_META_SENT_THIS_NOTIFICATION>          // Time Meta sent the notification
        "changes": [
          {
            "field": "comments",
            "value": {
              "from": {
                "id": "<INSTAGRAM_USER_SCOPED_ID>",         // Instagram-scoped ID of the Instagram user who made the comment
                "username": "<INSTAGRAM_USER_USERNAME>"     // Username of the Instagram user who made the comment
              }',
              "comment_id": "<COMMENT_ID>",                 // Comment ID of the comment with the mention
              "parent_id": "<PARENT_COMMENT_ID>",           // Parent comment ID, included if the comment was made on a comment
              "text": "<TEXT_ID>",                          // Comment text, included if comment included text
              "media": {
                "id": "<MEDIA_ID>",                             // Media's ID that was commented on
                "ad_id": "<AD_ID>",                             // Ad's ID, included if the comment was on an ad post
                "ad_title": "<AD_TITLE_ID>",                    // Ad's title, included if the comment was on an ad post
                "original_media_id": "<ORIGINAL_MEDIA_ID>",     // Original media's ID, included if the comment was on an ad post
                "media_product_type": "<MEDIA_PRODUCT_ID>"      // Product ID, included if the comment was on a specific product in an ad
              }
            }
          }
        ]
      }
    ]
  }
]
```


#### Business Login for Instagram

The following payload is returned for apps that have implemented Business Login for Instagram.

```html
[
  {
    "object": "instagram",
    "entry": [
      {
        "id": "<YOUR_APP_USERS_INSTAGRAM_ACCOUNT_ID>",
        "time": <TIME_META_SENT_THIS_NOTIFICATION>

    // Comment or live comment payload
        "field": "comments",
        "value": {
          "id": "<COMMENT_ID>",
          "from": {
            "id": "<INSTAGRAM_SCOPED_USER_ID>",
            "username": "<USERNAME>"
          },
          "text": "<COMMENT_TEXT>",
          "media": {
            "id": "<MEDIA_ID>",
            "media_product_type": "<MEDIA_PRODUCT_TYPE>"
          }
        }
      }
    ]
  }
]
```


Your app can parse the API or webhook notification for comments that match your app user's criteria then use the comment's ID to reply to that comment.

## Reply to a comment

To reply to a comment, send a `POST` request to the `/<IG_COMMENT_ID>/replies` endpoint, where `<IG_COMMENT_ID>` is the ID for the comment which you want to reply, with the `message` parameter set to your message text.

#### Sample Request

```html
curl -X POST "https://<HOST_URL>/v25.0/<IG_COMMENT_ID>/replies"
   -H "Content-Type: application/json"
   -d '{
         "message":"Thanks for sharing!"
       }'
```

On success, your app receives a JSON response with the comment ID for your comment.

```json
{
  "id": "17873440459141029"
}
```

If your app user has a lot of comments to reply to, you could [batch the replies into a single request](https://developers.facebook.com/docs/graph-api/making-multiple-requests).

## Next steps

Learn how to send a message to the person who commented on your app user's media post using [Private Replies](https://developers.facebook.com/documentation/instagram-platform/private-replies).

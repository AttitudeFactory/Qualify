# Instagram Platform Webhook Notification Examples



This guide contains example JSON payloads for Instagram webhook notifications sent from Meta when a webhook field has been triggered. Syntax returned in notifications vary slightly depending on log in type implemented in your app and triggering event.

## Business Login for Instagram

The following notification examples are for apps that have implemented Business Login for Instagram.

Common parameters of notifications

`object` string

Platform on which the webhook event was triggered. In this instance, `instagram`.

`entry.id` string

The Instagram professional account ID of your app user

`entry.time` int

The time Meta sent the notification

`entry` array of objects

An array containing the contents of the notification

`entry` array of objects

An array containing the contents of the notification

```html
[
  {
    "object":"instagram",
    "entry":[
      {
        "id":"<YOUR_APP_USERS_INSTAGRAM_ACCOUNT_ID>",
        "time":<TIME_META_SENT_THIS_NOTIFICATION>,
        <NOTIFICATION_PAYLOAD>
      }
    ]
  }
]
```

### Comments payload

The comment event notification payloads include the following:

* `field` set to `comments` or `live_comments`
* `value` set to an array that contains:
    * The comment ID
    * The Instagram-scoped user ID of the Instagram user who commented on your app user's media
    * The username of the Instagram user who commented on your app user's media
    * Any text that was included in the comment
    * The media's ID
    * Where the media was located, in an ad, feed, story, or reel

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

### Messaging payload

All messaging webhook notifications included the following:

* `object` set to `instagram`
* `entry` set to an array containing:
    * The Instagram professional account ID of your app user who is in the conversation
    * The time Meta sent the notification
    * The sender's ID
    * The recipient's ID
    * The time when the message was sent
    * The notification payload for the specific webhook that was triggered

```html
[
  {
    "object":"instagram",
    "entry":[
      {
        "id": "<YOUR_APP_USERS_INSTAGRAM_ACCOUNT_ID>",
        "time": <TIME_META_SENT_NOTIFICATION>,
        "messaging": [
          {
            "sender": { "id": "<SENDER_ID>" },
            "recipient": { "id": "<RECIPIENT_ID>" },
            "timestamp": <TIME_WEBHOOK_WAS_TRIGGERED>
            <NOTIFICATION_PAYLOAD>
          }
        ]
      }
    ]
  }
]
```

Identifying the values for the multiple `id`s within a notification can be confusing since the recipient and sender can vary depending on the action that triggered the webhook. The following table shows the action that triggered the webhook and the ID set for each `id` parameter.

| Action that triggers a messaging webhook | `id` | `recipient.id` | `sender.id` |
| --- | --- | --- | --- |
| Your app user **receives** a message from an Instagram user | Your app user's Instagram professional account ID | Your app user's Instagram professional account ID | The Instagram user's Instagram-scoped ID |
| Your app user **sends** a message to an Instagram user | Your app user's Instagram professional account ID | The Instagram user's Instagram-scoped ID | Your app user's Instagram professional account ID |

### `message`

The `message` event notification payloads include the following:

* `message` set to object that contains data about the message that was sent with:
    * `mid` set to the message ID that was sent

The payload might also include the following depending on the contents of the message:

* `text` included when the message contains text
* `is_deleted` set to `true` is included when the Instagram user deleted the message
* `is_echo` set to `true` is included when the message was sent by your app user
* `is_self` set to `true` is included when you send a test message to your Instagram professional account (a public Instagram professional account linked to your app in the Meta App Dashboard)
* `is_unsupported` set to true when the message contains unsupported media
* `quick_reply` set to  an object with `payload` set to the payload your app user wants to see for the quick reply chosen by the Instagram user
* `referral` set to an object that includes information about the CTD ad the Instagram user clicked:
    * `ref` set to the `ref` parameter value of the ad, if set by your app user
    * `ad_id` set to the ad ID
    * `source` set to `ADS`
    * `type` set to `OPEN_THREAD`
    * `ads_context_data` set to an object that contains the ad title, photo url if the Instagram user clicked an image in the ad or video url if the Instagram user clicked a video in the ad
* `reply_to` set to an object with the message ID if the user sends an inline reply
* `reply_to` set to an object with a `story` object that include the URL of the story and the story ID
* `attachments` set to an array that includes one or more objects with supported type and the payload that contains the URL for the media.
(Supported type: `media`, `audio`, `file`, `image` (image, gif, or sticker), `video`, `share`(legacy IG post share, deprecated after Feb 2026), `ig_post`, `story_mention`, `video`, `ig_reel`, `reel`, `story`, `ig_story`)

```html
[
  {
    "object":"instagram",
    "entry":[
      {
        "id":"<YOUR_APP_USERS_INSTAGRAM_USER_ID>",
        "time":<TIME_NOTIFICATION_WAS_SENT>,
        "messaging":[
          {
            "sender":{ "id":"<SENDER_ID>" },
            "recipient":{ "id":"<RECIPIENT_ID>" },
            "timestamp":<TIME_WEBHOOK_WAS_TRIGGERED>,

  // <MESSAGE_WEBHOOK_PAYLOAD>
            "message": {
              "mid": "<MESSAGE_ID>",

 // Optional parameters included for specific message types

              "attachments": [
                {
                  "type":"<ATTACHMENT_MEDIA_TYPE>",
                  "payload":{ "url":"<URL_FOR_THE_MEDIA>" }
                },
                // Can include multiple media objects
              ],

              "is_deleted": true,

              "is_echo": true,

              "is_self": true,  // Sent to self for testing webhooks setup

              "is_unsupported": true,

              "quick_reply": { "payload": "<QUICK_REPLY_OPTION_SELECTED>" },

              "referral": {
                "ref": "<AD_REF_PARAMETER_VALUE_IF_SET>"
                "ad_id": "<AD_ID>",
                "source": "ADS",
                "type": "OPEN_THREAD",
                "ads_context_data": {
                  "ad_title": "<AD_TITLE>",
                  "photo_url": "<IMAGE_URL_THAT_WAS_SELECTED>",
                  "video_url": "<THUMBNAIL_URL_FOR_THE_AD_VIDEO>",<!-- "post_id": ID-OF-THE-POST, -->
                }
              },

              "reply_to":{ "mid":"<MESSAGE_ID>" }

              "reply_to": {
              "story": {
                "url":"<CDN_URL_FOR_THE_STORY>",
                "id":"<STORY_ID>"
              }
            }

              "text": "<MESSAGE_TEXT>",

          }
        }
      ]
    }
  ]
}
```

### `message_reactions`

The `message_reactions` event notification payloads include the following:

* `reaction` set to an object with the following:
    * `mid` set to the message ID
    * `action` set to `react` or `unreact`, if removing a reaction
    * If reacting, `reaction` set to `love` and `emoji` set to `\u{2764}\u{FE0F}`

```json
{
  "object": "instagram",
  "entry": [
    {
      "id": "<YOUR_APP_USERS_INSTAGRAM_USER_ID>",  // ID for your app user's Instagram Professional account
      "time": 1569262486134,
      "messaging": [
        {
          "sender": {
            "id": "<INSTAGRAM_SCOPED_ID>"  // Instagram-scoped ID for the Instagram user who sent the message
          },
          "recipient": {
            "id": "<YOUR_APP_USERS_INSTAGRAM_USER_ID>"  // ID for your app user's Instagram Professional account
          },
          "timestamp": 1569262485349,
          "reaction" :{
            "mid" : "<MESSAGE_ID>",
            "action": "react",          // or unreact if removing the reaction
            "reaction": "love",         // Not included when action is unreact
            "emoji": "\u{2764}\u{FE0F}" // Not included when action is unreact
          }
        }
      ]
    }
  ]
}
```

### `messaging_postbacks`

The `messaging_postbacks` event notification payloads include the following:  

* `postback` set to an object with:
    * `mid` set to the message ID
    * `title` set to the icebreaker or CTA button the Instagram user selected
    * `payload` set to the payload your app user wants to receive for that selection

```json
{
  "object": "instagram",
  "entry": [
    {
      "id": "<INSTAGRAM_SCOPED_ID>",  // ID of your app user's Instagram Professional account
      "time": 1502905976963,
      "messaging": [
        {
          "sender": { "id": "<INSTAGRAM_SCOPED_ID>" },    // Instagram-scoped ID for the Instagram user who sent the message
          "recipient": { "id": "<YOUR_APP_USERS_INSTAGRAM_USER_ID>" },  // ID of your app user's Instagram Professional account
          "timestamp": 1502905976377,
          "postback": {
            "mid":"<MESSAGE_ID>",           // ID for the message sent to your app user
            "title": "<USER_SELECTED_ICEBREAKER_OPTION_OR_CTA_BUTTON>",
            "payload": "<OPTION_OR_BUTTON_PAYLOAD>",  // The payload with the option selected by the Instagram user
          }
        }
      ]
    }
  ]
}
```

### `messaging_referral` {#igme}

The `messaging_referral` event notification payloads include the following:  

* `referral` set to an object with:
    * `ref` set to the value of the `ref` parameter in your `ig.me` link that an Instagram user clicked
    * `source` set to the `ig.me` link that was clicked by an Instagram user
    * `type` set to `OPEN_THREAD` when a message is part of an existing conversation

```json
{
  "object": "instagram",
  "entry": [
    {
      "id": "<INSTAGRAM_SCOPED_ID>",  // ID of your Instagram Professional account
      "time": 1502905976963,
      "messaging": [
        {
          "sender": {
            "id": "<INSTAGRAM_SCOPED_ID>"  // Instagram-scoped ID for the Instagram user who sent the message
          },
          "recipient": {
            "id": "<YOUR_APP_USERS_INSTAGRAM_USER_ID>"  // ID of your Instagram Professional account
          },
          "timestamp": 1502905976377,
          "referral": {
                 "ref": "<IGME_LINK_REF_PARAMETER_VALUE>"
                 "source": "<IGME_SOURCE_LINK>"
                 "type":  "OPEN_THREAD"  // Included when a message is part of an existing conversation
          }
        }
      ]
    }
  ]
}
```

### `messaging_seen`

The `messaging_seen` event notification payloads include the following:

* `read` set to an object with:
    * `mid` set to the message ID that was read

```json
{
   "object":"instagram",
   "entry":[
      {
         "id":"<YOUR_APP_USERS_INSTAGRAM_USER_ID>",     // ID for your app user's Instagram Professional account
         "time":1569262486134,
         "messaging":[
            {
               "sender":{
                  "id":"<INSTAGRAM_SCOPED_ID>"  // Instagram-scoped ID for the Instagram user who sent the message
               },
               "recipient":{
                  "id":"<YOUR_APP_USERS_INSTAGRAM_USER_ID>"  // ID for your app user's Instagram Professional account
               },
               "timestamp":1569262485349,
               "read":{
                  "mid":"<MESSAGE_ID>"  // ID for the message that was seen
               }
            }
         ]
      }
   ]
}
```

### `message_edit`

The `message_edit` event notification payloads include the following:

* `message_edit` set to an object with:
    * `mid` set to the message ID that was read
    * `text` set to the edited text message by user
    * `num_edit` set to the number of times message has been edited

```html
[
  {
    "object":"instagram",
    "entry":[
      {
        "id":"<YOUR_APP_USERS_INSTAGRAM_USER_ID>",
        "time":<TIME_NOTIFICATION_WAS_SENT>,
        "messaging":[
          {
            "sender":{ "id":"<INSTAGRAM_SCOPED_ID>" },
            "recipient":{ "id":"<YOUR_APP_USERS_INSTAGRAM_USER_ID>" },
            "timestamp":<TIME_WEBHOOK_WAS_TRIGGERED>,

         // <MESSAGE_EDIT_PAYLOAD>
            "message_edit": {
              "mid":"<MESSAGE_ID>",
              "text": "<USER_EDITED_MESSAGE>",
              "num_edit": "<NUMBER_OF_TIMES_MESSAGE_IS_EDITED>"
            }
          }
        ]
      }
    ]
  }
]
```

## Facebook Login for Business

```html
[
  {
    "object": "instagram",
    "entry": [
      {
        "id": "<YOUR_APP_USERS_INSTAGRAM_ACCOUNT_ID>",      // ID of your app user's Instagram professional account
        "time": <TIME_META_SENT_THIS_NOTIFICATION>              // Time Meta sent the notification
        "changes": [
          {
            "field": "<WEBHOOK_FIELD>",
            "value": {

              <NOTIFICATION_PAYLOAD>

            }
          }
        ]
      }
    ]
  }
]
```

### `comments`

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


### `live_comments`

#### Facebook Login for Business objects

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
            "field": "live_comments",
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


### `mentions` on media

#### Business Login for Instagram objects

@mention on apps that use Business Login for Instagram are included in the `comments` notifications.

#### Facebook Login for Business objects

```json
[
  {
    "entry": [
      {
        "changes": [
          {
            "field": "mentions",
            "value": {
              "media_id": "17918195224117851"   // ID of the media where your app user's Instagram professional account was mentioned
            }
          }
        ],
        "id": "17841405726653026",   // ID of your app user's Instagram professional account
        "time": 1520622968           // The time Meta sent the notification
      }
    ],
    "object": "instagram"
  }
]
```


### `mentions` on comments

#### Business Login for Instagram objects

@mention on apps that use Business Login for Instagram are included in the `comments` notifications.

#### Facebook Login for Business objects

```json
[
  {
    "entry": [
      {
        "changes": [
          {
            "field": "mentions",
            "value": {
              "comment_id": "17894227972186120",  // ID of the comment in which your app user's Instagram professional account was mentioned
              "media_id": "17918195224117851"     // ID of the media the Instagram user commented on
            }
          }
        ],
        "id": "17841405726653026",   // ID of your app user's Instagram professional account
        "time": 1520622968           // Time the notification was sent
      }
    ],
    "object": "instagram"
  }
]
```

## Insights

### `story_insights`

```json
{
  "object": "instagram",
  "entry": [
    {
      "id": "<INSTAGRAM_SCOPED_ID>",  // ID of your app user's Instagram Professional account
      "time": 1502905976963,
      "messaging": [
        {
          "sender": { "id": "<INSTAGRAM_SCOPED_ID>" },    // Instagram-scoped ID for the Instagram user who sent the message
          "recipient": { "id": "<YOUR_APP_USERS_INSTAGRAM_USER_ID>" },  // ID of your app user's Instagram Professional account
          "timestamp": 1502905976377,
          "postback": {
            "mid":"<MESSAGE_ID>",           // ID for the message sent to your app user
            "title": "<USER_SELECTED_ICEBREAKER_OPTION_OR_CTA_BUTTON>",
            "payload": "<OPTION_OR_BUTTON_PAYLOAD>",  // The payload with the option selected by the Instagram user
          }
        }
      ]
    }
  ]
}
```


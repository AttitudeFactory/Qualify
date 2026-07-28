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
  &#123;
    &quot;object&quot;:&quot;instagram&quot;,
    &quot;entry&quot;:[
      &#123;
        &quot;id&quot;:&quot;&lt;YOUR_APP_USERS_INSTAGRAM_ACCOUNT_ID&gt;&quot;,
        &quot;time&quot;:&lt;TIME_META_SENT_THIS_NOTIFICATION&gt;,
        &lt;NOTIFICATION_PAYLOAD&gt;
      &#125;
    ]
  &#125;
]
```

### Comments payload

The comment event notification payloads include the following:

* `field` set to `comments` or `live_comments`
* `value` set to an array that contains:
    * The comment ID
    * The Instagram-scoped user ID of the Instagram user who commented on your app user&#039;s media
    * The username of the Instagram user who commented on your app user&#039;s media
    * Any text that was included in the comment
    * The media&#039;s ID
    * Where the media was located, in an ad, feed, story, or reel

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

### Messaging payload

All messaging webhook notifications included the following:

* `object` set to `instagram`
* `entry` set to an array containing:
    * The Instagram professional account ID of your app user who is in the conversation
    * The time Meta sent the notification
    * The sender&#039;s ID
    * The recipient&#039;s ID
    * The time when the message was sent
    * The notification payload for the specific webhook that was triggered

```html
[
  &#123;
    &quot;object&quot;:&quot;instagram&quot;,
    &quot;entry&quot;:[
      &#123;
        &quot;id&quot;: &quot;&lt;YOUR_APP_USERS_INSTAGRAM_ACCOUNT_ID&gt;&quot;,
        &quot;time&quot;: &lt;TIME_META_SENT_NOTIFICATION&gt;,
        &quot;messaging&quot;: [
          &#123;
            &quot;sender&quot;: &#123; &quot;id&quot;: &quot;&lt;SENDER_ID&gt;&quot; &#125;,
            &quot;recipient&quot;: &#123; &quot;id&quot;: &quot;&lt;RECIPIENT_ID&gt;&quot; &#125;,
            &quot;timestamp&quot;: &lt;TIME_WEBHOOK_WAS_TRIGGERED&gt;
            &lt;NOTIFICATION_PAYLOAD&gt;
          &#125;
        ]
      &#125;
    ]
  &#125;
]
```

Identifying the values for the multiple `id`s within a notification can be confusing since the recipient and sender can vary depending on the action that triggered the webhook. The following table shows the action that triggered the webhook and the ID set for each `id` parameter.

| Action that triggers a messaging webhook | `id` | `recipient.id` | `sender.id` |
| --- | --- | --- | --- |
| Your app user **receives** a message from an Instagram user | Your app user&#039;s Instagram professional account ID | Your app user&#039;s Instagram professional account ID | The Instagram user&#039;s Instagram-scoped ID |
| Your app user **sends** a message to an Instagram user | Your app user&#039;s Instagram professional account ID | The Instagram user&#039;s Instagram-scoped ID | Your app user&#039;s Instagram professional account ID |

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
  &#123;
    &quot;object&quot;:&quot;instagram&quot;,
    &quot;entry&quot;:[
      &#123;
        &quot;id&quot;:&quot;&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;&quot;,
        &quot;time&quot;:&lt;TIME_NOTIFICATION_WAS_SENT&gt;,
        &quot;messaging&quot;:[
          &#123;
            &quot;sender&quot;:&#123; &quot;id&quot;:&quot;&lt;SENDER_ID&gt;&quot; &#125;,
            &quot;recipient&quot;:&#123; &quot;id&quot;:&quot;&lt;RECIPIENT_ID&gt;&quot; &#125;,
            &quot;timestamp&quot;:&lt;TIME_WEBHOOK_WAS_TRIGGERED&gt;,

  // &lt;MESSAGE_WEBHOOK_PAYLOAD&gt;
            &quot;message&quot;: &#123;
              &quot;mid&quot;: &quot;&lt;MESSAGE_ID&gt;&quot;,

 // Optional parameters included for specific message types

              &quot;attachments&quot;: [
                &#123;
                  &quot;type&quot;:&quot;&lt;ATTACHMENT_MEDIA_TYPE&gt;&quot;,
                  &quot;payload&quot;:&#123; &quot;url&quot;:&quot;&lt;URL_FOR_THE_MEDIA&gt;&quot; &#125;
                &#125;,
                // Can include multiple media objects
              ],

              &quot;is_deleted&quot;: true,

              &quot;is_echo&quot;: true,

              &quot;is_self&quot;: true,  // Sent to self for testing webhooks setup

              &quot;is_unsupported&quot;: true,

              &quot;quick_reply&quot;: &#123; &quot;payload&quot;: &quot;&lt;QUICK_REPLY_OPTION_SELECTED&gt;&quot; &#125;,

              &quot;referral&quot;: &#123;
                &quot;ref&quot;: &quot;&lt;AD_REF_PARAMETER_VALUE_IF_SET&gt;&quot;
                &quot;ad_id&quot;: &quot;&lt;AD_ID&gt;&quot;,
                &quot;source&quot;: &quot;ADS&quot;,
                &quot;type&quot;: &quot;OPEN_THREAD&quot;,
                &quot;ads_context_data&quot;: &#123;
                  &quot;ad_title&quot;: &quot;&lt;AD_TITLE&gt;&quot;,
                  &quot;photo_url&quot;: &quot;&lt;IMAGE_URL_THAT_WAS_SELECTED&gt;&quot;,
                  &quot;video_url&quot;: &quot;&lt;THUMBNAIL_URL_FOR_THE_AD_VIDEO&gt;&quot;,&lt;!-- &quot;post_id&quot;: ID-OF-THE-POST, --&gt;
                &#125;
              &#125;,

              &quot;reply_to&quot;:&#123; &quot;mid&quot;:&quot;&lt;MESSAGE_ID&gt;&quot; &#125;

              &quot;reply_to&quot;: &#123;
              &quot;story&quot;: &#123;
                &quot;url&quot;:&quot;&lt;CDN_URL_FOR_THE_STORY&gt;&quot;,
                &quot;id&quot;:&quot;&lt;STORY_ID&gt;&quot;
              &#125;
            &#125;

              &quot;text&quot;: &quot;&lt;MESSAGE_TEXT&gt;&quot;,

          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

### `message_reactions`

The `message_reactions` event notification payloads include the following:

* `reaction` set to an object with the following:
    * `mid` set to the message ID
    * `action` set to `react` or `unreact`, if removing a reaction
    * If reacting, `reaction` set to `love` and `emoji` set to `\u&#123;2764&#125;\u&#123;FE0F&#125;`

```json
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;&quot;,  // ID for your app user&#039;s Instagram Professional account
      &quot;time&quot;: 1569262486134,
      &quot;messaging&quot;: [
        &#123;
          &quot;sender&quot;: &#123;
            &quot;id&quot;: &quot;&lt;INSTAGRAM_SCOPED_ID&gt;&quot;  // Instagram-scoped ID for the Instagram user who sent the message
          &#125;,
          &quot;recipient&quot;: &#123;
            &quot;id&quot;: &quot;&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;&quot;  // ID for your app user&#039;s Instagram Professional account
          &#125;,
          &quot;timestamp&quot;: 1569262485349,
          &quot;reaction&quot; :&#123;
            &quot;mid&quot; : &quot;&lt;MESSAGE_ID&gt;&quot;,
            &quot;action&quot;: &quot;react&quot;,          // or unreact if removing the reaction
            &quot;reaction&quot;: &quot;love&quot;,         // Not included when action is unreact
            &quot;emoji&quot;: &quot;\u&#123;2764&#125;\u&#123;FE0F&#125;&quot; // Not included when action is unreact
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

### `messaging_postbacks`

The `messaging_postbacks` event notification payloads include the following:  

* `postback` set to an object with:
    * `mid` set to the message ID
    * `title` set to the icebreaker or CTA button the Instagram user selected
    * `payload` set to the payload your app user wants to receive for that selection

```json
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;&lt;INSTAGRAM_SCOPED_ID&gt;&quot;,  // ID of your app user&#039;s Instagram Professional account
      &quot;time&quot;: 1502905976963,
      &quot;messaging&quot;: [
        &#123;
          &quot;sender&quot;: &#123; &quot;id&quot;: &quot;&lt;INSTAGRAM_SCOPED_ID&gt;&quot; &#125;,    // Instagram-scoped ID for the Instagram user who sent the message
          &quot;recipient&quot;: &#123; &quot;id&quot;: &quot;&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;&quot; &#125;,  // ID of your app user&#039;s Instagram Professional account
          &quot;timestamp&quot;: 1502905976377,
          &quot;postback&quot;: &#123;
            &quot;mid&quot;:&quot;&lt;MESSAGE_ID&gt;&quot;,           // ID for the message sent to your app user
            &quot;title&quot;: &quot;&lt;USER_SELECTED_ICEBREAKER_OPTION_OR_CTA_BUTTON&gt;&quot;,
            &quot;payload&quot;: &quot;&lt;OPTION_OR_BUTTON_PAYLOAD&gt;&quot;,  // The payload with the option selected by the Instagram user
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

### `messaging_referral` &#123;#igme&#125;

The `messaging_referral` event notification payloads include the following:  

* `referral` set to an object with:
    * `ref` set to the value of the `ref` parameter in your `ig.me` link that an Instagram user clicked
    * `source` set to the `ig.me` link that was clicked by an Instagram user
    * `type` set to `OPEN_THREAD` when a message is part of an existing conversation

```json
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;&lt;INSTAGRAM_SCOPED_ID&gt;&quot;,  // ID of your Instagram Professional account
      &quot;time&quot;: 1502905976963,
      &quot;messaging&quot;: [
        &#123;
          &quot;sender&quot;: &#123;
            &quot;id&quot;: &quot;&lt;INSTAGRAM_SCOPED_ID&gt;&quot;  // Instagram-scoped ID for the Instagram user who sent the message
          &#125;,
          &quot;recipient&quot;: &#123;
            &quot;id&quot;: &quot;&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;&quot;  // ID of your Instagram Professional account
          &#125;,
          &quot;timestamp&quot;: 1502905976377,
          &quot;referral&quot;: &#123;
                 &quot;ref&quot;: &quot;&lt;IGME_LINK_REF_PARAMETER_VALUE&gt;&quot;
                 &quot;source&quot;: &quot;&lt;IGME_SOURCE_LINK&gt;&quot;
                 &quot;type&quot;:  &quot;OPEN_THREAD&quot;  // Included when a message is part of an existing conversation
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

### `messaging_seen`

The `messaging_seen` event notification payloads include the following:

* `read` set to an object with:
    * `mid` set to the message ID that was read

```json
&#123;
   &quot;object&quot;:&quot;instagram&quot;,
   &quot;entry&quot;:[
      &#123;
         &quot;id&quot;:&quot;&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;&quot;,     // ID for your app user&#039;s Instagram Professional account
         &quot;time&quot;:1569262486134,
         &quot;messaging&quot;:[
            &#123;
               &quot;sender&quot;:&#123;
                  &quot;id&quot;:&quot;&lt;INSTAGRAM_SCOPED_ID&gt;&quot;  // Instagram-scoped ID for the Instagram user who sent the message
               &#125;,
               &quot;recipient&quot;:&#123;
                  &quot;id&quot;:&quot;&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;&quot;  // ID for your app user&#039;s Instagram Professional account
               &#125;,
               &quot;timestamp&quot;:1569262485349,
               &quot;read&quot;:&#123;
                  &quot;mid&quot;:&quot;&lt;MESSAGE_ID&gt;&quot;  // ID for the message that was seen
               &#125;
            &#125;
         ]
      &#125;
   ]
&#125;
```

### `message_edit`

The `message_edit` event notification payloads include the following:

* `message_edit` set to an object with:
    * `mid` set to the message ID that was read
    * `text` set to the edited text message by user
    * `num_edit` set to the number of times message has been edited

```html
[
  &#123;
    &quot;object&quot;:&quot;instagram&quot;,
    &quot;entry&quot;:[
      &#123;
        &quot;id&quot;:&quot;&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;&quot;,
        &quot;time&quot;:&lt;TIME_NOTIFICATION_WAS_SENT&gt;,
        &quot;messaging&quot;:[
          &#123;
            &quot;sender&quot;:&#123; &quot;id&quot;:&quot;&lt;INSTAGRAM_SCOPED_ID&gt;&quot; &#125;,
            &quot;recipient&quot;:&#123; &quot;id&quot;:&quot;&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;&quot; &#125;,
            &quot;timestamp&quot;:&lt;TIME_WEBHOOK_WAS_TRIGGERED&gt;,

         // &lt;MESSAGE_EDIT_PAYLOAD&gt;
            &quot;message_edit&quot;: &#123;
              &quot;mid&quot;:&quot;&lt;MESSAGE_ID&gt;&quot;,
              &quot;text&quot;: &quot;&lt;USER_EDITED_MESSAGE&gt;&quot;,
              &quot;num_edit&quot;: &quot;&lt;NUMBER_OF_TIMES_MESSAGE_IS_EDITED&gt;&quot;
            &#125;
          &#125;
        ]
      &#125;
    ]
  &#125;
]
```

## Facebook Login for Business

```html
[
  &#123;
    &quot;object&quot;: &quot;instagram&quot;,
    &quot;entry&quot;: [
      &#123;
        &quot;id&quot;: &quot;&lt;YOUR_APP_USERS_INSTAGRAM_ACCOUNT_ID&gt;&quot;,      // ID of your app user&#039;s Instagram professional account
        &quot;time&quot;: &lt;TIME_META_SENT_THIS_NOTIFICATION&gt;              // Time Meta sent the notification
        &quot;changes&quot;: [
          &#123;
            &quot;field&quot;: &quot;&lt;WEBHOOK_FIELD&gt;&quot;,
            &quot;value&quot;: &#123;

              &lt;NOTIFICATION_PAYLOAD&gt;

            &#125;
          &#125;
        ]
      &#125;
    ]
  &#125;
]
```

### `comments`

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


### `live_comments`

#### Facebook Login for Business objects

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
            &quot;field&quot;: &quot;live_comments&quot;,
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


### `mentions` on media

#### Business Login for Instagram objects

&#064;mention on apps that use Business Login for Instagram are included in the `comments` notifications.

#### Facebook Login for Business objects

```json
[
  &#123;
    &quot;entry&quot;: [
      &#123;
        &quot;changes&quot;: [
          &#123;
            &quot;field&quot;: &quot;mentions&quot;,
            &quot;value&quot;: &#123;
              &quot;media_id&quot;: &quot;17918195224117851&quot;   // ID of the media where your app user&#039;s Instagram professional account was mentioned
            &#125;
          &#125;
        ],
        &quot;id&quot;: &quot;17841405726653026&quot;,   // ID of your app user&#039;s Instagram professional account
        &quot;time&quot;: 1520622968           // The time Meta sent the notification
      &#125;
    ],
    &quot;object&quot;: &quot;instagram&quot;
  &#125;
]
```


### `mentions` on comments

#### Business Login for Instagram objects

&#064;mention on apps that use Business Login for Instagram are included in the `comments` notifications.

#### Facebook Login for Business objects

```json
[
  &#123;
    &quot;entry&quot;: [
      &#123;
        &quot;changes&quot;: [
          &#123;
            &quot;field&quot;: &quot;mentions&quot;,
            &quot;value&quot;: &#123;
              &quot;comment_id&quot;: &quot;17894227972186120&quot;,  // ID of the comment in which your app user&#039;s Instagram professional account was mentioned
              &quot;media_id&quot;: &quot;17918195224117851&quot;     // ID of the media the Instagram user commented on
            &#125;
          &#125;
        ],
        &quot;id&quot;: &quot;17841405726653026&quot;,   // ID of your app user&#039;s Instagram professional account
        &quot;time&quot;: 1520622968           // Time the notification was sent
      &#125;
    ],
    &quot;object&quot;: &quot;instagram&quot;
  &#125;
]
```

## Insights

### `story_insights`

```json
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;&lt;INSTAGRAM_SCOPED_ID&gt;&quot;,  // ID of your app user&#039;s Instagram Professional account
      &quot;time&quot;: 1502905976963,
      &quot;messaging&quot;: [
        &#123;
          &quot;sender&quot;: &#123; &quot;id&quot;: &quot;&lt;INSTAGRAM_SCOPED_ID&gt;&quot; &#125;,    // Instagram-scoped ID for the Instagram user who sent the message
          &quot;recipient&quot;: &#123; &quot;id&quot;: &quot;&lt;YOUR_APP_USERS_INSTAGRAM_USER_ID&gt;&quot; &#125;,  // ID of your app user&#039;s Instagram Professional account
          &quot;timestamp&quot;: 1502905976377,
          &quot;postback&quot;: &#123;
            &quot;mid&quot;:&quot;&lt;MESSAGE_ID&gt;&quot;,           // ID for the message sent to your app user
            &quot;title&quot;: &quot;&lt;USER_SELECTED_ICEBREAKER_OPTION_OR_CTA_BUTTON&gt;&quot;,
            &quot;payload&quot;: &quot;&lt;OPTION_OR_BUTTON_PAYLOAD&gt;&quot;,  // The payload with the option selected by the Instagram user
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```


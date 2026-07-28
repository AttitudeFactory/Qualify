# Webhooks for Instagram Messaging



Webhooks allows you to receive real-time HTTP notifications of changes to specific objects in the Meta social graph. For example, Meta can send you a notification when a customer sends your Instagram Professional account a message. Webhooks notifications allow you to track messaging changes and avoid rate limits that would occur if you were querying the Messenger Platform endpoints to track changes.

### Requirements &#123;#requirements&#125;

You will need to implement the following requirements to receive Webhooks notifications for Instagram Messaging.

* The `instagram_basic`, `instagram_manage_messages`, and `pages_manage_metadata` permissions
* To get webhooks notification that include data owned or managed by people who do not have a role on your app, your app must have been approved in App Review. Your app user must have granted your app the prerequisite permissions.
    * If your app has not been approved, pending, or review is not needed, Webhooks will only be sent if the person using your app has a role on the app. You can only access data you own or administer.
* Your app must be published, regardless of app review status, to receive webhooks.

**Note:** You will need to subscribe all messaging apps for your business to the messaging webhooks.

Learn more about
[access levels](https://developers.facebook.com/docs/graph-api/overview/access-levels),
[app modes](https://developers.facebook.com/docs/development/build-and-test/app-modes)
and
[app roles.](https://developers.facebook.com/docs/development/build-and-test/app-roles)

### Limitations

- When a customer reacts to or forwards an image from a carousel in an Instagram Post, the notification will include the first image in the carousel which may not be the image the customer reacted to or forwarded.

- Only the URL for the shared media or post is included in the notification when a customer sends a message with a share.

- Messages with gifs and stickers are not supported. If a person sends a message with a gif or sticker a webhook will not be triggered and a webhook notification will not be sent.

- [Disappearing media](https://help.instagram.com/1310346208996329/?cms_platform=iphone-app) (view once, allow replay) is not supported on Instagram media webhooks.

## Webhook events &#123;#webhook-events&#125;

| Webhook Field | Description |
| --- | --- |
| `message_reactions` | Meta sends a notification when a customer reacts or unreacts to a message&lt;br&gt;&lt;br&gt;Graph API v12.0 and later supports `angry`, `sad`, `wow`, `love`,  `like`, `laugh`, and `other` reactions. |
| `messages` | A notification is sent when a customer sends your business:&lt;br&gt;&lt;br&gt;* a message with text or media (image/video/file/audio)&lt;br&gt;* a share (media/post shares)&lt;br&gt;* a story reply or mention. Only story mentions will trigger a webhook. Tagging on regular posts will not trigger a webhook. Story Replies webhook currently doesn&#039;t support GIF or sticker.&lt;br&gt;* an inline message reply or sticker&lt;br&gt;* a quick reply or Icebreaker option or Generic Template button is selected&lt;br&gt;* a customer deletes a message&lt;br&gt;* a message from a customer is unsupported&lt;br&gt;* a customer sends a message from an Instagram Shops product detail page&lt;br&gt;* a customer clicks an ad that goes to an Instagram Messaging conversation [(Click To Direct, CTD)](https://www.facebook.com/business/help/198088077975174)&lt;br&gt;&lt;br&gt;A notification is also sent when your business sends a message to a customer. A notification will not be sent when your business reacts or unreacts to a customer message.&lt;br&gt;&lt;br&gt;This callback will occur when a message has been sent by your Instagram account. `is_echo` flag will be present to indicate that the message is sent from the Instagram account itself. `message_reactions` event will not have an echo webhook delivered |
| `messaging_postbacks` | A notification is sent when a customer clicked an Icebreaker option or Generic Template button&lt;br&gt;&lt;br&gt;Requires v8.0 or later. Requires v11.0 or later for inclusion of the `mid` field. |
| `messaging_seen` | A notification is sent when a message has been read by the recipient |
| `messaging_referral` | A notification is sent when an `ig.me` link with a referral parameter is clicked by a customer in an existing conversation |
| `standby` | When the messaging flow has multiple apps, a notification is sent when a customer sends your business a message but the app is not in control of the conversation at the time the message was sent. |

## Example notifications

The following are examples for the types of webhooks notifications you can receive.

### Messages

```json
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;IGID&quot;,  // ID of your Instagram Professional account
      &quot;time&quot;: 1569262486134,
      &quot;messaging&quot;: [
        &#123;
          &quot;sender&quot;: &#123; &quot;id&quot;: &quot;IGSID&quot; &#125;,    // Instagram-scoped ID for the customer who sent the message
          &quot;recipient&quot;: &#123; &quot;id&quot;: &quot;IGID&quot; &#125;,  // ID of your Instagram Professional account
          &quot;timestamp&quot;: 1569262485349,
          &quot;message&quot;: &#123;
            &quot;mid&quot;: &quot;MESSAGE-ID&quot;,   // ID of the message sent to your business

            &quot;text&quot;: &quot;MESSAGE-TEXT&quot;     // Included when a customer sends a message containing text

            &quot;attachments&quot;: [           // Included when a customer sends multiple media attachments or a URL for a story mention or share
              &#123;
                &quot;type&quot;:&quot;image&quot;,             // Can be audio, file, image (image or sticker), share, story_mention, video, ig_reel or reel
                &quot;payload&quot;:&#123; &quot;url&quot;:&quot;LINK&quot; &#125;
              &#125;,
              &#123;
                &quot;type&quot;:&quot;video&quot;,
                &quot;payload&quot;:&#123; &quot;url&quot;:&quot;LINK&quot; &#125;
              &#125;
            ]

            &quot;is_deleted&quot;: true         // Included when a customer deletes a message

            &quot;is_echo&quot;: true            // Included when your business sends a message to the customer

            &quot;is_unsupported&quot;: true,    // Included when a customer sends a message with unsupported media

            &quot;quick_reply&quot;: &#123;           // Included when a customer clicks a quick reply
              &quot;payload&quot;: &quot;CUSTOMER-RESPONSE-PAYLOAD&quot;   // The payload with the option selected by the customer
            &#125;,

            &quot;referral&quot;: &#123;              // Included when a customer clicks an Instagram Shop product
              &quot;product&quot;: &#123;
                &quot;id&quot;: &quot;PRODUCT-ID&quot;
            &#125;

            &quot;referral&quot;: &#123;                   // Included when a customer clicks an CTD ad
              &quot;ref&quot;: &quot;REF-DATA-IN-AD-IF-SPECIFIED&quot;
              &quot;ad_id&quot;: AD-ID,
              &quot;source&quot;: &quot;ADS&quot;,
              &quot;type&quot;: &quot;OPEN_THREAD&quot;,
              &quot;ads_context_data&quot;: &#123;
                &quot;ad_title&quot;: TITLE-FOR-THE-AD,
                &quot;photo_url&quot;: IMAGE-URL-THAT-WAS-CLICKED,
                &quot;video_url&quot;: THUMBNAIL-URL-FOR-THE-AD-VIDEO,&lt;!-- &quot;post_id&quot;: ID-OF-THE-POST, --&gt;
              &#125;
            &#125;

            &quot;reply_to&quot;:&#123;               // Included when a customer sends an inline reply
              &quot;mid&quot;:&quot;MESSAGE-ID&quot;
            &#125;

            &quot;reply_to&quot;: &#123;               // Included when a customer replies to a story
              &quot;story&quot;: &#123;
                &quot;url&quot;:&quot;CDN-URL&quot;,
                &quot;id&quot;:&quot;STORY-ID&quot;
              &#125;
            &#125;
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

### Message reactions

```json
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;IGID&quot;,  // ID for your Instagram Professional account
      &quot;time&quot;: 1569262486134,
      &quot;messaging&quot;: [
        &#123;
          &quot;sender&quot;: &#123;
            &quot;id&quot;: &quot;IGSID&quot;  // Instagram-scoped ID for the customer who sent the message
          &#125;,
          &quot;recipient&quot;: &#123;
            &quot;id&quot;: &quot;IGID&quot;  // ID for your Instagram Professional account
          &#125;,
          &quot;timestamp&quot;: 1569262485349,
          &quot;reaction&quot; :&#123;
            &quot;mid&quot; : &quot;MESSAGE-ID&quot;,
            &quot;action&quot;: &quot;react&quot;,    // or unreact
            &quot;reaction&quot;: &quot;love&quot;, // optional, to unreact if there is no reaction field
            &quot;emoji&quot;: &quot;\u&#123;2764&#125;\u&#123;FE0F&#125;&quot; // optional, to unreact if there is no emoji field
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

### Messaging postbacks

```json
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;IGSID&quot;,  // ID of your Instagram Professional account
      &quot;time&quot;: 1502905976963,
      &quot;messaging&quot;: [
        &#123;
          &quot;sender&quot;: &#123; &quot;id&quot;: &quot;IGSID&quot; &#125;,    // Instagram-scoped ID for the customer who sent the message
          &quot;recipient&quot;: &#123; &quot;id&quot;: &quot;IGID&quot; &#125;,  // ID of your Instagram Professional account
          &quot;timestamp&quot;: 1502905976377,
          &quot;postback&quot;: &#123;
            &quot;mid&quot;:&quot;MESSAGE-ID&quot;,           // ID for the message sent to your business
            &quot;title&quot;: &quot;SELECTED-ICEBREAKER-REPLY-OR-CTA-BUTTON&quot;,
            &quot;payload&quot;: &quot;CUSTOMER-RESPONSE-PAYLOAD&quot;,  // The payload with the option selected by the customer
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

### Messaging referral &#123;#igme&#125;

```json
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;IGSID&quot;,  // ID of your Instagram Professional account
      &quot;time&quot;: 1502905976963,
      &quot;messaging&quot;: [
        &#123;
          &quot;sender&quot;: &#123;
            &quot;id&quot;: &quot;IGSID&quot;  // Instagram-scoped ID for the customer who sent the message
          &#125;,
          &quot;recipient&quot;: &#123;
            &quot;id&quot;: &quot;IGID&quot;  // ID of your Instagram Professional account
          &#125;,
          &quot;timestamp&quot;: 1502905976377,
          &quot;referral&quot;: &#123;
                 &quot;ref&quot;: &quot;INFORMATION-INCLUDED-IN-REF-PARAMETER-OF-IGME-LINK&quot;
                 &quot;source&quot;: &quot;IGME-SOURCE-LINK&quot;
                 &quot;type&quot;:  &quot;OPEN_THREAD&quot;  // Only supported for existing conversations
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

### Messaging seen

```json
&#123;
   &quot;object&quot;:&quot;instagram&quot;,
   &quot;entry&quot;:[
      &#123;
         &quot;id&quot;:&quot;IGID&quot;,  // ID for your Instagram Professional account
         &quot;time&quot;:1569262486134,
         &quot;messaging&quot;:[
            &#123;
               &quot;sender&quot;:&#123;
                  &quot;id&quot;:&quot;IGSID&quot;  // Instagram-scoped ID for the customer who sent the message
               &#125;,
               &quot;recipient&quot;:&#123;
                  &quot;id&quot;:&quot;IGID&quot;  // ID for your Instagram Professional account
               &#125;,
               &quot;timestamp&quot;:1569262485349,
               &quot;read&quot;:&#123;
                  &quot;mid&quot;:&quot;MESSAGE-ID&quot;
               &#125;
            &#125;
         ]
      &#125;
   ]
&#125;
```

### Disappearing media

```json
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;IGID&quot;,  // ID of your Instagram Professional account
      &quot;time&quot;: 1569262486134,
      &quot;messaging&quot;: [
        &#123;
          &quot;sender&quot;: &#123; &quot;id&quot;: &quot;IGSID&quot; &#125;,    // Instagram-scoped ID for the customer who sent the message
          &quot;recipient&quot;: &#123; &quot;id&quot;: &quot;IGID&quot; &#125;,  // ID of your Instagram Professional account
          &quot;timestamp&quot;: 1569262485349,
          &quot;message&quot;: &#123;
            &quot;mid&quot;: &quot;MESSAGE-ID&quot;,   // ID of the message sent to your business
            &quot;attachments&quot;: [
              &#123;
                &quot;type&quot;:&quot;ephemeral&quot; // no URL is included for ephemeral media
              &#125;
            ]
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

## See also

- [Messenger Handover Protocol](https://developers.facebook.com/docs/messenger-platform/handover-protocol)  – If you have more than one app handling messages, for example, one app handles automated responses and one app handles escalations to a human agent, then you will need to implement the Handover Protocol to pass the conversation from one app to another.

- [Click To Direct, CTD](https://www.facebook.com/business/help/198088077975174)  – Visit the Business Help Center to learn more about creating ads that click to Instagram Direct.

### Developer Support

* Use the  [Meta Status tool](https://metastatus.com) to check for the status and outages of Meta business products.
* Use the [Meta Developer Support tool](https://developers.facebook.com/support) to report bugs and view reported bugs, get help with Ads or Business Manager, and more.


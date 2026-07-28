# Quick Replies



A Quick Reply is a preset button that allows a user to quickly reply to a prompt or question within a conversation. When a quick reply is tapped, the buttons are dismissed, and the title of the tapped button is posted to the conversation as a message. A messages event will be sent to your webhook that contains the button title and an optional payload.

You can have a maximum of 13 buttons that may contain:

* Plain text of up to 20 characters (will be truncated if more than 20)
* Phone number of the recipient, pre-filled with the phone number from the user&#039;s profile information
* Email of the recipient, pre-filled with the email from the user&#039;s profile information

If you include a phone number or email as a quick reply option, the quick reply button is pre-filled with the phone number or email from the user&#039;s profile information. If the user has not supplied a phone number or email in their profile, this quick reply option is not shown.

An Instagram webhook event notification is sent to your webhook server. The webhook notification contains the button title and an optional payload you set that can include information about the button selected.

## Before you start

This guide assumes you have set up your webhooks server to receive notifications and subscribed your app to Instagram `messages` and `messaging_postbacks` events.

You will need:

* The ID for the Instagram Professional account (`IG_ID`)
* The Instagram-scoped ID (`IGSID`) for the person to whom you are sending the message

#### Host URL
`https://graph.instagram.com`

### Limitations

This feature is currently not available on desktop.

* A maximum of 13 quick replies are supported  
* A quick reply can contain up to 20 characters before it is truncated
* Only plain text is supported except for pre-filled email or phone number quick replies
* If no email or phone number are supplied by the user, these quick replies are not displayed
* User information, such as email or phone number, is only sent to your app if the user selects an email or phone number quick reply button

## Send Quick Replies

To send a set of quick replies, send a `POST` request to the `/&lt;IG_ID&gt;/messages` endpoint with the following properties:

* `recipient.id` set to the Instagram-scoped ID for the person receiving the quick replies.
* `message` object with:
    * `text` set to the text that will prompt a person to click a quick reply
    * `quick_replies` array containing an object for each quick reply:
        * `content_type` set to
        * `title` set to the quick reply text
        * `payload` set to the content you would like to receive about the quick reply in the webhook notification

#### Sample Request

_Formatted for readability._

```html
curl -X POST -H &quot;Content-Type: application/json&quot; -d &#039;&#123;
  &quot;recipient&quot;:&#123;
    &quot;id&quot;:&quot;&lt;IGSID&gt;&quot;
  &#125;,
  &quot;message&quot;:&#123;
    &quot;text&quot;: &quot;&lt;THE_PROMPT_OR_QUESTION&gt;&quot;,
    &quot;quick_replies&quot;:[
      &#123;
        &quot;content_type&quot;:&quot;text&quot;,
        &quot;title&quot;:&quot;&lt;BUTTON_OPTION_TEXT1&gt;&quot;,
        &quot;payload&quot;:&quot;&lt;POSTBACK_PAYLOAD1&quot;
      &#125;,&#123;
        &quot;content_type&quot;:&quot;text&quot;,
        &quot;title&quot;:&quot;&lt;BUTTON_OPTION_TEXT2&gt;&quot;,
        &quot;payload&quot;:&quot;&lt;POSTBACK_PAYLOAD2&quot;
      &#125;,&#123;
        &quot;content_type&quot;:&quot;user_phone_number&quot;,
        &quot;title&quot;:&quot;&lt;PREFILLED_PHONE_NUMBER_IF_AVAILABLE&gt;&quot;,
        &quot;payload&quot;:&quot;&lt;POSTBACK_PHONE_NUMBER_PAYLOAD&gt;&quot;
      &#125;,&#123;
        &quot;content_type&quot;:&quot;user_email&quot;,
        &quot;title&quot;:&quot;&lt;PREFILLED_EMAIL_IF_AVAILABLE&gt;&quot;,
        &quot;payload&quot;:&quot;&lt;POSTBACK_EMAIL_PAYLOAD&gt;&quot;
      &#125;
    ]
  &#125;
&#125;&#039; &quot;https://graph.instagram.com/&lt;API_VERSION&gt;/me/messages?access_token=&lt;INSTAGRAM_ACCESS_TOKEN&gt;&quot;
```

## Webhook Event

When a quick reply is selected, a notification will be sent to your webhook server that contains the following:

* The ID for the Instagram Professional account that owns the quick replies
* The time the notification was sent
* The Instagram-scoped ID for the person who sent the quick reply
* The payload for the specific quick reply that was selected
* The ID for the message
* The text, email, or phone number of the selected quick reply

**Note:** If a user has not supplied their email or phone number in their profile information,  

#### Sample Notification

```json
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;&lt;IGID&gt;&quot;,
      &quot;time&quot;: 1502905976963,
      &quot;messaging&quot;: [
        &#123;
          &quot;sender&quot;: &#123;
            &quot;id&quot;: &quot;&lt;IGSID&gt;&quot;
          &#125;,
          &quot;recipient&quot;: &#123;
            &quot;id&quot;: &quot;&lt;IGID&gt;&quot;
          &#125;,
          &quot;timestamp&quot;: 1502905976377,
          &quot;message&quot;: &#123;
            &quot;quick_reply&quot;: &#123;
              &quot;payload&quot;: &quot;&lt;POSTBACK_OF_BUTTON_SELECTED&gt;&quot;
            &#125;,
            &quot;mid&quot;: &quot;&lt;MESSAGE_ID&gt;&quot;,
            &quot;text&quot;: &quot;&lt;PHONE_NUMBER_EMAIL_OR_TEXT_OF_BUTTON_SELECTED&gt;&quot;
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

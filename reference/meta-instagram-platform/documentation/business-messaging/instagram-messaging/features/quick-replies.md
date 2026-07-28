# Quick Replies



Quick replies provide a way to present a set of buttons in-conversation for users to reply with. A maximum of 13 quick replies are supported and each quick reply allows up to 20 characters before being truncated. Quick replies only support plain text.

When a quick reply is tapped, Instagram dismisses the buttons and posts the tapped button&#039;s title to the conversation as a message. Instagram then sends a messages event to your webhook that contains the button title and an optional payload.

**Note:** This feature is currently not available on desktop.

## Sending quick replies

```curl
curl -X POST -H &quot;Content-Type: application/json&quot; -d &#039;&#123;
  &quot;recipient&quot;:&#123;
    &quot;id&quot;:&quot;&lt;IGSID&gt;&quot;
  &#125;,
  &quot;messaging_type&quot;: &quot;RESPONSE&quot;,
  &quot;message&quot;:&#123;
    &quot;text&quot;: &quot;&lt;SOME_TEXT&gt;&quot;,
    &quot;quick_replies&quot;:[
      &#123;
        &quot;content_type&quot;:&quot;text&quot;,
        &quot;title&quot;:&quot;&lt;TITLE_1&gt;&quot;,
        &quot;payload&quot;:&quot;&lt;POSTBACK_PAYLOAD_1&gt;&quot;
      &#125;,
      &#123;
        &quot;content_type&quot;:&quot;text&quot;,
        &quot;title&quot;:&quot;&lt;TITLE_2&gt;&quot;,
        &quot;payload&quot;:&quot;&lt;POSTBACK_PAYLOAD_2&gt;&quot;
      &#125;
    ]
  &#125;
&#125;&#039; &quot;https://graph.facebook.com/&lt;API_VERSON&gt;/me/messages?access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot;
```

## Webhook event

When a quick reply is tapped, Instagram sends a text message to your webhook.

The text property of the event will correspond to the title of the quick reply. The message object will also contain a field named `quick_reply` containing the payload data on the quick reply.

```curl
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
              &quot;payload&quot;: &quot;&lt;PAYLOAD&gt;&quot;
            &#125;,
            &quot;mid&quot;: &quot;&lt;MID&gt;&quot;,
            &quot;text&quot;: &quot;&lt;SOME_TEXT&gt;&quot;
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

## User phone number quick reply &#123;#phone&#125;

The user phone number quick reply allows you to ask a user for their phone number. When the phone number quick reply is sent, the Instagram Direct Platform will automatically pre-fill the displayed quick reply with the phone number from the user&#039;s profile information.

If the user&#039;s profile does not have a phone number, Instagram does not show the quick reply.

The bot will not receive the phone number until the user clicks the quick reply.

Choosing the quick reply transmits the information once and does not constitute permission to access the information in the future.

### Syntax

```
&#123;
  &quot;content_type&quot;:&quot;user_phone_number&quot;
&#125;
```

### Webhook event

When the user taps the quick reply, the email address will be passed in the `payload` attribute of the `messages` webhook event.

```http
&#123;
  &quot;object&quot;: &quot;page&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;&lt;PAGE_ID&gt;&quot;,
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
              &quot;payload&quot;: &quot;&lt;PHONE_NUMBER&gt;&quot;
            &#125;,
            &quot;mid&quot;: &quot;&lt;MESSAGE_ID&gt;&quot;,
            &quot;text&quot;: &quot;&lt;PHONE_NUMBER&gt;&quot;
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

### Developer Support

* Use the  [Meta Status tool](https://metastatus.com) to check for the status and outages of Meta business products.
* Use the [Meta Developer Support tool](https://developers.facebook.com/support) to report bugs and view reported bugs, get help with Ads or Business Manager, and more.


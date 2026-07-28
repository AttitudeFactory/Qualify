# Using ig.me Links



`ig.me` is a shortened URL service operated by Meta that redirects users to a conversation in Instagram. You can use ig.me links on your website, email newsletters, and more.

When a user opens an ig.me link to start or continue a conversation with your Instagram account, the user is redirected to a new or existing thread, based on whether the user had previously messaged your Instagram account.

### Contents

- [Link Format](#format)
- [Referral Parameters](#refparams)
- [Examples](#examples)
- [User Experience](#userexperience)
- [Limitations](#limitations)

## Link format &#123;#format&#125;

The format of the link is as follows:

```http
https://ig.me/m/&lt;USERNAME&gt;
```

`USERNAME` is the Instagram handle of the Instagram account.

## Referral parameters &#123;#refparams&#125;

You can pass a referral parameter using these links.

Referral parameters can serve the following purposes:

- Track different links in different channels
- Tie an Instagram user to a session or account in an external app
- Direct the user to specific content or features available within your Instagram account

This is an ig.me link with an added parameter:

```http
https://ig.me/m/&lt;USERNAME&gt;?ref=&lt;REF_PARAM&gt;
```

`REF_PARAM` is passed to the server via a webhook.

### Requirements &#123;#ref_requirements&#125;

To properly use ig.me links, you must meet the following requirements:

* Your Instagram experience must have [Icebreakers](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/ice-breakers) set to receive the referral parameter for new conversations
* The referral parameter must be a string up to 2,083 characters in length
* The Instagram account that the app is connected to must be published to receive the referral parameter for all users, except those that have the developer, tester, or admin role for your bot
* You are using iOS and Android versions 235 and above

### Reading the passed parameter

The referral portion always follows this format:

```http
  &quot;referral&quot;: &#123;
     &quot;ref&quot;: &quot;ref_data_in_ig_dot_me_param&quot;
     &quot;source&quot;: &quot;SHORTLINKS&quot;
     &quot;type&quot;:  &quot;OPEN_THREAD&quot;
&#125;
```

| Field Value | Description |
| --- | --- |
| `ref` | The arbitrary data that was originally passed in the `ref` param added to the ig.me link. Only alphanumeric characters, and -, _, = are supported |
| `source` | The source of this referral. For ig.me links, the value of source is `&quot;SHORTLINK&quot;` |
| `type` | The identifier for the referral. For a referral from ig.me links, it is always `&quot;OPEN_THREAD&quot;` |

When an ig.me link with a `ref` parameter opens the Instagram app, there are three possible scenarios:

#### 1. New thread + icebreaker

If you have configured Icebreakers for your Instagram Account and the user taps on an Icebreaker, your app receives the `messaging_postback` webhook event which includes the passed referral parameter.

The `messaging_postback` webhook event follows this format:

```http
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;&lt;IGSID&gt;&quot;,
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
          &quot;postback&quot;: &#123;
            &quot;mid&quot;:&quot;&lt;MESSAGE_ID&gt;&quot;,
            &quot;title&quot;: &quot;&lt;SELECTED_ICEBREAKER_QUESTION&gt;&quot;,
            &quot;payload&quot;: &quot;&lt;USER_DEFINED_PAYLOAD&gt;,
            &quot;referral&quot;: &#123;
                   &quot;ref&quot;: &quot;ref_data_in_ig_dot_me_param&quot;
                   &quot;source&quot;: &quot;SHORTLINKS&quot;
                   &quot;type&quot;:  &quot;OPEN_THREAD&quot;
             &#125;
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

`USER_DEFINED_PAYLOAD` refers to the payload you previously configured to be sent in the postback.

#### 2. New thread + message send
If you have configured Icebreakers for your Instagram Account and the user doesn&#039;t tap on an Icebreaker, and chooses to send a message via the composer, your app receives the `messages` webhook event which includes the passed referral parameter.

The `messages` webhook event follows this format:

```http
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;&lt;IGSID&gt;&quot;,
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
              &quot;mid&quot;:&quot;&lt;MESSAGE_ID&gt;&quot;,
              &quot;referral&quot;: &#123;
                   &quot;ref&quot;: &quot;ref_data_in_ig_dot_me_param&quot;
                   &quot;source&quot;: &quot;SHORTLINKS&quot;
                   &quot;type&quot;:  &quot;OPEN_THREAD&quot;
              &#125;
           &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

#### 3. Existing thread
If the user has an existing thread with your Instagram Business, when the user follows your ig.me link, Instagram just opens that respective thread. To be notified of the referral, your webhook must be subscribed to the `messaging_referral` event.

This action resets the [24-hour window for standard messaging](https://developers.facebook.com/documentation/business-messaging/messenger-platform/policy#standard_messaging), allowing the app to reply after getting the webhook event with the `ref` parameter.

The `messaging_referral` webhook event follows this format:

```http
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;&lt;IGSID&gt;&quot;,
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
          &quot;referral&quot;: &#123;
                 &quot;ref&quot;: &quot;ref_data_in_ig_dot_me_param&quot;
                 &quot;source&quot;: &quot;SHORTLINKS&quot;
                 &quot;type&quot;:  &quot;OPEN_THREAD&quot;
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

## Examples &#123;#examples&#125;
Here are some ways you can use ig.me links:

1. Use ig.me links + QR code on product packaging to allow people to reach out to you for support or get a coupon towards the next purchase.
2. Use ig.me + QR code on out of home advertising such as billboards, TV ads, physical stores to sign up for loyalty/membership accounts.
3. Use ig.me links on the Contact Us page on a website to allow people to contact you via messaging instead of relying on calling.
4. Provide callers an option to message you on Instagram by sending an ig.me link with [referral param](#refparams) via SMS.

## User experience &#123;#userexperience&#125;

| New threads | Existing threads |
| --- | --- |
| **Note:** Instagram shows the user the following disclosure:  &lt;br&gt;You opened this conversation from a link. `&lt;Ig Business Handle&gt;` will see that you used their link once you send a message. | **Note:** Instagram shows the user the following disclosure:&lt;br&gt;You opened this conversation from a link. `&lt;Ig Business Handle&gt;` can see that you used their link. If you wish to stop receiving messages from them, you can turn off messages. |

## Limitations &#123;#limitations&#125;

ig.me links are currently not supported on Instagram Web.

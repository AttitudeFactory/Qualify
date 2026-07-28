# Self Messaging



This enables a single Instagram Professional account to act as both a **business** and an **Instagram user**, eliminating the need for two separate accounts when testing message previews or automation. This helps showcase messaging automation previews to your newly onboarded business users.

Since the business is messaging itself, the **24-hour response window** does **not apply**.

## Requirements

You will need the following:

- An **Instagram Professional account** connected to your app

- **Business Messaging API** access

- **Webhooks** configured for message events

### Availability and Limitations

The feature is available for IG business users onboarded through either of these flows: Instagram API with Instagram Login and Instagram API with Facebook Login. **Quick Replies** are not currently supported for self messaging.

## Step 1: Onboard the IG Professional Account

This guide assumes you have read the [Instagram Platform Overview](https://developers.facebook.com/documentation/instagram-platform/overview) and implemented the needed components for using this API, such as a Meta login flow and a webhooks server to receive notifications.

|  | Instagram API with Instagram Login | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Levels** | * Advanced Access&lt;br&gt;* Standard Access | * Advanced Access&lt;br&gt;* Standard Access |
| **Access Tokens** | * Instagram User access token | * Facebook Page access token |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | **Self messaging webhook**&lt;br&gt;&lt;br&gt;* `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_messages`&lt;br&gt;&lt;br&gt;**Self comment webhook**&lt;br&gt;&lt;br&gt;* `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_comments` | **Self messaging webhook**&lt;br&gt;&lt;br&gt;* `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_messages`&lt;br&gt;&lt;br&gt;**Self comment webhook**&lt;br&gt;&lt;br&gt;* `instagram_basic`&lt;br&gt;* `instagram_manage_comments`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;&lt;br&gt;If the app user was granted a role on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to your app user&#039;s Instagram professional account via the Business Manager, your app will also need:&lt;br&gt;&lt;br&gt;* `ads_management`&lt;br&gt;* `ads_read` |
| **Webhooks** | **Self messaging webhook**&lt;br&gt;&lt;br&gt;* `messages`&lt;br&gt;&lt;br&gt;**Self comment webhook**&lt;br&gt;&lt;br&gt;* `comments`&lt;br&gt;* `live_comments` | **Self messaging webhook**&lt;br&gt;&lt;br&gt;* `messages`&lt;br&gt;&lt;br&gt;**Self comment webhook**&lt;br&gt;&lt;br&gt;* `comments`&lt;br&gt;* `live_comments` |

## Step 2: Set Up Webhooks

Set up the webhook to listen for **message** and **postback** events.

When the Instagram Professional account sends a message to itself in the Instagram app, an **echo webhook** is triggered, including the **Instagram-scoped ID** of the account. `is_self` with a value of `true` indicates it is a self message.

### Example Echo Webhook

```json
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;&lt;YOUR_APP_USERS_IG_USER_ID&gt;&quot;,
      &quot;time&quot;: 1569262486134,
      &quot;messaging&quot;: [
        &#123;
          &quot;sender&quot;: &#123; &quot;id&quot;: &quot;&lt;YOUR_APP_USERS_IG_USER_ID&gt;&quot; &#125;,
          &quot;recipient&quot;: &#123; &quot;id&quot;: &quot;&lt;INSTAGRAM_SCOPED_ID&gt;&quot; &#125;,
          &quot;timestamp&quot;: 1569262485349,
          &quot;message&quot;: &#123;
            &quot;mid&quot;: &quot;&lt;MESSAGE_ID&gt;&quot;,
            &quot;text&quot;: &quot;&lt;MESSAGE_TEXT&gt;&quot;,
            &quot;is_echo&quot;: true,
            &quot;is_self&quot;: true
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

## Step 3: Send a Self Message Using the Business Messaging API

Use the `recipient ID` received from the webhook to send a message to self on the API.

### Example Request

```curl
curl -X POST &quot;https://graph.facebook.com/v25.0/&lt;INSTAGRAM_SCOPED_ID&gt;/messages&quot; \
        -H &quot;Content-Type: application/json&quot; \
        -H &quot;Authorization: Bearer &lt;ACCESS_TOKEN&gt;&quot; \
        -d &#039;&#123;
              &quot;message&quot;: &#123;
                &quot;text&quot;: &quot;Hello from your IG Pro account!&quot;
              &#125;
            &#125;&#039;
```

On success, your app receives a confirmation with the message ID.

```json
&#123;
  &quot;id&quot;: &quot;&lt;MESSAGE_ID&gt;&quot;
&#125;
```

## Postback and Comment Webhooks

When the Instagram Professional user clicks a CTA button or interacts with a message, a **postback webhook** is generated with `&quot;is_self&quot;: true`.

### Example Postback Webhook

```json
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;45202218377435&quot;,
      &quot;time&quot;: 1743480368963,
      &quot;messaging&quot;: [
        &#123;
          &quot;sender&quot;: &#123; &quot;id&quot;: &quot;&lt;YOUR_APP_USERS_IG_USER_ID&gt;&quot; &#125;,
          &quot;recipient&quot;: &#123; &quot;id&quot;: &quot;&lt;INSTAGRAM_SCOPED_ID&gt;&quot; &#125;,
          &quot;timestamp&quot;: 1743480368714,
          &quot;is_self&quot;: true,
          &quot;postback&quot;: &#123;
            &quot;title&quot;: &quot;Start Chatting&quot;,
            &quot;payload&quot;: &quot;DEVELOPER_DEFINED_PAYLOAD&quot;,
            &quot;mid&quot;: &quot;&lt;MESSAGE_ID&gt;&quot;
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

### Example Comment Webhook

When the Instagram Professional user comments on their own post, a **comments webhook** is generated with `self_ig_scoped_id` as the `IGSID` of their professional account.

```json
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;&lt;YOUR_APP_USERS_INSTAGRAM_ACCOUNT_ID&gt;&quot;,
      &quot;time&quot;: &quot;&lt;TIME_META_SENT_THIS_NOTIFICATION&gt;&quot;,
      &quot;changes&quot;: [
        &#123;
          &quot;field&quot;: &quot;comments&quot;,
          &quot;value&quot;: &#123;
            &quot;from&quot;: &#123;
              &quot;id&quot;: &quot;&lt;YOUR_APP_USERS_INSTAGRAM_ACCOUNT_ID&gt;&quot;,
              &quot;username&quot;: &quot;&lt;INSTAGRAM_USER_USERNAME&gt;&quot;,
              &quot;self_ig_scoped_id&quot;: &quot;&lt;YOUR_APP_USERS_INSTAGRAM_SCOPED_ID&gt;&quot;
            &#125;,
            &quot;id&quot;: &quot;&lt;COMMENT_ID&gt;&quot;,
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
&#125;
```

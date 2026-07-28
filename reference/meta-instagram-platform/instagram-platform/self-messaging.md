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
| **Access Levels** | * Advanced Access<br>* Standard Access | * Advanced Access<br>* Standard Access |
| **Access Tokens** | * Instagram User access token | * Facebook Page access token |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | **Self messaging webhook**<br><br>* `instagram_business_basic`<br>* `instagram_business_manage_messages`<br><br>**Self comment webhook**<br><br>* `instagram_business_basic`<br>* `instagram_business_manage_comments` | **Self messaging webhook**<br><br>* `instagram_business_basic`<br>* `instagram_business_manage_messages`<br><br>**Self comment webhook**<br><br>* `instagram_basic`<br>* `instagram_manage_comments`<br>* `pages_read_engagement`<br><br>If the app user was granted a role on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to your app user's Instagram professional account via the Business Manager, your app will also need:<br><br>* `ads_management`<br>* `ads_read` |
| **Webhooks** | **Self messaging webhook**<br><br>* `messages`<br><br>**Self comment webhook**<br><br>* `comments`<br>* `live_comments` | **Self messaging webhook**<br><br>* `messages`<br><br>**Self comment webhook**<br><br>* `comments`<br>* `live_comments` |

## Step 2: Set Up Webhooks

Set up the webhook to listen for **message** and **postback** events.

When the Instagram Professional account sends a message to itself in the Instagram app, an **echo webhook** is triggered, including the **Instagram-scoped ID** of the account. `is_self` with a value of `true` indicates it is a self message.

### Example Echo Webhook

```json
{
  "object": "instagram",
  "entry": [
    {
      "id": "<YOUR_APP_USERS_IG_USER_ID>",
      "time": 1569262486134,
      "messaging": [
        {
          "sender": { "id": "<YOUR_APP_USERS_IG_USER_ID>" },
          "recipient": { "id": "<INSTAGRAM_SCOPED_ID>" },
          "timestamp": 1569262485349,
          "message": {
            "mid": "<MESSAGE_ID>",
            "text": "<MESSAGE_TEXT>",
            "is_echo": true,
            "is_self": true
          }
        }
      ]
    }
  ]
}
```

## Step 3: Send a Self Message Using the Business Messaging API

Use the `recipient ID` received from the webhook to send a message to self on the API.

### Example Request

```curl
curl -X POST "https://graph.facebook.com/v25.0/<INSTAGRAM_SCOPED_ID>/messages" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer <ACCESS_TOKEN>" \
        -d '{
              "message": {
                "text": "Hello from your IG Pro account!"
              }
            }'
```

On success, your app receives a confirmation with the message ID.

```json
{
  "id": "<MESSAGE_ID>"
}
```

## Postback and Comment Webhooks

When the Instagram Professional user clicks a CTA button or interacts with a message, a **postback webhook** is generated with `"is_self": true`.

### Example Postback Webhook

```json
{
  "object": "instagram",
  "entry": [
    {
      "id": "45202218377435",
      "time": 1743480368963,
      "messaging": [
        {
          "sender": { "id": "<YOUR_APP_USERS_IG_USER_ID>" },
          "recipient": { "id": "<INSTAGRAM_SCOPED_ID>" },
          "timestamp": 1743480368714,
          "is_self": true,
          "postback": {
            "title": "Start Chatting",
            "payload": "DEVELOPER_DEFINED_PAYLOAD",
            "mid": "<MESSAGE_ID>"
          }
        }
      ]
    }
  ]
}
```

### Example Comment Webhook

When the Instagram Professional user comments on their own post, a **comments webhook** is generated with `self_ig_scoped_id` as the `IGSID` of their professional account.

```json
{
  "object": "instagram",
  "entry": [
    {
      "id": "<YOUR_APP_USERS_INSTAGRAM_ACCOUNT_ID>",
      "time": "<TIME_META_SENT_THIS_NOTIFICATION>",
      "changes": [
        {
          "field": "comments",
          "value": {
            "from": {
              "id": "<YOUR_APP_USERS_INSTAGRAM_ACCOUNT_ID>",
              "username": "<INSTAGRAM_USER_USERNAME>",
              "self_ig_scoped_id": "<YOUR_APP_USERS_INSTAGRAM_SCOPED_ID>"
            },
            "id": "<COMMENT_ID>",
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
}
```

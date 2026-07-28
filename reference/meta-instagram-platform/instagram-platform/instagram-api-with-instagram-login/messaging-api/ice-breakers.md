# Ice Breakers



Ice Breakers provide a way for your app users to start a conversation with a business with a list of frequently asked questions. A maximum of 4 questions can be set via the Ice Breaker API.

**Note:** This feature is currently not available on desktop.

## Requirements

This guide assumes you have read the [Instagram Platform Overview](https://developers.facebook.com/documentation/instagram-platform/overview) and implemented the needed components for using this API, such as a Meta login flow and a webhooks server to receive notifications.

You will need the following:

#### Access Level

* Advanced Access if your app serves Instagram professional accounts you don't own or manage
* Standard Access if your app serves Instagram professional accounts you own or manage and have added to your app in the App Dashboard

#### Access tokens

* An Instagram User access token requested from a person who can manage comments on the Instagram professional account

#### Base URL

All endpoints can be accessed via the `graph.instagram.com` host.

#### Endpoints

- [`GET /<YOUR_APP_USERS_YOUR_APP_USERS_IG_ID>/messenger_profile`](https://developers.facebook.com/docs/instagram-platform/reference/ig-user)
- [`POST /<YOUR_APP_USERS_YOUR_APP_USERS_IG_ID>/messenger_profile`](https://developers.facebook.com/docs/instagram-platform/reference/ig-user)
- [`DELETE /<YOUR_APP_USERS_YOUR_APP_USERS_IG_ID>/messenger_profile`](https://developers.facebook.com/docs/instagram-platform/reference/ig-user)

You can also use the `/me/messenger_profile` endpoints.

#### IDs

* The ID for your app user's Instagram professional account

#### Permissions
* `instagram_business_basic`
* `instagram_business_manage_messages`

#### Webhook event subscriptions

* `messages`
* `messaging_postbacks`

## Create Ice Breakers

To create ice breakers, send a `POST` request to the `/<YOUR_APP_USERS_IG_ID>/messenger_profile` endpoint,  where `<YOUR_APP_USERS_IG_ID>` is the ID for your app user's Instagram professional account, and include the `platform` property set to `instagram` and the `ice_breakers` property with a `call_to_actions` array of `question` and `payload` objects.

#### Sample request

_Formatted for readability._

```curl
curl -X POST -H "Content-Type: application/json"
     -d '{
          "platform": "instagram",
          "ice_breakers":[
            {
              "call_to_actions":[
                {
                  "question":"<QUESTION_1>",
                  "payload":"<PAYLOAD_FOR_QUESTION_1>"
                },
                {
                  "question":"<QUESTION_2>",
                  "payload":"<PAYLOAD_FOR_QUESTION_2>"
                }
              ],
            },
          ]
        }' "https://graph.instagram.com/v25.0/<YOUR_APP_USERS_IG_ID>/messenger_profile?access_token=<INSTAGRAM_USER_ACCESS_TOKEN>"
```

You can set a `call_to_actions` array for each `locale` you include.

On success your app receives a JSON response with `success` set to `true`.

#### Sample request with multiple locales

To create ice breakers for multiple locales, include the `locale` property and `call_to_actions` array for each locale.

_Formatted for readability._

```curl
curl -X POST -H "Content-Type: application/json"
     -d '{
          "platform": "instagram",
          "ice_breakers":[
            {
              "call_to_actions":[
                {
                  "question":"<QUESTION_1>",
                  "payload":"<PAYLOAD_FOR_QUESTION_1>"
                },
                {
                  "question":"<QUESTION_2>",
                  "payload":"<PAYLOAD_FOR_QUESTION_2>"
                }
              ],
              "locale": "zh_CN",
              "call_to_actions":[
                {
                  "question":"<QUESTION_1_zh_CN>",
                  "payload":"<PAYLOAD_FOR_QUESTION_1_zh_CN>"
                },
                {
                  "question":"<QUESTION_2_zh_CN>",
                  "payload":"<PAYLOAD_FOR_QUESTION_2_zh_CN>"
                }
              ]
            }
          ]
        }' "https://graph.instagram.com/v25.0/<YOUR_APP_USERS_IG_ID>/messenger_profile?access_token=<INSTAGRAM_USER_ACCESS_TOKEN>"
```

## List Ice Breakers

To get a list of your ice breakers, send a `GET` request to the `/me/messenger_profile` endpoint,  where `me` is the ID for your app user's Instagram professional account, with the `fields` parameter set to `ice_breakers`.

#### Sample request

_Formatted for readability._

```curl
curl -X GET "https://graph.instagram.com/v25.0/me/messenger_profile
     ?fields=ice_breakers
     &access_token=<INSTAGRAM_USER_ACCESS_TOKEN>"
```

On success your app receives a JSON response with an array of `call_to_actions` properties that include questions and payloads and locales, if applicable.

```json
{
   "data": [
        {
          "call_to_actions" : [
               {
                "question": "<QUESTION_1>",
                "payload": "<PAYLOAD_1>",

               },
               {
                "question": "<QUESTION_2>",
                "payload": "<PAYLOAD_2>",

               },
          ],
          "locale": "<LOCALE_1>",
      },
      {
          "call_to_actions" : [
               {
                "question": "<QUESTION_3>",
                "payload": "<PAYLOAD_3>",

               },
               {
                "question": "<QUESTION_4>",
                "payload": "<PAYLOAD_4>",

               },
          ],
          "locale": "<LOCALE_2>",
      }
   ]
}
```

## Delete ice breakers

To delete ice breakers, send a `DELETE` request to the `/<YOUR_APP_USERS_IG_ID>/messenger_profile` endpoint,  where `<YOUR_APP_USERS_IG_ID>` is the ID for your app user's Instagram professional account, with the `fields` parameter set to an array that includes `ice_breakers`.

#### Sample request

_Formatted for readability._

```curl
curl -X DELETE -H "Content-Type: application/json" -d '{
    "fields": [
      "ice_breakers",
    ]
  }' "https://graph.instagram.com/v25.0/me/messenger_profile?access_token=<INSTAGRAM_USER_ACCESS_TOKEN>"
```

On success your app receives a JSON response with `success` set to `true`.

## Webhook Notifications

When the `messaging_postback` event webhook is triggered, we will send your webhook server a notification with a JSON object that includes the following:

* `id` set to your app user's Instagram professional account
* `time` set to when the notification was sent
* `messaging.sender.id` set to the Instagram-scoped ID for the Instagram user who click a question
* `messaging.recipient.id` set to our app user's Instagram professional account who is receiving the notification
* `messaging.timestamp` set to when the user clicked on the question
* `messaging.postback.title` set to the question the Instagram user selected
* `messaging.postback.payload` set to the content associated with the question that was chosen

```json
{
  "object": "instagram",
  "entry": [
    {
      "id": "<YOUR_APP_USERS_IG_ID>",
      "time": <UNIX_TIMESTAMP>,
      "messaging": [
        {
          "sender": {
            "id": "<IGSID>"
          },
          "recipient": {
            "id": "<YOUR_APP_USERS_IG_ID>"
          },
          "timestamp": <UNIX_TIMESTAMP>,
          "postback": {
            "title": "<USER_SELECTED_ICEBREAKER_QUESTION>",
            "payload": "<QUESTION_PAYLOAD>",
          }
        }
      ]
    }
  ]
}
```

## Next steps

You've received a notification that an Instagram user clicked on an ice breaker, now [send the user a response](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api).

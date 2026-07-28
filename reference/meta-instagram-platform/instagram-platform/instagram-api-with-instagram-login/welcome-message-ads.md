# Welcome Message Flows



When creating ads that Click to Instagram Direct, you can connect a message flow from a messaging partner app. A message flow can include text, images, emoji, buttons, and other message types supported by the [Send API](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api).

This guide shows how to create and manage welcome message flows via the Instagram Platform.

## Requirements

This guide assumes you have read the [Instagram Platform Overview](https://developers.facebook.com/documentation/instagram-platform/overview) and implemented the needed components for using this API, such as a Meta login flow and a webhooks server to receive notifications.

You will need the following:

#### Access Level

* Advanced Access if your app serves Instagram professional accounts you don't own or manage
* Standard Access if your app serves Instagram professional accounts you own or manage and have added to your app in the App Dashboard

#### Access tokens

* An Instagram User access token requested from a person who can manage messages on the Instagram professional account

#### Base URL

All endpoints can be accessed via the `graph.instagram.com` host.

#### Endpoints

- [`/welcome_message_flows`](https://developers.facebook.com/documentation/instagram-platform/reference)
- `/<APP_USERS_INSTAGRAM_PRO_ID>` or `/me`

#### IDs

* The ID for the Instagram professional account that is creating the welcome message flow

#### Permissions
* `instagram_business_basic`
* `instagram_business_manage_messages`

### Limitations

* Welcome message flows are only available through Instagram Boost Ads if the Instagram professional account is not linked to a Facebook Page.
* Welcome message flows will not appear in Meta's Ads Manager if the Instagram professional account is not linked to a Facebook Page.

Linking a Facebook Page to the Instagram professional account allows for the welcome message flows to be visible in Ads Manager and accessible for other ad types.

## Create a flow

To create a welcome message flow, send a `POST` request to the `/me/welcome_message_flows` endpoint with the following properties:

* `eligible_platforms` set to `"instagram"` (Only Instagram is supported.)
* `name` set to the name of the flow
* `welcome_message_flow` set to an array of `message` objects with:
    * `message.text` set to your app user's welcome message
    * `message.quick_replies` set to an array defining each quick reply with:
        * `content_type` set to `text`
        * `title` set to the quick reply button text
        * `payload` set to the content to be sent in a webhook notification when a person clicks that button

#### Sample request

```curl
curl -X POST -H "Content-Type: application/json"
     -d '{
           "eligible_platforms":["instagram"],
           "name"="<WELCOME_MESSAGE_FLOW_NAME>",
           "welcome_message_flow": [
             {
               "message": {
                 "text":"<WELCOME_MESSAGE_TEXT>",
                 "quick_replies":[
                   {
                     "content_type":"text",
                     "title":"<QUICK_REPLY_TEXT_1>",
                     "payload":"<QUICK_REPLY_TEXT_1_WEBHOOK_CONTENT>"
                   },
                   {
                     "content_type":"text",
                     "title":"<QUICK_REPLY_TEXT_2>",
                     "payload":"<QUICK_REPLY_TEXT_2_WEBHOOK_CONTENT>"
                   },
                   {
                     "content_type":"text",
                     "title":"<QUICK_REPLY_TEXT_3>",
                     "payload":"<QUICK_REPLY_TEXT_3_WEBHOOK_CONTENT>"
                   }
                 ]
               }
             }
           ]
        }' "https://graph.instagram.com/v25.0/me/welcome_message_flows?access_token=<INSTAGRAM_USER_ACCESS-TOKEN>"
```

On success your app receives an ID for the welcome message flow.

```json
{
  "flow_id":"<WELCOME_MESSAGE_FLOW_ID>"
}
```

### Reference

| Properties | Description |
| --- | --- |
| `eligible_platforms`<br><br>*Array of strings* | **Required.** The platforms that the welcome message can be shown on, `"instagram"`. Only Instagram is supported. |
| `name`<br><br>*String* | **Required.** Name of the flow |
| `welcome_message_flow`<br><br>*Array of `message` objects* | **Required.** An array of message objects that contain the welcome message text and an array of quick replies sent upon clicking the ad |

| `welcome_message_flow` Properties | Description |
| --- | --- |
| `message`<br><br>*Object* | **Required.** An objects that contain the welcome message text and an array of quick replies sent upon clicking the ad |
| `message.text`<br><br>*String* | **Required.** The welcome message text sent upon clicking the ad |
| `message.quick_replies`<br><br>*Array* | **Required.** An array of objects that defines each quick reply including the content type of each quick reply, the text shown in each quick reply button, and the content sent via webhook notification when the quick reply that is selected. |
| `message.quick_replies.content_type`<br><br>*String* | **Required.** Must be `text`. |
| `message.quick_replies.payload`<br><br>*String* | **Required.** The content sent in a webhook notification when a person clicks on the associated quick reply button |
| `message.quick_replies.title`<br><br>*String* | **Required.** The text shown in the quick reply button. |

***Note:** Each Welcome Message will be validated against the platform(s) specified and will only be accepted if the message type in the welcome message is supported on the specified platform(s).*

## Read

To get a list of your app user's welcome message flows, send a `GET` request to `/me/welcome_message_flows` endpoint.

#### Sample request
_Formatted for readability._

```curl
curl -X GET "https://graph.instagram.com/v25.0/me/welcome_message_flows
      ?access_token=<INSTAGRAM_USER_ACCESS-TOKEN>"
```

On success, your app will receive a list of flows.

```json
[
  {
    "id":"<WELCOME_FLOW_1_ID>",
    "name":"<WELCOME_FLOW_1_NAME>",
    "welcome_message":"<MESSAGE_1_OBJECT_CONTENT>",
    "eligible_platforms": ["instagram"],
    "last_update_time":"2023-09-01T05:20:38+0000",
    "is_used_in_ad": false // indicates whether or not a flow is used in an ad
  },
  {
    "id":"<WELCOME_FLOW_2_ID>",
    "name":"<WELCOME_FLOW_2_NAME>",
    "welcome_message":"<MESSAGE_2_OBJECT_CONTENT>",
    "eligible_platforms": ["instagram"],
    "last_update_time":"2023-08-25T08:21:48+0000",
    "is_used_in_ad": true
  },
  {
    "id":"<WELCOME_FLOW_3_ID>",
    "name":"<WELCOME_FLOW_3_NAME>",
    "welcome_message":"<MESSAGE_3_OBJECT_CONTENT>",
    "eligible_platforms": ["instagram"],
    "last_update_time":"2023-08-20T07:43:00+0000",
    "is_used_in_ad": true
  }
  ...
  ...
  ...
]
```

**Note:**  You can limit the number of flows returned by including the `limit` parameter set to the number you want returned.

### Get a specific flow

To get a specific flow, send a `GET` request to `/me/welcome_message_flows` endpoint with the `flow_id` parameter set to the the flow ID being queried.

#### Sample request
_Formatted for readability._

```curl
curl -X GET "https://graph.instagram.com/v25.0/me/welcome_message_flows
      ?access_token=<INSTAGRAM_USER_ACCESS-TOKEN>"
```

On success, your app receives a JSON object with the data about the specific flow queried.

## Update a flow

To update an existing flow, send a `POST` request to the `/me/welcome_message_flows` endpoint with:

* the `flow_id` parameter set to the ID of the flow being updated
* at least one of the following parameters to be updated
    * `name`
    * `welcome_message`
    * `platforms`

**Warning:** A flow that is currently connected to an advertisement cannot be updated. Check the `is_used_in_ad` field to determine whether a flow is connected to an advertisement.

#### Sample request

_Formatted for readability._

```curl
curl -X POST "https://graph.instagram.com/v25.0/me/welcome_message_flows \
      ?access_token=<INSTAGRAM_USER_ACCESS-TOKEN> \
      &flow_id=<WELCOME_FLOW_3_ID> \
      &name=<WELCOME_FLOW_3_NEW_NAME>"
```

On success, your app receives a JSON object with `success` set to `true`.

```json
{"success":true}
```

## Delete a flow

To delete a flow, send a `DELETE` request to `/me/welcome_message_flows` endpoint with the `flow_id` parameter set to the ID of the flow to be deleted.

**Warning:** A flow that is currently connected to an advertisement cannot be deleted. Check the `is_used_in_ad` field to determine whether a flow is connected to an advertisement.

### Sample request

_Formatted for readability._

```curl
curl -X DELETE "https://graph.instagram.com/v25.0/me/welcome_message_flows
      ?access_token=<INSTAGRAM_USER_ACCESS-TOKEN> \
      &flow_id=<WELCOME_FLOW_3_ID>"
```

On success, your app receives a JSON object with `success` set to `true`.

## Next steps

Now that you have welcome message flows, they can be used to create ads using [the Marketing API](https://developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/messaging-ads/click-to-instagram#flows) or the [Ads Manager](https://adsmanager.facebook.com/).

### Ads manager

When creating a new engagement ad, scroll down to the **Message template** section and select Partner App.

 

Select the appropriate messaging Partner App.

Select the Welcome Message Flow.

Preview your message flow.


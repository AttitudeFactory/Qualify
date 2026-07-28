# Welcome Message Flows



When creating ads that Click to Instagram Direct, you can connect a message flow from a messaging partner app. A message flow can include text, images, emoji, buttons, and other message types supported by the [Send API](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api).

This guide shows how to create and manage welcome message flows via the Instagram Platform.

## Requirements

This guide assumes you have read the [Instagram Platform Overview](https://developers.facebook.com/documentation/instagram-platform/overview) and implemented the needed components for using this API, such as a Meta login flow and a webhooks server to receive notifications.

You will need the following:

#### Access Level

* Advanced Access if your app serves Instagram professional accounts you don&#039;t own or manage
* Standard Access if your app serves Instagram professional accounts you own or manage and have added to your app in the App Dashboard

#### Access tokens

* An Instagram User access token requested from a person who can manage messages on the Instagram professional account

#### Base URL

All endpoints can be accessed via the `graph.instagram.com` host.

#### Endpoints

- [`/welcome_message_flows`](https://developers.facebook.com/documentation/instagram-platform/reference)
- `/&lt;APP_USERS_INSTAGRAM_PRO_ID&gt;` or `/me`

#### IDs

* The ID for the Instagram professional account that is creating the welcome message flow

#### Permissions
* `instagram_business_basic`
* `instagram_business_manage_messages`

### Limitations

* Welcome message flows are only available through Instagram Boost Ads if the Instagram professional account is not linked to a Facebook Page.
* Welcome message flows will not appear in Meta&#039;s Ads Manager if the Instagram professional account is not linked to a Facebook Page.

Linking a Facebook Page to the Instagram professional account allows for the welcome message flows to be visible in Ads Manager and accessible for other ad types.

## Create a flow

To create a welcome message flow, send a `POST` request to the `/me/welcome_message_flows` endpoint with the following properties:

* `eligible_platforms` set to `&quot;instagram&quot;` (Only Instagram is supported.)
* `name` set to the name of the flow
* `welcome_message_flow` set to an array of `message` objects with:
    * `message.text` set to your app user&#039;s welcome message
    * `message.quick_replies` set to an array defining each quick reply with:
        * `content_type` set to `text`
        * `title` set to the quick reply button text
        * `payload` set to the content to be sent in a webhook notification when a person clicks that button

#### Sample request

```curl
curl -X POST -H &quot;Content-Type: application/json&quot;
     -d &#039;&#123;
           &quot;eligible_platforms&quot;:[&quot;instagram&quot;],
           &quot;name&quot;=&quot;&lt;WELCOME_MESSAGE_FLOW_NAME&gt;&quot;,
           &quot;welcome_message_flow&quot;: [
             &#123;
               &quot;message&quot;: &#123;
                 &quot;text&quot;:&quot;&lt;WELCOME_MESSAGE_TEXT&gt;&quot;,
                 &quot;quick_replies&quot;:[
                   &#123;
                     &quot;content_type&quot;:&quot;text&quot;,
                     &quot;title&quot;:&quot;&lt;QUICK_REPLY_TEXT_1&gt;&quot;,
                     &quot;payload&quot;:&quot;&lt;QUICK_REPLY_TEXT_1_WEBHOOK_CONTENT&gt;&quot;
                   &#125;,
                   &#123;
                     &quot;content_type&quot;:&quot;text&quot;,
                     &quot;title&quot;:&quot;&lt;QUICK_REPLY_TEXT_2&gt;&quot;,
                     &quot;payload&quot;:&quot;&lt;QUICK_REPLY_TEXT_2_WEBHOOK_CONTENT&gt;&quot;
                   &#125;,
                   &#123;
                     &quot;content_type&quot;:&quot;text&quot;,
                     &quot;title&quot;:&quot;&lt;QUICK_REPLY_TEXT_3&gt;&quot;,
                     &quot;payload&quot;:&quot;&lt;QUICK_REPLY_TEXT_3_WEBHOOK_CONTENT&gt;&quot;
                   &#125;
                 ]
               &#125;
             &#125;
           ]
        &#125;&#039; &quot;https://graph.instagram.com/v25.0/me/welcome_message_flows?access_token=&lt;INSTAGRAM_USER_ACCESS-TOKEN&gt;&quot;
```

On success your app receives an ID for the welcome message flow.

```json
&#123;
  &quot;flow_id&quot;:&quot;&lt;WELCOME_MESSAGE_FLOW_ID&gt;&quot;
&#125;
```

### Reference

| Properties | Description |
| --- | --- |
| `eligible_platforms`&lt;br&gt;&lt;br&gt;*Array of strings* | **Required.** The platforms that the welcome message can be shown on, `&quot;instagram&quot;`. Only Instagram is supported. |
| `name`&lt;br&gt;&lt;br&gt;*String* | **Required.** Name of the flow |
| `welcome_message_flow`&lt;br&gt;&lt;br&gt;*Array of `message` objects* | **Required.** An array of message objects that contain the welcome message text and an array of quick replies sent upon clicking the ad |

| `welcome_message_flow` Properties | Description |
| --- | --- |
| `message`&lt;br&gt;&lt;br&gt;*Object* | **Required.** An objects that contain the welcome message text and an array of quick replies sent upon clicking the ad |
| `message.text`&lt;br&gt;&lt;br&gt;*String* | **Required.** The welcome message text sent upon clicking the ad |
| `message.quick_replies`&lt;br&gt;&lt;br&gt;*Array* | **Required.** An array of objects that defines each quick reply including the content type of each quick reply, the text shown in each quick reply button, and the content sent via webhook notification when the quick reply that is selected. |
| `message.quick_replies.content_type`&lt;br&gt;&lt;br&gt;*String* | **Required.** Must be `text`. |
| `message.quick_replies.payload`&lt;br&gt;&lt;br&gt;*String* | **Required.** The content sent in a webhook notification when a person clicks on the associated quick reply button |
| `message.quick_replies.title`&lt;br&gt;&lt;br&gt;*String* | **Required.** The text shown in the quick reply button. |

***Note:** Each Welcome Message will be validated against the platform(s) specified and will only be accepted if the message type in the welcome message is supported on the specified platform(s).*

## Read

To get a list of your app user&#039;s welcome message flows, send a `GET` request to `/me/welcome_message_flows` endpoint.

#### Sample request
_Formatted for readability._

```curl
curl -X GET &quot;https://graph.instagram.com/v25.0/me/welcome_message_flows
      ?access_token=&lt;INSTAGRAM_USER_ACCESS-TOKEN&gt;&quot;
```

On success, your app will receive a list of flows.

```json
[
  &#123;
    &quot;id&quot;:&quot;&lt;WELCOME_FLOW_1_ID&gt;&quot;,
    &quot;name&quot;:&quot;&lt;WELCOME_FLOW_1_NAME&gt;&quot;,
    &quot;welcome_message&quot;:&quot;&lt;MESSAGE_1_OBJECT_CONTENT&gt;&quot;,
    &quot;eligible_platforms&quot;: [&quot;instagram&quot;],
    &quot;last_update_time&quot;:&quot;2023-09-01T05:20:38+0000&quot;,
    &quot;is_used_in_ad&quot;: false // indicates whether or not a flow is used in an ad
  &#125;,
  &#123;
    &quot;id&quot;:&quot;&lt;WELCOME_FLOW_2_ID&gt;&quot;,
    &quot;name&quot;:&quot;&lt;WELCOME_FLOW_2_NAME&gt;&quot;,
    &quot;welcome_message&quot;:&quot;&lt;MESSAGE_2_OBJECT_CONTENT&gt;&quot;,
    &quot;eligible_platforms&quot;: [&quot;instagram&quot;],
    &quot;last_update_time&quot;:&quot;2023-08-25T08:21:48+0000&quot;,
    &quot;is_used_in_ad&quot;: true
  &#125;,
  &#123;
    &quot;id&quot;:&quot;&lt;WELCOME_FLOW_3_ID&gt;&quot;,
    &quot;name&quot;:&quot;&lt;WELCOME_FLOW_3_NAME&gt;&quot;,
    &quot;welcome_message&quot;:&quot;&lt;MESSAGE_3_OBJECT_CONTENT&gt;&quot;,
    &quot;eligible_platforms&quot;: [&quot;instagram&quot;],
    &quot;last_update_time&quot;:&quot;2023-08-20T07:43:00+0000&quot;,
    &quot;is_used_in_ad&quot;: true
  &#125;
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
curl -X GET &quot;https://graph.instagram.com/v25.0/me/welcome_message_flows
      ?access_token=&lt;INSTAGRAM_USER_ACCESS-TOKEN&gt;&quot;
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
curl -X POST &quot;https://graph.instagram.com/v25.0/me/welcome_message_flows \
      ?access_token=&lt;INSTAGRAM_USER_ACCESS-TOKEN&gt; \
      &amp;flow_id=&lt;WELCOME_FLOW_3_ID&gt; \
      &amp;name=&lt;WELCOME_FLOW_3_NEW_NAME&gt;&quot;
```

On success, your app receives a JSON object with `success` set to `true`.

```json
&#123;&quot;success&quot;:true&#125;
```

## Delete a flow

To delete a flow, send a `DELETE` request to `/me/welcome_message_flows` endpoint with the `flow_id` parameter set to the ID of the flow to be deleted.

**Warning:** A flow that is currently connected to an advertisement cannot be deleted. Check the `is_used_in_ad` field to determine whether a flow is connected to an advertisement.

### Sample request

_Formatted for readability._

```curl
curl -X DELETE &quot;https://graph.instagram.com/v25.0/me/welcome_message_flows
      ?access_token=&lt;INSTAGRAM_USER_ACCESS-TOKEN&gt; \
      &amp;flow_id=&lt;WELCOME_FLOW_3_ID&gt;&quot;
```

On success, your app receives a JSON object with `success` set to `true`.

## Next steps

Now that you have welcome message flows, they can be used to create ads using [the Marketing API](https://developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/messaging-ads/click-to-instagram#flows) or the [Ads Manager](https://adsmanager.facebook.com/).

### Ads manager

When creating a new engagement ad, scroll down to the **Message template** section and select Partner App.

 

Select the appropriate messaging Partner App.

Select the Welcome Message Flow.

Preview your message flow.


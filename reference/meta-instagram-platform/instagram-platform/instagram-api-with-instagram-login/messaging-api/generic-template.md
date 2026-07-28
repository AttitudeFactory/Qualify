# Send a Generic Template



The generic template allows you to send a structured message that includes an image, text and buttons. A generic template with multiple options described in the [`elements`](#elements) array will send a horizontally scrollable carousel of items, each composed of an image, text and buttons.

## Before you start

This guide assumes you have set up your webhooks server to receive notifications and subscribed your app to Instagram `messages` and `messaging_postbacks` events.

You will need:

* The ID for the Instagram professional account, `<IG_ID>`
* The elements for the template
* The payload to include in the webhook notification for each element

### Limitations

This feature is currently not available on desktop.

#### Host URL

`https://graph.instagram.com`

## Send a template

To send a template message send a `POST` request to the `/<IG_ID>/messages` endpoint with the following parameters:

* `recipient.id` set to the Instagram-scoped ID of the person you are sending the message
* `message.attachment` object with:
    * `type` set to `template`
    * `payload` object with:
        * `template_type` set to `generic`
        * `elements` set to an array of objects that the recipient can select such as links, buttons, and images

#### Sample request

```curl
curl -X POST -H "Content-Type: application/json" -d '{
  "recipient":{
    "id":"<IGSID>"
  },
  "message":{
    "attachment":{
      "type":"template",
      "payload":{
        "template_type":"generic",
        "elements":[
           {
            "title":"Welcome!",
            "image_url":"https://raw.githubusercontent.com/fbsamples/original-coast-clothing/main/public/styles/male-work.jpg",
            "subtitle":"We have the right hat for everyone.",
            "default_action": {
              "type": "web_url",
              "url": "https://www.originalcoastclothing.com/",
            },
            "buttons":[
              {
                "type":"web_url",
                "url":"https://www.originalcoastclothing.com/",
                "title":"View Website"
              },{
                "type":"postback",
                "title":"Start Chatting",
                "payload":"DEVELOPER_DEFINED_PAYLOAD"
              }
            ]
          }
        ]
      }
    }
  }
}' "https://graph.instagram.com/v20.0/me/messages?access_token=INSTAGRAM_ACCESS_TOKEN"
```

On success your app receives a JSON response with the Instagram-scoped ID for the reciepient and the ID for the message.

#### Example Response {#example_response}

```js
{
  "recipient_id": "1254477777772919",
  "message_id": "AG5Hz2Uq7tuwNEhXfYYKj8mJEM_QPpz5jdCK48PnKAjSdjfipqxqMvK8ma6AC8fplwlqLP_5cgXIbu7I3rBN0P"
}
```


## Properties {#properties}

| Property | Type | Description |
| --- | --- | --- |
| `recipient.id` | String | The Instagram-scoped ID (`<IGSID>`) for the person to whom you are sending the message |
| `message.attachment` | Object | An object describing attachments to the message. |

### `message.attachment` {#attachment}  

| Property | Type | Description |
| --- | --- | --- |
| `type` | String | Value must be `template` |
| `payload` | Object | [`payload`](#payload) of the template. |

### `message.attachment.payload` {#payload}

| Property | Type | Description |
| --- | --- | --- |
| `template_type` | String | Value must be `generic` |
| `elements` | Array | An array of [`element`](#elements) objects that describe instances of the generic template to be sent. Specifying multiple elements will send a horizontally scrollable carousel of templates. A maximum of 10 elements is supported. |

### `message.attachment.payload.elements` {#elements}

The generic template supports a maximum of 10 elements per message. At least one property must be set in addition to `title`.

| Property Name | Type | Description |
| --- | --- | --- |
| `title` | String | The title to display in the template. 80 character limit. |
| `subtitle` | String | ***Optional.*** The subtitle to display in the template. 80 character limit. |
| `image_url` | String | ***Optional.*** The URL of the image to display in the template. |
| `default_action` | Object | ***Optional.*** The default action executed when the template is tapped. Accepts the same properties as [URL button](https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages/buttons), except `title`. |
| `buttons` | Array | ***Optional.*** An array of [buttons](https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages/buttons) to append to the template. A maximum of 3 buttons per element is supported. Only `postback` and `web_url` buttons are supported. |

## Learn more

Visit the [`message.attachment.data`](https://developers.facebook.com/docs/graph-api/reference/message) for GIFs and Stickers.

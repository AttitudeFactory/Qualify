# Button Template



A button template message allows you to send a message that contains text and up to three attached buttons that allow the message recipient to choose from different options. The buttons can open web pages in the in-app browser or send the recipient's selection to you via the `messaging_postback` webhook notification. You can then send information about the selection back to the recipient.

## Before you start
This guide assumes you have set up your webhooks server to receive notifications and subscribed your app to Instagram `messages` and `messaging_postbacks` events.

You will need:

* The ID for the Instagram professional account (`IG_ID`)
* The Instagram-scoped ID (`IGSID`) for the person to whom you are sending the message

#### Host URL
`https://graph.instagram.com`

### Button types

#### URL Button

The URL Button opens a web page in the in-app browser. This allows you to enrich the conversation with a web-based experience, where you have the full development flexibility of the web. For example, you might display a product summary in-conversation, then use the URL button to open the full product page on your website.

#### Postback Button

The postback button sends a [`messaging_postbacks`](https://developers.facebook.com/documentation/business-messaging/messenger-platform/reference/webhook-events/messaging_postbacks) event to your webhook with the string set in the `payload` property. This allows you to take arbitrary actions when the button is tapped. For example, you might display a list of products, then send the product ID in the postback to your webhook, where it can be used to query your database and return the product details as a structured message.

## Send a button template message

To send a message using the button template, send a `POST` request to the `/<IG_ID>/messages` endpoint with the following parameters:

* `recipient.id` set to the Instagram-scoped ID of the person you are sending the message
* `message.attachment` object with:
    * `type` set to `template`
    * `payload` object with:
        * `template_type` set to `button`
        * `text` set to the text that prompts the recipient to click a button
        * `buttons` set to an array of button objects with the button type, URL or payload and title

## Example Request {#example_request}

For complete request details and properties, refer to the Properties section below.

```curl
curl -X POST -H "Content-Type: application/json" -d '{
  "recipient":{
    "id":"<IGSID>"
  },
  "message":{
    "attachment":{
      "type":"template",
      "payload":{
        "template_type":"button",
        "text":"What do you want to do next?",
        "buttons":[
          {
            "type":"web_url",
            "url":"https://www.instagram.com",
            "title":"Visit Instagram",
          }, {
            "type":"postback",
            "payload":"postback_payload",
            "title":"postback button",
          }
        ]
      }
    }
  }
}' "https://graph.instagram.com/v20.0/me/messages?access_token=INSTAGRAM_ACCESS_TOKEN"
```

On success your app receives a JSON response with the recipient ID and message ID.

```js
{
  "recipient_id": "1254477777772919",
  "message_id": "AG5Hz2Uq7tuwNEhXfYYKj8mJEM_QPpz5jdCK48PnKAjSdjfipqxqMvK8ma6AC8fplwlqLP_5cgXIbu7I3rBN0P"
}
```


## Properties {#properties}
| Property | Type | Description |
| --- | --- | --- |
| `recipient.id` | String | IG Scoped User ID (IGSID) of the message recipient. |
| `message.attachment` | Object | An object describing attachments to the message. |

### `message.attachment`

| Property | Type | Description |
| --- | --- | --- |
| `type` | String | Value must be `template`. |
| `payload` | Object | `payload` of the template. |

### `message.attachment.payload`

| Property | Type | Description |
| --- | --- | --- |
| `template_type` | String | Value must be `button`. |
| `text` | String | UTF-8-encoded text of up to 640 characters. Text will appear above the buttons. |
| `buttons` | Array<button> | Set of 1-3 buttons that appear as call-to-actions. |
| `buttons.PAYLOAD` | String | The content to be sent in the `messaging_postback` webhook notification when a `postback` button is clicked |
| `buttons.title` | String | The button text |
| `buttons.type` | enum | Value can be `postback` or `web_url` |
| `buttons.url` | String | The URL for a `web_url` type button |


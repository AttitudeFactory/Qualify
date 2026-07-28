# Button Template



The button template sends a text message with up to three attached buttons. This template is useful for offering the message recipient options to choose from, such as predetermined responses to a question, or actions to take.

## Limitations

The button template is currently not available in the web version.

## Template payload &#123;#payload&#125;

For a complete list of template properties, refer to the [Properties](#properties) section below. Replace each `&lt;BUTTON_OBJECT&gt;` with a URL button or postback button object, as described in [Available buttons](#buttons).

```http
&quot;payload&quot;: &#123;
  &quot;template_type&quot;:&quot;button&quot;,
  &quot;text&quot;:&quot;&lt;MESSAGE_TEXT&gt;&quot;,
  &quot;buttons&quot;:[
    &lt;BUTTON_OBJECT&gt;,
    &lt;BUTTON_OBJECT&gt;,
    ...
  ]
&#125;
```

## Available buttons &#123;#buttons&#125;

### URL button &#123;#url&#125;

The URL button opens a web page in the in-app browser. The URL button lets you add a web-based view to the conversation. For example, you might display a product summary in-conversation, then use the URL button to open the full product page on your website.

#### Button format

```http
&#123;
  &quot;type&quot;: &quot;web_url&quot;,
  &quot;url&quot;: &quot;&lt;URL_TO_OPEN_IN_WEBVIEW&gt;&quot;,
  &quot;title&quot;: &quot;&lt;BUTTON_TEXT&gt;&quot;,
&#125;
```

### Postback button &#123;#postback&#125;

The postback button sends a [`messaging_postbacks`](https://developers.facebook.com/documentation/business-messaging/messenger-platform/reference/webhook-events/messaging_postbacks) event to your webhook with the string set in the `payload` property. This allows you to take arbitrary actions when the button is tapped. For example, you might display a list of products, then send the product ID in the postback to your webhook, where it can be used to query your database and return the product details as a structured message.

#### Button format

For a complete list of button properties, see the [postback button reference](https://developers.facebook.com/documentation/business-messaging/messenger-platform/reference/buttons/postback).

```http
&#123;
  &quot;type&quot;: &quot;postback&quot;,
  &quot;title&quot;: &quot;&lt;BUTTON_TEXT&gt;&quot;,
  &quot;payload&quot;: &quot;&lt;STRING_SENT_TO_WEBHOOK&gt;&quot;
&#125;
```

## Example request &#123;#example_request&#125;

For complete request details and properties, refer to the [Properties](#properties) section below.

```curl
curl -X POST -H &quot;Content-Type: application/json&quot; -d &#039;&#123;
  &quot;recipient&quot;:&#123;
    &quot;id&quot;:&quot;&lt;IGID&gt;&quot;
  &#125;,
  &quot;message&quot;:&#123;
    &quot;attachment&quot;:&#123;
      &quot;type&quot;:&quot;template&quot;,
      &quot;payload&quot;:&#123;
        &quot;template_type&quot;:&quot;button&quot;,
        &quot;text&quot;:&quot;What do you want to do next?&quot;,
        &quot;buttons&quot;:[
          &#123;
            &quot;type&quot;:&quot;web_url&quot;,
            &quot;url&quot;:&quot;https://www.messenger.com&quot;,
            &quot;title&quot;:&quot;Visit Messenger&quot;
          &#125;,
          &#123;
            ...
          &#125;,
          &#123;...&#125;
        ]
      &#125;
    &#125;
  &#125;
&#125;&#039; &quot;https://graph.facebook.com/v13.0/me/messages?access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot;
```

## Example response &#123;#example_response&#125;

A successful request returns a JSON response containing the recipient ID and the message ID, as shown in the following example:

```js
&#123;
  &quot;recipient_id&quot;: &quot;1254477777772919&quot;,
  &quot;message_id&quot;: &quot;AG5Hz2Uq7tuwNEhXfYYKj8mJEM_QPpz5jdCK48PnKAjSdjfipqxqMvK8ma6AC8fplwlqLP_5cgXIbu7I3rBN0P&quot;
&#125;
```


## Properties &#123;#properties&#125;

### `recipient`

Description of the message recipient. All requests must include one of the following properties to identify the recipient.

| Property | Type | Description |
| --- | --- | --- |
| `recipient.id` | String | IG Scoped User ID (IGSID) of the message recipient. |

### `message`

Description of the message to be sent.

| Property | Type | Description |
| --- | --- | --- |
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
| `text` | String | UTF-8-encoded text of up to 640 characters. The text appears above the buttons. |
| `buttons` | Array&lt;button&gt; | Set of 1-3 buttons that appear as call-to-actions. |


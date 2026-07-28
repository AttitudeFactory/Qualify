# Generic Template



The generic template allows you to send a structured message that includes an image, text, and buttons. A generic template with multiple templates described in the [`elements`](#elements) array will send a horizontally scrollable carousel of items, each composed of an image, text, and buttons.

### Limitations
This feature is currently not available in the web version.

## Request URI &#123;#request_uri&#125;

```
https://graph.facebook.com/v25.0/me/messages?access_token=&lt;PAGE_ACCESS_TOKEN&gt;
```

## Example request &#123;#example_request&#125;

```curl
curl -X POST -H &quot;Content-Type: application/json&quot; -d &#039;&#123;
  &quot;recipient&quot;:&#123;
    &quot;id&quot;:&quot;&lt;IGSID&gt;&quot;
  &#125;,
  &quot;message&quot;:&#123;
    &quot;attachment&quot;:&#123;
      &quot;type&quot;:&quot;template&quot;,
      &quot;payload&quot;:&#123;
        &quot;template_type&quot;:&quot;generic&quot;,
        &quot;elements&quot;:[
           &#123;
            &quot;title&quot;:&quot;Welcome!&quot;,
            &quot;image_url&quot;:&quot;https://github.com/fbsamples/original-coast-clothing/blob/main/public/looks/male-work.jpg&quot;,
            &quot;subtitle&quot;:&quot;We have the right hat for everyone.&quot;,
            &quot;default_action&quot;: &#123;
              &quot;type&quot;: &quot;web_url&quot;,
              &quot;url&quot;: &quot;https://www.originalcoastclothing.com&quot;,
            &#125;,
            &quot;buttons&quot;:[
              &#123;
                &quot;type&quot;:&quot;web_url&quot;,
                &quot;url&quot;:&quot;https://www.originalcoastclothing.com&quot;,
                &quot;title&quot;:&quot;View Website&quot;
              &#125;,&#123;
                &quot;type&quot;:&quot;postback&quot;,
                &quot;title&quot;:&quot;Start Chatting&quot;,
                &quot;payload&quot;:&quot;DEVELOPER_DEFINED_PAYLOAD&quot;
              &#125;
            ]
          &#125;
        ]
      &#125;
    &#125;
  &#125;
&#125;&#039; &quot;https://graph.facebook.com/v10.0/me/messages?access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot;
```

## Example response &#123;#example_response&#125;

```js
&#123;
  &quot;recipient_id&quot;: &quot;1254477777772919&quot;,
  &quot;message_id&quot;: &quot;AG5Hz2Uq7tuwNEhXfYYKj8mJEM_QPpz5jdCK48PnKAjSdjfipqxqMvK8ma6AC8fplwlqLP_5cgXIbu7I3rBN0P&quot;
&#125;
```


## Properties &#123;#properties&#125;

### `recipient` &#123;#recipient&#125;

Description of the message recipient. All requests must include one of the following properties to identify the recipient.

| Property | Type | Description |
| --- | --- | --- |
| `recipient.id` | String | IG Scoped User ID (IGSID) of the message recipient. |

### `message` &#123;#message&#125;

Description of the message to be sent.

| Property | Type | Description |
| --- | --- | --- |
| `message.attachment` | Object | An object describing attachments to the message. |

### `message.attachment` &#123;#attachment&#125;

| Property | Type | Description |
| --- | --- | --- |
| `type` | String | Value must be `template` |
| `payload` | Object | [`payload`](#payload) of the template. |

### `message.attachment.payload` &#123;#payload&#125;

| Property | Type | Description |
| --- | --- | --- |
| `template_type` | String | Value must be `generic` |
| `elements` | Array&lt;[`element`](#elements)&gt; | An array of [`element`](#elements) objects that describe instances of the generic template to be sent. Specifying multiple elements will send a horizontally scrollable carousel of templates. A maximum of 10 elements is supported. |

### `message.attachment.payload.elements` &#123;#elements&#125;

The generic template supports a maximum of 10 elements per message. At least one property must be set in addition to `title`.

| Property Name | Type | Description |
| --- | --- | --- |
| `title` | String | The title to display in the template. 80 character limit. |
| `subtitle` | String | ***Optional.*** The subtitle to display in the template. 80 character limit. |
| `image_url` | String | ***Optional.*** The URL of the image to display in the template. |
| `default_action` | Object | ***Optional.*** The default action executed when the template is tapped. Accepts the same properties as [URL button](https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages/buttons), except `title`. |
| `buttons` | Array&lt;[`button`](https://developers.facebook.com/documentation/business-messaging/messenger-platform/reference/buttons)&gt; | ***Optional.*** An array of [buttons](https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages/buttons) to append to the template. A maximum of 3 buttons per element is supported. Only `postback` and `web_url` buttons are supported. |

## Learn more

Visit the [`message.attachment.data`](https://developers.facebook.com/docs/graph-api/reference/message) for GIFs and Stickers.

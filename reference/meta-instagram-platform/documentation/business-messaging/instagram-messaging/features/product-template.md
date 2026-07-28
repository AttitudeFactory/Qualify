# Product Template for Instagram Messaging



Send Instagram messages with product information that you have uploaded to [your product catalog](https://www.facebook.com/business/help/1275400645914358) using the product template. The product template automatically pulls product details (image, title, price) from the product catalog.

You can create messages that have one product or a horizontally scrollable carousel of products using the product template.

## Before you start

You will need:

* The ID, or IDs, for the product from your Facebook catalog – You can get IDs from [Catalog API](https://developers.facebook.com/documentation/ads-commerce/catalog) or [Commerce Manager](https://www.facebook.com/business/help/2371372636254534).
* A Page Access Token from the Page that owns the products in the catalog
* [Meta Webhooks for Instagram Messaging subscriptions](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/webhooks)
* The ID for your Instagram Professional account
* The ID for the Page linked to your Instagram Professional account
* The Instagram Scoped ID for the person to whom you are sending the message

## Send a product message

To send a product message to a person, send a `POST` request to the `/PAGE-ID/messages` endpoint with the `recipient.id` property set to the Instagram-scoped ID of the person receiving the message. Include the `type` and `payload` properties in the `message.attachment` object. Set `type` to `template` and set the `payload.template_type` property to `product` and `payload.elements` to a list of product ID key-value pairs.

```curl
curl -X POST -H &quot;Content-Type: application/json&quot; -d &#039;&#123;
  &quot;recipient&quot;:&#123;
    &quot;id&quot;:&quot;INSTAGRAM-SCOPED-ID&quot;
  &#125;,
  &quot;message&quot;:&#123;
    &quot;attachment&quot;:&#123;
      &quot;type&quot;:&quot;template&quot;,
      &quot;payload&quot;: &#123;
        &quot;template_type&quot;: &quot;product&quot;,
        &quot;elements&quot;: [
          &#123;
            &quot;id&quot;: &quot;PRODUCT-ID&quot;
          &#125;
        ]
      &#125;
    &#125;
  &#125;
&#125;&#039; &quot;https://graph.facebook.com/LATEST-GRAPH-API-VERSION/PAGE-ID/messages?access_token=PAGE-ACCESS-TOKEN&quot;
```

### Send a carousel

To send a product carousel, add more product key-value pairs to the `payload.elements` property. You can include up to 10 products in your request.

```json
...
      &quot;payload&quot;: &#123;
        &quot;template_type&quot;: &quot;product&quot;,
        &quot;elements&quot;: [
          &#123;
            &quot;id&quot;: &quot;PRODUCT-ID-1&quot;
          &#125;,
          &#123;
            &quot;id&quot;: &quot;PRODUCT-ID-2&quot;
          &#125;,
          &#123;
            &quot;id&quot;: &quot;PRODUCT-ID-3&quot;
          &#125;
        ]
      &#125;
...
```

On success your app will receive the following JSON object with the recipient ID and the message ID.

```js
&#123;
  &quot;recipient_id&quot;: &quot;1254477777772919&quot;,
  &quot;message_id&quot;: &quot;AG5Hz2Uq7tuwNEhXfYYKj8mJEM_QPpz5jdCK48PnKAjSdjfipqxqMvK8ma6AC8fplwlqLP_5cgXIbu7I3rBN0P&quot;
&#125;
```


## Send an opt-in request

To send an opt-in request to a person to receive recurring marketing messages, send a `POST` request to `/PAGE-ID/messages` endpoint with the `recipient.id` property set to the Instagram-scoped ID of the person receiving the message. In the `message` `attachment.payload` property set `template_type` to `notification_messages`. In the `payload.elements` property include the `image_url`, `title`, `payload`, `notification_messages_frequency`, and `notification_messages_cta_text`.

```curl
curl -X POST -H &quot;Content-Type:application/json&quot; -d &#039;&#123;
  &quot;recipient&quot;: &#123;
    &quot;id&quot;: &quot;INSTAGRAM-SCOPED-ID&quot;
  &#125;,
  &quot;message&quot;: &#123;
    &quot;attachment&quot;: &#123;
      &quot;type&quot;: &quot;template&quot;,
      &quot;payload&quot;: &#123;
        &quot;template_type&quot;: &quot;notification_messages&quot;,
        &quot;elements&quot;: [
          &#123;
            &quot;image_url&quot;: &quot;IMAGE-URL&quot;,
            &quot;title&quot;: &quot;TEXT-TO-DISPLAY&quot;,
            &quot;payload&quot;: &quot;INFORMATION-ABOUT-THIS-MESSAGE&quot;,
            &quot;notification_messages_frequency&quot;: &quot;DAILY&quot;,
            &quot;notification_messages_cta_text&quot;: &quot;GET_UPDATES&quot;
          &#125;
        ]
      &#125;
    &#125;
  &#125;
&#125;&#039; &quot;https://graph.intern.facebook.com/LATEST-GRAPH-API-VERSION/PAGE-ID/messages?access_token=PAGE-ACCESS-TOKEN&quot;
```

### Properties

| Property | Value |
| --- | --- |
| `image_url`  &lt;br&gt;*string* | The URL for the image to display in the template |
| `notification_messages_cta_text`  &lt;br&gt;*enum &#123;&lt;br&gt;`ALLOW`,&lt;br&gt;`FREQUENCY`,&lt;br&gt;`GET`,&lt;br&gt;`GET_UPDATES`,&lt;br&gt;`OPT_IN`,&lt;br&gt;`SIGN_UP` &#125;&lt;br&gt;* | Set the call-to-action button text using one of the following values:&lt;br&gt;&lt;br&gt;* `ALLOW` – set opt-in message button text to **Allow messages**&lt;br&gt;* `FREQUENCY` – set opt-in message button text to **Get daily messages**&lt;br&gt;* `GET` – set opt-in message button text to **Get messages**&lt;br&gt;* `GET_UPDATES` – set opt-in message button text to **Get updates**, this is also default if `notification_messages_cta_text` is not set&lt;br&gt;* `OPT_IN` – set opt-in message button text to **Opt in to messages**&lt;br&gt;* `SIGN_UP` – set opt-in message button text to **Sign up for messages** |
| `notification_messages_frequency`  &lt;br&gt;*enum &#123;&lt;br&gt;`DAILY`,&lt;br&gt;`WEEKLY`,&lt;br&gt;`MONTHLY` &#125;&lt;br&gt;* | Message frequency for this recurring notification opt-in request.&lt;br&gt;&lt;br&gt;* `DAILY` – Opt in to receive one notification per 24 hour period for 6 months&lt;br&gt;* `WEEKLY` – Opt in to receive one notification per 7 day period for 9 months&lt;br&gt;* `MONTHLY` – Opt in to receive one notification per 1 month period for 12 months |
| `payload`  &lt;br&gt;*string* | The type of recurring notification, such as promotional messaging or product release messaging, for this recurring notification opt-in request |
| `title`  &lt;br&gt;*string* | The title to display in the template, cannot exceed 65 characters. If no value is assigned, the value defaults to &quot;Updates and promotions&quot; |

## Next steps

Now that people have opted in to receive recurring marketing messages, learn how to [send your marketing messages](https://developers.facebook.com/docs/messenger-platform/instagram/features/recurring-notifications#message-attachment-payload).

## See also

* [Common Error Codes Reference](https://developers.facebook.com/documentation/business-messaging/messenger-platform/error-codes)
* [Message Attachment Payload Reference](https://developers.facebook.com/docs/messenger-platform/instagram/features/recurring-notifications#message-attachment-payload)

# Send a Message



This document contains the requirements for sending freeform messages from your Instagram Professional account to your customers or people interested in your account using the Messenger Platform from Meta.

**Note:** If your app users don&#039;t have a Facebook Page linked to their Instagram professional account, learn more about building an app with [the Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram/platform/instagram-api).


You can send a freeform message that contains:

* one or more images, a video, or an audio file
* a reaction or sticker
* text, including a link

## Before you start

This guide assumes you have read the [Messenger Platform Overview](https://developers.facebook.com/documentation/business-messaging/messenger-platform/overview) and implemented the needed components such as a Facebook Page linked to your Instagram Professional account (or test Page), registered as a Meta developer, and created a Business App ID with the Messenger &gt; Instagram Messaging product in the App Dashboard.

You may also want to check the [status of the Meta Developer Platform](https://metastatus.com/#developerplatform) to ensure there are no issues.

### Requirements

* The ID for the Facebook Page linked to your Instagram Professional account
* The Instagram-scoped ID for customer who sent your business a message
* A Page access token requested from a person who can perform the `MESSAGE` task on the Facebook Page linked to your Instagram Professional account
* The `instagram_manage_messages` permission

### Limitations

- Apps with Standard Access can only send messages to people that have a role on the app
- Text message must be less than 1000 characters
- Media attachments can be:

| Media Type | Supported Format | Supported Size Maximum |
| --- | --- | --- |
| Audio | aac, m4a, wav, mp4 | 25MB |
| Image | png, jpeg | 8MB |
| Video | mp4, ogg, avi, mov, webm | 25MB |
| File | pdf | 25MB |

For more information about media attachments, see [Upload Media for Instagram Messaging](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/attachment-upload).

## Send a basic message

To send a message that contains text or a link, send a `POST` request to the `/PAGE-ID/messages` endpoint with the `recipient` parameter containing the Instagram-scoped ID (IGSID) and the `message` parameter containing the text or link.

Message text must be UTF-8 and be 1,000 bytes or less. Links must be valid formatted URLs.

### Sample request

_Formatted for readability._

```curl
curl -i -X POST \
  &quot;https://graph.facebook.com/&lt;API_VERSION&gt;/me/messages?access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot; \
  --data &#039;recipient=&#123;&quot;id&quot;:&quot;IGSID&quot;&#125;&amp;message=&#123;&quot;text&quot;:&quot;TEXT-OR-LINK&quot;&#125;&#039;
```

**Sample API response**

Upon success, your app receives the following JSON response:

```json
&#123;
  &quot;recipient_id&quot;: &quot;IGSID&quot;,
  &quot;message_id&quot;: &quot;MESSAGE-ID&quot;
&#125;
```

## Send an image

To send an image, send a `POST` request to the `/me/messages` endpoint with the `recipient` parameter containing the Instagram-scoped ID (`&lt;IGSID&gt;`) and the `message` parameter containing up to ten `attachment` objects with `type` set to `image` and `payload` containing `url` set to the URL for the image.

### Sample request: Sending one image

_Formatted for readability._

```curl
curl -X POST &quot;https://graph.facebook.com/&lt;API_VERSION&gt;/me/messages?access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot; \
     -H &quot;Content-Type: application/json&quot; \
     -d &#039;&#123;
           &quot;recipient&quot;:&#123;
               &quot;id&quot;:&quot;&lt;IGSID&gt;&quot;
           &#125;,
           &quot;message&quot;:&#123;
              &quot;attachment&quot;: &#123;
                 &quot;type&quot;:&quot;image&quot;,
                 &quot;payload&quot;:&#123;
                   &quot;url&quot;:&quot;&lt;IMAGE_URL&gt;&quot;
                 &#125;
              &#125;
           &#125;
         &#125;&#039;
```

### Sample request: Sending multiple images with image URL

_Formatted for readability._

```curl
curl -X POST &quot;https://graph.facebook.com/&lt;API_VERSION&gt;/me/messages?access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot; \
     -H &quot;Content-Type: application/json&quot; \
     -d &#039;&#123;
           &quot;recipient&quot;:&#123;
               &quot;id&quot;:&quot;&lt;IGSID&gt;&quot;
           &#125;,
           &quot;message&quot;:&#123;
              &quot;attachments&quot;:[
                 &#123;
                   &quot;type&quot;:&quot;image&quot;,
                   &quot;payload&quot;:&#123;
                     &quot;url&quot;:&quot;&lt;IMAGE_URL&gt;&quot;
                   &#125;
                 &#125;,
                 &#123;
                   &quot;type&quot;:&quot;image&quot;,
                   &quot;payload&quot;:&#123;
                     &quot;url&quot;:&quot;&lt;IMAGE_URL&gt;&quot;
                   &#125;
                 &#125;,
                 &#123;
                    ...
                 &#125;
              ]
           &#125;
         &#125;&#039;
```

### Sample request: Sending multiple images with attachment ID

The same images can be uploaded using the [Attachment Upload API](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/attachment-upload) and sent to many different users to avoid the delays and timeouts of uploading multiple high-resolution images. You can also mix both `url` and `attachment_id` parameters in the `payload`.

_Formatted for readability._

```curl
curl -X POST &quot;https://graph.facebook.com/&lt;API_VERSION&gt;/me/messages?access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot; \
     -H &quot;Content-Type: application/json&quot; \
     -d &#039;&#123;
           &quot;recipient&quot;:&#123;
               &quot;id&quot;:&quot;&lt;IGSID&gt;&quot;
           &#125;,
           &quot;message&quot;:&#123;
              &quot;attachments&quot;:[
                 &#123;
                   &quot;type&quot;:&quot;image&quot;,
                   &quot;payload&quot;:&#123;
                     &quot;attachment_id&quot;:&quot;&lt;attachment_ID&gt;&quot;
                   &#125;
                 &#125;,
                 &#123;
                   &quot;type&quot;:&quot;image&quot;,
                   &quot;payload&quot;:&#123;
                     &quot;attachment_id&quot;:&quot;&lt;attachment_ID&gt;&quot;
                   &#125;
                 &#125;,
                 &#123;
                    ...
                 &#125;
              ]
           &#125;
         &#125;&#039;
```

**Sample API responses**

Upon success, your app receives the following JSON response:

```json
&#123;
  &quot;recipient_id&quot;: &quot;IGSID&quot;,
  &quot;message_id&quot;: &quot;MESSAGE-ID&quot;
&#125;
```

## Send a published post

To send a message that contains a post you published to Instagram, send a `POST` request to the `/PAGE-ID/messages` endpoint with the `recipient` parameter containing the Instagram-scoped ID (IGSID) and the `message` parameter containing an `attachment` object with the `type` set to `MEDIA_SHARE` and `payload` containing the Meta ID for the post.

Your business must own the media you send in the message.

### Sample request

_Formatted for readability._

```curl
curl -i -X POST \
  &quot;https://graph.facebook.com/&lt;API_VERSION&gt;/me/messages?access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot; \
  --data &#039;recipient=&#123;&quot;id&quot;:&quot;IGSID&quot;&#125;&amp;message=&#123;
      &quot;attachment&quot;:
        &#123;
          &quot;type&quot;:&quot;MEDIA_SHARE&quot;,
          &quot;payload&quot;:&#123;&quot;id&quot;:&quot;POST-ID&quot;&#125;
        &#125;
&#125;&#039;
```

**Sample API response**

Upon success, your app receives the following JSON response:

```json
&#123;
  &quot;recipient_id&quot;: &quot;IGSID&quot;,
  &quot;message_id&quot;: &quot;MESSAGE-ID&quot;
&#125;
```

## Send a sticker

To send a heart sticker, send a `POST` request to the `/PAGE-ID/messages` endpoint with the `recipient` parameter containing the Instagram-scoped ID (IGSID) and the `message` parameter containing an `attachment` object with the `type` set to `like_heart`.

### Sample request

_Formatted for readability._

```curl
curl -i -X POST \
  &quot;https://graph.facebook.com/&lt;API_VERSION&gt;/me/messages?access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot; \
  --data &#039;recipient=&#123;&quot;id&quot;:&quot;IGSID&quot;&#125;&amp;message=&#123;
      &quot;attachment&quot;:
        &#123;
          &quot;type&quot;:&quot;like_heart&quot;
        &#125;
&#125;&#039;
```

**Sample API response**

Upon success, your app receives the following JSON response:

```json
&#123;
  &quot;recipient_id&quot;: &quot;IGSID&quot;,
  &quot;message_id&quot;: &quot;MESSAGE-ID&quot;
&#125;
```

## React to a message

To send a reaction, send a `POST` request to the `/PAGE-ID/messages` endpoint with the `recipient` parameter containing the Instagram-scoped ID (IGSID) and the `sender_action` parameter to `react` with the `payload` containing the `message_id` set to the ID for the message to apply the reaction to and `reaction` to `love`.

### Sample request

_Formatted for readability._

```curl
curl -i -X POST \
  &quot;https://graph.facebook.com/&lt;API_VERSION&gt;/me/messages?access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot; \
  --data &#039;recipient=&#123;&quot;id&quot;:&quot;IGSID&quot;&#125;&amp;sender_action=react&amp;payload=&#123;
      &quot;message_id&quot;:&quot;MESSAGE-ID&quot;,
      &quot;reaction&quot;:&quot;love&quot;
&#125;&#039;
```

### Unreact to a message

To remove a reaction from a message, send a `POST` request to the `/PAGE-ID/messages` endpoint with the `recipient` parameter containing the Instagram-scoped ID (IGSID) and the `sender_action` parameter to `unreact` with the `payload` containing the `message_id` set to the ID for the message from which to remove the reaction.

### Sample request

_Formatted for readability._

```curl
curl -i -X POST \
  &quot;https://graph.facebook.com/&lt;API_VERSION&gt;/me/messages?access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot; \
  --data &#039;recipient=&#123;&quot;id&quot;:&quot;IGSID&quot;&#125;&amp;sender_action=&quot;unreact&quot;&amp;payload=&#123;
      &quot;message_id&quot;:&quot;MESSAGE-ID&quot;
&#125;&#039;
```

**Sample API response**

Upon success, your app receives the following JSON response for react and unreact requests:

```json
&#123;
  &quot;recipient_id&quot;: &quot;IGSID&quot;
&#125;
```

## Send a reply

To send a reply to a specific past message within the chat, send a `POST` request to the `/PAGE-ID/messages` endpoint with the `recipient` parameter containing the Instagram-scoped ID (IGSID), your message details in the `message` parameter object, and the `reply_to` object with `mid` set to the message id of the specific message in the chat you want to reply to. The message can either be the message your business sent, or the user had sent.

You can send a text message, media message, template message as a reply to a message by using the `reply_to` object.

### Sample request

_Formatted for readability._

```curl
curl -X POST &quot;https://graph.facebook.com/&lt;API_VERSION&gt;/me/messages?access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot; \
     -H &quot;Content-Type: application/json&quot; \
     -d &#039;&#123;
           &quot;recipient&quot;:&#123;
               &quot;id&quot;:&quot;&lt;IGSID&gt;&quot;
           &#125;,
           &quot;message&quot;:&#123;
              &quot;text&quot;: &quot;TEXT&quot;
           &#125;,
           &quot;reply_to&quot;: &#123;
              &quot;mid&quot;: &quot;&lt;MESSAGE_ID&gt;&quot;
           &#125;
         &#125;&#039;
```

**Sample API response**

Upon success, your app receives the following JSON response with the recipient&#039;s ID and the message ID:

```json
&#123;
  &quot;recipient_id&quot;: &quot;IGSID&quot;,
  &quot;message_id&quot;: &quot;MESSAGE-ID&quot;
&#125;
```

## Next steps

* [Upload media such as audio, or image](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/attachment-upload) to Meta servers to be used in multiple messages.

* Send a structured message such as a [generic template](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/generic-template), a [product template](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/product-template), or a [persistent menu](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/persistent-menu).

## See also

* [Error Codes](https://developers.facebook.com/documentation/business-messaging/messenger-platform/error-codes)
* [Rate Limits for Instagram Messaging](https://developers.facebook.com/documentation/business-messaging/messenger-platform/overview)
* [Get the Media ID for your Media Assets](https://developers.facebook.com/docs/instagram-api/reference/ig-media)  

### Developer Support

* Use the  [Meta Status tool](https://metastatus.com) to check for the status and outages of Meta business products.
* Use the [Meta Developer Support tool](https://developers.facebook.com/support) to report bugs and view reported bugs, get help with Ads or Business Manager, and more.


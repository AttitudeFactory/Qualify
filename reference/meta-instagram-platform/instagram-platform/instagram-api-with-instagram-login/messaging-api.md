# Send Messages



This guide shows you how to send a message to an Instagram user from your Instagram professional account using the Instagram API with Instagram Login.

## How It Works

The Instagram API with Instagram Login enables your app users to send and receive messages between their Instagram professional account and their customers, potential customers, and followers.

#### An Instagram user sends a message

Conversations only begin when an Instagram user sends a message to your app user through your app user's Instagram Feed, posts, story mentions, and other channels.

#### Instagram Inbox

An Instagram professional account has a messaging inbox that allows the user to organize messages and control message notifications however when using the API the behavior will be a little different.

* **General** – Only after your app user to respond to a message, using your app, is the conversation  moved to the General folder, regardless of the inbox settings.
* **Primary** – All new conversations from followers will initially appear in the Primary folder.
* **Requests** – All new conversations from Instagram users who aren't followers of your app user will appear in the Requests folder.

[Learn more about the Instagram Inbox.](https://www.facebook.com/business/help/1264898753662278)

#### Inbox Limitations

* Inbox folders are not supported and messages delivered by the Messenger Platform do not include folder information that is shown in the Instagram from Meta app inbox folder
* Webhooks notifications or messages delivered via the API will not be considered as **Read** in the Instagram app inbox. Only after a reply is sent will a message be considered **Read**.

#### A webhook notification is sent

When an Instagram user sends a message to your app user, an event is triggered, and a webhook notification is sent to your webhook server. The notification contains the Instagram user's Instagram-scoped ID and their message. Your app user can use this information to respond.

#### Send a message

Only after an Instagram user has sent your app user's Instagram professional account a message can your app send a message to the Instagram user. Your app has 24 hours to respond to any message sent from an Instagram user to your app user.

Messages can contain the following:

* Audio files
* Images
* Instagram posts (owned by your app user)

* Links
* Reactions
* Stickers

* Templates
* Text
* Videos
* PDF Files

#### Automated experiences

You can provide an escalation path for automated messaging experiences using one of the following:

- **A Single App** – You can create a custom inbox to receive or reply to messages from a person. This custom inbox is powered by the same messaging app that also provides the automated experience

- **Multiple Apps** – [Handover Protocol](https://developers.facebook.com/docs/messenger-platform/handover-protocol) allows you pass the conversation from one app or inbox to another. For example, one app would handle the conversation with an automated experience and, when needed, would pass the conversation to another app to continue the conversation with a human agent.

#### Informing Users About Your Automated Experience

When required by applicable law, automated chat experiences must disclose that a person is interacting with an automated service:

* at the beginning of any conversation or message thread,
* after a significant lapse of time, or
* when a chat moves from human interaction to automated experience.

Automated chat experiences that serve the following groups should pay special attention to this requirement:

* California market or California users
* German market or German users

Disclosures may include but are not limited to: “I’m the [Page Name] bot,”“You are interacting with an automated experience,” “You are talking to a bot,” or “I am an automated chatbot.”

Even where not legally required, we recommend informing users when they’re interacting with an automated chat as best practice, as this helps manage user expectations about their interaction with your messaging experience.

Visit our
[Developer Policies](https://developers.facebook.com/devpolicy/#messengerplatform)
for more information.

#### Human agent experiences

If your app user uses a human agent to respond to messages and therefore may need more time to respond, your app can tag the response to allow your app to send the message outside the 24 hour messaging window.

You can provide an escalation path for human agent only messaging experiences with a custom inbox. Your messaging app must be able to:

- receive messages sent by people and render them correctly in the custom inbox

- reply to messages via the custom inbox and ensure people successfully received them

### Limitations

* Your app user must own any media or posts to be used in the message.
* Group messaging is not supported.  An Instagram professional account can only converse with one customer per conversation.
* Messages in the Requests folder that have not been active for 30 days will not be returned in API calls.
* Only the URL for the shared media or post is included in the webhooks notification when a customer sends a message with a share.
* Your app testers must have a role on your app, grant your app access to all the required permissions, and have a role on the Instagram professional account that owns the app.

## Requirements

This guide assumes you have read the [Instagram Platform Overview](https://developers.facebook.com/documentation/instagram-platform/overview) and implemented the needed components for using this API, such as a Meta login flow and a webhooks server to receive notifications.

You will need the following:

#### Access Level

* Advanced Access if your app serves Instagram professional accounts you don't own or manage
* Standard Access if your app serves Instagram professional accounts you own or manage or have added to your app in the App Dashboard; Some features may not work properly until your app has been granted Advanced Access

#### Access tokens

* An Instagram User access token requested from a person who can send a message from the Instagram professional account

#### Base URL

All endpoints can be accessed via the `graph.instagram.com` host.

#### Endpoints

* [`/<IG_ID>/messages`](https://developers.facebook.com/documentation/instagram-platform/reference) or `/me/messages`

##### Required Parameters

The following are required parameters for each API request:

* `recipient:{id:<IGSID>}`
* `message:{<MESSAGE_ELEMENTS>}`

#### IDs

* The app user's Instagram professional account ID (`<IG_ID>`) that received the message
* The Instagram-scoped ID (`<IGSID>`) for the Instagram user who sent the message to your app user, received from an Instagram messaging webhook notification

#### Permissions
* `instagram_business_basic`
* `instagram_business_manage_messages`

#### Webhook event subscriptions

* `messages`
* `messaging_optins`

* `messaging_postbacks`
* `messaging_reactions`

* `messaging_referrals`
* `messaging_seen`

#### Media types and specifications

| Media Type | Supported Format | Supported Size Maximum |
| --- | --- | --- |
| Audio | aac, m4a, wav, mp4 | 25MB |
| Image | png, jpeg | 8MB |
| Video | mp4, ogg, avi, mov, webm | 25MB |
| File | pdf | 25MB |

## Send a text message

To send a message that contains text or a link, send a `POST` request to the `/<IG_ID>/messages` endpoint with the `recipient` parameter containing the Instagram-scoped ID (`<IGSID>`) and the `message` parameter containing the text or link.

Message text must be UTF-8 and be a 1000 bytes or less. Links must be valid formatted URLs.

#### Sample Request

_Formatted for readability._

```curl
curl -X POST "https://graph.instagram.com/v25.0/<IG_ID>/messages"
     -H "Authorization: Bearer <INSTAGRAM_USER_ACCESS_TOKEN>"
     -H "Content-Type: application/json"
     -d '{
           "recipient":{
               "id":"<IGSID>"
           },
           "message":{
              "text":"<TEXT_OR_LINK>"
           }
        }'
```

## Send Images

To send images, send a `POST` request to the `/<IG_ID>/messages` endpoint with the `recipient` parameter containing the Instagram-scoped ID (`<IGSID>`) and the `message` parameter containing up to ten `attachment` objects with `type` set to `image` and `payload` containing `url` set to the URL for the image or GIF.

#### Sample Request: Sending a single image

_Formatted for readability._

```curl
curl -X POST "https://graph.instagram.com/v25.0/<IG_ID>/messages"
     -H "Authorization: Bearer <INSTAGRAM_USER_ACCESS_TOKEN>"
     -H "Content-Type: application/json"
     -d '{
           "recipient":{
               "id":"<IGSID>"
           },
           "message":{
             "attachments": {
               "type":"image",
               "payload":{
                 "url":"<IMAGE_URL>"
               }
             }
           }
         }'
```

#### Sample Request: Sending a collection of images with URLs

```curl
curl -X POST "https://graph.instagram.com/v25.0/<IG_ID>/messages"
     -H "Authorization: Bearer <INSTAGRAM_USER_ACCESS_TOKEN>"
     -H "Content-Type: application/json"
     -d '{
           "recipient":{
               "id":"<IGSID>"
           },
           "message":{
              "attachments":[
                 {
                   "type":"image",
                   "payload":{
                     "url":"<IMAGE_URL>",
                   },
                 },
                 {
                   "type":"image",
                   "payload":{
                     "url":"<IMAGE_URL>",
                   },
                 },
                 {
                    ...
                 }
              ]
           }
         }'
```

#### Sample Request: Sending a collection of images with attachment IDs

The same images can be uploaded using the [Attachment Upload API](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/attachment-upload) and sent to many different users to avoid the delays and timeouts of uploading multiple high-resolution images. You can also mix both `url` and `attachment_id` parameters in the `payload`.

```curl
curl -X POST "https://graph.instagram.com/v25.0/<IG_ID>/messages"
     -H "Content-Type: application/json"
     -d '{
           "recipient":{
               "id":"<IGSID>"
           },
           "message":{
              "attachments":[
                 {
                   "type":"image",
                   "payload":{
                     "attachment_id":"<attachment_ID>"
                   }
                 },
                 {
                   "type":"image",
                   "payload":{
                     "attachment_id":"<attachment_ID>"
                   }
                 },
                 {
                    ...
                 }
              ]
           }
         }'
```

#### Sample API Response for Message Sent Successfully

Upon success, your app will receive the following JSON response:

```json
{
  "recipient_id": "IGSID",
  "message_id": "MESSAGE-ID"
}
```

## Send audio, video or file

To send an audio, video, or file message, send a `POST` request to the `/<IG_ID>/messages` endpoint with the `recipient` parameter containing the Instagram-scoped ID (`<IGSID>`) and the `message` parameter containing the `attachment` object with `type` as `audio`, `video` or `file` and `payload` containing `url` set to the URL for the audio, video or file.

#### Sample Request

_Formatted for readability._

```curl
curl -X POST "https://graph.instagram.com/v25.0/<IG_ID>/messages"
     -H "Authorization: Bearer <INSTAGRAM_USER_ACCESS_TOKEN>"
     -H "Content-Type: application/json"
     -d '{
           "recipient":{
               "id":"<IGSID>"
           },
           "message":{
              "attachment":{
               "type":"audio",  // Or set to video or file
               "payload":{
                 "url":"<AUDIO_VIDEO_OR_FILE_URL>",
               }
             }
          }
        }'
```

## Send a Sticker

To send a heart sticker, send a `POST` request to the `/<IG_ID>/messages` endpoint with the `recipient` parameter containing the Instagram-scoped ID (`<IGSID>`) and the `message` parameter containing an `attachment` object with the `type` set to `like_heart`.

#### Sample Request

_Formatted for readability._

```curl
curl -X POST "https://graph.instagram.com/v25.0/<IG_ID>/messages"
     -H "Authorization: Bearer <INSTAGRAM_USER_ACCESS_TOKEN>"
     -H "Content-Type: application/json"
     -d '{
           "recipient":{
               "id":"<IGSID>"
           },
           "message":{
              "attachment":{
                "type":"like_heart",
              }
            }
         }'
```

## React or unreact to a message

To send a reaction, send a `POST` request to `/<IG_ID>/messages` with  `recipient`  containing the Instagram-scoped ID (`<IGSID>`); `sender_action` set to `react`; `payload` containing the `message_id` set to the message ID to react to; and `reaction` set to any emoji reaction(`<😊/🎉/etc>`) or a valid UTF-8 representation of an emoji.

To edit a sent reaction, repeat this request with the reaction set to the new emoji reaction.

To remove a reaction, repeat this request with `sender_action` set to unreact with the payload containing `message_id` only.

#### Sample Request

_Formatted for readability._

```curl
curl -X POST "https://graph.instagram.com/v25.0/<IG_ID>/messages"
     -H "Authorization: Bearer <INSTAGRAM_USER_ACCESS_TOKEN>"
     -H "Content-Type: application/json"
     -d '{
           "recipient":{
               "id":"<IGSID>"
           },
           "sender_action":"react",  // Or set to unreact to remove the reaction
           "payload":{
             "message_id":"<MESSAGE_ID>",
  "reaction":"love /😊/ 🎉/ \ud83d\udc4b",      // Omit if removing a reaction
           }
         }'
```

## Send a Published Post

To send a message that contains an app user's Instagram post, send a `POST` request to the `/<IG_ID>/messages` endpoint with the `recipient` parameter containing the Instagram-scoped ID (`<IGSID>`) and the `message` parameter containing an `attachment` object with the `type` set to `MEDIA_SHARE` and `payload` containing the Meta ID for the post.

The app user must own the post to be used in the message. Learn how to
[get your app user's Instagram posts.](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started#posts)

[Learn how to fetch the media owned by the business.](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started#get-the-instagram-professional-account-s-media-objects)

#### Sample Request
_Formatted for readability._

```curl
curl -X POST "https://graph.instagram.com/v25.0/<IG_ID>/messages"
     -H "Authorization: Bearer <INSTAGRAM_USER_ACCESS_TOKEN>"
     -H "Content-Type: application/json"
     -d '{
           "recipient":{
               "id":"<IGSID>"
           },
           "message":{
              "attachment":{
                "type":"MEDIA_SHARE",
                "payload":{
                  "id":"<POST_ID>",
                }
              }
           }
        }'
```

## Next Steps

Learn how to send a [private reply](https://developers.facebook.com/documentation/instagram-platform/private-replies), [quick reply](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api/quick-replies), or [template](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api/generic-template).

# Send a Private Reply to a Commenter



This documents shows you how to programmatically send a private reply to a person who commented on your app user's Instagram professional post, reel, story, Live, or ad post.

## How It Works

Step 1. An Instagram user comments on your app user's Instagram professional post, reel, story, Live, or ad post.

Step 2. A webhook event is triggered and Meta sends your server a notification with information about the comment including:

* Your app user's Instagram professional account ID
* The commenter's Instagram-scoped ID and username
* The comment's ID
* The media's ID, if the commenter included media in their comment
* The text of the comment, if applicable

Step 3. Your app uses the comment's ID to send a private response directly to the Instagram user. This reply appears in the person's **Inbox**, if the person follows the Instagram professional account, or to the **Request** folder, if they do not.

Step 4. Your app can send this private reply within 7 days of the creation time of the comment, excepting Instagram Live, where replies can only be sent during the live broadcast. The private reply message includes a link to the commented post.

## Requirements

This guide assumes you have read the [Instagram Platform Overview](https://developers.facebook.com/documentation/instagram-platform/overview) and implemented the needed components for using this API, such as a Meta login flow and a webhooks server to receive notifications.

You need the following:

|  | Instagram API with Instagram Login | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User access token | * [Facebook Page access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`<br>* `instagram_business_manage_comments` | * `instagram_basic`<br>* `instagram_manage_comments`<br>* `pages_read_engagement`<br><br>If the app user was granted a role on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to your app user's Instagram professional account via the Business Manager, your app will also need:<br><br>* `ads_management`<br>* `ads_read` |
| **Webhooks** | * `comments`<br>* `live_comments` | * `comments`<br>* `live_comments` |

### Limitations

* Only one message can be sent to the commenter
* The message must be sent within 7 days of the comment was made on the post or reel
* For Instagram Live, private replies can only be sent during the live broadcast. Once the broadcast ends, private replies cannot be sent
* Follow-up messages can only be sent if the recipient responds, and must be sent within 24 hours of the response

## Send a Private Reply

To send a private reply to a commenter on your app user's Instagram professional post, reel, or story, send a `POST` request to the `<APP_USERS_IG_ID>/messages` endpoint. The `recipient` parameter should contain the comment's ID and the `message` parameter should contain the text you wish to send.

#### Sample request
*Formatted for readability.*

```html
curl -i -X POST "https://<HOST_URL>/<API_VERSION>/<APP_USERS_IG_ID>/messages"
     -H "Content-Type: application/json"
     -H "Authorization: Bearer <ACCESS_TOKEN>"
     -d '{
             "recipient":{
                 "comment_id": "<COMMENT_ID>"
             },
             "message": {
                 "text": "<COMMENT_TEXT>"
             }
         }'
```

On success, your app receives a JSON response with the recipient's Instagram-scoped ID and the ID for the message.

```json
{
  "recipient_id": "526...",   // The Instagram-scoped ID
  "message_id": "aWdfZ..."    // The ID for the private reply message
}
```

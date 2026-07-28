Graph API Version

[v25.0](#)

# Page Messages

The PageMessages endpoint allows your business to send a message to a customer from your Facebook Page in response to a message received from the customer.

## Reading

You can't perform this operation on this endpoint.

## Creating

You can make a POST request to `messages` edge from the following paths:

* [`/{page_id}/messages`](/docs/graph-api/reference/page/messages/)

When posting to this edge, no Graph object will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `folder`  enum {PARTNERSHIP} | folder |
| `message`  Object | Message data  Supports Emoji |
| `a2ui`  Object |  |
| `text`  UTF-8 string | Supports Emoji |
| `dynamic_text`  Object | Supports Emoji |
| `text`  UTF-8 string | RequiredSupports Emoji |
| `fallback_text`  UTF-8 string | Supports Emoji |
| `attachment`  Object | Supports Emoji |
| `type`  enum {IMAGE, VIDEO, AUDIO, FILE, LOCATION, TEMPLATE, FALLBACK, REEL, IG\_REEL, POST, IG\_POST, STICKER, LIKE\_HEART, MEDIA\_SHARE} | Required |
| `payload`  string | Supports Emoji |
| `attachments`  list<Object> |  |
| `type`  enum {IMAGE, VIDEO, AUDIO, FILE, LOCATION, TEMPLATE, FALLBACK, REEL, IG\_REEL, POST, IG\_POST, STICKER, LIKE\_HEART, MEDIA\_SHARE} | Required |
| `payload`  string | Supports Emoji |
| `quick_reply_type`  string |  |
| `quick_replies`  list<Object> | Supports Emoji |
| `title`  UTF-8 string | Supports Emoji |
| `content_type`  enum {LOCATION, USER\_PHONE\_NUMBER, USER\_EMAIL, USER\_CITY, USER\_BIRTHDAY, USER\_STATE, USER\_ZIP\_CODE, OPEN\_CAMERA, OPEN\_GALLERY, RECORD\_AUDIO, POLL, TEXT, OPEN\_NATIVE, STICKER, OPEN\_APP, P2P\_PAYMENT, TRANSPORTATION, CREATE\_EVENT, GIF, BIC\_OPT\_IN, DISPLAY\_PERSISTENT\_MENU, BUSINESS\_LEAD\_FORM} | Required |
| `image_url`  URL |  |
| `data`  Object |  |
| `app`  string |  |
| `dest_address`  string |  |
| `sticker_id`  numeric string or integer |  |
| `payment_amount`  integer |  |
| `payment_currency`  ISO 4217 Currency Code |  |
| `payment_type`  enum{pay, request} |  |
| `poll_options`  list<string> |  |
| `provider_name`  string |  |
| `native_uri`  string |  |
| `payload`  UTF-8 string | Supports Emoji |
| `sticker_id`  int64 |  |
| `template`  Object |  |
| `name`  string | Required |
| `language`  Object | Required |
| `code`  string | Required |
| `components`  list<Object> | Supports Emoji |
| `type`  enum {HEADER, BODY, TITLE, BUTTONS} | Required |
| `parameters`  list<Object> | Supports Emoji |
| `type`  string | Required |
| `text`  string |  |
| `payload`  string |  |
| `url`  string |  |
| `parameter_name`  string |  |
| `metadata`  string |  |
| `messaging_type`  enum {RESPONSE, UPDATE, MESSAGE\_TAG, UTILITY} | Messaging type of the message |
| `notification_type`  enum {REGULAR, SILENT\_PUSH, NO\_PUSH} | Default value: `REGULAR`  Push notification / buzz type |
| `payload`  string | payload  Supports Emoji |
| `persona_id`  numeric string | The ID of a Persona |
| `recipient`  Object | The recipient of the message  Required |
| `id`  numeric string |  |
| `email`  string |  |
| `ids`  list<numeric string> |  |
| `thread_key` |  |
| `google_chat_options`  JSON object |  |
| `send_to_workchat_only`  boolean |  |
| `reply_to`  Object | reply\_to |
| `mid`  string |  |
| `sender_action`  enum {MARK\_SEEN, TYPING\_ON, TYPING\_OFF, REACT, UNREACT} | Actions such as setting / unsetting typing indicators |
| `tag`  Message tag | The use case tag of the message to bypass the subscriptions permission check |
| `thread_control`  Object | thread\_control |
| `app_id`  numeric string |  |
| `control_type`  string |  |
| `metadata`  Object |  |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`thread_key`: string,

`recipient_id`: string,

`message_id`: string,

`attachment_id`: string,

`gchat_space_name`: string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 551 | This person isn't available right now. |
| 100 | Invalid parameter |
| 2022 | The ability to send commerce messages has been temporarily disabled for this application. |
| 613 | Calls to this api have exceeded the rate limit. |
| 10903 | This user cant reply to this activity |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 190 | Invalid OAuth 2.0 Access Token |
| 10900 | Activity already replied to |
| 200 | Permissions error |
| 10904 | The page has messages disabled in the settings |

You can make a POST request to `messages` edge from the following paths:

* [`/{page_id}/messages`](/docs/graph-api/reference/page/messages/)

When posting to this edge, no Graph object will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `message`  Object | Information about the message including the message ID, type, and contents  Supports Emoji |
| `a2ui`  Object |  |
| `text`  UTF-8 string | Supports Emoji |
| `dynamic_text`  Object | Supports Emoji |
| `text`  UTF-8 string | RequiredSupports Emoji |
| `fallback_text`  UTF-8 string | Supports Emoji |
| `attachment`  Object | Supports Emoji |
| `type`  enum {IMAGE, VIDEO, AUDIO, FILE, LOCATION, TEMPLATE, FALLBACK, REEL, IG\_REEL, POST, IG\_POST, STICKER, LIKE\_HEART, MEDIA\_SHARE} | Required |
| `payload`  string | Supports Emoji |
| `attachments`  list<Object> |  |
| `type`  enum {IMAGE, VIDEO, AUDIO, FILE, LOCATION, TEMPLATE, FALLBACK, REEL, IG\_REEL, POST, IG\_POST, STICKER, LIKE\_HEART, MEDIA\_SHARE} | Required |
| `payload`  string | Supports Emoji |
| `quick_reply_type`  string |  |
| `quick_replies`  list<Object> | Supports Emoji |
| `title`  UTF-8 string | Supports Emoji |
| `content_type`  enum {LOCATION, USER\_PHONE\_NUMBER, USER\_EMAIL, USER\_CITY, USER\_BIRTHDAY, USER\_STATE, USER\_ZIP\_CODE, OPEN\_CAMERA, OPEN\_GALLERY, RECORD\_AUDIO, POLL, TEXT, OPEN\_NATIVE, STICKER, OPEN\_APP, P2P\_PAYMENT, TRANSPORTATION, CREATE\_EVENT, GIF, BIC\_OPT\_IN, DISPLAY\_PERSISTENT\_MENU, BUSINESS\_LEAD\_FORM} | Required |
| `image_url`  URL |  |
| `data`  Object |  |
| `app`  string |  |
| `dest_address`  string |  |
| `sticker_id`  numeric string or integer |  |
| `payment_amount`  integer |  |
| `payment_currency`  ISO 4217 Currency Code |  |
| `payment_type`  enum{pay, request} |  |
| `poll_options`  list<string> |  |
| `provider_name`  string |  |
| `native_uri`  string |  |
| `payload`  UTF-8 string | Supports Emoji |
| `sticker_id`  int64 |  |
| `template`  Object |  |
| `name`  string | Required |
| `language`  Object | Required |
| `code`  string | Required |
| `components`  list<Object> | Supports Emoji |
| `type`  enum {HEADER, BODY, TITLE, BUTTONS} | Required |
| `parameters`  list<Object> | Supports Emoji |
| `type`  string | Required |
| `text`  string |  |
| `payload`  string |  |
| `url`  string |  |
| `parameter_name`  string |  |
| `metadata`  string |  |
| `messaging_type`  enum {RESPONSE, UPDATE, MESSAGE\_TAG, UTILITY} | The type of message you are sending.   * `MESSAGE_TAG` – A non-promotional message that is being sent outside the 24-hour messaging window with a message tag. * `RESPONSE` – A response to a received message. This includes promotional and non-promotional messages sent inside the 24-hour messaging window. * `UPDATE` – A message that is not in response to a received message. This includes promotional and non-promotional messages sent inside the 24-hour messaging window. |
| `notification_type`  enum {REGULAR, SILENT\_PUSH, NO\_PUSH} | Default value: `REGULAR`  The type of push notification the customer receives when your message is delivered |
| `payload`  string | Payload of the sender action  Supports Emoji |
| `persona_id`  numeric string | The ID for your business persona |
| `recipient`  Object | The customer receiving your message. An example object is `{ "id": "PSID" }`  Required |
| `id`  numeric string |  |
| `follow_id` |  |
| `story_id`  story\_id |  |
| `poll_response_id`  poll\_response\_id |  |
| `phone_number`  string |  |
| `name`  Object |  |
| `first_name`  string |  |
| `last_name`  string |  |
| `user_ref`  string |  |
| `comment_id` |  |
| `post_id`  string |  |
| `player_id`  numeric string |  |
| `one_time_notif_token`  string |  |
| `notification_messages_token`  string |  |
| `login_id`  string |  |
| `reply_to`  Object | Information of the specific existing message in the thread that you want to send a reply to. |
| `mid`  string |  |
| `sender_action`  enum {MARK\_SEEN, TYPING\_ON, TYPING\_OFF, REACT, UNREACT} | The action displayed to a customer to let the customer know that you have seen and are processing their message.   * `MARK_SEEN` – Indicates that you have received the customer's message * `REACT` – Indicates that you have reacted to the customer's message * `TYPING_OFF` – Turns off the typing indicator * `TYPING_ON` – Indicates that you are typing a response to the customer's message. Automatically turns off after 20 seconds or after a response is sent * `UNREACT` – Indicates that you have removed a reaction to the customer's message |
| `tag`  Message tag | A tag to allow your app to send a personalized message to a customer outside the 24-hour messaging window.   * `ACCOUNT_UPDATE` – For a non-recurring message sent to a customer containing a change to the customer's application or account. * `CONFIRMED_EVENT_UPDATE` – For a reminder or update for an event that a customer has registered for (RSVP'ed, purchased tickets). The message can be sent for upcoming events and events in progress. * `CUSTOMER_FEEDBACK` – For a message sent to a customer containing the Customer Feedback Template. The message can be sent within 7 days after the customer's last message. * `HUMAN_AGENT` – For a message sent to a customer from a human agent in response to the customer's inquiries. The message can be sent within 7 days after a customer's last message. * `POST_PURCHASE_UPDATE` – For a message sent to a customer containing an update about the customer's recent purchase.   Only `HUMAN_AGENT` is available for Instagram Messaging. |

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`recipient_id`: string,

`message_id`: string,

`attachment_id`: string,

}

### Error Codes

| Error | Description |
| --- | --- |
| 551 | This person isn't available right now. |
| 100 | Invalid parameter |
| 2022 | The ability to send commerce messages has been temporarily disabled for this application. |
| 613 | Calls to this api have exceeded the rate limit. |
| 10903 | This user cant reply to this activity |
| 368 | The action attempted has been deemed abusive or is otherwise disallowed |
| 190 | Invalid OAuth 2.0 Access Token |
| 10900 | Activity already replied to |
| 200 | Permissions error |
| 10904 | The page has messages disabled in the settings |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

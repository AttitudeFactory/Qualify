# Conversation Control APIs



Instagram Platform Conversation Routing provides Conversation Control APIs, allowing you to:

1. Pass control to another app
2. Release thread control from the current app
3. Take thread control from another app (primary behavior only)
4. Extend thread control for your app
5. Request control of a conversation from another app (default behavior only)
6. Determine which app currently controls a conversation
7. Check whether conversation routing is configured for your account

This document outlines the specifics of conversation control invocations to change or retrieve thread control details.

## Send API: Message send with thread controls

**Warning:** Thread control support within the Send API is only available when conversation routing is enabled.

### Pass thread control

You can pass thread control to a specific app by setting the `app_id` and `control_type` fields in the `thread_control` parameter.

If `app_id` is not specified, thread control will be passed to the default application.

#### Sample request

```curl
curl -X POST -H &quot;Content-Type: application/json&quot; -d &#039;&#123;
  &quot;messaging_type&quot;: &quot;RESPONSE&quot;,
  &quot;thread_control&quot;: &#123;
  &quot;app_id&quot;: &quot;&lt;APPLICATION_ID&gt;&quot;,
  &quot;control_type&quot;: &quot;pass&quot;
  &#125;,
  &quot;recipient&quot;: &#123;
  &quot;id&quot;: &quot;&lt;IGSID&gt;&quot;
  &#125;,
  &quot;message&quot;: &#123;
  &quot;text&quot; : &quot;Let me transfer you to our live agent&quot;
  &#125;
&#125;&#039; &quot;https://graph.facebook.com/v12.0/me/messages?access_token=&lt;ACCESS_TOKEN&gt;&quot;
```

#### Sample response

```json
&#123;
  &quot;recipient_id&quot;:&quot;&lt;IGSID&gt;&quot;,
  &quot;message_id&quot;:&quot;MESSAGE-ID&quot;
&#125;
```

### Release thread control

Release thread control by setting the `control_type` field in the `thread_control` parameter.

#### Sample request

```curl
curl -X POST -H &quot;Content-Type: application/json&quot; -d &#039;&#123;
  &quot;messaging_type&quot;: &quot;RESPONSE&quot;,
  &quot;thread_control&quot;: &#123;
    &quot;control_type&quot;: &quot;release&quot;
  &#125;,
  &quot;recipient&quot;: &#123;
    &quot;id&quot;: &quot;&lt;IGSID&gt;&quot;
  &#125;,
  &quot;message&quot;: &#123;
    &quot;text&quot; : &quot;Let me transfer you to our live agent&quot;
  &#125;
&#125;&#039; &quot;https://graph.facebook.com/v12.0/me/messages?access_token=&lt;ACCESS_TOKEN&gt;&quot;
```

#### Sample response

```json
&#123;
  &quot;recipient_id&quot;:&quot;&lt;IGSID&gt;&quot;,
  &quot;message_id&quot;:&quot;MESSAGE-ID&quot;
&#125;
```

| Parameter | Description |
| --- | --- |
| `thread_control` | Specifies which Conversation Routing control flow to invoke after sending the message. |
| `control_type` | Indicates whether to pass or release thread control.&lt;br&gt;&lt;br&gt;- `pass`: Passes thread control to the specified app (or the default app) and sends a webhook to the app telling it to continue the conversation.&lt;br&gt;- `release`: Releases thread control to idle. No webhook is sent. Should be used when the app in control determines that no further action is needed on the conversation. |
| `app_id` (optional) | Used in the pass thread control flow to define the application ID that should become the thread owner. |

## Thread control APIs

### Pass thread control
When your app needs to hand over the conversation to another application, send a POST request to the `/PAGE_ID/pass_thread_control` endpoint.

- Set the `recipient` parameter to the IGSID of the customer.

- Set the `target_app_id` parameter to the ID of the app that should get control.

- Optionally, set the `metadata` parameter with information about the conversation.

**Notes:**

- To pass control to an Inbox, use `263902037430900` for the Page Inbox and `1217981644879628` for the Instagram Inbox.

- This API can only be invoked if:

- You are the current thread owner, or

- The thread is in idle state

- If the target app is not specified, control will be passed to the default application (if conversation routing is enabled).

- The target app cannot be itself to extend thread control if you are the current owner.

#### Sample request

```curl
curl -X POST &quot;https://graph.facebook.com/LATEST-API-VERSION/PAGE-ID/pass_thread_control
  ?recipient=&#123;id:IGSID&#125;
  &amp;target_app_id=APP-GETTING-CONTROL
  &amp;metadata=Information about the conversation
  &amp;access_token=PAGE-ACCESS-TOKEN&quot;
```

#### Sample response

```json
&#123;
  &quot;success&quot; : true
&#125;
```

#### Webhook notification example

```json
&#123;
  &quot;sender&quot;:&#123;
     &quot;id&quot;:&quot;IGSID&quot; // The Instagram-scoped ID for the person who sent the message to the business
  &#125;,
  &quot;recipient&quot;:&#123;
     &quot;id&quot;:&quot;BusinessId&quot;
  &#125;,
  &quot;timestamp&quot;:UNIX-TIMESTAMP,
  &quot;pass_thread_control&quot;:&#123;
     &quot;previous_owner_app_id&quot;:&quot;APP-RELEASING-CONTROL&quot;,
      &quot;new_owner_app_id&quot;: &quot;APP-GETTING-CONTROL&quot;,
      &quot;metadata&quot;:&quot;Information about the conversation&quot;
  &#125;
&#125;
```

### Release thread control

Release control of the conversation (returning it to idle) as soon as your app is finished, rather than waiting for the response window to expire.

To release thread control, send a POST request to `/PAGE-ID/release_thread_control`.

- Set the `recipient` parameter to the ID of the person who sent the message.

- Optionally, set the `metadata` parameter.

**Notes:**

- Only the current thread owner can invoke this API.

#### Sample request

```curl
curl -X POST &quot;https://graph.facebook.com/LATEST-API-VERSION/PAGE-ID/release_thread_control
  ?recipient=&#123;id:IGSID&#125;
  &amp;metadata=Information about the conversation
  &amp;access_token=PAGE-ACCESS-TOKEN&quot;
```

#### Sample response

```json
&#123;
  &quot;success&quot; : true
&#125;
```

After a successful request, the conversation status changes to idle.

### Take thread control

To take control of a conversation, send a POST request to `/PAGE-ID/take_thread_control`.

- Set the `recipient` parameter to the ID of the person who sent the message.

- Optionally, set the `metadata` parameter.

**Notes:**

- Only supported when conversation routing is enabled.

- The thread control takeover setting must be enabled for the app in Page Settings → Page Setup → Advanced Messaging.

- You cannot invoke this API to extend thread control if you are already the thread owner.

#### Sample request

```curl
curl -X POST &quot;https://graph.facebook.com/LATEST-API-VERSION/PAGE-ID/take_thread_control
  ?recipient=&#123;id:ID&#125;
  &amp;metadata=Information about the conversation
  &amp;access_token=PAGE_ACCESS_TOKEN&quot;
```

#### Sample response

```json
&#123;
  &quot;success&quot; : true
&#125;
```

#### Webhook notification example

The thread owner from whom the control was taken will receive a notification with the IGSID for the person who sent the message, the ID for the Instagram Professional account that received the message, the ID for the previous app that controlled the conversation, the ID for the app that now controls the conversation, and any metadata about the conversation that was sent in the API request that triggered the webhook. If the thread was taken from idle state, no webhooks would be sent.

```json
&#123;
  &quot;sender&quot;:&#123;
    &quot;id&quot;:&quot;IGSID&quot;
  &#125;,
  &quot;recipient&quot;:&#123;
    &quot;id&quot;:&quot;BusinessId&quot;
  &#125;,
  &quot;timestamp&quot;:UNIX-TIMESTAMP,
  &quot;take_thread_control&quot;:&#123;
    &quot;previous_owner_app_id&quot;:&quot;PREVIOUS-OWNER-APP-ID&quot;,
    &quot;new_owner_app_id&quot;: &quot;NEW-OWNER-APP-ID&quot;,
    &quot;metadata&quot;:&quot;Information about the conversation&quot;
  &#125;
&#125;
```

### Extend thread control

To give your app more time to respond to a message, you can extend control past the 24-hour response time frame. You can extend the time up to 7 days.

To extend control of a conversation, send a POST request to `/PAGE-ID/extend_thread_control`.

- Set the `recipient` parameter to the ID of the person who sent the message.

- Set `duration` to the length of time in seconds.

**Notes:**

- Only the current thread owner can invoke this API.

#### Sample request

```curl
curl -X POST &quot;https://graph.facebook.com/LATEST-API-VERSION/PAGE-ID/extend_thread_control
  ?recipient=&#123;id:IGSID&#125;
  &amp;duration=86400   //Length of time, in seconds
  &amp;access_token=PAGE-ACCESS-TOKEN&quot;
```

#### Sample response

```json
&#123;
  &quot;success&quot; : true
&#125;
```

### Request thread control

**Warning:** Request Thread control is only available when conversation routing is not enabled (Default message routing behavior).

To request control of a conversation from another app, send a POST request to `/PAGE-ID/request_thread_control`.

- Set the `recipient` parameter to the PSID of the customer.

- Optionally, set the `metadata` parameter.

**Notes:**

- You cannot request thread control if you are already the thread owner.

- If the thread is idle, control will be passed to you and a pass thread control webhook will be sent.

#### Sample request

```curl
curl -X POST &quot;https://graph.facebook.com/LATEST-API-VERSION/PAGE-ID/request_thread_control
  ?recipient=&#123;id:PSID&#125;
  &amp;metadata=Information about the conversation
  &amp;access_token=PAGE-ACCESS-TOKEN&quot;
```

#### Sample response

```json
&#123;
  &quot;success&quot; : true
&#125;
```

#### Webhook notification example

The following webhook notification will be received by the current thread owner.

```json
&#123;
  &quot;sender&quot;:&#123;
     &quot;id&quot;:&quot;IGSID&quot; // The Instagram-scoped ID for the person who sent the message to the business
  &#125;,
  &quot;recipient&quot;:&#123;
     &quot;id&quot;:&quot;BusinessId&quot;
  &#125;,
  &quot;timestamp&quot;:UNIX-TIMESTAMP,
  &quot;request_thread_control&quot;:&#123;
     &quot;requested_owner_app_id&quot;:&quot;APP-ASKING-FOR-THREAD-CONTROL&quot;,
     &quot;metadata&quot;:&quot;Information about the conversation&quot;
  &#125;
&#125;
```

### Find the app in control

To find which app currently controls a conversation, send a GET request to `/PAGE-ID/thread_owner` with the `recipient` parameter set to the Instagram-scoped ID.

- Set the `recipient` parameter to the IGSID.

- Set the `access_token` parameter to your page access token.

#### Sample request

```curl
curl -X GET &quot;https://graph.facebook.com/LATEST-API-VERSION/PAGE-ID/thread_owner
  ?recipient=IGSID
  &amp;access_token=PAGE-ACCESS-TOKEN&quot;
```

#### Sample response

- If your app is the current thread owner or the default app, you&#039;ll receive the `app_id` and expiration timestamp.

- Otherwise, if the thread is not idle, you&#039;ll receive the expiration timestamp only.

- Otherwise, you&#039;ll receive an empty response.

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;thread_owner&quot;: &#123;
        &quot;app_id&quot;: APP-ID,
        &quot;expiration&quot;: UNIX-TIMESTAMP
      &#125;
    &#125;
  ]
&#125;
```

### Messaging feature status API

Check the Conversation Routing status of a Facebook Page for Messenger or a business ID for Instagram Direct (IGD) messaging.

- Send a GET request to `/v12.0/me` with the `fields=messaging_feature_status` and your `access_token`.

#### Sample request

```curl
curl -X GET &quot;https://graph.facebook.com/v12.0/me?fields=messaging_feature_status&amp;access_token=&lt;ACCESS_TOKEN&gt;&quot;
```

#### Sample response

```json
&#123;
  &quot;messaging_feature_status&quot;: &#123;
    &quot;hop_v2&quot;: false,
    &quot;msgr_multi_app&quot;: true,
    &quot;ig_multi_app&quot;: false
  &#125;,
  &quot;id&quot;: &quot;&lt;page_id&gt;&quot;
&#125;
```

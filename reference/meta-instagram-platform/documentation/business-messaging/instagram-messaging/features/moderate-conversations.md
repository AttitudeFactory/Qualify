# Moderate Conversations API for Instagram



This guide explains how to use the Moderate Conversations API to:

- Block a user
- Unblock a user
- Move a conversation to spam in the Meta Business Suite Inbox

## Before you start

This guide assumes you have read the [Messenger Platform Overview](https://developers.facebook.com/documentation/business-messaging/messenger-platform/overview) and implemented the needed components for sending and receiving messages and notifications.

You will need:

- The ID for the Facebook Page linked to your Instagram Professional account
- The Instagram-scoped ID for the customer you want to apply the action to
- A Page access token requested from a person who can perform the MESSAGE task on the Facebook Page linked to your Instagram Professional account
- `instagram_manage_messages`, `instagram_basic`, and `business_management` permissions. **Advanced Access** is required to use this API for conversations involving your business and people who **do not** have a role on your messaging app, your Facebook page, or your business
- A conversation must exist between the user and Instagram business before any of the actions provided by this API can be used

### Limitations

- Up to 10 IDs can be provided in each request
- Up to 2 actions can be specified in each request. `unblock_user` cannot be included in the same request as `block_user`
- You cannot block an Instagram user that is linked, through accounts center, to your Instagram business account

### Request parameters

#### `user_ids`

| Property | Description |
| --- | --- |
| `id` *string&lt;br&gt;* | Instagram-scoped ID for the person you want to apply the action to |

#### Actions

| Action | Description |
| --- | --- |
| `block_user` | Blocks user and Instagram business interactions on Instagram.&lt;br&gt;&lt;br&gt;Prevents a user from messaging the Instagram business and prevents the business from messaging the user. The user will not be able to find the business&#039;s profile, posts, or stories on Instagram. |
| `unblock_user` | Unblocks user and Instagram business interactions on Instagram.&lt;br&gt;&lt;br&gt;Allows the user and business to message each other again. The user will be able to view and interact with the business&#039;s content on Instagram. |
| `move_to_spam` | Marks the conversation as spam and moves the conversation to the spam folder in Meta Business Suite inbox. |

## Block a user

To block messaging with a user, send a `POST` request to the `/&lt;PAGE_ID&gt;/moderate_conversations` endpoint with the Instagram-scoped ID for the user and the `block_user` action.

#### Sample request

```curl
curl -X POST -H &quot;Content-Type: application/json&quot; -d &#039;&#123;
  &quot;user_ids&quot;:[
    &#123;
        &quot;id&quot;: &quot;&lt;IGSID&gt;&quot;
    &#125;
  ],
  &quot;actions&quot;: [
    &quot;block_user&quot;
  ]
&#125;&#039; &quot;https://graph.facebook.com/v22.0/&lt;PAGE_ID&gt;/moderate_conversations?access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot;
```

On success, your app will receive the following JSON response with the `success` field set to `true`. On failure, the `success` field will be set to `false`.

```curl
&quot;success&quot;: &quot;true&quot;
```

## Unblock a user

To unblock a user, send a `POST` request to the `/&lt;PAGE_ID&gt;/moderate_conversations` endpoint with the Instagram-scoped ID for the user and the `unblock_user` action.

#### Sample request

```curl
curl -X POST -H &quot;Content-Type: application/json&quot; -d &#039;&#123;
  &quot;user_ids&quot;:[
    &#123;
        &quot;id&quot;:&quot;&lt;IGSID&gt;&quot;
    &#125;
  ],
  &quot;actions&quot;: [
    &quot;unblock_user&quot;
  ]
&#125;&#039; &quot;https://graph.facebook.com/v22.0/&lt;PAGE_ID&gt;/moderate_conversations?access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot;
```

On success, your app will receive the following JSON response with the `success` field set to `true`. On failure, the `success` field will be set to `false`.

```curl
&quot;success&quot;: &quot;true&quot;
```

## Move conversation to spam

To mark a conversation as spam and move it to the spam folder in the Meta Business Suite inbox, send a `POST` request to `/&lt;PAGE_ID&gt;/moderate_conversations` with the Instagram-scoped ID for the user and the `move_to_spam` action.

#### Sample request

```curl
curl -X POST -H &quot;Content-Type: application/json&quot; -d &#039;&#123;
  &quot;user_ids&quot;:[
    &#123;
        &quot;id&quot;:&quot;&lt;IGSID&gt;&quot;
    &#125;
  ],
  &quot;actions&quot;: [
    &quot;move_to_spam&quot;
  ]
&#125;&#039; &quot;https://graph.facebook.com/v22.0/&lt;PAGE_ID&gt;/moderate_conversations?access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot;
```

On success, your app will receive the following JSON response with the `success` field set to `true`. On failure, the `success` field will be set to `false`.

```curl
&quot;success&quot;: &quot;true&quot;
```

## Perform multiple actions for multiple users

If you would like to perform multiple actions at once for a set of users, send a `POST` request to `/&lt;PAGE_ID&gt;/moderate_conversations` with the Instagram-scoped IDs for the users and a list of the actions that should be applied to the users.

#### Sample request

Block two users and move the conversations to spam.

```curl
curl -X POST -H &quot;Content-Type: application/json&quot; -d &#039;&#123;
  &quot;user_ids&quot;:[
    &#123;
        &quot;id&quot;:&quot;&lt;IGSID&gt;&quot;
    &#125;,
    &#123;
        &quot;id&quot;:&quot;&lt;IGSID&gt;&quot;
    &#125;
  ],
  &quot;actions&quot;: [
    &quot;block_user&quot;,
    &quot;move_to_spam&quot;
  ]
&#125;&#039; &quot;https://graph.facebook.com/v22.0/&lt;PAGE_ID&gt;/moderate_conversations?access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot;
```

On success, your app will receive the following JSON response with the `success` field set to `true`. On failure, the `success` field will be set to `false`.

```curl
&quot;success&quot;: &quot;true&quot;
```

## Error codes
If you encounter any of the following errors while trying to complete the request for multiple users, you can retry the request with one user at a time.

| Error Code | Message |
| --- | --- |
| `100` | Invalid parameter&lt;br&gt;&lt;br&gt;The provided user ids or actions may be invalid&lt;br&gt;&lt;br&gt;The user ID is not a valid PSID or IGSID&lt;br&gt;&lt;br&gt;Invalid actions |
| `1` | Failed to block Instagram user&lt;br&gt;&lt;br&gt;Failed to unblock Instagram user&lt;br&gt;&lt;br&gt;Instagram Direct thread not found between business and consumer&lt;br&gt;&lt;br&gt;Unexpected error: Failed to move Instagram thread to spam folder |


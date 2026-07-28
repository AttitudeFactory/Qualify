Graph API Version

[v25.0](#)

# Page Take Thread Control

Allows an app to take control of an idle conversation. If the app is a Primary Receiver, the app can take control of a conversation owned by another app. Part of the Messenger Platform Handover Protocol

## Reading

You can't perform this operation on this endpoint.

## Creating

You can make a POST request to `take_thread_control` edge from the following paths:

* [`/{page_id}/take_thread_control`](/docs/graph-api/reference/page/take_thread_control/)

When posting to this edge, a [Page](/docs/graph-api/reference/page/) will be created.

### Parameters

| Parameter | Description |
| --- | --- |
|  |  |
| --- | --- |
| `metadata`  string | Additional information about the conversation |
| `recipient`  Object | The PSID for the customer who sent the message to your business  Required |
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

### Return Type

This endpoint supports [read-after-write](/docs/graph-api/overview/#read-after-write) and will read the node to which you POSTed.

Struct {

`success`: bool,

}

### Error Codes

| Error | Description |
| --- | --- |
| 551 | This person isn't available right now. |
| 100 | Invalid parameter |
| 190 | Invalid OAuth 2.0 Access Token |
| 200 | Permissions error |

## Updating

You can't perform this operation on this endpoint.

## Deleting

You can't perform this operation on this endpoint.

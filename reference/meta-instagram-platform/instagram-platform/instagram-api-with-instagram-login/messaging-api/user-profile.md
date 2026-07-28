# Instagram User Profile API



The User Profile API allows your app to get an Instagram user's profile information using the user's Instagram-scoped ID received from an Instagram messaging webhook notification. Your app can use this information to create a personalized messaging experience for Instagram users who are interacting with your app users.

## User Consent

**User consent is required to access an Instagram user's profile.**

User consent is set only when an Instagram user sends a message to your app user, or clicks an icebreaker or persistent menu. If an Instagram user comments on a post or comment but has not sent a message to your app user, and your app tries to send the Instagram user a message, your app will receive an error, **User consent is required to access user profile.**

## Requirements

This guide assumes you have read the [Instagram Platform Overview](https://developers.facebook.com/documentation/instagram-platform/overview) and implemented the needed components for using this API, such as a Meta login flow and a webhooks server to receive notifications.

You will need the following:

#### Access Level

* Advanced Access if your app serves Instagram professional accounts you don't own or manage
* Standard Access if your app serves Instagram professional accounts you own or manage and have added to your app in the App Dashboard

#### Access tokens

* An Instagram user access token requested from your app user who received the webhook notification and who can manage messages on the Instagram professional account

#### Base URL

All endpoints can be accessed via the `graph.instagram.com` host.

#### Endpoints

- `/<IGSID>`

#### IDs

* The Instagram-scoped ID (`<IGSID>`) for the Instagram user interested in your app user; [received from a webhook notification](#webhook-notification)

#### Permissions
* `instagram_business_basic`
* `instagram_business_manage_messages`

#### Webhook event subscriptions

* `messages`
* `messaging_optins`
* `messaging_postbacks`
* `messaging_referral`

### Limitations

* If the Instagram user has blocked your app user, your app will not be able to view the Instagram user's information.

## Webhook notification

In order to get profile information for an Instagram user who has messaged your app user's Instagram professional account, you need the Instagram-scoped ID for the Instagram user that was sent in a message notification, the value of the `messages.sender.id` property.

```curl
{
  "object": "instagram",
  "entry": [
    {
      "id": "<YOUR_APP_USERS_IG_ID>",  // Your app user's Instagram Professional account ID
      "time": <UNIX_TIMESTAMP>,
      "messaging": [
        {
"sender": { "id": "<INSTAGRAM_SCOPED_ID>" },    // Instagram-scoped ID for the Instagram user who sent the message
...
```

## Get profile information

To get an the Instagram user's profile information, send a `GET` request to the `/<INSTAGRAM_SCOPED_ID>` endpoint, where `<INSTAGRAM_SCOPED_ID>` is the Instagram-scoped ID received in a messaging webhook notification, with the `fields` parameter set to a comma separated list of information you would like to view.

#### Sample Request

*Formatted for readability.*

```curl
curl -X GET "https://graph.instagram.com/v25.0/<INSTAGRAM_SCOPED_ID> \
  ?fields=name,username,profile_pic,follower_count,is_user_follow_business,is_business_follow_user \
  &access_token=<INSTAGRAM_ACCESS_TOKEN>"
```

On success, your app will receive the following JSON response:

```json
{
  "name": "Peter Chang",
  "username": "peter_chang_live",
  "profile_pic": "https://fbcdn-profile-...",
  "follower_count": 1234
  "is_user_follow_business": false,
  "is_business_follow_user": true,
}
```

## Reference

| Field Name | Description |
| --- | --- |
| `access_token`*string* | The Instagram user access token from your app user who can manage messages on the Instagram professional account who received the webhook notification |
| `follower_count`*int* | The number of followers the Instagram user has |
| `<IGSID>  ` *int* | The Instagram-scoped ID returned in a webhook notification that represents the Instagram user who interacted with your app user's Instagram professional account and triggered the notification |
| `is_business_follow_user  ` *boolean* | Indicates whether your app user follows the Instagram user (`true`) or not (`false`) |
| `is_user_follow_business `*boolean* | Indicates whether the Instagram user follows your app user (`true`) or not (`false`) |
| `is_verified_user`*boolean* | Indicates whether the Instagram user has a verified Instagram account (`true`) or not (`false`) |
| `name`*string* | The Instagram user's name (can be null if name not set) |
| `profile_pic`*url* | The URL for the Instagram user's profile picture (can be null if profile pic not set). The URL will expire in a few days |
| `username`<br>*string* | The Instagram user's username |

## Next steps

Use this information to [send a quick reply](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api/quick-replies).

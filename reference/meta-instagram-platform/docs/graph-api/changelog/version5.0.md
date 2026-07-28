# Version 5.0

**Released** October 29, 2019 | **Available until** February 3, 2022

* [Application](#application)
* [Marketing API](#marketing-api)
* [Messenger](#messenger)
* [Pages](#pages)

## Application

*This change applies to v5.0+.*

The following endpoints are deprecated:

* [`GET /{application-id}/objects`](/docs/graph-api/reference/v4.0/application/objects)
* [`POST /{application-id}/objects`](/docs/graph-api/reference/v4.0/application/objects)

## Marketing API

**Released** October 29, 2019 | **Available until** September 28, 2020

## Messenger

### New Features

*These changes apply to all versions.*

* [Click to Messenger Ads support for Handover protocol](https://developers.facebook.com/docs/messenger-platform/handover-protocol/click-to-messenger-ads-hop). Ads can now indicate the app id that will have control over the thread once a user clicks on the ad.
* [Replies and Reactions Webhooks](https://developers.facebook.com/docs/messenger-platform/webhook/reply_and_reactions). It is now possible to receive webhook events when users react or reply to messages from businesses.
* [`POST / GET / DELETE /{page-id}/messenger_profile` — Ice Breakers](https://developers.facebook.com/docs/messenger-platform/reference/messenger-profile-api/ice-breakers). Apps can now set icebreakers on the Messenger profile via the API to provide a set of common questions that users can use to start a conversation.
* [`GET /{thread-id}` — Admin Messages Filter](https://developers.facebook.com/docs/graph-api/reference/v4.0/thread#filters). Apps can now filter out admin messages to just get messages between the Page and the user.

### Deprecations

*These changes apply to various versions.*

The following endpoints are deprecated for **versions v5.0+**. They supported plain text only private replies. Use the [New Private Replies](/docs/messenger-platform/discovery/private-replies/) instead.

* [`POST /{comment-id}/private_replies`](/docs/graph-api/reference/object/private_replies#publish)
* [`POST /{post-id}/private_replies`](/docs/graph-api/reference/object/private_replies)

The following endpoints wil be deprecated for **all versions on March 4, 2020**.

* [`POST /{ad-account-id}/sponsored_message_ads`](https://developers.facebook.com/docs/messenger-platform/reference/sponsored-messages/)
* [`POST /{broadcast-id}`](https://developers.facebook.com/docs/messenger-platform/send-messages/broadcast-messages/)
* [`POST /{page-id}/broadcast_messages`](https://developers.facebook.com/docs/messenger-platform/send-messages/broadcast-messages)
* [`POST /{page-id}/broadcast_reach_estimations`](https://developers.facebook.com/docs/messenger-platform/send-messages/broadcast-messages/estimate-reach/)
* [`POST /{page-id}/message_creatives`](https://developers.facebook.com/docs/messenger-platform/send-messages/broadcast-messages)

## Pages

### Error Messages

*This change applies to all versions.*

Endpoints that require [`manage_pages`](/docs/facebook-login/permissions#reference-manage_pages) or [Page Public Content Access](/docs/apps/review/feature#reference-PAGES_ACCESS) and return an error code `10` when both permissions are missing will now return a new error message:

This endpoint requires the 'manage\_pages' permission or the 'Page Public Content Access' feature. Refer to [manage\_pages](https://developers.facebook.com/docs/facebook-login/permissions#reference-manage_pages) and [Page Public Content Access](https://developers.facebook.com/docs/apps/review/feature#reference-PAGES_ACCESS) for details.

### Page Public Content Access

*This change applies to v5.0+*

Requests made to endpoints that require the [Page Public Content Access](/docs/apps/review/feature#reference-PAGES_ACCESS) feature must be made with either an [App Access Token](/docs/facebook-login/access-tokens#apptokens) or include the app's [App Secret](/docs/facebook-login/security/#appsecret). If the calling app has been granted the [`manage_pages`](/docs/facebook-login/permissions#reference-manage_pages) permission however, an app access token or app secret is not required.

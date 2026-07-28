# Apps For Your Own Business



If your app is an automated experience or a custom inbox solution that can only process messages sent to your own Instagram Professional account, follow these guidelines when completing App Review. If your app will be used to process messages on behalf of other businesses, follow [this guide](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/app-review/apps-for-other-businesses) instead.

If you are unfamiliar with App Review, refer to our [App Review for Instagram Messaging Apps](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/app-review) document before proceeding.

## Screen recording

Create a [screen recording](https://developers.facebook.com/videos/2021/developing-for-success-how-to-produce-a-screencast-for-app-review/) showing us how to test your app. You will upload this video in later steps and our reviewers will refer to it when testing your app.

Show the following:

- How to initiate a conversation with your app

- How your app processes a message

- How your app processes [quick replies](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/quick-replies), [ice breakers](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/ice-breakers), or [generic templates](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/generic-template), if you have implemented them

- How your app processes [rich media](https://developers.facebook.com/documentation/business-messaging/messenger-platform/overview#content-design-network-urls)

- How your app processes messages the sender unsent

Make sure that the app you are recording is the same app that you are submitting for review, otherwise your submission will be rejected.

## Verification details

Providing verification details is optional. If you do want to provide this information, use the guidance below.

### Platform settings

Set the platform to **Website** (click the **Add Platform** button if you haven&#039;t set a platform yet) and use your business&#039;s website URL.

### Credentials

Leave this section blank.

## `instagram_manage_messages`

### Description

- Tell us if your app is an automated experience, a custom inbox solution, or both.

- Tell us how to initiate a conversation with your app.

- If your app is an automated experience, provide a set of commands we can test. Include commands that can trigger [quick replies](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/quick-replies), [ice breakers](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/ice-breakers), or [generic templates](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/generic-template), if you have implemented them.

### Instagram account

Enter your Instagram profile handle.

### Primary experience

Choose an option that best describes what we can build using your app.

* **Automated** — Choose this option if we can use your app to build an automated experience that automatically processes messages in real-time.
* **Live Agent** — Choose this option if we can only use your app to build a custom inbox solution that agents can use to manually process (read, reply, delete, and so on) direct messages.

### Screen recording

Upload the [screen recording](#screen-recording) you recorded earlier.

## business_management

When requesting the `business_management` permission, call out the following in your app review submission:

1. This permission is a dependency for the `pages_messaging` and `pages_show_list` permissions.
2. For Instagram Messaging, call out that this permission is a dependency for the `instagram_manage_messages` permission.
3. In the app review screencast, clearly show the Page admin navigating the Facebook Login flow, picking the pages or Instagram handles and providing the necessary permissions to the app.

In your app, make sure to inform the Page admin that they need to explicitly provide permissions to the app to manage their business assets. You will need to add the `business_management` permission as part of the [Facebook Login for Business](https://developers.facebook.com/documentation/facebook-login/facebook-login-for-business) flow.

## Human agent

The Human Agent feature is optional. Only request this feature if you have a custom inbox solution to process [human agent escalations](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/human-agent-escalation) and your agents need up to 7 days to respond to escalations using [message tags](https://developers.facebook.com/documentation/business-messaging/messenger-platform/reference/send-api).

### Description

Explain why it can take someone up to 7 days to reply to a direct message instead of 24 hours.

### Screen recording

If you are requesting this feature along with the `instagram_manages_messages` permission in the same App Review submission, upload the [screen recording](#screen-recording) you recorded earlier. Otherwise, capture a new screen recording  that shows a human agent responding to a message.

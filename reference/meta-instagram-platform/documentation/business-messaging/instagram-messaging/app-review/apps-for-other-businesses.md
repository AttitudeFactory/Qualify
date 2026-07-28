# Apps For Other Businesses



If your app will be used by other Instagram professional accounts to create automated experiences or custom inbox solutions that can process messages sent to their own Instagram professional accounts, follow the guidelines below. If your app can only process messages sent to your own Instagram professional account, follow [this guide](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/app-review/apps-for-your-own-business) instead.

If you are unfamiliar with App Review, refer to our [App Review for Instagram Messaging Apps](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/app-review) document before proceeding.

## Screen recording

Create a [screen recording](https://developers.facebook.com/videos/2021/developing-for-success-how-to-produce-a-screencast-for-app-review/) showing us how to use your app to set up an automated experience or custom inbox solution of our own. Also, show us how to test that experience or solution once we have created it. You will upload this video in later steps and our reviewers will refer to it when testing your app.

Show the following setup information:

- How to log into your app

- How to grant your app appropriate permissions with Facebook Login for Business

- How to set up an automated experience or custom inbox solution that can process [messages](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/send-message) and [conversations](https://developers.facebook.com/documentation/business-messaging/messenger-platform/conversations)

- How to set up [quick replies](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/quick-replies), [ice breakers](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/ice-breakers), or [generic templates](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/generic-template) (if your app allows users to set them up)

Show the following testing information:

- How to initiate a conversation with the experience or solution we create

- How to test unsent message processing

- If your app allows users to set up a custom inbox solution, show us how to send messages to it, and how to reply to and delete those messages.

Make sure that the app you are recording is the same app that you are submitting for review, otherwise your submission will be rejected.

## Verification details

### Platform settings

Set this to **Website** (click the **Add Platform** button if you haven&#039;t set a platform yet) and provide the URL where your app users can log into your service and set up an automated experience or custom inbox solution.

### Step-by-step instructions

Your step-by-step instructions should cover the following information:

* How to log into your website/service
* How to grant your app appropriate permissions with Facebook Login
* How to use your app to set up an automated experience or custom inbox solution that can process messages and conversations

If you wish, use the template below as a starting point when writing your step-by-step instructions:

**Note:** To create an app:

1. Go to &#123;website testing URL&#125;.
1. Log in with test credentials above.
1. Click the &#123;button&#125; in the left nav.
1. Click the &#039;Continue with Facebook&#039; button and log in with a valid Facebook account.
1. Click the &#039;Set Up an Automated Experience&#039; button.
1. ...

### Credentials

Select the dropdown menu option that best describes how app users access your app before they are able to create an automated experience or custom inbox solution.

* **I use Facebook Login for Business to log into my website** — Select this option if your app users can use Facebook Login for Business to create an account and sign into your app.
* **I don&#039;t use Facebook Login for Business to log into my website** — Select this option if app users cannot use Facebook Login for Business to create an account or sign in your app. Include a login and password for a test account that our app reviewers can use to access your app and set up an automated experience or inbox solution. Do not include personal Facebook or Instagram account details or Facebook or Instagram test user credentials. We will use our own Facebook accounts to test your service (our reviewers do not need to be granted any roles on your app).

## `instagram_basic`

### Description

Describe how to use functionality in your app that relies on this permission and how your app uses data provided by endpoints that require this permission.

### Screen recording

Upload the [screen recording](#screen-recording) you recorded earlier.

## `instagram_manage_messages`

### Description

Tell us how to test functionality in your app that relies on this permission, how your app uses data provided by endpoints that require this permission, and how to initiate a conversation with the experience or solution that we have created.

### Custom inbox solution

A custom inbox solution is functionality that an agent can use to manually process (such as reading, replying, and deleting) messages that an automated experience is unable to process for any reason.

### Unsent messages

Tell us how to test how the automated experience or custom inbox solution we have created handles unsent messages.

### Screen recording

Upload the [screen recording](#screen-recording) you recorded earlier.

## `business_management`

When requesting the `business_management` permission, call out the following in your app review submission:

1. State that you are requesting this permission as a dependency for the `pages_messaging` and `pages_show_list` permissions.
2. For Instagram Messaging, state that you are requesting this permission as a dependency for the `instagram_manage_messages` permission.
3. In the app review screencast, clearly show the Page admin navigating the Facebook Login flow, picking the pages or Instagram handles and providing the necessary permissions to the app.

In your app, make sure to inform the Page admin that they need to explicitly provide permissions to the app to manage their business assets. You will need to add the `business_management` permission as part of the [Facebook Login for Business](https://developers.facebook.com/documentation/facebook-login/facebook-login-for-business) flow.

## Human agent

This feature is optional. Only request this feature if you have a custom inbox solution to process [human agent escalations](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/human-agent-escalation) and your agents need up to 7 days to respond to escalations using [message tags](https://developers.facebook.com/documentation/business-messaging/messenger-platform/reference/send-api).

* **Description** — Explain why it can take someone up to 7 days to reply to a direct message instead of 24 hours.
* **Screen Recording** — If you are requesting this feature along with the instagram_manages_messages permission in the same App Review submission, upload the [screen recording](#screen-recording) you recorded earlier. Otherwise, capture a new screen recording that shows a human agent responding to a message.

# Overview of Instagram Messaging API



The Messenger Platform allows you to build messaging solutions for many Instagram Professional accounts.

Instagram Messaging is available for the following accounts:

* Any Instagram Professional account for a business
* Any Instagram Professional account for a Creator

You can check the eligibility for accounts that you manage using the
[Conversations API](https://developers.facebook.com/documentation/business-messaging/messenger-platform/conversations).

If your app users don&#039;t have a Facebook Page linked to their Instagram account, you can use the [Instagram Platform&#039;s Messaging API](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api) instead.

## Common uses

* Get messages that have been sent to your Instagram Professional Inbox from customers
* Receive and respond to customer messages with text, media, stories, and more
* Send a private reply to a person who published a public post on your Instagram
* Send a private reply to a person who published a comment on your Instagram post

## How it works

The Messenger Platform allows you to have conversations with people interested in your business or creations. The Facebook Page linked to your Instagram Professional account facilitates these conversations using the Messenger Platform. When a person sends your Instagram a message, Instagram delivers the message to your Instagram Inbox and sends a webhook notification to your server. Your messaging app has
[24 hours](https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages#standard-messaging)
to respond to this message. If a human agent needs more time to respond, you can add a tag to your response to send the message outside the standard 24-hour messaging window.

Instagram Messaging offers several conversation entry points for people to start a conversation and several message types for your messaging app to respond with.

### Instagram inbox &#123;#inbox-folder-behavior&#125;

An Instagram Professional account has a messaging inbox that allows you to control notifications and organize messages. By default, notifications are off. You can turn notifications on in the Inbox Settings. The inbox is organized into different categories, **Primary**, **General**, and **Requests**. By default, all new conversations from followers will appear in the Primary folder.
Conversations that existed before you implemented Instagram Messaging will be in the folders you have placed them within.
Messages that you receive from people who are not followers of your account are in the Requests folder. You can choose to accept or deny these requests, and request messages aren&#039;t marked as **Seen** until you accept them. Once a request is accepted you can move the conversation to the Primary or General folder. All message requests that you answer using a third-party app will be moved to the General folder.

#### Inbox limitations

* If you reply to a message using a third-party app, the conversation will be moved to the **General** folder regardless of your Setting configuration
* Inbox folders are not supported and messages delivered by the Messenger Platform do not include the folder information the Instagram from Meta app shows in its inbox folder
* Webhooks notifications or messages delivered via the API will not be considered as **Read** in the Instagram app inbox. Only after a reply is sent will a message be considered **Read**.

### Business login for Instagram

[Business login for Instagram](https://developers.facebook.com/docs/instagram/business-login-for-instagram) allows a person to convert their Instagram account to an Instagram Professional account, create a Facebook Page for their business, and to connect that Page to their Instagram Professional account within the login flow.

## Requirements

This guide assumes you have read the [Messenger Platform Overview](https://developers.facebook.com/documentation/business-messaging/messenger-platform/overview) and implemented the needed components for sending and receiving messages and notifications.

- The [**Instagram Graph API**](https://developers.facebook.com/docs/instagram-api) – This API allows businesses and Creators to manage their presence on Instagram using your app

- The following permissions:

- `instagram_basic`

- `instagram_manage_messages`

- `pages_manage_metadata`

- `pages_showlist`

- `business_management`

- The Human Agent feature – This feature allows your messaging app to provide an escalation path to a human agent

- Content Delivery Network (CDN) URL handling

- Delete messages when you receive a webhooks notification to do so, in accordance with [Meta Platform Terms](https://developers.facebook.com/terms/dfc_platform_terms/)

### Human agent escalation

Apps that use the Instagram Messaging APIs must have an escalation path to a human agent. Experiences can either start by directly interacting with a human agent or can start from an automation to qualify intent but must have a way for users to chat with a human agent as needed.

### Automated experiences &#123;#automated-experiences&#125;

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

### Human agent only &#123;#custom-inbox-only&#125;

You can provide an escalation path for human agent only messaging experiences with a custom inbox. Your messaging app must be able to:

- receive messages sent by people and render them correctly in the custom inbox

- reply to messages via the custom inbox and ensure people successfully received them

## Limitations

* An Instagram Professional account can only converse with **one customer per conversation**. Group messaging is not supported
* Conversations in the Requests folder that have not been active for 30 days will not be returned in API calls
* Only the URL for the shared media or post is included in the webhooks notification when a customer sends a message with a share
* An Instagram Professional account for a **Creator** must send an API request using the Instagram Conversations API before the account can receive webhooks

### Testing limitations

* Apps with Standard Access can only interact with people who have a role on the app
* Some features may not work properly until your app has been granted Advanced Access
* People testing your app must have a role on your app, grant access to all the required permissions, and have a role on the Instagram Professional account

## Next steps

* [Set up Webhooks](https://developers.facebook.com/documentation/business-messaging/messenger-platform/webhooks) for Instagram Messaging

## See also

- [Sample Instagram Messaging Experience](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/sample-experience) – Example code for a working Instagram messaging experience

- [Available Message Types](https://developers.facebook.com/docs/messenger-platform/instagram/features) – Explanations of various Instagram Messaging features

- [FAQs](https://developers.facebook.com/documentation/business-messaging/messenger-platform/overview) –  Solutions to common problems, troubleshooting tips, and FAQs

- [Rate Limits](https://developers.facebook.com/documentation/business-messaging/messenger-platform/overview#rate-limiting) –  Explanations of various Instagram Messaging rate limits

- [App Review](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/app-review) – Review the Platform policies and follow our pre-launch checklist to ensure a successful launch

- [Feature Reference](https://developers.facebook.com/docs/features-reference) –  Learn more about the Human Agent feature and how it works


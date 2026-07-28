Meta for Developers


[![Nav Logo](https://static.xx.fbcdn.net/rsrc.php/y9/r/tL_v571NdZ0.svg)](https://developers.facebook.com/)

Build with us

[Docs](/docs/)

[Blog](/blog/)

Resources

Developer centers

[Login](https://business.facebook.com/business/loginpage/?next=https%3A%2F%2Fdevelopers.facebook.com%2Fdocumentation%2Fbusiness-messaging%2Finstagram-messaging%2Fchangelog)

Instagram Messaging

Instagram Messaging

[Instagram Messaging](/documentation/business-messaging/instagram-messaging)

[Overview](/documentation/business-messaging/instagram-messaging/overview)

[Getting Started](/documentation/business-messaging/instagram-messaging/get-started)

[Sample Experience](/documentation/business-messaging/instagram-messaging/sample-experience)

[Messages](#)

[Send a Message](/documentation/business-messaging/instagram-messaging/features/send-message)

[Generic Template](/documentation/business-messaging/instagram-messaging/generic-template)

[Button Template](/documentation/business-messaging/instagram-messaging/button-template)

[Product Template](/documentation/business-messaging/instagram-messaging/features/product-template)

[Quick Replies](/documentation/business-messaging/instagram-messaging/features/quick-replies)

[Sender Actions](/documentation/business-messaging/instagram-messaging/features/sender-actions)

[Attachment Upload API](/documentation/business-messaging/instagram-messaging/features/attachment-upload)

[Conversation Features](#)

[Conversation Routing](#)

[Conversation Routing](/documentation/business-messaging/instagram-messaging/features/conversation-routing)

[Conversation Routing APIs](/documentation/business-messaging/instagram-messaging/features/conversation-routing/apis)

[Human Agent Escalation](/documentation/business-messaging/instagram-messaging/features/human-agent-escalation)

[Ice Breakers](/documentation/business-messaging/instagram-messaging/features/ice-breakers)

[ig.me links](/documentation/business-messaging/instagram-messaging/features/ig-me-links)

[Persistent Menu](/documentation/business-messaging/instagram-messaging/features/persistent-menu)

[Private Replies](/documentation/business-messaging/instagram-messaging/features/private-replies)

[Story Mention](/documentation/business-messaging/instagram-messaging/features/story-mention)

[Moderate Conversations API](/documentation/business-messaging/instagram-messaging/features/moderate-conversations)

[User Profile API](/documentation/business-messaging/instagram-messaging/features/user-profile)

[Webhooks](/documentation/business-messaging/instagram-messaging/webhooks)

[App Review](#)

[App Review](/documentation/business-messaging/instagram-messaging/app-review)

[Apps For Other Businesses](/documentation/business-messaging/instagram-messaging/app-review/apps-for-other-businesses)

[Apps For Your Own Business](/documentation/business-messaging/instagram-messaging/app-review/apps-for-your-own-business)

[Webhook Debugger](/documentation/business-messaging/instagram-messaging/webhooks/debugging)

---

Resources

[Changelog](/documentation/business-messaging/instagram-messaging/changelog/)

[Docs](/documentation)

Changelog

Changelog

Updated: May 6, 2026

[Get notified](/documentation/business-messaging/instagram-messaging/changelog/rss/)

---

Changelog (39)

Search Changelog

May 6, 2026

#

[Sending multiple images](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api/) is now out of beta and available to all accounts via [Facebook Graph API](https://developers.facebook.com/docs/messenger-platform/instagram/features/send-message/) for Instagram accounts linked with a Facebook page OR the [Instagram API](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api/) for Instagram-only accounts.

---

Apr 27, 2026

#

The legacy `share` attachment type is being removed from Instagram post share webhook payloads. As announced on [October 30, 2025](#october-30-2025), the `share` attachment has been deprecated in favor of the `ig_post` attachment type, which includes full metadata (media ID, URL, and title). This change is being rolled out gradually: webhooks will return only the `ig_post` attachment once rollout reaches your app. If your integration still relies on the `share` attachment type for Instagram posts, update it to use `ig_post` instead or contact our developer support team through [Meta Developer Support Portal](https://developers.facebook.com/support/) to request exclusion of your app(s) from this change.

---

Mar 13, 2026

#

The Instagram Direct Send API now supports sending the images with attachment IDs (in addition to image URLs) which resolves the problem of timeouts when uploading multiple large high-quality images from slow servers. You can use the attachment API to upload the images one at a time and reuse the attachment IDs to send the same image to multiple users. See the updated documentation for [Facebook Graph API](/documentation/business-messaging/instagram-messaging/features/send-message) for Instagram accounts linked with a Facebook page OR the [Instagram API](/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api) for Intagram-only accounts.

---

Dec 19, 2025

#

### Instagram PDF Attachments

You can now upload and send PDF file attachment in Instagram Direct using [Facebook Graph API](/documentation/business-messaging/instagram-messaging/features/send-message) for Instagram accounts linked with a Facebook page OR the [Instagram API](/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api) for Instagram-only accounts.

### Instagram Message Replies API

You can now send a reply to a specific message in Instagram Direct using the [Facebook Graph API](/documentation/business-messaging/instagram-messaging/features/send-message#send-a-reply-to-a-message) for Instagram accounts linked with a Facebook page

`reply_to` object will also be available in the [Conversations API](/documentation/business-messaging/messenger-platform/conversations). It will be non-null when the message is a reply and will indicate if it is a self reply. This boolean flag will also be added to the reply\_to object returned in the message object in Message and Echo webhooks.

---

Dec 2, 2025

#

Businesses can now use the [Messenger](/documentation/business-messaging/messenger-platform/send-messages/sender-actions) and [Instagram Send API](/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api#react-or-unreact-to-a-message) to react with a reaction emoji to a message in their inbox, edit an existing reaction on a message and remove a reaction (unreact) from a message that was previously reacted to.

---

Nov 3, 2025

#

You can now send a collection of images in Instagram Direct using either the [Facebook Graph API](/documentation/business-messaging/instagram-messaging/features/send-message) for Instagram accounts linked with a Facebook page OR the [Instagram API](/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api) for Intagram-only accounts.

November 3, 2025: Multi-image sending is a Beta feature that will be rolled out incrementally over a few weeks . While the feature is rolled out, some Instagram accounts may get an error response [`2534068`](/documentation/business-messaging/instagram-messaging/features/send-message#send-images) to indicate that the feature is not yet available for that account.

---

Oct 30, 2025

#

Starting November 3, 2025, the webhook payload for Instagram post shares will include two attachments: the existing `share` attachment and a new `ig_post` attachment. The payload now provides additional metadata, including media ID, URL, and title (caption).

If this change is not compatible with your app and you need more time to make updates, please contact our developer support team via the [Meta Developer Support Portal](https://developers.facebook.com/support/) to request exclusion of your app(s) from this change until you make the necessary updates to support the new attachment type.

The old `share` attachment type will continue to be supported for Instagram posts until **February 1, 2026**, after which it will be removed. Partners and integrators are encouraged to migrate to the new `ig_post` attachment type as soon as possible. See [here](/docs/instagram-platform/webhooks/new) for before and after payload sample.

---

Oct 23, 2025

#

Meta no longer supports the Handover Protocol for Instagram. All businesses have been migrated to [Conversation Routing](/documentation/business-messaging/instagram-messaging/features/conversation-routing). Conversation Routing is backwards compatible with most Handover Protocol APIs and functionalities, and is expected to function without interruption.

---

Oct 21, 2025

#

[Instagram Moderate Conversations API](/documentation/business-messaging/instagram-messaging/features/moderate-conversations) is now available.
This new API will allow businesses to block users, unblock users, and move conversations to the spam folder in Meta Business Suite Inbox for the Instagram platform. Previously, these actions could only be completed on the Instagram app or Meta Business Suite.

---

Oct 13, 2025

#

The [Conversations API](/documentation/business-messaging/messenger-platform/conversations#conversation-ownership-filtering) now supports an `is_owner` field for both Messenger and Instagram. This field indicates if the app making the request is the current thread owner of the conversation or not, and is only returned when [Conversation Routing](/documentation/business-messaging/messenger-platform/conversation-routing) is enabled.

Benefits:

- Filter and respond only to conversations your app owns.
- Avoid unnecessary ticket creation and reduce costs.
- Streamline recovery after downtime by focusing on relevant threads.

---

Sep 23, 2025

#

Businesses can now display typing indicators and mark\_seen indicators in a conversation to let message recipients know that the business has seen and are processing their message, using [Sender Actions](/documentation/business-messaging/instagram-messaging/features/sender-actions).

---

Sep 16, 2025

#

[Custom thread control window](/documentation/business-messaging/instagram-messaging/features/conversation-routing?locale=en_US#extended-thread-control-window) for Click To Instagram Ads is now available. When a conversation starts from an ad, the app controls the thread for 24 hours from the last user message, extendable up to 30 days by setting `receiving_app_control_expiration`. Invalid values or Conversation Control actions reset the window to 1 day.

---

Sep 10, 2025

#

Introducing the new `message_edit` webhook subscription in Instagram supporting both use cases of both Business Login for Instagram and Facebook Login for Business. Sample `message_edit` webhook can be found [here](/docs/instagram-platform/webhooks/examples?locale=en_US#message-edit).

---

Feb 24, 2025

#

### Messenger and Instagram

`messaging_referrals` webhook now contains flow ID.
The webhook event contains a `flow_id` field when an ad referral originates from an ad with a [Welcome Message flow](/documentation/business-messaging/messenger-platform/ads/ads-welcome-message-flows). This is available in the ad referral object of the `messages`, `messaging_postbacks`, `messaging_referrals` webhooks. See more details about the webhook [here](/documentation/business-messaging/messenger-platform/reference/webhook-events/messaging_referrals).

---

Oct 8, 2024

#

### Messenger `response_feedback` webhook

The new `response_feedback` webhook event notifies you when a user provides feedback on a message you send, by clicking on one of the “thumbs up”/”thumbs down”/”Good response”/”Bad response” buttons. See more details about the webhook [here](/documentation/business-messaging/messenger-platform/reference/webhook-events/response_feedback).

### Send API Rate Limits

Your app can now make 300 (up from 100) calls per second per Instagram professional account for messages that contain text, links, reactions, and stickers. [Learn more.](/documentation/business-messaging/messenger-platform/overview#rate-limiting)

---

Jun 23, 2024

#

### Launch of the new Instagram API with Instagram Login

[Components of this new Instagram API:](/docs/instagram/platform/instagram-api/overview)

* A Facebook Page will no longer be required
* The host URL for API calls is `graph.instagram.com`
* New permissions for this API:
  + `instagram_business_basic`
  + `instagram_business_content_publishing`
  + `instagram_business_manage_comments`
  + `instagram_business_manage_messages`
* New apps will add the new **Instagram** product when creating a Meta app
* Existing apps can add the new **Instagram** product in the App Dashboard

[Visit our migration guide to learn if this new Instagram API with Instagram Login is right for you](/docs/instagram/platform/instagram-api/migration-guide).

Monitor the [Instagram Platform Changelog](/docs/instagram-api/changelog) for changes including bug fixes and new features

---

Jun 11, 2024

#

### Messenger Messages Webhook

`ig_reel` will now be a supported attachment type for the messages webhook. IG reel attachments will have type `ig_reel` and the attachment payload will include the title, url, and video id for the reel.

### Instagram Messages Webhook

`ig_reel` and `reel` will now be supported attachment types in a messages webhook. IG reel attachments will have type `ig_reel`, and the attachment payload will include the title, url, and video id for the reel. FB reel attachments will have type `reel`, and the attachment payload will include the title, url, and video id for the reel.

### Messenger Conversation Routing: app-level thread control configs

Businesses using Messenger Conversation Routing can now configure the thread control takeover capability on the individual app level. The original takeover config that’s coupled with the default app is now deprecated with all values migrated. Learn more [here](/documentation/business-messaging/messenger-platform/conversation-routing?locale=en_US#tc-takeover-configs).

### Instagram Comment Webhooks

*Applies to all versions*

In addition to the `ad_id` and `ad_title`, the `original_media_id` will be returned in the `media` object of the `comments` field’s `value` object when a person comments on a [boosted Instagram post or Instagram ads post⁠](https://l.facebook.com/l.php?u=https%3A%2F%2Fhelp.instagram.com%2F1067656009937668&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl). For more information, refer to [Set Up Webhooks for Instagram](/docs/instagram-api/guides/webhooks).

---

Mar 12, 2024

#

### Welcome Message Flows

Welcome Message flows can now be configured for messaging ads using the marketing API. Learn more about Click to Messenger ads [here](/documentation/ads-commerce/marketing-api/ad-creative/messaging-ads/click-to-messenger) and Click to Instagram ads [here](/documentation/ads-commerce/marketing-api/ad-creative/messaging-ads/click-to-instagram).

---

Oct 17, 2023

#

### Conversation Routing for Instagram

Conversation Routing is now available for Instagram. Conversation Routing allows Meta to route conversations between your business and customers, or prospective customers, to the app that you have specified to respond in the conversation. This routing allows your business to create rich conversations with people and to minimize API calls to Meta’s servers.

### Custom Labels and Personas APIs

The Custom Labels API and Personas API access has been restored to businesses that operate in Europe, and for people in Europe and Japan who connect with businesses globally.

### Updates to welcome message flows for Ads that Click to Messenger and Instagram Direct

Businesses and agencies can now easily connect their Click to Messenger and Click to Instagram Direct ads to a welcome message created in a partner app without having to use a JSON code snippet. The welcome message will appear as a dropdown in ads manager when creating the Click to Messenger and Click to Instagram Direct ad. [Learn more about it here.](/documentation/business-messaging/messenger-platform/ads/ads-welcome-message-flows)

---

Sep 12, 2023

#

### Conversation Routing

As a business, you may use multiple third-party messaging providers for different conversations with your customers, like lead generation, marketing offers about your products, or customer support questions. Conversation routing lets you define which partners control customer conversations at a particular time, so that customers get the information they need. You can create and manage message routing rules in your Page settings.

### Button Template for Instagram

The button template sends a text message with up to three attached buttons. This template is useful for offering the message recipient options to choose from, such as predetermined responses to a question, or actions to take. Supported button types are `postback` and `web_url`.

---

Jun 20, 2023

#

### Instagram Messaging with the Messenger Platform

Instagram Messaging is now available for any Instagram Professional account for a business or a Creator.

---

Jun 15, 2023

#

### Ads that Click to Messenger

#### Call Prompt

You can now add a call prompt to allow customers or people interested in your business to call your business.

#### Click to Subscribe

You can now create ads that include a click to subscribe flow that allow you to ask customers or people interested in your business to opt in to receiving marketing messages.

### Multi App Routing

Multi App Routing is now available for Instagram Direct and Messenger.

---

Feb 21, 2023

#

Recurring Notifications for Messenger Platform

#### Titles for Opt In Request

The `title` property for [recurring notification opt in requests](/docs/messenger-platform/send-messages/recurring-notifications#request-permission-to-send-recurring-notifications) is **no longer required**. If `title` is not set, the value defaults to “Updates and promotions”. This change applies to opt in requests sent from a Facebook Page or Instagram Professional accounts.

---

Feb 2, 2023

#

Recurring Notifications for Messenger Platform

#### Message Frequency for Opt In Requests

The `notification_messages_frequency` property for [recurring notification opt in requests](/docs/messenger-platform/send-messages/recurring-notifications) is **deprecated** and will no longer be returned in `GET` requests or webhook notifications. However, notification message tokens created before Feb. 2, 2023 for weekly or monthly recurring notifications will be supported and the `notification_message_frequency` will be returned in webhook notifications.

#### Followup Messages for Opt Ins

You can now send up to three [followup messages](/docs/messenger-platform/send-messages/recurring-notifications#opt-in-followup-messages) to a person who has opted in to receiving recurring notifications. All three followup messages must be sent within 2 minutes of the first followup message.

#### Notification Message Tokens

The [`GET /PAGE-ID/notification_message_tokens` endpoint](/docs/messenger-platform/send-messages/recurring-notifications#get-a-list-of-tokens) is now available for Instagram Messaging.

The [`next_eligible_time` property](/docs/messenger-platform/send-messages/recurring-notifications#get-a-list-of-tokens) for Notification Message Token endpoints is now available. This field returns the time at which you are able to send the next recurring notification using that notification message token.

Messenger API for Instagram

You can now send GIFs in [messages sent](/documentation/business-messaging/instagram-messaging/features/send-message) from an Instagram Professional account using the Messenger API for Instagram.

The [Attachment Upload API](/docs/messenger-platform/instagram/features/upload-attachment) now supports uploading media for messages sent from an Instagram Professional account.

Referral information for ads that click to an Instagram conversation (CTD) is now returned in [messages webhook notifications](/documentation/business-messaging/instagram-messaging/webhooks#messages).

---

Nov 9, 2022

#

#### Business Login for Instagram

[Business Login for Instagram](/docs/instagram/business-login-for-instagram) makes it easier for you to onboard Instagram users who still need to configure their account for API access through modal pop ups and fewer steps.

#### Improvements between Click to Messenger, Lead Gen ads and Messenger Platform

We’ve made following up on Lead Gen ads that Click to Messenger easier through:

* A new [Referral Webhook for Click to Messenger, Lead Gen ads](/documentation/business-messaging/messenger-platform/discovery/lead-generation-ads-in-messenger#webhooks) that include the lead information.
* Improvements to the [Handover Protocol](/docs/messenger-platform/handover-protocol/messenger-lead-ads-hop). Advertisers can now select which app they want to route completed leads. Additionally, for apps that haven’t yet implemented these app notifications, an [optional summary message](/documentation/business-messaging/messenger-platform/discovery/lead-generation-ads-in-messenger#connnectapp) can be enabled, to send lead information to that app in the form of a regular message.
* Since referral or summary events are triggered while the standard messaging window is open, apps can use this to follow-up with leads directly in Messenger, upsell them to [Recurring Notifications](/docs/messenger-platform/send-messages/recurring-notifications) or have them book an appointment or call the business directly.

#### Messaging Events API

Messaging Events API supports the [`lead_submitted` event](/documentation/ads-commerce/conversions-api/business-messaging#lead_submitted). Businesses can use this event to report lead submissions from Click to Messenger ads. This new messaging event is released as an Open Beta. Reporting in Ads Manager will come soon.

#### Persistent Menu

[Persistent Menu](/documentation/business-messaging/instagram-messaging/features/persistent-menu) is now available for Instagram Messaging.

#### Private Replies

Instagram Messaging now supports [Private Replies](/documentation/business-messaging/instagram-messaging/features/private-replies) for comments on Instagram Live Stories and ads posts. You may need to update your webhooks server to handle these new fields.

#### Recurring Notifications

You can now get a list of all valid Notification Message Tokens using the [`GET /PAGE-ID/notification_message_tokens` endpoint](/docs/messenger-platform/send-messages/recurring-notifications#get-a-list-of-tokens).

---

Aug 16, 2022

#

#### Private Replies

[Private Reply](/documentation/business-messaging/instagram-messaging/features/private-replies) is now available for comments on Instagram Reels.

#### Instagram Messaging

You can now send Instagram messages with audio and videos that have been uploaded to a Meta server or sent from your server.

---

May 25, 2022

#

[User Profile API](/documentation/business-messaging/instagram-messaging/features/user-profile) supports retrieval of the customer’s Instagram username field on Graph API v14.0 and later.

---

May 19, 2022

#

**Recurring Notifications for Messenger API**
[Recurring Notifications](/docs/messenger-platform/send-messages/recurring-notifications) is a major update to the Messenger API to allow businesses to send proactive, automated messages that drive re-engagement. Recurring Notifications help businesses deliver personalized, customer centric messages at every stage of the customer journey.

**Recurring Notifications for Messenger API for Instagram**
 We’re announcing Recurring Notifications for Messenger API for Instagram as a beta. Developers can sign up for our [beta interest list⁠](https://www.facebook.com/help/contact/528956182103351) before July.

**Instagram Send API rate limit increase**
 We have increased the rate limit for the Send API to 100 API calls per second for each Instagram Professional Account.

**ig.me referral parameter**
 Businesses can add [ig.me links](/documentation/business-messaging/instagram-messaging/features/ig-me-links) on websites, emails, and product packaging to easily enable users to start a conversation with a business on Instagram. We are adding the ability for brands to add a **referral parameter** to these ig.me links to create personalized messaging experiences.

**Instagram API New Onboarding Flow**
 We are announcing a [new onboarding flow for the Instagram API](/docs/instagram/business-login-for-instagram) as a beta. Developers can sign up for our beta interest list before June 29.

---

Mar 15, 2022

#

We have launched the [Persistent Menu for Messenger API support for Instagram](/documentation/business-messaging/instagram-messaging/features/persistent-menu). This enables users to discover and interact with a Page’s main features.

---

Nov 11, 2021

#

Messenger API for Instagram is now available for Instagram Creators account type with less than 500K followers. Please see details in the [developer documentation](/docs/messenger-platform/instagram/rollout).

---

Nov 9, 2021

#

* We have updated [Private Reply](/documentation/business-messaging/instagram-messaging/features/private-replies) on Instagram to support comments on Instagram Live videos. Please refer to the [developer documentation](/documentation/business-messaging/instagram-messaging/features/private-replies) for details on implementation.

---

Oct 20, 2021

#

* IG comments [webhook](/docs/graph-api/webhooks/reference/instagram#comments) and [API](/docs/instagram-api/reference/ig-comment) are updated with additional fields. Please refer to the developer documentation for more details on new fields.
* Starting support for [IG.me link](/documentation/business-messaging/instagram-messaging/features/ig-me-links), a shortened URL service that directs users to messaging experience on Instagram. Developers can use the link format `https://ig.me/m/{ig_profile_handle}` on website, email, and more. Please refer to the [developer documentation](/documentation/business-messaging/instagram-messaging/features/ig-me-links) for more details.
* We have made updates to the [Ice Breaker](/documentation/business-messaging/instagram-messaging/features/ice-breakers) on Instagram to support multiple versions in different languages. Developers can now set up Ice Breakers in different languages and serve the right version to users based on user locale. Please refer to the [developer documentation](/documentation/business-messaging/instagram-messaging/features/ice-breakers) for more details.

---

Sep 14, 2021

#

* Handover Protocol Improvements
  + We are making improvements to [Handover Protocol](/docs/messenger-platform/handover-protocol) which helps developers and businesses launch messaging experiences (i.e. apps) quickly, makes it easy to pass control of conversation between apps and ensures a great user experience by disallowing apps from interjecting ongoing conversations. Key improvements include [Exclusive mode](/docs/messenger-platform/handover-protocol#how-it-works), [Idle mode](/docs/messenger-platform/handover-protocol#how-it-works), [New APIs for finer control over thread ownership](/docs/messenger-platform/handover-protocol/conversation-control) and [removing the requirement to assign primary or secondary roles for apps](/docs/messenger-platform/handover-protocol#how-it-works)
  + Note that developers and businesses who currently use Handover Protocol need to implement the changes to their current Handover Protocol implementation by March 1st, 2022. Please refer to the [migration guide](/docs/messenger-platform/handover-protocol-v2#migration-guide) and [breaking changes](/docs/messenger-platform/handover-protocol-v2#breaking-changes) sections for more details.
* Custom Labels API - We are making exciting updates to the [Custom Labels API](/documentation/business-messaging/messenger-platform/identity/custom-labels) that would allow businesses to create, update and delete labels and sync the labels between the Facebook Page Inbox and any other tool the business might be using to communicate with their customers.
  * In order to use the Custom Labels API after October 1st, 2021 businesses need to accept our new *Page Contact Terms.* These terms describe Meta’s data practices for the Custom Labels created by the business. We will be rolling out the Page Contact Terms acceptance requirement to Facebook Pages on a rolling basis starting October 1st.
  * Graph API `v12.0`+ Custom Labels API `name` field will be replaced with `page_label_name`. This change will take effect on all older Graph API versions starting Dec 14, 2021. Developer should leverage `page_label_name` across various CRUD (Create, Retrieve, Update, Delete) API calls and webhooks.
* [Messenger API Updates for Europe and Japan](/documentation/business-messaging/messenger-platform/europe-japan-updates) - We have restored [Customer Feedback Template](/documentation/business-messaging/messenger-platform/send-messages/templates/customer-feedback-template) in the Messenger API that wasn’t available to businesses in Europe, and for people in Europe and Japan who connect with businesses globally. Details [here](/documentation/business-messaging/messenger-platform/europe-japan-updates).
* Messenger API for Instagram updates
  + [Reaction Webhook](/documentation/business-messaging/instagram-messaging/webhooks) - We have updated emoji reactions to return a new unicode format and support multiple emoji reactions. Please refer to the [developer documentation](/documentation/business-messaging/instagram-messaging/webhooks) and migrate to the new version before December 14, 2021 in order to continue supporting emoji reactions.
* [User Profile API](/documentation/business-messaging/instagram-messaging/features/user-profile) - We have updated User Profile API to include additional fields that are publicly available on the Instagram app. Please refer to the [developer documentation](/documentation/business-messaging/instagram-messaging/features/user-profile) for details.
* IGID Deprecation - [Conversation API](/documentation/business-messaging/messenger-platform/conversations) will no longer return `IGID` field and fully rely on `IGSID` field. See [developer documentation](/documentation/business-messaging/messenger-platform/conversations) for details in order to migrate before December 14, 2021.
* [Facebook Chat Plugin Customization API](/documentation/business-messaging/messenger-platform/discovery) - We are launching Chat Plugin customization settings through API. With this new release, developers will be able to edit features including the position, color, greetings, guest mode settings, etc. that are currently only available using our first-party tools today.
* [Message Echo webhook](/documentation/business-messaging/messenger-platform/reference/webhook-events/message-echoes) will now include the app id for Facebook Page Inbox as part of Graph API `v12.0` - When a business responds to a Messenger conversation from Facebook Page Inbox, other apps connected to the Page can listen to the Message Echo webhook. These apps will receive an echo webhook with the Facebook Page inbox app id (`263902037430900`).

---

Aug 16, 2021

#

* [Messenger API for Instagram](/docs/messenger-platform/instagram)- Messenger API for Instagram opened up to all developers in June, with an opportunity to build for IG business accounts with follower counts between 10k-100k. Now, developers can add Instagram messaging into their apps and build Instagram messaging experiences for all businesses on Instagram. The use of Messenger API for Instagram must comply with the [Developer Policies](https://developers.facebook.com/devpolicy#messengerplatform), particularly the policies listed under ‘Messenger and Instagram Messaging APIs’, as well as the [technical documentation](/docs/messenger-platform/instagram).

---

Aug 6, 2021

#

* [Private Replies](/documentation/business-messaging/instagram-messaging/features/private-replies) on Instagram Messaging API no longer need to be sent using the Human Agent Message Tag. Private Reply API calls with the [Human Agent Tag](/documentation/business-messaging/messenger-platform/reference/send-api) will stop working after Sept 13, 2021.

---

Jul 7, 2021

#

* [Messenger API for Instagram](/docs/messenger-platform/instagram) - Messenger API for Instagram opened up to all developers in June, with an opportunity to build for IG business accounts with follower counts between 10k-100k. We are expanding the rollout to IG business accounts with follower counts between 1K-10K. Now, developers can add Instagram messaging into their apps and build Instagram messaging experiences for even more businesses. The use of Messenger API for Instagram must comply with the [Developer Policies](https://developers.facebook.com/devpolicy#messengerplatform), particularly the policies listed under ‘Messenger and Instagram Messaging APIs’, as well as the [technical documentation](/docs/messenger-platform/instagram).

---

Jun 22, 2021

#

* [Generic Templates](/documentation/business-messaging/instagram-messaging/generic-template), which allows you to send a structured message that includes an image, text and buttons, is now available for Instagram

---

Jun 8, 2021

#

The following changes apply to v11.0+

* **Adding `<mid>` to `messaging_postback` events for Messenger and Messenger API for Instagram for Graph API V11.0+** - We are adding the Message Id (`<mid>`) field as part of the `messaging_postback` payload to help reduce engineering overheads for our partners who have had to rely on the [Conversations API](/docs/graph-api/reference/v10.0/conversation) to fetch conversation history and then compare it with the webhook events. See more details [here](/documentation/business-messaging/messenger-platform/reference/webhook-events/messaging_postbacks).
* **[Airline Templates are deprecated](/docs/messenger-platform/send-messages/template/airline)** *-* Airline Templates will no longer be supported starting Graph API v11. Deprecation for the prior versions of the Graph API will occur 6 months after the announcement of this change on Dec 6, 2021. We recommend airlines send [Boarding Pass](/docs/messenger-platform/reference/templates/airline-boarding-pass) and [Check-in](/docs/messenger-platform/reference/templates/airline-checkin) templates as images which are consistent with how they typically send these notifications in other channels.

---

Jun 2, 2021

#

* [Messenger API for Instagram](/docs/messenger-platform/instagram) - We have opened up the Messenger API for Instagram to all developers who are making it possible for brands to offer messaging experiences on Instagram at scale. Now, developers can add Instagram messaging into their apps and build experiences for Instagram messaging. Developers can help businesses use different applications to leverage existing workflows, drive more meaningful conversations, increase customer satisfaction, and grow sales. Learn more [here](/docs/messenger-platform/instagram). The use of Messenger API for Instagram must comply with the [Developer Policies](https://developers.facebook.com/devpolicy#messengerplatform), particularly the policies listed under ‘Messenger and Instagram Messaging APIs’, as well as the [technical documentation](/docs/messenger-platform/instagram).
* [Human Agent message tag](/documentation/business-messaging/messenger-platform/reference/send-api) now available to all developers - This tag allows businesses to respond to user messages on Messenger and Instagram manually outside the 24-hour standard messaging window up to 7days. This tag is helpful especially for use cases such as weekend closures or for inquiries that need more than 24 hours to resolve. Developers should apply for the Human Agent tag permission via the App dashboard even if your app has been previously approved for Human Agent message tag. Navigate to the “Permissions and Features” section of the app dashboard and apply for the “Human Agent” permission. Learn more [here](/documentation/business-messaging/messenger-platform/reference/send-api).
* [Customer Feedback Template](/documentation/business-messaging/messenger-platform/send-messages/templates/customer-feedback-template) *is now available as Beta* - We are launching a native template within Messenger that supports common survey formats such as CSAT (Customer Satisfaction), NPS (Net Promoter Score), CES (Customer Effort Score) and free form text. The native template is easier to integrate because it’s built on Send API, eliminates the need to build custom survey solutions using Webview and makes it easy for developers to aggregate scores across channels that use similar survey formats. Learn more [here](/documentation/business-messaging/messenger-platform/send-messages/templates/customer-feedback-template).

---

---

![Meta](https://static.xx.fbcdn.net/rsrc.php/y9/r/tL_v571NdZ0.svg)

[![Facebook](https://scontent-eze1-1.xx.fbcdn.net/v/t39.2365-6/425860105_925920989121941_6933048753023841367_n.svg?_nc_cat=1&ccb=1-7&_nc_sid=aa6a2f&_nc_ohc=eOVGLOPhO7EQ7kNvwF2i2xi&_nc_oc=AdqYV0GokV3-ZVpoi3zZGUiJ756Idf5HsqY6cjcMg7351weidc1RMwP4OVXdc4bhjjY&_nc_zt=14&_nc_ht=scontent-eze1-1.xx&_nc_gid=BPDVn8p_16Pv0x0rTSgT_A&_nc_ss=7b20f&oh=00_AQDxuR6O7EJjzp6QZ8XuECdeYbWjw9Kj4YVgqhBrKrvIeg&oe=6A68CA62)](https://www.facebook.com/MetaforDevelopers)[![Instagram](https://scontent-eze1-1.xx.fbcdn.net/v/t39.2365-6/425804778_757649995874129_6917476492193301523_n.svg?_nc_cat=1&ccb=1-7&_nc_sid=aa6a2f&_nc_ohc=vMKpyl1_hrUQ7kNvwG3T0yd&_nc_oc=Adq3czsTjZzE6nAQEqYqO7VqwYhLYZWTctUaSORchooanTy5-7Xfnm9SqfR6EBEN7IY&_nc_zt=14&_nc_ht=scontent-eze1-1.xx&_nc_gid=BPDVn8p_16Pv0x0rTSgT_A&_nc_ss=7b20f&oh=00_AQBS89-75-_dymP6X-cAWETgAPHcEwa_uKsqQNK0JFW73w&oe=6A68B478)](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.instagram.com%2Fmetafordevelopers%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)[![X](https://scontent-eze1-1.xx.fbcdn.net/v/t39.2365-6/426747931_385023204117867_5811151062540225287_n.svg?_nc_cat=1&ccb=1-7&_nc_sid=aa6a2f&_nc_ohc=gWIEuCON_kYQ7kNvwEEM79R&_nc_oc=Adr5RIuFkI0Pwo0D7OiQtPFjRvVFPFz3A5JjsCMj6Eb94nQduDPIv7SjhbpggxOIFFE&_nc_zt=14&_nc_ht=scontent-eze1-1.xx&_nc_gid=BPDVn8p_16Pv0x0rTSgT_A&_nc_ss=7b20f&oh=00_AQBKd7IKbPU9B4Fo9KhJ8OxCFEJOXFwtYeP9b_1E1gpqow&oe=6A689AAA)](https://l.facebook.com/l.php?u=https%3A%2F%2Ftwitter.com%2Fmetafordevs&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)[![LinkedIn](https://scontent-eze1-2.xx.fbcdn.net/v/t39.2365-6/467689750_1684384502343829_7561568713040200172_n.svg?_nc_cat=103&ccb=1-7&_nc_sid=aa6a2f&_nc_ohc=RlaN0FyncU4Q7kNvwGqw28q&_nc_oc=AdqGjmW94_SY4NMjJAAIqOwSW0XgI_sXOfUHc-o4ZcoapMWzOpBOK0CKp7KA0IBj18Y&_nc_zt=14&_nc_ht=scontent-eze1-2.xx&_nc_gid=BPDVn8p_16Pv0x0rTSgT_A&_nc_ss=7b20f&oh=00_AQDefRHzQzO8wK9BGDClEoma_kwHC55Kb2hFn95P3SHbsA&oe=6A68AA3E)](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.linkedin.com%2Fshowcase%2Fmeta-for-developers%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)[![YouTube](https://scontent-eze1-1.xx.fbcdn.net/v/t39.2365-6/425519002_724756916408357_7491658959807896355_n.svg?_nc_cat=1&ccb=1-7&_nc_sid=aa6a2f&_nc_ohc=NktWNYDvv5QQ7kNvwHtzoKr&_nc_oc=Adri0glt7pNBE1EzGyprn2nXptKW5YGdeGpzYNwJT9OoTG-OfrSHxxRiyC3YLuLP9Cg&_nc_zt=14&_nc_ht=scontent-eze1-1.xx&_nc_gid=BPDVn8p_16Pv0x0rTSgT_A&_nc_ss=7b20f&oh=00_AQC0BTjKU1ptpqV892bTEti1ypWJis3-As4K4zsHwBtOfw&oe=6A68955F)](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.youtube.com%2FMetaDevelopers%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

Build with Meta

[AI](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.llama.com%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)[Meta Horizon](https://l.facebook.com/l.php?u=https%3A%2F%2Fdevelopers.meta.com%2Fhorizon%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl) [Social technologies](/social-technologies/)[Wearables](https://l.facebook.com/l.php?u=https%3A%2F%2Fdevelopers.meta.com%2Fwearables%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

---

News

[Meta for Developers](https://l.facebook.com/l.php?u=https%3A%2F%2Fdevelopers.meta.com%2Fblog%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)[Blog](/blog/)[Success stories](/success-stories/)

---

Support

[Developer Support](/support/)[Bug tool](/support/bugs/)[Platform status](https://l.facebook.com/l.php?u=https%3A%2F%2Fmetastatus.com%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)[Developer community forum](https://www.facebook.com/groups/fbdevelopers/)[Report an incident](/incident/report/)

---

Terms and policies

[Responsible platform initiatives](/products/responsible-platform-initiatives/)[Platform terms](/terms/dfc_platform_terms/)[Developer policies](/devpolicy/)[Privacy policy](https://www.facebook.com/about/privacy)[Cookies](https://www.facebook.com/help/cookies)

---

About us

[About](https://l.facebook.com/l.php?u=https%3A%2F%2Fabout.fb.com%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)[Careers](https://www.facebook.com/careers)

---

Build with Meta

[AI](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.llama.com%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

[Meta Horizon](https://l.facebook.com/l.php?u=https%3A%2F%2Fdevelopers.meta.com%2Fhorizon%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

[Social technologies](/social-technologies/)

[Wearables](https://l.facebook.com/l.php?u=https%3A%2F%2Fdevelopers.meta.com%2Fwearables%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

News

[Meta for Developers](https://l.facebook.com/l.php?u=https%3A%2F%2Fdevelopers.meta.com%2Fblog%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

[Blog](/blog/)

[Success stories](/success-stories/)

Support

[Developer Support](/support/)

[Bug tool](/support/bugs/)

[Platform status](https://l.facebook.com/l.php?u=https%3A%2F%2Fmetastatus.com%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

[Developer community forum](https://www.facebook.com/groups/fbdevelopers/)

[Report an incident](/incident/report/)

About us

[About](https://l.facebook.com/l.php?u=https%3A%2F%2Fabout.fb.com%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

[Careers](https://www.facebook.com/careers)

Terms and policies

[Responsible platform initiatives](/products/responsible-platform-initiatives/)

[Platform terms](/terms/dfc_platform_terms/)

[Developer policies](/devpolicy/)

[Privacy policy](https://www.facebook.com/about/privacy)

[Cookies](https://www.facebook.com/help/cookies)

Build with Meta

[AI](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.llama.com%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

[Meta Horizon](https://l.facebook.com/l.php?u=https%3A%2F%2Fdevelopers.meta.com%2Fhorizon%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

[Social technologies](/social-technologies/)

[Wearables](https://l.facebook.com/l.php?u=https%3A%2F%2Fdevelopers.meta.com%2Fwearables%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

News

[Meta for Developers](https://l.facebook.com/l.php?u=https%3A%2F%2Fdevelopers.meta.com%2Fblog%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

[Blog](/blog/)

[Success stories](/success-stories/)

Support

[Developer Support](/support/)

[Bug tool](/support/bugs/)

[Platform status](https://l.facebook.com/l.php?u=https%3A%2F%2Fmetastatus.com%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

[Developer community forum](https://www.facebook.com/groups/fbdevelopers/)

[Report an incident](/incident/report/)

About us

[About](https://l.facebook.com/l.php?u=https%3A%2F%2Fabout.fb.com%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

[Careers](https://www.facebook.com/careers)

Terms and policies

[Responsible platform initiatives](/products/responsible-platform-initiatives/)

[Platform terms](/terms/dfc_platform_terms/)

[Developer policies](/devpolicy/)

[Privacy policy](https://www.facebook.com/about/privacy)

[Cookies](https://www.facebook.com/help/cookies)

Build with Meta

[AI](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.llama.com%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

[Meta Horizon](https://l.facebook.com/l.php?u=https%3A%2F%2Fdevelopers.meta.com%2Fhorizon%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

[Social technologies](/social-technologies/)

[Wearables](https://l.facebook.com/l.php?u=https%3A%2F%2Fdevelopers.meta.com%2Fwearables%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

News

[Meta for Developers](https://l.facebook.com/l.php?u=https%3A%2F%2Fdevelopers.meta.com%2Fblog%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

[Blog](/blog/)

[Success stories](/success-stories/)

Support

[Developer Support](/support/)

[Bug tool](/support/bugs/)

[Platform status](https://l.facebook.com/l.php?u=https%3A%2F%2Fmetastatus.com%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

[Developer community forum](https://www.facebook.com/groups/fbdevelopers/)

[Report an incident](/incident/report/)

About us

[About](https://l.facebook.com/l.php?u=https%3A%2F%2Fabout.fb.com%2F&h=AUAgKpaG-2vasLr6d9dXb7VxJjBtaU5vYLaihXtK53_ehqP18pBoqYfWmQibl8_bCRajPiLcXVIALkGnFYp7gPX9Yv17zAIox7_HnrySJHySrhK_OB_islsrk3y5cwnXNPLI38lRNfwwW9Rl)

[Careers](https://www.facebook.com/careers)

Terms and policies

[Responsible platform initiatives](/products/responsible-platform-initiatives/)

[Platform terms](/terms/dfc_platform_terms/)

[Developer policies](/devpolicy/)

[Privacy policy](https://www.facebook.com/about/privacy)

[Cookies](https://www.facebook.com/help/cookies)

English (US)

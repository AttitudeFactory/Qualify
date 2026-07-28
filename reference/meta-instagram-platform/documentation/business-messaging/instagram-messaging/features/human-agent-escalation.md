# Human Agent Escalation



Your app can implement an escalation path to a human agent using a custom inbox only or using an automated experience.

## Custom inbox only (no automation) &#123;#custom-inbox-only&#125;

With the custom inbox only solution (no automation), end users interact with the human agent directly rather than initiating the conversation with a keyword or intent. If your app uses this path to escalate to a human agent, ensure it can:

* Receive messages sent by end users and render them correctly in the custom inbox using the [Conversation API](https://developers.facebook.com/documentation/business-messaging/messenger-platform/conversations) with the given app ID
* Reply to messages via the custom inbox and confirm that end users receive them, using the [Send API](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/send-message#send-api) with the given app ID

## Automated experiences &#123;#automated-experiences&#125;

If your app has an automated experience, it can escalate to a human agent using a fallback intent, keyword, or quick replies when a certain scenario or flow is met.

As soon as the scenario or flow is met the escalation to a human agent can be done in the following ways:

* **Custom Inbox** - The ability to receive or reply to messages to end users from the custom inbox, which is powered by the same app ID
* **Conversation Routing API** - Use [this API](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/conversation-routing) to pass thread control to either Instagram Inbox (first-party) or a custom third-party inbox solution (using another FB app ID). For the app review process, demonstrate that when escalation to a human agent happens, thread ownership transfers to the inbox and the agent can use the inbox to reply to end users.

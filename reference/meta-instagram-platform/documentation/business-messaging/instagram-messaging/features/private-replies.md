# Private Replies



This document shows you how to programmatically add Private Replies to your messaging experience.

## How it works

Private Replies allows your app user to send a single message to an Instagram user who commented on the app user&#039;s Instagram professional account post, ads post, reel, or live story.

When your webhook server receives a `comments` or `live_comments` event notification, you can use the comment ID to send a private reply directly to the Instagram user who published the comment. This reply will be delivered to the Instagram user&#039;s **Inbox** folder, if the Instagram user follows the Instagram professional account, or to the Instagram user&#039;s **Request** folder, if the Instagram user does not follow the account.

Private replies can be sent within 7 days of when the comment was created, excepting Instagram Live for which you a private reply can only be sent during the live broadcast. The message will contain a link to the post that the Instagram user commented on.

### Webhooks &#123;#webhooks&#125;

- When hosting an Instagram Live story, make sure your server can handle the increased load of notifications triggered by

[`live_comments` webhooks events, via the Instagram API,](https://developers.facebook.com/docs/instagram-api/guides/webhooks)
and that your system can differentiate between `live_comments` and `comments` notifications.

- Instagram Graph API `comments` webhooks notifications for ads posts will include the ID and title for the ad. You may need to update your webhooks server to handle these new fields.

**Success:** The `ad_id` and `ad_title` will be returned in the media object when an Instagram user comments on a boosted Instagram post or Instagram ads post. Commenting on a boosted or ads post may result in duplicate webhook notifications.

### Limitations

* Only one message can be sent to the Instagram user who commented.
* The message must be sent within 7 days from when the comment was created for comments on a post, ads post, or reel.
* Due to the transient nature of Instagram Live Stories, private replies on Instagram Live Story comments can only be sent during the live broadcast. As soon as the live broadcast has ended, private replies can no longer be sent.
* Only when the Instagram user responds to the private message can you continue the conversation within the 24-hour messaging window.
* Standard Access apps can only access data for people who have a role on the app.

### Before you start

This guide assumes you have read the [Messenger Platform Overview](https://developers.facebook.com/documentation/business-messaging/messenger-platform/overview) and the [Instagram Messaging Overview](https://developers.facebook.com/docs/messenger-platform/instagram/overview) and implemented the needed components.

You will need:

* The ID for the Facebook Page linked to your Instagram professional account
* The ID for the comment made by the person to whom you are sending the private reply. The ID can be obtained from the Instagram `comments` webhooks, for posts, ads posts, and reels, and Instagram `live_comments` webhooks for live stories (recommended to avoid rate limiting) or an API call to the `/page/feed` endpoint
* The `instagram_manage_comments` and `pages_messaging` permissions, obtained via Facebook Login
* A Page access token requested by an Instagram user who can perform the `MESSAGING` task on the Facebook Page linked to your Instagram professional account
* The Human Agent feature
* Advanced Access

## Send a private reply

To send a private reply to an Instagram user who commented on your post, reel, or live story, send a `POST` request to the `/&lt;PAGE_ID&gt;/messages` endpoint where the `recipient` parameter contains the comment ID and the `message` parameter contains the text you wish to send.

*Formatted for readability.*

### cURL
```
curl -i -X POST &quot;https://graph.facebook.com/&lt;PAGE_ID&gt;/messages
  ?recipient: &#123; comment_id: &lt;COMMENT_ID&gt; &#125;
  &amp;message: &#123; &quot;text&quot;: &quot;Thanks for reaching out, how can I help?&quot; &#125;
  &amp;access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot;
```

### Android SDK
```
GraphRequest request = GraphRequest.newPostRequest(
  accessToken,
  &quot;/1353269864728879/messages&quot;,
  new JSONObject(&quot;&#123;\&quot;recipient\&quot;:\&quot;&#123;comment_id: 18000158536435933&#125;\&quot;,\&quot;message\&quot;:\&quot;&#123;\\\&quot;text\\\&quot;: \\\&quot;It is cool\\\&quot;&#125;\&quot;&#125;&quot;),
  new GraphRequest.Callback() &#123;
    &#064;Override
    public void onCompleted(GraphResponse response) &#123;
      // Insert your code here
    &#125;
&#125;);
request.executeAsync();
```

### Objective-C
```
FBSDKGraphRequest *request = [[FBSDKGraphRequest alloc]
    initWithGraphPath:&#064;&quot;/1353269864728879/messages&quot;
           parameters:&#064;&#123; &#064;&quot;recipient&quot;: &#064;&quot;&#123;comment_id: 18000158536435933&#125;&quot;,&#064;&quot;message&quot;: &#064;&quot;&#123;&quot;text&quot;: &quot;It is cool&quot;&#125;&quot;,&#125;
           HTTPMethod:&#064;&quot;POST&quot;];
[request startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection, id result, NSError *error) &#123;
    // Insert your code here
&#125;];
```

### Java SDK
```
FB.api(
  &#039;/1353269864728879/messages&#039;,
  &#039;POST&#039;,
  &#123;&quot;recipient&quot;:&quot;&#123;comment_id: 18000158536435933&#125;&quot;,&quot;message&quot;:&quot;&#123;\&quot;text\&quot;: \&quot;It is cool\&quot;&#125;&quot;&#125;,
  function(response) &#123;
      // Insert your code here
  &#125;
);
```

On success, your app will receive the following response:

```json
&#123;
  &quot;recipient_id&quot;: &quot;526...&quot;,   // The Instagram-scoped ID
  &quot;message_id&quot;: &quot;aWdfZ...&quot;    // The message ID for your private reply
&#125;
```

## See also

- [Access Levels](https://developers.facebook.com/documentation/business-messaging/messenger-platform/overview#advanced---standard-access) – Learn about the access levels and data available for each.

- [Instagram Live Media and Comments](https://developers.facebook.com/docs/instagram-api/reference/ig-user/live_media) – Visit the Instagram Graph API Reference for more information about live media.

- [Instagram Media and Comments](https://developers.facebook.com/docs/instagram-api/reference/ig-media) – Visit the Instagram Graph API Reference for more information about Instagram media.

- [Rate limits for Instagram Messaging API](https://developers.facebook.com/documentation/business-messaging/messenger-platform/overview#rate-limiting) – Learn more about the rate limits that affect Instagram Messaging.

- [Tasks on Facebook Pages](https://developers.facebook.com/docs/pages/overview/permissions-features#tasks) – Learn about the tasks people can perform on the Page.

- [Webhooks for Messenger Platform](https://developers.facebook.com/documentation/business-messaging/messenger-platform/webhooks) – Learn about the webhooks available for Instagram Messaging

### Developer Support

* Use the  [Meta Status tool](https://metastatus.com) to check for the status and outages of Meta business products.
* Use the [Meta Developer Support tool](https://developers.facebook.com/support) to report bugs and view reported bugs, get help with Ads or Business Manager, and more.


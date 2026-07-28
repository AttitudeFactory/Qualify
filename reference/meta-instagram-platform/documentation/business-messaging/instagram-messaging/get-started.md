# Getting Started



This document explains how to successfully call Messenger API support for Instagram (also known as Instagram Messaging API in our Developer Policies) with your app and get Instagram professional account messages.

**Note:** If your app users don&#039;t have a Facebook Page linked to their Instagram professional account, learn more about building an app with [the Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram/platform/instagram-api).


## Before you start

You will need access to the following:

* An Instagram [professional account](https://www.facebook.com/help/instagram/138925576505882)
* A Facebook Page connected to that [account](https://developers.facebook.com/docs/instagram-api/overview#pages)
* A Meta Developer account that can perform the [`MODERATE` task](https://developers.facebook.com/docs/instagram-api/overview#tasks) on that Page
* A [Meta App](https://developers.facebook.com/docs/apps#register) created with the Facebook Login Use Case and with Basic settings configured

If you are a developer who is new to the Messenger Platform:

- Follow the step-by-step guide detailed below on how to generate Page access token, webhooks setup.

- Learn about the various [platform features](https://developers.facebook.com/docs/messenger-platform/instagram/features) and adopt those that suit your needs.

Developers with prior experience on the Messenger Platform

* Access token and webhooks concepts are similar. Messenger API support for Instagram will require `instagram_manage_messages` in the Page access token and Instagram topic webhooks subscribed.
* Most of the features are similar to Messenger API. Review the details on feature list and adopt those that suit your needs.

### Login flow

You can use Facebook Login for Business or Business Login for Instagram to ask your app users for the needed permissions.

The
[Business Login for Instagram](https://developers.facebook.com/docs/instagram/business-login-for-instagram) flow allows a person to complete the following during the login flow:

- convert their Instagram account to an Instagram professional account

- create a Facebook Page for their business

- connect that Page to their Instagram professional account

To implement Business Login for Instagram, visit our
[Business Login for Instagram guide](https://developers.facebook.com/docs/instagram/business-login-for-instagram) then return to this guide.

## 1. Get a user access token

Make sure you are signed into your Facebook Developer account, then access your app and trigger the Facebook Login modal. Remember, your Facebook Developer account must be able to perform [Tasks](https://developers.facebook.com/docs/pages-api/overview#tasks) with at least &quot;Moderate&quot; level access on the [Facebook Page](https://developers.facebook.com/docs/pages-api/overview) connected to the Instagram account you want to query.

Once you have triggered the modal, click OK to grant your app the `instagram_basic`, `instagram_manage_messages`, and `pages_manage_metadata` permissions.

The API should return a User access token. Capture the token so your app can use it in the next few queries. If you are using the Graph API Explorer, it will be captured automatically and displayed in the Access Token field for reference:

## 2. Get the user&#039;s Pages

Query the `GET /me/accounts` endpoint (this translates to `GET /&#123;user-id&#125;/accounts`, which performs a GET on the Facebook [User](https://developers.facebook.com/docs/graph-api/reference/user) node, based on your access token).

```bash
curl -i -X GET \
 &quot;https://graph.facebook.com/v9.0/me/accounts?access_token=&#123;access-token&#125;&quot;
```

This should return a collection of Facebook Pages that the current Facebook User can perform the `MANAGE`, `CREATE_CONTENT`, `MODERATE`, or `ADVERTISE` tasks on:  

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;access_token&quot;: &quot;EAAJjmJ...&quot;,
      &quot;category&quot;: &quot;App Page&quot;,
      &quot;category_list&quot;: [
        &#123;
          &quot;id&quot;: &quot;2301&quot;,
          &quot;name&quot;: &quot;App Page&quot;
        &#125;
      ],
      &quot;name&quot;: &quot;Metricsaurus&quot;,
      &quot;id&quot;: &quot;134895793791914&quot;,  // capture the Page ID
      &quot;tasks&quot;: [
        &quot;ANALYZE&quot;,
        &quot;ADVERTISE&quot;,
        &quot;MODERATE&quot;,
        &quot;CREATE_CONTENT&quot;,
        &quot;MANAGE&quot;
      ]
    &#125;
  ]
&#125;
```

Capture the ID of the Facebook Page that&#039;s connected to the Instagram account that you want to query. Keep in mind that your app users may be able to perform tasks on multiple pages, so you eventually will have to introduce logic that can determine the correct Page ID to capture (or devise a UI where your app users can identify the correct Page for you).  

## 3. Get the Page access token

In order to perform various Instagram Messaging API calls, you will need to use the associated Page access token (PAT) of the relevant Instagram professional account that has been previously granted via Facebook login flow.

Send a `GET` request to the `/&#123;page-id&#125;` endpoint using your User access token. For example:

```bash
curl -i -X GET &quot;https://graph.facebook.com/&#123;page-id&#125;?
  fields=access_token&amp;
  access_token=&#123;user-access-token&#125;&quot;
```

On success, your app gets this response:

```json
&#123;
  &quot;access_token&quot;:&quot;&#123;page-access-token&#125;&quot;,
  &quot;id&quot;:&quot;&#123;page-id&#125;&quot;
&#125;
```

* If you used a short-lived User access token, the Page access token is valid for only 1 hour.
* If you used a long-lived User access token, the Page access token has no expiration date.

To generate a long-lived Page access token, you can follow the guide [here](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens/get-long-lived#get-a-long-lived-page-access-token).

## 3a. Get the Page access token via the Instagram Developer Dashboard tool &#123;#app-dashboard&#125;

**Note:** Meta is rolling out this tool to all developers over the coming weeks. If you don&#039;t see the settings under the App Dashboard, you can leverage Step 1-5 above to generate Page Access Tokens.

Optionally, if you own the assets (Instagram account and Facebook Page) that you want to onboard to Messenger API support for Instagram, you can leverage the Instagram setup tool under the Developer App Dashboard to allow you to easily setup Page access tokens and Webhooks. You can find the tool under Developer app dashboard → Messenger → Instagram Settings. Existing way of configuring tokens and webhook will still work, but this tool will give you an easier way to setup your environment.

## 4. Enable message control connected tools settings &#123;#connected-tools-toggle&#125;

In order to manage Instagram messages via API, Instagram professional accounts will need to enable the connected tools toggle under message controls settings. This setting can be found by going to:

**Instagram Settings &gt; Messages and story replies &gt;Message controls &gt; Connected Tools &gt; toggle Allow Access to Messages**

## 5. Get the Instagram professional account&#039;s Inbox Objects

Use the Page ID you captured and the Page access token (PAT) to query the `GET /&#123;page-id&#125;/conversations?platform=instagram` endpoint:  

```bash
curl -i -X GET \
 &quot;https://graph.facebook.com/v9.0/17841405822304914/conversations?platform=instagram&amp;access_token=&#123;access-token&#125;&quot;
```

This should return the IDs of all the thread objects on the Instagram user:

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;id&quot;: &quot;aWdfZAG06MTpJR01lc3NhZA2VUaHJlYWQ6OTAwMTAxNDYyOTkyODI6MzQwMjgyMzY2ODQxNzEwMzAwOTQ5MTI4MTM2MDk5MDc1MzYyOTgx&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;aWdfZAG06MTpJR01lc3NhZA2VUaHJlYWQ6OTAwMTAxNDYyOTkyODI6MzQwMjgyMzY2ODQxNzEwMzAwOTQ5MTI4MTYzMzQ2MzE5NjM1NDcy&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;aWdfZAG06MTpJR01lc3NhZA2VUaHJlYWQ6OTAwMTAxNDYyOTkyODI6MzQwMjgyMzY2ODQxNzEwMzAwOTQ5MTI4MTk3MTY0NjI2NzAyMjMw&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;aWdfZAG06MTpJR01lc3NhZA2VUaHJlYWQ6OTAwMTAxNDYyOTkyODI6MzQwMjgyMzY2ODQxNzEwMzAwOTQ5MTI4MzkzNDI5MDYzMzkyNjU0&quot;
    &#125;
&#125;
```

If you can perform this final query successfully, you should be able to perform queries using any of the Messenger API support for Instagram endpoints - just refer to our various guides and references to learn what each endpoint can do and what permission they require.

## Next steps

* [Develop your app further](https://developers.facebook.com/docs/messenger-platform/instagram/features) so it can successfully use any other endpoints it needs, and keep track of the permissions each endpoint requires
* Complete the [webhook setup](https://developers.facebook.com/documentation/business-messaging/messenger-platform/webhooks) so it can receive real time notifications whenever a user sends a message to the Instagram professional account.
* Complete the [App Review](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/app-review) process and request approval for all permissions your app will need so your app users can grant them while your app is in production.

### Developer Support

* Use the  [Meta Status tool](https://metastatus.com) to check for the status and outages of Meta business products.
* Use the [Meta Developer Support tool](https://developers.facebook.com/support) to report bugs and view reported bugs, get help with Ads or Business Manager, and more.


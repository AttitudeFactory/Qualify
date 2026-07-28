# Get Started



This document explains how to make your first call using the Instagram API with Instagram Login to obtain information about your Instagram professional account, including your User ID, username, and media objects.  

## Before You Start

This guide assumes you have read the [Instagram Platform Overview](https://developers.facebook.com/documentation/instagram-platform/overview) and implemented the needed components for using this API, such as a Meta login flow and a webhooks server to receive notifications.

**Warning:** If your current Meta app type is **not** a Business type app you will need to create a new app and [select **Business** during the creation process.](https://developers.facebook.com/documentation/instagram-platform/create-an-instagram-app#step-4--select-your-app-type) If this new app needs Advanced Access, App Review is required.

## Get an access token

An access token contains information about the app making the request, the token&#039;s expiration date, the app user&#039;s Instagram User ID and the permissions the user has granted the app. You can get an Instagram user access token using one of the following methods:

**[Business Login for Instagram](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login)
**

If you have implemented Business Login for Instagram into your app, log in to your app.

**[App Dashboard](https://developers.facebook.com/apps)
**

If you have not implemented Business Login for Instagram,  Get an access token via the App Dashboard.

1. In your app dashboard, click **Instagram &gt; API setup with Instagram business login** in the left side menu.
2. Click **Generate token** next to the Instagram account you want to access.
3. Log into Instagram.
4. Copy the access token.

Access tokens from the business login flow are short-lived and valid for 1 hour. Access tokens from the App Dashboard are long-lived and are valid for 60 days. [Learn how to extend the expiry of any access token.](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login#get-a-long-lived-access-token)

## Get the app user ID &amp; username

To obtain your app user&#039;s Instagram professional account user ID and username, send a `GET` request to the `/me` endpoint with the following parameters:

* `fields` set to a comma-separated list with `user_id` and `username`
* `access_token` set to the access token from the app dashboard

**Note:** The `/me` endpoint represents the app user&#039;s ID received from the access token, in this example, your user ID.

### Example request

_Formatted for readability._

```html
curl -i -X GET \
 &quot;https://graph.instagram.com/v25.0/me
      ?fields=user_id,username
      &amp;access_token=Ealkdfj...&quot;
```

On success, your app receives a JSON object with the app user&#039;s Instagram user ID and the username of the Instagram professional account.

```html
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;user_id&quot;: &quot;&lt;IG_ID&gt;&quot;
      &quot;username&quot;: &quot;&lt;IG_USERNAME&gt;&quot;
    &#125;
  ]
&#125;
```

### Fields &#123;#fields&#125;

You can use the `fields` query string parameter to request the following fields on a User.

| Field Name | Description |
| --- | --- |
| `id` | The app user&#039;s app-scoped ID |
| `user_id` | The Instagram professional acount ID, `&lt;IG_ID&gt;`, for your app user. This ID is value of the `id` field received in webhook notifications for this account. |
| `username` | The app user&#039;s Instagram username. |
| `name` | The app user&#039;s name |
| `account_type` | The app user&#039;s account type. Can be `Business` or `Media_Creator`. |
| `profile_picture_url` | The URL for the app user&#039;s  profile picture. |
| `followers_count` | The number of followers of the app user&#039;s Instagram professional account |
| `follows_count` | The number of Instagram accounts the app user&#039;s Instagram professional account follows |
| `media_count` | The number of Media object on the User |

## Get an app user&#039;s media objects &#123;#posts&#125;

To get media objects, send a `GET` request to the `/&lt;IG_ID&gt;/media` endpoint.

### Example request

_Formatted for readability._

```html
curl -i -X GET \
 &quot;https://graph.instagram.com/v25.0/&lt;IG_ID&gt;/media?access_token=&lt;INSTAGRAM_USER_ACCESS_TOKEN&gt;&quot;
```

On success your app receives a JSON object with the IDs of all the [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects on the [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user):

```html
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;id&quot;: &quot;17918195224117851&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17895695668004550&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17899305451014820&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17896450804038745&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17881042411086627&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17869102915168123&quot;
    &#125;
  ],
  &quot;paging&quot;: &#123;
    &quot;cursors&quot;: &#123;
      &quot;before&quot;: &quot;QVFIUkdGRXA2eHNNTUs4T1ZAXNGFxQTAtd3U4QjBLd1B2NXRMM1NkcnhqRFdBcEUzSDVJZATFoLWtXMWZAGU2VrRTk2RHVtTVlDckI2NjN0UERFa2JrUk4yMW13&quot;,
      &quot;after&quot;: &quot;QVFIUmlwbnFsM3N2cV9lZAFdCa0hDeV9qMVliT0VuMmJyNENxZA180c0t6VjFQVEJaTE9XV085aU92OUFLNFB6Szd2amo5aV9rTlVBcnNlWmEtMzYxcE1HSFR3&quot;
    &#125;
  &#125;
&#125;
```

If you are able to perform this final query successfully, you should be able to perform queries using any of the Instagram API with Instagram Login endpoints — just see our various guides and references to learn what each endpoint can do and what permissions they require.

## Next Steps

Now that you know how to get access tokens and Instagram User IDs for your app users, learn how to [subscribe your app users to Instagram webhooks notifications.](https://developers.facebook.com/documentation/instagram-platform/webhooks)

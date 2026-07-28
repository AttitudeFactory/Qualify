# Facebook Login for Business



Facebook Login for Business is a custom, [manual Facebook Login flow](https://developers.facebook.com/documentation/facebook-login/guides/advanced/manual-flow) that makes it easier for you to onboard Instagram users who still need to configure their account for API access.

In order to make their account accessible to our APIs, Instagram users must first  convert their account to a Professional account, create a Facebook Page that represents their business, then connect that Page to their account.

Facebook Login for Business  simplifies this process by allowing Instagram users to complete all of these steps in a single window instead of having to complete them in the Facebook and Instagram apps.

## Before You Start

You will need a Meta [Business type app](https://developers.facebook.com/documentation/development/create-an-app/other-app-types) to add the following products:

* Instagram &gt; API setup with Facebook login
* Facebook Login for Business
* Webhooks

Add the Facebook Login for B product to your app and add a redirect URL. We will redirect users to this URL after they complete the onboarding flow.

1. Go to the [Apps Panel](https://developers.facebook.com/apps) and select your app to load it in the App Dashboard.
1. In the left-hand menu, click **Add Products**, locate **Facebook Login for Business**, then click **Set Up** to add it to your app.
1. In the left-hand menu under **Facebook Login for Business**, click **Settings**.
1. In the **Client OAuth Settings** &gt; **Valid OAuth Redirect URIs** field, enter your redirect URL.

## Step 1: Construct the Login URL

Construct the Business Login URL using its base URL and query string parameters.

### URL Syntax

```http
https://www.facebook.com/dialog/oauth
  ?client_id=&#123;client-id&#125;
  &amp;display=&#123;display&#125;
  &amp;extras=&#123;extras&#125;
  &amp;redirect_uri=&#123;redirect-uri&#125;
  &amp;response_type=&#123;response_type&#125;
  &amp;scope=&#123;scope&#125;
```

### Query String Parameters

All parameters are **required**.

| Key | Placeholder | Description | Sample Value |
| --- | --- | --- | --- |
| `client_id` | `&#123;client-id&#125;` | Your Meta app ID. | `442224939723604` |
| `display` | `&#123;display&#125;` | Set to `page`. | `page` |
| `extras` | `&#123;extras&#125;` | Set to `&#123;&quot;setup&quot;:&#123;&quot;channel&quot;:&quot;IG_API_ONBOARDING&quot;&#125;&#125;`. | `&#123;&quot;setup&quot;:&#123;&quot;channel&quot;:&quot;IG_API_ONBOARDING&quot;&#125;&#125;` |
| `redirect_uri` | `&#123;redirect_uri&#125;` | URL to redirect user to after completing login flow. This URL must match a URL in the **Facebook Login** &gt; **Settings** &gt; **Client OAuth Settings** &gt; **Valid OAuth Redirect URI** field in the **App Dashboard**.&lt;br&gt;&lt;br&gt;See [Before you start](#before-you-start). | `https://my-clever-redirect-url.com/success/` |
| `response_type` | `&#123;response_type&#125;` | Set to `token`. | `token` |
| `scope` | `&#123;scope&#125;` | A list of permissions you want to request from the user.&lt;br&gt;&lt;br&gt;The list of permission you request will depend on which APIs your app relies on. Refer the endpoint references for any endpoints your app uses to determine which permission you should request. | `instagram_basic,instagram_content_publish,instagram_manage_comments,instagram_manage_insights,pages_show_list,pages_read_engagement` |

### Example URL

This is an example of a URL constructed by an app that relies on the Instagram Messaging API and has therefore requested permissions required by Messaging API endpoints.

```http
https://www.facebook.com/v25.0/dialog/oauth?client_id=442224939723604&amp;display=page&amp;extras=&#123;&quot;setup&quot;:&#123;&quot;channel&quot;:&quot;IG_API_ONBOARDING&quot;&#125;&#125;&amp;redirect_uri=https://my-clever-redirect-url.com/success/&amp;response_type=token&amp;scope=instagram_basic,instagram_content_publish,instagram_manage_comments,instagram_manage_insights,pages_show_list,pages_read_engagement
```

## Step 2: Assign the URL to a Button

Assign the URL to a standard anchor link or button of your own design and display it to any users who you are certain have not completed the onboarding flow.

### Example Anchor Link

```html
&lt;a href=&quot;https://www.facebook.com/v25.0/dialog/oauth?client_id=442224939723604&amp;display=page&amp;extras=&#123;&quot;setup&quot;:&#123;&quot;channel&quot;:&quot;IG_API_ONBOARDING&quot;&#125;&#125;&amp;redirect_uri=https://my-clever-redirect-url.com/success/&amp;response_type=token&amp;scope=instagram_basic,instagram_content_publish,instagram_manage_comments,instagram_manage_insights,pages_show_list,pages_read_engagement&quot;&gt;Login to Facebook&lt;/a&gt;
```

## Step 3: Capture User access token

After a user clicks your link or button and completes the Business Login for Instagram flow, we will redirect the user to the URL you assigned to the `redirect_uri`. We will also append a URL fragment (`#`) with the user&#039;s short-lived [User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens), some metadata about the token, and the user&#039;s [long-lived access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens/get-long-lived). Capture the long-lived access token.

### Canceled Login

If a user cancels out of the login flow we will still redirect the user to your `redirect_uri` but append different data. Refer to the [Manually Build a Login Flow](https://developers.facebook.com/documentation/facebook-login/guides/advanced/manual-flow) document&#039;s [Canceled Login](https://developers.facebook.com/documentation/facebook-login/guides/advanced/manual-flow#nonjscancel) section to learn how process these redirects.

### Redirect Syntax

```http
&#123;redirect-url&#125;?
  #access_token=&#123;access-token&#125;
  &amp;data_access_expiration_time=&#123;data-access-expiration-time&#125;
  &amp;expires_in=&#123;expires-in&#125;
  &amp;long_lived_token=&#123;long-lived-token&#125;
```

### Fragment Providers

Token values have been truncated (`...`) in this example for readibility.

| Key | Placeholder | Description | Sample Value |
| --- | --- | --- | --- |
| `access_token` | `&#123;access-token&#125;` | The user&#039;s short-lived [User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens). | `EAAHm...` |
| `data_access_expiration_time` | `&#123;data-access-expiration-time&#125;` | ISO 8601 timestamp when [data access expires](https://developers.facebook.com/documentation/facebook-login/auth-vs-data#data-access-expiration). | `1658889585` |
| `expires_in` | `&#123;expires-in&#125;` | Number of seconds until the short-lived User access token expires. | `4815` |
| `long_lived_token` | `&#123;long-lived-token&#125;` | The user&#039;s [long-lived access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens/get-long-lived). | `ABAEs...` |

### Example Redirect

Token values have been truncated (`...`) in this example for readability.

```http
https://my-clever-redirect-url.com/success/?#access_token=EAAHm...&amp;data_access_expiration_time=1658889585&amp;expires_in=4815&amp;long_lived_token=ABAEs...
```

## Step 4: Get the User&#039;s Page, Page Access Token, and Instagram Business Account

Send a request to the `GET /me/accounts` endpoint and request the following fields:

* `id`
* `name`
* `access_token`
* `instagram_business_account`

This will return a collection of Facebook Pages that the user can perform tasks on. For each Page in the result set, the response will include its:

* ID
* Name
* [Page access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#pagetokens)
* Instagram Business account ID connected to the Page

### cURL Example

Token values have been truncated (`...`) in this example for readability.

```curl
curl -i -X GET \
 &quot;https://graph.facebook.com/v25.0/me/accounts?fields=id%2Cname%2Caccess_token%2Cinstagram_business_account&amp;access_token=EAACw...&quot;
```

### Example Response

Token values have been truncated (`...`) in this example for readability.

```json
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;id&quot;: &quot;134895793791914&quot;,
      &quot;name&quot;: &quot;Metricsaurus&quot;,
      &quot;access_token&quot;: &quot;EAACw...&quot;,
      &quot;instagram_business_account&quot;: &#123;
        &quot;id&quot;: &quot;17841405309211844&quot;
      &#125;
    &#125;
  ],
  &quot;paging&quot;: &#123;
    &quot;cursors&quot;: &#123;
      &quot;before&quot;: &quot;MTc1NTg0Nzc2ODAzNDQwMgZDZD&quot;,
      &quot;after&quot;: &quot;MTc1NTg0Nzc2ODAzNDQwMgZDZD&quot;
    &#125;
  &#125;
&#125;
```

Capture the Page ID (`id`), Page access token (`access_token`), and Instagram Professional account ID (`instagram_business_account`) for the Page that the user has connected to their Instagram Professional account.

Keep in mind that some users may be able to perform tasks on more than one Page. If multiple Pages are included in the response, you may have to surface each Page&#039;s name (`name`) to the user so they can identify which Page&#039;s data to capture.

## Conclusion

You should now have everything you need to help your access and work with their data using our various APIs:

* Instagram Business account ID
* ID of the Facebook Page connected to the Instagram Business account
* the Facebook Page&#039;s access token (required by the [Instagram Messaging API](https://developers.facebook.com/documentation/business-messaging/instagram-messaging))
* a User access token from the user, who is able to perform tasks on the Facebook Page connected to the Instagram Business account (required by the [Instagram Graph API](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login))

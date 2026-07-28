# Facebook Login for Business



Facebook Login for Business is the preferred authentication and authorization solution for tech providers building integrations with Meta’s business tools to create marketing, messaging, and selling solutions.

Facebook Login for Business allows you to create a login experience in the Meta App Dashboard based on the needs of your app. You can specify the access token type, assets, and permissions your app needs, and save it as a **configuration**. During login your app users are presented with this configuration that allows them to grant your app access to their business assets.

## Requirements

- Your Meta app must be a [**business type app**](https://developers.facebook.com/docs/development/create-an-app/other-app-types#step-3--select-an-app-type)

- All permissions that your app asks for during login must be granted by your app user or your app won&#039;t be granted any permissions.

- The `email` and `public_profile` permissions are automatically granted to all apps but at least one other supported permission must be included for each app installation.

- To serve businesses that you do not own or manage, your app must be approved for **Advanced Access** via [**Meta&#039;s App Review**](https://developers.facebook.com/docs/app-review)

- Apps with Advanced Access are required to undergo [Ongoing Review](https://developers.facebook.com/documentation/resp-plat-initiatives/individual-processes/ongoing-reviews) to retain access. However, apps using Facebook Login for Business have reduced requirements for certain ongoing compliance reviews because they are limited to accessing business permissions and features.

## Supported permissions

The following table shows the available permissions for Facebook Login for Business.

| Available Permissions | User access tokens | Business Integration System User access tokens |
| --- | --- | --- |
| [`ads_management`](https://developers.facebook.com/docs/permissions#ads_management) | ✓ | ✓ |
| [`ads_read`](https://developers.facebook.com/docs/permissions#ads_read) | ✓ | ✓ |
| [`business_management`](https://developers.facebook.com/docs/permissions#business_management) | ✓ | ✓ |
| [`catalog_management`](https://developers.facebook.com/docs/permissions#catalog_management) | ✓ | ✓ |
| [`email`](https://developers.facebook.com/docs/permissions#email) | ✓ | N/A |
| [`instagram_basic`](https://developers.facebook.com/docs/permissions#instagram_basic) | ✓ | ✓ |
| [`instagram_content_publish`](https://developers.facebook.com/docs/permissions#instagram_content_publish) | ✓ | ✓ |
| [`instagram_manage_comments`](https://developers.facebook.com/docs/permissions#instagram_manage_comments) | ✓ | ✓ |
| [`instagram_manage_insights`](https://developers.facebook.com/docs/permissions#instagram_manage_insights) | ✓ | ✓ |
| [`instagram_manage_messages`](https://developers.facebook.com/docs/permissions#instagram_manage_messages) | ✓ | ✓ |
| [`instagram_shopping_tag_products`](https://developers.facebook.com/docs/permissions#instagram_shopping_tag_products) | ✓ | ✓ |
| [`leads_retrieval`](https://developers.facebook.com/docs/permissions#leads_retrieval) | ✓ | ✓ |
| [`manage_app_solutions`](https://developers.facebook.com/docs/permissions#manage_app_solution) | ✓ | ✓ |
| [`manage_fundraisers`](https://developers.facebook.com/docs/permissions#manage_fundraisers) | ✓ | ✓ |
| [`pages_manage_cta`](https://developers.facebook.com/docs/permissions#pages_manage_cta) | ✓ | ✓ |
| [`page_events`](https://developers.facebook.com/docs/permissions#page_events) | ✓ | ✓ |
| [`pages_manage_ads`](https://developers.facebook.com/docs/permissions#pages_manage_ads) | ✓ | ✓ |
| [`pages_manage_engagement`](https://developers.facebook.com/docs/permissions#pages_manage_engagement) | ✓ | ✓ |
| [`pages_manage_instant_articles`](https://developers.facebook.com/docs/permissions#pages_manage_instant_articles) | ✓ | ✓ |
| [`pages_manage_metadata`](https://developers.facebook.com/docs/permissions#pages_manage_metadata) | ✓ | ✓ |
| [`pages_manage_posts`](https://developers.facebook.com/docs/permissions#pages_manage_posts) | ✓ | ✓ |
| [`pages_messaging`](https://developers.facebook.com/docs/permissions#pages_messaging) | ✓ | ✓ |
| [`pages_read_engagement`](https://developers.facebook.com/docs/permissions#pages_read_engagement) | ✓ | ✓ |
| [`pages_read_user_content`](https://developers.facebook.com/docs/permissions#pages_read_user_content) | ✓ | ✓ |
| [`pages_show_list`](https://developers.facebook.com/docs/permissions#pages_show_list) | ✓ | ✓ |
| [`private_computation_access`](https://developers.facebook.com/docs/permissions#private_computation_access) | ✓ | ✓ |
| [`public_profile`](https://developers.facebook.com/docs/permissions#public_profile) | ✓ | N/A |
| [`publish_video`](https://developers.facebook.com/docs/permissions#publish_video) | ✓ | ✓ |
| [`read_insights`](https://developers.facebook.com/docs/permissions#read_insights) | ✓ | ✓ |
| [`read_audience_network_insights`](https://developers.facebook.com/docs/permissions#read_audience_network_insights) | ✓ | ✓ |
| [`whatsapp_business_management`](https://developers.facebook.com/docs/permissions#whatsapp_business_management) | ✓ | ✓ |
| [`whatsapp_business_messaging`](https://developers.facebook.com/docs/permissions#whatsapp_business_messaging) | ✓ | ✓ |

## [Supported features](https://developers.facebook.com/docs/features-reference) &#123;#supported-features&#125;

* Marketing API Access Tier
* Business Asset User Profile Access
* Human Agent
* Instagram Public Content Access

* Live Video API
* Page Mentions
* Page Public Content Access
* Page Public Metadata Access

## Supported products

- [App Ads](https://developers.facebook.com/documentation/app-ads)

- [App Events](https://developers.facebook.com/docs/app-events)

- [App Links](https://developers.facebook.com/documentation/applinks)

- [Audience Network](https://developers.facebook.com/docs/audience-network)

- [Commerce Platform](https://developers.facebook.com/documentation/ads-commerce/commerce-platform)

- [Fundraiser API](https://developers.facebook.com/docs/fundraiser-api)

- [Instagram Platform](https://developers.facebook.com/documentation/instagram-platform)

- [Jobs](https://developers.facebook.com/docs/pages/jobs-xml)

- [Marketing API](https://developers.facebook.com/documentation/ads-commerce/marketing-api)

- [Messenger Platform](https://developers.facebook.com/documentation/business-messaging/messenger-platform)

- [Meta Business Extension](https://developers.facebook.com/docs/meta-business-extension)

- [Meta Pixel](https://developers.facebook.com/documentation/meta-pixel)

- [Pages API](https://developers.facebook.com/docs/pages-api)

- [Sharing](https://developers.facebook.com/docs/sharing)

- [ThreatExchange](https://developers.facebook.com/docs/threat-exchange)

- [Web Payments](https://developers.facebook.com/docs/games_payments)

- [Webhooks](https://developers.facebook.com/docs/graph-api/webhooks)

- [WhatsApp Business Platform](https://developers.facebook.com/documentation/business-messaging/whatsapp/overview)

## Supported access tokens

You can use Facebook Login for Business to get either Business Integration System User access tokens or User access tokens.

### User access tokens

User access tokens should be used if your app takes actions in real time, based on input from the user. For example, use a user access token if your app requires a user to input text and click a button in order to post content to their Page. User access tokens should also be used if you require an API that requires admin permissions on a business portfolio.

### Business integration system user access tokens

Business integration system user access tokens should be used if your app performs programmatic, automated actions on your business clients&#039; assets without having to rely on input from an app user, or require re-authentication at a future date. For example:

* Hourly, automated server-to-server conversion API calls
* Sending automated responses as a Facebook Page or WhatsApp business portfolio
* Continuous, automated updates to product catalog inventories
* Automated retrieval of ads insights

#### Requirements

To get business integration system user access tokens from your business clients:

- Your app can only request logins from web surfaces

- Businesses onboarding to your app must have, or be willing to create, a
[business portfolio](https://www.facebook.com/business/help/2199735813629697)

- Your app must be associated with a
[business portfolio,](https://www.facebook.com/business/help/2199735813629697)  which you have full control. This needs to be separate from the business portfolio owned by your business client.

To test the business integration system user access token flow, the tester must have a role on the app and full control of the client business.

#### Granular business integration system user access tokens

If you need different access setups for different purposes or departments, you can use multiple granular business integration system user access tokens per client business to improve the scalability and security of your integrations.

Granular access tokens are still specific to a client business portfolio. They are not shareable and accessible across different client businesses. Their scope and asset list are a subset of the original business integration system user access token.

To isolate potential security incidents in the event of a compromised token, only that specific client business will be impacted, instead of impacting all business portfolios across all client businesses.

### Comparison

|  | Business Integration System User access tokens | User access tokens |
| --- | --- | --- |
| Access Designations | Access is **explicitly delegated** at the time of authorization. Your app can only access the assets that were designated by your business client when they completed the Facebook Login for Business flow. Tech Providers only. | Access is **inherited** from your app user&#039;s current account access; your app can access the same business assets that the app user currently has access to. |
| Account association | Associated with your business client&#039;s business portfolio rather than a specific user. Any admin in your business client&#039;s admin group can grant your app a system user access token. | Associated with your app user&#039;s personal Facebook account. |
| Expiration and refresh | Defaults to **never expire** for the common offline server-to-server communication. | A **short-lived** token for online activities such as web browsers. |
| OAuth grant type | **Authorization Code** grant only. | **Implicit** grant by default, and can support authorization code grant for improved security. Mainly used for user-agent based clients such as web browsers and mobile apps. |
| Representation | Part of the Tech Provider integration&#039;s infrastructure, initialized by a client business through Tech Provider’s app installation. | Represents servers or software making API calls to assets owned or managed by a&lt;br&gt;[Business Manager.](https://developers.facebook.com/docs/business-manager-api)&lt;br&gt; |
| Token Invalidation | Your business clients can invalidate business integration system User access tokens by going to **[Business Manager](https://business.facebook.com) &gt; Settings &gt; Business Settings &gt; Integrations &gt; Connected apps** and removing your app.&lt;br&gt; | Your business clients can invalidate User access tokens by going to Facebook and navigating to **Settings &amp; privacy** &gt; **Settings** &gt; **Security and login** &gt; **Business Integrations** and removing your app. |

## Business Integration System User Access Token Management API &#123;#bisu-token-api&#125;

When a client business installs an app through Facebook Login for Business and generates a business integration system user access token, the token includes a client business ID. This ID represents the client business and is used by your app to make API calls.

### Get a client business ID

To get a client business ID from the business integration system user access token, send a `GET` request to the `/me` endpoint with the `fields` parameter set to `client_business_id` and the `access_token` parameter to your app user&#039;s business integration system user access token.

```html
curl -i -X GET \
&quot;https://graph.facebook.com/&lt;API_VERSION&gt;/me \
  ?fields=client_business_id
  &amp;access_token=&lt;BUSINESS_INTEGRATION_SYSTEM_USER_ACCESS_TOKEN&gt;”
```

On success your app receives a JSON response with your app user&#039;s client business ID.

```json
&#123;
  &quot;client_business_id&quot;: &quot;&lt;CLIENT_BUSINESS_ID&gt;&quot;,
  &quot;id&quot;: &quot;&lt;APP_SCOPED_ID&gt;&quot;
&#125;
```

### Get tokens

The `/&lt;CLIENT_BUSINESS_ID&gt;/system_user_access_tokens` endpoint allows you to manage your existing business integration system user access tokens. Actions include:

* Generate granular business integration system user access tokens from the existing business integration system user access tokens
* Fetch any existing business integration system user access tokens

##### Parameters

| Object | Description |
| --- | --- |
| `access_token` _string_ | **Required.** This access token requires the `business_management` permission |
| `appsecret_proof` _string_ | **Required.**&lt;br&gt;The [`appsecret_proof`](https://developers.facebook.com/docs/graph-api/guides/secure-requests#generate-the-proof) is a `sha256` hash of your access token ensuring API calls are from a server are more secure.&lt;br&gt; |
| `asset` _int_ | Optional.&lt;br&gt;When you want to generate a more granular token, you can set a list of  `asset` IDs, separated by commas. The list of assets will have to be a subset of assets from the original access token. |
| `fetch_only` _bool_ | Optional.&lt;br&gt;The flag you want to use to fetch the existing token and indicate this operation is read only |
| `scope` _bool_ | Optional.&lt;br&gt;When you want to generate a more granular token, you can set a list of `scope` ids, separated by a comma. The list of assets will have to be a subset of scopes from the original access token. |
| `set_token_expires_in_60_days` _bool_ | Optional.&lt;br&gt;When you generate a new token, set to `true` so that the token expires in 60 days. |
| `system_user_id` _int_ | Optional. The ID for the system user included in the access token. |

##### Sample request

_Formatted for readability._

```
curl -i -X POST &quot;https://graph.facebook.com/v25.0/&lt;CLIENT_BUSINESS_ID&gt;/system_user_access_tokens
    ?appsecret_proof=&lt;APPSECRET_PROOF_HASH&gt;
    &amp;access_token=&lt;ACCESS_TOKEN&gt;
    &amp;system_user_id=&lt;SYSTEM_USER_ID&gt;
    &amp;fetch_only=true&quot;
```

On success your app receives a JSON response with a new access token to be used in subsequent API calls.

```
&#123;
  &quot;access_token&quot;: &quot;&lt;NEW_ACCESS_TOKEN&gt;&quot;
&#125;
```

## Login flow experience

| User access token login flow | Business integration system user access token login flow |
| --- | --- |
|  |  |

## Get started

The following are the steps required to set up Facebook Login for Business if you don&#039;t already have an app.

### Create an app &#123;#create-a-configuration&#125;

- In Meta&#039;s App Dashboard, create a [**Business type app**.](https://developers.facebook.com/docs/development/create-an-app/app-dashboard/app-types#business)

- Add the **Facebook Login for Business** product.

- In the left side menu select **Configurations**.

- You can either **+ Create configuration** to create a configuration or **Create from template** to select one of Meta&#039;s preset configurations.

You can create multiple configurations and present them to different sets of users.

- Name your configuration

- Choose the type of access token you want to request from your business clients, a User access token or System-user access token and token expiration.

If you select  User access token then your app users will log in using their personal Facebook account. If you select System-user access token your app users will be required to log in using a business portfolio. This is only required if this configuration needs continuous access to business assets, such as Facebook Pages, ad accounts or Instagram accounts.

- Select all the assets your app needs access to.

- Select the permissions your app needs and click **Create**.

You will receive a **Configuration ID** that you will use in your code to invoke the login dialog.

#### Create a WhatsApp Business Platform Embedded Signup configuration

To create a WhatApp Embedded Signup configuration, visit our [WhatsApp Embedded Signup guide.](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview)

#### Create a Conversions API for Business Messaging configuration

To create a Conversions API for Business Messaging configuration, visit our [Marketing API – Conversions API for Business Messaging guide](https://developers.facebook.com/documentation/ads-commerce/conversions-api/business-messaging).

#### Create an Instagram Graph API configuration

To create  an Instagram Graph API configuration, visit our [Instagram Graph API documentation](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login).

### Invoke a login dialog

Invoke a login dialog using one of our SDKs (recommended) or manually build your login flow.

#### Invoking with our SDKS

You can use any of our SDKs to invoke the login dialog by replacing the list of scopes (permissions) your app needs with your configuration ID and the access token&#039;s required OAuth grant type.

If you are unfamiliar with our SDKs, we recommend that you first install the JavaScript SDK and get it working with the consumer Facebook Login product before proceeding, as the following examples reference the SDK.

##### Business integration system user access token configurations

Here&#039;s an example of the JavaScript SDK&#039;s `FB.login()` method modified to use a configuration for a System User access token. Note that `config_id` has replaced `scope` (which should not be used), the `response_type` has been set to `code`, since SUAT&#039;s require the authorization code grant type, and `override_default_response_type` must be set to `true`.  When true, any response types passed in the `response_type` will take precedence over the default types.

```js
FB.login(
  function(response) [
    console.log(response);
  ],
  [
    config_id: &#039;&lt;CONFIG_ID&gt;&#039;,
    response_type: &#039;code&#039;,
    override_default_response_type: true
  ]
);
```

When the user completes the login dialog flow we will redirect the user to your redirect URL and include a code. You must then exchange this code for an access token by performing a server-to-server call to our servers.

```http
GET https://graph.facebook.com/v25.0/oauth/access_token?
  client_id=&lt;APP_ID&gt;
  &amp;client_secret=&lt;APP_SECRET&gt;
  &amp;code=&lt;CODE&gt;
```

See [Exchanging Code for an Access Token](https://developers.facebook.com/documentation/facebook-login/guides/advanced/manual-flow#exchangecode) for more information about this step.

##### User access token configurations

Here&#039;s an example of the JavaScript SDK&#039;s `FB.login()` method modified to use a configuration for a User access token. Note that `config_id` has replaced `scope` (although `scope` can still be included, we recommend that you do not use it).

```js
FB.login(
  function(response) &#123;
    console.log(response);
  &#125;,
  &#123;
    config_id: &#039;&lt;CONFIG_ID&gt;&#039; // configuration ID goes here
  &#125;
);
```

Here&#039;s an example of the JavaScript SDK&#039;s **login** button modified to use a User access token configuration:

```html
&lt;fb:login-button config_id=&quot;&lt;CONFIG_ID&gt;&quot; onlogin=&quot;checkLoginState();&quot;&gt;
&lt;/fb:login-button&gt;
```

#### Build a manual login flow

See [Manually Building the Login Flow](https://developers.facebook.com/documentation/facebook-login/guides/advanced/manual-flow) to learn how to invoke the login dialog manually. When [invoking the login dialog and setting the redirect URL](https://developers.facebook.com/documentation/facebook-login/guides/advanced/manual-flow#logindialog), include your configuration ID as an optional parameter (although scope can still be included, we recommend that you do not use it).

```js
config_id=&lt;CONFIG_ID&gt;
```

## Switch to Facebook Login for Business

**Warning:** It is recommended you conduct [testing](https://developers.facebook.com/documentation/facebook-login/facebook-login-for-business#getting-started) and learn about potentially encountered problems[](https://developers.facebook.com/documentation/facebook-login/facebook-login-for-business#troubleshooting) before switching to Facebook Login for Business.

Facebook Login for Business is available to [**Business type apps**](https://developers.facebook.com/docs/development/create-an-app/app-dashboard/app-types#business).

If your app is eligible to switch to Facebook Login for Business, you should be able to see an opt in banner by the following steps:

- Select your app in the App Dashboard

- Go to or add the Facebook Login product

- Click either **Settings** or **Quickstart** in the left side menu

- Click the “Get started with Facebook Login for Business” button at the top of the page.

Note that your current access tokens will not be impacted upon switching to Facebook Login for Business. Additionally, any test app(s) associated with this app will also switch to Facebook Login for Business.

After switching, your app type will be under **Business type**. If your app is not functioning as intended, each app is allowed to roll back to Facebook Login within **30 days** after the switch.

## Troubleshooting

Business clients might encounter error messages for the following reasons:

* Config ID is invalid
* Business System User Access Token is not currently supported on Mobile devices
* Business System User Access Token is set up with incorrect response_type

Potential breaking changes:

* If your app type is currently **None**, switching to Facebook Login for Business will change your app’s type to **Business** and will only retain access to the [permissions](#supported-permissions), [features](#supported-features) and [products](#supported-products) listed above.
* If you request permissions or features from business clients that Facebook Login for Business doesn’t support, those permissions and features will be **revoked immediately** once you switch your app to Facebook Login for Business.  
* If you only request `email` and/or `public_profile` from your business clients, switching the app to Facebook Login for Business will lead to the invalidation of all previously installed tokens for these clients.
* If your app has both Facebook Login for Business and Meta Business Extension, the Meta Business Extension experience will be limited to permissions supported by Facebook Login for Business.
* Business Asset User Profile Access may affect how user profile data is accessed and managed through our APIs.
* Note that if the login dialog for Facebook Login for Business is invoked via configuration id, and if you decide to rollback to Facebook Login, the login dialog might fail to load as Facebook Login does not support the `config_id` parameter and you need to replace the `config_id` parameter with the `scope` parameter instead.

Learn more about [Meta Business Extension.](https://developers.facebook.com/docs/facebook-business-extension/fbe/get-started/business-login)

## Switch back to Facebook Login

**Warning:** Only available when an existing app has switched to Facebook Login for Business; Newly created Business Type apps cannot switch back to Facebook Login.

After switching to Facebook Login for Business, if your app is not functioning as intended after switching to Facebook Login for Business,  you can roll back to Facebook Login by going to the **App Dashboard** &gt; **Facebook Login for Business** &gt; **Settings** and clicking the **Switch to Facebook Login** link. You will be presented with a survey which helps us improve the Facebook Login for Business configuration experience. Each app is allowed to roll back to Facebook Login within **30 days** after the switch.

## FAQs

**Facebook Login for Business isn’t available for my app - what should I do?**

The easiest way to add Facebook Login for Business is to create a new Business Type app, where Facebook Login for Business is automatically available, and request supported business permissions through Meta App Review. If you want to use it for an existing None type app, your app must have advanced access to at least one supported business permission.

**What should I use for authentication if my app is not intended for businesses or if I am not a Tech Provider building an app for other businesses to use?**

If you are not a Tech Provider building solutions using Meta’s business APIs, Facebook Login is recommended for consumer authentication.

**What permissions do I need to request when implementing Facebook Login for Business?**

Only request the minimum permissions necessary for your app&#039;s functionality. Be transparent with users about why you need each permissions and features. Note that the `email` and `public_profile` permissions must be requested with at least one other supported [business permission](#supported-permissions).

**Is advanced access to the public_profile permission required before a Facebook Login for Business app goes live?**

Yes, advanced access to the `public_profile` permission is required for Facebook Login for Business apps before they go live. This requirement is crucial to ensure that the app can support authorization from users who do not have an app role, commonly referred to as external users.


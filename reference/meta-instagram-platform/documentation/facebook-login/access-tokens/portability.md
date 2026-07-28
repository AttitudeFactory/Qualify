# Access Token Portability



This guide explains some common scenarios of portability so you can build your app with the configuration to fit your needs.

## Token Usage with Different App Types &#123;#architecture&#125;

Access tokens are portable. Once you obtain a token, you can use it from any machine. When you combine web interfaces, mobile clients, and servers, you can get a mix of different possible configurations. However, these different configurations come with different advantages and disadvantages in terms of capabilities and security.

| Configuration | Advantages | Disadvantages | Security Notes |
| --- | --- | --- | --- |
| Login and API requests happen in a web client (short term token). | Simple implementation. | No offline posting.&lt;br&gt;&lt;br&gt;No long term access.&lt;br&gt;&lt;br&gt;Authenticate often.&lt;br&gt; |  |
| Login and API requests happen in a native mobile or web client (long term token). | Authenticate less often. | No offline posting. |  |
| Login and API requests happen in a web client (long term token after code exchange). | Extra security in certain situations. | Difficult to implement.&lt;br&gt;&lt;br&gt;No offline posting.&lt;br&gt; | Only useful in specific situations. |
| Login happens in a native mobile or web client.&lt;br&gt;&lt;br&gt;API requests happen on a Server (with long term token).&lt;br&gt; | Offline posting.&lt;br&gt;&lt;br&gt;Add security features available with server based calls.&lt;br&gt; | Client must call the server to proxy any calls. | Use [`appsecret_proof`](https://developers.facebook.com/documentation/facebook-login/security) for any calls.&lt;br&gt; |
| Login happens in a native mobile or web client.&lt;br&gt;&lt;br&gt;API requests happen on a server or in the client.&lt;br&gt; | Offline posting&lt;br&gt;&lt;br&gt;User-driven posting from client&lt;br&gt; | Difficult to implement | Use [`appsecret_proof`](https://developers.facebook.com/documentation/facebook-login/security) for any calls made from the server.&lt;br&gt; |

## Native or Web Client Login and API requests &#123;#authNative&#125;

This is the simplest configuration where authentication and API requests happen on the client. There are three possible configurations in this model:

1. Native or web client authenticates and uses the returned short or long-term token to make calls.
2. Web client authenticates and exchanges the short-term token for a long-term token via a server. This token is sent back to the web client where the web client uses it to make API calls.
3. Web client authenticates and exchanges the short-term token for a long-term token via a server. The server sends a code to the client. The client exchanges the code for a long-term token and uses it to make API calls. This configuration is rarely used.

### Native or Web Client Flow

### Web Client Flow with Long Term Token

### Web Client Flow with Code Exchange

## Client Login and Server API Calls &#123;#authClientServer&#125;

In this common configuration, authentication happens on the client, but all API calls are made by the server on behalf of the client.  The server can use the [`appsecret_proof`](https://developers.facebook.com/documentation/facebook-login/security) parameter to further enhance security when making calls.

## Client Login and Client or Server API Calls &#123;#authHybrid&#125;

This configuration is a combination of the above approaches.

## Set Access Tokens Using the SDK &#123;#changingtokens&#125;

There are different ways to specify which access token to use with an API call in our SDKs.

- The Facebook Android SDK [`setCurrentAccessToken` method](https://developers.facebook.com/docs/reference/android/current/class/AccessToken#setCurrentAccessToken) has the `accessToken` parameter.

- The Facebook iOS SDK [`setCurrentAccessToken` method](https://developers.facebook.com/docs/reference/ios/current/class/FBSDKAccessToken) has the `token` parameter.

- The Facebook Javascript SDK [`FB.api()` method](https://developers.facebook.com/docs/reference/javascript/FB.api) has the `access_token` parameter.


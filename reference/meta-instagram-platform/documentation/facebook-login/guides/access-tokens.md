# Access Tokens for Meta Technologies



An access token is an opaque string that identifies a user, app, or Facebook Page and can be used by the app to make Graph API calls. The token includes information about when it expires and which app generated it. Most API calls on Meta apps require an access token for privacy checks. Different types of access tokens support different use cases.

| Access Token Type | Description |
| --- | --- |
| App Access Token | App access tokens let you read and modify app settings. Generate one using your Meta app secret via a server-to-server call. |
| Client Token | Client tokens identify your app when calling app-level APIs from native or desktop apps. Because client tokens are embedded in apps, they are not secret. Find your client token in the Meta App Dashboard. |
| Page Access Token | Page access tokens let you read, write, and modify data belonging to a Facebook Page. To obtain one, first get a user access token, then exchange it for a Page access token via the Graph API. |
| System User Access Token | System User access tokens let your app perform programmatic, automated actions on Ad objects or Pages without requiring input from an app user or re-authentication. |
| User Access Token | User access tokens let your app take actions in real time based on input from the user. You need a User access token any time your app reads, modifies, or writes a person&#039;s Facebook data on their behalf. Obtain one via a login dialog that requires the person to grant your app permission. |

## User Access Tokens &#123;#usertokens&#125;

User access tokens let your app take actions in real time based on input from the user. You need a User access token any time your app reads, modifies, or writes a person&#039;s Facebook data on their behalf. Obtain one via a login dialog that requires the person to grant your app permission.


Different platforms have different methods to kick off this process and include functionality to manage access tokens on behalf of the developer and the person granting permissions:

### Android

The Facebook SDKs for Android automatically manages user access tokens through the class [`com.facebook.AccessToken`](https://developers.facebook.com/docs/reference/android/current/class/AccessToken). You can learn more about obtaining a user access token by implementing [Facebook Login for Android](https://developers.facebook.com/documentation/facebook-login/android). You can retrieve the user access token by inspecting [`Session.getCurrentAccessToken`](https://developers.facebook.com/docs/reference/android/current/class/AccessToken#getCurrentAccessToken).

#### Sample Code

```
&#064;Override
public void onCreate(Bundle savedInstanceState) &#123;
    super.onCreate(savedInstanceState);
    accessToken = AccessToken.getCurrentAccessToken();
&#125;
```

### iOS

The Facebook SDKs for iOS automatically manages user access tokens through the class [`FBSDKAccessToken`](https://developers.facebook.com/docs/reference/ios/current/class/FBSDKAccessToken). You can learn more about obtaining a user access token by implementing [Facebook Login for iOS](https://developers.facebook.com/documentation/facebook-login/ios). You can retrieve the access token by inspecting [`FBSDKAccessToken.currentAccessToken`](https://developers.facebook.com/docs/reference/ios/current/class/FBSDKAccessToken#currentAccessToken).

#### Sample Code

```
- (void)viewDidLoad
&#123;
  [super viewDidLoad];
  NSString *accessToken = [FBSDKAccessToken currentAccessToken];
&#125;
```

### Javascript

The [Facebook SDK for Javascript](https://developers.facebook.com/docs/javascript) obtains and persists user access tokens automatically in browser cookies. You can retrieve the user access token by making a call to [`FB.getAuthResponse`](https://developers.facebook.com/docs/reference/javascript/FB.getAuthResponse) which will include an `accessToken` property within the response.

#### Sample Code

```
FB.getLoginStatus(function(response) &#123;
  if (response.status === &#039;connected&#039;) &#123;
    var accessToken = response.authResponse.accessToken;
  &#125;
&#125; );
```

Please visit the [Facebook Web SDKs documentation](https://developers.facebook.com/docs/web) for a [complete code sample](https://developers.facebook.com/docs/reference/php/examples#get-a-user-access-token).

#### Web (without JavaScript)

When building a web app [without Facebook&#039;s SDK for Javascript](https://developers.facebook.com/documentation/facebook-login/guides/advanced/manual-flow) you will need to generate an access token during the steps outlined in that document.

## App Access Tokens &#123;#apptokens&#125;

App access tokens let you read and modify app settings. Generate one using your Meta app secret via a server-to-server call.

### Limitations

App access tokens don&#039;t expose all user data that a user access token would. To read user data in your app, use a user access token instead.

App access tokens are insecure if your app is set to `Native/Desktop` in the Advanced settings of your [App Dashboard](https://developers.facebook.com/apps). Native or desktop apps typically embed the app secret in the code, making the generated app access token insecure.

### Generating an app access token

To generate an app access token, you need:

* Your [App ID](https://developers.facebook.com/docs/apps#app-id)
* Your [App Secret](https://developers.facebook.com/documentation/facebook-login/security#appsecret)

#### Code sample

```curl
curl -X GET &quot;https://graph.facebook.com/oauth/access_token
  ?client_id=&#123;your-app-id&#125;
  &amp;client_secret=&#123;your-app-secret&#125;
  &amp;grant_type=client_credentials&quot;
```

This call returns an app access token that you can use in place of a user access token for API calls. Never hard-code app access tokens into client-side code or app binaries — doing so exposes your app secret and gives anyone who loads your webpage or decompiles your app full access to modify it. Only use app access tokens in server-to-server calls.

**Important**: This request uses your app secret, so it must only be made using server-side code. Never share your app secret with anyone.

There is another method to make calls to the Graph API that doesn&#039;t require using a generated app access token. You can just pass your app ID and app secret as the `access_token` parameter when you make a call:

```curl
curl -i -X GET &quot;https://graph.facebook.com/&#123;api-endpoint&#125;&amp;access_token=&#123;your-app_id&#125;|&#123;your-app_secret&#125;&quot;
```

The choice to use a generated access token or this method depends on where you hide your app secret.


## Page Access Tokens &#123;#pagetokens&#125;

Page access tokens let you read, write, and modify data belonging to a Facebook Page. To obtain one, first get a user access token, then exchange it for a Page access token via the Graph API.

#### Code sample

```
curl -i -X GET &quot;https://graph.facebook.com/&#123;your-user-id&#125;/accounts?access_token=&#123;user-access-token&#125;&quot;
```

This returns a list of Pages you have a role on, including the Page category, your permissions on each Page, and the Page access token.

```
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;access_token&quot;: &quot;EAACEdE...&quot;,
      &quot;category&quot;: &quot;Brand&quot;,
      &quot;category_list&quot;: [
        &#123;
          &quot;id&quot;: &quot;1605186416478696&quot;,
          &quot;name&quot;: &quot;Brand&quot;
        &#125;
      ],
      &quot;name&quot;: &quot;Ash Cat Page&quot;,
      &quot;id&quot;: &quot;1353269864728879&quot;,
      &quot;tasks&quot;: [
        &quot;ANALYZE&quot;,
        &quot;ADVERTISE&quot;,
        &quot;MODERATE&quot;,
        &quot;CREATE_CONTENT&quot;,
        &quot;MANAGE&quot;
      ]
    &#125;,
    &#123;
      &quot;access_token&quot;: &quot;EAACEdE...&quot;,
      &quot;category&quot;: &quot;Pet Groomer&quot;,
      &quot;category_list&quot;: [
        &#123;
          &quot;id&quot;: &quot;163003840417682&quot;,
          &quot;name&quot;: &quot;Pet Groomer&quot;
        &#125;,
        &#123;
          &quot;id&quot;: &quot;2632&quot;,
          &quot;name&quot;: &quot;Pet&quot;
        &#125;
      ],
      &quot;name&quot;: &quot;Unofficial: Tigger the Cat&quot;,
      &quot;id&quot;: &quot;1755847768034402&quot;,
      &quot;tasks&quot;: [
        &quot;ANALYZE&quot;,
        &quot;ADVERTISE&quot;,
        &quot;MODERATE&quot;,
        &quot;CREATE_CONTENT&quot;
      ]
    &#125;
  ]
&#125;
```

With a Page access token, you can make [API calls on behalf of a Page](https://developers.facebook.com/docs/pages), such as posting a status update to a Page or reading Page Insights data.

Page access tokens are unique to each Page, admin, and app combination.


## System User Access Tokens &#123;#systemusertokens&#125;

System User access tokens let your app perform programmatic, automated actions on Ad objects or Pages without requiring input from an app user or re-authentication.

System tokens rely on system users. When you use a system token, endpoints check whether the identified user has access to the requested resource. If the user lacks access, the request is rejected.

System users can be admins or employees:

- **Admin system users** have full access to all assets owned by or shared with your business portfolio by default. Admin system users are useful if your app needs access to all of the business portfolio&#039;s assets, without having to manually grant business asset access to each asset whenever it is created or shared with your business portfolio.
- **Employee system users** must be granted access to individual assets that are owned by, or shared with, your business portfolio. If your app will only need access to a few assets that you own, an employee system user should be sufficient.

### Generate a system user access token

To generate a system token:

1. Access the [**Business settings**](https://business.facebook.com/settings/) panel and click **System Users**.
2. Click the **+Add** button. In the **Create system user** window, enter a system user name and assign it an **Admin** or **Employee** role.
3. Click the system user&#039;s name to display the asset assignment overlay.
4. Click the **Assign assets** button, select your app, and grant your system user the **Manage app** permission.
5. Reload the page to confirm your system user has been granted **Full control** of your app.
6. Click the **Generate token** button. In the window that appears, select your app, choose a token expiration preference, and assign the required permissions for your use case.
7. Click **Generate token** and copy the token when it appears.


## Client Access Tokens &#123;#clienttokens&#125;

Client tokens identify your app when calling app-level APIs from native or desktop apps. Because client tokens are embedded in apps, they are not secret. Find your client token in the Meta App Dashboard.

Unlike other tokens, client access tokens cannot be used in requests on their own. You must combine them with your App ID by appending the token to the end of the App ID, separated by a pipe symbol (`|`):

`&#123;app-id&#125;|&#123;client-token&#125;`

For example:

`access_token=1234|5678`

To get your app&#039;s client access token:

1. Sign into your [developer account](https://developers.facebook.com/).
2. On the [Apps page](https://developers.facebook.com/apps), select an app to open the dashboard for that app.
3. On the **Dashboard**, navigate to **Settings** &gt; **Advanced** &gt; **Security** &gt; **Client token**.


## Short-lived and long-lived tokens &#123;#termtokens&#125;

Access tokens come in two forms: short-lived and long-lived. Short-lived tokens typically last about one to two hours, while long-lived tokens last about 60 days. Do not depend on these lifetimes remaining the same — they may change without warning or expire early. See [handling errors](https://developers.facebook.com/docs/facebook-login/access-tokens/debugging-and-error-handling) for more information.

Access tokens generated via web login are short-lived, but you can [convert them to long-lived tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens/get-long-lived) by making a server-side API call with your app secret.

Mobile apps that use Facebook&#039;s iOS and Android SDKs get long-lived tokens by default.

Apps with [Standard access](https://developers.facebook.com/documentation/ads-commerce/marketing-api/get-started/authorization) to the Marketing API receive long-lived tokens that do not expire based on time, though they are still subject to invalidation for other reasons. This also applies to access tokens for [System Users in Business Manager](https://developers.facebook.com/docs/marketing-api/businessmanager/systemuser).


## Token portability &#123;#portabletokens&#125;

Most access tokens are portable — you can use them from a mobile client, a web browser, or your server. If you obtain a token on a client, you can send it to your server for server-to-server calls. If you obtain a token via a server call, you can send it to a client for client-side calls. However, Apple does not allow moving tokens to servers.

Always transfer tokens between your client and server securely over HTTPS to protect user accounts. Learn more about [token portability implications](https://developers.facebook.com/documentation/facebook-login/access-tokens/portability).


## Access token classes &#123;#tokenclasses&#125;

When testing an API call, you can include the `access_token` parameter set to your access token value. However, when making secure calls from your app, use the access token class provided by the platform SDK instead of passing raw token strings. This ensures tokens are managed securely and refreshed automatically.


## Access Token Length &#123;#size&#125;

The length of access tokens changes over time as Meta updates what they store and how they are encoded. Use a variable-length data type without a specific maximum size to store access tokens.


## Learn More &#123;#advanced&#125;

* Use the [Access Token Tool](https://developers.facebook.com/tools/accesstoken) to see a list of your access tokens and debugging information for each token in.

* [Expiration and Extension](https://developers.facebook.com/docs/facebook-login/access-tokens/expiration-and-extension)

* [Debugging and Error Handling](https://developers.facebook.com/docs/facebook-login/access-tokens/debugging-and-error-handling)

* [Using Tokens with different App Types](https://developers.facebook.com/documentation/facebook-login/access-tokens/portability)

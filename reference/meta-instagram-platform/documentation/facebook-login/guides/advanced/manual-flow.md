# Manually Build a Login Flow



For browser-based login for a web or desktop app without using our SDKs, such as in a webview for a native desktop app (for example Windows 8), or a login flow using entirely server-side code, you can build a Login flow for yourself by using browser redirects. This guide will take you through each step of the login flow and show you how to implement each one without using our SDKs:

+ [Checking login status](#checklogin)
+ [Logging people in](#login)
+ [Confirming identity](#confirm)
+ [Storing access tokens and login status](#token)
+ [Logging people out](#logout)
+ [Detecting When People Uninstall Apps](#deauth-callback)
+ [Responding to Requests to Delete User Data](#data-deletion)

**Warning:** To use Facebook Login in a desktop app, you&#039;ll need to be able to embed a web browser (sometimes called a webview) within the app to perform the login process.

## Checking Login Status &#123;#checklogin&#125;

Apps using our SDKs can check whether someone has already logged in using built-in functions. All other apps must [create their own way of storing when a person has logged in](#token), and when that indicator is not there, proceed on the assumption that they are logged out. If someone is logged out, then your app should redirect them to the Login dialog at an appropriate time — for example if they click a login button.

## Logging People In &#123;#login&#125;

Whether someone is not logged into your app or not logged into Facebook, you can use [the Login dialog](https://developers.facebook.com/documentation/facebook-login/overview#logindialog) to prompt them to do both. If they aren&#039;t logged into Facebook, they&#039;ll be prompted to login and then move onto logging into your app. This is automatically detected, so you don&#039;t need to do anything extra to enable this behavior.

#### Invoking the Login Dialog and Setting the Redirect URL &#123;#logindialog&#125;

Your app must initiate a redirect to an endpoint which will display the login dialog:

```
https://www.facebook.com/v25.0/dialog/oauth?client_id=&#123;app-id&#125;
&amp;redirect_uri=&#123;redirect-uri&#125;
&amp;state=&#123;state-param&#125;
```

This endpoint has the following required parameters:

+ `client_id`. The ID of your app, found in your app&#039;s dashboard.
+ `redirect_uri`. The URL that you want to redirect the person logging in back to. This URL will capture the response from the Login Dialog. If you are using this in a webview within a desktop app, this must be set to `https://www.facebook.com/connect/login_success.html`.
You can confirm that this URL is set for your app in the App Dashboard. Under **Products** in the App Dashboard&#039;s left side navigation menu, click **Facebook Login**, then click **Settings**. Verify the **Valid OAuth redirect URIs** in the **Client OAuth Settings** section.
+ `state`. A string value created by your app to maintain
state between the request and callback. This parameter should be used for preventing [Cross-site Request Forgery](http://en.wikipedia.org/wiki/Cross-site_request_forgery) and will be passed back to you, unchanged, in your redirect URI.

For example, if your login request looks like:

```
https://www.facebook.com/v25.0/dialog/oauth?client_id=&#123;app-id&#125;
&amp;redirect_uri=&#123;&quot;https://www.domain.com/login&quot;&#125;
&amp;state=&#123;&quot;&#123;st=state123abc,ds=123456789&#125;&quot;&#125;
```

then your redirect URI would be called with this:

```
https://www.domain.com/login?state=&quot;&#123;st=state123abc,ds=123456789&#125;&quot;
```

It also has the following optional parameters:

+ `response_type`. Determines whether the response data included when the redirect back to the app occurs is in URL parameters or fragments. See the [Confirming Identity](#confirm) section to choose which type your app should use. This can be one of:
+ `code`. Response data is included as URL parameters and contains `code` parameter (an encrypted string unique to each login request). This is the default behavior if this parameter is not specified.  It&#039;s most useful when your server will be handling the token.
+ `token`. Response data is included as a URL fragment and contains an access token. Desktop apps must use this setting for `response_type`.  This is most useful when the client will be handling the token.
+ `code%20token`. Response data is included as a URL fragment and contains both an access token and the `code` parameter.
+ `granted_scopes`. Returns a comma-separated list of all [Permissions](https://developers.facebook.com/docs/facebook-login/permissions) granted to the app by the user at the time of login. Can be combined with other `response_type` values. When combined with `token`, response data is included as a URL fragment, otherwise included as a URL parameter.
+ `scope`. A comma or space separated list of [Permissions](https://developers.facebook.com/docs/facebook-login/permissions) to request from the person using your app.

##### For Windows 8 Apps &#123;#windows8&#125;

If you are building Login for a Windows app you can use the  [Package Security Identifier](http://msdn.microsoft.com/en-us/library/windows/apps/hh465407.aspx) as your `redirect_uri`. Trigger the Login Dialog by calling [`WebAuthenticationBroker.AuthenticateAsync`](http://msdn.microsoft.com/en-us/library/windows/apps/br212068.aspx) and use the Login Dialog endpoint as the requestUri. Here is an example in JavaScript:

```
var requestUri = new Windows.Foundation.Uri(
  &quot;https://www.facebook.com/v25.0/dialog/oauth?    client_id=&#123;app-id&#125;
    &amp;display=popup
    &amp;response_type=token
    &amp;redirect_uri=ms-app://&#123;package-security-identifier&#125;&quot;);

Windows.Security.Authentication.Web.WebAuthenticationBroker.authenticateAsync(
  options,
  requestUri)
  .done(function (result) &#123;
    // Handle the response from the Login Dialog
  &#125;
);
```

This will return control flow back to your app with an access token on success, or error on failure.

We recommend using the default browser for Windows 8 apps.

#### Handling Login Dialog Response &#123;#dialogresponse&#125;

At this point in the login flow, the person will see the Login dialog and will have a choice of whether to cancel or to let the app access their data.

If the person using the app chooses OK on the Login dialog, they grant access to their public profile, friend list and any additional [Permissions](https://developers.facebook.com/docs/facebook-login/permissions) your app requested.

In all cases, the browser returns to the app, and response data indicating whether someone connected or cancelled is included. When your app uses the redirect method as above, the `redirect_uri` your app returns to will be appended with URL parameters or fragments (as per the chosen `response_type`), which must be captured.  

Because of the various combinations of code languages that could be used in web apps, our guide doesn&#039;t show specific examples. However most modern languages will be capable of URL parsing, as follows:

Client-side JavaScript can capture URL fragments (for example [jQuery BBQ](https://github.com/cowboy/jquery-bbq/)), whereas URL parameters can be captured by both client-side and server-side code (for example [`$_GET` in PHP](http://php.net/manual/en/reserved.variables.get.php), [`jQuery.deparam` in jQuery BBQ](https://github.com/cowboy/jquery-bbq/), [`querystring.parse` in Node.js](http://nodejs.org/api/querystring.html) or [`urlparse` in Python](http://docs.python.org/2/library/urlparse.html)). Microsoft provides [a guide and sample code for Windows 8 apps](http://msdn.microsoft.com/en-us/library/windows/apps/jj856915.aspx) connecting to an &quot;online provider&quot; - in this case, Facebook.

**Warning:** When using a desktop app and logging in, Facebook redirects people to the `redirect_uri` mentioned above and places an access token along with some other metadata (such as token expiry time) in the URI fragment:

```
https://www.facebook.com/connect/login_success.html#
    access_token=ACCESS_TOKEN...
```

Your app needs to detect this redirect and then read the access token out of the URI using the mechanisms provided by the OS and development framework you are using. You can then skip straight to the [Inspecting access tokens](#checktoken) step.

#### Canceled Login &#123;#nonjscancel&#125;

If people using your app don&#039;t accept the Login dialog and clicks Cancel, they&#039;ll be redirected to the following:

```
YOUR_REDIRECT_URI?
 error_reason=user_denied
 &amp;error=access_denied
 &amp;error_description=Permissions+error.
```

See [Handling Missing Permissions](https://developers.facebook.com/docs/facebook-login/permissions#missingperms) for more about what apps should do when people refuse to login.

## Confirming Identity &#123;#confirm&#125;

Because this redirect flow involves browsers being redirected to URLs in your app from the Login dialog, traffic could directly access this URL with made-up fragments or parameters. If your app assumed these were valid parameters, the made-up data would be used by your app for potentially malicious purposes. As a result, your app should confirm that the person using the app is the same person that you have response data for before generating an access token for them. Confirming identity is accomplished in different ways depending on the `response_type` received above:

+ When `code` is received, it has to be [exchanged for an access token using an endpoint](#exchangecode).  The call will need to be server-to-server, since it involves your app secret.  (Your app secret should never end up in client code.)
+ When `token` is received, it needs to be verified.  You should [make an API call to an inspection endpoint](#checktoken) that will indicate who the token was generated for and by which app.  As this API call requires using an app access token, never make this call from a client. Instead make this call from a server where you can securely store your app secret.
+ When `code` and `token` are both received, both steps should be performed.

Note that you can also generate your own [`state` parameter](#logindialog) and use it with your login request to provide CSRF protection.

#### Exchanging Code for an Access Token &#123;#exchangecode&#125;

To get an access token, make an HTTP GET request to the following OAuth endpoint:

```
GET https://graph.facebook.com/v25.0/oauth/access_token?client_id=&#123;app-id&#125;
&amp;redirect_uri=&#123;redirect-uri&#125;
&amp;client_secret=&#123;app-secret&#125;
&amp;code=&#123;code-parameter&#125;
```

This endpoint has some required parameters:

+ `client_id`. Your app&#039;s IDs
+ `redirect_uri`. This argument is required and must be the same as the original `request_uri` that you used when starting the OAuth login process.
+ `client_secret`. Your unique app secret, shown on the [App Dashboard](https://developers.facebook.com/apps). Never include this app secret in client-side code or in binaries that could be decompiled. It is extremely important that it remains completely secret as it is the core of the security of your app and all the people using it.
+ `code`. The parameter received from the Login Dialog redirect above.

**Response**  

The response you will receive from this endpoint will be returned in JSON format and, if successful, is:

```
&#123;
  &quot;access_token&quot;: &#123;access-token&#125;,
  &quot;token_type&quot;: &#123;type&#125;,
  &quot;expires_in&quot;:  &#123;seconds-til-expiration&#125;
&#125;
```

If it is not successful, you will receive an explanatory error message.

## Inspecting Access Tokens &#123;#checktoken&#125;

Whether or not your app uses `code` or `token` as your `response_type` from the Login dialog, it will have received an access token. You can perform automated checks on these tokens using a Graph API endpoint:

```
GET graph.facebook.com/debug_token?
     input_token=&#123;token-to-inspect&#125;
     &amp;access_token=&#123;app-token-or-admin-token&#125;
```

This endpoint takes the following parameters:

* `input_token`. The token you need to inspect.
* `access_token` An [app access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens) or an access token for a developer of the app.

The response of the API call is a JSON array containing data about the inspected token. For example:

```
&#123;
    &quot;data&quot;: &#123;
        &quot;app_id&quot;: 138483919580948,
        &quot;type&quot;: &quot;USER&quot;,
        &quot;application&quot;: &quot;Social Cafe&quot;,
        &quot;expires_at&quot;: 1352419328,
        &quot;is_valid&quot;: true,
        &quot;issued_at&quot;: 1347235328,
        &quot;metadata&quot;: &#123;
            &quot;sso&quot;: &quot;iphone-safari&quot;
        &#125;,
        &quot;scopes&quot;: [
            &quot;email&quot;,
            &quot;publish_actions&quot;
        ],
        &quot;user_id&quot;: &quot;1207059&quot;
    &#125;
&#125;
```

The `app_id` and `user_id` fields help your app verify that the access token is valid for the person and for your app. For a full description of the other fields, see the [Getting Info about Access Tokens guide](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens).

### Checking Permissions &#123;#permscheck&#125;

The [`/me/permissions` edge](https://developers.facebook.com/docs/graph-api/reference/user/permissions) can be called in order to retrieve a list of permissions that have been granted or declined by a particular user. Your app can use this to check which of the requested permissions it cannot use for any particular user.  

## Re-asking for Declined Permissions &#123;#reaskperms&#125;

Facebook Login lets people decline sharing some permissions with your app.  The Login Dialog contains a screen that looks like this:

The `public_profile` permission is always required and greyed out because it can&#039;t be disabled.

However, if someone were to uncheck `user_likes` (Likes) in this example, checking [`/me/permissions`](https://developers.facebook.com/docs/graph-api/reference/user/permissions) for which permissions have been granted results in:

```
&#123;
  &quot;data&quot;:
    [
      &#123;
        &quot;permission&quot;:&quot;public_profile&quot;,
        &quot;status&quot;:&quot;granted&quot;
      &#125;,
      &#123;
        &quot;permission&quot;:&quot;user_likes&quot;,
        &quot;status&quot;:&quot;declined&quot;
      &#125;
    ]
&#125;
```

Note that `user_likes` has been declined instead of granted.

It&#039;s OK to ask a person again to grant your app permissions that they&#039;ve declined.  You should have a screen of education on why you think they should grant the permission to you and then re-ask. But if you invoke the Login Dialog [as before](#logindialog), it won&#039;t ask for that permission.

**This is because once someone has declined a permission, the Login Dialog will not re-ask them for it unless you explicitly tell the dialog you&#039;re re-asking for a declined permission.**

You do this by adding the `auth_type=rerequest` parameter to your Login Dialog URL:

```
https://www.facebook.com/v25.0/dialog/oauth?client_id=&#123;app-id&#125;
&amp;redirect_uri=&#123;redirect-uri&#125;
&amp;auth_type=rerequest
scope=email
```

Using this, the Login Dialog will re-ask for the declined permission.

## Storing Access Tokens and Login Status &#123;#token&#125;

At this point in the flow, you have someone authenticated and logged in. Your app is ready to make API calls on their behalf. Before doing so, it should store the access token and the login status of the person using the app.

#### Storing Access Tokens

After your app receives the access token from the previous step, the token should be stored so it&#039;s available to all parts of the app when it makes API calls. There is no specific process here, however in general if you&#039;re building a web app, it is best to add the token as a session variable to identify that browser session with a particular person, if you&#039;re building a native desktop or mobile app, then you should use the datastore available to your app. Also, the app should store the token in a database along with the `user_id` to identify it.

Please see our note about the [size of access tokens in the access token document](https://developers.facebook.com/docs/facebook-login/access-tokens/debugging-and-error-handling#sizes).

#### Tracking login status

Again, your app should store a person&#039;s login status, which helps avoid having to make additional calls to the Login dialog. Whatever procedure you chose, modify your [login status checking](#checklogin) to account for it.

## Logging People Out &#123;#logout&#125;

You can log people out of your app by undoing [whatever login status indicator you added](#token), for example deleting the session that indicates a person is logged in. You should also remove the stored access token.

Logging someone out is not the same as revoking login permission (removing previously granted authentication), [which can be performed separately](https://developers.facebook.com/documentation/facebook-login/guides/permissions/request-revoke#revokelogin). Because of this, build your app so it doesn&#039;t automatically force people who have logged out back to the Login dialog.

## Detecting When People Uninstall Apps &#123;#deauth-callback&#125;

People are able to uninstall apps via Facebook.com without interacting with the app itself. To help apps detect when this has happened, we allow them to provide a de-authorize callback URL which will be pinged whenever this occurs.

You can enable a deauthorize callback through the [App Dashboard](https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback).

## Responding to Requests to Delete User Data &#123;#data-deletion&#125;

People can request an app to delete all information about them received from Facebook. For responding to these requests, see [Data Deletion Request Callback](https://developers.facebook.com/docs/apps/delete-data).

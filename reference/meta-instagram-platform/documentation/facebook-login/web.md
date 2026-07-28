# Facebook Login for the Web with the JavaScript SDK



This document walks you through the steps of implementing Facebook Login with the [Facebook SDK for JavaScript](https://developers.facebook.com/docs/javascript) on your webpage.

## Before You Start

You will need the following:

- A [Facebook Developer Account](https://developers.facebook.com/apps/)

- A [Facebook App ID](https://developers.facebook.com/docs/apps#register) for a website

## Basic Automatic Login Example

The following code sample shows you how to add the Facebook SDK for Javascript to your webpage, initialize the SDK, and, if you are logged in to Facebook, will display your name and email. If you are not logged into Facebook, the login dialog popup window will automatically be displayed.

The
[public_profile permission](https://developers.facebook.com/docs/permissions/reference/public_profile), which allows you to get publicly available information such as name and profile picture,
and the
[email permission](https://developers.facebook.com/docs/permissions/reference/email)
do not require app review and are automatically granted to all apps using Facebook Login.

```
&lt;!doctype html&gt;
&lt;html lang=&quot;en&quot;&gt;
  &lt;head&gt;&lt;/head&gt;
  &lt;body&gt;
    &lt;h2&gt;Add Facebook Login to your webpage&lt;/h2&gt;

    &lt;!-- Set the element id for the JSON response --&gt;
    &lt;p id=&quot;profile&quot;&gt;&lt;/p&gt;
    &lt;button onclick=&quot;loginWithFacebook()&quot;&gt;Log in with Facebook&lt;/button&gt;

    &lt;script&gt;
      // Initialize the Facebook JavaScript SDK, but wait till it&#039;s loaded
      window.fbAsyncInit = function () &#123;
        FB.init(&#123;
          appId: &quot;&#123;your-facebook-app-id&#125;&quot;,
          xfbml: true,
          version: &quot;&#123;the-graph-api-version-for-your-app&#125;&quot;,
        &#125;);
      &#125;;

      // Handle clicks on the &quot;Log in with Facebook&quot; button
      function loginWithFacebook() &#123;
        FB.login(function (response) &#123;
          if (response.authResponse) &#123;
            console.log(&quot;Welcome!  Fetching your information.... &quot;);
            // After successful login, we can fetch the user&#039;s information
            FB.api(&quot;/me&quot;, &#123; fields: &quot;name, email&quot; &#125;, function (response) &#123;
              document.getElementById(&quot;profile&quot;).innerHTML =
                &quot;Good to see you, &quot; +
                response.name +
                &quot;. i see your email address is &quot; +
                response.email;
            &#125;);
          &#125; else &#123;
            console.log(&quot;User cancelled login or did not fully authorize.&quot;);
          &#125;
        &#125;);
      &#125;

      // Load the JavaScript SDK asynchronously
      (function (d, s, id) &#123;
        var js,
          fjs = d.getElementsByTagName(s)[0];
        if (d.getElementById(id)) &#123;
          return;
        &#125;
        js = d.createElement(s);
        js.id = id;
        js.src = &quot;https://connect.facebook.net/en_US/sdk.js&quot;;
        fjs.parentNode.insertBefore(js, fjs);
      &#125;)(document, &quot;script&quot;, &quot;facebook-jssdk&quot;);
    &lt;/script&gt;
  &lt;/body&gt;
&lt;/html&gt;
```

## 1. Enable JavaScript SDK for Facebook Login &#123;#redirecturl&#125;

In the [App Dashboard](https://developers.facebook.com/apps), choose your app and scroll to **Add a Product** Click **Set Up** in the **Facebook Login** card. Select **Settings** in the left side navigation panel and under **Client OAuth Settings**, enter your redirect URL in the **Valid OAuth Redirect URIs** field for successful authorization.

Indicate that you are using the JavaScript SDK for login by setting the **Login with JavaScript SDK** toggle to “yes”, and enter the domain of your page that hosts the SDK in **Allowed Domains for JavaScript SDK** list. This ensures that access tokens are only returned to callbacks in authorized domains. Only https pages are supported for authentication actions with the Facebook JavaScript SDK.

## 2. Check Login Status of a Person &#123;#checklogin&#125;

The first step when your webpage loads is determining if a person is already logged into your webpage with Facebook Login. A call to [`FB.getLoginStatus`](https://developers.facebook.com/docs/reference/javascript/FB.getLoginStatus) starts a call to Facebook to get the login status. Facebook then calls your callback function with the results.

#### Sample Call

```
FB.getLoginStatus(function(response) &#123;
    statusChangeCallback(response);
&#125;);
```

#### Sample JSON Response

```
&#123;
    status: &#039;connected&#039;,
    authResponse: &#123;
        accessToken: &#039;&#123;access-token&#125;&#039;,
        expiresIn:&#039;&#123;unix-timestamp&#125;&#039;,
        reauthorize_required_in:&#039;&#123;seconds-until-token-expires&#125;&#039;,
        signedRequest:&#039;&#123;signed-parameter&#125;&#039;,
        userID:&#039;&#123;user-id&#125;&#039;
    &#125;
&#125;
```

`status` specifies the login status of the person using the webpage. The `status` can be one of the following:

| `Status` Type | Description |
| --- | --- |
| `connected` | The person is logged into Facebook, and has logged into your webpage. |
| `not_authorized` | The person is logged into Facebook, but has not logged into your webpage. |
| `unknown` | The person is not logged into Facebook, so you don&#039;t know if they have logged into your webpage. Or [FB.logout()](#logout) was called before, and therefore, it cannot connect to Facebook. |

If the status is `connected`, the following `authResponse` parameters are included in the response:

| `authResponse` Parameters | Value |
| --- | --- |
| `accessToken` | An access token for the person using the webpage. |
| `expiresIn` | A UNIX time stamp when the token expires. Once the token expires, the person will need to login again. |
| `reauthorize_required_in` | The amount of time before the login expires, in seconds, and the person will need to login again. |
| `signedRequest` | A signed parameter that contains information about the person using your webpage. |
| `userID` | The ID of the person using your webpage. |

The JavaScript SDK automatically detects login status, so you don&#039;t need to do anything to enable this behavior.

## 3. Log a Person In &#123;#login&#125;

If a person opens your webpage but is not logged in or not logged in to Facebook, you can use [the Login dialog](https://developers.facebook.com/documentation/facebook-login/overview#logindialog) to prompt them to log in to both. If they are not logged into Facebook, they will first be prompted to log in, then prompted to log in to your webpage.

There are two ways to log someone in:

* The [Facebook Login Button](#loginbutton)
* The [Login Dialog](#logindialog) from the JavaScript SDK

### A. Log In with the Login Button &#123;#loginbutton&#125;

Customize the [Login Button](https://developers.facebook.com/documentation/facebook-login/web/login-button) and add the code to your project.

### B. Log In with the Javascript SDK Login Dialog &#123;#logindialog&#125;

To use your own login button, invoke the Login Dialog with a call to [`FB.login()`](https://developers.facebook.com/docs/reference/javascript/FB.login).

```
FB.login(function(response)&#123;
  // handle the response
&#125;);
```

### Ask for Additional Permissions

When a person clicks your HTML button a pop-up window with the Login dialog is shown. This dialog allows you to [ask for permission](https://developers.facebook.com/documentation/facebook-login/web/permissions) to access a person&#039;s data. The `scope` parameter can be passed along with the `FB.login()` function call. This optional parameter is a list of [permissions](https://developers.facebook.com/docs/facebook-login/permissions), separated by commas, that a person must confirm to give your webpage access to their data. Facebook Login requires dvanced public_profile permission, to be used by external users.

#### Sample Call

This example asks the person logging in if your webpage can have permission to access their public profile and email.

```
FB.login(function(response) &#123;
  // handle the response
&#125;, &#123;scope: &#039;public_profile,email&#039;&#125;);
```

### Handle the Login Dialog Response &#123;#dialogresponse&#125;

The response, either to connect or to cancel, returns an `authResponse` object to the callback specified when you called `FB.login()`. This response can be detected and handled within the `FB.login()`.

#### Sample Call

```
FB.login(function(response) &#123;
  if (response.status === &#039;connected&#039;) &#123;
    // Logged into your webpage and Facebook.
  &#125; else &#123;
    // The person is not logged into your webpage or we are unable to tell.
  &#125;
&#125;);
```

## 4. Log a Person Out &#123;#logout&#125;

Log a person out of your webpage by attaching the JavaScript SDK function `FB.logout()` to a button or a link.

#### Sample Call

```
FB.logout(function(response) &#123;
   // Person is now logged out
&#125;);
```

**Note: This function call may also log the person out of Facebook.**

#### Scenarios to Consider

1. A person logs into Facebook, then logs into your webpage. Upon logging out from your app, the person is still logged into Facebook.
2. A person logs into your webpage and into Facebook as part of your app&#039;s login flow. Upon logging out from your app, the user is also logged out of Facebook.
3. A person logs into another webpage and into Facebook as part of the other webpage&#039;s login flow, then logs into your webpage. Upon logging out from either webpage, the person is logged out of Facebook.

Additionally, logging out of your webpage does not revoking permissions the person granted your webpage during login. [Revoking permissions](https://developers.facebook.com/docs/facebook-login/permissions#revokelogin) must be done separately. Build your webpage in such a way that a person who has logged out will not see the Login dialog when they log back in.

## Full Code Example &#123;#example&#125;

This code loads and initializes the JavaScript SDK in your HTML page. Replace `&#123;app-id&#125;` with your [app ID](https://developers.facebook.com/docs/apps) and `&#123;api-version&#125;` with the Graph API version to use. Unless you have a specific reason to use an older version, specify the most recent version: v25.0.

```
&lt;!DOCTYPE html&gt;
&lt;html&gt;
&lt;head&gt;
&lt;title&gt;Facebook Login JavaScript Example&lt;/title&gt;
&lt;meta charset=&quot;UTF-8&quot;&gt;
&lt;/head&gt;
&lt;body&gt;
&lt;script&gt;

  function statusChangeCallback(response) &#123;  // Called with the results from FB.getLoginStatus().
    console.log(&#039;statusChangeCallback&#039;);
    console.log(response);                   // The current login status of the person.
    if (response.status === &#039;connected&#039;) &#123;   // Logged into your webpage and Facebook.
      testAPI();
    &#125; else &#123;                                 // Not logged into your webpage or we are unable to tell.
      document.getElementById(&#039;status&#039;).innerHTML = &#039;Please log &#039; +
        &#039;into this webpage.&#039;;
    &#125;
  &#125;

  function checkLoginState() &#123;               // Called when a person is finished with the Login Button.
    FB.getLoginStatus(function(response) &#123;   // See the onlogin handler
      statusChangeCallback(response);
    &#125;);
  &#125;

  window.fbAsyncInit = function() &#123;
    FB.init(&#123;
      appId      : &#039;&#123;app-id&#125;&#039;,
      cookie     : true,                     // Enable cookies to allow the server to access the session.
      xfbml      : true,                     // Parse social plugins on this webpage.
      version    : &#039;&#123;api-version&#125;&#039;           // Use this Graph API version for this call.
    &#125;);

    FB.getLoginStatus(function(response) &#123;   // Called after the JS SDK has been initialized.
      statusChangeCallback(response);        // Returns the login status.
    &#125;);
  &#125;;

  function testAPI() &#123;                      // Testing Graph API after login.  See statusChangeCallback() for when this call is made.
    console.log(&#039;Welcome!  Fetching your information.... &#039;);
    FB.api(&#039;/me&#039;, function(response) &#123;
      console.log(&#039;Successful login for: &#039; + response.name);
      document.getElementById(&#039;status&#039;).innerHTML =
        &#039;Thanks for logging in, &#039; + response.name + &#039;!&#039;;
    &#125;);
  &#125;

&lt;/script&gt;

&lt;!-- The JS SDK Login Button --&gt;

&lt;fb:login-button scope=&quot;public_profile,email&quot; onlogin=&quot;checkLoginState();&quot;&gt;
&lt;/fb:login-button&gt;

&lt;div id=&quot;status&quot;&gt;
&lt;/div&gt;

&lt;!-- Load the JS SDK asynchronously --&gt;
&lt;script async defer crossorigin=&quot;anonymous&quot; src=&quot;https://connect.facebook.net/en_US/sdk.js&quot;&gt;&lt;/script&gt;
&lt;/body&gt;
&lt;/html&gt;
```

### Additional Resources &#123;#additional-resources&#125;

* [Login Button](https://developers.facebook.com/documentation/facebook-login/web/login-button) Documentation
* [`FB.login()` Reference](https://developers.facebook.com/docs/reference/javascript/FB.login)
* [`FB.getLoginStatus()` Reference](https://developers.facebook.com/docs/reference/javascript/FB.getLoginStatus)
* [JavaScript SDK Reference](https://developers.facebook.com/docs/reference/javascript)

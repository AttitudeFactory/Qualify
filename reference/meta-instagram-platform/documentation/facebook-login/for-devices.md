# Facebook Login for Devices



**Warning:** If you are looking for help for your Facebook **Portal**, please visit the [Portal Help Center](https://portal.facebook.com/help/).

To enter your Facebook for Devices **code** to log in to your smart TV, camera, printer, and other devices, visit the [Facebook for Devices Page](https://www.facebook.com/device).

Implement Facebook Login for Devices to allow people to log into your app or service with their Facebook account. This feature allows people to log into devices with limited input or display capabilities such as smart TVs, digital photo frames, or Internet of Things devices.

With device login, your device shows an alphanumeric code and tells people to enter it on a web page on their desktop PC or smartphone. People using your app or service can then grant permissions. After your application gets permissions, the device receives an access token which your app uses to make Graph API requests to identify the person and get information to personalize their experience with the device.

If you&#039;re building a TV app for Apple TV, or Android TV, or Fire TV, you should use [Facebook SDK for tvOS](https://developers.facebook.com/documentation/ios) or [Facebook SDK for Android](https://developers.facebook.com/docs/android/devices).

This guide describes the manual integration of Device Login without using the above SDKs.

+ [User experience](#design)
+ [Implement Login for Devices](#tech)
+ [Troubleshooting](#troubleshooting)

## User Experience &#123;#design&#125;

These guidelines describe how to design a clear, safe, and consistent login experience across devices and services.

### 1. Call-to-Action &#123;#design-step1&#125;

First consider where in your user experience you want to ask people to log in or connect with Facebook. For some devices this will be right away, and for others it might be later in the experience.

To ensure the most usable, consistent, and reliable user experience, design the button to look as much as possible like the official Facebook Login button.

From a visual design perspective, this means that you should

1. Label the button with “Log in with Facebook” or “Connect to Facebook”.
2. Use white and the official Facebook brand blue: #1877F2.
3. If your device supports a graphical display, you can also incorporate the official “f” logo. According to the [Facebook brand guidelines](https://www.facebookbrand.com/), the logo should always be either white or Facebook blue (#1877F2).

Where relevant, describe the benefit of logging in. For example, “find out what your friends are watching” or &quot;see photos from your Facebook Albums”.

### 2. Display the Code &#123;#design-step2&#125;

When someone clicks the call-to-action, your device makes a call to Facebook&#039;s API which returns a code.

In your interface, tell people that they need to visit a website and enter the code with the following message, “Next, visit facebook.com/device (http://facebook.com/device) on your desktop or smartphone and enter this code”.  Display the full code you received from Facebook&#039;s Device Login API. The code is between 6 and 12 characters long.

You can include a `Close` or `Cancel` button so people can cancel the device login flow. This should return them to the initial login screen.

When the code displays on screen, your device polls the Device Login API to see if someone authorized your application. After a few minutes, if they have not entered their code, the Device Login API returns a `code_expired` error. When your device receives this error you should cancel the login flow and the interface should display the call-to-action.

QR codes may also be generated with the user code embedded in the url. This is done by adding the `user_code` parameter to the url:

```html
https://www.facebook.com/device?user_code=&lt;USER_CODE&gt;
```

### 3. Authorization &#123;#design-step3&#125;

This is the flow people see when they go to [facebook.com/device](https://www.facebook.com/device) on their desktop or mobile browser. First they see a text field where they can enter their code:

After they enter their code and click `Continue` they can choose the permissions they want to grant:

So people know their login process is successful, they then see a confirmation message:

### 4. Confirm Successful Login &#123;#design-step4&#125;

On your device&#039;s interface, you should also display a confirmation message. Ideally this includes the person&#039;s name and, if possible, their Facebook profile picture.

Display this confirmation on your device until the person clicks a `Continue` button. Someone may have to enter the code into a computer at another location, so they may need time to return to your device and see the confirmation before continuing.

After the person clicks `Continue`, your device can then show a great, personalized experience.

### 5. Log out or Disconnect &#123;#design-step5&#125;

People should be able to log out from your device, and your device should not store their connection with Facebook. To do this, provide a `Log out from Facebook` or `Disconnect from Facebook` option in your device&#039;s menu.

When someone selects this option, your device should delete the stored access token from its memory. If you store the access token in a database or cloud storage, you should also remove it there. You do not need to make an API call to invalidate the access token.

After someone logs out, your device should display the initial call-to-action in [Step 1](#design-step1).

## Implement Login for Devices &#123;#tech&#125;

Facebook Login for Devices is for devices that directly make HTTP calls over the internet. The following are the API calls and responses your device can make.

### 1. Enable Login for Devices &#123;#tech-step-enable-login-for-devices&#125;

Load your [app&#039;s dashboard](https://developers.facebook.com/apps/) and change Product &gt; Facebook login &gt; Settings &gt; Login from Devices to &#039;Yes&#039;.

### 2. Generate a Code &#123;#tech-step1&#125;

When the person clicks the `Connect to Facebook` or `Log in with Facebook` call-to-action, you device should make an HTTP POST to:

```html
POST https://graph.facebook.com/&lt;API_VERSION&gt;/device/login
       access_token=&lt;YOUR_APP_ID|CLIENT_TOKEN&gt;
       scope=&lt;COMMA_SEPARATED_PERMISSION_NAMES&gt; // e.g. public_profile,user_likes
       redirect_uri=&lt;VALID_OAUTH_REDIRECT_URL&gt;
```

The `scope` parameter is optional and must contain a comma separated list of [Login Permissions](https://developers.facebook.com/docs/facebook-login/permissions) which are approved for use in [Login Review](https://developers.facebook.com/docs/facebook-login/review).

The `CLIENT_TOKEN` is found in your App Settings -&gt; Advanced, and should be combined with your app ID (separated with a pipe, `|`) to form the complete `access_token`.

The `redirect_uri` is an optional parameter. When you supply a URL, the person will be redirected to the URL after completing the login successfully. This allows you to log the person into your app&#039;s website for additional account management. This URL must be a valid OAuth redirect URL as configured in your App Settings -&gt; Advanced.
The response is in this form:

```
&#123;
  &quot;code&quot;: &quot;92a2b2e351f2b0b3503b2de251132f47&quot;,
  &quot;user_code&quot;: &quot;A1NWZ9&quot;,
  &quot;verification_uri&quot;: &quot;https://www.facebook.com/device&quot;,
  &quot;expires_in&quot;: 420,
  &quot;interval&quot;: 5
&#125;
```

This response means:

1. Display the string “**A1NWZ9**” on your device
2. Tell the person to go to “facebook.com/device” and enter this code
3. The code expires in 420 seconds. You should cancel the login flow after that time if you do not receive an access token
4. Your device should poll the Device Login API every 5 seconds to see if the authorization has been successful.

### 3. Display the Code &#123;#tech-step2&#125;

Your device should display the `user_code` and tell people to visit the `verification_uri` such as facebook.com/device on their PC or smartphone. See  [User Experience](#design).

### 4. Poll for Authorization &#123;#tech-step3&#125;

Your device should poll the Device Login API to see if the person successfully authorized your app. You should do this at the `interval` in the response to your call in [Step 2](#tech-step1), which is every 5 seconds. Your device should poll to:

```html
POST https://graph.facebook.com/&lt;API_VERSION&gt;/device/login_status
       access_token=&lt;YOUR_APP_ID|CLIENT_TOKEN&gt;
       code=&lt;LONG_CODE_FROM_STEP_1&gt; // e.g. &quot;92a2b2e351f2b0b3503b2de251132f47&quot;
```

The response to this API call depends on where someone is in the authorization flow. You will either receive the access token or an error object with a specific subcode to parse:

| Error subcode | Example Response | Meaning |
| --- | --- | --- |
| `N/A` | `&#123;&quot;access_token&quot;: &quot;ABCD...&quot;, &quot;expires_in&quot; : 5183996 &#125;` | User has successfully authorized the device. The device can now use the `access_token` value to make authorized API calls. |
| `1349174` | `&#123;&quot;error&quot;:&#123;&quot;message&quot;:&quot;This request requires the user to take a pending action&quot;,&quot;code&quot;:31,&quot;error_subcode&quot;:1349174,&quot;error_user_title&quot;:&quot;Device Login Authorization Pending&quot;,&quot;error_user_msg&quot;:&quot;User has not yet authorized your application. Continue polling.&quot;&#125;&#125;` | User has not yet authorized your application. Continue polling at the rate specified in the response in [Step 1](#tech-step1). |
| `1349172` | `&#123;&quot;error&quot;:&#123;&quot;message&quot;:&quot;User request limit reached&quot;,&quot;code&quot;:17,&quot;error_subcode&quot;:1349172,&quot;error_user_title&quot;:&quot;OAuth Device Excessive Polling&quot;,&quot;error_user_msg&quot;:&quot;Your device is polling too frequently. Space your requests with a minium interval of 5 seconds.&quot;&#125;&#125;` | Your device is polling too frequently. Slow down the polling to the interval specified in the first API call. |
| `1349152` | `&#123;&quot;error&quot;:&#123;&quot;message&quot;:&quot;The session has expired&quot;&quot;code&quot;:463,&quot;error_subcode&quot;:1349152, &quot;error_user_title&quot;:&quot;Activation Code Expired&quot;,&quot;error_user_msg&quot;:&quot;The code you entered has expired. Please go back to your device for a new code and try again.&quot;&#125;&#125;` | The device code has expired. Cancel the device login flow and send the user back to the initial screen. |

### 5. Confirm Successful Login &#123;#tech-step4&#125;

When you receive an access token the person successfully authorized your application. You should persist this access token on the device.

So people know the login process succeeded, your device should display their name and if available, a profile picture until they click `Continue`. To get the person&#039;s name and profile picture, your device should make a standard Graph API call:

```html
GET https://graph.facebook.com/me?
      fields=name,picture&amp;
      access_token=&lt;USER_ACCESS_TOKEN&gt;
```

You get a response in the form:

```
&#123;
  &quot;name&quot;: &quot;John Doe&quot;,
  &quot;picture&quot;: &#123;
    &quot;data&quot;: &#123;
      &quot;is_silhouette&quot;: false,
      &quot;url&quot;: &quot;https://fbcdn.akamaihd.net/hmac...ile.jpg&quot;
    &#125;
  &#125;,
  &quot;id&quot;: &quot;2023462875238472&quot;
&#125;
```

Display the person&#039;s name and profile picture until they click `Continue` on your device.

### 6. Store Access Tokens &#123;#tech-step5&#125;

Your device should persist the access token to make other requests to the Graph API.

Device login access tokens may be valid for up to 60 days but may be invalided in a number of scenarios. For example when a person changes their Facebook password their access token is invalidated.

If the token is invalid, your device should delete the token from its memory. The person using your device needs to perform the device login flow again from [Step 1](#tech-step1) to retrieve a new, valid token.

## Troubleshooting &#123;#troubleshooting&#125;

**Can I make device flow requests over HTTP?**  
OAuth 2 requires TLS/HTTPS.

**Can I make device flow requests with the GET method?**  
All device flow requests should be `POST` requests.

**How can I refresh my device login access token?**  
Device login access tokens may be valid for up to 60 days.

If the token is invalid, your device should delete the token from its memory. The person using your device needs to perform the device login flow again described here in [Step 1](#tech-step1) to retrieve a new, valid token.

To learn more about refreshing tokens, refer to [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens).

**I&#039;m getting a `Invalid API method` error when making a POST request, what&#039;s wrong?**  
If you&#039;re making a POST request and getting an error like this:

```
&#123;&quot;error&quot;:&#123;&quot;message&quot;:&quot;Invalid API method&quot;,&quot;type&quot;:&quot;OAuthException&quot;,&quot;code&quot;:3&#125;&#125;
```

You may need to enable Login from Devices in your app.

Load your [app&#039;s dashboard](https://developers.facebook.com/apps/) and set Product &gt; Facebook login &gt; Settings &gt; Login from Devices to &#039;Yes&#039;.

**My device login access token is invalid. What do I do?**  
If your access token is invalid, your device should delete the token from its memory and obtain a new token. The person using your device needs to perform the device login flow again described here in [Step 1](#tech-step1) to retrieve a new, valid token.

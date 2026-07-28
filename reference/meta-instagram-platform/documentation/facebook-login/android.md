# Facebook Login for Android - Quickstart



The Facebook SDK for Android enables people to sign into your app with Facebook Login. When people log into your app with Facebook they can grant permissions to your app so you can retrieve information or perform actions on Facebook on their behalf.

**Note:** For an example project that illustrates how to integrate Facebook Login into an Android app, see the [FBLoginSample](https://github.com/facebook/facebook-android-sdk/tree/master/samples/FBLoginSample) on [GitHub](https://github.com/).

Follow the steps below to add Facebook Login to your app.

## 1. Register

Please register as a developer if you have not already.
[Register](https://business.facebook.com/business/loginpage/)

## 2. Download the Facebook App

Download the Facebook app by clicking the button below.

[Download Facebook for Android](https://play.google.com/store/apps/details?id=com.facebook.katana)

## 3. Integrate the Facebook SDK

The Facebook Login SDK for Android is a component of the [Facebook SDK for Android](https://developers.facebook.com/documentation/android/componentsdks). To use the Facebook Login SDK in your project, make it a dependency in Maven, or download it. To support the changes in Android 11, use SDK version 8.1 or higher.

Using Maven

- In your project, open your_app &gt; Gradle Scripts &gt; build.gradle (Project) make sure the following repository is listed in the `buildscript &#123; repositories &#123;&#125;&#125;`:

```
mavenCentral()
```

- In your project, **open your_app &gt; Gradle Scripts &gt; build.gradle (Module: app)** and add the following implementation statement to the `dependencies&#123;&#125;` section to depend on the latest version of the Facebook Login SDK:

```
implementation &#039;com.facebook.android:facebook-login:latest.release&#039;
```

- Build your project.

## 4. Edit Your Resources and Manifest

If you use version 5.15 or later of the Facebook SDK for Android, you don&#039;t need to to add an activity or intent filter for Chrome Custom Tabs. This functionality is included in the SDK.

After you integrate Facebook Login, certain App Events are automatically logged and collected for [Events Manager](https://eventsmanager.facebook.com/events_manager2/overview?act=21802407841825), unless you disable Automatic App Event Logging. In particular, when launching an app in Korea, please note that Automatic App Event Logging can be disabled. For details about what information is collected and how to disable automatic app event logging, see [Automatic App Event Logging](https://developers.facebook.com/docs/app-events/automatic-event-collection-detail).

Create strings for your Facebook app ID and for those needed to enable Chrome Custom Tabs. Also, add `FacebookActivity` to your Android manifest.

- Open your `/app/res/values/strings.xml` file.

- Add `string` elements with the names `facebook_app_id`, `fb_login_protocol_scheme` and `facebook_client_token`, and set the values to your App ID and Client Token. For example, if your app ID is `1234`and your client token is `56789` your code looks like the following:

```
&lt;string name=&quot;facebook_app_id&quot;&gt;1234&lt;/string&gt;
&lt;string name=&quot;fb_login_protocol_scheme&quot;&gt;fb1234&lt;/string&gt;
&lt;string name=&quot;facebook_client_token&quot;&gt;56789&lt;/string&gt;
```

- Open the `/app/manifest/AndroidManifest.xml` file.

- Add `meta-data` elements to the `application` element for your app ID and client token:

```
&lt;application android:label=&quot;&#064;string/app_name&quot; ...&gt;
    ...
     &lt;meta-data android:name=&quot;com.facebook.sdk.ApplicationId&quot; android:value=&quot;&#064;string/facebook_app_id&quot;/&gt;
     &lt;meta-data android:name=&quot;com.facebook.sdk.ClientToken&quot; android:value=&quot;&#064;string/facebook_client_token&quot;/&gt;
    ...
&lt;/application&gt;
```

- Add an activity for Facebook, and an activity and intent filter for Chrome Custom Tabs inside your `application` element:

```
&lt;activity android:name=&quot;com.facebook.FacebookActivity&quot;
    android:configChanges=
            &quot;keyboard|keyboardHidden|screenLayout|screenSize|orientation&quot;
    android:label=&quot;&#064;string/app_name&quot; /&gt;
&lt;activity
    android:name=&quot;com.facebook.CustomTabActivity&quot;
    android:exported=&quot;true&quot;&gt;
    &lt;intent-filter&gt;
        &lt;action android:name=&quot;android.intent.action.VIEW&quot; /&gt;
        &lt;category android:name=&quot;android.intent.category.DEFAULT&quot; /&gt;
        &lt;category android:name=&quot;android.intent.category.BROWSABLE&quot; /&gt;
        &lt;data android:scheme=&quot;&#064;string/fb_login_protocol_scheme&quot; /&gt;
    &lt;/intent-filter&gt;
&lt;/activity&gt;
```

- Add a `uses-permission` element to the manifest after the `application` element:

```
&lt;uses-permission android:name=&quot;android.permission.INTERNET&quot;/&gt;
```

- (Optional) To opt out of the [Advertising ID Permission](https://developers.facebook.com/documentation/android/getting-started#ad-id-permissions), add a `uses-permission` element to the manifest after the `application` element:

```
&lt;uses-permission android:name=&quot;com.google.android.gms.permission.AD_ID&quot; tools:node=&quot;remove&quot;/&gt;
```

You may directly set the auto-logging of App Events to “true” or “false” by setting the `AutoLogAppEventsEnabled` flag in the `AndroidManifest.xml` file.

- Build your project.

## 5. Associate Your Package Name and Default Class with Your App

Find these settings in your [app&#039;s settings page.](https://developers.facebook.com/apps/)
**App Settings &gt; Basic &gt; + Platform &gt; Android**

**Package Name:**
Your package name uniquely identifies your Android app. We use this to let people download your app from Google Play if they don&#039;t have it installed. You can find this in your Android Manifest or your app&#039;s build.gradle file.

_Example: com.example.myapp_

**Default Activity Class Name:** This is the fully qualified class name of the activity that handles deep linking such as com.example.app.DeepLinkingActivity. We use this when we deep link into your app from the Facebook app. You can also find this in your Android Manifest.

_Example: com.example.myapp.MainActivity_

## 6. Provide the Development and Release Key Hashes for Your App
To ensure the authenticity of the interactions between your app and Facebook, you need to supply us with the Android key hash for your development environment. If your app has already been published, you should add your release key hash too.

**Generating a Development Key Hash**

You&#039;ll have a unique development key hash for each Android development environment.

### Mac OS
You will need the Key and Certificate Management Tool (`keytool`) from the Java Development Kit.
To generate a development key hash, open a terminal window and run the following command:

**Windows**
You will need the following:

- Key and Certificate Management Tool (`keytool`) from the Java Development Kit

- `openssl-for-windows` openssl library for Windows from the [Google Code Archive](https://code.google.com/archive/p/openssl-for-windows/downloads)

To generate a development key hash, run the following command in a command prompt in the Java SDK folder:

```
keytool -exportcert -alias androiddebugkey -keystore &quot;C:\Users\USERNAME\.android\debug.keystore&quot; | &quot;PATH_TO_OPENSSL_LIBRARY\bin\openssl&quot; sha1 -binary | &quot;PATH_TO_OPENSSL_LIBRARY\bin\openssl&quot; base64
```

This command will generate a 28-character key hash unique to your development environment. Copy and paste it into the field below. You will need to provide a development key hash for the development environment of each person who works on your app.

**Generating a Release Key Hash**

Android apps must be digitally signed with a release key before you can upload them to the store. To generate a hash of your release key, run the following command on Mac or Windows substituting your release key alias and the path to your keystore:

```
keytool -exportcert -alias YOUR_RELEASE_KEY_ALIAS -keystore YOUR_RELEASE_KEY_PATH | openssl sha1 -binary | openssl base64
```

This will generate a 28-character string that you should copy and paste into the field below. Also, see the [Android documentation](https://developer.android.com/studio/publish/app-signing) for signing your apps.

Find the Key Hash settings in your [app&#039;s settings page.](https://developers.facebook.com/apps/) **App Settings &gt; Basic &gt; + Platform &gt; Android**

## 7. Add the Facebook Login Button

The simplest way to add Facebook Login to your app is to add `LoginButton` from the SDK. The `LoginButton` is a UI element that wraps functionality available in the `LoginManager`. When someone clicks on the button, the login is initiated with the permissions set in the `LoginManager`. Facebook Login requires advanced public_profile permission, to be used by external users. The button follows the login state, and displays the correct text based on someone&#039;s authentication state.

To add the Facebook Login button, first add it to your layout XML file:

```
&lt;com.facebook.login.widget.LoginButton
    android:id=&quot;&#064;+id/login_button&quot;
    android:layout_width=&quot;wrap_content&quot;
    android:layout_height=&quot;wrap_content&quot;
    android:layout_gravity=&quot;center_horizontal&quot;
    android:layout_marginTop=&quot;30dp&quot;
    android:layout_marginBottom=&quot;30dp&quot; /&gt;
```

## 8. Register a Callback

Now create a callbackManager to handle login responses by calling `CallbackManager.Factory.create`.

```
callbackManager = CallbackManager.Factory.create();
```

If you are adding the button to a Fragment you must also update your activity to use your fragment. You can customize the properties of `Login button` and register a callback in your `onCreate()` or `onCreateView()` method. Properties you can customize includes `LoginBehavior`, `DefaultAudience`, `ToolTipPopup.Style` and permissions on the `LoginButton`. For example:

```
private static final String EMAIL = &quot;email&quot;;

loginButton = (LoginButton) findViewById(R.id.login_button);
loginButton.setReadPermissions(Arrays.asList(EMAIL));
// If you are using in a fragment, call loginButton.setFragment(this);

// Callback registration
loginButton.registerCallback(callbackManager, new FacebookCallback&lt;LoginResult&gt;() &#123;
    &#064;Override
    public void onSuccess(LoginResult loginResult) &#123;
        // App code
    &#125;

    &#064;Override
    public void onCancel() &#123;
        // App code
    &#125;

    &#064;Override
    public void onError(FacebookException exception) &#123;
        // App code
    &#125;
&#125;);
```

To respond to a login result, you need to register a callback with either `LoginManager` or `LoginButton`. If you register the callback with `LoginButton`, don&#039;t need to register the callback on Login manager.

You add the LoginManager callback to your activity or fragment&#039;s `onCreate()` method:

```
callbackManager = CallbackManager.Factory.create();

LoginManager.getInstance().registerCallback(callbackManager,
        new FacebookCallback&lt;LoginResult&gt;() &#123;
            &#064;Override
            public void onSuccess(LoginResult loginResult) &#123;
                // App code
            &#125;

            &#064;Override
            public void onCancel() &#123;
                 // App code
            &#125;

            &#064;Override
            public void onError(FacebookException exception) &#123;
                 // App code
            &#125;
&#125;);
```

If login succeeds, the `LoginResult` parameter has the new `AccessToken`, and the most recently granted or declined permissions.

You don&#039;t need a `registerCallback` for login to succeed, you can choose to follow current access token changes with the `AccessTokenTracker` class described below.

Finally, in your `onActivityResult` method, call `callbackManager.onActivityResult` to pass the login results to the `LoginManager` via `callbackManager`.

If you are using AndroidX activities or fragments, you don&#039;t have to override `onActivityResult`.

```
  &#064;Override
protected void onActivityResult(int requestCode, int resultCode, Intent data) &#123;
    callbackManager.onActivityResult(requestCode, resultCode, data);
    super.onActivityResult(requestCode, resultCode, data);
&#125;
```

Every activity and fragment that you integrate with the FacebookSDK Login or Share should forward `onActivityResult` to the `callbackManager`.

## 9. Check Login Status

Your app can only have one person at a time logged in, and `LoginManager` sets the current `AccessToken` and `Profile` for that person. The FacebookSDK saves this data in shared preferences and sets at the beginning of the session. You can see if a person is already logged in by checking `AccessToken.getCurrentAccessToken()` and `Profile.getCurrentProfile()`.

You can load `AccessToken.getCurrentAccessToken` with the SDK from cache or from an app book mark when your app launches from a cold start. You should check its validity in your `Activity`&#039;s `onCreate` method:

```
AccessToken accessToken = AccessToken.getCurrentAccessToken();
boolean isLoggedIn = accessToken != null &amp;&amp; !accessToken.isExpired();
```

Then you can later perform the actual login, such as in a custom button&#039;s `OnClickListener`:

```
LoginManager.getInstance().logInWithReadPermissions(this, Arrays.asList(&quot;public_profile&quot;));
```

## 10. Enable Express Login

Express login logs people in with their Facebook account across devices and platform. If a person logs into your app on Android and then changes devices, express login logs them in with their Facebook account, instead of asking for them to select a login method. This avoid creating duplicate accounts or failing to log in at all. To support the changes in Android 11, first add the following code to the `queries` element in your `/app/manifest/AndroidManifest.xml` file.

```
&lt;queries&gt;
  &lt;package android:name=&quot;com.facebook.katana&quot; /&gt;
&lt;/queries&gt;
```

The following code shows how to enable express login.

```
LoginManager.getInstance().retrieveLoginStatus(this, new LoginStatusCallback() &#123;
    &#064;Override
    public void onCompleted(AccessToken accessToken) &#123;
        // User was previously logged in, can log them in directly here.
        // If this callback is called, a popup notification appears that says
        // &quot;Logged in as &lt;User Name&gt;&quot;
    &#125;
    &#064;Override
    public void onFailure() &#123;
        // No access token could be retrieved for the user
    &#125;
    &#064;Override
    public void onError(Exception exception) &#123;
        // An error occurred
    &#125;
&#125;);
```

## Next Steps

Congrats, you&#039;ve added Facebook Login to your Android app! Be sure to check out our other documentation pages for more advanced guides.

[**Implement a Data Deletion Callback**](https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback)
Implement a data deletion callback to respond the people&#039;s request to delete their data from Facebook.

[**Access Tokens and Profiles**](https://developers.facebook.com/documentation/facebook-login/android/accesstokens)
Track the access token and profile of your users.

[**Permissions**](https://developers.facebook.com/documentation/facebook-login/android/permissions)
Manage what data your app has access to through Facebook Login.

[**Troubleshooting**](https://developers.facebook.com/documentation/facebook-login/android/troubleshooting)
Having problems integrating Facebook Login? Check out a list of common problems and how to resolve them.

[**App Review**](https://developers.facebook.com/documentation/resp-plat-initiatives/individual-processes/app-review)
Depending on the Facebook data you request from people using Facebook Login, you may need to submit your app for review prior to launch.

[**Create Your Own Login Flow**](https://developers.facebook.com/documentation/facebook-login/guides/advanced/manual-flow)
For building your own login flow, see [Manually Build a Login Flow.](https://developers.facebook.com/documentation/facebook-login/guides/advanced/manual-flow)


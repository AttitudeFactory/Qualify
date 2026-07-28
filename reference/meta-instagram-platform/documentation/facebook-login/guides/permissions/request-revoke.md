# Requesting &amp; Revoking Permissions



Each type of login flow has its own method of requesting permissions, depending on your platform and how you choose to integrate Facebook Login:

### Web

+ **The Facebook JavaScript SDK** uses a `scope` option with the [`FB.login` function call](https://developers.facebook.com/docs/reference/javascript/FB.login#permissions).
+ **The Login Button** uses a `scope` or `data-scope` parameter on the [`fb:login-button`](https://developers.facebook.com/documentation/facebook-login/web/login-button) element.
+ **A Manually Built Login Flow** should add the `scope` parameter to the [login dialog URL that they redirect to.](https://developers.facebook.com/documentation/facebook-login/guides/advanced/manual-flow#login)

### Mobile Apps

+ **Android Login** can use a number of different classes to request and manage permissions.  Please see our [login tutorial for Android](https://developers.facebook.com/documentation/facebook-login/android) for more information.
+ **iOS Login** can use a number of different methods to request permissions.  Please see our [login tutorial for iOS](https://developers.facebook.com/documentation/facebook-login/ios#permissions) for more information.
+ **Windows Phone** uses the [`scope` parameter](https://developers.facebook.com/docs/facebook-login/login-for-windows-phone#login) when launching the URI association.

Please note that many of the APIs listed above can also be used to ask for additional permissions later during an app&#039;s lifetime, not just at initial login.

## Optimizing Permissions Requests &#123;#optimizing&#125;

As a general rule, the more permissions an app requests, the less likely it is that people will use Facebook to log into your app. In fact, our research shows that apps that ask for more than four permissions experience a significant drop off in the number of completed logins.

### Guidelines

Here are a few guidelines to use when asking for permissions, both during and after login:

+ Only ask for the permissions that are essential to an app.

+ Ask for permission in the context in which they are required. For example, if your app wants to show places of interest near a person&#039;s location, asking for `user_location` just prior to displaying that information gives the person a greater understanding of why the permission is being requested.

+ Separate the request of read and publish permissions. For more details, see [below](#publishing).

+ Never ask for permissions you think you might need in the future. People will be suspicious and may reject your app.

+ Tell people ahead of time why you are requesting a permission.  Explaining why you need access to something will increase the chance that they are willing to share it.

* Regulatory requirements applicable to collecting, processing and sharing personal data have continued to evolve around the world, and, depending on the jurisdiction, different laws will apply to your collection and processing of information (the European Union’s GDPR, the United Kingdom’s UKGDPR and Brazil’s Lei Geral de Proteção de Dados are examples of such laws). We strongly recommend that you familiarise yourself with the requirements under any applicable laws and seek any specific legal guidance where necessary.

### Publishing Permissions &#123;#publishing&#125;

Apps should separate the request of read and publish permissions. Plan your app around requesting the bare minimum of read permissions at initial login and then any publish permissions when a person actually needs them, for example when they want to create an Open Graph story from within the app. This provides the best user experience and optimizes conversion.

**Note:** You may receive Developer Alerts if your app requests read and publish permissions back-to-back. To stop receiving these alerts, separate your requests or follow the guidelines below for exceptional cases.

In the rare case your app requires publishing permissions up front (for example, an app that does nothing but publish a person&#039;s mood to Facebook) only request the bare minimum read permissions at initial login. After the person logs in, show the person a screen explaining why your app needs publishing permissions and let the person opt-in to the publishing permission request by clicking a button. This will provide them with more context and improve your conversion.

One instance where you may have to request read and write permissions back-to-back is the first time that you&#039;re associating an email-based account with a person&#039;s Facebook account.  This is usually done when someone wants to share a story on their Facebook Timeline.  When your app creates the login dialog, the person will see two dialogs in a row - one to connect their account to your app and another asking for publish permissions. For this case, make sure that the only read permissions you request are `public_profile`. This provides the best user experience because the user wants to publish from your app and is often not interested in providing additional read permissions. It will also improve your conversion.

## Checking Current Permissions &#123;#checking&#125;

Facebook offers people full control over the permissions they grant to an app. That control extends beyond the point at which they see the login dialog. They can choose not to grant certain permissions during the login process.  They can also revoke permissions in their Facebook privacy settings at any time. Apps should check for the validity of permissions before attempting to perform an API call where they are required.  For example, checking that `email` is still granted before sending a message.

For web apps, we provide a graph API endpoint to retrieve a list of granted permissions:

```
GET /&#123;user-id&#125;/permissions
```

The call must be made with either a user [access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens) or your app access token. The call will return a JSON string containing the permission names which have been granted to the app and their status:

```
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;permission&quot;: &quot;public_profile&quot;,
      &quot;status&quot;: &quot;granted&quot;
    &#125;,
    &#123;
      &quot;permission&quot;: &quot;email&quot;,
      &quot;status&quot;: &quot;granted&quot;
    &#125;,
    &#123;
      &quot;permission&quot;: &quot;user_friends&quot;,
      &quot;status&quot;: &quot;declined&quot;
    &#125;
  ]
&#125;
```

We also provide methods in the [iOS](https://developers.facebook.com/documentation/facebook-login/ios/permissions#permissions-checking) and [Android](https://developers.facebook.com/documentation/facebook-login/android/permissions) SDKs that provide platform-friendly representations of the permissions your app has been granted.

## Handling Missing Permissions &#123;#handling&#125;

When an app requests permissions, people may completely deny those permissions, not fully grant those permissions, or change them later. In order to provide a great experience, apps should be built to handle these situations.

First, apps should be able to handle any permissions that were requested but not granted:

+ [Check granted permissions](#checking) before trying to use APIs that require them.
+ Detect permissions errors returned when an API request is made without the correct permission.  This is an example error:

```
&#123;
  &quot;error&quot;: &#123;
    &quot;message&quot;: &quot;(#200) The user hasn&#039;t authorized the application
     to perform this action&quot;,
    &quot;type&quot;: &quot;OAuthException&quot;,
    &quot;code&quot;: 200
  &#125;
&#125;
```

Once an app has detected that someone has denied some or all permissions, it may pass them back through the login flow **once** and request any required permissions. However, this is a poor experience and should be avoided if possible. If someone is actively choosing not to grant a specific permission to an app they are unlikely to change their mind, even in the face of continued prompting. Instead, do the following:

+ If a person declines the [login dialog](https://developers.facebook.com/documentation/facebook-login/overview#logindialog) have a clear and upfront explanation about why you are requesting each permission.  Then let them click or tap to opt back in to the permission request dialog.  Do not immediately redirect them into a permission request dialog without an explanation.

+ If someone has declined a permission for your app, the login dialog won&#039;t let your app re-request the permission [unless you pass `auth_type=rerequest` along with your request.](https://developers.facebook.com/documentation/facebook-login/web#re-asking-declined-permissions)

+ For cases where someone has granted some permissions but not others, only prompt for missing permissions at the point at which they are needed. For example, if your app sends order confirmations to users&#039; email, only request `email` when they make an order.

+ Unless the permissions you are requesting in the login dialog are critical to the functionality of your app and a feature doesn&#039;t work without them, let people continue using your app without the permissions.

**Note:** You may receive Developer Alerts if your app repeatedly directs users to permissions dialogs after they deny permissions. To stop receiving these alerts, follow these guidelines.

## Revoking Permissions &#123;#revoking&#125;

Apps can let people revoke permissions that were previously granted. For example, your app could have a settings page that lets someone disable sending them email messages.  That settings page could also revoke the `email` permission at the same time.

You can revoke a specific permission by making a call to a Graph API endpoint:

```
DELETE /&#123;user-id&#125;/permissions/&#123;permission-name&#125;
```

This request must be made with a user access token or an app access token for the current app. If the request is successful, you will receive a response of `true`.

### Revoking Authorization and Token Invalidation for Login &#123;#revokelogin&#125;

You can also let people completely de-authorize an app, or revoke authorization for login, by making a call to this Graph API endpoint:

```
DELETE /&#123;user-id&#125;/permissions
```

This request must be made with a valid user access token or an app access token for the current app. If the request is successful, your app receives a response of `true`.  If the call is successful, any user access token for the person will be invalidated and they will have to log in again.  Because you&#039;re de-authorizing your app, they will also have to grant access to your app as if they were logging in for the first time.

## Platform Guides

[Android](https://developers.facebook.com/documentation/facebook-login/android/permissions)

[iOS](https://developers.facebook.com/documentation/facebook-login/ios/permissions)

[Web](https://developers.facebook.com/documentation/facebook-login/web#re-launching-permissions-dialog)

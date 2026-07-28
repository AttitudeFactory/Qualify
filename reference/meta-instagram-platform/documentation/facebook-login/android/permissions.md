# Managing Permissions for Android



During basic login your app receives access to a person&#039;s public profile and email. To access additional profile information or to publish content to Facebook on someone&#039;s behalf, you need to request the necessary permissions:

- __[Default Public Profile fields](https://developers.facebook.com/docs/facebook-login/permissions#reference-default)__ -  Gives access to basic profile information.

- __Read Permissions__ - All other information that someone adds to their Facebook profile are secured by other read permissions.

- __Write Permissions__ - Apps need separate publish permission to post content on the person&#039;s behalf.

Here are the ways to manage permissions in your app:

- When your app sends Facebook requests for someone, it should check for necessary permissions and request them if necessary.

- Your app should deal with missing permissions errors from Facebook by asking for permissions and retrying.

- People using your app can revoke permissions on Facebook, but you can also implement this in your app.

- You can also let people remove basic login privileges from your app, by implementing a mechanism to revoke login entirely.

Learn more about the different available permissions in [Permissions Guide](https://developers.facebook.com/docs/reference/login#permissions).  

People are sensitive about granting publish permissions, so you should only ask for publish permissions once a person is ready to post something from your app and  **not** during the initial login.

## Get Additional Permissions &#123;#permissions&#125;

During the basic login your app receives access to a person&#039;s public profile and email. To access additional profile information or to publish content to Facebook on their behalf, you need to request the necessary permissions.

Here we get `user_status`. You can pass in these permissions to the `LoginButton` button or a custom UI for login and permissions.

In `MainFragment` class modify the code in the `onCreateView()`:

```
...
LoginButton authButton = (LoginButton)view.findViewById(R.id.authButton);
authButton.setFragment(this);
authButton.setReadPermissions(Arrays.asList(&quot;user_status&quot;));

return view;
...
```

## Get Read Permissions &#123;#permissions-read&#125;

`LoginManager` is a singleton instance, and works with the AccessToken&#039;s currentAccessToken. After a successful login, the currentAccessToken will be set. To request additional permissions, simply call the `logInWithPermissionName` methods.

The `logInWithPermissionName` methods always open a UI and prompt someone for additional permissions if needed. To get addiitional permissions from someone, make this request with the Facebook SDK for Android:

```
LoginManager.getInstance().logInWithReadPermissions(
    fragmentOrActivity,
    Arrays.asList(&quot;email&quot;));
```

Use this to request permissions beyond what the app already has been granted. You can use this after initial login.

You can request many of the read permissions listed in [Permissions Reference](https://developers.facebook.com/docs/facebook-login/permissions#reference).

## Get Publish Permissions &#123;#permissions-publish&#125;

You can ask for any number of read permissions or for publish permissions during login. Ask for more than four permissions experience a significant drop off in the number of completed logins.

**Note:** As of April 24,2018, the `pubish_actions` permission has been removed. Please see the [Breaking Changes Changelog](https://developers.facebook.com/docs/graph-api/changelog/breaking-changes#login-4-24) for more details. To provide a way for your app users to share content to Facebook, we encourage you to use our [Sharing products](https://developers.facebook.com/docs/sharing) instead.

Requesting publishing permissions with `publish_actions` during login creates a second step in the login UI. So you should request minimum read permissions during login then request any additional or publish permissions when someone actually needs them. To optimize your permission requests, see [Optimizing Permissions](https://developers.facebook.com/docs/facebook-login/permissions/v2.2#optimizing).

To ask for publish permissions in your app, you can use the `LoginManager`.

```
LoginManager.getInstance().logInWithPublishPermissions(
    fragmentOrActivity,
    Arrays.asList(&quot;publish_actions&quot;));
```

This requests permissions in addition to what the app already received during login.

## Re-Request Permissions &#123;#permissions-rerequest&#125;

People can grant only a subset of permissions that you ask for, except for `public profile`, which is granted at login.

To get the list of permissions associated with the current access token, call:

```
AccessToken.getCurrentAccessToken().getPermissions();
```

To get the list of declined permissions, call:

```
AccessToken.getCurrentAccessToken().getDeclinedPermissions();
```

Your app should handle the case where someone had declined to grant your app one of the permissions you requested. If your app must have one of the declined permissions to work, you can request them again by using the `LoginManager` as in the examples above.

## Login Review &#123;#loginreview&#125;

When you implement Facebook Login, your app can optionally ask someone for permissions on a subset of that person&#039;s data.

If your app asks for more than the default public profile fields and email, Facebook must review it before you release it. Learn more about the review process and what&#039;s required to pass review.

[Login Review Guide](https://developers.facebook.com/docs/facebook-login/review)

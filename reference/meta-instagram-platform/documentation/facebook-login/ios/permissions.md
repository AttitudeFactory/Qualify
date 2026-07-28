# Managing Permissions, iOS



During basic login, your app receives access to a person&#039;s public profile. To access additional profile information or to publish content to Facebook on their behalf, you need to request additional permissions, see [Permissions with Facebook Login](https://developers.facebook.com/docs/facebook-login/permissions).

Your app should manage permissions as follows:

- __Graph API Requests__ - Before you send Graph API requests, you should check for necessary permissions and request them if needed.

- __Missing and Revoked Permissions__ - Your app needs to deal with missing or revoked permissions errors from Facebook such as by asking for permissions and retrying. See [Error-Handling, iOS SDK](https://developers.facebook.com/documentation/ios/errors).

- __Timing Requests__ - You will get better conversion if you ask for permissions only when they are needed and provide functionality without requiring all permissions.

## Request at Login &#123;#permissions-login&#125;

To ask for permissions on login with `FBSDKLoginButton`, set the `permissions` property:

```
let loginButton = FBLoginButton()
loginButton.permissions = [&quot;public_profile&quot;, &quot;email&quot;]
```

If you&#039;re using a custom login button instead of `FBSDKLoginButton`, you can use a `LoginManager` to perform the login:

```
override func viewDidLoad() &#123;
    super.viewDidLoad()

    ...
    loginButton.addTarget(self, action: #selector(loginButtonClicked), for: .touchUpInside)
&#125;

&#064;objc func loginButtonClicked() &#123;
    let loginManager = LoginManager()
    loginManager.logIn(permissions: [&quot;email&quot;], from: self) &#123; result, error in
        // Process result or error
    &#125;
&#125;
```

You should check the for availability of an existing token before you call the `loginManager`. See [Facebook Login for iOS](https://developers.facebook.com/documentation/facebook-login/ios)

## Check for Permissions &#123;#permissions-checking&#125;

To check for current permissions, inspect the `FBSDKAccessToken`.

```
if ([[FBSDKAccessToken currentAccessToken] hasGranted:&#064;&quot;email&quot;]) &#123;
  // TODO: publish content.
&#125; else &#123;
  FBSDKLoginManager *loginManager = [[FBSDKLoginManager alloc] init];
  [loginManager logInWithPublishPermissions:&#064;[&#064;&quot;email&quot;]
                         fromViewController:self
                                    handler:^(FBSDKLoginManagerLoginResult *result, NSError *error) &#123;
    //TODO: process error or result.
  &#125;];
&#125;
```

## Declined Permissions &#123;#permissions-declining&#125;

Inspect the `FBSDKLoginResult` returned to the `FBSDKLoginManager` callback or to the `FBSDKLoginButton` delegate to see if someone declined a request for permissions:

```
FBSDKLoginManager *loginManager = [[FBSDKLoginManager alloc] init];
[loginManager logInWithPublishPermissions:&#064;[&#064;&quot;email&quot;]
                       fromViewController:self
                                  handler:^(FBSDKLoginManagerLoginResult *result, NSError *error) &#123;
 if ([result.declinedPermissions containsObject:&#064;”email”]) &#123;
   // TODO: do not request permissions again immediately. Consider providing a NUX
  // describing  why the app want this permission.
 &#125; else &#123;
 // ...
 &#125;
&#125;];
```

## Missing Permissions &#123;#permissions-missing&#125;

When you make Graph API requests, you can check the `NSError` object to see of there are permission errors:

```
[[[FBSDKGraphRequest alloc] initWithGraphPath:&#064;&quot;me/feed&quot;
                                   parameters:&#064;&#123; &#064;&quot;message&quot; : &#064;&quot;This is a status update&quot; &#125;
                                   HTTPMethod:&#064;&quot;POST&quot;]
  startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection, id result, NSError *error) &#123;
    if ([error.userInfo[FBSDKGraphRequestErrorGraphErrorCode] isEqual:&#064;200]) &#123;
      NSLog(&#064;&quot;permission error&quot;);
    &#125;
&#125;];
```

For more information, see [Error-Handling, iOS SDK](https://developers.facebook.com/documentation/ios/errors).

## Request More Permissions &#123;#permissions-requesting&#125;

Use `FBSDKLoginManager` to request additional permissions or request previously declined permissions using the `logInWith*:` methods. `FBSDKLoginManager` will see it&#039;s a re-request by the availability of `[FBSDKAccessToken currentAcccessToken]`.

## Revoke Permissions &#123;#permissions-revoking&#125;

You can enable someone to remove or revoke specific permissions previously granted to your app. For example your app can have a settings page where people can disable specific features.

Revoke permissions by making a call to a Graph API endpoint.

```
[[[FBSDKGraphRequest alloc] initWithGraphPath:&#064;&quot;me/permissions/email&quot;
       parameters:nil
       HTTPMethod:&#064;&quot;DELETE&quot;]
  startWithCompletionHandler:^(FBSDKGraphRequestConnection *connection, id result, NSError *error) &#123;
  // ...
&#125;];
```

### Revoke Login &#123;#permissions-revokinglogin&#125;

You can revoke all privileges for an app, by making a Graph API call that deletes all permissions. Use the code in [Revoke Permissions](#permissions-revoking) and change the request&#039;s path to `/me/permissions`.

### Revoking Permissions via Graph API Explorer
For testing purposes you may want to unauthorize revoke permissions without using your app. You can use the [Graph API Explorer](https://developers.facebook.com/tools/explorer/) to do so.

1. Access the [Graph API Explorer](https://developers.facebook.com/tools/explorer/).
2. Select your App.
3. Click `Get Token` &gt; `Get Access Token`.
4. Click `Clear` to unauthorize the selected app.

To revoke a single permission:

1. Set the path input field to `/me/permissions/&#123;permission-name&#125;` while using the permission you want to remove for `&#123;permission-name&#125;`, for example `email`.
2. Switch from `GET` to `DELETE`.
3. Hit the `Submit` button.

[Graph API Explorer](https://developers.facebook.com/tools/explorer/)

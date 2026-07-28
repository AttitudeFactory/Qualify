# Facebook Login for iOS - Quickstart



**Warning:** We have made a change to endpoints for Limited Login; it is now accessible under limited.facebook.com

When people log into your app with Facebook, they can grant permissions to your app so you can retrieve information or perform actions on Facebook on their behalf.

The following steps are for adding Facebook Login to your iOS project.

## 1. Register

Please register as a developer if you have not already.
[Register](https://business.facebook.com/business/loginpage/)

## 2. Set up Your Development Environment

Set up your development environment before using Facebook Login for iOS.

Using Swift Package Manager (SPM)

- In Xcode, click **File &gt; Swift Packages &gt; Add Package Dependency.**

- In the dialog that appears, enter the repository URL: [https://github.com/facebook/facebook-ios-sdk](https://github.com/facebook/facebook-ios-sdk)

- In **Version**, select **Up to Next Major** and the default option.

- Complete the prompts to select the libraries you want to use in your project.
| If You Want To | Add This Package to your project |
| --- | --- |
| Allow your app to use the Facebook services | `FBSDKCoreKit` |
| Allow users to log into your app and for your app to ask for permissions to access data | `FBSDKLoginKit` |
| Allow your app to share content on Facebook | `FBSDKShareKit` |
| Allow users to log into your app to enable engagement and promote social features | `FBSDKGamingServicesKit` |

## 3. Register and Configure Your App with Facebook

Register and configure your app so you can use Facebook Login by adding your Bundle Identifier.

The bundle identifier (Bundle ID) should appear in the box below. If the box is empty, find your bundle identifier in your Xcode Project&#039;s iOS Application Target and paste it into the box below.

You can change your bundle identifier via the iOS section on the settings page.

**App Settings &gt; Basic &gt; + Platform &gt; iOS**

## 4. Configure Your Project

Configure the `Info.plist` file with an XML snippet that contains data about your app.

After you integrate Facebook Login, certain App Events are automatically logged and collected for [Events Manager](https://eventsmanager.facebook.com/events_manager2/overview), unless you disable Automatic App Event Logging. In particular, when launching an app in Korea, please note that Automatic App Event Logging can be disabled. For details about what information is collected and how to disable automatic app event logging, see [Automatic App Event Logging](https://developers.facebook.com/docs/app-events/automatic-event-collection-detail).

- Right-click `Info.plist`, and choose **Open As ▸ Source Code.**

- Copy and paste the following XML snippet into the body of your file (`&lt;dict&gt;...&lt;/dict&gt;`).

```
&lt;key&gt;CFBundleURLTypes&lt;/key&gt;
&lt;array&gt;
  &lt;dict&gt;
  &lt;key&gt;CFBundleURLSchemes&lt;/key&gt;
  &lt;array&gt;
    &lt;string&gt;fbAPP-ID&lt;/string&gt;
  &lt;/array&gt;
  &lt;/dict&gt;
&lt;/array&gt;
&lt;key&gt;FacebookAppID&lt;/key&gt;
&lt;string&gt;APP-ID&lt;/string&gt;
&lt;key&gt;FacebookClientToken&lt;/key&gt;
&lt;string&gt;CLIENT-TOKEN&lt;/string&gt;
&lt;key&gt;FacebookDisplayName&lt;/key&gt;
&lt;string&gt;APP-NAME&lt;/string&gt;
```

- In `&lt;array&gt;&lt;string&gt;` in the key &gt;`[CFBundleURLSchemes]`, replace APP-ID with your App ID.

- In `&lt;string&gt;` in the key `FacebookAppID`, replace *APP-ID* with your App ID.

- In `&lt;string&gt;` in the key `FacebookClientToken`, replace CLIENT-TOKEN with the value found under **Settings &gt; Advanced &gt; Client Token** in your App Dashboard.

- In `&lt;string&gt;` in the key `FacebookDisplayName`, replace *APP-NAME* with the name of your app.

- To use any of the Facebook dialogs (e.g., Login, Share, App Invites, etc.) that can perform an app switch to Facebook apps, your application&#039;s `Info.plist` also needs to include the following:

```
&lt;key&gt;LSApplicationQueriesSchemes&lt;/key&gt;
&lt;array&gt;
  &lt;string&gt;fbapi&lt;/string&gt;
  &lt;string&gt;fb-messenger-share-api&lt;/string&gt;
&lt;/array&gt;
```

You may directly set the automatic collection of App Events to “true” or “false” by adding `FacebookAutoLogAppEventsEnabled` as a key in `Info.plist`.

Your project will need to include the Keychain Sharing capability in order for login to work in Mac Catalyst applications.

- Select the **+ Capability** button in the **Signing &amp; Capabilities** tab when configuring your app target.

- Find and select the **Keychain Sharing** capability.

- Ensure that the **Keychain Sharing** capability is listed for the target.

## 5. Connect your App Delegate

Replace the code in `AppDelegate.swift` method with the following code. This code initializes the SDK when your app launches, and allows the SDK to handle logins and sharing from the native Facebook app when you perform a Login or Share action. Otherwise, the user must be logged into Facebook to use the in-app browser to login.

```
// AppDelegate.swift
import UIKit
import FBSDKCoreKit

&#064;UIApplicationMain
class AppDelegate: UIResponder, UIApplicationDelegate &#123;
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
    ) -&gt; Bool &#123;
        ApplicationDelegate.shared.application(
            application,
            didFinishLaunchingWithOptions: launchOptions
        )

        return true
    &#125;

    func application(
        _ app: UIApplication,
        open url: URL,
        options: [UIApplication.OpenURLOptionsKey : Any] = [:]
    ) -&gt; Bool &#123;
        ApplicationDelegate.shared.application(
            app,
            open: url,
            sourceApplication: options[UIApplication.OpenURLOptionsKey.sourceApplication] as? String,
            annotation: options[UIApplication.OpenURLOptionsKey.annotation]
        )
    &#125;
&#125;
```

iOS 13 moved opening URL functionality to the `SceneDelegate`. If you are using iOS 13, add the following method to your `SceneDelegate` so that operations like logging in or sharing function as intended:

```
// SceneDelegate.swift
import FBSDKCoreKit
  ...
func scene(_ scene: UIScene, openURLContexts URLContexts: Set&lt;UIOpenURLContext&gt;) &#123;
    guard let url = URLContexts.first?.url else &#123;
        return
    &#125;

    ApplicationDelegate.shared.application(
        UIApplication.shared,
        open: url,
        sourceApplication: nil,
        annotation: [UIApplication.OpenURLOptionsKey.annotation]
    )
&#125;
```

## 6. Add Facebook Login to Your Code

Use the Facebook Login button in your iOS app.

**6a. Add Facebook Login to Your Code**

To add a Facebook-branded Login button to your app, add the following code snippet to a view controller.

```
// Add this to the header of your file, e.g. in ViewController.swift
import FBSDKLoginKit

// Add this to the body
class ViewController: UIViewController &#123;
    override func viewDidLoad() &#123;
        super.viewDidLoad()

        let loginButton = FBLoginButton()
        loginButton.center = view.center
        view.addSubview(loginButton)
    &#125;
&#125;
```

At this point you should be able to run your app and log in using the Facebook Login button.

**6b. Check Current Login Status**

Your app can only have one person logged in at a time. We represent each person logged into your app with `AccessToken.current`.

The `LoginManager` sets this token for you and when it sets `AccessToken.current` it also automatically writes it to the keychain store.

The `AccessToken` contains `userID` which you can use to identify the user.

You should update your view controller to check for an existing token at load. This avoids unnecessary showing the login flow again if someone already granted permissions to your app:

```
override func viewDidLoad() &#123;
    super.viewDidLoad()

    if let token = AccessToken.current,
        !token.isExpired &#123;
        // User is logged in, do work such as go to next view controller.
    &#125;
&#125;
```

**6c. Ask for Permissions**

When using Facebook Login, your app can ask for permissions on a subset of a person&#039;s data. Facebook Login requires advanced public_profile permission, to be used by external users.

**Read Permissions for Facebook Login Button**

To request additional read permissions, set the `permissions` property on the `FBLoginButton` object.

```
// Extend the code sample from 6a. Add Facebook Login to Your Code
// Add to your viewDidLoad method:
loginButton.permissions = [&quot;public_profile&quot;, &quot;email&quot;]
```

The user will be prompted to grant your app with the requested permissions. Note that some permissions will require a Login Review. See [Managing Permissions](https://developers.facebook.com/documentation/facebook-login/ios/permissions) for more information on permissions.

## 7. Next Steps

Congrats, you&#039;ve added Facebook Login to your iOS app! Be sure to check out our other documentation pages for more advanced guides.

[**Implement a Data Deletion Callback**](https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback)
Implement a data deletion callback to respond the people&#039;s request to delete their data from Facebook.

[**Add App Events**](https://developers.facebook.com/documentation/ios/getting-started#app-events)
Add events to your app to view analytics, measure ad performance and build audiences for ad targeting.

[**Advanced Topics &amp; Setup
**](https://developers.facebook.com/documentation/facebook-login/ios/advanced)
Check out our advanced setup for Facebook Login for iOS apps.

[**Permissions**](https://developers.facebook.com/documentation/facebook-login/ios/permissions)
Manage what data your app has access to through Facebook Login.

[**Handling Errors**](https://developers.facebook.com/documentation/ios/errors)
Check out how to responds to errors returned by the Facebook SDK.

[**App Review**](https://developers.facebook.com/documentation/resp-plat-initiatives/individual-processes/app-review)
Depending on the Facebook data you request from people using Facebook Login, you may need to submit your app for review prior to launch.

[**Create Your Own Login Flow**](https://developers.facebook.com/documentation/facebook-login/guides/advanced/manual-flow)
For building your own login flow, see Manually Build a Login Flow.


# Facebook Login for iOS - Advanced



#### - [Login Review](#review)
#### - [Custom Login Button](#custom-login-button)
#### - [Using the Interface Builder](#interface-builder)
#### - [Access Tokens](#access-tokens)
#### - [Profiles](#profiles)
#### - [Track Profile Pictures](#profile_picture_view)
#### - [Setting the Authorization Type](#auth_type)

## Login Review &#123;#review&#125;

If your app asks for more than `public_profile` and `email`, Facebook must review it before you release it. Learn more about the review process and what&#039;s required to pass review.

[Login Review Guide](https://developers.facebook.com/docs/facebook-login/review)

## Custom Login Button &#123;#custom-login-button&#125;

Instead of using the Facebook-branded login button (explained in [Facebook Login for iOS - Quickstart](https://developers.facebook.com/documentation/facebook-login/ios#6--add-facebook-login-to-your-code)) you may want to design a custom layout and behavior. In the following code example we invoke the login dialog using the login manager class (`LoginManager`) and a custom button (`UIButton`). You can use any other custom user interface or event handling to invoke the login dialog.

```
class ViewController: UIViewController &#123;
    override func viewDidLoad() &#123;
        super.viewDidLoad()

        // Add a custom login button to your app
        let loginButton = UIButton(type: .custom)
        loginButton.backgroundColor = .darkGray
        loginButton.frame = CGRect(x: 0, y: 0, width: 180, height: 40)
        loginButton.center = view.center
        loginButton.setTitle(&quot;My Login Button&quot;, for: .normal)

        // Handle clicks on the button
        loginButton.addTarget(self, action: #selector(loginButtonClicked), for: .touchUpInside)

        view.addSubview(loginButton)
    &#125;

    // Once the button is clicked, show the login dialog
    func loginButtonClicked() &#123;
        let loginManager = LoginManager()
        loginManager.logIn(permissions: [&quot;public_profile&quot;], from: self) &#123; result, error in
            if let error = error &#123;
                print(&quot;Encountered Erorr: \(error)&quot;)
            &#125; else if let result = result, result.isCancelled &#123;
                print(&quot;Cancelled&quot;)
            &#125; else &#123;
                print(&quot;Logged In&quot;)
            &#125;
        &#125;
    &#125;
&#125;
```

## Using the Interface Builder &#123;#interface-builder&#125;

These steps are required for version 12.0.0 and later of the Facebook iOS SDK. Apps using the `Interface Builder` may crash if you have not completed this step.

To add the login button graphically in `Interface Builder`:

1. Add a `UIButton` object to your layout. Set constraints to position it.
2. In `Identity inspector` change the `Class` property to `FBSDKLoginButton`.

Now your layout looks like this:

**Note**: Do not set a module for the `FBSDKLoginButton` class. It should show **None**:

**Note**: You may see the following error in Xcode logs due to a known issue with XCFrameworks:

```
[Storyboard] Unknown class FBSDKLoginButton in Interface Builder file.
```

You can fix this by &quot;pre-loading&quot; the FBSDKLoginButton class before the storyboard loads by adding the following to your `application:didFinishLaunchingWithOptions:` method:

```
// For Swift
_ = FBLoginButton.self

// For Objective-C
[FBSDKLoginButton class];
```

## Access Tokens &#123;#access-tokens&#125;

### Notifications &#123;#access-tokens-notifications&#125;

You can track `AccessToken.current` changes with the `.AccessTokenDidChange` notification in `NotificationCenter`. This allows you to respond to changes in the user&#039;s login state:

```
NotificationCenter.default.addObserver(
    forName: .AccessTokenDidChange,
    object: nil,
    queue: .main
) &#123; notification in
    if notification.userInfo?[AccessTokenDidChangeUserIDKey] != nil &#123;
        // Handle user change
    &#125;
&#125;
```

The iOS SDK can update `AccessToken.current` over time, such as when the SDK refreshes a token with a longer expiration date. Therefore, you should check the `userInfo` dictionary in the notification for `AccessTokenDidChangeUserIDKey` to determine if the user has changed.

## Profiles &#123;#profiles&#125;

`Profile` contains public profile information, allowing you to personalize your app with the user&#039;s name and profile picture. You can load the logged in user&#039;s profile using `loadCurrentProfile(completion:)`.

```
Profile.loadCurrentProfile &#123; profile, error in
    if let firstName = profile?.firstName &#123;
        print(&quot;Hello, \(firstName)&quot;)
    &#125;
&#125;
```

You can set the `enableUpdatesOnAccessTokenChange` property to `true` to have the profile automatically loaded to `Profile.current`. This also lets you to observe the `.ProfileDidChange` notification to respond to profile changes:

```
Profile.enableUpdatesOnAccessTokenChange(true)
NotificationCenter.default.addObserver(
    forName: .ProfileDidChange,
    object: nil,
    queue: .main
) &#123; notification in
    if let currentProfile = Profile.current &#123;
        // Update for new user profile
    &#125;
&#125;
```

## Showing Profile Pictures &#123;#profile_picture_view&#125;

The `FBProfilePictureView` class provides an easy way to display someone&#039;s Facebook profile picture. Simply set the `profileID` property on the instance. You can set it to a value of `AccessToken.current.userID` to show the profile picture of the person currently logged in.

```
let profilePictureView = FBProfilePictureView()
profilePictureView.frame = CGRect(x: 0, y: 0, width: 100, height: 100)
profilePictureView.profileID = AccessToken.current!.userID
view.addSubview(profilePictureView)
```

## Setting the Authorization Type &#123;#auth_type&#125;

The default `auth_type` for Facebook Login buttons in the Facebook SDK for iOS is [rerequest](https://developers.facebook.com/documentation/facebook-login/guides/permissions/request-revoke#handling). If you want to avoid requesting permissions that were previously denied, set `auth_type` to `nil`. You can also set it to [reauthorize](https://developers.facebook.com/documentation/facebook-login/auth-vs-data#data-access-expiration) to show the data reauthorization dialog if the user&#039;s data access has expired.

The following example shows how to set the `auth_type` in Swift.

```
let loginButton = FBLoginButton()

// Set to nil for no auth_type
button.authType = nil

// Or set to reauthorize
button.authType = .reauthorize
```

The following example shows how to set the `auth_type` using a login configuration with a login manager.

```
let config = LoginConfiguration(
    permissions: [],
    tracking: .enabled,
    messengerPageId: nil,
    authType: nil
)

let loginManager = LoginManager()
loginManager.logIn(viewController: self, configuration: config!) &#123; loginResult in
    // Do something with loginResult
&#125;
```

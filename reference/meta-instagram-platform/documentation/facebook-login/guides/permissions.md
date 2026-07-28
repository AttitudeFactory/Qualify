# Permissions with Facebook Login



When a person logs into your app via Facebook Login you can access a subset of that person&#039;s data stored on Facebook.  *Permissions* are how you ask someone if you can access that data.  A person&#039;s privacy settings combined with what you ask for will determine what you can access.

[Requesting &amp; Revoking](https://developers.facebook.com/documentation/facebook-login/guides/permissions/request-revoke)

[Review](https://developers.facebook.com/documentation/facebook-login/guides/permissions/review)

[Permissions Reference](https://developers.facebook.com/docs/facebook-login/permissions)

## Facebook Login Example
Permissions are strings that are passed along with a login request or an API call. For example, if you add the [login button](https://developers.facebook.com/documentation/facebook-login/web/login-button) to a web app and ask for `pages_show_list` via the `scope` parameter, a person would be prompted with this dialog when logging in for the first time. We provide similar mechanisms for iOS and Android.  Links are provided for each platform in the [Requesting and Revoking](https://developers.facebook.com/documentation/facebook-login/guides/permissions/request-revoke) guide.

## When to ask for Permissions

Your app can ask for additional permissions at any time, even after a person logs in for the first time.  For example, the `user_photos` permission allows your app to get a person&#039;s published photos. It&#039;s recommended you ask for this permission only when your app needs to show the person their published photos.  When you ask for new permissions, the person using your app will be asked about those new permissions and has the ability to opt out.  For more information, see [Optimizing Permissions Requests](https://developers.facebook.com/documentation/facebook-login/guides/permissions/request-revoke#optimizing).

Permissions only need to be granted once per app, i.e. permissions granted on one platform are effectively granted on all the platforms your app supports.

## User Control
Facebook Login allows **a person to grant only a subset of permissions** that you ask for to your app, except for public profile, which is always required.  This is available as a separate screen in the login dialog when you ask for permissions. Your app should handle the case where someone had declined to grant your app one of the permissions you requested.

#### Revoked Permissions
People can also revoke permissions granted to your app in Facebook&#039;s interface at any time after they have logged in. It is important that your app regularly checks which permissions have been granted, especially when launching on a new platform. We provide methods for you to [check what permissions are currently granted to your app](https://developers.facebook.com/documentation/facebook-login/guides/permissions/request-revoke#checking).

## Granular Permissions &#123;#granularpermissions&#125;

People can grant your app permissions for Pages and business assets they manage at the individual level. For example, someone who manages several Pages, may grant your app permission for only a particular Page or for only some of their Pages.

People choose which permissions they grant through a permission request flow. For example, if an app requests Page permissions, people receive a request to grant those permissions in the login dialog. If they don&#039;t grant all the requested permisions, they can manage what sorts of permissions they grant and the assets, such as permission to a specific Page if they manage many, the app can access with those permissions.

If someone initially grants only some of the requested permissions, they can later change which permissions they allow through the app settings page. However, if they update this to grant all permissions, they will no longer be able to use the app settings page to change the permissions they have granted.

People can manage the following permissions at the individual level:

* [All Page permissions](https://developers.facebook.com/docs/pages/overview#permissions)
* [`business_management` permission](https://developers.facebook.com/docs/facebook-login/permissions#reference-business_management)

## Expiration of Permissions &#123;#permission-expiration&#125;

If your app does not use a permission for 90 days, that permission may expire. This is true even if the permission was approved through app review.

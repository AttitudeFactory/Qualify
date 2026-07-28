# Testing a Login Flow



It’s important to test and verify that your Facebook Login flow works well under a variety of conditions. To test your Login flow, first create a separate Facebook user account:

1. Create a new test user account with Facebook
2. Log into Facebook with your test user credentials

## Common Test Cases

Before you test each use case below, make sure you remove your app from your test user&#039;s Facebook account using [app settings](https://www.facebook.com/settings?tab=applications).

#### 1. Someone new to your app logs in with Facebook
1. Go to your app and tap on the `Log in with Facebook` button
2. Tap OK to accept the read permissions
3. Click OK again to accept write permissions if applicable
4. Go to [app settings](https://www.facebook.com/settings?tab=applications) and verify that the granted permissions are there

#### 2. Someone logs in with Facebook after previously logging in via a non-Facebook flow with the same email address
1. Go to your app and login using your email address
2. Log out of your app and tap on the &quot;Log in with Facebook&quot; button
3. Tap OK to accept the read permissions (and OK again to accept write permissions where applicable)
4. Go to [app settings](https://www.facebook.com/settings?tab=applications) on Facebook and verify that the granted permissions are there

#### 3. Someone who has logged into your app with Facebook in the past logs back in
1. Go back to your app and tap on the “Log in with Facebook” button
2. Tap OK to accept the read permissions (and OK again to accept write permissions where applicable)
3. Uninstall then re-install your app
4. Open your app and tap on the “Log in with Facebook” button
5. Verify that you can log in without seeing any permission dialogs

#### 4. Someone cancels log in with Facebook and tries to log in again
1. Go to your app and tap on the &quot;Log in with Facebook” button
2. Verify that the read permissions are shown and tap “Cancel”
3. Open your app and tap on the &quot;Log in with Facebook” button
4. Verify that the read permissions are shown again

#### 5. Someone removes your app from Facebook via app settings and revisits your app. Your app should detect this and prompt the person to log back in.
1. Go to your app and tap on the &quot;Log in with Facebook” button
2. Tap OK to accept the read permissions (and OK again to accept write permissions where applicable)
3. Go to [app settings](https://www.facebook.com/settings?tab=applications) on Facebook and remove your app
4. Repeat steps 1-2 and verify that Facebook Login works

#### 6. Someone changes the Facebook password after logging in with Facebook to your app

In this case, your token will be invalid and you should notify users that their Facebook session has expired and ask them to log in again.

1. Change your Facebook password and select “Log me out of other devices”
2. Go to your app and tap on the &quot;Log in with Facebook” button
3. Tap OK to accept the read permissions (and OK again to accept write permissions where applicable)
4. Go to app settings on Facebook and verify that the granted permissions are there

#### 7. Someone disabled Facebook platform via app settings and logs in to your app

In this case, you should make sure your app detects the error so that it can notify users and redirect them to the non-iOS integrated version of Facebook Login.

1. Turn off platform for your test user via [app settings](https://www.facebook.com/settings?tab=applications)
2. Go to your app and tap on the &quot;Log in with Facebook” button
3. Tap OK to accept the read permissions (and OK again to accept write permissions where applicable)
4. Verify that platform is now turned on and the app is added to your test user profile with correct privacy

#### 8. Someone revisits your app when your app token has expired.
Please read our guide on [handling token expiration](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#extending)

#### 9. For games that want to sync their status across multiple devices, test your syncing state  
1. Login with Facebook on your app and play your app’s game until you reach a certain level X
2. Login with Facebook on a different device via the same or different operating systems, and test that level X remains

## Additional use cases that you should test on iOS

#### 1. Someone logs into your app when the Facebook app is installed and iOS Facebook integration is enabled
If someone clicks “Cancel” in response to your Facebook Login read permissions request, he / she will need to go into the iOS system settings to re-enable Login for your app.

In cases where people have previously denied Facebook permissions via iOS integrated login, your app should use conventional fast app switch login for future permissions requests. In terms of SDK calls, don&#039;t use FBSessionLoginBehaviorUseSystemAccountIfPresent as the FBSessionLoginBehavior in this case. See [FBSession](https://developers.facebook.com/docs/reference/ios/3.24/class/FBSessionTokenCachingStrategy) for versions 3.24 and older of the SDK and [FBSDKAccessToken currentAccessToken](https://developers.facebook.com/docs/reference/ios/current/class/FBSDKAccessToken) and [FBSDKLoginManager](https://developers.facebook.com/docs/reference/ios/current/class/FBSDKLoginManager) for newer versions.

#### 2. Someone logs into your app when the Facebook app is not installed and iOS Facebook integration is not enabled
1. Go to your app and tap on the &quot;Log in with Facebook” button
2. Verify that the mobile web Facebook Login screen appears and log in

3. Tap OK to accept the read permissions (and OK again to accept write permissions where applicable)
4. Go to [app settings](https://www.facebook.com/settings?tab=applications) on Facebook and verify that the granted permissions are there

#### 3. Someone logs in to your app when the Facebook app is not installed and iOS Facebook integration is enabled
1. Go to your app and tap on the &quot;Log in with Facebook” button
2. Tap OK to accept the read permissions (and OK again to accept write permissions where applicable)
3. Go to [app settings](https://www.facebook.com/settings?tab=applications) on Facebook and verify that the granted permissions are there

## Test Users

In your app settings (under &quot;Roles&quot;, i.e., `https://developers.facebook.com/apps/&#123;YOUR_APP_ID&#125;/roles/test-users/`), you can create [test user accounts](https://developers.facebook.com/docs/apps/test-users) to verify your Facebook integration without worrying about spamming.

In the iOS SDK, the class `FBSDKTestUsersManager` (in `FBSDKCoreKit`) can be used to easily fetch access tokens for those test users so that you can write automated integration tests. Note this class requires your app secret and you should ensure the app secret is not included in your released app.

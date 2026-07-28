# Tracking Access Tokens and Profiles in Facebook Login for Android



If you want your app to keep up with the current access token and profile, you can implement `AccessTokenTracker` and `ProfileTracker` classes.

These classes call your code when access token or profile changes happen.  Internally they use receivers, so you need to call `stopTracking()` on  an activity or  call a fragment&#039;s `onDestroy()` method.

## Track Access Tokens &#123;#track_token&#125;

For example to use the `AccessTokenTracker` instead of using a login callback:

```
&#064;Override
public void onCreate(Bundle savedInstanceState) &#123;
    super.onCreate(savedInstanceState);

    callbackManager = CallbackManager.Factory.create();

    accessTokenTracker = new AccessTokenTracker() &#123;
        &#064;Override
        protected void onCurrentAccessTokenChanged(
            AccessToken oldAccessToken,
            AccessToken currentAccessToken) &#123;
                // Set the access token using
                // currentAccessToken when it&#039;s loaded or set.
        &#125;
    &#125;;
    // If the access token is available already assign it.
    accessToken = AccessToken.getCurrentAccessToken();
&#125;

&#064;Override
protected void onActivityResult(int requestCode, int resultCode, Intent data) &#123;
    super.onActivityResult(requestCode, resultCode, data);
    callbackManager.onActivityResult(requestCode, resultCode, data);
&#125;

&#064;Override
public void onDestroy() &#123;
    super.onDestroy();
    accessTokenTracker.stopTracking();
&#125;
```

## Track Current Profile &#123;#track_profile&#125;

You can use `ProfileTracker` in a similar way to track changes in the current profile:

```
&#064;Override
public void onCreate(Bundle savedInstanceState) &#123;
    super.onCreate(savedInstanceState);

    callbackManager = CallbackManager.Factory.create();

    profileTracker = new ProfileTracker() &#123;
        &#064;Override
        protected void onCurrentProfileChanged(
                Profile oldProfile,
                Profile currentProfile) &#123;
            // App code
        &#125;
    &#125;;
&#125;

&#064;Override
protected void onActivityResult(int requestCode, int resultCode, Intent data) &#123;
    super.onActivityResult(requestCode, resultCode, data);
    callbackManager.onActivityResult(requestCode, resultCode, data);
&#125;

&#064;Override
public void onDestroy() &#123;
    super.onDestroy();
    profileTracker.stopTracking();
&#125;
```

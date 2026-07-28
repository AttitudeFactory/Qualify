# Troubleshoot



The following are commonly encountered problems and solutions for the Facebook Login for Android.

## I get a login dialog error.

I get the native login dialog permissions, but the person is not authenticated. The logcat exception error returned looks like:

```json
...W/fb4a:fb:OrcaServiceQueue(504): com.facebook.orca.protocol.base.ApiException:
   remote_app_id does not match stored id
```

or,

I see a non-native login dialog that includes an error that looks like:

```json
...App is Misconfigured for facebook login...
```

If you are having trouble with your login dialog, here are some things to try:

- If you don&#039;t have openssl, install it for [Windows](http://www.slproweb.com/products/Win32OpenSSL.html) or [MAC](http://www.openssl.org/source/).

- Be sure you have [signed your Android app](https://developer.android.com/studio/publish/app-signing).

## My key hash is invalid.

If you are having trouble with your key hash, here are some things to try:

- When you add a new key hash to the [App Dashboard](https://developers.facebook.com/apps) be sure to **Save Changes**.

- The password you entered is incorrect. The default Keystore password: &quot;android&quot;.

- Copy and paste the key hash you sent to Facebook to the [App Dashboard](https://developers.facebook.com/apps) and **Save Changes** and make this change to `onCreate()` in your main activity:

```
&#064;Override

public void onCreate(Bundle savedInstanceState) &#123;
     super.onCreate(savedInstanceState);

     try &#123;
         PackageInfo info = getPackageManager().getPackageInfo(
                           &quot;&#123;your-package-name&#125;&quot;,                  //Insert your own package name.
                            PackageManager.GET_SIGNATURES);
         for (Signature signature : info.signatures) &#123;
             MessageDigest md = MessageDigest.getInstance(&quot;SHA&quot;);
             md.update(signature.toByteArray());
             Log.d(&quot;KeyHash:&quot;, Base64.encodeToString(md.digest(), Base64.DEFAULT));
             &#125;
          &#125; catch (NameNotFoundException e) &#123;

          &#125; catch (NoSuchAlgorithmException e) &#123;

          &#125;
           ...
```

- [Generate a new key hash](https://developers.facebook.com/documentation/android/getting-started#create_hash)

## I get a Keytool error.

- If you get a `Command not found` error, add the path to your global `PATH` or go to the folder to run the following command:

On Windows:  `C:\Program Files (x86)\Java\jdk1.6.0\bin`

On MAC: `/usr/bin`

- If Keytool could not find your `debug.keystore` location. Check for the correct path. Keytool always ask for a password when it has the correct location.


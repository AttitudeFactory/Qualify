# Managing Permissions in Facebook Login for the Web



One of the most important parts of launching the Login Dialog is choosing what data your app would like access to.  These examples have all used the `scope` parameter, which is how you ask for access to someone&#039;s data.  These are all called *Permissions*.

Permissions are covered in depth in our [permissions guide](https://developers.facebook.com/docs/facebook-login/permissions).  However, there are a few things to remember when dealing with permissions and the login dialog:

* You ask for permissions when the dialog is created.  The resulting set of permissions is tied to the access token that&#039;s returned.
* Other platforms may have a different set of permissions.  For example, on iOS you can ask for places a person&#039;s been tagged, while in the web version of your app that permission is not required for the experience.
* You can add permissions later when you need more capabilities.  When you need a new permission, you simply add the permission you need to the list you&#039;ve already granted, re-launch the Login Dialog and it will ask for the new permission.
* The Login Dialog lets people **decline to share certain permissions with your app that you ask for.**  Your app should handle this case.  Learn more about this in our [permissions dialog](https://developers.facebook.com/docs/facebook-login/permissions#handling).
* Apps that ask for more information than the default fields and the `email` permission **must be reviewed by Facebook before they can be made available to the general public**.  Learn more in our documentation for [login review](https://developers.facebook.com/docs/apps/review/login) and our general [review guidelines](https://developers.facebook.com/docs/apps/review).

## Adding Permissions &#123;#re-launching-permissions-dialog&#125;

One of the [best practices with Facebook Login is to not request read permissions and publishing permissions at the same time](https://developers.facebook.com/documentation/facebook-login/best-practices#avoidbacktoback).  To support this your app can ask for more permissions later, well after someone has logged in.  To do that, all you have to do is launch the Login Dialog with the new permission that you&#039;re asking for.

For example, let&#039;s say you had a Login Button with the following permissions:

```
&lt;fb:login-button scope=&quot;public_profile&quot; onlogin=&quot;checkLoginState();&quot;&gt;
&lt;/fb:login-button&gt;
```

And if you checked `/me/permissions` for [permissions granted after the person accepted](https://developers.facebook.com/docs/facebook-login/permissions#checking) you would find this:

```
&#123;&quot;data&quot;:
  [
    &#123;
      &quot;permission&quot;:&quot;public_profile&quot;,
      &quot;status&quot;:&quot;granted&quot;
    &#125;
  ]
&#125;
```

If you wanted to add the `email` permission later, you could re-launch it with the `FB.login()` function like this:

```
FB.login(function(response) &#123;
   console.log(response);
&#125;, &#123;scope: &#039;email&#039;&#125;);
```

(This function must be called from a button&#039;s event handler otherwise it&#039;s likely to be blocked by browser popup blockers.)

Note that it only asks for the new permission.  If you accept the new permission checking `/me/permissions` will result in this:

```
&#123;&quot;data&quot;:
  [
    &#123;
      &quot;permission&quot;:&quot;public_profile&quot;,
      &quot;status&quot;:&quot;granted&quot;
    &#125;,
    &#123;
      &quot;permission&quot;:&quot;email&quot;,
      &quot;status&quot;:&quot;granted&quot;
    &#125;
  ]
&#125;
```

Note that the new `email` permission has been added to the list of allowed permissions.

## Re-asking for Declined Permissions &#123;#re-asking-declined-permissions&#125;

Facebook Login lets people decline sharing some permissions with your app. If someone were to declines `user_likes` (Likes), checking `/me/permissions` for what permissions have been granted results in:

```
&#123;
  &quot;data&quot;:
    [
      &#123;
        &quot;permission&quot;:&quot;public_profile&quot;,
        &quot;status&quot;:&quot;granted&quot;
      &#125;,
      &#123;
        &quot;permission&quot;:&quot;user_likes&quot;,
        &quot;status&quot;:&quot;declined&quot;
      &#125;
    ]
&#125;
```

Note that `user_likes` has been declined instead of granted.

It&#039;s OK to ask a person **once** to grant your app permissions that they&#039;ve declined.  You should have a screen of education on why you think they should grant the permission to you and then re-ask.  But if you use the method described in the [previous section](#re-launching-permissions-dialog), the Login Dialog won&#039;t ask for that permission.

**This is because once someone has declined a permission, the Login Dialog will not re-ask them for it unless you explicitly tell the dialog you&#039;re re-asking for a declined permission.**

You do this by adding the `auth_type: rerequest` flag to your `FB.login()` call:

```
FB.login(
  function(response) &#123;
    console.log(response);
  &#125;,
  &#123;
    scope: &#039;user_likes&#039;,
    auth_type: &#039;rerequest&#039;
  &#125;
);
```

When you do that, the Login Dialog will re-ask for the declined permission.  The dialog will look very much like the dialog in the section on re-asking for permissions but will let you re-ask for a declined permission.

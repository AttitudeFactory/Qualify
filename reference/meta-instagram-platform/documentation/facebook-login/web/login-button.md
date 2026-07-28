# Login Button



The Login button is a simple way to trigger the [Facebook Login process](https://developers.facebook.com/documentation/facebook-login/web) on your website or web app.

If someone hasn&#039;t logged into your app yet, they&#039;ll see this button, and clicking it will open a Login dialog, starting the [login flow](https://developers.facebook.com/documentation/facebook-login/web). People who have already logged in won&#039;t see any button, or you can also choose to show a logout button to them.

If you show a logout button, when people use it to log out, they log out both from your app and from Facebook.

The Login button is only designed to work in connection with the [JavaScript SDK](https://developers.facebook.com/documentation/facebook-login/web) — if you&#039;re building a mobile app or can&#039;t use our JavaScript SDK, you should follow the [login flow guide for that type of app](https://developers.facebook.com/documentation/facebook-login) instead.

The **Continue with Facebook** button replaces earlier versions of the Login button. For more information, see [Migration](#migration).

## Settings &#123;#settings&#125;

In addition to the settings above, you can also change the following:

| Setting | HTML5 Attribute | Description | Options |
| --- | --- | --- | --- |
| `auto_logout_link` | `data-auto-logout-link` | If enabled, the button will change to a logout button when the user is logged in. | **`false`**, `true` |
| `onlogin` | `data-onlogin` | A JavaScript function to trigger when the login process is complete. | `Function` |
| `scope` | `data-scope` | The list of permissions to request during login. | **`public_profile`** (default) or a [comma separated list of permissions](https://developers.facebook.com/docs/facebook-login/permissions) |
| `size` | `data-size` | Picks one of the size options for the button. | **`small`**, `medium`, `large` |
| `default_audience` | `data-default-audience` | Determines what audience will be selected by default, when requesting write permissions. | `everyone`, **`friends`**, `only_me` |

## FAQs &#123;#faq&#125;

#### How do I use this to log users in? &#123;#loginfaq&#125;

Once someone has clicked the Login button, and accepted the login dialog — completing the [Login flow](https://developers.facebook.com/documentation/facebook-login/web) — your app can now use the [Facebook SDK for JavaScript](https://developers.facebook.com/docs/javascript) to make API calls on behalf of that person.

There is no extra setup required here, however you can use the `onlogin` setting in the button to trigger your own JavaScript function that will run upon login.

#### Can I use the Login button with server-side registration code? &#123;#loginserversidefaq&#125;

You can, however you will still need to use the JavaScript SDK partially. Once the login process started by clicking on the button is done, the SDK will have access to an `authResponse` object using [`FB.getLoginStatus()`](https://developers.facebook.com/docs/reference/javascript/FB.getLoginStatus). You can use this function to pass the response object to your server-side code to complete any registration that exists there.

#### Can I use the Login button to re-request a permission that a person has declined? &#123;#login-button-rerequest&#125;

The Login button doesn&#039;t support re-requests because asking for declined permissions doesn&#039;t fit the verbage on the button.  If you need to re-request a permission, set up a custom button and [use `FB.login()` as described in the Facebook Login for the Web](https://developers.facebook.com/documentation/facebook-login/web#re-asking-declined-permissions) documentation.

#### The button isn&#039;t rendering.

The `&lt;div&gt;` tags are transformed into rendered buttons using a technology we call XFBML, which relies on JavaScript in the SDK to parse the page and make replacements.  If you are dynamically modifying page content to add these `div`s after the SDK `init` method has run, (e.g. in a dynamically constructed dialog) you need to call [FB.XFBML.parse()](https://developers.facebook.com/docs/reference/javascript/FB.XFBML.parse) again in order for the transformation to be effected.

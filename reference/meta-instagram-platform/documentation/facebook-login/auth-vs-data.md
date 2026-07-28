# Authentication Versus Data Access



Facebook Login provides two major benefits: authentication and data access. These are not mutually exclusive. You can use Facebook Login to authenticate people without planning to access their data. In that case, you do not need to ask for [permissions](https://developers.facebook.com/documentation/facebook-login/guides/permissions) or put your app through [app review](https://developers.facebook.com/docs/facebook-login/review).

Authentication and data access each last for a finite period. However, the expiration periods for authentication and data access are different and depend on different factors.

## Authentication &#123;#authentication&#125;

Authentication enables people to log in to your mobile or web app and create an account by using their Facebook credentials. They do not need to create or remember a separate password.

### Authentication Expiration

When your app uses Facebook Login to authenticate someone, it receives a User [access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens). If your app uses one of the Facebook SDKs, this token lasts for about 60 days. However, the SDKs automatically refresh the token whenever the person uses your app, so the tokens expire 60 days after last use. If your app doesn&#039;t use the Facebook SDKs, you need to include code that refreshes the User token manually. If the User access token expires, your app must put the user through the login flow again.

## Data Access &#123;#data-access&#125;

Facebook Login also enables you to ask for [permissions](https://developers.facebook.com/documentation/facebook-login/guides/permissions) when people log in to your app. These permissions, if granted by the user, give your app access to items of user data. For example, your app can access a user&#039;s name and profile photo.

If an app asks for permissions, it is often necessary to put the app through [app review](https://developers.facebook.com/docs/facebook-login/review) so that Facebook can make sure that data is not misused. Your app can ask for people&#039;s name and photo (the [default profile fields](https://developers.facebook.com/docs/facebook-login/permissions#reference-default)) and for [email](https://developers.facebook.com/docs/facebook-login/permissions#reference-email) without going through app review, but all other permissions require review. For lists of permissions and which ones require app review, see [Permissions Reference](https://developers.facebook.com/docs/facebook-login/permissions).

### Data Access Expiration &#123;#data-access-expiration&#125;

The expiration period for data access is 90 days, based on when the user was last active. When this 90-day period expires, the user can still access your app — that is, they are still authenticated — but your app can&#039;t access their data. To regain data access, your app must ask the user to re-authorize your app&#039;s permissions.

To ask for re-authorization with the Facebook SDK for Android or the Facebook SDK for iOS, call `reauthorizeDataAccess()` on the `LoginManager`.

With the Facebook SDK for JavaScript, use `auth_type: &#039;reauthorize&#039;`.

```
FB.login(function(response) &#123;
  // Original FB.login code
&#125;, &#123; auth_type: &#039;reauthorize&#039; &#125;)
```

For the web, make the call with `auth_type=reauthorize`.

The following permissions do not expire:

* `ads_read`
* `ads_management`
* `business_management`
* `configure_page_transactions`
* `pages_manage_ads `
* `pages_manage_cta`
* `pages_manage_instant_articles`

* `pages_manage_engagement`
* `pages_manage_metadata `
* `pages_manage_posts `
* `pages_messaging`
* `pages_read_engagement `
* `pages_read_user_content `
* `pages_show_list`
* `read_audience_network_insights`
* `read_insights`

### Testing When Access to User Data Expires

With the Android and iOS SDKs, you can retrieve when your app&#039;s access to user data will expire by calling `dataAccessExpirationTime` on the access token object. This method returns a date specifying when data access will expire.

You can also test whether access to user data has expired by calling `isDataAccessExpired`, which returns a Boolean.

Server side, you can retrieve this information from the [`debug_token` endpoint](https://developers.facebook.com/docs/graph-api/reference/debug_token).

On the web, you can see the expiration time in the `payload: data_access_expiration_time`.

```
&#123;
  status: &#039;connected&#039;,
  authResponse: &#123;
    accessToken: &#039;...&#039;,
    expiresIn:&#039;...&#039;,
    reauthorize_required_in:&#039;...&#039;,
    data_access_expiration_time: &#039;...&#039;,
    signedRequest:&#039;...&#039;,
    userID:&#039;...&#039;
  &#125;
&#125;
```

### Permission Expiration &#123;#permission-expiration&#125;

Regardless of when the user was last active, if your app does not use a permission for 90 days, that permission may expire. This is true even if the permission was approved through app review.

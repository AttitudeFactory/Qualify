# Oauth Authorize



This endpoint returns the Authorization Window, which app users use to authenticate their identity and grant your app permissions and Instagram User Access Tokens.

## Creating

This operation is not supported.

## Reading

**`GET /oauth/authorize`**

Get the Authorization Window.

### Requirements

None.

### Request Syntax

```html
GET https://api.instagram.com/oauth/authorize
  ?client_id=<APP_ID>,
  &redirect_uri=<REDIRECT_URI>,
  &response_type=code,
  &scope=<PERMISSIONS_APP_NEEDS>
```

### Query String Parameters

Augment the request with the following query parameters.

| Key | Sample Value | Description |
| --- | --- | --- |
| `client_id`  <br>**Required**  <br>*Numeric string* | `990602627938098` | Your Instagram App ID displayed in the **Meta App Dashboard** |
| `redirect_uri`  <br>**Required**  <br>*String* | `https://socialsizzle.herokuapp.com/auth/` | A URI where we will redirect users after they authenticate. Make sure this exactly matches one of the base URIs in your list of valid oAuth URIs. Keep in mind that the App Dashboard may have added a trailing slash to your URIs, so we recommend that you verify by checking the list. |
| `response_type`  <br>**Required**  <br>*String* | `code` | Set this value to `code`. |
| `scope`  <br>**Required**  <br>*Comma-separated list* | `instagram_basic` or `instagram_business_basic` | A comma-separated list, or URL-encoded space-separated list, of permissions to request from the app user. `instagram_basic` or `instagram_business_basic` is required. |
| `state`  <br>*String* | `1` | An optional value indicating a server-specific state. For example, you can use this to protect against CSRF issues. We will include this parameter and value when redirecting the user back to you. |

### Response

The Authorization Window, which you should display to the app user. Once the user authenticates, the window will redirect to your `redirect_uri` and include an Authentication Code, which you can then exchange for a short-lived Instagram User Access Token.

Note that we `#_` append to the end of the redirect URI, but it is not part of the code itself, so strip it out before exchanging it for a short-lived token.

### HTTP Example

```json
https://api.instagram.com/oauth/authorize
  ?client_id=990602627938098
  &redirect_uri=https://socialsizzle.herokuapp.com/auth/
  &scope=instagram_business_basic
  &response_type=code
```

### Successful Authorization

If authentication is successful, the Authorization Window will redirect the user to your `redirect_uri` and include an Authorization Code. Capture the code so you can exchange it for a short-lived access token.

Codes are valid for 1 hour and can only be used once.

#### Sample Successful Authorization Redirect

```
https://socialsizzle.herokuapp.com/auth?code=AQBx-hBsH3...
```

### Canceled Authorization

If the user cancels the authorization flow, we will redirect the user to your `redirect_uri` and append the following error parameters. *It is your responsibility to fail gracefully in these situations and display an appropriate message to your users*.

| Parameter | Value |
| --- | --- |
| `error` | `access_denied` |
| `error_reason` | `user_denied` |
| `error_description` | `The+user+denied+your+request` |

#### Sample Canceled Authentication Redirect

```
https://socialsizzle.herokuapp.com/auth/
  ?error=access_denied
  &error_reason=user_denied
  &error_description=The+user+denied+your+request
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

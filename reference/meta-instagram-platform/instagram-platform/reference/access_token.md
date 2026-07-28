# Access Token



The `/access_token` endpoint allows you to exchange short-lived Instagram User Access Tokens, those that expire in one hour, for long-lived Instagram User access Tokens that expire in 60 days.

## Creating

This operation is not supported.

## Reading

**`GET /access_token`**

Exchange a short-lived Instagram User access token, that expires in one hour, for long-lived Instagram User access token that expires in 60 days.

### Limitations

Requests for long-lived tokens include your app secret so should only be made in server-side code, never in client-side code or in an app binary that could be decompiled. Do not share your app secret with anyone, expose it in code, send it to a client, or store it in a device.

### Requirements

#### Access tokens

* An Instagram User access token requested from a person who can send a message from the Instagram professional account

#### Base URL
All endpoints can be accessed via the graph.instagram.com host.

#### Endpoints

* `/access_token`

#### Required Parameters

The following table contains the required parameters for each API request.

| Key | Value |
| --- | --- |
| `client_secret`  <br>**Required**  <br>*String* | Your Instagram app's secret from the App Dashboard |
| `grant_type`  <br>**Required**  <br>*String* | Set this to `ig_exchange_token` |
| `access_token`  <br>**Required**  <br>*String* | The valid (unexpired) short-lived Instagram User Access Token that you want to exchange for a long-lived token. |

#### Permissions

* `instagram_basic` for apps that implemented Facebook Login for Business
* `instagram_business_basic` for apps that implemented Business Login for Instagram

### Request Syntax

_Formatted for readability._

```
GET https://graph.instagram.com/access_token
  ?grant_type=ig_exchange_token
  &client_secret=<INSTAGRAM_APP_SECRET>
  &access_token=<VALID_SHORT_LIVED_ACCESS_TOKEN>
```

### Response

Upon success, your app receives a JSON-formatted object containing the following:

* `access_token` set to the new, long-lived Instagram User access token; _numeric string_
* `token_type` set to `bearer`; _string_
* `expires_in` set to the number of seconds until the token expires; _integer_

### cURL Example

#### Request

```curl
curl -X GET "https://graph.instagram.com/access_token?grant_type=ig_exchange_token&&client_secret=eb87G...&access_token=IGQVJ..."
```

#### Response

```json
{
  "access_token": "lZAfb2dhVW...",
  "token_type": "bearer",
  "expires_in": 5184000
}
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

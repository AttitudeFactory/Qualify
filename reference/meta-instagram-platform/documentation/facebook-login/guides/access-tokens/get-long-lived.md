# Long-Lived Access Tokens



Default User and Page access tokens are short-lived, expiring in hours, however, you can exchange a short-lived token for a long-lived token.

When you use the iOS, Android, or JavaScript SDK, the SDK will automatically refresh tokens if the person has used your app within the last 90 days. Native mobile apps using Facebook&#039;s SDKs get long-lived User access tokens, good for about 60 days.  These tokens are refreshed once per day, when the person using your app makes a request to Facebook&#039;s servers.  If no requests are made, the token will expire after about 60 days and the person will have to go through the login flow again to get a new token.

Latest Graph API Version: v25.0

## Get a Long-Lived User Access Token

If you need a long-lived User access token you can generate one from a short-lived User access token. A long-lived token generally lasts about 60 days.  

You will need the following:

* A valid User Access Token
* Your App ID
* Your App Secret

Query the `GET oauth/access_token` endpoint.

```
curl -i -X GET &quot;https://graph.facebook.com/&#123;graph-api-version&#125;/oauth/access_token?
    grant_type=fb_exchange_token&amp;
    client_id=&#123;app-id&#125;&amp;
    client_secret=&#123;app-secret&#125;&amp;
    fb_exchange_token=&#123;your-access-token&#125;&quot;
```

#### Sample Response

```json
&#123;
  &quot;access_token&quot;:&quot;&#123;long-lived-user-access-token&#125;&quot;,
  &quot;token_type&quot;: &quot;bearer&quot;,
  &quot;expires_in&quot;: 5183944            //The number of seconds until the token expires
&#125;
```

The workflow for generating a long-lived User access token is as follows:

Once you have retrieved the long-lived token, you can use it from your server or send it back to the client to use there.

#### Caveats

* **You can not use an expired token to request a long-lived token.** If the token has expired, your app must send the user through the login flow again to regenerate a new short-lived access token.

* **Make this call from your server, not a client.**  Your app secret is included in this API call, so you should never make the request client-side. Instead implement server-side code that makes the request, then pass the response containing the long-lived token back to your client-side code. This will be a different string than the original token, so if you&#039;re storing these tokens, replace the old one.

* **Do not use the same long-lived tokens on more than one web client** (i.e. if the person logs in from more than one computer).  Instead, you should use the long-lived tokens on your server to generate a code and then use that to get a long-lived token on the client.  Please see below for information [Generating long-lived tokens from server-side long-lived tokens](#long-via-code).

## Get a Long-Lived Page Access Token &#123;#long-lived-page-token&#125;

If you need a long-lived Page access token, you can generate one from a long-lived User access token. Long-lived Page access token do not have an expiration date and only [expire or are invalidated under certain conditions](https://developers.facebook.com/docs/facebook-login/access-tokens/debugging-and-error-handling#expiredtokens).

You will need the following:

* A valid [long-lived User access token](#get-a-long-lived-user-access-token). The person requesting the token must have a role on the Page.

Query the `GET &#123;app-scoped-user-id&#125;?accounts` endpoint.

```
curl -i -X GET &quot;https://graph.facebook.com/&#123;graph-api-version&#125;/&#123;app-scoped-user-id&#125;/accounts?
  access_token=&#123;long-lived-user-access-token&#125;&quot;
```

#### Sample Response

```json
&#123;
  &quot;data&quot;:[
    &#123;
      &quot;access_token&quot;:&quot;&#123;long-lived-page-access-token&#125;&quot;,
      &quot;category&quot;:&quot;Brand&quot;,
      &quot;category_list&quot;:[
        &#123;
          &quot;id&quot;:&quot;1605186416478696&quot;,
          &quot;name&quot;:&quot;Brand&quot;
        &#125;
      ],
      &quot;name&quot;:&quot;Cute Kitten Page&quot;,
      &quot;id&quot;:&quot;&#123;page-id&#125;&quot;,
      &quot;tasks&quot;:[
        &quot;ANALYZE&quot;,
        &quot;ADVERTISE&quot;,
        &quot;MODERATE&quot;,
        &quot;CREATE_CONTENT&quot;,
        &quot;MANAGE&quot;
      ]
    &#125;
  ],
  &quot;paging&quot;:&#123;
    &quot;cursors&quot;:&#123;
      &quot;before&quot;:&quot;MTM1MzI2OTg2NDcyODg3OQZDZD&quot;,
      &quot;after&quot;:&quot;MTM1MzI2OTg2NDcyODg3OQZDZD&quot;
    &#125;
  &#125;
&#125;
```

## Get Long_lived Tokens for Clients &#123;#long-via-code&#125;

Facebook has an option for getting long-lived access tokens for apps to avoid triggering Facebook&#039;s automated spam systems. Apps that:

* Have their own authentication system (use a username/password for example)
* Store a Facebook access token on their servers for people using different clients (browser or native mobile apps)
* Make API calls from all these different clients

At a high level, you obtain a long-lived token for the client by:

1. Using a valid, long-lived access token, your server sends a request to get a code from Facebook.
2. Facebook sends a code back to your server and you securely send this code to the client.
3. The client uses this code to request a long-lived token from Facebook.
4. Facebook sends the client a long-lived token which is used to post stories or query data.

### Get a Code

Query the `GET oauth/client_code` endpoint. The redirect URI must be the exact value you set in your [app dashboard](https://developers.facebook.com/apps) under the **Facebook Login &gt; Settings Client &gt; OAuth Settings** card.

```
curl -i -X GET &quot;https://graph.facebook.com/&#123;graph-api-version&#125;/oauth/client_code?
    client_id=&#123;app-id&#125;&amp;
    client_secret=&#123;app-secret&#125;&amp;
    redirect_uri=&#123;app-redirect-uri&#125;&amp;
    access_token=&#123;long-lived-user-access-token&#125;&quot;
```

#### Sample Response

```json
&#123;
  &quot;code&quot;:&quot;&#123;code-for-your-client&#125;&quot;
&#125;
```

### Redeem the Code for a Long-lived Access Token

Once you&#039;ve retrieved the code from Facebook&#039;s server you then need to ship it to the client via a secure channel.  Once that&#039;s done, you need to make a request from the client to the `/oauth/access_token` endpoint:

```
curl -i -X GET &quot;https://graph.facebook.com/&#123;graph-api-version&#125;/oauth/access_token?
    code=&#123;code-for-your-client&#125;&amp;
    client_id=&#123;app-id&#125;&amp;
    redirect_uri=&#123;app-redirect-uri&#125;&amp;
    machine_id= &#123;your-client-machine-id&#125;&quot;
```

The `machine_id` is an optional parameter that identifies and tracks clients and is used for security and spam prevention. It is a **per client** not **per user** value. If you have previously made calls to get a code and been provided a `machine_id` you should include in your code request.

#### Sample Response

```
&#123;
  &quot;access_token&quot;:&quot;&#123;long-lived-access-token&#125;&quot;,
  &quot;expires_in&quot;:5183944,           //The number of seconds until the token expires
  &quot;machine_id&quot;:&quot;&#123;your-client-machine-id&#125;&quot;
&#125;
```

The workflow for generating a long-lived token is as follows:


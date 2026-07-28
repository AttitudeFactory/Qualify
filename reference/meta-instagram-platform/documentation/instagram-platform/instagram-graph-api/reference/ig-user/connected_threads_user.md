# IG User Connected Threads User



Represents a [Threads account connected to an Instagram account](https://developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/threads-ads#instagram-connected-threads-accounts).

### Requirements

| Type | Description |
| --- | --- |
| [Permissions](https://developers.facebook.com/docs/apps/review/login-permissions) | * [`instagram_basic`](https://developers.facebook.com/docs/facebook-login/permissions#instagram_basic)&lt;br&gt;* [`threads_business_basic`](https://developers.facebook.com/docs/facebook-login/permissions#threads_business_basic)&lt;br&gt;* [`pages_read_engagement`](https://developers.facebook.com/docs/permissions#pages_read_engagement)&lt;br&gt;&lt;br&gt;If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to your app user&#039;s Instagram professional account, your app will also need one of:&lt;br&gt;&lt;br&gt;* [`ads_management`](https://developers.facebook.com/docs/facebook-login/permissions#ads_management)&lt;br&gt;* [`ads_read`](https://developers.facebook.com/docs/facebook-login/permissions#ads_read) |
| [Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens) | A Facebook User [access token](https://developers.facebook.com/documentation/instagram-platform/overview#authentication). |

### Limitations

* You need to have at least an Advertiser role on the [Page that is linked to your Instagram account](https://developers.facebook.com/documentation/ads-commerce/instagram/ads-api/guides/pages-ig-account#via_page); Manager or Content Creator also work. Or you need to have the Instagram account [connected to a business account](https://developers.facebook.com/documentation/ads-commerce/instagram/ads-api/guides/ig-accounts-with-business-manager#claim_account) where you have appropriate roles.
* If you want to use this Threads account ID for Threads ads creation, make sure your connected Instagram account has the correct ads creation identity setup, either [business-claimed Instagram account](https://developers.facebook.com/documentation/ads-commerce/instagram/ads-api/guides/ig-accounts-with-business-manager) or [page-connected Instagram account](https://developers.facebook.com/documentation/ads-commerce/instagram/ads-api/guides/pages-ig-account).
* An Instagram account can have only one Instagram-connected Threads account. [Verify whether a specific Instagram account has an Instagram-connected Threads account](#reading) before attempting to create a new one. If one already exists, use that one.

## Reading

`GET /&#123;ig-user-id&#125;/connected_threads_user`

Once you [connect a Threads account to a valid Instagram account](https://help.instagram.com/1747515265645443), you can make an API request to get the Threads account ID.

### Sample request

```html
curl -G \
  -d &quot;access_token=&lt;ACCESS_TOKEN&gt;&quot;\
  -d &quot;fields=threads_user_id&quot; \
&quot;https://graph.facebook.com/v25.0/&lt;IG_USER_ID&gt;/connected_threads_user&quot;
```

### Sample response

```html
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;threads_user_id&quot;: &quot;&lt;THREADS_USER_ID&gt;&quot;,
    &#125;
  ],
&#125;
```

## Creating

This operation is not supported.

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

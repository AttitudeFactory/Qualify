# Page



Represents a Facebook Page.

This node allows you to:

- get the [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) connected to a Facebook Page.

Available via Facebook Login for Business only.

## Creating &#123;#create&#125;

This operation is not supported.

## Reading &#123;#read&#125;

### Getting a Page&#039;s IG User

`GET /&lt;PAGE_ID&gt;?fields=instagram_business_account`

Returns the [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) connected to the Facebook Page.

#### Permissions

A Facebook User [access token](https://developers.facebook.com/documentation/instagram-platform/overview#authentication) with the following permissions:

- `instagram_basic`
- `pages_show_list`

If the token is from a User whose **Page role was granted via the Business Manager**, one of the following permissions is also required:

- `ads_management`
- `ads_read`

#### Sample Request

```
GET graph.facebook.com
  /134895793791914?fields=instagram_business_account
```

#### Sample Response

```
&#123;
  &quot;instagram_business_account&quot;: &#123;
    &quot;id&quot;: &quot;17841405822304914&quot;
  &#125;,
  &quot;id&quot;: &quot;134895793791914&quot;
&#125;
```

## Updating &#123;#update&#125;

This operation is not supported.

## Deleting &#123;#delete&#125;

This operation is not supported.

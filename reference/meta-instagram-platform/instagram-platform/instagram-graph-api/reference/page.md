# Page



Represents a Facebook Page.

This node allows you to:

- get the [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) connected to a Facebook Page.

Available via Facebook Login for Business only.

## Creating {#create}

This operation is not supported.

## Reading {#read}

### Getting a Page's IG User

`GET /<PAGE_ID>?fields=instagram_business_account`

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
{
  "instagram_business_account": {
    "id": "17841405822304914"
  },
  "id": "134895793791914"
}
```

## Updating {#update}

This operation is not supported.

## Deleting {#delete}

This operation is not supported.

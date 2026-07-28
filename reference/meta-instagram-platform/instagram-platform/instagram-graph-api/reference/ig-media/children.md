# Children



Represents a collection of [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects on an album [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media).

### Requirements

|  | Instagram AP with Instagram Loging | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User user access token | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic` | * `instagram_basic`<br>* `pages_read_engagement`<br><br>If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need one of:<br><br>* `ads_management`<br>* `ads_read` |

## Creating {#create}

This operation is not supported.

## Reading {#read}

### Getting Child Media Objects {#children}

`GET /<IG_MEDIA_ID>/children`

Returns a list of [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects on an album [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object.

#### Limitations

- Some fields, such as `permalink`, cannot be used on photos within albums (children).

#### Sample Request

```
GET graph.facebook.com
  /17896450804038745/children
```

#### Sample Response

```
{
  "data": [
    {
      "id": "17880997618081620"
    },
    {
      "id": "17871527143187462"
    }
  ]
}
```

## Updating {#update}

This operation is not supported.

## Deleting {#delete}

This operation is not supported.

# Children



Represents a collection of [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects on an album [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media).

### Requirements

|  | Instagram AP with Instagram Loging | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User user access token | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic` | * `instagram_basic`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;&lt;br&gt;If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need one of:&lt;br&gt;&lt;br&gt;* `ads_management`&lt;br&gt;* `ads_read` |

## Creating &#123;#create&#125;

This operation is not supported.

## Reading &#123;#read&#125;

### Getting Child Media Objects &#123;#children&#125;

`GET /&lt;IG_MEDIA_ID&gt;/children`

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
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;id&quot;: &quot;17880997618081620&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17871527143187462&quot;
    &#125;
  ]
&#125;
```

## Updating &#123;#update&#125;

This operation is not supported.

## Deleting &#123;#delete&#125;

This operation is not supported.

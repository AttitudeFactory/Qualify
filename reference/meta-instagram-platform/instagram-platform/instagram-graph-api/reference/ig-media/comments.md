# Comments



Represents a collection of [IG Comments](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) on an [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object.

### Non-Organic Comments {#non-organic-comments}

Comments on Ads containing IG Media (i.e. non-organic comments) are of a different type and are not supported. To get non-organic comments, use the [Marketing API](https://developers.facebook.com/documentation/ads-commerce/marketing-api) and request the Ad's `effective_instagram_media_id`. You can then query the returned ID's `/comments` edge to get a collection of non-organic [Instagram Comments](https://developers.facebook.com/docs/graph-api/reference/instagram-comment). Refer to the Marketing API's [Post Moderation](https://developers.facebook.com/documentation/ads-commerce/instagram/ads-api/guides/post-moderation) guide for more information.

### Requirements

|  | Instagram API with Instagram Login | Instagram API with Facebook Login |
| --- | --- | --- |
| **Access Tokens** | * Instagram User access token | * [Facebook User access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens#usertokens) |
| **Host URL** | `graph.instagram.com` | `graph.facebook.com` |
| **Login Type** | Business Login for Instagram | Facebook Login for Business |
| [**Permissions**](https://developers.facebook.com/docs/permissions/reference#i) | * `instagram_business_basic`<br>* `instagram_business_manage_comments` | * `instagram_basic`<br>* `instagram_manage_comments`<br>* `pages_read_engagement`<br><br>If the app user was granted a role via the Business Manager on the [Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the targeted IG User, you will also need one of:<br><br>* `ads_management`<br>* `ads_read` |

## Creating

### Creating a Comment on a Media Object

`POST /<IG_MEDIA_ID>/comments?message=<MESSAGE_CONTENT>`

Creates an [IG Comment](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) on an [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object.

#### Limitations

Comments on live video IG Media are not supported.

#### Query String Parameters

Query string parameters are optional unless indicated as required.

- `<MESSAGE_CONTENT>` (required) — The text to be included in the comment.

#### Example Request

```
POST graph.facebook.com
  /17895695668004550/comments?message=This%20is%20awesome!
```

#### Example Response

```
{
  "id": "17870913679156914"
}
```

## Reading

### Getting Comments on a Media Object {#comments}

`GET /<IG_MEDIA_ID>/comments`

Returns a list of [IG Comments](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) on an [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object.

#### Limitations

- Requests made using API version 3.1 or older will have results returned in chronological order. Requests made using version 3.2+ will have results returned in reverse chronological order.  
- Returns only top-level comments. Replies to comments are not included unless you use field expansion to request the `replies` field.
- Returns a maximum of 50 comments per query.
- Comments cannot be filtered by timestamp.

#### Permissions

An [access token](https://developers.facebook.com/documentation/instagram-platform/overview#authentication) from a User who created the [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object, with the following permissions:

- `instagram_basic`
- `instagram_manage_comments`

If the token is from a User whose **Page role was granted via the Business Manager**, one of the following permissions is also required:

- `ads_management`
- `ads_read`

#### Sample Request

```
GET graph.facebook.com
  /17895695668004550/comments
```

#### Sample Response

```
{
  "data": [
    {
      "timestamp": "2017-08-31T19:16:02+0000",
      "text": "This is awesome!",
      "id": "17870913679156914"
    },
    {
      "timestamp": "2017-08-31T18:10:30+0000",
      "text": "*Sniff*",
      "id": "17873440459141021"
    }
  ]
}
```

## Updating

This operation is not supported.

## Deleting

This operation is not supported.

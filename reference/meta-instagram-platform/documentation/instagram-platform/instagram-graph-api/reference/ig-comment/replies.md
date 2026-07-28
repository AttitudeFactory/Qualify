# IG Comment Replies



Represents a collection of [IG Comments](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) on an [IG Comment](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment).

To create an [IG Comment](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) on an [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object, use the [`POST /&#123;ig-media-id&#125;/comments`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-media/comments) endpoint instead.

## Creating &#123;#create&#125;

### Replying to a Comment &#123;#replying&#125;

`POST /&#123;ig-comment-id&#125;/replies?message=&#123;message&#125;`

Creates an [IG Comment](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) on an [IG Comment](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment).

#### Query String Parameters

Query string parameters are optional unless indicated as required.

- `&#123;message&#125;` (required) — The text to be included in the comment.

#### Limitations

- You can only reply to top-level comments; replies to a reply will be added to the top-level comment.  
- You cannot reply to hidden comments.
- You cannot reply to comments on a live video; use the [Instagram Messaging API](https://developers.facebook.com/documentation/business-messaging/instagram-messaging) to send a [private reply](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/private-replies) instead.

#### Permissions

A User [access token](https://developers.facebook.com/documentation/instagram-platform/overview#authentication) from a User who created the comment, with the following permissions:

- `instagram_basic`
- `instagram_manage_comments`
- `pages_show_list`
- `page_read_engagement`

If the token is from a User whose **Page role was granted via the Business Manager**, one of the following permissions is also required:

- `ads_management`
- `ads_read`

#### Sample Request

```
POST graph.facebook.com
  /17870913679156914/replies?message=*sniff*
```

#### Sample Response

```
&#123;
  &quot;id&quot;: &quot;17873440459141021&quot;
&#125;
```

## Reading &#123;#read&#125;

### Getting All Replies (Comments) on a Comment &#123;#replies&#125;

`GET /&#123;ig-comment-id&#125;/replies`

Returns a list of [IG Comments](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) on an [IG Comment](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment).

#### Limitations

You cannot get replies to a comment that has been deleted.

#### Permissions

An [access token](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens) from a User who created the comment, with the following permissions:

- `instagram_basic`
- `pages_show_list`
- `page_read_engagement`

If the token is from a User whose **Page role was granted via the Business Manager**, one of the following permissions is also required:

- `ads_management`
- `ads_read`

#### Sample Request

```
GET graph.facebook.com
  /17873440459141021/replies
```

#### Sample Response

```
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;timestamp&quot;: &quot;2017-08-31T16:53:49+0000&quot;,
      &quot;text&quot;: &quot;This is a great comment&quot;,
      &quot;id&quot;: &quot;17871618799146774&quot;
    &#125;,
    &#123;
      &quot;timestamp&quot;: &quot;2017-08-30T04:24:45+0000&quot;,
      &quot;text&quot;: &quot;It&#039;s me. Trust me.&quot;,
      &quot;id&quot;: &quot;17887288333072596&quot;
    &#125;
  ]
&#125;
```

## Updating &#123;#update&#125;

This operation is not supported.

## Deleting &#123;#delete&#125;

This operation is not supported.

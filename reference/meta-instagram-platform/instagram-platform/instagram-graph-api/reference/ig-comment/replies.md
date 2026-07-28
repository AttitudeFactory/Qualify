# IG Comment Replies



Represents a collection of [IG Comments](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) on an [IG Comment](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment).

To create an [IG Comment](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) on an [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) object, use the [`POST /{ig-media-id}/comments`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-media/comments) endpoint instead.

## Creating {#create}

### Replying to a Comment {#replying}

`POST /{ig-comment-id}/replies?message={message}`

Creates an [IG Comment](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment) on an [IG Comment](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-comment).

#### Query String Parameters

Query string parameters are optional unless indicated as required.

- `{message}` (required) — The text to be included in the comment.

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
{
  "id": "17873440459141021"
}
```

## Reading {#read}

### Getting All Replies (Comments) on a Comment {#replies}

`GET /{ig-comment-id}/replies`

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
{
  "data": [
    {
      "timestamp": "2017-08-31T16:53:49+0000",
      "text": "This is a great comment",
      "id": "17871618799146774"
    },
    {
      "timestamp": "2017-08-30T04:24:45+0000",
      "text": "It's me. Trust me.",
      "id": "17887288333072596"
    }
  ]
}
```

## Updating {#update}

This operation is not supported.

## Deleting {#delete}

This operation is not supported.

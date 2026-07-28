# Mentions



Identify captions, comments, and IG Media in which an Instagram Business or Creator's alias has been tagged or @mentioned.

## Limitations

- Mentions on Stories are not supported.
- Commenting on photos in which you were tagged is not supported.
- [Webhooks](#webhooks) will not be sent if the Media upon which the comment or @mention appears was created by an account that is set to [private](https://www.facebook.com/help/instagram/448523408565555).

## Endpoints

The API consists of the following endpoints:

* [`GET /{ig-user-id}/tags`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/tags) — to get the media objects in which a Business or Creator Account has been tagged
* [`GET /{ig-user-id}?fields=mentioned_comment`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/mentioned_comment#reading) — to get data about a comment that an Business or Creator Account  has been @mentioned in
* [`GET /{ig-user-id}?fields=mentioned_media`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/mentioned_media#reading) — to get data about a media object on which a Business or Creator Account has been @mentioned in a caption
* [`POST /{ig-user-id}/mentions`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/mentions#creating) — to reply to a comment or media object caption that a Business or Creator Account has been @mentioned in by another Instagram user

Refer to each endpoint reference document for usage instructions.

## Webhooks

Subscribe to the `mentions` field to recieve [Instagram Webhooks](https://developers.facebook.com/documentation/instagram-platform/webhooks) notifications whenever an Instagram user mentions an Instagram Business or Creator Account. Note that we do not store Webhooks notification data, so if you set up a Webhook that listens for mentions, you should store any received data if you plan on using it later.

## Examples

### Listening for and Replying to Comment @Mentions

You can listen for comment @mentions and reply to any that meet your criteria:

1. Set up an [Instagram webhook](https://developers.facebook.com/documentation/instagram-platform/webhooks) that's subscribed to the `mentions` field.
1. Set up a script that can parse the Webhooks notifications and identify comment IDs.
1. Use the IDs to query the `GET /{ig-user-id}/mentioned_comment` endpoint to get more information about each comment.
1. Analyze the returned results to identify any comments that meet your criteria.
1. Use the `POST /{ig-user-id}/mentions` endpoint to [reply to those comments](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/mentions#creating).

The reply will appear as a sub-thread comment on the comment in which the Business or Creator Account was mentioned.

### Listening for and Replying to Caption @Mentions

You can listen for caption @mentions and reply to any that meet your criteria:

1. Set up an [Instagram webhook](https://developers.facebook.com/documentation/instagram-platform/webhooks) that's subscribed to the `mentions` field.
1. Set up a script that can parse the Webhooks notifications and identify media IDs.
1. Use the IDs to query the `GET /{ig-user-id}/mentioned_media` endpoint to get more information about each media object.
1. Analyze the returned results to identify media objects with captions that meet your criteria.
1. Use the `POST /{ig-user-id}/mentions` endpoint to [comment on those media objects](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/mentions#creating).


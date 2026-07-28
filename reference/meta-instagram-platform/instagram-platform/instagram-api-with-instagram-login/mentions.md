# Mentions



Identify captions, comments, and IG Media in which an Instagram Business or Creator's alias has been tagged or @mentioned.

## Requirements

This guide assumes you have read the [Instagram Platform Overview](https://developers.facebook.com/documentation/instagram-platform/overview) and implemented the needed components for using this API, such as a Meta login flow and a webhooks server to receive notifications.

You will need the following:

#### Access Level

* Advanced Access if your app serves Instagram Professional accounts you don't own or manage
* Standard Access if your app serves Instagram Professional accounts you own or manage and have added to your app in the App Dashboard

#### Base URL

All endpoints can be accessed via the `graph.instagram.com` host.

#### Endpoints

* [`GET /<IG_ID>/tags`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/tags) — to get the media objects in which a Business or Creator Account has been tagged
* [`POST /<IG_ID>/mentions`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/mentions#creating) — to reply to a comment or media object caption that a Business or Creator Account has been @mentioned in by another Instagram user

#### Permissions
* `instagram_business_basic`
* `instagram_business_manage_comments`

### Limitations

- Mentions on Stories are not supported.
- Commenting on photos in which you were tagged is not supported.
- [Webhooks](https://developers.facebook.com/documentation/instagram-platform/webhooks) will not be sent if the Media upon which the comment or @mention appears was created by an account that is set to [private](https://www.facebook.com/help/instagram/448523408565555).

## Listening for and Replying to @Mentions

You can listen for comment @mentions and reply to any that meet your criteria:

1. Set up a script that can parse the Webhooks notifications and identify comment IDs.
1. Use the IDs to query the `GET /<IG_ID>/tags` endpoint to get more information about each comment.
1. Analyze the returned results to identify any comments that meet your criteria.
1. Use the `POST /<IG_ID>/mentions` endpoint to reply to those comments or media objects.

# Version 6.0

**Released** February 3, 2020 | **Available until** May 5, 2022

In addition to the changes described below, we are [deprecating a number of endpoints](/docs/graph-api/changelog/2020-02-03-endpoint-deprecations) as part of our ongoing commitments to privacy and security. These deprecations apply to version 6.0+ immediately and will apply to all versions on May 5, 2020.

## Messenger

*This change applies to v6.0+*

[Webhook Event: `messages`](https://developers.facebook.com/docs/messenger-platform/reference/webhook-events/messages) - Adjusted the way attachments type `fallback` and `image` with a sticker are sent.

### Breaking Change

*This change applies to v6.0+ and will apply to all versions on June 30, 2020.*

`/{conversation-id}/messages` - This endpoint is being deprecated. For sending messages use the [Send API](https://developers.facebook.com/docs/messenger-platform/reference/send-api/).

## Page Public Metadata Access

*This change applies to all versions.*

We have introduced a new [reviewable feature](#app-review) named [Page Public Metadata Access](/docs/apps/review/feature#page-public-metadata-access). [Page Public Metadata Access](/docs/apps/review/feature#page-public-metadata-access) allows read-only access to the [Pages Search API](/docs/pages/searching)  as well as a [set of Page fields and edges](/docs/graph-api/reference/page#public-page-data) that would normally require the [Page Public Content Access](/docs/apps/review/feature#reference-PAGES_ACCESS) feature. Apps that have requested only these fields and edges on Pages in the past have been automatically approved for Page Public Metadata Access and will lose approval for Page Public Content Access on May 3, 2020.

Apps affected by this change will not lose any functionality and will not require any code changes.

## Pages

*This change applies to all versions.*

The `GET /{page-id}/upcoming_changes` endppoint has been deprecated.

## SDKs

[Facebook SDK for Android](/docs/android) v6.0 and [Facebook SDK for iOS](/docs/ios) v6.0 call version 6.0 of the Graph and Marketing APIs by default.

## User Node

*This change applies to v6.0+.*

The [`GET /{user-id}/promotable_domains`](/docs/graph-api/reference/user/promotable_domains) edge has been deprecated.

## Marketing API

**Released** February 3, 2020 | **Extended to** February 8, 2021

For Marketing API, v6.0, there are no new features or deprecations. We continue to encourage ads developers to migrate calls to version 6.0 in advance of the version 5.0 deprecation on September 28, 2020.

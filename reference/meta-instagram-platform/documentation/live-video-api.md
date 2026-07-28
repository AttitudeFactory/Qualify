# Live Video API


**Note:** The overlay_url field on the [GET /&lt;LIVE_VIDEO_ID&gt;](https://developers.facebook.com/docs/graph-api/reference/live-video#fields) endpoint has been removed for v24.0+. It will continue to return null for v23.0 and older requests.

The Live Video API from Meta shows you how to steam live video to Facebook, create backup streams, crosspost to other profiles or pages, interact with viewers, and more.

**Warning:** On June 10th, 2024, Meta is launching new requirements that must meet before an account can go live on Facebook. The new requirements are as follows:

- The Facebook account must be at least 60 days old

- The Facebook Page or [professional mode profile](https://www.facebook.com/business/help/2680340558863560) must have at least 100 followers

Visit our
Help Center to learn more about this change.

## Common Uses

- [Broadcasting](https://developers.facebook.com/documentation/live-video-api/guides/streaming) a live video stream on a User profile, Page, Group, or Event
- [Interacting](https://developers.facebook.com/documentation/live-video-api/interact-with-viewers) with live video broadcast audiences
- [Creating polls](https://developers.facebook.com/documentation/live-video-api/polls) on live video broadcasts

## Requirements

To use this API, your app must undergo [App Review](https://developers.facebook.com/docs/apps/review) for the following features and permissions.

Your app must produce a live RTMPS stream to be abe to stream to Facebook using the Live Video API.

### Features

* [Live Video API](https://developers.facebook.com/docs/apps/review/feature#reference-LIVE_VIDEOS)

### Permissions

Most endpoints require a mix of the following permissions. To determine which permissions you need, refer to the reference documents for each of the endpoints your app uses.

Publishing on a User

- [`publish_video`](https://developers.facebook.com/docs/facebook-login/permissions#publish_video)

Publishing on a Page

- [`pages_manage_posts`](https://developers.facebook.com/documentation/pages-api/overview#permissions)

- [`pages_read_engagement`](https://developers.facebook.com/documentation/pages-api/overview#permissions)

## Next Steps

Read our [Overview](https://developers.facebook.com/documentation/live-video-api/overview) to learn about the API&#039;s core concepts, then follow the steps in our [Getting Started](https://developers.facebook.com/documentation/live-video-api/overview) document to quickly create a broadcast on your own User profile.

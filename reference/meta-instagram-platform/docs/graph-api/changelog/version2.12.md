# Version 2.12

[Graph API](#gapi) | [Marketing API](#mapi)

Changelog entries are categorized in the following way:

* **New Features** — New products or services, including new nodes, edges, and fields.
* **Changes** — Changes to existing products or services (not including **Deprecations**).
* **Deprecations** — Existing products or services that are being removed.
* **90-Day Breaking Changes** — Changes and deprecations that will take effect 90 days after the version release date.

**New Features**, **Changes**, and **Deprecations** only affect this version. **90-Day Breaking Changes** affect all versions.

[Breaking Changes](/docs/graph-api/changelog/breaking-changes) are not included here since they are not tied to specific releases.

---

## Graph API

**Released** January 30, 2018 | **Available until** May 5, 2020 | [Blog Post](/blog/post/2018/01/30/graph-api-v2.12/)

* [New Features](#gapi-new)
* [Changes](#gapi-change)
* [Deprecations](#gapi-deprecate)
* [90-Day Breaking Changes](#gapi-90)

---

### New Features

No new features.

---

### Changes

* [Webhooks](#gapi-change-webhooks)

#### Webhooks

* **Page Topic** — `sender_name` and `sender_id` have been replaced with a single `from` property in Mentions for Workplace subscriptions.

---

### Deprecations

No deprecations.

---

### 90-Day Breaking Changes

* [Events](#gapi-90-events)
* [Groups](#gapi-90-groups)
* [Pages](#gapi-90-pages)
* [Videos](#gapi-90-videos)

#### Events

* `GET /event` — `GET` operations on the following fields now require an access token of an Admin of the Event.

  + `is_draft`
  + `can_guests_invite`
  + `guest_list_enabled`
  + `attending`
  + `interested`
  + `declined`
  + `maybe`
  + `noreply`
  + `roles`
  + `ticket_tiers`
  + `feed`
  + `posts`
  + `comments`
  + `photos`
  + `live_videos`

  In addition, the following fields have been deprecated:

  + `is_viewer_admin`
  + `can_viewer_post`

* `POST /event` — `POST` operations now require an access token of an Admin of the Event.

* **Event-Owned Objects** — `GET` operations on Event-owned objects now require an access token of an Admin of the Event. This affects the following nodes:

  + `GET /post`
  + `GET /comment`
  + `GET /photo`
  + `GET /live_video`

#### Groups

* `GET /group` — `GET` operations on the following fields and edges now require an access token of an Admin of the Group:

  **Fields**

  + `member_request_count`
  + `owner`
  + `privacy`
  + `updated_time`

  **Edges**

  + `GET /albums`\*
  + `GET /admins`
  + `GET /docs`\*
  + `GET /events`\*
  + `GET /feed`\*
  + `GET /files`
  + `GET /former_members`
  + `GET /groups`\*
  + `GET /links`\*
  + `GET /live_videos`\*
  + `GET /member_requests`
  + `GET /members`
  + `GET /moderators`
  + `GET /posts`\*
  + `GET /tagged`
  + `GET /videos`\*

  In the coming weeks, edges marked with an asterisk (\*) will once again allow requests from non-Admin Group members. However, responses will not include User information unless the request is made with an access token of an Admin of the Group.

* `POST /group` — `POST` operations now require an access token of an Admin of the Group.

* **Group-Owned Objects** — `GET` operations on Group-owned objects now require an access token of an Admin of the Group. This affects the following nodes:

  + `GET /album`
  + `GET /comment`
  + `GET /doc`
  + `GET /event`
  + `GET /live_video`
  + `GET /photo`
  + `GET /post`

#### Pages

* **Impressions Reporting** — Redefining the use of *organic* from *not paid*, *not viral* to *not paid* and introducing a new sets of metrics called *nonviral* which will match the old definition of *organic* from and earlier versions. The new relationship:

  + total impressions = paid impressions + organic impressions
  + organic impressions = viral impressions + nonviral impressions

This affects the following endpoints:

* `GET /page/insights`
* `GET /post/insights`

* **Insights** — Changing the results returned by **like** and **unlike** metrics.

  The following **like** metrics:

  + `/page/insights/page_fans_by_like_source_unique`
  + `/page/insights/page_fans_by_like_source`

  now return:

  + `Ads`
  + `Other`
  + `Page Suggestions`
  + `News Feed`
  + `Your Page`
  + `Restored Likes from Reactivated Accounts`
  + `Search`

  The following **unlike** metrics:

  + `/page/insights/page_fans_by_unlike_source_unique`
  + `/page/insights/page_fans_by_unlike_source`

  now return:

  + `Deactivated or Memorialized Account Removals`
  + `Suspicious Account Removals`
  + `Unlikes from Page, Posts, or News Feed`
  + `Unlikes from Search`
  + `Underage Account Removals`
  + `Unlikes from Page Suggestions`
  + `Other`

#### Videos

* **Page-owned videos** — The `source` field will no longer be returned for Page-owned videos unless the User making the request has a role on the owning Page. This affects the following endpoints:

  + `GET /video`
  + `GET /post`
  + `GET /page/videos`
  + `GET /page/posts`
  + `GET /page/feed`

## Marketing API

**Released** January 30, 2018 | **Available Until** Aug 7, 2018 | [Blog Post](/ads/blog/post/2018/01/30/graph-api-212-release/)

Please refer to [the blog post](/ads/blog/post/2018/01/30/graph-api-212-release/) for a summary of changes.

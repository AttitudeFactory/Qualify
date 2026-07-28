# Version 3.1

**Released** July 26, 2018 | **Available until** October 27, 2020 | [Blog Post](/blog/post/2018/07/26/introducing-graph-api-v3.1-marketing-api-v3.1-graph-api-explorer-beta/)

* [General](#general)
* [Live API](#live-api)
* [Marketing API](#marketing-api)
* [Messenger Platform](#messenger-platform)
* [Mutual Friends API](#mutual-friends-api)
* [Pages API](#pages-api)
* [Webhooks](#webhooks)

## General

*These changes apply to v3.1+, and will apply to all versions on October 24, 2018.*

All Graph API endpoints now return all empty structs as `{}`, and all empty lists as `[]`.

## Live API

*These changes apply to v3.1+, and will apply to all versions on October 24, 2018.*

The `type` parameter is deprecated for the following edges. It has been replaced with a new `source` parameter.

* `/event/live_videos`
* `/group/live_videos`
* `/official_events/live_videos`
* `/page/live_videos`
* `/user/live_videos`

The new `source` parameter can accept one of two possible values: `target` and `owner`. Querying a node's `/live_videos` edge with `source=target` returns live videos **streamed to** that node, while querying for `source=owner` returns live videos **streamed by** that node.

Event and Group nodes only support `target` queries, and some `target` queries may fail if you do not have permission to view the targeted node.

## Marketing API

**Released** July 26, 2018 | **Available Until** May 14, 2019 | [Blog Post](/ads/blog/post/2018/07/26/marketing-api-v31/)

### Ads Management

* **Behavior-based Targeting Categories** - We deprecated some behavior-based targeting options used in `behaviors`. If you try to create ads with one of these categories, you will get the error `The category you selected is no longer available.` To check on valid categories available for targeting, use [Targeting Search](/docs/marketing-api/targeting-search).
* **Deprecated** `PAGE_ENGAGEMENT` **as** `optimization_goal` - We deprecated `PAGE_ENGAGEMENT` as an `optimization_goal` for ad campaigns. As of v3.1 you can no longer create, update or duplicate ad campaigns with `optimization_goal` set to `PAGE_ENGAGEMENT`. If you have existing ad campaigns created prior to v3.1, you can still run these campaigns with this setting. You can also still use `PAGE_ENGAGEMENT` as an Insights API breakdown for data on existing ad campaigns using this `optimization_goal`.
* **Deprecated Single-Image Page Like Ads without Post** - As of v3.1 you can no longer create single-image Page Like Ads without a page post. Instead you should create a Page Like Ad with a post, see [Creative, Placement and Preview, Creating Page Like Ads](/docs/marketing-api/buying-api/ad-units#like).

* **No Lead Ads Retrieval via Webhooks for Dev Tier** - We will stop sending data collected in Lead Ads forms via webhooks to apps in [*Dev Mode*](/ads/blog/post/2018/07/02/marketing-api-tier-simplification/). We begin enforcing this change on February 1, 2019.

  + If you subscribe to updates in v3.1, we will not send any unless your app is in production and in *Live Mode*.
  + If you create a new app after v3.1 is available, we will not send any updates unless your app is in production and in *Live Mode*.
  + If you have an existing app, it will need to be in Live Mode by February 1, 2019. Until that date, you will continue receiving updates in *Dev Mode*.

  For more information about Marketing API access tiers and app modes, see [New Structure for Marketing API Access](/ads/blog/post/2018/07/02/marketing-api-tier-simplification/) and [Marketing API, Access and Authentication](https://developers.facebook.com/docs/marketing-api/access).

### Ads Insights and Measurement

* We renamed `cost_per_store_visit` and `store_visits` for the Insights API to `cost_per_store_visit_actions` and `store_visit_actions`. This impacts:

  + `GET {adaccount-id}/insights`,
  + `GET {campaign-id}/insights`,
  + `GET {adset-id}/insights`,
  + `GET {ad-id}/insights`,
  + `POST {adaccount-id}/insights`,
  + `POST {campaign-id}/insights`,
  + `POST {adset-id}/insights` and
  + `POST {ad-id}/insights`.

  For information about the newly named metrics, see [Store Visits, Measurement](/docs/marketing-api/guides/dynamic-ad/store-visits#measurement). Note that the Store Visits API and related documentation are available on a limited basis. Contact your Facebook Representative for access.

### Business Manager API

In v3.1 we introduce the new concept of **task-based permissions** to substitute for the current role-based permission. This affects access to ad accounts managed by Business Manager API and Pages. Role-based access to ad accounts and Pages is still available but will be deprecated in the future. This impacts the following roles and provides the equivalent tasks for ad accounts:

Role | Tasks | Description || `ADMIN` | `['MANAGE', 'ADVERTISE', 'ANALYZE']` | Manage all aspects of ad campaigns, reporting, billing and ad account permissions. |
| `GENERAL_USER` | `['ADVERTISE', 'ANALYZE']` | Create ads using the funding source associated with the ad account. Run reports. |
| `GENERAL_USER` | `['ANALYZE']` | Run reports. |

This replaces the following roles in Business Manager API with these tasks:

Role | Tasks || `MANAGER` | `['MANAGE', 'CREATE_CONTENT', 'MODERATE', 'ADVERTISE', 'ANALYZE']` |
| `CONTENT_CREATOR` | `['CREATE_CONTENT', 'MODERATE', 'ADVERTISE', 'ANALYZE']` |
| `MODERATOR` | `['MODERATE', 'ADVERTISE', 'ANALYZE']` |
| `ADVERTISER` | `['ADVERTISE', 'ANALYZE']` |
| `INSIGHTS_ANALYST` | `['ANALYZE']` |

For management of Facebook Pixel, this impacts these roles and introduces new tasks:

Role | Tasks || `PIXEL_EDITOR` | `['EDIT', 'ANALYZE']` |
| `PIXEL_ANALYST` | `['ANALYZE']` |

As part of this change we will deprecate the following Business Management API fields and replace them with the following:

Area | Deprecated | New Field || `GET {adaccount-id}/users` | `permissions`, `role` | `tasks` |
| `POST {adaccount-id}/users` | `role`, `uidRoles`, `emailRoles` | `tasks` |
| `GET {user-id}/adaccounts` | `permissions`, `role` | `tasks` |
| `GET {user-id}/assigned_ad_accounts` | `role`, `permitted_role` | `tasks`, `permitted_tasks` |
| `GET {user-id}/assigned_pages` | `role`, `permitted_role` | `tasks`, `permitted_tasks` |
| `GET {adaccount-id}/assigned_users` | `role`, `permitted_role` | `tasks`, `permitted_tasks` |
| `POST {adaccount-id}/assigned_users` | `role` | `tasks` |
| `GET {page-id}/assigned_users` | `role`, `permitted_role` | `tasks`, `permitted_tasks` |
| `POST {page-id}/assigned_users` | `role` | `tasks` |
| `GET {fb-pixel-id}/assigned_users` | `role`, `permitted_role` | `tasks`, `permitted_tasks` |
| `GET {adaccount-id}/userpermissions` | `role` | `tasks` |
| `POST {adaccount-id}/userpermissions` | `role` | `tasks` |
| `GET {page-id}/userpermissions` | `role` | `tasks` |
| `POST {page-id}/userpermissions` | `role` | `tasks` |
| `GET {business-id}/client_ad_accounts` | `permitted_role` | `permitted_tasks` |
| `POST {business-id}/client_ad_accounts` | `permitted_role` | `permitted_tasks` |
| `GET {business-id}/client_pages` | `permitted_role` | `permitted_tasks` |
| `POST {business-id}/client_pages` | `permitted_role` | `permitted_tasks` |
| `GET {business-id}/client_pixels` | `permitted_role` | `permitted_tasks` |
| `GET {adaccount-id}/agencies` | `permitted_role` | `permitted_tasks` |
| `POST {adaccount-id}/agencies` | `permitted_role` | `permitted_tasks` |
| `GET {page-id}/agencies` | `permitted_role` | `permitted_tasks` |
| `POST {page-id}/agencies` | `permitted_role` | `permitted_tasks` |
| `GET {business-id}/pending_client_pages` | `permitted_role` | `permitted_tasks` |
| `GET {business-id}/pending_client_ad_accounts` | `permitted_role` | `permitted_tasks` |

This new design also impacts Pages API, see [Graph API 3.1, Pages API, Breaking Changes](/docs/graph-api/changelog/version3.1#pages-api). For Business Manager API documentation, see:

* [Business Manager API, Assets](/docs/marketing-api/businessmanager/assets)
* [Business Manager API, System User Permissions](/docs/marketing-api/businessmanager/systemuser#permissions)

## Messenger Platform

*For apps created before July 26, 2018, these changes take effect on January 8, 2019. For apps created after July 26, 2018, these changes take effect immediately.*

The [User Profile API](/docs/messenger-platform/identity/user-profile) now only returns `first_name`, `last_name`, and `profile_pic` fields by default. [Additional fields](/docs/messenger-platform/identity/user-profile#fields) now require product review through the Messenger Platform tab of the App Dashboard.

The `last_ad_referral` and `is_payment_enabled` fields are deprecated, and will be removed from the API on October 30, 2018.

## Mutual Friends API

*These changes apply to v3.1+, and will apply to all versions on October 24, 2018.*

The Mutual Friends API was deprecated on [April 4, 2018](https://developers.facebook.com/docs/graph-api/changelog/breaking-changes#friends-4-4), and the endpoints below started returning empty data sets. The endpoints are now fully deprecated and will return an error.

* `/user-context/all_mutual_friends`
* `/user-context/mutual_friends`
* `/user-context/three_degree_mutual_friends`

## Pages API

### Permissions

*The following changes apply to v3.1+, and will apply to all versions on February 1, 2019.*

The [`pages_manage_cta` permission](https://developers.facebook.com/docs/facebook-login/permissions#reference-pages_manage_cta) now requires [App Review](https://developers.facebook.com/docs/apps/review) for all `POST` and `DELETE` requests. Apps created before July 26, 2018 can continue to use this permission but must submit for review before February 1, 2019 to continue to use `pages_manage_cta`.

### Page Roles

*The following changes apply to v3.1+.*

[Page roles](/docs/pages/access-tokens#roles) are undergoing deprecation and are being replaced with [Page tasks](/docs/pages/access-tokens#page-tasks). Instead of granting a User a role on a Page, you now must grant the User their equivalent in tasks instead.

Role | Equivalent Tasks || `Admin` | `ADVERTISE`, `ANALYZE`, `CREATE_CONTENT`, `MANAGE`, `MODERATE` |
| `Advertiser` | `ADVERTISE`, `ANALYZE` |
| `Analyst` | `ANALYZE` |
| `Editor` | `ADVERTISE`, `ANALYZE`, `CREATE_CONTENT`, `MODERATE` |
| `Moderator` | `ADVERTISE`, `ANALYZE`, `MODERATE` |

Until role-based permissions are completely replaced by task-based permissions, when granting tasks via `/page/roles`, you must grant all of a role's equivalent tasks or the `POST` operation will fail.

To support these changes, the `perms` and `role` fields have been deprecated and replaced with a new `tasks` field. This affects the following edges:

* `/me/accounts`
* `/page/roles`
* `/user/accounts`

Please refer to the [Marketing API changelog](#marketing-api) to see how these changes affect the Marketing API and Business Manager API.

## Webhooks

*These changes apply to v3.1+, and will apply to all versions on October 24, 2018.*

The following User webhook fields are deprecated:

* `pic_big_with_logo`
* `pic_small_with_logo`
* `pic_square_with_logo`
* `pic_with_logo`

The following User webhook fields now use HTTPS URLs instead of HTTP.

* `pic`
* `pic_big`
* `pic_small`
* `pic_square`
* `picture`

In addition, the URLs for these fields will expire — *this affects all API versions, immediately.*
